from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import time
from typing import get_type_hints

import pytest
from sqlalchemy.exc import OperationalError

from egp_api.bootstrap import background
from egp_api.executors import discovery_dispatch
from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchBatchResult,
    DiscoveryJobDispatchDisposition,
)
from egp_shared_types.enums import CrawlerBlockerCode


class RecordingDiscoveryProcessor:
    def __init__(self, *, stop_event: asyncio.Event | None = None) -> None:
        self.stop_event = stop_event
        self.limits: list[int | None] = []

    def process_pending(
        self,
        *,
        limit: int | None = None,
    ) -> DiscoveryDispatchBatchResult:
        self.limits.append(limit)
        if self.stop_event is not None:
            self.stop_event.set()
        return DiscoveryDispatchBatchResult(
            requested_limit=limit or 3,
            dispositions=tuple(
                DiscoveryJobDispatchDisposition(
                    job_id=f"job-{index}",
                    outcome="dispatched",
                )
                for index in range(3)
            ),
        )


class RecordingRunService:
    def __init__(self) -> None:
        self.owner_pids: list[int] = []

    def reconcile_missing_workers(self, *, owner_pid: int) -> list[object]:
        self.owner_pids.append(owner_pid)
        return []


class RecordingRuntimeReporter:
    def __init__(self, *, minimum_interval_seconds: float = 30.0) -> None:
        self.payloads: list[dict[str, object]] = []
        self.minimum_interval_seconds = minimum_interval_seconds
        self._condition = threading.Condition()

    def report(self, **payload: object) -> bool:
        with self._condition:
            self.payloads.append(payload)
            self._condition.notify_all()
        return True

    def wait_for_payloads(self, count: int, *, timeout: float = 1.0) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: len(self.payloads) >= count,
                timeout=timeout,
            )


def test_run_discovery_dispatch_once_passes_limit_and_reconciles_workers() -> None:
    processor = RecordingDiscoveryProcessor()
    run_service = RecordingRunService()

    processed = discovery_dispatch.run_discovery_dispatch_once(
        processor=processor,
        run_service=run_service,
        owner_pid=1234,
        limit=5,
    )

    assert processed.processed_count == 3
    assert processor.limits == [5]
    assert run_service.owner_pids == [1234, 1234]


def test_reconcile_missing_discovery_workers_return_annotation_is_integer() -> None:
    hints = get_type_hints(discovery_dispatch.reconcile_missing_discovery_workers)

    assert hints["return"] is int


@pytest.mark.asyncio
async def test_run_discovery_dispatch_loop_processes_until_stop_event() -> None:
    stop_event = asyncio.Event()
    processor = RecordingDiscoveryProcessor(stop_event=stop_event)
    run_service = RecordingRunService()

    await discovery_dispatch.run_discovery_dispatch_loop(
        processor=processor,
        run_service=run_service,
        owner_pid=5678,
        stop_event=stop_event,
        poll_interval_seconds=0.01,
    )

    assert processor.limits == [None]
    assert run_service.owner_pids == [5678, 5678]


@pytest.mark.asyncio
async def test_dispatch_loop_reports_shared_blocker_without_stopping_observability() -> None:
    stop_event = asyncio.Event()
    reporter = RecordingRuntimeReporter()

    class BlockedProcessor:
        def process_pending(
            self,
            *,
            limit: int | None = None,
        ) -> DiscoveryDispatchBatchResult:
            del limit
            stop_event.set()
            return DiscoveryDispatchBatchResult(
                requested_limit=1,
                dispositions=(),
                blocker=CrawlerBlockerCode.CIRCUIT_OPEN,
                circuit_reset_at="2026-07-23T04:00:00+00:00",
            )

    await discovery_dispatch.run_discovery_dispatch_loop(
        processor=BlockedProcessor(),
        stop_event=stop_event,
        poll_interval_seconds=0.01,
        runtime_reporter=reporter,
    )

    assert reporter.payloads[-1] == {
        "watcher_status": "running",
        "database_status": "connected",
        "blocker_code": CrawlerBlockerCode.CIRCUIT_OPEN,
        "profile_status": "ready",
        "circuit_state": "open",
        "circuit_reset_at": "2026-07-23T04:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_dispatch_loop_does_not_clear_persistent_blocker_between_polls() -> None:
    stop_event = asyncio.Event()
    reporter = RecordingRuntimeReporter()

    class PersistentlyBlockedProcessor:
        def __init__(self) -> None:
            self.calls = 0

        def process_pending(
            self,
            *,
            limit: int | None = None,
        ) -> DiscoveryDispatchBatchResult:
            del limit
            self.calls += 1
            if self.calls == 2:
                stop_event.set()
            return DiscoveryDispatchBatchResult(
                requested_limit=1,
                dispositions=(),
                blocker=CrawlerBlockerCode.CIRCUIT_OPEN,
                circuit_reset_at="2026-07-23T04:00:00+00:00",
            )

    await discovery_dispatch.run_discovery_dispatch_loop(
        processor=PersistentlyBlockedProcessor(),
        stop_event=stop_event,
        poll_interval_seconds=0.01,
        runtime_reporter=reporter,
        runtime_heartbeat_interval_seconds=60,
    )

    first_blocked_index = next(
        index
        for index, payload in enumerate(reporter.payloads)
        if payload["blocker_code"] == CrawlerBlockerCode.CIRCUIT_OPEN
    )
    assert all(
        payload["blocker_code"] == CrawlerBlockerCode.CIRCUIT_OPEN
        for payload in reporter.payloads[first_blocked_index:]
    )


@pytest.mark.asyncio
async def test_dispatch_loop_serializes_periodic_and_batch_heartbeats() -> None:
    stop_event = asyncio.Event()
    first_started = threading.Event()
    first_finished = threading.Event()

    class DelayedFirstReporter(RecordingRuntimeReporter):
        def __init__(self) -> None:
            super().__init__()
            self._call_count = 0
            self._call_lock = threading.Lock()

        def report(self, **payload: object) -> bool:
            with self._call_lock:
                self._call_count += 1
                call_count = self._call_count
            if call_count == 1:
                first_started.set()
                time.sleep(0.05)
            result = super().report(**payload)
            if call_count == 1:
                first_finished.set()
            return result

    class BlockedAfterHeartbeatProcessor:
        def process_pending(
            self,
            *,
            limit: int | None = None,
        ) -> DiscoveryDispatchBatchResult:
            del limit
            assert first_started.wait(timeout=1)
            stop_event.set()
            return DiscoveryDispatchBatchResult(
                requested_limit=1,
                dispositions=(),
                blocker=CrawlerBlockerCode.CIRCUIT_OPEN,
            )

    reporter = DelayedFirstReporter()
    await discovery_dispatch.run_discovery_dispatch_loop(
        processor=BlockedAfterHeartbeatProcessor(),
        stop_event=stop_event,
        poll_interval_seconds=0.01,
        runtime_reporter=reporter,
        runtime_heartbeat_interval_seconds=60,
    )
    assert await asyncio.to_thread(first_finished.wait, 1)

    assert reporter.payloads[-1]["blocker_code"] == CrawlerBlockerCode.CIRCUIT_OPEN


def test_main_reports_database_unreachable_when_runtime_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporter = RecordingRuntimeReporter()
    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: reporter,
    )

    def fail_runtime_factory(*args: object, **kwargs: object):
        del args, kwargs
        raise OperationalError(
            "database tunnel unavailable",
            {},
            ConnectionRefusedError("connection refused"),
        )

    exit_code = discovery_dispatch.main([], runtime_factory=fail_runtime_factory)

    assert exit_code == 1
    assert reporter.payloads == [
        {
            "watcher_status": "error",
            "database_status": "unreachable",
            "blocker_code": CrawlerBlockerCode.DATABASE_UNREACHABLE,
            "profile_status": "unknown",
            "circuit_state": "unknown",
        }
    ]


def test_main_once_builds_runtime_and_reports_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    built_args: list[tuple[str | None, Path | None, int | None]] = []
    processor = RecordingDiscoveryProcessor()
    run_service = RecordingRunService()
    reporter = RecordingRuntimeReporter()
    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: reporter,
    )

    def runtime_factory(
        database_url: str | None = None,
        *,
        artifact_root: Path | None = None,
        worker_count: int | None = None,
    ) -> discovery_dispatch.DiscoveryDispatchRuntime:
        built_args.append((database_url, artifact_root, worker_count))
        return discovery_dispatch.DiscoveryDispatchRuntime(
            processor=processor,
            run_service=run_service,
        )

    exit_code = discovery_dispatch.main(
        [
            "--database-url",
            "sqlite+pysqlite:///discovery-executor.sqlite3",
            "--artifact-root",
            str(tmp_path),
            "--once",
            "--limit",
            "7",
            "--worker-count",
            "3",
        ],
        runtime_factory=runtime_factory,
        owner_pid=91011,
    )

    assert exit_code == 0
    assert built_args == [("sqlite+pysqlite:///discovery-executor.sqlite3", tmp_path, 3)]
    assert processor.limits == [7]
    assert run_service.owner_pids == [91011, 91011]
    assert reporter.payloads[0]["watcher_status"] == "running"
    assert reporter.payloads[-1] == {
        "watcher_status": "stopping",
        "database_status": "connected",
        "blocker_code": CrawlerBlockerCode.AGENT_OFFLINE,
        "profile_status": "ready",
        "circuit_state": "closed",
        "circuit_reset_at": None,
        "force": True,
    }


def test_main_once_heartbeats_while_batch_is_running_then_reports_stopping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    reporter = RecordingRuntimeReporter(minimum_interval_seconds=0.01)

    class BlockingProcessor:
        def process_pending(
            self,
            *,
            limit: int | None = None,
        ) -> DiscoveryDispatchBatchResult:
            del limit
            entered.set()
            assert release.wait(timeout=1)
            return DiscoveryDispatchBatchResult(
                requested_limit=1,
                dispositions=(),
            )

    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: reporter,
    )
    runtime = discovery_dispatch.DiscoveryDispatchRuntime(
        processor=BlockingProcessor(),
        run_service=RecordingRunService(),
    )
    result: list[int] = []
    main_thread = threading.Thread(
        target=lambda: result.append(
            discovery_dispatch.main(
                ["--once"],
                runtime_factory=lambda *args, **kwargs: runtime,
            )
        )
    )

    main_thread.start()
    assert entered.wait(timeout=1)
    assert reporter.wait_for_payloads(2)
    assert all(
        payload["watcher_status"] == "running"
        for payload in reporter.payloads[:2]
    )
    release.set()
    main_thread.join(timeout=1)

    assert not main_thread.is_alive()
    assert result == [0]
    assert reporter.payloads[-1]["watcher_status"] == "stopping"
    assert reporter.payloads[-1]["blocker_code"] == CrawlerBlockerCode.AGENT_OFFLINE


def test_main_once_serializes_delayed_heartbeat_before_stopping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DelayedFirstReporter(RecordingRuntimeReporter):
        def __init__(self) -> None:
            super().__init__(minimum_interval_seconds=30)
            self.first_finished = threading.Event()
            self._call_count = 0
            self._call_lock = threading.Lock()

        def report(self, **payload: object) -> bool:
            with self._call_lock:
                self._call_count += 1
                call_count = self._call_count
            if call_count == 1:
                time.sleep(1.05)
            result = super().report(**payload)
            if call_count == 1:
                self.first_finished.set()
            return result

    reporter = DelayedFirstReporter()
    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: reporter,
    )
    runtime = discovery_dispatch.DiscoveryDispatchRuntime(
        processor=RecordingDiscoveryProcessor(),
        run_service=RecordingRunService(),
    )

    assert (
        discovery_dispatch.main(
            ["--once"],
            runtime_factory=lambda *args, **kwargs: runtime,
        )
        == 0
    )
    assert reporter.first_finished.wait(timeout=1)
    assert reporter.payloads[-1]["watcher_status"] == "stopping"
    assert reporter.payloads[-1]["blocker_code"] == CrawlerBlockerCode.AGENT_OFFLINE


def test_runtime_stopping_state_always_reports_agent_offline() -> None:
    state = discovery_dispatch.RuntimeHeartbeatState()
    state.update_from_batch(
        DiscoveryDispatchBatchResult(
            requested_limit=1,
            dispositions=(),
            blocker=CrawlerBlockerCode.CIRCUIT_OPEN,
            circuit_reset_at="2026-07-23T04:00:00+00:00",
        )
    )

    state.mark_stopping()

    assert state.report_kwargs() == {
        "watcher_status": "stopping",
        "database_status": "connected",
        "blocker_code": CrawlerBlockerCode.AGENT_OFFLINE,
        "profile_status": "ready",
        "circuit_state": "open",
        "circuit_reset_at": "2026-07-23T04:00:00+00:00",
    }


def test_background_lifespan_uses_standalone_discovery_executor_loop() -> None:
    assert (
        background.run_discovery_dispatch_loop
        is discovery_dispatch.run_discovery_dispatch_loop
    )
