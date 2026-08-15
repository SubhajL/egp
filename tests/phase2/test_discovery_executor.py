from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
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
from egp_db.repositories.discovery_job_repo import DiscoveryQueueSnapshot
from egp_shared_types.enums import CrawlerBlockerCode

FAULT_JOB_ID = "11111111-1111-4111-8111-111111111111"
FAULT_TENANT_ID = "22222222-2222-4222-8222-222222222222"


def _fault_cli_args(
    *,
    mode: str = "nonzero_exit",
    job_id: str | None = FAULT_JOB_ID,
    tenant_id: str | None = FAULT_TENANT_ID,
    once: bool = True,
    limit: str = "1",
) -> list[str]:
    args = ["--limit", limit, "--fault-mode", mode]
    if once:
        args.insert(0, "--once")
    if job_id is not None:
        args.extend(["--fault-job-id", job_id])
    if tenant_id is not None:
        args.extend(["--fault-tenant-id", tenant_id])
    return args


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


@pytest.mark.parametrize(
    ("result", "expected_reason"),
    [
        (
            DiscoveryDispatchBatchResult(
                requested_limit=2,
                dispositions=(
                    DiscoveryJobDispatchDisposition(
                        job_id="job-1",
                        outcome="dispatched",
                    ),
                    DiscoveryJobDispatchDisposition(
                        job_id="job-2",
                        outcome="retrying",
                        failure_code="search_page_state_error",
                    ),
                ),
                queue_snapshot=DiscoveryQueueSnapshot(
                    pending_count=3,
                    claimable_count=2,
                    leased_count=0,
                    retry_scheduled_count=1,
                ),
            ),
            "limit_reached",
        ),
        (
            DiscoveryDispatchBatchResult(
                requested_limit=5,
                dispositions=(),
                blocker=CrawlerBlockerCode.CIRCUIT_OPEN,
                queue_snapshot=DiscoveryQueueSnapshot(
                    pending_count=3,
                    claimable_count=3,
                    leased_count=0,
                    retry_scheduled_count=0,
                ),
            ),
            "blocked",
        ),
    ],
)
def test_once_summary_distinguishes_limit_queue_and_blocker(
    result: DiscoveryDispatchBatchResult,
    expected_reason: str,
) -> None:
    summary = discovery_dispatch.build_discovery_one_shot_summary(result)

    assert summary.exit_reason == expected_reason
    assert summary.requested_limit == result.requested_limit
    assert summary.processed_count == result.processed_count
    assert summary.remaining_pending_count == result.queue_snapshot.pending_count
    assert summary.remaining_claimable_count == result.queue_snapshot.claimable_count
    assert summary.blocker == (
        result.blocker.value if result.blocker is not None else None
    )
    assert asdict(summary)["dispositions"] == [
        {
            "job_id": disposition.job_id,
            "outcome": disposition.outcome,
            "failure_code": disposition.failure_code,
        }
        for disposition in result.dispositions
    ]


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
async def test_dispatch_loop_reports_shared_blocker_without_stopping_observability() -> (
    None
):
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
    capsys: pytest.CaptureFixture[str],
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

    exit_code = discovery_dispatch.main(
        ["--once", "--limit", "4"],
        runtime_factory=fail_runtime_factory,
    )

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
    assert json.loads(capsys.readouterr().out) == {
        "blocker": CrawlerBlockerCode.DATABASE_UNREACHABLE.value,
        "circuit_reset_at": None,
        "dispositions": None,
        "exit_reason": "error",
        "processed_count": None,
        "remaining_claimable_count": None,
        "remaining_leased_count": None,
        "remaining_pending_count": None,
        "remaining_retry_scheduled_count": None,
        "requested_limit": 4,
    }


def test_main_once_reports_unknown_progress_after_partial_work_then_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingProcessor:
        def __init__(self) -> None:
            self.dispatched_job_ids: list[str] = []

        def process_pending(
            self,
            *,
            limit: int | None = None,
        ) -> DiscoveryDispatchBatchResult:
            del limit
            self.dispatched_job_ids.append("job-already-dispatched")
            raise RuntimeError("token=must-never-leak")

    processor = FailingProcessor()
    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: None,
    )
    runtime = discovery_dispatch.DiscoveryDispatchRuntime(
        processor=processor,
        run_service=RecordingRunService(),
    )

    exit_code = discovery_dispatch.main(
        ["--once", "--limit", "2"],
        runtime_factory=lambda *args, **kwargs: runtime,
    )

    encoded = capsys.readouterr().out
    assert exit_code == 1
    assert processor.dispatched_job_ids == ["job-already-dispatched"]
    assert json.loads(encoded) == {
        "blocker": "runtime_error",
        "circuit_reset_at": None,
        "dispositions": None,
        "exit_reason": "error",
        "processed_count": None,
        "remaining_claimable_count": None,
        "remaining_leased_count": None,
        "remaining_pending_count": None,
        "remaining_retry_scheduled_count": None,
        "requested_limit": 2,
    }
    assert "must-never-leak" not in encoded


def test_main_once_builds_runtime_and_reports_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
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
    assert built_args == [
        ("sqlite+pysqlite:///discovery-executor.sqlite3", tmp_path, 3)
    ]
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
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "blocker": None,
        "circuit_reset_at": None,
        "dispositions": [
            {
                "failure_code": None,
                "job_id": f"job-{index}",
                "outcome": "dispatched",
            }
            for index in range(3)
        ],
        "exit_reason": "queue_drained",
        "processed_count": 3,
        "remaining_claimable_count": 0,
        "remaining_leased_count": 0,
        "remaining_pending_count": 0,
        "remaining_retry_scheduled_count": 0,
        "requested_limit": 7,
    }


def test_main_once_returns_blocked_exit_code_and_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class BlockedProcessor:
        def process_pending(
            self,
            *,
            limit: int | None = None,
        ) -> DiscoveryDispatchBatchResult:
            return DiscoveryDispatchBatchResult(
                requested_limit=limit or 1,
                dispositions=(),
                blocker=CrawlerBlockerCode.CIRCUIT_OPEN,
                circuit_reset_at="2026-07-23T15:00:00+00:00",
                queue_snapshot=DiscoveryQueueSnapshot(
                    pending_count=2,
                    claimable_count=2,
                    leased_count=0,
                    retry_scheduled_count=0,
                ),
            )

    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: None,
    )
    runtime = discovery_dispatch.DiscoveryDispatchRuntime(
        processor=BlockedProcessor(),
        run_service=RecordingRunService(),
    )

    exit_code = discovery_dispatch.main(
        ["--once", "--limit", "1"],
        runtime_factory=lambda *args, **kwargs: runtime,
    )

    assert exit_code == 3
    assert json.loads(capsys.readouterr().out) == {
        "blocker": CrawlerBlockerCode.CIRCUIT_OPEN.value,
        "circuit_reset_at": "2026-07-23T15:00:00+00:00",
        "dispositions": [],
        "exit_reason": "blocked",
        "processed_count": 0,
        "remaining_claimable_count": 2,
        "remaining_leased_count": 0,
        "remaining_pending_count": 2,
        "remaining_retry_scheduled_count": 0,
        "requested_limit": 1,
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
        payload["watcher_status"] == "running" for payload in reporter.payloads[:2]
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


@pytest.mark.parametrize(
    ("argv", "enabled", "protocol"),
    [
        (_fault_cli_args(), None, "off"),
        (_fault_cli_args(), "false", "off"),
        (_fault_cli_args(once=False), "true", "off"),
        (_fault_cli_args(limit="2"), "true", "off"),
        (_fault_cli_args(), "true", "shadow"),
        (["--once", "--limit", "1", "--fault-mode", "nonzero_exit"], "true", "off"),
        (_fault_cli_args(job_id="not-a-uuid"), "true", "off"),
        (_fault_cli_args(tenant_id=None), "true", "off"),
    ],
)
def test_fault_injection_operator_gate_denies_before_runtime_build(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    argv: list[str],
    enabled: str | None,
    protocol: str,
) -> None:
    if enabled is None:
        monkeypatch.delenv("EGP_DISCOVERY_FAULT_INJECTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("EGP_DISCOVERY_FAULT_INJECTION_ENABLED", enabled)
    monkeypatch.setenv("EGP_CRAWLER_AGENT_PROTOCOL", protocol)
    aggregate_log = tmp_path / "Library" / "Logs" / "egp" / "crawl.log"
    aggregate_log.parent.mkdir(parents=True)
    aggregate_log.write_text("existing audit\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    rotate_calls: list[Path] = []
    monkeypatch.setattr(
        discovery_dispatch,
        "rotate_log_copytruncate",
        lambda path: rotate_calls.append(path),
    )
    built = False

    def runtime_factory(*args: object, **kwargs: object):
        nonlocal built
        built = True
        pytest.fail(f"denied injection built runtime: {args!r} {kwargs!r}")

    assert discovery_dispatch.main(argv, runtime_factory=runtime_factory) == 2
    assert built is False
    assert rotate_calls == []
    events = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    assert any(event.get("event") == "fault_injection_denied" for event in events)


def test_fault_injection_operator_gate_wires_authorized_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_FAULT_INJECTION_ENABLED", "true")
    monkeypatch.setenv("EGP_CRAWLER_AGENT_PROTOCOL", "off")
    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: None,
    )
    processor = RecordingDiscoveryProcessor()
    monkeypatch.setattr(
        processor,
        "process_pending",
        lambda *, limit=None: DiscoveryDispatchBatchResult(
            requested_limit=limit or 1,
            dispositions=(
                DiscoveryJobDispatchDisposition(
                    job_id=FAULT_JOB_ID,
                    outcome="fault_verified",
                    failure_code="worker_exit_nonzero",
                ),
            ),
        ),
    )
    run_service = RecordingRunService()
    built_kwargs: list[dict[str, object]] = []

    def runtime_factory(*args: object, **kwargs: object):
        del args
        built_kwargs.append(dict(kwargs))
        return discovery_dispatch.DiscoveryDispatchRuntime(
            processor=processor,
            run_service=run_service,
        )

    assert (
        discovery_dispatch.main(
            _fault_cli_args(),
            runtime_factory=runtime_factory,
        )
        == 0
    )
    assert built_kwargs == [
        {
            "artifact_root": None,
            "worker_count": None,
            "fault_mode": "nonzero_exit",
            "fault_job_id": FAULT_JOB_ID,
            "fault_tenant_id": FAULT_TENANT_ID,
        }
    ]
    events = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    assert any(
        event.get("event") == "fault_injection_authorized"
        and event.get("fault_mode") == "nonzero_exit"
        for event in events
    )
    assert any(
        event.get("event") == "fault_injection_observed"
        and event.get("observed_failure_code") == "worker_exit_nonzero"
        for event in events
    )


@pytest.mark.parametrize("enabled", [None, "true"])
def test_fault_injection_operator_gate_redacts_invalid_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    enabled: str | None,
) -> None:
    if enabled is None:
        monkeypatch.delenv("EGP_DISCOVERY_FAULT_INJECTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("EGP_DISCOVERY_FAULT_INJECTION_ENABLED", enabled)
    monkeypatch.setenv("EGP_CRAWLER_AGENT_PROTOCOL", "off")
    secret_like_mode = "token-super-sensitive-value"

    assert (
        discovery_dispatch.main(
            _fault_cli_args(mode=secret_like_mode),
            runtime_factory=lambda *args, **kwargs: pytest.fail(
                "runtime must not be built"
            ),
        )
        == 2
    )

    stderr = capsys.readouterr().err
    assert secret_like_mode not in stderr
    events = [json.loads(line) for line in stderr.splitlines() if line.startswith("{")]
    assert any(
        event.get("event") == "fault_injection_denied"
        and event.get("fault_mode") == "invalid"
        and event.get("reason")
        == ("authorization_disabled" if enabled is None else "invalid_mode")
        for event in events
    )


def test_fault_injection_operator_returns_nonzero_when_outcome_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_FAULT_INJECTION_ENABLED", "true")
    monkeypatch.setenv("EGP_CRAWLER_AGENT_PROTOCOL", "off")
    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: None,
    )
    processor = RecordingDiscoveryProcessor()
    monkeypatch.setattr(
        processor,
        "process_pending",
        lambda *, limit=None: DiscoveryDispatchBatchResult(
            requested_limit=limit or 1,
            dispositions=(
                DiscoveryJobDispatchDisposition(
                    job_id=FAULT_JOB_ID,
                    outcome="failed",
                    failure_code="worker_terminated",
                ),
            ),
        ),
    )
    runtime = discovery_dispatch.DiscoveryDispatchRuntime(
        processor=processor,
        run_service=RecordingRunService(),
    )

    assert (
        discovery_dispatch.main(
            _fault_cli_args(mode="worker_crash"),
            runtime_factory=lambda *args, **kwargs: runtime,
        )
        == 4
    )
    events = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    assert any(event.get("event") == "fault_injection_mismatch" for event in events)


def test_fault_injection_operator_returns_nonzero_for_wrong_job_disposition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_FAULT_INJECTION_ENABLED", "true")
    monkeypatch.setenv("EGP_CRAWLER_AGENT_PROTOCOL", "off")
    monkeypatch.setattr(
        discovery_dispatch,
        "build_crawler_runtime_reporter_from_env",
        lambda: None,
    )
    processor = RecordingDiscoveryProcessor()
    monkeypatch.setattr(
        processor,
        "process_pending",
        lambda *, limit=None: DiscoveryDispatchBatchResult(
            requested_limit=limit or 1,
            dispositions=(
                DiscoveryJobDispatchDisposition(
                    job_id="22222222-2222-4222-8222-222222222222",
                    outcome="fault_verified",
                    failure_code="worker_exit_nonzero",
                ),
            ),
        ),
    )
    runtime = discovery_dispatch.DiscoveryDispatchRuntime(
        processor=processor,
        run_service=RecordingRunService(),
    )

    assert (
        discovery_dispatch.main(
            _fault_cli_args(mode="nonzero_exit"),
            runtime_factory=lambda *args, **kwargs: runtime,
        )
        == 4
    )
    events = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{")
    ]
    assert any(
        event.get("event") == "fault_injection_mismatch"
        and event.get("expected_discovery_job_id") == FAULT_JOB_ID
        and event.get("observed_discovery_job_id")
        == "22222222-2222-4222-8222-222222222222"
        for event in events
    )


def test_background_lifespan_uses_standalone_discovery_executor_loop() -> None:
    assert (
        background.run_discovery_dispatch_loop
        is discovery_dispatch.run_discovery_dispatch_loop
    )
