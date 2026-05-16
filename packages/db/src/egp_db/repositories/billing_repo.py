"""Compatibility facade for tenant-scoped billing persistence."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from egp_db.connection import create_shared_engine
from egp_db.db_utils import normalize_database_url

from .billing_events import BillingEventMixin
from .billing_invoices import BillingInvoiceMixin
from .billing_models import (
    BillingEventRecord,
    BillingPage,
    BillingPaymentRecord,
    BillingPaymentRequestRecord,
    BillingRecordDetail,
    BillingRecordRecord,
    BillingSubscriptionRecord,
    BillingSummary,
)
from .billing_payment_requests import BillingPaymentRequestMixin
from .billing_payments import BillingPaymentMixin
from .billing_schema import (
    BILLING_EVENTS_TABLE,
    BILLING_PAYMENTS_TABLE,
    BILLING_PAYMENT_REQUESTS_TABLE,
    BILLING_PROVIDER_EVENTS_TABLE,
    BILLING_RECORDS_TABLE,
    BILLING_SUBSCRIPTIONS_TABLE,
    METADATA,
)
from .billing_subscriptions import BillingSubscriptionMixin


__all__ = [
    "BILLING_EVENTS_TABLE",
    "BILLING_PAYMENTS_TABLE",
    "BILLING_PAYMENT_REQUESTS_TABLE",
    "BILLING_PROVIDER_EVENTS_TABLE",
    "BILLING_RECORDS_TABLE",
    "BILLING_SUBSCRIPTIONS_TABLE",
    "METADATA",
    "BillingEventRecord",
    "BillingPage",
    "BillingPaymentRecord",
    "BillingPaymentRequestRecord",
    "BillingRecordDetail",
    "BillingRecordRecord",
    "BillingSubscriptionRecord",
    "BillingSummary",
    "SqlBillingRepository",
    "create_billing_repository",
]


class SqlBillingRepository(
    BillingInvoiceMixin,
    BillingPaymentRequestMixin,
    BillingPaymentMixin,
    BillingSubscriptionMixin,
    BillingEventMixin,
):
    """Relational billing repository for invoice lifecycle and reconciliation."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)


def create_billing_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlBillingRepository:
    return SqlBillingRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
