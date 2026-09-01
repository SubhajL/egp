"""Versioned private target contract for an exact live-ingestion canary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import unicodedata
from uuid import UUID


_TARGET_KEYS = frozenset(
    {
        "contract_version",
        "kind",
        "tenant_id",
        "job_id",
        "profile_id",
        "keyword",
        "live",
        "execution_backend",
        "browser_required",
        "max_pages_per_keyword",
    }
)


def _canonical_uuid(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a canonical UUID string")
    try:
        canonical = str(UUID(value))
    except (AttributeError, ValueError):
        raise ValueError(f"{field_name} must be a canonical UUID string") from None
    if canonical != value:
        raise ValueError(f"{field_name} must be a canonical UUID string")
    return canonical


def _validated_keyword(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("keyword must be a string")
    if not 1 <= len(value) <= 200:
        raise ValueError("keyword length is outside the allowed range")
    if value != value.strip():
        raise ValueError("keyword must already be trimmed")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("keyword must already be NFC-normalized")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("keyword must not contain control characters")
    return value


@dataclass(frozen=True, slots=True)
class ExactIngestionCanaryTarget:
    """The complete, immutable authorization scope for an exact canary."""

    contract_version: int
    kind: str
    tenant_id: str
    job_id: str
    profile_id: str
    keyword: str
    live: bool
    execution_backend: str
    browser_required: bool
    max_pages_per_keyword: int

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> ExactIngestionCanaryTarget:
        if not isinstance(payload, Mapping) or set(payload) != _TARGET_KEYS:
            raise ValueError("exact canary target keys are invalid")

        contract_version = payload["contract_version"]
        if type(contract_version) is not int or contract_version != 1:
            raise ValueError("unsupported exact canary contract version")
        kind = payload["kind"]
        if kind != "exact_ingestion_canary":
            raise ValueError("exact canary target kind is invalid")
        if not isinstance(kind, str):
            raise ValueError("exact canary target kind is invalid")

        live = payload["live"]
        if type(live) is not bool or live is not True:
            raise ValueError("exact canary target must be live")
        execution_backend = payload["execution_backend"]
        if execution_backend != "legacy" or not isinstance(execution_backend, str):
            raise ValueError("exact canary target backend is invalid")
        browser_required = payload["browser_required"]
        if type(browser_required) is not bool or browser_required is not True:
            raise ValueError("exact canary target requires a browser")
        max_pages = payload["max_pages_per_keyword"]
        if type(max_pages) is not int or not 1 <= max_pages <= 15:
            raise ValueError("exact canary page cap is invalid")

        return cls(
            contract_version=contract_version,
            kind=kind,
            tenant_id=_canonical_uuid(payload["tenant_id"], field_name="tenant_id"),
            job_id=_canonical_uuid(payload["job_id"], field_name="job_id"),
            profile_id=_canonical_uuid(payload["profile_id"], field_name="profile_id"),
            keyword=_validated_keyword(payload["keyword"]),
            live=live,
            execution_backend=execution_backend,
            browser_required=browser_required,
            max_pages_per_keyword=max_pages,
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "kind": self.kind,
            "tenant_id": self.tenant_id,
            "job_id": self.job_id,
            "profile_id": self.profile_id,
            "keyword": self.keyword,
            "live": self.live,
            "execution_backend": self.execution_backend,
            "browser_required": self.browser_required,
            "max_pages_per_keyword": self.max_pages_per_keyword,
        }

    def canonical_digest(self) -> str:
        canonical_json = json.dumps(
            self.to_mapping(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical_json).hexdigest()
