from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from egp_api.bootstrap import background
from egp_api.executors import discovery_dispatch


class RecordingDiscoveryProcessor:
    def __init__(self, *, stop_event: asyncio.Event | None = None) -> None:
        self.stop_event = stop_event
        self.limits: list[int | None] = []

    def process_pending(self, *, limit: int | None = None) -> int:
        self.limits.append(limit)
        if self.stop_event is not None:
            self.stop_event.set()
        return 3


class RecordingRunService:
    def __init__(self) -> None:
        self.owner_pids: list[int] = []

    def reconcile_missing_workers(self, *, owner_pid: int) -> list[object]:
        self.owner_pids.append(owner_pid)
        return []


def test_run_discovery_dispatch_once_passes_limit_and_reconciles_workers() -> None:
    processor = RecordingDiscoveryProcessor()
    run_service = RecordingRunService()

    processed = discovery_dispatch.run_discovery_dispatch_once(
        processor=processor,
        run_service=run_service,
        owner_pid=1234,
        limit=5,
    )

    assert processed == 3
    assert processor.limits == [5]
    assert run_service.owner_pids == [1234, 1234]


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


def test_main_once_builds_runtime_from_database_url_and_artifact_root(tmp_path) -> None:
    built_args: list[tuple[str | None, Path | None]] = []
    processor = RecordingDiscoveryProcessor()
    run_service = RecordingRunService()

    def runtime_factory(
        database_url: str | None = None,
        *,
        artifact_root: Path | None = None,
    ) -> discovery_dispatch.DiscoveryDispatchRuntime:
        built_args.append((database_url, artifact_root))
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
        ],
        runtime_factory=runtime_factory,
        owner_pid=91011,
    )

    assert exit_code == 0
    assert built_args == [("sqlite+pysqlite:///discovery-executor.sqlite3", tmp_path)]
    assert processor.limits == [7]
    assert run_service.owner_pids == [91011, 91011]


def test_background_lifespan_uses_standalone_discovery_executor_loop() -> None:
    assert (
        background.run_discovery_dispatch_loop
        is discovery_dispatch.run_discovery_dispatch_loop
    )
