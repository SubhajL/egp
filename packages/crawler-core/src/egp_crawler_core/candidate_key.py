"""Deterministic content-based candidate key for discovery result rows."""

from __future__ import annotations

import hashlib
import json


def compute_candidate_key(
    keyword: str,
    project_name: str,
    project_number: str | None = None,
    organization_name: str = "",
    budget_text: str = "",
    source_status_text: str = "",
) -> str:
    """Return a SHA-256 hex digest identifying a search-result row by CONTENT.

    PR-CANARY-03 F6/identity: the key is position-independent — a browser-death
    resume that re-scans the same row (with the logical page reset) produces
    the SAME key, so the durable ``record_accepted`` write is idempotent via
    its ON CONFLICT DO NOTHING instead of orphaning a second row.

    Identity rules:

    - keyword: ``strip()`` + ``casefold()`` (the ``normalize_keyword`` +
      casefold treatment used by discovery authorization);
    - a truthy ``project_number`` dominates;
    - otherwise the visible row signature — name, organization, budget text,
      and status text (all casefold-ONLY, no whitespace collapsing) — so two
      physically distinct rows that differ in ANY visible column get distinct
      keys even when their display names collide. Rows identical in EVERY
      visible column are content-indistinguishable by construction (a resume
      re-scan could not tell them apart either) and deliberately share a key.
    - fields are JSON-encoded before hashing, so no scraped value can inject a
      delimiter and collide two dedupe-distinct rows (the QCHECK
      ``name="x|org:y"`` attack).

    The key stays run-local in meaning: uniqueness is enforced per
    ``(tenant_id, run_id, candidate_key)``, and the keyword component keeps the
    same project distinct across keywords (the duplicate is F4's
    ``duplicate_in_run``).
    """
    normalized_keyword = keyword.strip().casefold()
    if project_number:
        parts: list[str] = ["num", str(project_number).casefold()]
    else:
        parts = [
            "name",
            project_name.casefold(),
            organization_name.casefold(),
            budget_text.casefold(),
            source_status_text.casefold(),
        ]
    payload = json.dumps(
        ["egp-candidate-key.v2", normalized_keyword, *parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
