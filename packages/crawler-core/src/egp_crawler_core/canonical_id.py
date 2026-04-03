"""Canonical project identity helpers for Phase 1 deduplication."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import re


def _normalize_text(value: object) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"\s+", " ", text)


def _normalize_budget(value: object) -> str:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return ""
    try:
        normalized = Decimal(text).normalize()
    except InvalidOperation:
        return _normalize_text(text)
    return format(normalized, "f").rstrip("0").rstrip(".") or "0"


def _normalize_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _normalize_text(value)


def generate_canonical_fingerprint(
    *,
    organization_name: object,
    project_name: object,
    proposal_submission_date: object,
    budget_amount: object,
) -> str:
    components = [
        _normalize_text(organization_name),
        _normalize_text(project_name),
        _normalize_date(proposal_submission_date),
        _normalize_budget(budget_amount),
    ]
    payload = "|".join(components).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def generate_canonical_id(
    *,
    project_number: object,
    organization_name: object,
    project_name: object,
    proposal_submission_date: object,
    budget_amount: object,
) -> str:
    normalized_project_number = str(project_number or "").strip()
    if normalized_project_number:
        return f"project-number:{normalized_project_number}"

    fingerprint = generate_canonical_fingerprint(
        organization_name=organization_name,
        project_name=project_name,
        proposal_submission_date=proposal_submission_date,
        budget_amount=budget_amount,
    )
    return f"fingerprint:{fingerprint}"


def build_project_aliases(
    *,
    project_number: object,
    search_name: object,
    detail_name: object,
    organization_name: object,
    project_name: object,
    proposal_submission_date: object,
    budget_amount: object,
) -> list[tuple[str, str]]:
    aliases: list[tuple[str, str]] = []

    normalized_project_number = str(project_number or "").strip()
    normalized_search_name = str(search_name or "").strip()
    normalized_detail_name = str(detail_name or project_name or "").strip()

    if normalized_project_number:
        aliases.append(("project_number", normalized_project_number))
    if normalized_search_name:
        aliases.append(("search_name", normalized_search_name))
    if normalized_detail_name:
        aliases.append(("detail_name", normalized_detail_name))

    fingerprint = generate_canonical_fingerprint(
        organization_name=organization_name,
        project_name=project_name,
        proposal_submission_date=proposal_submission_date,
        budget_amount=budget_amount,
    )
    aliases.append(("fingerprint", fingerprint))

    deduped_aliases: list[tuple[str, str]] = []
    seen = set()
    for alias in aliases:
        if alias in seen:
            continue
        seen.add(alias)
        deduped_aliases.append(alias)
    return deduped_aliases
