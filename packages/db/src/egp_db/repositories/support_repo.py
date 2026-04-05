"""Tenant support lookup and cost observability queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, case, desc, distinct, func, or_, select
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import create_shared_engine
from egp_db.db_utils import normalize_database_url, normalize_uuid_string
from egp_db.repositories.admin_repo import TENANTS_TABLE, TENANT_SETTINGS_TABLE
from egp_db.repositories.billing_repo import (
    BILLING_PAYMENTS_TABLE,
    BILLING_PAYMENT_REQUESTS_TABLE,
    BILLING_RECORDS_TABLE,
)
from egp_db.repositories.document_repo import (
    DOCUMENT_DIFF_REVIEWS_TABLE,
    DOCUMENTS_TABLE,
)
from egp_db.repositories.notification_repo import (
    NOTIFICATIONS_TABLE,
    USERS_TABLE,
    WEBHOOK_DELIVERIES_TABLE,
)
from egp_db.repositories.run_repo import CRAWL_RUNS_TABLE, CRAWL_TASKS_TABLE


_MONEY_QUANTUM = Decimal("0.01")
_CRAWL_RUN_RATE = Decimal("0.20")
_CRAWL_TASK_RATE = Decimal("0.05")
_FAILED_RUN_RATE = Decimal("0.10")
_DOCUMENT_RATE = Decimal("0.03")
_SENT_NOTIFICATION_RATE = Decimal("0.20")
_FAILED_WEBHOOK_RATE = Decimal("0.01")
_BILLING_RECORD_RATE = Decimal("1.25")
_PAYMENT_REQUEST_RATE = Decimal("0.40")


@dataclass(frozen=True, slots=True)
class SupportTenantRecord:
    id: str
    name: str
    slug: str
    plan_code: str
    is_active: bool
    support_email: str | None
    billing_contact_email: str | None
    active_user_count: int


@dataclass(frozen=True, slots=True)
class SupportCrawlCost:
    estimated_cost_thb: str
    run_count: int
    task_count: int
    failed_run_count: int


@dataclass(frozen=True, slots=True)
class SupportStorageCost:
    estimated_cost_thb: str
    document_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class SupportNotificationCost:
    estimated_cost_thb: str
    sent_count: int
    failed_webhook_delivery_count: int


@dataclass(frozen=True, slots=True)
class SupportPaymentCost:
    estimated_cost_thb: str
    billing_record_count: int
    payment_request_count: int
    collected_amount_thb: str


@dataclass(frozen=True, slots=True)
class SupportCostSummary:
    window_days: int
    currency: str
    estimated_total_thb: str
    crawl: SupportCrawlCost
    storage: SupportStorageCost
    notifications: SupportNotificationCost
    payments: SupportPaymentCost


@dataclass(frozen=True, slots=True)
class SupportTriageSummary:
    failed_runs_recent: int
    pending_document_reviews: int
    failed_webhook_deliveries: int
    outstanding_billing_records: int


@dataclass(frozen=True, slots=True)
class SupportFailedRunRecord:
    id: str
    trigger_type: str
    status: str
    error_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class SupportPendingReviewRecord:
    id: str
    project_id: str
    status: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SupportFailedWebhookRecord:
    id: str
    webhook_subscription_id: str
    delivery_status: str
    last_response_status_code: int | None
    last_attempted_at: str | None


@dataclass(frozen=True, slots=True)
class SupportBillingIssueRecord:
    id: str
    record_number: str
    status: str
    amount_due: str
    due_at: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class SupportSummary:
    tenant: SupportTenantRecord
    triage: SupportTriageSummary
    cost_summary: SupportCostSummary
    recent_failed_runs: list[SupportFailedRunRecord]
    pending_reviews: list[SupportPendingReviewRecord]
    failed_webhooks: list[SupportFailedWebhookRecord]
    billing_issues: list[SupportBillingIssueRecord]


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _money(value: Decimal) -> str:
    return format(value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP), ".2f")


def _count(row_value) -> int:
    return int(row_value or 0)


def _decimal(row_value) -> Decimal:
    if row_value is None:
        return Decimal("0.00")
    return Decimal(str(row_value))


def _tenant_from_mapping(row: RowMapping) -> SupportTenantRecord:
    return SupportTenantRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        plan_code=str(row["plan_code"]),
        is_active=bool(row["is_active"]),
        support_email=str(row["support_email"])
        if row["support_email"] is not None
        else None,
        billing_contact_email=(
            str(row["billing_contact_email"])
            if row["billing_contact_email"] is not None
            else None
        ),
        active_user_count=_count(row["active_user_count"]),
    )


def _failed_run_from_mapping(row: RowMapping) -> SupportFailedRunRecord:
    return SupportFailedRunRecord(
        id=str(row["id"]),
        trigger_type=str(row["trigger_type"]),
        status=str(row["status"]),
        error_count=_count(row["error_count"]),
        created_at=_to_iso(row["created_at"]) or "",
    )


def _pending_review_from_mapping(row: RowMapping) -> SupportPendingReviewRecord:
    return SupportPendingReviewRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        status=str(row["status"]),
        created_at=_to_iso(row["created_at"]) or "",
    )


def _failed_webhook_from_mapping(row: RowMapping) -> SupportFailedWebhookRecord:
    return SupportFailedWebhookRecord(
        id=str(row["id"]),
        webhook_subscription_id=str(row["webhook_subscription_id"]),
        delivery_status=str(row["delivery_status"]),
        last_response_status_code=(
            int(row["last_response_status_code"])
            if row["last_response_status_code"] is not None
            else None
        ),
        last_attempted_at=_to_iso(row["last_attempted_at"]),
    )


def _billing_issue_from_mapping(row: RowMapping) -> SupportBillingIssueRecord:
    return SupportBillingIssueRecord(
        id=str(row["id"]),
        record_number=str(row["record_number"]),
        status=str(row["status"]),
        amount_due=_money(_decimal(row["amount_due"])),
        due_at=_to_iso(row["due_at"]),
        created_at=_to_iso(row["created_at"]) or "",
    )


class SqlSupportRepository:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")

    def _tenant_identity_query(self):
        return (
            select(
                TENANTS_TABLE.c.id,
                TENANTS_TABLE.c.name,
                TENANTS_TABLE.c.slug,
                TENANTS_TABLE.c.plan_code,
                TENANTS_TABLE.c.is_active,
                TENANT_SETTINGS_TABLE.c.support_email,
                TENANT_SETTINGS_TABLE.c.billing_contact_email,
                func.count(
                    distinct(
                        case(
                            (USERS_TABLE.c.status == "active", USERS_TABLE.c.id),
                            else_=None,
                        )
                    )
                ).label("active_user_count"),
            )
            .select_from(
                TENANTS_TABLE.outerjoin(
                    TENANT_SETTINGS_TABLE,
                    TENANT_SETTINGS_TABLE.c.tenant_id == TENANTS_TABLE.c.id,
                ).outerjoin(USERS_TABLE, USERS_TABLE.c.tenant_id == TENANTS_TABLE.c.id)
            )
            .group_by(
                TENANTS_TABLE.c.id,
                TENANTS_TABLE.c.name,
                TENANTS_TABLE.c.slug,
                TENANTS_TABLE.c.plan_code,
                TENANTS_TABLE.c.is_active,
                TENANT_SETTINGS_TABLE.c.support_email,
                TENANT_SETTINGS_TABLE.c.billing_contact_email,
            )
        )

    def get_tenant(self, *, tenant_id: str) -> SupportTenantRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    self._tenant_identity_query().where(
                        TENANTS_TABLE.c.id == normalized_tenant_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _tenant_from_mapping(row)

    def search_tenants(
        self, *, query: str, limit: int = 20
    ) -> list[SupportTenantRecord]:
        normalized_query = str(query).strip().lower()
        if not normalized_query:
            return []
        normalized_limit = max(1, min(int(limit), 50))
        pattern = f"%{normalized_query}%"
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    self._tenant_identity_query()
                    .where(
                        or_(
                            func.lower(TENANTS_TABLE.c.name).like(pattern),
                            func.lower(TENANTS_TABLE.c.slug).like(pattern),
                            func.lower(
                                func.coalesce(TENANT_SETTINGS_TABLE.c.support_email, "")
                            ).like(pattern),
                            func.lower(
                                func.coalesce(
                                    TENANT_SETTINGS_TABLE.c.billing_contact_email, ""
                                )
                            ).like(pattern),
                            func.lower(func.coalesce(USERS_TABLE.c.email, "")).like(
                                pattern
                            ),
                        )
                    )
                    .order_by(TENANTS_TABLE.c.slug.asc())
                    .limit(normalized_limit)
                )
                .mappings()
                .all()
            )
        return [_tenant_from_mapping(row) for row in rows]

    def get_cost_summary(
        self, *, tenant_id: str, window_days: int = 30
    ) -> SupportCostSummary:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_window_days = max(1, min(int(window_days), 90))
        cutoff = _now() - timedelta(days=normalized_window_days)
        with self._engine.connect() as connection:
            run_count = _count(
                connection.execute(
                    select(func.count())
                    .select_from(CRAWL_RUNS_TABLE)
                    .where(
                        and_(
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_RUNS_TABLE.c.created_at >= cutoff,
                        )
                    )
                ).scalar_one()
            )
            failed_run_count = _count(
                connection.execute(
                    select(func.count())
                    .select_from(CRAWL_RUNS_TABLE)
                    .where(
                        and_(
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_RUNS_TABLE.c.created_at >= cutoff,
                            CRAWL_RUNS_TABLE.c.status == "failed",
                        )
                    )
                ).scalar_one()
            )
            task_count = _count(
                connection.execute(
                    select(func.count())
                    .select_from(
                        CRAWL_TASKS_TABLE.join(
                            CRAWL_RUNS_TABLE,
                            CRAWL_RUNS_TABLE.c.id == CRAWL_TASKS_TABLE.c.run_id,
                        )
                    )
                    .where(
                        and_(
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_TASKS_TABLE.c.created_at >= cutoff,
                        )
                    )
                ).scalar_one()
            )
            document_row = (
                connection.execute(
                    select(
                        func.count().label("document_count"),
                        func.coalesce(func.sum(DOCUMENTS_TABLE.c.size_bytes), 0).label(
                            "total_bytes"
                        ),
                    )
                    .select_from(DOCUMENTS_TABLE)
                    .where(
                        and_(
                            DOCUMENTS_TABLE.c.tenant_id == normalized_tenant_id,
                            DOCUMENTS_TABLE.c.created_at >= cutoff,
                        )
                    )
                )
                .mappings()
                .one()
            )
            sent_count = _count(
                connection.execute(
                    select(func.count())
                    .select_from(NOTIFICATIONS_TABLE)
                    .where(
                        and_(
                            NOTIFICATIONS_TABLE.c.tenant_id == normalized_tenant_id,
                            NOTIFICATIONS_TABLE.c.created_at >= cutoff,
                            NOTIFICATIONS_TABLE.c.status == "sent",
                        )
                    )
                ).scalar_one()
            )
            failed_webhook_delivery_count = _count(
                connection.execute(
                    select(func.count())
                    .select_from(WEBHOOK_DELIVERIES_TABLE)
                    .where(
                        and_(
                            WEBHOOK_DELIVERIES_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            WEBHOOK_DELIVERIES_TABLE.c.created_at >= cutoff,
                            WEBHOOK_DELIVERIES_TABLE.c.delivery_status == "failed",
                        )
                    )
                ).scalar_one()
            )
            billing_record_count = _count(
                connection.execute(
                    select(func.count())
                    .select_from(BILLING_RECORDS_TABLE)
                    .where(
                        and_(
                            BILLING_RECORDS_TABLE.c.tenant_id == normalized_tenant_id,
                            BILLING_RECORDS_TABLE.c.created_at >= cutoff,
                        )
                    )
                ).scalar_one()
            )
            payment_request_count = _count(
                connection.execute(
                    select(func.count())
                    .select_from(BILLING_PAYMENT_REQUESTS_TABLE)
                    .where(
                        and_(
                            BILLING_PAYMENT_REQUESTS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            BILLING_PAYMENT_REQUESTS_TABLE.c.created_at >= cutoff,
                        )
                    )
                ).scalar_one()
            )
            collected_amount = _decimal(
                connection.execute(
                    select(func.coalesce(func.sum(BILLING_PAYMENTS_TABLE.c.amount), 0))
                    .select_from(BILLING_PAYMENTS_TABLE)
                    .where(
                        and_(
                            BILLING_PAYMENTS_TABLE.c.tenant_id == normalized_tenant_id,
                            BILLING_PAYMENTS_TABLE.c.payment_status == "reconciled",
                            BILLING_PAYMENTS_TABLE.c.recorded_at >= cutoff,
                        )
                    )
                ).scalar_one()
            )

        crawl_cost_value = (
            Decimal(run_count) * _CRAWL_RUN_RATE
            + Decimal(task_count) * _CRAWL_TASK_RATE
            + Decimal(failed_run_count) * _FAILED_RUN_RATE
        )
        storage_cost_value = (
            Decimal(_count(document_row["document_count"])) * _DOCUMENT_RATE
        )
        notification_cost_value = (
            Decimal(sent_count) * _SENT_NOTIFICATION_RATE
            + Decimal(failed_webhook_delivery_count) * _FAILED_WEBHOOK_RATE
        )
        payment_cost_value = (
            Decimal(billing_record_count) * _BILLING_RECORD_RATE
            + Decimal(payment_request_count) * _PAYMENT_REQUEST_RATE
        )
        total_cost_value = (
            crawl_cost_value
            + storage_cost_value
            + notification_cost_value
            + payment_cost_value
        )

        return SupportCostSummary(
            window_days=normalized_window_days,
            currency="THB",
            estimated_total_thb=_money(total_cost_value),
            crawl=SupportCrawlCost(
                estimated_cost_thb=_money(crawl_cost_value),
                run_count=run_count,
                task_count=task_count,
                failed_run_count=failed_run_count,
            ),
            storage=SupportStorageCost(
                estimated_cost_thb=_money(storage_cost_value),
                document_count=_count(document_row["document_count"]),
                total_bytes=_count(document_row["total_bytes"]),
            ),
            notifications=SupportNotificationCost(
                estimated_cost_thb=_money(notification_cost_value),
                sent_count=sent_count,
                failed_webhook_delivery_count=failed_webhook_delivery_count,
            ),
            payments=SupportPaymentCost(
                estimated_cost_thb=_money(payment_cost_value),
                billing_record_count=billing_record_count,
                payment_request_count=payment_request_count,
                collected_amount_thb=_money(collected_amount),
            ),
        )

    def get_support_summary(
        self, *, tenant_id: str, window_days: int = 30
    ) -> SupportSummary:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        tenant = self.get_tenant(tenant_id=normalized_tenant_id)
        if tenant is None:
            raise KeyError(normalized_tenant_id)
        normalized_window_days = max(1, min(int(window_days), 90))
        cutoff = _now() - timedelta(days=normalized_window_days)
        cost_summary = self.get_cost_summary(
            tenant_id=normalized_tenant_id,
            window_days=normalized_window_days,
        )
        with self._engine.connect() as connection:
            failed_runs_recent = _count(
                connection.execute(
                    select(func.count())
                    .select_from(CRAWL_RUNS_TABLE)
                    .where(
                        and_(
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_RUNS_TABLE.c.created_at >= cutoff,
                            CRAWL_RUNS_TABLE.c.status == "failed",
                        )
                    )
                ).scalar_one()
            )
            pending_document_reviews = _count(
                connection.execute(
                    select(func.count())
                    .select_from(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.status == "pending",
                        )
                    )
                ).scalar_one()
            )
            failed_webhook_deliveries = _count(
                connection.execute(
                    select(func.count())
                    .select_from(WEBHOOK_DELIVERIES_TABLE)
                    .where(
                        and_(
                            WEBHOOK_DELIVERIES_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            WEBHOOK_DELIVERIES_TABLE.c.delivery_status == "failed",
                        )
                    )
                ).scalar_one()
            )
            outstanding_billing_records = _count(
                connection.execute(
                    select(func.count())
                    .select_from(BILLING_RECORDS_TABLE)
                    .where(
                        and_(
                            BILLING_RECORDS_TABLE.c.tenant_id == normalized_tenant_id,
                            BILLING_RECORDS_TABLE.c.status.not_in(
                                ["paid", "cancelled", "refunded"]
                            ),
                        )
                    )
                ).scalar_one()
            )
            failed_run_rows = (
                connection.execute(
                    select(CRAWL_RUNS_TABLE)
                    .where(
                        and_(
                            CRAWL_RUNS_TABLE.c.tenant_id == normalized_tenant_id,
                            CRAWL_RUNS_TABLE.c.created_at >= cutoff,
                            CRAWL_RUNS_TABLE.c.status == "failed",
                        )
                    )
                    .order_by(desc(CRAWL_RUNS_TABLE.c.created_at))
                    .limit(5)
                )
                .mappings()
                .all()
            )
            pending_review_rows = (
                connection.execute(
                    select(DOCUMENT_DIFF_REVIEWS_TABLE)
                    .where(
                        and_(
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            DOCUMENT_DIFF_REVIEWS_TABLE.c.status == "pending",
                        )
                    )
                    .order_by(desc(DOCUMENT_DIFF_REVIEWS_TABLE.c.created_at))
                    .limit(5)
                )
                .mappings()
                .all()
            )
            failed_webhook_rows = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE)
                    .where(
                        and_(
                            WEBHOOK_DELIVERIES_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            WEBHOOK_DELIVERIES_TABLE.c.delivery_status == "failed",
                        )
                    )
                    .order_by(desc(WEBHOOK_DELIVERIES_TABLE.c.last_attempted_at))
                    .limit(5)
                )
                .mappings()
                .all()
            )
            billing_issue_rows = (
                connection.execute(
                    select(BILLING_RECORDS_TABLE)
                    .where(
                        and_(
                            BILLING_RECORDS_TABLE.c.tenant_id == normalized_tenant_id,
                            BILLING_RECORDS_TABLE.c.status.not_in(
                                ["paid", "cancelled", "refunded"]
                            ),
                        )
                    )
                    .order_by(desc(BILLING_RECORDS_TABLE.c.created_at))
                    .limit(5)
                )
                .mappings()
                .all()
            )

        return SupportSummary(
            tenant=tenant,
            triage=SupportTriageSummary(
                failed_runs_recent=failed_runs_recent,
                pending_document_reviews=pending_document_reviews,
                failed_webhook_deliveries=failed_webhook_deliveries,
                outstanding_billing_records=outstanding_billing_records,
            ),
            cost_summary=cost_summary,
            recent_failed_runs=[
                _failed_run_from_mapping(row) for row in failed_run_rows
            ],
            pending_reviews=[
                _pending_review_from_mapping(row) for row in pending_review_rows
            ],
            failed_webhooks=[
                _failed_webhook_from_mapping(row) for row in failed_webhook_rows
            ],
            billing_issues=[
                _billing_issue_from_mapping(row) for row in billing_issue_rows
            ],
        )


def create_support_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
) -> SqlSupportRepository:
    return SqlSupportRepository(database_url=database_url, engine=engine)
