"""TDD: enqueue-only scheduled discovery producer (no browser).

Once the Lightsail in-box ``discovery-executor`` is disabled (off-box crawl
topology), nothing fires interval-based crawls. This executor reuses the
existing scheduler planning but, instead of running a browser, inserts
``schedule`` rows into the ``discovery_jobs`` outbox for the off-box Mac
crawler to claim. It must enqueue idempotently and tag every job ``schedule``.
"""

from __future__ import annotations

from types import SimpleNamespace

from egp_api.executors.scheduled_discovery_enqueue import (
    enqueue_scheduled_discovery_jobs,
    main,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROFILE_ID = "22222222-2222-2222-2222-222222222222"


class _FakeJobStore:
    """Records enqueue calls; reports `created=False` for a repeated pending key."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._seen: set[tuple[str, str, str, str]] = set()

    def create_pending_discovery_job_if_absent(
        self, *, tenant_id, profile_id, profile_type, keyword, trigger_type="profile_created", live=True
    ):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "profile_id": profile_id,
                "profile_type": profile_type,
                "keyword": keyword,
                "trigger_type": trigger_type,
                "live": live,
            }
        )
        key = (tenant_id, profile_id, keyword, trigger_type)
        created = key not in self._seen
        self._seen.add(key)
        return SimpleNamespace(job=None, created=created)


def _fake_scheduler_factory(jobs):
    captured: dict[str, object] = {}

    def _scheduler(*, database_url, job_runner, now=None):
        captured["database_url"] = database_url
        captured["now"] = now
        results = [job_runner(job) for job in jobs]
        return {
            "due_job_count": len(jobs),
            "executed_job_count": len(results),
            "jobs": jobs,
            "results": results,
        }

    return _scheduler, captured


def _job(keyword: str) -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "profile_id": PROFILE_ID,
        "profile": "custom",
        "keyword": keyword,
        "trigger_type": "schedule",
        "live": True,
    }


def test_enqueues_every_due_job_tagged_schedule() -> None:
    store = _FakeJobStore()
    scheduler, _ = _fake_scheduler_factory([_job("a"), _job("b")])

    summary = enqueue_scheduled_discovery_jobs(
        database_url="postgresql://example.test/egp",
        discovery_job_repository=store,
        scheduler=scheduler,
    )

    assert [c["trigger_type"] for c in store.calls] == ["schedule", "schedule"]
    assert summary["due_job_count"] == 2
    assert summary["enqueued_count"] == 2
    assert summary["created_count"] == 2


def test_enqueue_is_idempotent_on_duplicate_pending_job() -> None:
    store = _FakeJobStore()
    scheduler, _ = _fake_scheduler_factory([_job("a"), _job("a")])  # same keyword twice

    summary = enqueue_scheduled_discovery_jobs(
        database_url="postgresql://example.test/egp",
        discovery_job_repository=store,
        scheduler=scheduler,
    )

    assert summary["enqueued_count"] == 2
    assert summary["created_count"] == 1  # second is a no-op duplicate


def test_passes_database_url_and_now_to_scheduler() -> None:
    store = _FakeJobStore()
    scheduler, captured = _fake_scheduler_factory([_job("a")])

    enqueue_scheduled_discovery_jobs(
        database_url="postgresql://example.test/egp",
        discovery_job_repository=store,
        scheduler=scheduler,
        now="2026-06-05T00:00:00+00:00",
    )

    assert captured["database_url"] == "postgresql://example.test/egp"
    assert captured["now"] == "2026-06-05T00:00:00+00:00"


def test_main_runs_one_enqueue_pass_and_returns_zero() -> None:
    seen: dict[str, object] = {}

    def _fake_enqueue(*, database_url):
        seen["database_url"] = database_url
        return {"due_job_count": 3, "enqueued_count": 3, "created_count": 2}

    code = main(["--database-url", "postgresql://example.test/egp"], enqueue=_fake_enqueue)

    assert code == 0
    assert seen["database_url"] == "postgresql://example.test/egp"
