"""Standalone discovery dispatch executor."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from egp_api.config import get_artifact_root, get_database_url, get_discovery_worker_count
from egp_api.services.discovery_dispatch import DiscoveryDispatchProcessor
from egp_api.services.discovery_worker_dispatcher import SubprocessDiscoveryDispatcher
from egp_api.services.run_service import RunService
from egp_db.connection import create_shared_engine
from egp_db.repositories.discovery_job_repo import create_discovery_job_repository
from egp_db.repositories.profile_repo import create_profile_repository
from egp_db.repositories.run_repo import CrawlRunRecord, create_run_repository


logger = logging.getLogger(__name__)


class PendingDiscoveryProcessor(Protocol):
    def process_pending(self, *, limit: int | None = None) -> int: ...


class MissingWorkerReconciler(Protocol):
    def reconcile_missing_workers(self, *, owner_pid: int) -> list[CrawlRunRecord]: ...


@dataclass(frozen=True, slots=True)
class DiscoveryDispatchRuntime:
    processor: PendingDiscoveryProcessor
    run_service: MissingWorkerReconciler


def build_discovery_dispatch_runtime(
    database_url: str | None = None,
    *,
    artifact_root: Path | None = None,
    worker_count: int | str | None = None,
) -> DiscoveryDispatchRuntime:
    """Build repository-backed discovery dispatch runtime dependencies."""

    resolved_artifact_root = get_artifact_root(artifact_root)
    resolved_database_url = get_database_url(
        database_url,
        artifact_root=resolved_artifact_root,
    )
    shared_engine = create_shared_engine(resolved_database_url)
    run_repository = create_run_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    profile_repository = create_profile_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    dispatcher = SubprocessDiscoveryDispatcher(
        resolved_database_url,
        artifact_root=resolved_artifact_root,
        run_repository=run_repository,
        profile_repository=profile_repository,
    )
    processor = DiscoveryDispatchProcessor(
        repository=create_discovery_job_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        dispatcher=dispatcher,
        worker_count=get_discovery_worker_count(worker_count),
    )
    return DiscoveryDispatchRuntime(
        processor=processor,
        run_service=RunService(
            run_repository,
            artifact_root=resolved_artifact_root,
        ),
    )


def reconcile_missing_discovery_workers(
    *,
    run_service: MissingWorkerReconciler,
    owner_pid: int,
    logger: logging.Logger | None = None,
) -> int:
    """Mark discovery runs failed when their worker PID disappeared."""

    resolved_logger = logger or globals()["logger"]
    try:
        failed_runs = run_service.reconcile_missing_workers(owner_pid=owner_pid)
    except Exception:
        resolved_logger.warning(
            "Failed to reconcile missing discover workers",
            exc_info=True,
        )
        return 0
    for failed_run in failed_runs:
        resolved_logger.warning(
            "Marked discover run %s failed (worker_lost)",
            failed_run.id,
        )
    return len(failed_runs)


def run_discovery_dispatch_once(
    *,
    processor: PendingDiscoveryProcessor,
    run_service: MissingWorkerReconciler | None = None,
    owner_pid: int | None = None,
    limit: int | None = None,
    logger: logging.Logger | None = None,
) -> int:
    """Process one batch of queued discovery dispatch jobs."""

    _reconcile_if_configured(
        run_service=run_service,
        owner_pid=owner_pid,
        logger=logger,
    )
    processed = processor.process_pending(limit=limit)
    _reconcile_if_configured(
        run_service=run_service,
        owner_pid=owner_pid,
        logger=logger,
    )
    return processed


async def run_discovery_dispatch_loop(
    *,
    processor: PendingDiscoveryProcessor,
    stop_event: asyncio.Event,
    poll_interval_seconds: float,
    run_service: MissingWorkerReconciler | None = None,
    owner_pid: int | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Process queued discovery dispatch jobs until `stop_event` is set."""

    resolved_logger = logger or globals()["logger"]
    while not stop_event.is_set():
        try:
            run_discovery_dispatch_once(
                processor=processor,
                run_service=run_service,
                owner_pid=owner_pid,
                logger=resolved_logger,
            )
        except Exception:
            resolved_logger.warning(
                "Failed to process pending discovery dispatch jobs",
                exc_info=True,
            )
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=max(0.05, float(poll_interval_seconds)),
            )
        except TimeoutError:
            continue


def _reconcile_if_configured(
    *,
    run_service: MissingWorkerReconciler | None,
    owner_pid: int | None,
    logger: logging.Logger | None,
) -> None:
    if run_service is None or owner_pid is None:
        return
    reconcile_missing_discovery_workers(
        run_service=run_service,
        owner_pid=owner_pid,
        logger=logger,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dispatch queued e-GP discovery jobs.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Artifact root. Defaults to EGP_ARTIFACT_ROOT or .data/artifacts.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch and exit instead of polling forever.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum discovery jobs to claim in --once mode.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=1.0,
        help="Polling interval for long-running mode.",
    )
    parser.add_argument(
        "--worker-count",
        type=int,
        default=None,
        help="Concurrent discovery workers. Defaults to EGP_DISCOVERY_WORKER_COUNT or 1.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runtime_factory=build_discovery_dispatch_runtime,
    owner_pid: int | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    runtime = runtime_factory(
        args.database_url,
        artifact_root=args.artifact_root,
        worker_count=args.worker_count,
    )
    resolved_owner_pid = os.getpid() if owner_pid is None else owner_pid
    if args.once:
        processed = run_discovery_dispatch_once(
            processor=runtime.processor,
            run_service=runtime.run_service,
            owner_pid=resolved_owner_pid,
            limit=args.limit,
        )
        logger.info("Processed %d pending discovery dispatch jobs", processed)
        return 0

    try:
        asyncio.run(
            _run_forever(
                processor=runtime.processor,
                run_service=runtime.run_service,
                owner_pid=resolved_owner_pid,
                poll_interval_seconds=args.poll_interval_seconds,
            ),
        )
    except KeyboardInterrupt:
        logger.info("Discovery dispatch executor stopped")
        return 130
    return 0


async def _run_forever(
    *,
    processor: PendingDiscoveryProcessor,
    run_service: MissingWorkerReconciler,
    owner_pid: int,
    poll_interval_seconds: float,
) -> None:
    stop_event = asyncio.Event()
    await run_discovery_dispatch_loop(
        processor=processor,
        run_service=run_service,
        owner_pid=owner_pid,
        stop_event=stop_event,
        poll_interval_seconds=poll_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
