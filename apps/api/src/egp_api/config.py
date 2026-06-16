"""API configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from egp_notifications.service import SmtpConfig

BackgroundRuntimeMode = Literal["embedded", "external"]


def get_background_runtime_mode(
    override: str | None = None,
) -> BackgroundRuntimeMode:
    if override is not None:
        raw = override.strip().lower()
    else:
        raw = os.getenv("EGP_BACKGROUND_RUNTIME_MODE", "embedded").strip().lower()
    if not raw:
        return "embedded"
    if raw in {"embedded", "external"}:
        return raw
    raise RuntimeError("EGP_BACKGROUND_RUNTIME_MODE must be one of: embedded, external")


def get_discovery_worker_count(override: int | str | None = None) -> int:
    """Return the bounded discovery-dispatch worker count."""

    if override is None:
        raw: int | str = os.getenv("EGP_DISCOVERY_WORKER_COUNT", "1")
    else:
        raw = override
    try:
        worker_count = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("EGP_DISCOVERY_WORKER_COUNT must be a positive integer") from exc
    if worker_count < 1:
        raise RuntimeError("EGP_DISCOVERY_WORKER_COUNT must be a positive integer")
    return worker_count


def _get_positive_int_env(
    *,
    name: str,
    default: int,
    override: int | str | None = None,
) -> int:
    if override is None:
        raw: int | str = os.getenv(name, str(default))
    else:
        raw = override
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _get_nonnegative_int_env(
    *,
    name: str,
    default: int,
    override: int | str | None = None,
) -> int:
    if override is None:
        raw: int | str = os.getenv(name, str(default))
    else:
        raw = override
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a non-negative integer") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be a non-negative integer")
    return value


def _get_positive_float_env(
    *,
    name: str,
    default: float,
    override: float | str | None = None,
) -> float:
    if override is None:
        raw: float | str = os.getenv(name, str(default))
    else:
        raw = override
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive number")
    return value


def _get_nonnegative_float_env(
    *,
    name: str,
    default: float,
    override: float | str | None = None,
) -> float:
    if override is None:
        raw: float | str = os.getenv(name, str(default))
    else:
        raw = override
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a non-negative number") from exc
    if value < 0:
        raise RuntimeError(f"{name} must be a non-negative number")
    return value


def get_browser_cdp_port_base(override: int | str | None = None) -> int:
    """Return the first Chrome CDP port available for discovery workers."""

    port_base = _get_positive_int_env(
        name="EGP_BROWSER_CDP_PORT_BASE",
        default=9222,
        override=override,
    )
    if port_base > 65_535:
        raise RuntimeError("EGP_BROWSER_CDP_PORT_BASE must be between 1 and 65535")
    return port_base


def get_browser_cdp_port_range(override: int | str | None = None) -> int:
    """Return the number of CDP ports reserved for discovery workers."""

    return _get_positive_int_env(
        name="EGP_BROWSER_CDP_PORT_RANGE",
        default=200,
        override=override,
    )


def get_browser_nav_timeout_ms(override: int | str | None = None) -> int:
    """Page navigation timeout (ms). Raise via env for slow residential proxies."""
    return _get_positive_int_env(
        name="EGP_BROWSER_NAV_TIMEOUT_MS", default=60_000, override=override
    )


def get_browser_cloudflare_timeout_ms(override: int | str | None = None) -> int:
    """Cloudflare / search-controls settle timeout (ms). Raise for slow proxies."""
    return _get_positive_int_env(
        name="EGP_BROWSER_CLOUDFLARE_TIMEOUT_MS", default=120_000, override=override
    )


def get_browser_cloudflare_reload_retries(override: int | str | None = None) -> int:
    """Reload attempts while waiting out a Cloudflare challenge (0 = none)."""
    return _get_nonnegative_int_env(
        name="EGP_BROWSER_CLOUDFLARE_RELOAD_RETRIES", default=1, override=override
    )


def get_browser_cloudflare_operator_timeout_ms(override: int | str | None = None) -> int:
    """How long to keep Chrome open for operator-assisted Cloudflare verification."""
    return _get_nonnegative_int_env(
        name="EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS",
        default=600_000,
        override=override,
    )


def get_browser_project_detail_timeout_s(override: float | str | None = None) -> float:
    """Per-project detail/document extraction budget (seconds)."""
    return _get_positive_float_env(
        name="EGP_BROWSER_PROJECT_DETAIL_TIMEOUT_S", default=240.0, override=override
    )


def get_browser_warmup_stale_after_seconds(override: float | str | None = None) -> float:
    """Return the freshness window for on-demand persistent-profile warmups."""
    return _get_nonnegative_float_env(
        name="EGP_BROWSER_WARMUP_STALE_AFTER_SECONDS",
        default=1_800.0,
        override=override,
    )


def get_browser_predispatch_warm_seconds(override: float | str | None = None) -> float:
    """Return the post-preflight hold time for on-demand dispatch warmups."""
    return _get_nonnegative_float_env(
        name="EGP_BROWSER_PREDISPATCH_WARM_SECONDS",
        default=0.0,
        override=override,
    )


def get_browser_profile_root(override: Path | str | None = None) -> Path:
    """Return the root directory for per-run Chrome user-data directories."""

    if override is not None:
        raw = str(override).strip()
    else:
        raw = os.getenv("EGP_BROWSER_PROFILE_ROOT", "~/.egp/profiles").strip()
    return Path(raw or "~/.egp/profiles").expanduser().resolve()


BrowserProfileMode = Literal["per_run", "persistent"]


def get_browser_profile_mode(override: str | None = None) -> BrowserProfileMode:
    """Return the Chrome user-data-dir lifecycle mode.

    ``per_run`` (default) is the existing behaviour: a fresh per-run profile that
    is deleted afterwards. ``persistent`` reuses a single warmed profile dir and
    never deletes it (needed to keep Cloudflare Turnstile clearance run-to-run).
    """
    if override is not None:
        raw = override.strip().lower()
    else:
        raw = os.getenv("EGP_BROWSER_PROFILE_MODE", "per_run").strip().lower()
    if not raw:
        return "per_run"
    if raw in {"per_run", "persistent"}:
        return raw  # type: ignore[return-value]
    raise RuntimeError("EGP_BROWSER_PROFILE_MODE must be one of: per_run, persistent")


def get_browser_persistent_profile_dir(override: Path | str | None = None) -> Path | None:
    """Return the warmed persistent Chrome profile dir (persistent mode only)."""
    if override is not None:
        raw = str(override).strip()
    else:
        raw = os.getenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def get_browser_chrome_path(override: str | None = None) -> str | None:
    """Return an explicit Chrome/Chromium binary path for the worker, if set."""
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_BROWSER_CHROME_PATH", "").strip()
    return raw or None


def get_browser_proxy_server(override: str | None = None) -> str | None:
    """Return the residential proxy endpoint Chrome should route through, if set.

    Only IP-allowlist proxies are supported: a value carrying ``user:pass@``
    credentials is rejected, because Chrome's ``--proxy-server`` would expose
    them in the process list (where redaction cannot reach).
    """
    if override is not None:
        value = override.strip()
    else:
        value = os.getenv("EGP_BROWSER_PROXY_SERVER", "").strip()
    if not value:
        return None
    if "@" in value:
        raise RuntimeError(
            "EGP_BROWSER_PROXY_SERVER must not contain credentials (user:pass@); "
            "use a proxy that authenticates by IP allowlist"
        )
    return value


def get_browser_use_xvfb(override: bool | None = None) -> bool:
    """Return whether to launch headful Chrome inside a virtual display (Xvfb)."""
    if override is not None:
        return bool(override)
    raw = os.getenv("EGP_BROWSER_USE_XVFB", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_artifact_root(override: Path | None = None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    raw = os.getenv("EGP_ARTIFACT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(".data") / "artifacts").resolve()


def get_database_url(override: str | None = None, *, artifact_root: Path | None = None) -> str:
    if override is not None:
        value = override.strip()
        if value:
            return value
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        return raw
    raise RuntimeError("DATABASE_URL is required")


def get_artifact_storage_backend(override: str | None = None) -> str:
    if override:
        return override.strip()
    return os.getenv("EGP_ARTIFACT_STORE", "local").strip() or "local"


def get_artifact_bucket(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = (
        os.getenv("SUPABASE_STORAGE_BUCKET", "").strip()
        or os.getenv("AWS_S3_BUCKET", "").strip()
        or os.getenv("S3_BUCKET", "").strip()
    )
    return raw or None


def get_artifact_prefix(override: str | None = None) -> str:
    if override is not None:
        return override.strip().strip("/")
    return os.getenv("EGP_ARTIFACT_PREFIX", "").strip().strip("/") or os.getenv(
        "SUPABASE_STORAGE_PREFIX", ""
    ).strip().strip("/")


def get_supabase_url(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("SUPABASE_URL", "").strip()
    return raw or None


def get_supabase_service_role_key(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    return raw or None


def get_auth_required(override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    raw = os.getenv("EGP_AUTH_REQUIRED", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def get_jwt_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_JWT_SECRET", "").strip() or os.getenv("SUPABASE_JWT_SECRET", "").strip()
    return raw or None


def get_storage_credentials_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_STORAGE_CREDENTIALS_SECRET", "").strip()
    return raw or None


def get_google_drive_client_id(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_GOOGLE_DRIVE_CLIENT_ID", "").strip()
    return raw or None


def get_google_drive_client_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_GOOGLE_DRIVE_CLIENT_SECRET", "").strip()
    return raw or None


def get_google_drive_redirect_uri(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_GOOGLE_DRIVE_REDIRECT_URI", "").strip()
    return raw or None


def get_google_drive_scopes(override: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
    if override is not None:
        return tuple(scope.strip() for scope in override if scope.strip())
    raw = os.getenv("EGP_GOOGLE_DRIVE_SCOPES", "").strip()
    if not raw:
        return ()
    return tuple(scope.strip() for scope in raw.split(",") if scope.strip())


def get_onedrive_client_id(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_ONEDRIVE_CLIENT_ID", "").strip()
    return raw or None


def get_onedrive_client_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_ONEDRIVE_CLIENT_SECRET", "").strip()
    return raw or None


def get_onedrive_redirect_uri(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_ONEDRIVE_REDIRECT_URI", "").strip()
    return raw or None


def get_onedrive_scopes(override: list[str] | tuple[str, ...] | None = None) -> tuple[str, ...]:
    if override is not None:
        return tuple(scope.strip() for scope in override if scope.strip())
    raw = os.getenv("EGP_ONEDRIVE_SCOPES", "").strip()
    if not raw:
        return ()
    return tuple(scope.strip() for scope in raw.split(",") if scope.strip())


def get_internal_worker_token(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_INTERNAL_WORKER_TOKEN", "").strip()
    return raw or None


def get_smtp_config(override: SmtpConfig | None = None) -> SmtpConfig | None:
    if override is not None:
        return override

    host = os.getenv("EGP_SMTP_HOST", "").strip()
    if not host:
        return None

    raw_port = os.getenv("EGP_SMTP_PORT", "").strip() or "587"
    return SmtpConfig(
        host=host,
        port=int(raw_port),
        username=os.getenv("EGP_SMTP_USERNAME", "").strip(),
        password=os.getenv("EGP_SMTP_PASSWORD", "").strip(),
        from_address=os.getenv("EGP_SMTP_FROM", "").strip() or "noreply@egp-intelligence.th",
        use_tls=os.getenv("EGP_SMTP_USE_TLS", "true").strip().lower()
        not in {"0", "false", "no", "off"},
    )


def get_payment_provider(override: str | None = None) -> str:
    if override is not None:
        return override.strip()
    return os.getenv("EGP_PAYMENT_PROVIDER", "mock_promptpay").strip() or "mock_promptpay"


def get_promptpay_proxy_id(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_PROMPTPAY_PROXY_ID", "").strip()
    return raw or None


def get_payment_base_url(override: str | None = None) -> str:
    if override is not None:
        return override.strip().rstrip("/")
    return os.getenv("EGP_PAYMENT_BASE_URL", "http://localhost:8000").strip().rstrip("/")


def get_payment_callback_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_PAYMENT_CALLBACK_SECRET", "").strip()
    return raw or None


def get_opn_public_key(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_OPN_PUBLIC_KEY", "").strip()
    return raw or None


def get_opn_secret_key(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_OPN_SECRET_KEY", "").strip()
    return raw or None


def get_opn_webhook_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_OPN_WEBHOOK_SECRET", "").strip()
    return raw or None


def get_stripe_secret_key(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_STRIPE_SECRET_KEY", "").strip()
    return raw or None


def get_stripe_webhook_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_STRIPE_WEBHOOK_SECRET", "").strip()
    return raw or None


def get_stripe_publishable_key(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_STRIPE_PUBLISHABLE_KEY", "").strip()
    return raw or None


def get_line_channel_secret(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_LINE_CHANNEL_SECRET", "").strip()
    return raw or None


def get_line_channel_access_token(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    return raw or None


def get_line_admin_user_ids(override: str | None = None) -> tuple[str, ...]:
    raw = override if override is not None else os.getenv("EGP_LINE_ADMIN_USER_IDS", "")
    return tuple(part.strip() for part in str(raw).split(",") if part.strip())


def get_line_add_url(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_LINE_ADD_URL", "").strip()
    return raw or None


def get_admin_console_base_url(override: str | None = None) -> str:
    if override is not None:
        return override.strip().rstrip("/")
    return os.getenv("EGP_ADMIN_CONSOLE_BASE_URL", "").strip().rstrip("/")


def get_session_cookie_name(override: str | None = None) -> str:
    if override is not None:
        normalized = override.strip()
        return normalized or "egp_session"
    return os.getenv("EGP_SESSION_COOKIE_NAME", "egp_session").strip() or "egp_session"


def get_session_cookie_max_age_seconds(override: int | None = None) -> int:
    if override is not None:
        return max(60, int(override))
    raw = os.getenv("EGP_SESSION_MAX_AGE_SECONDS", "").strip()
    return max(60, int(raw or "604800"))


def get_session_cookie_secure(override: bool | None = None) -> bool:
    if override is not None:
        return bool(override)
    raw = os.getenv("EGP_SESSION_COOKIE_SECURE", "false").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def get_session_cookie_samesite(
    override: str | None = None,
) -> Literal["lax", "strict", "none"]:
    raw = (
        (override if override is not None else os.getenv("EGP_SESSION_COOKIE_SAMESITE", "lax"))
        .strip()
        .lower()
    )
    if raw not in {"lax", "strict", "none"}:
        return "lax"
    return raw


def get_web_allowed_origins(override: list[str] | None = None) -> list[str]:
    if override is not None:
        return [origin.strip().rstrip("/") for origin in override if origin.strip()]
    raw = os.getenv("EGP_WEB_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [part.strip().rstrip("/") for part in raw.split(",") if part.strip()]


def get_web_allow_origin_regex(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_WEB_ALLOW_ORIGIN_REGEX", "").strip()
    if raw:
        return raw
    if os.getenv("EGP_WEB_ALLOWED_ORIGINS", "").strip():
        return None
    return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def get_web_base_url(
    override: str | None = None, *, allowed_origins: list[str] | None = None
) -> str:
    if override is not None:
        normalized = override.strip().rstrip("/")
        if normalized:
            return normalized
    raw = os.getenv("EGP_WEB_BASE_URL", "").strip().rstrip("/")
    if raw:
        return raw
    if allowed_origins:
        for origin in allowed_origins:
            normalized = origin.strip().rstrip("/")
            if normalized:
                return normalized
    return "http://localhost:3000"
