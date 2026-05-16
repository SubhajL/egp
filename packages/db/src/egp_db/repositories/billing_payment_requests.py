"""Billing payment request operations."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, select, update

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import (
    BillingEventType,
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
)

from .billing_models import BillingPaymentRequestRecord, BillingRecordDetail
from .billing_schema import BILLING_PAYMENT_REQUESTS_TABLE
from .billing_utils import (
    _normalize_amount,
    _normalize_datetime,
    _normalize_payment_method,
    _normalize_payment_provider,
    _normalize_payment_request_status,
    _now,
    _payment_request_from_mapping,
)


class BillingPaymentRequestMixin:
    def _load_payment_requests_for_records(
        self, record_ids: list[str]
    ) -> list[BillingPaymentRequestRecord]:
        if not record_ids:
            return []
        normalized_ids = [normalize_uuid_string(record_id) for record_id in record_ids]
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_PAYMENT_REQUESTS_TABLE)
                    .where(
                        BILLING_PAYMENT_REQUESTS_TABLE.c.billing_record_id.in_(
                            normalized_ids
                        )
                    )
                    .order_by(BILLING_PAYMENT_REQUESTS_TABLE.c.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [_payment_request_from_mapping(row) for row in rows]

    def _get_payment_request_by_id(
        self, request_id: str
    ) -> BillingPaymentRequestRecord | None:
        normalized_request_id = normalize_uuid_string(request_id)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_PAYMENT_REQUESTS_TABLE)
                    .where(BILLING_PAYMENT_REQUESTS_TABLE.c.id == normalized_request_id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _payment_request_from_mapping(row) if row is not None else None

    def _get_payment_request_by_provider_reference(
        self,
        *,
        provider: BillingPaymentProvider | str,
        provider_reference: str,
    ) -> BillingPaymentRequestRecord | None:
        normalized_provider = _normalize_payment_provider(provider)
        normalized_reference = str(provider_reference).strip()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_PAYMENT_REQUESTS_TABLE)
                    .where(
                        BILLING_PAYMENT_REQUESTS_TABLE.c.provider
                        == normalized_provider.value,
                        BILLING_PAYMENT_REQUESTS_TABLE.c.provider_reference
                        == normalized_reference,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _payment_request_from_mapping(row) if row is not None else None

    def _require_payment_request_for_tenant(
        self, *, tenant_id: str, request_id: str
    ) -> BillingPaymentRequestRecord:
        request = self._get_payment_request_by_id(request_id)
        if request is None:
            raise KeyError(request_id)
        record = self._require_record_for_tenant(
            tenant_id=tenant_id,
            record_id=request.billing_record_id,
        )
        if record.tenant_id != normalize_uuid_string(tenant_id):
            raise PermissionError(request_id)
        return request

    def get_payment_request_detail(
        self, *, tenant_id: str, request_id: str
    ) -> BillingPaymentRequestRecord | None:
        try:
            return self._require_payment_request_for_tenant(
                tenant_id=tenant_id,
                request_id=request_id,
            )
        except (KeyError, PermissionError):
            return None

    def require_payment_request_detail(
        self, *, tenant_id: str, request_id: str
    ) -> BillingPaymentRequestRecord:
        return self._require_payment_request_for_tenant(
            tenant_id=tenant_id,
            request_id=request_id,
        )

    def get_payment_request_by_provider_reference(
        self,
        *,
        provider: BillingPaymentProvider | str,
        provider_reference: str,
    ) -> BillingPaymentRequestRecord | None:
        return self._get_payment_request_by_provider_reference(
            provider=provider,
            provider_reference=provider_reference,
        )

    def create_payment_request(
        self,
        *,
        tenant_id: str,
        billing_record_id: str,
        provider: BillingPaymentProvider | str,
        payment_method: BillingPaymentMethod | str,
        status: BillingPaymentRequestStatus | str,
        provider_reference: str,
        payment_url: str,
        qr_payload: str,
        qr_svg: str,
        amount: Decimal | str | float | int,
        currency: str,
        expires_at: str | None,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> BillingRecordDetail:
        record = self._require_record_for_tenant(
            tenant_id=tenant_id,
            record_id=billing_record_id,
        )
        normalized_provider = _normalize_payment_provider(provider)
        normalized_method = _normalize_payment_method(payment_method)
        normalized_status = _normalize_payment_request_status(status)
        normalized_amount = _normalize_amount(amount)
        normalized_expires_at = _normalize_datetime(expires_at)
        request_id = str(uuid4())
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                insert(BILLING_PAYMENT_REQUESTS_TABLE).values(
                    id=request_id,
                    tenant_id=record.tenant_id,
                    billing_record_id=record.id,
                    provider=normalized_provider.value,
                    payment_method=normalized_method.value,
                    status=normalized_status.value,
                    provider_reference=str(provider_reference).strip(),
                    payment_url=str(payment_url).strip(),
                    qr_payload=str(qr_payload),
                    qr_svg=str(qr_svg),
                    amount=normalized_amount,
                    currency=str(currency).strip() or "THB",
                    expires_at=normalized_expires_at,
                    settled_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record.id,
                payment_id=None,
                event_type=BillingEventType.PAYMENT_REQUEST_CREATED,
                actor_subject=actor_subject,
                note=note,
                from_status=record.status.value,
                to_status=normalized_status.value,
            )

        detail = self.get_billing_record_detail(
            tenant_id=tenant_id,
            record_id=record.id,
        )
        if detail is None:
            raise KeyError(record.id)
        return detail

    def record_provider_callback(
        self,
        *,
        tenant_id: str,
        payment_request_id: str,
        provider: BillingPaymentProvider | str,
        provider_event_id: str,
        event_type: str,
        payload_json: str,
    ) -> bool:
        payment_request = self._require_payment_request_for_tenant(
            tenant_id=tenant_id,
            request_id=payment_request_id,
        )
        normalized_provider = _normalize_payment_provider(provider)
        with self._engine.begin() as connection:
            return self._record_provider_event(
                connection,
                tenant_id=tenant_id,
                payment_request_id=payment_request.id,
                provider=normalized_provider,
                provider_event_id=provider_event_id,
                event_type=event_type,
                payload_json=payload_json,
            )

    def update_payment_request_status(
        self,
        *,
        tenant_id: str,
        payment_request_id: str,
        status: BillingPaymentRequestStatus | str,
        settled_at: str | None = None,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> BillingRecordDetail:
        request_before = self._require_payment_request_for_tenant(
            tenant_id=tenant_id,
            request_id=payment_request_id,
        )
        target_status = _normalize_payment_request_status(status)
        if request_before.status is target_status:
            detail = self.get_billing_record_detail(
                tenant_id=tenant_id,
                record_id=request_before.billing_record_id,
            )
            if detail is None:
                raise KeyError(request_before.billing_record_id)
            return detail
        record = self._require_record_for_tenant(
            tenant_id=tenant_id,
            record_id=request_before.billing_record_id,
        )
        now = _now()
        resolved_settled_at = _normalize_datetime(settled_at)
        with self._engine.begin() as connection:
            connection.execute(
                update(BILLING_PAYMENT_REQUESTS_TABLE)
                .where(
                    BILLING_PAYMENT_REQUESTS_TABLE.c.id
                    == normalize_uuid_string(payment_request_id)
                )
                .values(
                    status=target_status.value,
                    settled_at=resolved_settled_at,
                    updated_at=now,
                )
            )
            if target_status is BillingPaymentRequestStatus.SETTLED:
                self._append_event(
                    connection,
                    tenant_id=tenant_id,
                    billing_record_id=record.id,
                    payment_id=None,
                    event_type=BillingEventType.PAYMENT_REQUEST_SETTLED,
                    actor_subject=actor_subject,
                    note=note,
                    from_status=request_before.status.value,
                    to_status=target_status.value,
                )
        detail = self.get_billing_record_detail(
            tenant_id=tenant_id,
            record_id=request_before.billing_record_id,
        )
        if detail is None:
            raise KeyError(request_before.billing_record_id)
        return detail
