"""Routes for LINE-mediated manual PromptPay slip verification.

- ``POST /v1/integrations/line/webhook`` — public, LINE-signature-verified.
- ``GET  /v1/billing/slips`` + verify/reject/image — admin slip review.
- ``GET  /v1/billing/payment-config`` — exposes the active provider + LINE deep
  link so the frontend doesn't duplicate server configuration.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from egp_api.auth import request_has_support_role, require_admin_role
from egp_api.services.line_integration import parse_message_events, verify_line_signature
from egp_api.services.line_slip_service import LineSlipService

router = APIRouter(tags=["line"])


class LineWebhookResponse(BaseModel):
    status: str
    text_events: int
    image_events: int
    slips_created: int
    slips_matched: int


class PaymentSlipResponse(BaseModel):
    id: str
    tenant_id: str | None
    billing_record_id: str | None
    payment_request_id: str | None
    line_user_id: str
    reference_code_match: str | None
    image_object_key: str | None
    verification_status: str
    verified_by_user_id: str | None
    verified_at: str | None
    verification_notes: str | None
    received_at: str
    created_at: str
    updated_at: str


class PaymentSlipListResponse(BaseModel):
    slips: list[PaymentSlipResponse]


class SlipActionRequest(BaseModel):
    note: str | None = None


class PaymentConfigResponse(BaseModel):
    provider: str
    line_add_url: str | None


def _slip_service(request: Request) -> LineSlipService:
    service = getattr(request.app.state, "line_slip_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="line integration not configured")
    return service


def _serialize_slip(slip) -> PaymentSlipResponse:
    return PaymentSlipResponse(
        id=slip.id,
        tenant_id=slip.tenant_id,
        billing_record_id=slip.billing_record_id,
        payment_request_id=slip.payment_request_id,
        line_user_id=slip.line_user_id,
        reference_code_match=slip.reference_code_match,
        image_object_key=slip.image_object_key,
        verification_status=slip.verification_status,
        verified_by_user_id=slip.verified_by_user_id,
        verified_at=slip.verified_at,
        verification_notes=slip.verification_notes,
        received_at=slip.received_at,
        created_at=slip.created_at,
        updated_at=slip.updated_at,
    )


def _admin_user_id_from_request(request: Request) -> str | None:
    auth_context = getattr(request.state, "auth_context", None)
    subject = getattr(auth_context, "subject", None) if auth_context is not None else None
    if not subject:
        return None
    try:
        return str(UUID(str(subject).strip()))
    except (ValueError, AttributeError):
        return None


def _is_operator(request: Request) -> bool:
    """Operator scope = auth disabled (dev) or the cross-tenant support role.

    The LINE OA is operator-level infrastructure, so only the operator triages
    the global slip inbox (including unmatched slips with no tenant).
    """
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is None:
        return True
    return request_has_support_role(request)


def _caller_tenant_id(request: Request) -> str | None:
    auth_context = getattr(request.state, "auth_context", None)
    return getattr(auth_context, "tenant_id", None) if auth_context is not None else None


def _authorize_slip(request: Request, service: LineSlipService, slip_id: str):
    """Load a slip and enforce that a non-operator admin only touches their own
    tenant's matched slips."""
    slip = service.get_slip(slip_id)
    if slip is None:
        raise HTTPException(status_code=404, detail="slip not found")
    if _is_operator(request):
        return slip
    caller_tenant = _caller_tenant_id(request)
    if slip.tenant_id is None or slip.tenant_id != caller_tenant:
        raise HTTPException(status_code=403, detail="tenant mismatch")
    return slip


@router.post("/v1/integrations/line/webhook", response_model=LineWebhookResponse)
async def handle_line_webhook(request: Request) -> LineWebhookResponse:
    service = _slip_service(request)
    channel_secret = getattr(request.app.state, "line_channel_secret", None)
    if not channel_secret:
        raise HTTPException(status_code=503, detail="line channel secret not configured")
    body_bytes = await request.body()
    signature = request.headers.get("x-line-signature")
    if not verify_line_signature(
        channel_secret=channel_secret, raw_body=body_bytes, signature_header=signature
    ):
        raise HTTPException(status_code=400, detail="invalid line signature")
    try:
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid json payload") from exc
    summary = service.handle_webhook_events(parse_message_events(payload))
    return LineWebhookResponse(
        status="ok",
        text_events=summary.text_events,
        image_events=summary.image_events,
        slips_created=summary.slips_created,
        slips_matched=summary.slips_matched,
    )


@router.get("/v1/billing/slips", response_model=PaymentSlipListResponse)
def list_payment_slips(
    request: Request,
    slip_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> PaymentSlipListResponse:
    require_admin_role(request)
    service = _slip_service(request)
    # Operators see the whole inbox (incl. unmatched); a tenant admin only sees
    # slips already matched to their own tenant.
    tenant_filter = None if _is_operator(request) else _caller_tenant_id(request)
    slips = service.list_slips(status=slip_status, tenant_id=tenant_filter, limit=limit)
    return PaymentSlipListResponse(slips=[_serialize_slip(slip) for slip in slips])


@router.post("/v1/billing/slips/{slip_id}/verify", response_model=PaymentSlipResponse)
def verify_payment_slip(
    slip_id: str, payload: SlipActionRequest, request: Request
) -> PaymentSlipResponse:
    require_admin_role(request)
    service = _slip_service(request)
    _authorize_slip(request, service, slip_id)
    try:
        slip = service.verify_slip(
            slip_id=slip_id,
            admin_user_id=_admin_user_id_from_request(request),
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="slip not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize_slip(slip)


@router.post("/v1/billing/slips/{slip_id}/reject", response_model=PaymentSlipResponse)
def reject_payment_slip(
    slip_id: str, payload: SlipActionRequest, request: Request
) -> PaymentSlipResponse:
    require_admin_role(request)
    service = _slip_service(request)
    _authorize_slip(request, service, slip_id)
    try:
        slip = service.reject_slip(
            slip_id=slip_id,
            admin_user_id=_admin_user_id_from_request(request),
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="slip not found") from exc
    return _serialize_slip(slip)


@router.get("/v1/billing/slips/{slip_id}/image")
def get_payment_slip_image(slip_id: str, request: Request) -> Response:
    require_admin_role(request)
    service = _slip_service(request)
    _authorize_slip(request, service, slip_id)
    try:
        data, content_type = service.get_slip_image(slip_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="slip not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="slip image not available") from exc
    return Response(content=data, media_type=content_type or "application/octet-stream")


@router.get("/v1/billing/payment-config", response_model=PaymentConfigResponse)
def get_payment_config(request: Request) -> PaymentConfigResponse:
    provider = getattr(request.app.state, "payment_provider_name", "") or "mock_promptpay"
    return PaymentConfigResponse(
        provider=provider,
        line_add_url=getattr(request.app.state, "line_add_url", None),
    )
