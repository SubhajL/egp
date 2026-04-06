"""API configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from egp_notifications.service import SmtpConfig


def get_artifact_root(override: Path | None = None) -> Path:
    if override is not None:
        return override
    raw = os.getenv("EGP_ARTIFACT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(".data") / "artifacts"


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
