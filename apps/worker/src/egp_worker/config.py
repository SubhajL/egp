"""Worker configuration helpers."""

from __future__ import annotations

import os


def get_internal_api_base_url(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip().rstrip("/")
        return value or None
    raw = (
        os.getenv("EGP_INTERNAL_API_BASE_URL", "").strip().rstrip("/")
        or os.getenv("EGP_API_BASE_URL", "").strip().rstrip("/")
    )
    return raw or None


def get_internal_worker_token(override: str | None = None) -> str | None:
    if override is not None:
        value = override.strip()
        return value or None
    raw = os.getenv("EGP_INTERNAL_WORKER_TOKEN", "").strip() or os.getenv(
        "EGP_API_BEARER_TOKEN", ""
    ).strip()
    return raw or None


def get_internal_api_timeout_seconds(override: float | None = None) -> float:
    if override is not None:
        return max(0.1, float(override))
    raw = os.getenv("EGP_INTERNAL_API_TIMEOUT_SECONDS", "").strip() or os.getenv(
        "EGP_API_TIMEOUT_SECONDS", ""
    ).strip()
    return max(0.1, float(raw or "10"))
