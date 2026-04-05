"""Billing routes for manual records and reconciliation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from egp_api.auth import resolve_request_tenant_id
from egp_api.services.billing_service import BillingService
from egp_db.repositories.billing_repo import (
    BillingEventRecord,
    BillingPage,
    BillingPaymentRecord,
    BillingPaymentRequestRecord,
    BillingRecordDetail,
    BillingRecordRecord,
    BillingSubscriptionRecord,
    BillingSummary,
)
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
    BillingPaymentStatus,
    BillingRecordStatus,
)


router = APIRouter(prefix="/v1/billing", tags=["billing"])


class BillingRecordResponse(BaseModel):
    id: str
    tenant_id: str
    record_number: str
    plan_code: str
    status: str
    billing_period_start: str
    billing_period_end: str
    due_at: str | None
    issued_at: str | None
    paid_at: str | None
    currency: str
    amount_due: str
    reconciled_total: str
    outstanding_balance: str
    notes: str | None
    created_at: str
    updated_at: str


class BillingPaymentResponse(BaseModel):
    id: str
    billing_record_id: str
    payment_method: str
    payment_status: str
    amount: str
    currency: str
    reference_code: str | None
    received_at: str
    recorded_at: str
    reconciled_at: str | None
    note: str | None
    recorded_by: str | None
    reconciled_by: str | None


class BillingEventResponse(BaseModel):
    id: str
    billing_record_id: str
    payment_id: str | None
    event_type: str
    actor_subject: str | None
    note: str | None
    from_status: str | None
    to_status: str | None
    created_at: str


class BillingPaymentRequestResponse(BaseModel):
    id: str
    billing_record_id: str
    provider: str
    payment_method: str
    status: str
    provider_reference: str
    payment_url: str
    qr_payload: str
    qr_svg: str
    amount: str
    currency: str
    expires_at: str | None
    settled_at: str | None
    created_at: str
    updated_at: str


class BillingSubscriptionResponse(BaseModel):
    id: str
    tenant_id: str
    billing_record_id: str
    plan_code: str
    subscription_status: str
    billing_period_start: str
    billing_period_end: str
    keyword_limit: int | None
    activated_at: str
    activated_by_payment_id: str | None
    created_at: str
    updated_at: str


class BillingRecordDetailResponse(BaseModel):
    record: BillingRecordResponse
    payment_requests: list[BillingPaymentRequestResponse]
    payments: list[BillingPaymentResponse]
    events: list[BillingEventResponse]
    subscription: BillingSubscriptionResponse | None


class BillingSummaryResponse(BaseModel):
    open_records: int
    awaiting_reconciliation: int
    outstanding_amount: str
    collected_amount: str


class BillingListResponse(BaseModel):
    records: list[BillingRecordDetailResponse]
    total: int
    limit: int
    offset: int
    summary: BillingSummaryResponse


class BillingPlanResponse(BaseModel):
    code: str
    label: str
    description: str
    currency: str
    amount_due: str
    billing_interval: str
    keyword_limit: int
    duration_days: int | None
    duration_months: int | None


class BillingPlansResponse(BaseModel):
    plans: list[BillingPlanResponse]


class CreateBillingRecordRequest(BaseModel):
    tenant_id: str | None = None
    record_number: str = Field(min_length=1)
    plan_code: str = Field(min_length=1)
    status: BillingRecordStatus = BillingRecordStatus.AWAITING_PAYMENT
    billing_period_start: str = Field(min_length=1)
    billing_period_end: str | None = None
    due_at: str | None = None
    issued_at: str | None = None
    amount_due: str | None = None
    currency: str | None = None
    notes: str | None = None


class CreateBillingPaymentRequest(BaseModel):
    tenant_id: str | None = None
    payment_method: BillingPaymentMethod
    amount: str = Field(min_length=1)
    currency: str = Field(default="THB", min_length=1)
    reference_code: str | None = None
    received_at: str = Field(min_length=1)
    note: str | None = None


class ReconcileBillingPaymentRequest(BaseModel):
    tenant_id: str | None = None
    status: BillingPaymentStatus
    note: str | None = None


class TransitionBillingRecordRequest(BaseModel):
    tenant_id: str | None = None
    status: BillingRecordStatus
    note: str | None = None


class CreateBillingPaymentRequestRequest(BaseModel):
    tenant_id: str | None = None
    provider: BillingPaymentProvider = BillingPaymentProvider.MOCK_PROMPTPAY
    expires_in_minutes: int = Field(default=30, ge=1, le=1440)


class PaymentRequestCallbackRequest(BaseModel):
    tenant_id: str | None = None
    provider_event_id: str = Field(min_length=1)
    status: BillingPaymentRequestStatus
    amount: str = Field(min_length=1)
    currency: str = Field(default="THB", min_length=1)
    occurred_at: str = Field(min_length=1)
    reference_code: str | None = None


def _service_from_request(request: Request) -> BillingService:
    return request.app.state.billing_service


def _actor_subject_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None and getattr(auth_context, "subject", None):
        return str(auth_context.subject)
    return "manual-operator"


def _require_payment_callback_secret(request: Request) -> None:
    configured_secret = getattr(request.app.state, "payment_callback_secret", None)
    if configured_secret:
        header_secret = request.headers.get("x-egp-payment-callback-secret", "").strip()
        if header_secret != configured_secret:
            raise HTTPException(status_code=401, detail="invalid payment callback secret")
        return
    if getattr(request.app.state, "auth_required", False):
        raise HTTPException(status_code=503, detail="payment callback secret not configured")


def _serialize_record(record: BillingRecordRecord) -> BillingRecordResponse:
    return BillingRecordResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        record_number=record.record_number,
        plan_code=record.plan_code,
        status=record.status.value,
        billing_period_start=record.billing_period_start,
        billing_period_end=record.billing_period_end,
        due_at=record.due_at,
        issued_at=record.issued_at,
        paid_at=record.paid_at,
        currency=record.currency,
        amount_due=record.amount_due,
        reconciled_total=record.reconciled_total,
        outstanding_balance=record.outstanding_balance,
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _serialize_payment(payment: BillingPaymentRecord) -> BillingPaymentResponse:
    return BillingPaymentResponse(
        id=payment.id,
        billing_record_id=payment.billing_record_id,
        payment_method=payment.payment_method.value,
        payment_status=payment.payment_status.value,
        amount=payment.amount,
        currency=payment.currency,
        reference_code=payment.reference_code,
        received_at=payment.received_at,
        recorded_at=payment.recorded_at,
        reconciled_at=payment.reconciled_at,
        note=payment.note,
        recorded_by=payment.recorded_by,
        reconciled_by=payment.reconciled_by,
    )


def _serialize_event(event: BillingEventRecord) -> BillingEventResponse:
    return BillingEventResponse(
        id=event.id,
        billing_record_id=event.billing_record_id,
        payment_id=event.payment_id,
        event_type=event.event_type.value,
        actor_subject=event.actor_subject,
        note=event.note,
        from_status=event.from_status,
        to_status=event.to_status,
        created_at=event.created_at,
    )


def _serialize_payment_request(
    payment_request: BillingPaymentRequestRecord,
) -> BillingPaymentRequestResponse:
    return BillingPaymentRequestResponse(
        id=payment_request.id,
        billing_record_id=payment_request.billing_record_id,
        provider=payment_request.provider.value,
        payment_method=payment_request.payment_method.value,
        status=payment_request.status.value,
        provider_reference=payment_request.provider_reference,
        payment_url=payment_request.payment_url,
        qr_payload=payment_request.qr_payload,
        qr_svg=payment_request.qr_svg,
        amount=payment_request.amount,
        currency=payment_request.currency,
        expires_at=payment_request.expires_at,
        settled_at=payment_request.settled_at,
        created_at=payment_request.created_at,
        updated_at=payment_request.updated_at,
    )


def _serialize_subscription(
    subscription: BillingSubscriptionRecord,
) -> BillingSubscriptionResponse:
    return BillingSubscriptionResponse(
        id=subscription.id,
        tenant_id=subscription.tenant_id,
        billing_record_id=subscription.billing_record_id,
        plan_code=subscription.plan_code,
        subscription_status=subscription.subscription_status.value,
        billing_period_start=subscription.billing_period_start,
        billing_period_end=subscription.billing_period_end,
        keyword_limit=subscription.keyword_limit,
        activated_at=subscription.activated_at,
        activated_by_payment_id=subscription.activated_by_payment_id,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
    )


def _serialize_detail(detail: BillingRecordDetail) -> BillingRecordDetailResponse:
    return BillingRecordDetailResponse(
        record=_serialize_record(detail.record),
        payment_requests=[
            _serialize_payment_request(payment_request)
            for payment_request in detail.payment_requests
        ],
        payments=[_serialize_payment(payment) for payment in detail.payments],
        events=[_serialize_event(event) for event in detail.events],
        subscription=(
            _serialize_subscription(detail.subscription)
            if detail.subscription is not None
            else None
        ),
    )


def _serialize_summary(summary: BillingSummary) -> BillingSummaryResponse:
    return BillingSummaryResponse(
        open_records=summary.open_records,
        awaiting_reconciliation=summary.awaiting_reconciliation,
        outstanding_amount=summary.outstanding_amount,
        collected_amount=summary.collected_amount,
    )


def _serialize_page(page: BillingPage) -> BillingListResponse:
    return BillingListResponse(
        records=[_serialize_detail(detail) for detail in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        summary=_serialize_summary(page.summary),
    )


@router.get("/plans", response_model=BillingPlansResponse)
def list_billing_plans(request: Request) -> BillingPlansResponse:
    service = _service_from_request(request)
    return BillingPlansResponse(
        plans=[
            BillingPlanResponse(
                code=plan.code,
                label=plan.label,
                description=plan.description,
                currency=plan.currency,
                amount_due=plan.amount_due,
                billing_interval=plan.billing_interval,
                keyword_limit=plan.keyword_limit,
                duration_days=plan.duration_days,
                duration_months=plan.duration_months,
            )
            for plan in service.list_plans()
        ]
    )


@router.get("/records", response_model=BillingListResponse)
def list_billing_records(
    request: Request,
    tenant_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BillingListResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, tenant_id)
    return _serialize_page(
        service.list_snapshot(tenant_id=resolved_tenant_id, limit=limit, offset=offset)
    )


@router.post("/records", response_model=BillingRecordDetailResponse)
def create_billing_record(
    payload: CreateBillingRecordRequest,
    request: Request,
    response: Response,
) -> BillingRecordDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        detail = service.create_record(
            tenant_id=resolved_tenant_id,
            record_number=payload.record_number,
            plan_code=payload.plan_code,
            status=payload.status,
            billing_period_start=payload.billing_period_start,
            billing_period_end=payload.billing_period_end,
            due_at=payload.due_at,
            issued_at=payload.issued_at,
            amount_due=payload.amount_due,
            currency=payload.currency,
            notes=payload.notes,
            actor_subject=_actor_subject_from_request(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED
    return _serialize_detail(detail)


@router.post("/records/{record_id}/transition", response_model=BillingRecordDetailResponse)
def transition_billing_record(
    record_id: str,
    payload: TransitionBillingRecordRequest,
    request: Request,
) -> BillingRecordDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        detail = service.transition_record(
            tenant_id=resolved_tenant_id,
            billing_record_id=record_id,
            status=payload.status,
            note=payload.note,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="billing record not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="billing record not found for tenant") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_detail(detail)


@router.post("/records/{record_id}/payments", response_model=BillingPaymentResponse)
def create_billing_payment(
    record_id: str,
    payload: CreateBillingPaymentRequest,
    request: Request,
    response: Response,
) -> BillingPaymentResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        payment = service.record_payment(
            tenant_id=resolved_tenant_id,
            billing_record_id=record_id,
            payment_method=payload.payment_method,
            amount=payload.amount,
            currency=payload.currency,
            reference_code=payload.reference_code,
            received_at=payload.received_at,
            note=payload.note,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="billing record not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="billing record not found for tenant") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED
    return _serialize_payment(payment)


@router.post("/records/{record_id}/payment-requests", response_model=BillingRecordDetailResponse)
def create_billing_payment_request(
    record_id: str,
    payload: CreateBillingPaymentRequestRequest,
    request: Request,
    response: Response,
) -> BillingRecordDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        detail = service.create_payment_request(
            tenant_id=resolved_tenant_id,
            billing_record_id=record_id,
            provider=payload.provider,
            expires_in_minutes=payload.expires_in_minutes,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="billing record not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="billing record not found for tenant") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED
    return _serialize_detail(detail)


@router.post(
    "/payment-requests/{request_id}/callbacks",
    response_model=BillingRecordDetailResponse,
)
def handle_billing_payment_request_callback(
    request_id: str,
    payload: PaymentRequestCallbackRequest,
    request: Request,
) -> BillingRecordDetailResponse:
    _require_payment_callback_secret(request)
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        detail = service.handle_payment_request_callback(
            tenant_id=resolved_tenant_id,
            payment_request_id=request_id,
            payload=payload.model_dump(exclude_none=True),
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="payment request not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="payment request not found for tenant") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_detail(detail)


@router.post("/payments/{payment_id}/reconcile", response_model=BillingRecordDetailResponse)
def reconcile_billing_payment(
    payment_id: str,
    payload: ReconcileBillingPaymentRequest,
    request: Request,
) -> BillingRecordDetailResponse:
    service = _service_from_request(request)
    resolved_tenant_id = resolve_request_tenant_id(request, payload.tenant_id)
    try:
        detail = service.reconcile_payment(
            tenant_id=resolved_tenant_id,
            payment_id=payment_id,
            status=payload.status,
            note=payload.note,
            actor_subject=_actor_subject_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="billing payment not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="billing payment not found for tenant") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_detail(detail)
