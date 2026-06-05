"""TDD: map a discovery_jobs.trigger_type to a valid crawl_runs.trigger_type.

`crawl_runs.trigger_type` is constrained by a CHECK to
``schedule | manual | retry | backfill`` (migration 001). The discovery_jobs
queue carries richer trigger labels (``profile_created``, ``profile_updated``,
...). When a queued job is dispatched into a run, its trigger must be mapped
into the allowed set — and crucially ``schedule`` must survive so the
scheduler's "is this tenant due?" calculation keeps working.
"""

from __future__ import annotations

import pytest

from egp_api.services.run_trigger_mapping import (
    RUN_TRIGGER_TYPES,
    map_job_trigger_to_run_trigger,
)


@pytest.mark.parametrize("allowed", sorted(RUN_TRIGGER_TYPES))
def test_allowed_run_triggers_pass_through(allowed: str) -> None:
    assert map_job_trigger_to_run_trigger(allowed) == allowed


def test_schedule_survives_mapping() -> None:
    # The whole point: scheduled jobs must create `schedule` runs.
    assert map_job_trigger_to_run_trigger("schedule") == "schedule"


@pytest.mark.parametrize(
    "job_trigger", ["profile_created", "profile_updated", "manual_recrawl", "weird"]
)
def test_unknown_job_triggers_fall_back_to_manual(job_trigger: str) -> None:
    assert map_job_trigger_to_run_trigger(job_trigger) == "manual"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_falls_back_to_manual(blank: str | None) -> None:
    assert map_job_trigger_to_run_trigger(blank) == "manual"


def test_mapping_is_case_and_whitespace_insensitive() -> None:
    assert map_job_trigger_to_run_trigger("  SCHEDULE ") == "schedule"


def test_result_is_always_a_valid_run_trigger() -> None:
    for candidate in ["schedule", "manual", "retry", "backfill", "x", "", None]:
        assert map_job_trigger_to_run_trigger(candidate) in RUN_TRIGGER_TYPES
