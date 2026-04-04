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
    BillingRecordDetail,
    BillingRecordRecord,
    BillingSummary,
)
from egp_shared_types.enums import BillingPaymentMethod, BillingPaymentStatus, BillingRecordStatus


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


class BillingRecordDetailResponse(BaseModel):
    record: BillingRecordResponse
    payments: list[BillingPaymentResponse]
    events: list[BillingEventResponse]


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


class CreateBillingRecordRequest(BaseModel):
    tenant_id: str | None = None
    record_number: str = Field(min_length=1)
    plan_code: str = Field(min_length=1)
    status: BillingRecordStatus = BillingRecordStatus.AWAITING_PAYMENT
    billing_period_start: str = Field(min_length=1)
    billing_period_end: str = Field(min_length=1)
    due_at: str | None = None
    issued_at: str | None = None
    amount_due: str = Field(min_length=1)
    currency: str = Field(default="THB", min_length=1)
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


def _service_from_request(request: Request) -> BillingService:
    return request.app.state.billing_service


def _actor_subject_from_request(request: Request) -> str:
    auth_context = getattr(request.state, "auth_context", None)
    if auth_context is not None and getattr(auth_context, "subject", None):
        return str(auth_context.subject)
    return "manual-operator"


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


def _serialize_detail(detail: BillingRecordDetail) -> BillingRecordDetailResponse:
    return BillingRecordDetailResponse(
        record=_serialize_record(detail.record),
        payments=[_serialize_payment(payment) for payment in detail.payments],
        events=[_serialize_event(event) for event in detail.events],
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
