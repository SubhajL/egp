"""Webhook subscription routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import AnyHttpUrl, BaseModel, Field

from egp_api.auth import require_admin_role, resolve_request_tenant_id
from egp_api.services.webhook_service import WebhookList, WebhookService
from egp_shared_types.enums import NotificationType


router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


class WebhookResponse(BaseModel):
    id: str
    name: str
    url: str
    notification_types: list[str]
    is_active: bool
    created_at: str
    updated_at: str
    last_delivery_status: str | None
    last_delivery_attempted_at: str | None
    last_delivered_at: str | None
    last_response_status_code: int | None


class WebhookListResponse(BaseModel):
    webhooks: list[WebhookResponse]


class CreateWebhookRequest(BaseModel):
    tenant_id: str | None = None
    name: str = Field(min_length=1)
    url: AnyHttpUrl
    notification_types: list[NotificationType] = Field(min_length=1)
    signing_secret: str = Field(min_length=8)


def _service_from_request(request: Request) -> WebhookService:
    return request.app.state.webhook_service


def _actor_subject_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None and getattr(auth_context, "subject", None):
        return str(auth_context.subject)
    return "manual-operator"


def _serialize_list(result: WebhookList) -> WebhookListResponse:
    return WebhookListResponse(
        webhooks=[WebhookResponse(**asdict(webhook)) for webhook in result.webhooks]
    )


@router.get("", response_model=WebhookListResponse)
def list_webhooks(request: Request, tenant_id: str | None = None) -> WebhookListResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        result = service.list_webhooks(tenant_id=resolved_tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return _serialize_list(result)


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(request: Request, payload: CreateWebhookRequest) -> WebhookResponse:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        created = service.create_webhook(
            tenant_id=resolved_tenant_id,
            name=payload.name,
            url=str(payload.url),
            notification_types=payload.notification_types,
            signing_secret=payload.signing_secret,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return WebhookResponse(**asdict(created))


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(
    webhook_id: str,
    request: Request,
    tenant_id: str | None = None,
) -> None:
    require_admin_role(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    try:
        service.delete_webhook(
            tenant_id=resolved_tenant_id,
            webhook_id=webhook_id,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="webhook not found") from exc
