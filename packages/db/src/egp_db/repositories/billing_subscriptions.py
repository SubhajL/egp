"""Billing subscription and upgrade operations."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, select

from egp_db.db_utils import normalize_uuid_string
from egp_shared_types.billing_plans import (
    derive_plan_period_end,
    get_billing_plan_definition,
)
from egp_shared_types.enums import (
    BillingEventType,
    BillingRecordStatus,
    BillingSubscriptionStatus,
)

from .billing_models import BillingRecordDetail, BillingSubscriptionRecord
from .billing_schema import BILLING_RECORDS_TABLE, BILLING_SUBSCRIPTIONS_TABLE
from .billing_utils import (
    _normalize_date,
    _now,
    _select_effective_subscription,
    _select_upcoming_subscription,
    _subscription_from_mapping,
    _TERMINAL_BILLING_STATUSES,
)


class BillingSubscriptionMixin:
    def _load_subscriptions_for_records(
        self, record_ids: list[str]
    ) -> list[BillingSubscriptionRecord]:
        if not record_ids:
            return []
        normalized_ids = [normalize_uuid_string(record_id) for record_id in record_ids]
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(BILLING_SUBSCRIPTIONS_TABLE)
                    .where(
                        BILLING_SUBSCRIPTIONS_TABLE.c.billing_record_id.in_(
                            normalized_ids
                        )
                    )
                    .order_by(BILLING_SUBSCRIPTIONS_TABLE.c.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [_subscription_from_mapping(row) for row in rows]

    def list_subscriptions_for_tenant(
        self, *, tenant_id: str
    ) -> list[BillingSubscriptionRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(BILLING_SUBSCRIPTIONS_TABLE)
                    .where(
                        BILLING_SUBSCRIPTIONS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                    .order_by(
                        BILLING_SUBSCRIPTIONS_TABLE.c.billing_period_end.desc(),
                        BILLING_SUBSCRIPTIONS_TABLE.c.billing_period_start.desc(),
                        BILLING_SUBSCRIPTIONS_TABLE.c.created_at.desc(),
                    )
                )
                .mappings()
                .all()
            )
        return [_subscription_from_mapping(row) for row in rows]

    def get_effective_subscription_for_tenant(
        self, *, tenant_id: str
    ) -> BillingSubscriptionRecord | None:
        return _select_effective_subscription(
            self.list_subscriptions_for_tenant(tenant_id=tenant_id)
        )

    def _get_open_upgrade_record_id(
        self,
        *,
        tenant_id: str,
        subscription_id: str,
    ) -> str | None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(BILLING_RECORDS_TABLE.c.id)
                    .where(
                        BILLING_RECORDS_TABLE.c.tenant_id
                        == normalize_uuid_string(tenant_id),
                        BILLING_RECORDS_TABLE.c.upgrade_from_subscription_id
                        == normalize_uuid_string(subscription_id),
                        BILLING_RECORDS_TABLE.c.status.not_in(
                            [status.value for status in _TERMINAL_BILLING_STATUSES]
                        ),
                    )
                    .order_by(BILLING_RECORDS_TABLE.c.created_at.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return str(row["id"])

    def activate_free_trial_subscription(
        self,
        *,
        tenant_id: str,
        actor_subject: str | None = None,
        note: str | None = None,
    ) -> BillingSubscriptionRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        plan_definition = get_billing_plan_definition("free_trial")
        if plan_definition is None:
            raise ValueError("free_trial plan is not configured")
        now = _now()
        period_start = now.date()
        period_end = period_start + timedelta(
            days=(plan_definition.duration_days or 1) - 1
        )
        with self._engine.begin() as connection:
            existing_rows = (
                connection.execute(
                    select(BILLING_SUBSCRIPTIONS_TABLE)
                    .where(
                        BILLING_SUBSCRIPTIONS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                    .order_by(BILLING_SUBSCRIPTIONS_TABLE.c.created_at.desc())
                )
                .mappings()
                .all()
            )
            for row in existing_rows:
                subscription = _subscription_from_mapping(row)
                if subscription.plan_code == "free_trial":
                    raise ValueError("free trial already used for tenant")
                if subscription.subscription_status is BillingSubscriptionStatus.ACTIVE:
                    raise ValueError("tenant already has an active subscription")

            record_id = str(uuid4())
            subscription_id = str(uuid4())
            record_number = f"TRIAL-{record_id[:8].upper()}"
            connection.execute(
                insert(BILLING_RECORDS_TABLE).values(
                    id=record_id,
                    tenant_id=normalized_tenant_id,
                    record_number=record_number,
                    plan_code="free_trial",
                    status=BillingRecordStatus.PAID.value,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    currency=plan_definition.currency,
                    amount_due=Decimal("0.00"),
                    due_at=None,
                    issued_at=now,
                    paid_at=now,
                    notes=note or "Free trial activation",
                    created_at=now,
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record_id,
                payment_id=None,
                event_type=BillingEventType.BILLING_RECORD_CREATED,
                actor_subject=actor_subject,
                note=note or "Free trial activation",
                from_status=None,
                to_status=BillingRecordStatus.PAID.value,
            )
            connection.execute(
                insert(BILLING_SUBSCRIPTIONS_TABLE).values(
                    id=subscription_id,
                    tenant_id=normalized_tenant_id,
                    billing_record_id=record_id,
                    plan_code="free_trial",
                    status=BillingSubscriptionStatus.ACTIVE.value,
                    billing_period_start=period_start,
                    billing_period_end=period_end,
                    keyword_limit=plan_definition.keyword_limit,
                    activated_at=now,
                    activated_by_payment_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._append_event(
                connection,
                tenant_id=tenant_id,
                billing_record_id=record_id,
                payment_id=None,
                event_type=BillingEventType.SUBSCRIPTION_ACTIVATED,
                actor_subject=actor_subject,
                note=note or "Free trial activation",
                from_status=None,
                to_status=BillingSubscriptionStatus.ACTIVE.value,
            )

        detail = self.require_billing_record_detail(
            tenant_id=tenant_id, record_id=record_id
        )
        if detail.subscription is None:
            raise RuntimeError("free trial subscription activation failed")
        return detail.subscription

    def create_upgrade_billing_record(
        self,
        *,
        tenant_id: str,
        target_plan_code: str,
        billing_period_start: str,
        amount_due: Decimal | str | float | int | None = None,
        record_number: str,
        notes: str | None = None,
        actor_subject: str | None = None,
    ) -> BillingRecordDetail:
        current_subscription = self.get_effective_subscription_for_tenant(
            tenant_id=tenant_id
        )
        if current_subscription is None:
            raise ValueError(
                "active, pending, or expired subscription required for upgrade"
            )
        if current_subscription.subscription_status not in {
            BillingSubscriptionStatus.ACTIVE,
            BillingSubscriptionStatus.PENDING_ACTIVATION,
            BillingSubscriptionStatus.EXPIRED,
        }:
            raise ValueError(
                "active, pending, or expired subscription required for upgrade"
            )

        normalized_target_plan_code = str(target_plan_code).strip()
        allowed_transitions = {
            ("free_trial", "one_time_search_pack"),
            ("free_trial", "monthly_membership"),
            ("one_time_search_pack", "monthly_membership"),
        }
        if (
            current_subscription.plan_code,
            normalized_target_plan_code,
        ) not in allowed_transitions:
            raise ValueError("unsupported subscription upgrade")

        target_plan_definition = get_billing_plan_definition(
            normalized_target_plan_code
        )
        if target_plan_definition is None:
            raise ValueError("unsupported subscription upgrade")

        period_start = _normalize_date(billing_period_start)
        upgrade_mode = (
            "replace_on_activation" if period_start > _now().date() else "replace_now"
        )

        if (
            self._get_open_upgrade_record_id(
                tenant_id=tenant_id,
                subscription_id=current_subscription.id,
            )
            is not None
        ):
            raise ValueError("upgrade already in progress for subscription")

        period_end = derive_plan_period_end(
            target_plan_definition,
            billing_period_start=period_start,
        )
        return self.create_billing_record(
            tenant_id=tenant_id,
            record_number=record_number,
            plan_code=target_plan_definition.code,
            status=BillingRecordStatus.AWAITING_PAYMENT,
            billing_period_start=period_start.isoformat(),
            billing_period_end=period_end.isoformat(),
            amount_due=(
                target_plan_definition.amount_due if amount_due is None else amount_due
            ),
            currency=target_plan_definition.currency,
            due_at=None,
            issued_at=_now().isoformat(),
            upgrade_from_subscription_id=current_subscription.id,
            upgrade_mode=upgrade_mode,
            notes=notes,
            actor_subject=actor_subject,
        )

    def get_upcoming_subscription_for_tenant(
        self, *, tenant_id: str
    ) -> BillingSubscriptionRecord | None:
        return _select_upcoming_subscription(
            self.list_subscriptions_for_tenant(tenant_id=tenant_id)
        )
