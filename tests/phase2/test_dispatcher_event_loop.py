from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

import pytest

from egp_api.executors import discovery_dispatch
from egp_api.services.discovery_dispatch import DiscoveryDispatchBatchResult


class BlockingDiscoveryProcessor:
    def __init__(self, *, release: threading.Event) -> None:
        self.release = release
        self.limits: list[int | None] = []

    def process_pending(
        self,
        *,
        limit: int | None = None,
    ) -> DiscoveryDispatchBatchResult:
        self.limits.append(limit)
        self.release.wait(timeout=5.0)
        return DiscoveryDispatchBatchResult(requested_limit=1, dispositions=())


class RecordingRunService:
    def __init__(self) -> None:
        self.owner_pids: list[int] = []

    def reconcile_missing_workers(self, *, owner_pid: int) -> list[object]:
        self.owner_pids.append(owner_pid)
        return []


class RecordingRuntimeReporter:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    def report(self, **payload: object) -> bool:
        self.payloads.append(payload)
        return True


@pytest.mark.asyncio
async def test_run_discovery_dispatch_loop_does_not_block_event_loop() -> None:
    stop_event = asyncio.Event()
    release = threading.Event()
    processor = BlockingDiscoveryProcessor(release=release)
    run_service = RecordingRunService()

    started_at = time.perf_counter()
    dispatch_task = asyncio.create_task(
        discovery_dispatch.run_discovery_dispatch_loop(
            processor=processor,
            run_service=run_service,
            owner_pid=1234,
            stop_event=stop_event,
            poll_interval_seconds=30.0,
        )
    )

    try:
        await asyncio.sleep(0.1)
        assert time.perf_counter() - started_at < 1.0
    finally:
        release.set()
        stop_event.set()
        await asyncio.wait_for(dispatch_task, timeout=1.0)

    assert processor.limits == [None]
    assert run_service.owner_pids == [1234, 1234]


@pytest.mark.asyncio
async def test_blocking_batch_keeps_emitting_runtime_heartbeats() -> None:
    stop_event = asyncio.Event()
    release = threading.Event()
    processor = BlockingDiscoveryProcessor(release=release)
    reporter = RecordingRuntimeReporter()
    dispatch_task = asyncio.create_task(
        discovery_dispatch.run_discovery_dispatch_loop(
            processor=processor,
            stop_event=stop_event,
            poll_interval_seconds=30.0,
            runtime_reporter=reporter,
            runtime_heartbeat_interval_seconds=0.02,
        )
    )

    try:
        await _wait_until(lambda: len(reporter.payloads) >= 2)
        assert release.is_set() is False
    finally:
        release.set()
        stop_event.set()
        await asyncio.wait_for(dispatch_task, timeout=1.0)

    assert all(
        payload["watcher_status"] == "running"
        and payload["database_status"] == "connected"
        for payload in reporter.payloads[:2]
    )


@pytest.mark.asyncio
async def test_run_discovery_dispatch_loop_wakes_before_poll_interval() -> None:
    stop_event = asyncio.Event()
    processor = _RecordingDiscoveryProcessor()
    wake_signal = discovery_dispatch.DiscoveryDispatchWakeSignal()

    dispatch_task = asyncio.create_task(
        discovery_dispatch.run_discovery_dispatch_loop(
            processor=processor,
            stop_event=stop_event,
            poll_interval_seconds=30.0,
            wake_signal=wake_signal,
        )
    )

    try:
        await _wait_until(lambda: len(processor.limits) == 1)
        wake_signal.wake()
        await _wait_until(lambda: len(processor.limits) == 2)
    finally:
        stop_event.set()
        wake_signal.wake()
        await asyncio.wait_for(dispatch_task, timeout=1.0)

    assert processor.limits == [None, None]


class _RecordingDiscoveryProcessor:
    def __init__(self) -> None:
        self.limits: list[int | None] = []

    def process_pending(self, *, limit: int | None = None) -> int:
        self.limits.append(limit)
        return 0


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")
