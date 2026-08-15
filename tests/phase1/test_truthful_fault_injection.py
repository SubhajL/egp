"""Canonical F7: injected failures traverse real child-process cleanup paths."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchRequest,
    NonRetriableDiscoveryDispatchError,
)
from egp_api.services.discovery_worker_dispatcher import (
    FAULT_INJECTION_MODES,
    DiscoverySpawnError,
    SubprocessDiscoveryDispatcher,
)
from egp_shared_types.enums import DiscoveryFailureCode
from egp_worker.fault_injection import FAULT_MODES


class RecordingRunRepository:
    """Minimal run-state boundary used to observe dispatcher terminalization."""

    def __init__(self) -> None:
        self.runs: dict[str, dict[str, object]] = {}

    def create_run(self, **values: object) -> None:
        run_id = str(values["run_id"])
        self.runs[run_id] = {
            **values,
            "status": "queued",
            "finished_at": None,
            "failure_reason": None,
            "summary_json": {},
        }

    def update_run_summary(
        self,
        run_id: str,
        *,
        summary_json: dict[str, object] | None,
    ) -> None:
        current = self.runs[run_id]["summary_json"]
        assert isinstance(current, dict)
        current.update(summary_json or {})

    def fail_run_if_active(
        self,
        run_id: str,
        *,
        error: str,
        failure_reason: str,
    ) -> SimpleNamespace | None:
        run = self.runs[run_id]
        if run["status"] not in {"queued", "running"}:
            return None
        run.update(
            status="failed",
            finished_at="2026-08-15T00:00:00+00:00",
            error=error,
            failure_reason=failure_reason,
        )
        return SimpleNamespace(id=run_id)


def _request(fault_mode: str | None) -> DiscoveryDispatchRequest:
    return DiscoveryDispatchRequest(
        tenant_id="tenant-f7",
        profile_id="profile-f7",
        profile_type="tor",
        keyword="truthful fault",
        fault_mode=fault_mode,
    )


def _events(artifact_root: Path, run_id: str) -> list[dict[str, object]]:
    log_path = artifact_root / "tenants" / "tenant-f7" / "runs" / run_id / "worker.log"
    return [
        json.loads(line)
        for line in log_path.read_text().splitlines()
        if line.startswith("{")
    ]


@pytest.mark.parametrize(
    ("fault_mode", "expected_exception", "expected_code", "expected_reason"),
    [
        (
            "worker_timeout",
            DiscoverySpawnError,
            DiscoveryFailureCode.WORKER_TIMEOUT,
            "worker_timeout",
        ),
        (
            "nonzero_exit",
            DiscoverySpawnError,
            DiscoveryFailureCode.WORKER_EXIT_NONZERO,
            "worker_exit_nonzero",
        ),
        (
            "missing_result",
            DiscoverySpawnError,
            DiscoveryFailureCode.WORKER_RESULT_MISSING,
            "worker_result_missing",
        ),
        (
            "entitlement_denied",
            NonRetriableDiscoveryDispatchError,
            DiscoveryFailureCode.ENTITLEMENT_DENIED,
            "entitlement_denied",
        ),
        (
            "worker_crash",
            NonRetriableDiscoveryDispatchError,
            DiscoveryFailureCode.WORKER_TERMINATED,
            "worker_terminated",
        ),
    ],
)
def test_every_injected_fault_terminalizes_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault_mode: str,
    expected_exception: type[Exception],
    expected_code: DiscoveryFailureCode,
    expected_reason: str,
) -> None:
    repository = RecordingRunRepository()
    artifact_root = tmp_path / "artifacts"
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=artifact_root,
        run_repository=repository,
        timeout_seconds=5,
        fault_injection_authorized=True,
        browser_profile_root=tmp_path / "profiles",
    )
    dispatcher._fault_timeout_seconds = 0.05

    reconciliations: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda *, run_id, terminal_reason: (
            reconciliations.append((run_id, terminal_reason)) or True
        ),
    )
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []
    popen_kwargs: list[dict[str, object]] = []

    def tracking_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(*args, **kwargs)
        children.append(process)
        popen_kwargs.append(dict(kwargs))
        return process

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        tracking_popen,
    )

    with pytest.raises(expected_exception) as exc_info:
        dispatcher.dispatch_cancellable(_request(fault_mode), cancellation_event=None)

    assert getattr(exc_info.value, "failure_code", None) == expected_code
    assert getattr(exc_info.value, "fault_evidence_verified", False) is True
    assert len(repository.runs) == 1
    run_id, run = next(iter(repository.runs.items()))
    assert run["status"] == "failed"
    assert run["finished_at"] is not None
    assert run["failure_reason"] == expected_reason

    assert len(children) == 1
    child = children[0]
    assert child.args == [
        sys.executable,
        "-m",
        "egp_worker.fault_injection",
        fault_mode,
    ]
    assert len(popen_kwargs) == 1
    assert popen_kwargs[0]["start_new_session"] is True
    assert child.poll() is not None
    if fault_mode == "worker_timeout":
        assert child.returncode == -signal.SIGKILL

    assert reconciliations
    assert reconciliations[0][0] == run_id
    events = _events(artifact_root, run_id)
    assert any(
        event.get("event") == "fault_injection_started"
        and event.get("fault_mode") == fault_mode
        for event in events
    )
    assert any(
        event.get("event") == "fault_injection_terminalized"
        and event.get("failure_code") == expected_code.value
        for event in events
    )
    assert not (tmp_path / "profiles" / run_id).exists()


def test_unknown_injected_fault_terminalizes_reserved_run_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = RecordingRunRepository()
    artifact_root = tmp_path / "artifacts"
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=artifact_root,
        run_repository=repository,
        fault_injection_authorized=True,
        browser_profile_root=tmp_path / "profiles",
    )
    reconciliations: list[tuple[str, str]] = []
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda *, run_id, terminal_reason: (
            reconciliations.append((run_id, terminal_reason)) or True
        ),
    )

    def unexpected_popen(*args: object, **kwargs: object) -> None:
        pytest.fail(f"unknown mode spawned a process: {args!r} {kwargs!r}")

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        unexpected_popen,
    )

    with pytest.raises(NonRetriableDiscoveryDispatchError) as exc_info:
        dispatcher.dispatch_cancellable(_request("not-a-mode"), cancellation_event=None)

    assert exc_info.value.failure_code == DiscoveryFailureCode.DISPATCH_EXCEPTION
    assert "not-a-mode" not in str(exc_info.value)
    assert len(repository.runs) == 1
    run_id, run = next(iter(repository.runs.items()))
    assert run["status"] == "failed"
    assert run["failure_reason"] == DiscoveryFailureCode.DISPATCH_EXCEPTION.value
    assert reconciliations
    events = _events(artifact_root, run_id)
    assert any(event.get("event") == "fault_injection_invalid_mode" for event in events)
    assert "not-a-mode" not in json.dumps(events)


def test_fault_mode_vocabulary_matches_child_harness() -> None:
    assert FAULT_INJECTION_MODES == FAULT_MODES


def test_terminalization_audit_reports_failed_durable_transition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = RecordingRunRepository()
    artifact_root = tmp_path / "artifacts"
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=artifact_root,
        run_repository=repository,
        fault_injection_authorized=True,
        browser_profile_root=tmp_path / "profiles",
    )

    def fail_run_write(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("injected run repository outage")

    monkeypatch.setattr(repository, "fail_run_if_active", fail_run_write)
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda **kwargs: True,
    )

    with pytest.raises(NonRetriableDiscoveryDispatchError) as exc_info:
        dispatcher.dispatch_cancellable(
            _request("nonzero_exit"), cancellation_event=None
        )

    assert exc_info.value.failure_code == DiscoveryFailureCode.DISPATCH_EXCEPTION
    assert getattr(exc_info.value, "fault_evidence_verified", False) is False
    run_id, run = next(iter(repository.runs.items()))
    assert run["status"] == "queued"
    events = _events(artifact_root, run_id)
    assert any(
        event.get("event") == "fault_injection_terminalization_failed"
        for event in events
    )
    assert not any(
        event.get("event") == "fault_injection_terminalized" for event in events
    )


def test_direct_fault_seam_requires_authorized_dispatcher(tmp_path: Path) -> None:
    repository = RecordingRunRepository()
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=tmp_path / "artifacts",
        run_repository=repository,
        browser_profile_root=tmp_path / "profiles",
    )

    with pytest.raises(NonRetriableDiscoveryDispatchError) as exc_info:
        dispatcher.dispatch_cancellable(
            _request("nonzero_exit"), cancellation_event=None
        )

    assert exc_info.value.failure_code == DiscoveryFailureCode.DISPATCH_EXCEPTION
    assert repository.runs == {}


def test_injected_setup_failure_terminalizes_reserved_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = RecordingRunRepository()
    artifact_root = tmp_path / "artifacts"
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=artifact_root,
        run_repository=repository,
        fault_injection_authorized=True,
        browser_profile_root=tmp_path / "profiles",
    )
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.tempfile.SpooledTemporaryFile",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("spool unavailable")),
    )

    with pytest.raises(RuntimeError, match="spool unavailable"):
        dispatcher.dispatch_cancellable(
            _request("nonzero_exit"), cancellation_event=None
        )

    run_id, run = next(iter(repository.runs.items()))
    assert run["status"] == "failed"
    assert run["failure_reason"] == DiscoveryFailureCode.DISPATCH_EXCEPTION.value
    assert any(
        event.get("event") == "fault_injection_terminalized"
        for event in _events(artifact_root, run_id)
    )


def test_unexpected_injected_communication_failure_reaps_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = RecordingRunRepository()
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=tmp_path / "artifacts",
        run_repository=repository,
        fault_injection_authorized=True,
        browser_profile_root=tmp_path / "profiles",
    )
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda **kwargs: True,
    )
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def tracking_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        tracking_popen,
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher._communicate_with_cancellation",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("communication failed")
        ),
    )

    with pytest.raises(RuntimeError, match="communication failed"):
        dispatcher.dispatch_cancellable(
            _request("worker_timeout"), cancellation_event=None
        )

    assert len(children) == 1
    assert children[0].poll() is not None
    run = next(iter(repository.runs.values()))
    assert run["status"] == "failed"
    assert run["failure_reason"] == DiscoveryFailureCode.DISPATCH_EXCEPTION.value


def test_operator_fault_preflight_skips_real_circuit_and_profile_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=tmp_path / "artifacts",
        fault_mode="nonzero_exit",
        fault_injection_authorized=True,
        browser_profile_root=tmp_path / "profiles",
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.get_default_rate_limiter",
        lambda: pytest.fail("fault preflight must not inspect the real e-GP circuit"),
    )

    assert dispatcher.prepare_for_dispatch().should_dispatch is True


def test_worker_log_resolution_failure_does_not_orphan_injected_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = RecordingRunRepository()
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=tmp_path / "artifacts",
        run_repository=repository,
        fault_injection_authorized=True,
        browser_profile_root=tmp_path / "profiles",
    )
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda **kwargs: True,
    )
    original_resolve = Path.resolve

    def fail_worker_log_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        if path.name == "worker.log":
            raise OSError("worker log path unavailable")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_worker_log_resolve)

    with pytest.raises(DiscoverySpawnError) as exc_info:
        dispatcher.dispatch_cancellable(
            _request("nonzero_exit"), cancellation_event=None
        )

    assert exc_info.value.failure_code == DiscoveryFailureCode.WORKER_EXIT_NONZERO
    assert getattr(exc_info.value, "fault_evidence_verified", False) is True
    run = next(iter(repository.runs.values()))
    assert run["status"] == "failed"


def test_timeout_diagnostic_failure_still_terminalizes_injected_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = RecordingRunRepository()
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=tmp_path / "artifacts",
        run_repository=repository,
        fault_injection_authorized=True,
        fault_timeout_seconds=0.05,
        browser_profile_root=tmp_path / "profiles",
    )
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher._drain_worker_stdout",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("diagnostic drain failed")
        ),
    )

    with pytest.raises(DiscoverySpawnError) as exc_info:
        dispatcher.dispatch_cancellable(
            _request("worker_timeout"), cancellation_event=None
        )

    assert exc_info.value.failure_code == DiscoveryFailureCode.WORKER_TIMEOUT
    assert getattr(exc_info.value, "fault_evidence_verified", False) is True
    run = next(iter(repository.runs.values()))
    assert run["status"] == "failed"
    assert run["finished_at"] is not None


def test_timeout_cleanup_terminates_real_descendant_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = RecordingRunRepository()
    descendant_pid_path = tmp_path / "descendant.pid"
    dispatcher = SubprocessDiscoveryDispatcher(
        "sqlite+pysqlite:///:memory:",
        artifact_root=tmp_path / "artifacts",
        run_repository=repository,
        fault_injection_authorized=True,
        fault_timeout_seconds=0.5,
        browser_profile_root=tmp_path / "profiles",
    )
    monkeypatch.setattr(
        dispatcher,
        "_reconcile_candidate_attempts",
        lambda **kwargs: True,
    )
    descendant_script = "import time; time.sleep(60)"
    leader_script = (
        "import pathlib, subprocess, sys, time; "
        "descendant = subprocess.Popen([sys.executable, '-c', sys.argv[2]]); "
        "pathlib.Path(sys.argv[1]).write_text(str(descendant.pid)); "
        "sys.stdin.buffer.read(); time.sleep(60)"
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher._fault_worker_command",
        lambda mode: [
            sys.executable,
            "-c",
            leader_script,
            str(descendant_pid_path),
            descendant_script,
        ],
    )

    with pytest.raises(DiscoverySpawnError) as exc_info:
        dispatcher.dispatch_cancellable(
            _request("worker_timeout"), cancellation_event=None
        )

    assert exc_info.value.failure_code == DiscoveryFailureCode.WORKER_TIMEOUT
    assert descendant_pid_path.exists()
    descendant_pid = int(descendant_pid_path.read_text())
    deadline = time.monotonic() + 2.0
    descendant_exists = True
    while descendant_exists and time.monotonic() < deadline:
        try:
            os.kill(descendant_pid, 0)
        except ProcessLookupError:
            descendant_exists = False
        else:
            time.sleep(0.02)
    if descendant_exists:
        os.kill(descendant_pid, signal.SIGKILL)
    assert descendant_exists is False
