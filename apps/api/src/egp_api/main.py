"""Packaged FastAPI application."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from egp_api.bootstrap.background import (
    build_lifespan,
    discovery_dispatch_loop_enabled_for_database_url as _discovery_dispatch_loop_enabled_for_database_url,
    discovery_dispatch_route_kick_enabled as _discovery_dispatch_route_kick_enabled,
)
from egp_api.bootstrap.middleware import configure_http_pipeline
from egp_api.bootstrap.repositories import build_repository_bundle
from egp_api.bootstrap.services import configure_services
from egp_api.config import (
    BackgroundRuntimeMode,
    get_background_runtime_mode,
    get_web_allow_origin_regex,
    get_web_allowed_origins,
)
from egp_api.services.discovery_dispatch import DiscoveryDispatcher, DiscoveryDispatchRequest
from egp_api.services.discovery_worker_dispatcher import (
    DISCOVER_WORKER_TIMEOUT_SECONDS as _DISCOVER_WORKER_TIMEOUT_SECONDS,
    SubprocessDiscoveryDispatcher,
)
from egp_api.services.google_drive import (
    GoogleDriveOAuthConfig,
)
from egp_api.services.onedrive import (
    OneDriveOAuthConfig,
)
from egp_api.services.payment_provider import PaymentProvider
from egp_notifications.service import EmailSender, SmtpConfig


_logger = logging.getLogger(__name__)
DISCOVER_WORKER_TIMEOUT_SECONDS = _DISCOVER_WORKER_TIMEOUT_SECONDS


def _make_discover_spawner(
    database_url: str,
    *,
    artifact_root: Path | None = None,
    run_repository=None,
    profile_repository=None,
) -> SubprocessDiscoveryDispatcher:
    """Return the subprocess-backed discovery dispatcher as a legacy callable spawner."""

    return SubprocessDiscoveryDispatcher(
        database_url,
        artifact_root=artifact_root,
        run_repository=run_repository,
        profile_repository=profile_repository,
    )


def _make_discovery_dispatcher(
    app: FastAPI,
) -> DiscoveryDispatcher:
    class _AppStateDiscoveryDispatcher:
        def dispatch(self, request: DiscoveryDispatchRequest) -> None:
            spawner = getattr(app.state, "discover_spawner", None)
            if spawner is None:
                return
            spawner(
                tenant_id=request.tenant_id,
                profile_id=request.profile_id,
                profile_type=request.profile_type,
                keyword=request.keyword,
            )

    return _AppStateDiscoveryDispatcher()


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
    storage_credentials_secret: str | None = None,
    google_drive_oauth_config: GoogleDriveOAuthConfig | None = None,
    google_drive_client=None,
    onedrive_oauth_config: OneDriveOAuthConfig | None = None,
    onedrive_client=None,
    smtp_config: SmtpConfig | None = None,
    notification_email_sender: EmailSender | None = None,
    payment_provider: PaymentProvider | None = None,
    payment_base_url: str | None = None,
    promptpay_proxy_id: str | None = None,
    opn_public_key: str | None = None,
    opn_secret_key: str | None = None,
    opn_webhook_secret: str | None = None,
    payment_callback_secret: str | None = None,
    web_allowed_origins: list[str] | None = None,
    internal_worker_token: str | None = None,
    background_runtime_mode: BackgroundRuntimeMode | str | None = None,
) -> FastAPI:
    resolved_web_allowed_origins = get_web_allowed_origins(web_allowed_origins)
    resolved_web_allow_origin_regex = get_web_allow_origin_regex(None)
    resolved_background_runtime_mode = get_background_runtime_mode(background_runtime_mode)
    repository_bundle = build_repository_bundle(
        artifact_root=artifact_root,
        database_url=database_url,
        artifact_storage_backend=artifact_storage_backend,
        artifact_bucket=artifact_bucket,
        artifact_prefix=artifact_prefix,
        s3_client=s3_client,
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_service_role_key,
        supabase_client=supabase_client,
        auth_required=auth_required,
        jwt_secret=jwt_secret,
        storage_credentials_secret=storage_credentials_secret,
        google_drive_oauth_config=google_drive_oauth_config,
        google_drive_client=google_drive_client,
        onedrive_oauth_config=onedrive_oauth_config,
        onedrive_client=onedrive_client,
        internal_worker_token=internal_worker_token,
    )
    app = FastAPI(
        title="e-GP Intelligence Platform",
        version="0.1.0",
        description="Thailand public procurement monitoring API",
        lifespan=build_lifespan(logger=_logger),
    )
    configure_services(
        app=app,
        bundle=repository_bundle,
        smtp_config=smtp_config,
        notification_email_sender=notification_email_sender,
        payment_provider=payment_provider,
        payment_base_url=payment_base_url,
        promptpay_proxy_id=promptpay_proxy_id,
        opn_public_key=opn_public_key,
        opn_secret_key=opn_secret_key,
        opn_webhook_secret=opn_webhook_secret,
        payment_callback_secret=payment_callback_secret,
        resolved_web_allowed_origins=resolved_web_allowed_origins,
        discover_spawner_factory=_make_discover_spawner,
        discovery_dispatcher_factory=_make_discovery_dispatcher,
        discovery_loop_enabled=_discovery_dispatch_loop_enabled_for_database_url,
        discovery_route_kick_enabled=_discovery_dispatch_route_kick_enabled,
        background_runtime_mode=resolved_background_runtime_mode,
    )
    configure_http_pipeline(
        app=app,
        resolved_web_allowed_origins=resolved_web_allowed_origins,
        resolved_web_allow_origin_regex=resolved_web_allow_origin_regex,
    )
    return app
