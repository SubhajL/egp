"""Service bootstrap and app-state binding for the API application."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from egp_api.bootstrap.repositories import RepositoryBundle
from egp_api.config import (
    BackgroundRuntimeMode,
    get_admin_console_base_url,
    get_line_add_url,
    get_line_admin_user_ids,
    get_line_channel_access_token,
    get_line_channel_secret,
    get_payment_base_url,
    get_payment_callback_secret,
    get_payment_provider,
    get_discovery_worker_count,
    get_promptpay_proxy_id,
    get_opn_public_key,
    get_opn_secret_key,
    get_opn_webhook_secret,
    get_smtp_config,
    get_stripe_publishable_key,
    get_stripe_secret_key,
    get_stripe_webhook_secret,
    get_web_base_url,
)
from egp_api.services.admin_service import AdminService
from egp_api.services.audit_service import AuditService
from egp_api.services.auth_service import AuthService
from egp_api.services.billing_service import BillingService
from egp_api.services.dashboard_service import DashboardService
from egp_api.services.discovery_dispatch import DiscoveryDispatchProcessor
from egp_api.services.discovery_dispatch import DiscoveryDispatcher
from egp_api.services.entitlement_service import (
    EntitlementAwareNotificationDispatcher,
    TenantEntitlementService,
)
from egp_api.services.export_service import ExportService
from egp_api.services.line_integration import HttpLineMessagingClient
from egp_api.services.line_slip_service import LineSlipService
from egp_api.services.payment_provider import PaymentProvider, build_payment_provider
from egp_shared_types.billing_plans import get_billing_plan_definition
from egp_domain.document_ingest import DocumentIngestService
from egp_domain.project_ingest import ProjectIngestService
from egp_api.services.project_service import ProjectService
from egp_api.services.rules_service import RulesService
from egp_api.services.run_service import RunService
from egp_api.services.storage_settings_service import StorageSettingsService
from egp_api.services.support_service import SupportService
from egp_api.services.webhook_service import WebhookService
from egp_db.db_utils import is_sqlite_url
from egp_notifications.dispatcher import NotificationDispatcher
from egp_notifications.service import EmailSender, NotificationService, SmtpConfig
from egp_notifications.webhook_delivery import WebhookDeliveryProcessor, WebhookDeliveryService


def configure_services(
    *,
    app: FastAPI,
    bundle: RepositoryBundle,
    smtp_config: SmtpConfig | None,
    notification_email_sender: EmailSender | None,
    payment_provider: PaymentProvider | None,
    payment_base_url: str | None,
    promptpay_proxy_id: str | None,
    opn_public_key: str | None,
    opn_secret_key: str | None,
    opn_webhook_secret: str | None,
    stripe_secret_key: str | None,
    stripe_webhook_secret: str | None,
    stripe_publishable_key: str | None,
    payment_callback_secret: str | None,
    resolved_web_allowed_origins: list[str],
    discover_spawner_factory: Callable[..., Callable[..., None]],
    discovery_dispatcher_factory: Callable[[FastAPI], DiscoveryDispatcher],
    discovery_loop_enabled: Callable[..., bool],
    discovery_route_kick_enabled: Callable[..., bool],
    background_runtime_mode: BackgroundRuntimeMode,
) -> None:
    notification_service = NotificationService(
        smtp_config=get_smtp_config(smtp_config),
        in_app_store=bundle.notification_repository,
        email_sender=notification_email_sender,
    )
    webhook_delivery_service = WebhookDeliveryService(repository=bundle.notification_repository)
    webhook_delivery_processor = WebhookDeliveryProcessor(repository=bundle.notification_repository)
    notification_dispatcher = NotificationDispatcher(
        service=notification_service,
        recipient_resolver=bundle.notification_repository,
        webhook_delivery_service=webhook_delivery_service,
    )
    entitlement_service = TenantEntitlementService(
        bundle.billing_repository,
        bundle.profile_repository,
        run_repository=bundle.run_repository,
        discovery_job_repository=bundle.discovery_job_repository,
        tenant_entitlement_repository=bundle.tenant_entitlement_repository,
    )
    resolved_web_base_url = get_web_base_url(None, allowed_origins=resolved_web_allowed_origins)
    resolved_payment_provider = payment_provider or build_payment_provider(
        provider_name=get_payment_provider(None),
        base_url=get_payment_base_url(payment_base_url),
        promptpay_proxy_id=get_promptpay_proxy_id(promptpay_proxy_id),
        opn_public_key=get_opn_public_key(opn_public_key),
        opn_secret_key=get_opn_secret_key(opn_secret_key),
        opn_webhook_secret=get_opn_webhook_secret(opn_webhook_secret),
        stripe_secret_key=get_stripe_secret_key(stripe_secret_key),
        stripe_webhook_secret=get_stripe_webhook_secret(stripe_webhook_secret),
        stripe_publishable_key=get_stripe_publishable_key(stripe_publishable_key),
        web_base_url=resolved_web_base_url,
    )
    resolved_payment_callback_secret = get_payment_callback_secret(payment_callback_secret)
    if resolved_payment_callback_secret is None:
        raise RuntimeError("payment callback secret is required")
    gated_notification_dispatcher = EntitlementAwareNotificationDispatcher(
        notification_dispatcher,
        entitlement_service,
    )
    auth_service = AuthService(
        bundle.auth_repository,
        bundle.admin_repository,
        session_max_age_seconds=bundle.session_cookie_max_age_seconds,
        notification_service=notification_service,
        notification_repository=bundle.notification_repository,
        billing_service=BillingService(
            bundle.billing_repository,
            payment_provider=resolved_payment_provider,
        ),
        entitlement_service=entitlement_service,
        web_base_url=resolved_web_base_url,
    )
    storage_settings_service = StorageSettingsService(
        bundle.admin_repository,
        credential_cipher=bundle.storage_credential_cipher,
        audit_repository=bundle.audit_repository,
        google_drive_oauth_config=bundle.resolved_google_drive_oauth_config,
        google_drive_client=bundle.resolved_google_drive_client,
        onedrive_oauth_config=bundle.resolved_onedrive_oauth_config,
        onedrive_client=bundle.resolved_onedrive_client,
    )
    app.state.db_engine = bundle.shared_engine
    app.state.admin_repository = bundle.admin_repository
    app.state.auth_repository = bundle.auth_repository
    app.state.audit_repository = bundle.audit_repository
    app.state.auth_service = auth_service
    app.state.billing_repository = bundle.billing_repository
    app.state.audit_service = AuditService(bundle.audit_repository)
    app.state.admin_service = AdminService(
        bundle.admin_repository,
        bundle.notification_repository,
        bundle.billing_repository,
        bundle.audit_repository,
    )
    app.state.storage_settings_service = storage_settings_service
    app.state.billing_service = BillingService(
        bundle.billing_repository,
        payment_provider=resolved_payment_provider,
    )
    resolved_line_channel_secret = get_line_channel_secret(None)
    resolved_line_access_token = get_line_channel_access_token(None)
    line_messaging_client = (
        HttpLineMessagingClient(channel_access_token=resolved_line_access_token)
        if resolved_line_access_token
        else None
    )
    app.state.line_channel_secret = resolved_line_channel_secret
    app.state.line_add_url = get_line_add_url(None)
    app.state.payment_provider_name = get_payment_provider(None)
    app.state.line_slip_service = LineSlipService(
        line_repository=bundle.line_payment_repository,
        billing_repository=bundle.billing_repository,
        billing_service=app.state.billing_service,
        artifact_store=bundle.managed_artifact_store,
        messaging_client=line_messaging_client,
        admin_user_ids=get_line_admin_user_ids(None),
        admin_console_base_url=get_admin_console_base_url(None) or resolved_web_base_url,
    )

    # Late-bind so an admin/manual reconciliation (not a LINE slip) still pushes a
    # subscription-activated notice to the customer's known LINE contact. Resolve
    # line_slip_service from app.state at CALL time (not captured here) so it stays
    # correct if the service is swapped later, and because LineSlipService itself
    # depends on BillingService (construction-order cycle).
    def _notify_subscription_activated(*, tenant_id: str, plan_code: str) -> None:
        slip_service = getattr(app.state, "line_slip_service", None)
        if slip_service is None:
            return
        plan = get_billing_plan_definition(plan_code)
        slip_service.notify_subscription_activated(
            tenant_id, plan_label=plan.label if plan is not None else plan_code
        )

    app.state.billing_service.set_subscription_activated_notifier(_notify_subscription_activated)
    app.state.entitlement_service = entitlement_service
    app.state.document_capture_attempt_repository = (
        bundle.document_capture_attempt_repository
    )
    app.state.document_repository = bundle.document_repository
    app.state.notification_repository = bundle.notification_repository
    app.state.discovery_job_repository = bundle.discovery_job_repository
    app.state.recrawl_request_repository = bundle.recrawl_request_repository
    app.state.support_repository = bundle.support_repository
    app.state.notification_service = notification_service
    app.state.notification_dispatcher = gated_notification_dispatcher
    app.state.webhook_delivery_processor = webhook_delivery_processor
    app.state.background_runtime_mode = background_runtime_mode
    app.state.webhook_delivery_processor_enabled = (
        background_runtime_mode == "embedded" and not is_sqlite_url(bundle.resolved_database_url)
    )
    app.state.discovery_dispatch_processor_enabled = discovery_loop_enabled(
        bundle.resolved_database_url,
        background_runtime_mode=background_runtime_mode,
    )
    app.state.discovery_dispatch_route_kick_enabled = discovery_route_kick_enabled(
        bundle.resolved_database_url,
        background_runtime_mode=background_runtime_mode,
    )
    app.state.support_service = SupportService(bundle.support_repository)
    app.state.webhook_service = WebhookService(
        bundle.admin_repository,
        bundle.notification_repository,
        bundle.audit_repository,
        entitlement_service,
    )
    app.state.payment_callback_secret = resolved_payment_callback_secret
    app.state.web_base_url = resolved_web_base_url
    app.state.document_ingest_service = DocumentIngestService(
        bundle.document_repository,
        entitlement_service=entitlement_service,
        project_repository=bundle.project_repository,
        capture_attempt_repository=bundle.document_capture_attempt_repository,
        notification_dispatcher=gated_notification_dispatcher,
        audit_repository=bundle.audit_repository,
    )
    app.state.project_ingest_service = ProjectIngestService(
        bundle.project_repository,
        notification_dispatcher=gated_notification_dispatcher,
    )
    app.state.project_repository = bundle.project_repository
    app.state.project_service = ProjectService(bundle.project_repository)
    app.state.profile_repository = bundle.profile_repository
    app.state.run_repository = bundle.run_repository
    app.state.run_service = RunService(
        bundle.run_repository,
        artifact_root=bundle.resolved_artifact_root,
        entitlement_service=entitlement_service,
        notification_dispatcher=gated_notification_dispatcher,
    )
    app.state.dashboard_service = DashboardService(
        bundle.project_repository,
        bundle.run_repository,
        bundle.support_repository,
    )
    app.state.rules_service = RulesService(
        bundle.profile_repository,
        entitlement_service=entitlement_service,
        notification_event_wiring_complete=True,
        admin_repository=bundle.admin_repository,
        discovery_job_repository=bundle.discovery_job_repository,
        recrawl_request_repository=bundle.recrawl_request_repository,
    )
    app.state.export_service = ExportService(
        bundle.project_repository,
        document_repository=bundle.document_repository,
        entitlement_service=entitlement_service,
        notification_dispatcher=gated_notification_dispatcher,
    )
    app.state.auth_required = bundle.resolved_auth_required
    app.state.internal_worker_token = bundle.resolved_internal_worker_token
    app.state.jwt_secret = bundle.resolved_jwt_secret
    app.state.session_cookie_name = bundle.session_cookie_name
    app.state.session_cookie_max_age_seconds = bundle.session_cookie_max_age_seconds
    app.state.session_cookie_secure = bundle.session_cookie_secure
    app.state.session_cookie_samesite = bundle.session_cookie_samesite
    app.state.discover_spawner = discover_spawner_factory(
        bundle.resolved_database_url,
        artifact_root=bundle.resolved_artifact_root,
        artifact_storage_backend=bundle.resolved_artifact_storage_backend,
        artifact_bucket=bundle.resolved_artifact_bucket,
        artifact_prefix=bundle.resolved_artifact_prefix,
        supabase_url=bundle.resolved_supabase_url,
        supabase_service_role_key=bundle.resolved_supabase_service_role_key,
        run_repository=bundle.run_repository,
        profile_repository=bundle.profile_repository,
    )
    discovery_dispatcher = discovery_dispatcher_factory(app)
    app.state.discovery_dispatcher = discovery_dispatcher
    app.state.discovery_dispatch_worker_count = get_discovery_worker_count()
    app.state.discovery_dispatch_processor = DiscoveryDispatchProcessor(
        repository=bundle.discovery_job_repository,
        dispatcher=discovery_dispatcher,
        pre_dispatch_preparer=discovery_dispatcher,
        worker_count=app.state.discovery_dispatch_worker_count,
    )
