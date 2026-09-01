"""Helpers for exposing sanitized crawl-run summaries through public APIs."""

from __future__ import annotations


def sanitize_public_run_summary(
    summary_json: dict[str, object] | None,
) -> dict[str, object] | None:
    """Return a copy of a run summary without private canary custody data."""

    if summary_json is None:
        return None
    return {key: value for key, value in summary_json.items() if key != "canary_ingestion_evidence"}
