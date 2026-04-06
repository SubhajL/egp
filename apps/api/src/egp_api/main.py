"""Packaged FastAPI application."""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from egp_api.auth import authenticate_request
from egp_api.config import (
    get_auth_required,
    get_artifact_bucket,
    get_artifact_prefix,
    get_artifact_root,
    get_artifact_storage_backend,
    get_database_url,
    get_internal_worker_token,
    get_jwt_secret,
    get_opn_public_key,
    get_opn_secret_key,
    get_payment_base_url,
    get_payment_callback_secret,
    get_payment_provider,
    get_promptpay_proxy_id,
    get_session_cookie_max_age_seconds,
    get_session_cookie_name,
    get_session_cookie_samesite,
    get_session_cookie_secure,
    get_smtp_config,
    get_supabase_service_role_key,
    get_supabase_url,
    get_web_allow_origin_regex,
    get_web_base_url,
    get_web_allowed_origins,
)
from egp_api.routes.auth import router as auth_router
from egp_api.routes.admin import router as admin_router
from egp_api.routes.billing import router as billing_router
from egp_api.routes.dashboard import router as dashboard_router
from egp_api.routes.documents import router as documents_router
from egp_api.routes.exports import router as exports_router
from egp_api.routes.project_ingest import router as project_ingest_router
from egp_api.routes.projects import router as projects_router
from egp_api.routes.rules import router as rules_router
from egp_api.routes.runs import router as runs_router
from egp_api.routes.webhooks import router as webhooks_router
from egp_api.services.admin_service import AdminService
from egp_api.services.audit_service import AuditService
from egp_api.services.auth_service import AuthService
from egp_api.services.billing_service import BillingService
from egp_api.services.dashboard_service import DashboardService
from egp_api.services.document_ingest_service import DocumentIngestService
from egp_api.services.entitlement_service import (
    EntitlementAwareNotificationDispatcher,
    TenantEntitlementService,
)
from egp_api.services.export_service import ExportService
from egp_api.services.payment_provider import PaymentProvider, build_payment_provider
from egp_api.services.project_ingest_service import ProjectIngestService
from egp_api.services.project_service import ProjectService
from egp_api.services.rules_service import RulesService
from egp_api.services.run_service import RunService
from egp_api.services.support_service import SupportService
from egp_api.services.webhook_service import WebhookService
from egp_db.connection import create_shared_engine
from egp_db.db_utils import is_sqlite_url
from egp_db.repositories.audit_repo import create_audit_repository
from egp_db.repositories.admin_repo import create_admin_repository
from egp_db.repositories.auth_repo import create_auth_repository
from egp_db.repositories.billing_repo import create_billing_repository
from egp_db.repositories.document_repo import create_document_repository
from egp_db.repositories.notification_repo import create_notification_repository
from egp_db.repositories.profile_repo import create_profile_repository
from egp_db.repositories.project_repo import create_project_repository
from egp_db.repositories.run_repo import create_run_repository
from egp_db.repositories.support_repo import create_support_repository
from egp_notifications.dispatcher import NotificationDispatcher
from egp_notifications.service import EmailSender, NotificationService, SmtpConfig
from egp_notifications.webhook_delivery import WebhookDeliveryProcessor, WebhookDeliveryService


async def _run_webhook_delivery_loop(
    *,
    processor: WebhookDeliveryProcessor,
    stop_event: asyncio.Event,
    poll_interval_seconds: float,
) -> None:
    while not stop_event.is_set():
        processor.process_pending()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, poll_interval_seconds))
        except TimeoutError:
            continue


def create_app(
    *,
    artifact_root: Path | None = None,
    database_url: str | None = None,
    artifact_storage_backend: str | None = None,
    artifact_bucket: str | None = None,
    artifact_prefix: str | None = None,
    s3_client=None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_client=None,
    auth_required: bool | None = None,
    jwt_secret: str | None = None,
    smtp_config: SmtpConfig | None = None,
    notification_email_sender: EmailSender | None = None,
    payment_provider: PaymentProvider | None = None,
    payment_base_url: str | None = None,
    promptpay_proxy_id: str | None = None,
    opn_public_key: str | None = None,
    opn_secret_key: str | None = None,
    payment_callback_secret: str | None = None,
    web_allowed_origins: list[str] | None = None,
    internal_worker_token: str | None = None,
) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        poller_task = None
        poller_stop_event = None
        processor = getattr(app.state, "webhook_delivery_processor", None)
        if processor is not None and getattr(
            app.state, "webhook_delivery_processor_enabled", False
        ):
            poller_stop_event = asyncio.Event()
            poller_task = asyncio.create_task(
                _run_webhook_delivery_loop(
                    processor=processor,
                    stop_event=poller_stop_event,
                    poll_interval_seconds=1.0,
                )
            )
        try:
            yield
        finally:
            if poller_stop_event is not None:
                poller_stop_event.set()
            if poller_task is not None:
                poller_task.cancel()
                with suppress(asyncio.CancelledError):
                    await poller_task

    app = FastAPI(
        title="e-GP Intelligence Platform",
        version="0.1.0",
        description="Thailand public procurement monitoring API",
        lifespan=lifespan,
    )

    resolved_web_allowed_origins = get_web_allowed_origins(web_allowed_origins)
    resolved_web_allow_origin_regex = get_web_allow_origin_regex(None)

    def cors_headers_for_origin(origin: str | None) -> dict[str, str]:
        normalized_origin = str(origin or "").strip().rstrip("/")
        if not normalized_origin:
            return {}
        if normalized_origin in resolved_web_allowed_origins or (
            resolved_web_allow_origin_regex
            and re.fullmatch(resolved_web_allow_origin_regex, normalized_origin)
        ):
            return {
                "Access-Control-Allow-Origin": normalized_origin,
                "Access-Control-Allow-Credentials": "true",
                "Vary": "Origin",
            }
        return {}

    if resolved_web_allowed_origins or resolved_web_allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_web_allowed_origins,
            allow_origin_regex=resolved_web_allow_origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    resolved_artifact_root = get_artifact_root(artifact_root)
    resolved_database_url = get_database_url(database_url, artifact_root=resolved_artifact_root)
    resolved_auth_required = get_auth_required(auth_required)
    resolved_internal_worker_token = get_internal_worker_token(internal_worker_token)
    resolved_jwt_secret = get_jwt_secret(jwt_secret)
    session_cookie_name = get_session_cookie_name(None)
    session_cookie_max_age_seconds = get_session_cookie_max_age_seconds(None)
    session_cookie_secure = get_session_cookie_secure(None)
    session_cookie_samesite = get_session_cookie_samesite(None)
    shared_engine = create_shared_engine(resolved_database_url)
    repository = create_document_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
        storage_backend=get_artifact_storage_backend(artifact_storage_backend),
        artifact_root=resolved_artifact_root,
        s3_bucket=get_artifact_bucket(artifact_bucket),
        s3_prefix=get_artifact_prefix(artifact_prefix),
        s3_client=s3_client,
        supabase_url=get_supabase_url(supabase_url),
        supabase_service_role_key=get_supabase_service_role_key(supabase_service_role_key),
        supabase_client=supabase_client,
    )
    project_repository = create_project_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    billing_repository = create_billing_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    admin_repository = create_admin_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    auth_repository = create_auth_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    audit_repository = create_audit_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    profile_repository = create_profile_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    run_repository = create_run_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    notification_repository = create_notification_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    support_repository = create_support_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    notification_service = NotificationService(
        smtp_config=get_smtp_config(smtp_config),
        in_app_store=notification_repository,
        email_sender=notification_email_sender,
    )
    webhook_delivery_service = WebhookDeliveryService(repository=notification_repository)
    webhook_delivery_processor = WebhookDeliveryProcessor(repository=notification_repository)
    notification_dispatcher = NotificationDispatcher(
        service=notification_service,
        recipient_resolver=notification_repository,
        webhook_delivery_service=webhook_delivery_service,
    )
    entitlement_service = TenantEntitlementService(
        billing_repository,
        profile_repository,
    )
    resolved_payment_provider = payment_provider or build_payment_provider(
        provider_name=get_payment_provider(None),
        base_url=get_payment_base_url(payment_base_url),
        promptpay_proxy_id=get_promptpay_proxy_id(promptpay_proxy_id),
        opn_public_key=get_opn_public_key(opn_public_key),
        opn_secret_key=get_opn_secret_key(opn_secret_key),
    )
    resolved_payment_callback_secret = get_payment_callback_secret(payment_callback_secret)
    if resolved_payment_callback_secret is None:
        raise RuntimeError("payment callback secret is required")
    gated_notification_dispatcher = EntitlementAwareNotificationDispatcher(
        notification_dispatcher,
        entitlement_service,
    )
    auth_service = AuthService(
        auth_repository,
        admin_repository,
        session_max_age_seconds=session_cookie_max_age_seconds,
        notification_service=notification_service,
        notification_repository=notification_repository,
        billing_service=BillingService(
            billing_repository,
            payment_provider=resolved_payment_provider,
        ),
        web_base_url=get_web_base_url(None, allowed_origins=resolved_web_allowed_origins),
    )
    app.state.db_engine = shared_engine
    app.state.admin_repository = admin_repository
    app.state.auth_repository = auth_repository
    app.state.audit_repository = audit_repository
    app.state.auth_service = auth_service
    app.state.billing_repository = billing_repository
    app.state.audit_service = AuditService(audit_repository)
    app.state.admin_service = AdminService(
        admin_repository,
        notification_repository,
        billing_repository,
        audit_repository,
    )
    app.state.billing_service = BillingService(
        billing_repository,
        payment_provider=resolved_payment_provider,
    )
    app.state.entitlement_service = entitlement_service
    app.state.document_repository = repository
    app.state.notification_repository = notification_repository
    app.state.support_repository = support_repository
    app.state.notification_service = notification_service
    app.state.notification_dispatcher = gated_notification_dispatcher
    app.state.webhook_delivery_processor = webhook_delivery_processor
    app.state.webhook_delivery_processor_enabled = not is_sqlite_url(resolved_database_url)
    app.state.support_service = SupportService(support_repository)
    app.state.webhook_service = WebhookService(
        admin_repository,
        notification_repository,
        audit_repository,
    )
    app.state.payment_callback_secret = resolved_payment_callback_secret
    app.state.document_ingest_service = DocumentIngestService(
        repository,
        entitlement_service=entitlement_service,
        project_repository=project_repository,
        notification_dispatcher=gated_notification_dispatcher,
        audit_repository=audit_repository,
    )
    app.state.project_ingest_service = ProjectIngestService(
        project_repository,
        notification_dispatcher=gated_notification_dispatcher,
    )
    app.state.project_repository = project_repository
    app.state.project_service = ProjectService(project_repository)
    app.state.profile_repository = profile_repository
    app.state.run_repository = run_repository
    app.state.run_service = RunService(
        run_repository,
        entitlement_service=entitlement_service,
        notification_dispatcher=gated_notification_dispatcher,
    )
    app.state.dashboard_service = DashboardService(
        project_repository,
        run_repository,
        support_repository,
    )
    app.state.rules_service = RulesService(
        profile_repository,
        entitlement_service=entitlement_service,
        notification_event_wiring_complete=True,
        admin_repository=admin_repository,
    )
    app.state.export_service = ExportService(
        project_repository,
        entitlement_service=entitlement_service,
        notification_dispatcher=gated_notification_dispatcher,
    )
    app.state.auth_required = resolved_auth_required
    app.state.internal_worker_token = resolved_internal_worker_token
    app.state.jwt_secret = resolved_jwt_secret
    app.state.session_cookie_name = session_cookie_name
    app.state.session_cookie_max_age_seconds = session_cookie_max_age_seconds
    app.state.session_cookie_secure = session_cookie_secure
    app.state.session_cookie_samesite = session_cookie_samesite

    @app.middleware("http")
    async def auth_middleware(request, call_next):
        if request.method == "OPTIONS":
            request.state.auth_context = None
            headers = cors_headers_for_origin(request.headers.get("origin"))
            if headers:
                headers.update(
                    {
                        "Access-Control-Allow-Methods": "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT",
                        "Access-Control-Max-Age": "600",
                    }
                )
                requested_headers = request.headers.get("access-control-request-headers")
                if requested_headers:
                    headers["Access-Control-Allow-Headers"] = requested_headers
            return Response(status_code=200, headers=headers)
        if (
            request.url.path
            in {
                "/health",
                "/openapi.json",
                "/docs",
                "/docs/oauth2-redirect",
                "/redoc",
                "/v1/auth/login",
                "/v1/auth/logout",
                "/v1/auth/register",
                "/v1/auth/password/forgot",
                "/v1/auth/password/reset",
                "/v1/auth/invite/accept",
                "/v1/auth/email/verify",
                "/internal/worker/projects/discover",
                "/internal/worker/projects/close-check",
            }
            or (
                request.url.path.startswith("/v1/billing/payment-requests/")
                and request.url.path.endswith("/callbacks")
            )
            or request.url.path == "/v1/billing/providers/opn/webhooks"
        ):
            request.state.auth_context = None
            return await call_next(request)

        if not app.state.auth_required:
            request.state.auth_context = None
            return await call_next(request)

        try:
            request.state.auth_context = authenticate_request(
                authorization_header=request.headers.get("authorization"),
                session_token=request.cookies.get(app.state.session_cookie_name),
                jwt_secret=app.state.jwt_secret,
                session_authenticator=app.state.auth_service.authenticate_session,
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "invalid bearer token")
            return JSONResponse(
                status_code=status_code,
                content={"detail": detail},
                headers=cors_headers_for_origin(request.headers.get("origin")),
            )
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(billing_router)
    app.include_router(dashboard_router)
    app.include_router(documents_router)
    app.include_router(exports_router)
    app.include_router(project_ingest_router)
    app.include_router(projects_router)
    app.include_router(rules_router)
    app.include_router(runs_router)
    app.include_router(webhooks_router)
    return app
