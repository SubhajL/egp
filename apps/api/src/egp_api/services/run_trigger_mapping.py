"""Map a queued discovery job's trigger label onto a valid crawl-run trigger.

``crawl_runs.trigger_type`` is constrained by ``runs_trigger_check`` (migration
``001_initial_schema.sql``) to one of ``schedule | manual | retry | backfill``.
The ``discovery_jobs`` outbox carries richer labels (``profile_created``,
``profile_updated``, ...). When a job is dispatched into a run we must collapse
its trigger into the allowed set, while preserving ``schedule`` so the
scheduler's due-tenant calculation (which only counts ``schedule`` runs) keeps
honouring ``crawl_interval_hours``.
"""

from __future__ import annotations

# Mirrors the CHECK constraint in packages/db/src/migrations/001_initial_schema.sql.
RUN_TRIGGER_TYPES: frozenset[str] = frozenset({"schedule", "manual", "retry", "backfill"})

_FALLBACK_RUN_TRIGGER = "manual"


def map_job_trigger_to_run_trigger(job_trigger_type: str | None) -> str:
    """Return a ``crawl_runs.trigger_type``-valid value for a job trigger.

    Allowed run triggers pass through unchanged (case/whitespace-insensitive);
    anything else — including ``profile_created``/``profile_updated``, unknown
    values, and blanks — falls back to ``manual``.
    """
    normalized = (job_trigger_type or "").strip().lower()
    if normalized in RUN_TRIGGER_TYPES:
        return normalized
    return _FALLBACK_RUN_TRIGGER
