"""Request and response models for admin routes."""

from __future__ import annotations

from pydantic import BaseModel, Field

from egp_shared_types.enums import UserRole


class AdminTenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan_code: str
    is_active: bool
    created_at: str
    updated_at: str


class AdminTenantSettingsResponse(BaseModel):
    support_email: str | None
    billing_contact_email: str | None
    timezone: str
    locale: str
    daily_digest_enabled: bool
    weekly_digest_enabled: bool
    crawl_interval_hours: int | None
    created_at: str | None
    updated_at: str | None


class AdminTenantStorageSettingsResponse(BaseModel):
    provider: str
    connection_status: str
    account_email: str | None
    folder_label: str | None
    folder_path_hint: str | None
    provider_folder_id: str | None
    provider_folder_url: str | None
    managed_fallback_enabled: bool
    managed_backup_enabled: bool
    last_validated_at: str | None
    last_validation_error: str | None
    has_credentials: bool
    credential_type: str | None
    credential_updated_at: str | None
    created_at: str | None
    updated_at: str | None


class AdminUserResponse(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    status: str
    email_verified_at: str | None
    mfa_enabled: bool
    created_at: str
    updated_at: str
    notification_preferences: dict[str, bool]


class AdminBillingRecordResponse(BaseModel):
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
    upgrade_from_subscription_id: str | None
    upgrade_mode: str
    notes: str | None
    created_at: str
    updated_at: str


class AdminBillingSummaryResponse(BaseModel):
    open_records: int
    awaiting_reconciliation: int
    outstanding_amount: str
    collected_amount: str


class AdminSubscriptionResponse(BaseModel):
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


class AdminBillingResponse(BaseModel):
    summary: AdminBillingSummaryResponse
    current_subscription: AdminSubscriptionResponse | None
    upcoming_subscription: AdminSubscriptionResponse | None
    records: list[AdminBillingRecordResponse]


class AdminSnapshotResponse(BaseModel):
    tenant: AdminTenantResponse
    settings: AdminTenantSettingsResponse
    users: list[AdminUserResponse]
    billing: AdminBillingResponse


class AuditLogEventResponse(BaseModel):
    id: str
    tenant_id: str
    source: str
    entity_type: str
    entity_id: str
    project_id: str | None
    document_id: str | None
    actor_subject: str | None
    event_type: str
    summary: str
    metadata_json: dict[str, object] | None
    occurred_at: str
    created_at: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogEventResponse]
    total: int
    limit: int
    offset: int


class SupportTenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan_code: str
    is_active: bool
    support_email: str | None
    billing_contact_email: str | None
    active_user_count: int


class SupportTenantListResponse(BaseModel):
    tenants: list[SupportTenantResponse]


class SupportTriageResponse(BaseModel):
    failed_runs_recent: int
    pending_document_reviews: int
    failed_webhook_deliveries: int
    outstanding_billing_records: int


class SupportFailedRunResponse(BaseModel):
    id: str
    trigger_type: str
    status: str
    error_count: int
    created_at: str


class SupportPendingReviewResponse(BaseModel):
    id: str
    project_id: str
    status: str
    created_at: str


class SupportFailedWebhookResponse(BaseModel):
    id: str
    webhook_subscription_id: str
    delivery_status: str
    last_response_status_code: int | None
    last_attempted_at: str | None


class SupportBillingIssueResponse(BaseModel):
    id: str
    record_number: str
    status: str
    amount_due: str
    due_at: str | None
    created_at: str


class SupportStorageDiagnosticsResponse(BaseModel):
    provider: str
    connection_status: str
    account_email: str | None
    provider_folder_id: str | None
    provider_folder_url: str | None
    managed_fallback_enabled: bool
    managed_backup_enabled: bool
    has_credentials: bool
    last_validated_at: str | None
    last_validation_error: str | None


class SupportAlertResponse(BaseModel):
    severity: str
    code: str
    title: str
    detail: str


class SupportCrawlCostResponse(BaseModel):
    estimated_cost_thb: str
    run_count: int
    task_count: int
    failed_run_count: int


class SupportStorageCostResponse(BaseModel):
    estimated_cost_thb: str
    document_count: int
    total_bytes: int


class SupportNotificationCostResponse(BaseModel):
    estimated_cost_thb: str
    sent_count: int
    failed_webhook_delivery_count: int


class SupportPaymentCostResponse(BaseModel):
    estimated_cost_thb: str
    billing_record_count: int
    payment_request_count: int
    collected_amount_thb: str


class SupportCostSummaryResponse(BaseModel):
    window_days: int
    currency: str
    estimated_total_thb: str
    crawl: SupportCrawlCostResponse
    storage: SupportStorageCostResponse
    notifications: SupportNotificationCostResponse
    payments: SupportPaymentCostResponse


class SupportSummaryResponse(BaseModel):
    tenant: SupportTenantResponse
    triage: SupportTriageResponse
    cost_summary: SupportCostSummaryResponse
    storage_diagnostics: SupportStorageDiagnosticsResponse
    alerts: list[SupportAlertResponse]
    recent_failed_runs: list[SupportFailedRunResponse]
    pending_reviews: list[SupportPendingReviewResponse]
    failed_webhooks: list[SupportFailedWebhookResponse]
    billing_issues: list[SupportBillingIssueResponse]


class CreateAdminUserRequest(BaseModel):
    tenant_id: str | None = None
    email: str = Field(min_length=1)
    full_name: str | None = None
    role: UserRole = UserRole.VIEWER
    status: str = Field(default="active", pattern="^(active|suspended|deactivated)$")
    password: str | None = None


class UpdateAdminUserRequest(BaseModel):
    tenant_id: str | None = None
    full_name: str | None = None
    role: UserRole | None = None
    status: str | None = Field(default=None, pattern="^(active|suspended|deactivated)$")
    password: str | None = None


class UpdateUserNotificationPreferencesRequest(BaseModel):
    tenant_id: str | None = None
    email_preferences: dict[str, bool]


class UpdateTenantSettingsRequest(BaseModel):
    tenant_id: str | None = None
    support_email: str | None = None
    billing_contact_email: str | None = None
    timezone: str | None = None
    locale: str | None = None
    daily_digest_enabled: bool | None = None
    weekly_digest_enabled: bool | None = None
    crawl_interval_hours: int | None = Field(default=None, ge=1, le=168)


class UpdateTenantStorageSettingsRequest(BaseModel):
    tenant_id: str | None = None
    provider: str | None = Field(
        default=None,
        pattern="^(managed|google_drive|onedrive|local_agent)$",
    )
    connection_status: str | None = Field(
        default=None,
        pattern="^(managed|pending_setup|connected|error|disconnected)$",
    )
    account_email: str | None = None
    folder_label: str | None = None
    folder_path_hint: str | None = None
    provider_folder_id: str | None = None
    provider_folder_url: str | None = None
    managed_fallback_enabled: bool | None = None
    managed_backup_enabled: bool | None = None
    last_validated_at: str | None = None
    last_validation_error: str | None = None


class ConnectTenantStorageRequest(BaseModel):
    tenant_id: str | None = None
    provider: str = Field(pattern="^(google_drive|onedrive|local_agent)$")
    credential_type: str = Field(min_length=1)
    credentials: dict[str, object] = Field(default_factory=dict)


class DisconnectTenantStorageRequest(BaseModel):
    tenant_id: str | None = None
    provider: str = Field(pattern="^(google_drive|onedrive|local_agent)$")


class TestTenantStorageRequest(BaseModel):
    tenant_id: str | None = None


class StartGoogleDriveOAuthRequest(BaseModel):
    tenant_id: str | None = None


class GoogleDriveOAuthStartResponse(BaseModel):
    provider: str
    authorization_url: str
    state: str


class StartOneDriveOAuthRequest(BaseModel):
    tenant_id: str | None = None


class OneDriveOAuthStartResponse(BaseModel):
    provider: str
    authorization_url: str
    state: str


class SelectGoogleDriveFolderRequest(BaseModel):
    tenant_id: str | None = None
    folder_id: str = Field(min_length=1)
    folder_label: str | None = None
    folder_url: str | None = None


class SelectOneDriveFolderRequest(BaseModel):
    tenant_id: str | None = None
    folder_id: str = Field(min_length=1)
    folder_label: str | None = None
    folder_url: str | None = None


class AdminInviteUserRequest(BaseModel):
    tenant_id: str | None = None


class AdminInviteUserResponse(BaseModel):
    status: str
    delivery_email: str
