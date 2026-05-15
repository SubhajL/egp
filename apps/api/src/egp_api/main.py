"""Packaged FastAPI application."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

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
    get_web_allow_origin_regex,
    get_web_allowed_origins,
)
from egp_api.services.discovery_dispatch import NonRetriableDiscoveryDispatchError
from egp_api.services.google_drive import (
    GoogleDriveOAuthConfig,
)
from egp_api.services.onedrive import (
    OneDriveOAuthConfig,
)
from egp_api.services.payment_provider import PaymentProvider
from egp_notifications.service import EmailSender, SmtpConfig


DISCOVER_WORKER_TIMEOUT_SECONDS = 3 * 60 * 60


_logger = logging.getLogger(__name__)


def _resolve_browser_settings_payload(
    *,
    profile_repository,
    tenant_id: str,
    profile_id: str,
) -> dict[str, object] | None:
    if profile_repository is None:
        return None
    try:
        detail = profile_repository.get_profile_detail(
            tenant_id=tenant_id,
            profile_id=profile_id,
        )
    except Exception:
        _logger.warning(
            "Failed to resolve crawl profile settings for discover spawn (tenant_id=%s profile_id=%s)",
            tenant_id,
            profile_id,
            exc_info=True,
        )
        return None
    if detail is None:
        return None
    max_pages_per_keyword = getattr(detail.profile, "max_pages_per_keyword", None)
    if max_pages_per_keyword is None:
        return None
    try:
        normalized_max_pages = max(1, int(max_pages_per_keyword))
    except (TypeError, ValueError):
        _logger.warning(
            "Invalid max_pages_per_keyword on crawl profile (tenant_id=%s profile_id=%s value=%r)",
            tenant_id,
            profile_id,
            max_pages_per_keyword,
        )
        return None
    return {"max_pages_per_keyword": normalized_max_pages}


def _make_discover_spawner(
    database_url: str,
    *,
    artifact_root: Path | None = None,
    run_repository=None,
    profile_repository=None,
) -> Callable[..., None]:
    """Return a function that spawns a worker subprocess for a single keyword.

    The spawner is fire-and-forget: it starts the worker, writes the JSON
    payload to stdin, and waits for it to finish (inside a BackgroundTask
    thread so the API response is not blocked).
    """

    class _NoopRunRepository:
        def create_run(self, **kwargs) -> None:
            del kwargs

        def fail_run_if_active(self, *args, **kwargs) -> None:
            del args, kwargs
            return None

        def update_run_summary(self, run_id: str, *, summary_json: dict[str, object] | None):
            del run_id, summary_json

    resolved_artifact_root = (artifact_root or Path("artifacts")).expanduser().resolve()
    resolved_run_repository = run_repository or _NoopRunRepository()

    def _stderr_preview(stderr: bytes | str | None, *, limit: int = 500) -> str | None:
        if stderr is None:
            return None
        if isinstance(stderr, bytes):
            text = stderr.decode("utf-8", errors="replace")
        else:
            text = str(stderr)
        normalized = text.strip()
        if not normalized:
            return None
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."

    def _parse_non_retriable_error(
        stderr: bytes | str | None,
    ) -> NonRetriableDiscoveryDispatchError | None:
        if stderr is None:
            return None
        if isinstance(stderr, bytes):
            text = stderr.decode("utf-8", errors="replace")
        else:
            text = str(stderr)
        for raw_line in reversed(text.splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("error_type") != "entitlement_denied":
                continue
            detail = str(payload.get("detail") or "discover entitlement denied").strip()
            return NonRetriableDiscoveryDispatchError(detail)
        return None

    class _DiscoverSpawnError(RuntimeError):
        pass

    def _safe_update_run_summary(
        *,
        run_id: str,
        summary_json: dict[str, object],
    ) -> None:
        try:
            resolved_run_repository.update_run_summary(
                run_id,
                summary_json=summary_json,
            )
        except Exception:
            _logger.warning(
                "Failed to persist discover run summary metadata (run_id=%s)",
                run_id,
                exc_info=True,
            )

    def _read_log_tail(log_path: Path | None, *, limit: int = 8192) -> str | None:
        if log_path is None or not log_path.is_file():
            return None
        data = log_path.read_bytes()
        if len(data) > limit:
            data = data[-limit:]
        return data.decode("utf-8", errors="replace")

    def _mark_active_run_failed(
        *,
        run_id: str,
        error: str,
        failure_reason: str,
    ) -> None:
        try:
            failed_run = resolved_run_repository.fail_run_if_active(
                run_id,
                error=error,
                failure_reason=failure_reason,
            )
        except Exception:
            _logger.warning(
                "Failed to mark discover run failed (run_id=%s failure_reason=%s)",
                run_id,
                failure_reason,
                exc_info=True,
            )
            return
        if failed_run is not None:
            _logger.warning(
                "Marked discover run %s failed (%s)",
                failed_run.id,
                failure_reason,
            )

    def _worker_termination_error(
        *,
        returncode: int,
        run_id: str,
        keyword: str,
    ) -> NonRetriableDiscoveryDispatchError | None:
        if returncode >= 0:
            return None
        signal_number = abs(int(returncode))
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"SIG{signal_number}"
        error_message = (
            f"discover worker terminated by signal {signal_name} for keyword {keyword!r}"
        )
        _mark_active_run_failed(
            run_id=run_id,
            error=error_message,
            failure_reason="worker_terminated",
        )
        return NonRetriableDiscoveryDispatchError(error_message)

    def spawn_discover(
        *,
        tenant_id: str,
        profile_id: str,
        profile_type: str,
        keyword: str,
    ) -> None:
        run_id = str(uuid4())
        browser_settings = _resolve_browser_settings_payload(
            profile_repository=profile_repository,
            tenant_id=tenant_id,
            profile_id=profile_id,
        )
        resolved_run_repository.create_run(
            tenant_id=tenant_id,
            profile_id=profile_id,
            trigger_type="manual",
            run_id=run_id,
        )
        log_path = (
            resolved_artifact_root / "tenants" / tenant_id / "runs" / run_id / "worker.log"
        ).resolve()
        log_handle = None
        if resolved_artifact_root is not None:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_handle = log_path.open("ab")
            except Exception:
                _logger.warning(
                    "Failed to create discover worker log file (run_id=%s)",
                    run_id,
                    exc_info=True,
                )
                log_path = None
        payload = json.dumps(
            {
                "command": "discover",
                "database_url": database_url,
                "artifact_root": str(resolved_artifact_root),
                "tenant_id": tenant_id,
                "run_id": run_id,
                "profile_id": profile_id,
                "keyword": keyword,
                "profile": profile_type,
                "trigger_type": "manual",
                "live": True,
                "live_include_documents": True,
                **({"browser_settings": browser_settings} if browser_settings is not None else {}),
            },
            ensure_ascii=False,
        ).encode()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "egp_worker.main"],
                stdin=subprocess.PIPE,
                stdout=log_handle or subprocess.DEVNULL,
                stderr=log_handle or subprocess.PIPE,
            )
            _safe_update_run_summary(
                run_id=run_id,
                summary_json={
                    **({"worker_log_path": str(log_path)} if log_path is not None else {}),
                    "worker_owner_pid": os.getpid(),
                    **(
                        {"worker_pid": proc.pid}
                        if isinstance(getattr(proc, "pid", None), int)
                        else {}
                    ),
                },
            )
            _, stderr = proc.communicate(input=payload, timeout=DISCOVER_WORKER_TIMEOUT_SECONDS)
            if log_handle is not None:
                log_handle.flush()
            stderr_text = (_read_log_tail(log_path) if log_path is not None else None) or stderr
            if proc.returncode not in {0, None}:
                preview = _stderr_preview(stderr_text)
                _logger.warning(
                    "Discover worker exited non-zero for keyword %r (tenant_id=%s profile_id=%s returncode=%s stderr=%r)",
                    keyword,
                    tenant_id,
                    profile_id,
                    proc.returncode,
                    preview,
                )
                terminated = _worker_termination_error(
                    returncode=int(proc.returncode),
                    run_id=run_id,
                    keyword=keyword,
                )
                if terminated is not None:
                    raise terminated
                non_retriable = _parse_non_retriable_error(stderr_text)
                if non_retriable is not None:
                    raise non_retriable
                raise _DiscoverSpawnError(
                    f"discover worker exited non-zero for keyword {keyword!r}"
                )
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            _, stderr = proc.communicate()
            if log_handle is not None:
                log_handle.flush()
            stderr_text = (_read_log_tail(log_path) if log_path is not None else None) or (
                stderr or exc.stderr
            )
            preview = _stderr_preview(stderr_text)
            error_message = f"discover worker timed out for keyword {keyword!r}"
            _logger.warning(
                "Discover worker timed out for keyword %r (tenant_id=%s profile_id=%s timeout_seconds=%s stderr=%r)",
                keyword,
                tenant_id,
                profile_id,
                exc.timeout,
                preview,
            )
            _mark_active_run_failed(
                run_id=run_id,
                error=error_message,
                failure_reason="worker_timeout",
            )
            raise _DiscoverSpawnError(error_message) from exc
        except _DiscoverSpawnError:
            raise
        except Exception:
            _logger.warning(
                "Failed to spawn discover for keyword %r (tenant_id=%s profile_id=%s)",
                keyword,
                tenant_id,
                profile_id,
                exc_info=True,
            )
            raise
        finally:
            if log_handle is not None:
                log_handle.close()

    return spawn_discover


def _make_discovery_dispatcher(app: FastAPI) -> Callable[..., None]:
    def dispatch(
        *,
        tenant_id: str,
        profile_id: str,
        profile_type: str,
        keyword: str,
    ) -> None:
        spawner = getattr(app.state, "discover_spawner", None)
        if spawner is None:
            return
        spawner(
            tenant_id=tenant_id,
            profile_id=profile_id,
            profile_type=profile_type,
            keyword=keyword,
        )

    return dispatch


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
) -> FastAPI:
    resolved_web_allowed_origins = get_web_allowed_origins(web_allowed_origins)
    resolved_web_allow_origin_regex = get_web_allow_origin_regex(None)
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
    )
    configure_http_pipeline(
        app=app,
        resolved_web_allowed_origins=resolved_web_allowed_origins,
        resolved_web_allow_origin_regex=resolved_web_allow_origin_regex,
    )
    return app
