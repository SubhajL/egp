"""Standalone discovery dispatch executor."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
import logging
import os
from contextlib import suppress
from pathlib import Path
import threading
from typing import Callable, Literal, Protocol

from sqlalchemy.exc import OperationalError

from egp_api.config import (
    get_artifact_bucket,
    get_artifact_prefix,
    get_artifact_root,
    get_artifact_storage_backend,
    get_database_url,
    get_discovery_lease_heartbeat_seconds,
    get_discovery_lease_seconds,
    get_discovery_worker_count,
    get_supabase_service_role_key,
    get_supabase_url,
)
from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchBatchResult,
    DiscoveryDispatchProcessor,
    DiscoveryJobDispatchDisposition,
)
from egp_api.services.discovery_worker_dispatcher import SubprocessDiscoveryDispatcher
from egp_api.services.crawler_runtime_reporter import (
    CrawlerRuntimeReporter,
    build_crawler_runtime_reporter_from_env,
)
from egp_api.services.run_service import RunService
from egp_db.connection import create_shared_engine
from egp_db.repositories.discovery_job_repo import create_discovery_job_repository
from egp_db.repositories.profile_repo import create_profile_repository
from egp_db.repositories.run_repo import CrawlRunRecord, create_run_repository
from egp_shared_types.enums import CrawlerBlockerCode


logger = logging.getLogger(__name__)


class PendingDiscoveryProcessor(Protocol):
    def process_pending(
        self,
        *,
        limit: int | None = None,
    ) -> DiscoveryDispatchBatchResult: ...


class MissingWorkerReconciler(Protocol):
    def reconcile_missing_workers(self, *, owner_pid: int) -> list[CrawlRunRecord]: ...


class RuntimeHeartbeatReporter(Protocol):
    def report(
        self,
        *,
        watcher_status: str,
        database_status: str,
        profile_status: str,
        circuit_state: str,
        blocker_code: CrawlerBlockerCode | str | None = None,
        circuit_reset_at: str | None = None,
        force: bool = False,
    ) -> bool: ...


class DiscoveryDispatchWakeSignal:
    """Thread-safe signal for waking the async discovery dispatch loop."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        event: asyncio.Event | None = None,
    ) -> None:
        self._loop = loop or asyncio.get_running_loop()
        self._event = event or asyncio.Event()

    def wake(self) -> None:
        self._loop.call_soon_threadsafe(self._event.set)

    async def wait(self) -> None:
        await self._event.wait()

    def clear(self) -> None:
        self._event.clear()


@dataclass(frozen=True, slots=True)
class DiscoveryDispatchRuntime:
    processor: PendingDiscoveryProcessor
    run_service: MissingWorkerReconciler


OneShotExitReason = Literal[
    "blocked",
    "error",
    "limit_reached",
    "queue_drained",
    "waiting_retry_or_lease",
    "work_remains",
]


@dataclass(frozen=True, slots=True)
class DiscoveryOneShotSummary:
    requested_limit: int | None
    processed_count: int | None
    dispositions: list[DiscoveryJobDispatchDisposition] | None
    remaining_pending_count: int | None
    remaining_claimable_count: int | None
    remaining_leased_count: int | None
    remaining_retry_scheduled_count: int | None
    blocker: str | None
    circuit_reset_at: str | None
    exit_reason: OneShotExitReason


def build_discovery_one_shot_summary(
    result: DiscoveryDispatchBatchResult,
) -> DiscoveryOneShotSummary:
    """Build the stable, sanitized terminal contract for bounded crawling."""

    queue = result.queue_snapshot
    if result.blocker is not None:
        exit_reason: OneShotExitReason = "blocked"
    elif queue.pending_count == 0:
        exit_reason = "queue_drained"
    elif result.processed_count >= result.requested_limit:
        exit_reason = "limit_reached"
    elif queue.claimable_count == 0:
        exit_reason = "waiting_retry_or_lease"
    else:
        exit_reason = "work_remains"
    return DiscoveryOneShotSummary(
        requested_limit=result.requested_limit,
        processed_count=result.processed_count,
        dispositions=list(result.dispositions),
        remaining_pending_count=queue.pending_count,
        remaining_claimable_count=queue.claimable_count,
        remaining_leased_count=queue.leased_count,
        remaining_retry_scheduled_count=queue.retry_scheduled_count,
        blocker=result.blocker.value if result.blocker is not None else None,
        circuit_reset_at=result.circuit_reset_at,
        exit_reason=exit_reason,
    )


def build_discovery_one_shot_error_summary(
    *,
    requested_limit: int | None,
    exc: BaseException,
) -> DiscoveryOneShotSummary:
    """Build a sanitized terminal contract when bounded dispatch cannot complete."""

    blocker = (
        CrawlerBlockerCode.DATABASE_UNREACHABLE.value
        if isinstance(exc, OperationalError)
        else "runtime_error"
    )
    return DiscoveryOneShotSummary(
        requested_limit=requested_limit,
        processed_count=None,
        dispositions=None,
        remaining_pending_count=None,
        remaining_claimable_count=None,
        remaining_leased_count=None,
        remaining_retry_scheduled_count=None,
        blocker=blocker,
        circuit_reset_at=None,
        exit_reason="error",
    )


def _print_discovery_one_shot_summary(summary: DiscoveryOneShotSummary) -> None:
    print(json.dumps(asdict(summary), sort_keys=True, separators=(",", ":")))


@dataclass(slots=True)
class RuntimeHeartbeatState:
    watcher_status: str = "running"
    database_status: str = "connected"
    blocker_code: CrawlerBlockerCode | None = None
    profile_status: str = "ready"
    circuit_state: str = "closed"
    circuit_reset_at: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def mark_processing(self) -> None:
        with self._lock:
            self._mark_processing_unlocked()

    def _mark_processing_unlocked(self) -> None:
        self.watcher_status = "running"
        self.database_status = "connected"
        self.blocker_code = None
        self.profile_status = "ready"
        self.circuit_state = "closed"
        self.circuit_reset_at = None

    def update_from_batch(self, result: DiscoveryDispatchBatchResult) -> None:
        with self._lock:
            self._mark_processing_unlocked()
            self.blocker_code = result.blocker
            self.circuit_reset_at = result.circuit_reset_at
            if result.blocker == CrawlerBlockerCode.CIRCUIT_OPEN:
                self.circuit_state = "open"
            elif result.blocker == CrawlerBlockerCode.PROFILE_BUSY:
                self.profile_status = "busy"
            elif result.blocker == CrawlerBlockerCode.PROFILE_WARM_RETRY:
                self.profile_status = "warm_retry"
            elif result.blocker == CrawlerBlockerCode.PROFILE_OPERATOR_ACTION_REQUIRED:
                self.profile_status = "operator_action_required"

    def update_from_error(self, exc: BaseException) -> None:
        with self._lock:
            self.watcher_status = "error"
            self.database_status = (
                "unreachable" if isinstance(exc, OperationalError) else "unknown"
            )
            self.blocker_code = (
                CrawlerBlockerCode.DATABASE_UNREACHABLE
                if isinstance(exc, OperationalError)
                else None
            )
            self.profile_status = "unknown"
            self.circuit_state = "unknown"
            self.circuit_reset_at = None

    def mark_stopping(self) -> None:
        with self._lock:
            self.watcher_status = "stopping"
            self.blocker_code = CrawlerBlockerCode.AGENT_OFFLINE

    def report_kwargs(self) -> dict[str, object]:
        with self._lock:
            return {
                "watcher_status": self.watcher_status,
                "database_status": self.database_status,
                "blocker_code": self.blocker_code,
                "profile_status": self.profile_status,
                "circuit_state": self.circuit_state,
                "circuit_reset_at": self.circuit_reset_at,
            }


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
        artifact_storage_backend=get_artifact_storage_backend(None),
        artifact_bucket=get_artifact_bucket(None),
        artifact_prefix=get_artifact_prefix(None),
        supabase_url=get_supabase_url(None),
        supabase_service_role_key=get_supabase_service_role_key(None),
        run_repository=run_repository,
        profile_repository=profile_repository,
    )
    processor = DiscoveryDispatchProcessor(
        repository=create_discovery_job_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        dispatcher=dispatcher,
        pre_dispatch_preparer=dispatcher,
        lease_seconds=get_discovery_lease_seconds(),
        lease_heartbeat_seconds=get_discovery_lease_heartbeat_seconds(),
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
    on_pre_dispatch_ready: Callable[[], None] | None = None,
) -> DiscoveryDispatchBatchResult:
    """Process one batch of queued discovery dispatch jobs."""

    _reconcile_if_configured(
        run_service=run_service,
        owner_pid=owner_pid,
        logger=logger,
    )
    observed_processor = getattr(processor, "process_pending_with_observer", None)
    if on_pre_dispatch_ready is not None and callable(observed_processor):
        processed = observed_processor(
            limit=limit,
            on_pre_dispatch_ready=on_pre_dispatch_ready,
        )
    else:
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
    wake_signal: DiscoveryDispatchWakeSignal | None = None,
    runtime_reporter: RuntimeHeartbeatReporter | None = None,
    runtime_heartbeat_interval_seconds: float = 30.0,
) -> None:
    """Process queued discovery dispatch jobs until `stop_event` is set."""

    resolved_logger = logger or globals()["logger"]
    runtime_state = RuntimeHeartbeatState()
    heartbeat_delivery_lock = asyncio.Lock()
    heartbeat_task = (
        asyncio.create_task(
            _run_periodic_runtime_heartbeats(
                reporter=runtime_reporter,
                state=runtime_state,
                stop_event=stop_event,
                interval_seconds=runtime_heartbeat_interval_seconds,
                delivery_lock=heartbeat_delivery_lock,
            )
        )
        if runtime_reporter is not None
        else None
    )
    try:
        while not stop_event.is_set():
            try:
                result = await asyncio.to_thread(
                    run_discovery_dispatch_once,
                    processor=processor,
                    run_service=run_service,
                    owner_pid=owner_pid,
                    logger=resolved_logger,
                    on_pre_dispatch_ready=runtime_state.mark_processing,
                )
                runtime_state.update_from_batch(result)
            except Exception as exc:
                resolved_logger.warning(
                    "Failed to process pending discovery dispatch jobs",
                    exc_info=True,
                )
                runtime_state.update_from_error(exc)
            await _emit_runtime_heartbeat(
                runtime_reporter,
                runtime_state,
                delivery_lock=heartbeat_delivery_lock,
            )
            await _wait_for_next_dispatch(
                stop_event=stop_event,
                wake_signal=wake_signal,
                timeout_seconds=max(0.05, float(poll_interval_seconds)),
            )
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task


async def _run_periodic_runtime_heartbeats(
    *,
    reporter: RuntimeHeartbeatReporter,
    state: RuntimeHeartbeatState,
    stop_event: asyncio.Event,
    interval_seconds: float,
    delivery_lock: asyncio.Lock,
) -> None:
    interval = max(0.01, float(interval_seconds))
    while not stop_event.is_set():
        await _emit_runtime_heartbeat(
            reporter,
            state,
            delivery_lock=delivery_lock,
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue


def _run_periodic_runtime_heartbeats_sync(
    *,
    reporter: RuntimeHeartbeatReporter,
    state: RuntimeHeartbeatState,
    stop_event: threading.Event,
    interval_seconds: float,
    delivery_lock: threading.Lock,
    first_attempt_started: threading.Event,
) -> None:
    interval = max(0.01, float(interval_seconds))
    while not stop_event.is_set():
        with delivery_lock:
            if stop_event.is_set():
                return
            first_attempt_started.set()
            reporter.report(**state.report_kwargs())
        if stop_event.wait(interval):
            return


async def _emit_runtime_heartbeat(
    reporter: RuntimeHeartbeatReporter | None,
    state: RuntimeHeartbeatState,
    *,
    delivery_lock: asyncio.Lock,
) -> None:
    if reporter is None:
        return
    async with delivery_lock:
        await asyncio.to_thread(
            reporter.report,
            **state.report_kwargs(),
        )


async def _wait_for_next_dispatch(
    *,
    stop_event: asyncio.Event,
    wake_signal: DiscoveryDispatchWakeSignal | None,
    timeout_seconds: float,
) -> None:
    if wake_signal is None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=timeout_seconds)
        except TimeoutError:
            return
        return

    pending: set[asyncio.Task[bool | None]] = set()
    stop_task = asyncio.create_task(stop_event.wait())
    wake_task = asyncio.create_task(wake_signal.wait())
    try:
        done, pending = await asyncio.wait(
            {stop_task, wake_task},
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if wake_task in done:
            wake_signal.clear()
    finally:
        for task in pending:
            task.cancel()
        for task in pending:
            with suppress(asyncio.CancelledError):
                await task


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


def _start_runtime_heartbeat_thread(
    *,
    reporter: RuntimeHeartbeatReporter | None,
    state: RuntimeHeartbeatState,
) -> tuple[threading.Event, threading.Thread | None, threading.Lock]:
    stop_event = threading.Event()
    delivery_lock = threading.Lock()
    if reporter is None:
        return stop_event, None, delivery_lock
    first_attempt_started = threading.Event()
    interval_seconds = float(
        getattr(reporter, "minimum_interval_seconds", 30.0)
    )
    heartbeat_thread = threading.Thread(
        target=_run_periodic_runtime_heartbeats_sync,
        kwargs={
            "reporter": reporter,
            "state": state,
            "stop_event": stop_event,
            "interval_seconds": interval_seconds,
            "delivery_lock": delivery_lock,
            "first_attempt_started": first_attempt_started,
        },
        daemon=True,
        name="egp-crawler-runtime-heartbeat",
    )
    heartbeat_thread.start()
    first_attempt_started.wait(timeout=1.0)
    return stop_event, heartbeat_thread, delivery_lock


def _stop_runtime_heartbeat_and_report(
    *,
    reporter: RuntimeHeartbeatReporter | None,
    state: RuntimeHeartbeatState,
    stop_event: threading.Event,
    heartbeat_thread: threading.Thread | None,
    delivery_lock: threading.Lock,
) -> None:
    stop_event.set()
    with delivery_lock:
        if reporter is not None:
            state.mark_stopping()
            reporter.report(**state.report_kwargs(), force=True)
    if heartbeat_thread is not None:
        heartbeat_thread.join(timeout=1.0)


def _report_database_unreachable(
    reporter: RuntimeHeartbeatReporter | None,
) -> None:
    if reporter is None:
        return
    reporter.report(
        watcher_status="error",
        database_status="unreachable",
        blocker_code=CrawlerBlockerCode.DATABASE_UNREACHABLE,
        profile_status="unknown",
        circuit_state="unknown",
    )


def _report_runtime_error(
    reporter: RuntimeHeartbeatReporter | None,
    exc: BaseException,
) -> None:
    if isinstance(exc, OperationalError):
        _report_database_unreachable(reporter)
        return
    if reporter is None:
        return
    reporter.report(
        watcher_status="error",
        database_status="unknown",
        blocker_code=None,
        profile_status="unknown",
        circuit_state="unknown",
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
    runtime_reporter: CrawlerRuntimeReporter | None = (
        build_crawler_runtime_reporter_from_env()
    )
    try:
        runtime = runtime_factory(
            args.database_url,
            artifact_root=args.artifact_root,
            worker_count=args.worker_count,
        )
    except Exception as exc:
        _report_runtime_error(runtime_reporter, exc)
        if args.once:
            _print_discovery_one_shot_summary(
                build_discovery_one_shot_error_summary(
                    requested_limit=args.limit,
                    exc=exc,
                )
            )
        logger.exception("Failed to build discovery dispatch runtime")
        return 1
    resolved_owner_pid = os.getpid() if owner_pid is None else owner_pid
    if args.once:
        runtime_state = RuntimeHeartbeatState()
        heartbeat_stop, heartbeat_thread, heartbeat_delivery_lock = (
            _start_runtime_heartbeat_thread(
                reporter=runtime_reporter,
                state=runtime_state,
            )
        )
        try:
            processed = run_discovery_dispatch_once(
                processor=runtime.processor,
                run_service=runtime.run_service,
                owner_pid=resolved_owner_pid,
                limit=args.limit,
                on_pre_dispatch_ready=runtime_state.mark_processing,
            )
        except Exception as exc:
            runtime_state.update_from_error(exc)
            _stop_runtime_heartbeat_and_report(
                reporter=runtime_reporter,
                state=runtime_state,
                stop_event=heartbeat_stop,
                heartbeat_thread=heartbeat_thread,
                delivery_lock=heartbeat_delivery_lock,
            )
            _print_discovery_one_shot_summary(
                build_discovery_one_shot_error_summary(
                    requested_limit=args.limit,
                    exc=exc,
                )
            )
            logger.exception("Failed to process pending discovery dispatch jobs")
            return 1
        runtime_state.update_from_batch(processed)
        _stop_runtime_heartbeat_and_report(
            reporter=runtime_reporter,
            state=runtime_state,
            stop_event=heartbeat_stop,
            heartbeat_thread=heartbeat_thread,
            delivery_lock=heartbeat_delivery_lock,
        )
        summary = build_discovery_one_shot_summary(processed)
        _print_discovery_one_shot_summary(summary)
        logger.info(
            "Processed %d pending discovery dispatch jobs",
            processed.processed_count,
        )
        return 3 if summary.exit_reason == "blocked" else 0

    try:
        asyncio.run(
            _run_forever(
                processor=runtime.processor,
                run_service=runtime.run_service,
                owner_pid=resolved_owner_pid,
                poll_interval_seconds=args.poll_interval_seconds,
                runtime_reporter=runtime_reporter,
                runtime_heartbeat_interval_seconds=(
                    runtime_reporter.minimum_interval_seconds
                    if runtime_reporter is not None
                    else 30.0
                ),
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
    runtime_reporter: RuntimeHeartbeatReporter | None = None,
    runtime_heartbeat_interval_seconds: float = 30.0,
) -> None:
    stop_event = asyncio.Event()
    await run_discovery_dispatch_loop(
        processor=processor,
        run_service=run_service,
        owner_pid=owner_pid,
        stop_event=stop_event,
        poll_interval_seconds=poll_interval_seconds,
        runtime_reporter=runtime_reporter,
        runtime_heartbeat_interval_seconds=runtime_heartbeat_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
