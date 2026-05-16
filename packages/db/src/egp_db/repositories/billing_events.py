"""Billing event persistence helpers."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.enums import BillingEventType, BillingPaymentProvider

from .billing_models import BillingEventRecord
from .billing_schema import BILLING_EVENTS_TABLE, BILLING_PROVIDER_EVENTS_TABLE
from .billing_utils import _event_from_mapping, _now


class BillingEventMixin:
    def _load_events_for_records(
        self, record_ids: list[str]
    ) -> list[BillingEventRecord]:
        if not record_ids:
            return []
        normalized_ids = [normalize_uuid_string(record_id) for record_id in record_ids]
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_EVENTS_TABLE)
                    .where(BILLING_EVENTS_TABLE.c.billing_record_id.in_(normalized_ids))
                    .order_by(BILLING_EVENTS_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
        return [_event_from_mapping(row) for row in rows]

    def _append_event(
        self,
        connection,
        *,
        tenant_id: str,
        billing_record_id: str,
        payment_id: str | None,
        event_type: BillingEventType,
        actor_subject: str | None,
        note: str | None,
        from_status: str | None,
        to_status: str | None,
    ) -> None:
        connection.execute(
            insert(BILLING_EVENTS_TABLE).values(
                id=str(uuid4()),
                tenant_id=normalize_uuid_string(tenant_id),
                billing_record_id=normalize_uuid_string(billing_record_id),
                payment_id=normalize_uuid_string(payment_id)
                if payment_id is not None
                else None,
                event_type=event_type.value,
                actor_subject=actor_subject,
                note=note,
                from_status=from_status,
                to_status=to_status,
                created_at=_now(),
            )
        )

    def _record_provider_event(
        self,
        connection,
        *,
        tenant_id: str,
        payment_request_id: str,
        provider: BillingPaymentProvider,
        provider_event_id: str,
        event_type: str,
        payload_json: str,
    ) -> bool:
        try:
            connection.execute(
                insert(BILLING_PROVIDER_EVENTS_TABLE).values(
                    id=str(uuid4()),
                    tenant_id=normalize_uuid_string(tenant_id),
                    payment_request_id=normalize_uuid_string(payment_request_id),
                    provider=provider.value,
                    provider_event_id=str(provider_event_id).strip(),
                    event_type=str(event_type).strip(),
                    payload_json=str(payload_json),
                    created_at=_now(),
                )
            )
        except IntegrityError:
            return False
        return True
