"""Deterministic candidate key for discovery result rows."""

from __future__ import annotations

import hashlib


def compute_candidate_key(
    keyword: str,
    page_number: int,
    row_ordinal: int,
    project_name: str,
) -> str:
    """Return a SHA-256 hex digest that uniquely identifies a search-result row.

    The key is run-local: same inputs always produce the same digest, but the
    key is only meaningful within a single crawl run.
    """
    payload = f"{keyword}|{page_number}|{row_ordinal}|{project_name}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
