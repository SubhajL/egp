"""Serialization helpers for admin route responses."""

from __future__ import annotations

from dataclasses import asdict

from egp_api.routes.admin.schemas import (
    AdminBillingRecordResponse,
    AdminBillingResponse,
    AdminBillingSummaryResponse,
    AdminSnapshotResponse,
    AdminSubscriptionResponse,
    AdminTenantResponse,
    AdminTenantSettingsResponse,
    AdminTenantStorageSettingsResponse,
    AdminUserResponse,
    AuditLogEventResponse,
    AuditLogListResponse,
    SupportAlertResponse,
    SupportBillingIssueResponse,
    SupportCostSummaryResponse,
    SupportFailedRunResponse,
    SupportFailedWebhookResponse,
    SupportPendingReviewResponse,
    SupportStorageDiagnosticsResponse,
    SupportSummaryResponse,
    SupportTenantResponse,
    SupportTriageResponse,
)
from egp_api.services.admin_service import AdminSnapshot, AdminUserView
from egp_db.repositories.admin_repo import TenantSettingsRecord, TenantStorageSettingsRecord
from egp_db.repositories.audit_repo import AuditLogPage
from egp_db.repositories.support_repo import (
    SupportCostSummary,
    SupportSummary,
    SupportTenantRecord,
)


def serialize_user(user: AdminUserView) -> AdminUserResponse:
    return AdminUserResponse(**asdict(user))


def serialize_settings(settings: TenantSettingsRecord) -> AdminTenantSettingsResponse:
    return AdminTenantSettingsResponse(**asdict(settings))


def serialize_storage_settings(
    settings: TenantStorageSettingsRecord,
) -> AdminTenantStorageSettingsResponse:
    return AdminTenantStorageSettingsResponse(**asdict(settings))


def serialize_snapshot(snapshot: AdminSnapshot) -> AdminSnapshotResponse:
    current_subscription = snapshot.billing.current_subscription
    upcoming_subscription = snapshot.billing.upcoming_subscription
    return AdminSnapshotResponse(
        tenant=AdminTenantResponse(**asdict(snapshot.tenant)),
        settings=serialize_settings(snapshot.settings),
        users=[serialize_user(user) for user in snapshot.users],
        billing=AdminBillingResponse(
            summary=AdminBillingSummaryResponse(**asdict(snapshot.billing.summary)),
            current_subscription=(
                AdminSubscriptionResponse(
                    id=current_subscription.id,
                    tenant_id=current_subscription.tenant_id,
                    billing_record_id=current_subscription.billing_record_id,
                    plan_code=current_subscription.plan_code,
                    subscription_status=current_subscription.subscription_status.value,
                    billing_period_start=current_subscription.billing_period_start,
                    billing_period_end=current_subscription.billing_period_end,
                    keyword_limit=current_subscription.keyword_limit,
                    activated_at=current_subscription.activated_at,
                    activated_by_payment_id=current_subscription.activated_by_payment_id,
                    created_at=current_subscription.created_at,
                    updated_at=current_subscription.updated_at,
                )
                if current_subscription is not None
                else None
            ),
            upcoming_subscription=(
                AdminSubscriptionResponse(
                    id=upcoming_subscription.id,
                    tenant_id=upcoming_subscription.tenant_id,
                    billing_record_id=upcoming_subscription.billing_record_id,
                    plan_code=upcoming_subscription.plan_code,
                    subscription_status=upcoming_subscription.subscription_status.value,
                    billing_period_start=upcoming_subscription.billing_period_start,
                    billing_period_end=upcoming_subscription.billing_period_end,
                    keyword_limit=upcoming_subscription.keyword_limit,
                    activated_at=upcoming_subscription.activated_at,
                    activated_by_payment_id=upcoming_subscription.activated_by_payment_id,
                    created_at=upcoming_subscription.created_at,
                    updated_at=upcoming_subscription.updated_at,
                )
                if upcoming_subscription is not None
                else None
            ),
            records=[
                AdminBillingRecordResponse(
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
                    upgrade_from_subscription_id=record.upgrade_from_subscription_id,
                    upgrade_mode=record.upgrade_mode,
                    notes=record.notes,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
                for record in snapshot.billing.records
            ],
        ),
    )


def serialize_audit_log(page: AuditLogPage) -> AuditLogListResponse:
    return AuditLogListResponse(
        items=[AuditLogEventResponse(**asdict(item)) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def serialize_support_tenant(tenant: SupportTenantRecord) -> SupportTenantResponse:
    return SupportTenantResponse(**asdict(tenant))


def serialize_support_cost_summary(summary: SupportCostSummary) -> SupportCostSummaryResponse:
    return SupportCostSummaryResponse(
        window_days=summary.window_days,
        currency=summary.currency,
        estimated_total_thb=summary.estimated_total_thb,
        crawl=asdict(summary.crawl),
        storage=asdict(summary.storage),
        notifications=asdict(summary.notifications),
        payments=asdict(summary.payments),
    )


def serialize_support_summary(summary: SupportSummary) -> SupportSummaryResponse:
    return SupportSummaryResponse(
        tenant=serialize_support_tenant(summary.tenant),
        triage=SupportTriageResponse(**asdict(summary.triage)),
        cost_summary=serialize_support_cost_summary(summary.cost_summary),
        storage_diagnostics=SupportStorageDiagnosticsResponse(
            **asdict(summary.storage_diagnostics)
        ),
        alerts=[SupportAlertResponse(**asdict(item)) for item in summary.alerts],
        recent_failed_runs=[
            SupportFailedRunResponse(**asdict(item)) for item in summary.recent_failed_runs
        ],
        pending_reviews=[
            SupportPendingReviewResponse(**asdict(item)) for item in summary.pending_reviews
        ],
        failed_webhooks=[
            SupportFailedWebhookResponse(**asdict(item)) for item in summary.failed_webhooks
        ],
        billing_issues=[
            SupportBillingIssueResponse(**asdict(item)) for item in summary.billing_issues
        ],
    )
