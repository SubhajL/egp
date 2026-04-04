"""API configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

from egp_notifications.service import SmtpConfig


def get_artifact_root(override: Path | None = None) -> Path:
    if override is not None:
        return override
    raw = os.getenv("EGP_ARTIFACT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(".data") / "artifacts"


def get_database_url(override: str | None = None, *, artifact_root: Path | None = None) -> str:
    if override:
        return override.strip()
    raw = os.getenv("DATABASE_URL", "").strip()
    if raw:
        return raw
    base = artifact_root if artifact_root is not None else get_artifact_root()
    return f"sqlite+pysqlite:///{base / 'document_metadata.sqlite3'}"


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
