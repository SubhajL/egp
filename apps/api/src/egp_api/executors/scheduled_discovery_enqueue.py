"""Enqueue-only scheduled discovery producer (no browser).

In the off-box-crawl topology the Lightsail ``discovery-executor`` is disabled
so the local Mac is the sole *claimer* of ``discovery_jobs``. Nothing, however,
fires interval-based crawls anymore. This executor closes that gap: it reuses
the existing scheduler planning (``egp_worker.scheduler.run_scheduled_discovery``
— due-tenant calculation, entitlement + authorization filtering) but swaps the
browser ``job_runner`` for one that simply inserts ``schedule`` rows into the
``discovery_jobs`` outbox. It needs only a DB connection, so it runs on the
control-plane host (Lightsail) on a systemd timer — never a browser.

Run once per timer fire:

    python -m egp_api.executors.scheduled_discovery_enqueue --database-url ...
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from typing import Protocol

from egp_api.config import get_database_url
from egp_db.repositories.discovery_job_repo import create_discovery_job_repository


logger = logging.getLogger(__name__)


class _PendingDiscoveryJobStore(Protocol):
    def create_pending_discovery_job_if_absent(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        profile_type: str,
        keyword: str,
        trigger_type: str = ...,
        live: bool = ...,
    ): ...


def enqueue_scheduled_discovery_jobs(
    *,
    database_url: str,
    discovery_job_repository: _PendingDiscoveryJobStore | None = None,
    scheduler: Callable[..., dict[str, object]] | None = None,
    now=None,
) -> dict[str, int]:
    """Plan due scheduled crawls and enqueue them as ``schedule`` outbox jobs.

    Returns counts: ``due_job_count`` (planned), ``enqueued_count`` (enqueue
    attempts) and ``created_count`` (newly inserted, excluding idempotent
    duplicates). ``scheduler`` is injected in tests; in production it defaults
    to the worker's ``run_scheduled_discovery`` planning function.
    """

    if scheduler is None:
        # Lazy import keeps egp_worker a runtime-only (not import-time) dependency.
        from egp_worker.scheduler import run_scheduled_discovery

        scheduler = run_scheduled_discovery
    repository = discovery_job_repository or create_discovery_job_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )

    enqueued: list[object] = []

    def _enqueue_runner(job: dict[str, object]) -> object:
        result = repository.create_pending_discovery_job_if_absent(
            tenant_id=str(job["tenant_id"]),
            profile_id=str(job["profile_id"]),
            profile_type=str(job.get("profile") or "custom"),
            keyword=str(job["keyword"]),
            trigger_type="schedule",
            live=bool(job.get("live", True)),
        )
        enqueued.append(result)
        return result

    summary = scheduler(database_url=database_url, job_runner=_enqueue_runner, now=now)
    created_count = sum(1 for result in enqueued if getattr(result, "created", False))
    return {
        "due_job_count": int(summary.get("due_job_count", 0)),
        "enqueued_count": len(enqueued),
        "created_count": created_count,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enqueue due scheduled e-GP discovery jobs (no browser).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    enqueue: Callable[..., dict[str, int]] = enqueue_scheduled_discovery_jobs,
) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    summary = enqueue(database_url=get_database_url(args.database_url))
    logger.info(
        "Enqueued scheduled discovery jobs (new=%d of due=%d, attempts=%d)",
        summary["created_count"],
        summary["due_job_count"],
        summary["enqueued_count"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
