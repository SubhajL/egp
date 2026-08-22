from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


RELEASE_SHA = "a" * 40


def _runtime_evidence() -> dict[str, object]:
    roles = (
        "migrate",
        "api",
        "webhook-executor",
        "crawler-agent-inbox-executor",
        "discovery-executor",
    )
    collected_at = datetime.now(UTC).isoformat()
    image_id = f"sha256:{'1' * 64}"
    return {
        "collected_at": collected_at,
        "source_release_sha": RELEASE_SHA,
        "role_revisions": {
            role: {
                "oci_revision": RELEASE_SHA,
                "baked_release_sha": RELEASE_SHA,
                "image_id": image_id,
                "container_image_id": image_id,
            }
            for role in roles
        },
        "mac_release_sha": RELEASE_SHA,
        "discovery_executor_replicas": 0,
        "crawler_agent_protocol": "off",
        "profile_execution_backend": "legacy",
        "pending_jobs_by_backend": {"legacy": 0, "agent": 0},
        "doctor": {
            "status": "ready",
            "blockers": [],
            "defer_reasons": [],
            "heartbeat": {
                "heartbeat_status": "online",
                "heartbeat_age_seconds": 1,
                "reported_at": collected_at,
            },
            "profile": {"status": "ready", "lock_status": "free"},
            "queue": {
                "pending_count": 0,
                "claimable_count": 0,
                "leased_count": 0,
                "retry_scheduled_count": 0,
                "oldest_claimable_age_seconds": None,
            },
        },
        "password": "must-not-appear",
    }


def _write_long_running_tree(tmp_path: Path) -> tuple[list[str], Path]:
    child_pid_path = tmp_path / "descendant.pid"
    script_path = tmp_path / "long_running_tree.py"
    script_path.write_text(
        """
import pathlib
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
while True:
    time.sleep(1)
""".lstrip(),
        encoding="utf-8",
    )
    return [sys.executable, str(script_path), str(child_pid_path)], child_pid_path


def _doctor_command(*, online: bool = True) -> list[str]:
    doctor = _runtime_evidence()["doctor"]
    doctor["heartbeat"]["heartbeat_status"] = (  # type: ignore[index]
        "online" if online else "offline"
    )
    return [
        sys.executable,
        "-c",
        f"import json; print({json.dumps(json.dumps(doctor))})",
    ]


def _blocking_doctor_tree(tmp_path: Path) -> tuple[list[str], Path, Path]:
    doctor_pid_path = tmp_path / "doctor.pid"
    child_pid_path = tmp_path / "doctor-descendant.pid"
    script_path = tmp_path / "blocking_doctor.py"
    script_path.write_text(
        """
import os
import pathlib
import subprocess
import sys
import time

pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding="utf-8")
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
pathlib.Path(sys.argv[2]).write_text(str(child.pid), encoding="utf-8")
while True:
    time.sleep(1)
""".lstrip(),
        encoding="utf-8",
    )
    return (
        [sys.executable, str(script_path), str(doctor_pid_path), str(child_pid_path)],
        doctor_pid_path,
        child_pid_path,
    )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_supervised_interval_stops_and_reaps_the_complete_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    monkeypatch.setattr(supervisor, "MIN_DURATION_SECONDS", 0.1)
    command, child_pid_path = _write_long_running_tree(tmp_path)

    report = supervisor.supervise(
        command=command,
        doctor_command=_doctor_command(),
        duration_seconds=0.3,
        expected_release_sha=RELEASE_SHA,
        runtime_evidence=_runtime_evidence(),
        termination_grace_seconds=1.0,
        observed_at=datetime(2026, 8, 22, 14, 0, tzinfo=UTC),
    )

    assert report.schema_version == 1
    assert report.stage == "supervised"
    assert report.status == "accepted"
    assert report.release_sha == RELEASE_SHA
    assert report.deadline_reached is True
    assert report.process_group_reaped is True
    assert report.postflight_runtime_accepted is True
    assert report.observed_at == "2026-08-22T14:00:00+00:00"
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while _pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _pid_exists(child_pid)


def test_supervised_interval_rejects_early_watcher_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    monkeypatch.setattr(supervisor, "MIN_DURATION_SECONDS", 0.1)

    report = supervisor.supervise(
        command=[sys.executable, "-c", "raise SystemExit(0)"],
        doctor_command=_doctor_command(),
        duration_seconds=0.3,
        expected_release_sha=RELEASE_SHA,
        runtime_evidence=_runtime_evidence(),
        termination_grace_seconds=0.2,
    )

    assert report.status == "rejected"
    assert "watcher_exited_before_deadline" in report.errors


def test_supervised_interval_rejects_unhealthy_postflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    monkeypatch.setattr(supervisor, "MIN_DURATION_SECONDS", 0.1)
    command, _ = _write_long_running_tree(tmp_path)
    report = supervisor.supervise(
        command=command,
        doctor_command=_doctor_command(online=False),
        duration_seconds=0.2,
        expected_release_sha=RELEASE_SHA,
        runtime_evidence=_runtime_evidence(),
        termination_grace_seconds=1.0,
    )

    assert report.status == "rejected"
    assert report.postflight_runtime_accepted is False
    assert "postflight_runtime_rejected" in report.errors


def test_supervised_interval_rejects_runtime_evidence_before_starting_watcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    monkeypatch.setattr(supervisor, "MIN_DURATION_SECONDS", 0.1)
    started_marker = tmp_path / "watcher-started"
    evidence = _runtime_evidence()
    evidence["crawler_agent_protocol"] = "shadow"

    report = supervisor.supervise(
        command=[
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import time; "
                f"Path({str(started_marker)!r}).write_text('started'); time.sleep(60)"
            ),
        ],
        doctor_command=_doctor_command(),
        duration_seconds=0.2,
        expected_release_sha=RELEASE_SHA,
        runtime_evidence=evidence,
        termination_grace_seconds=1.0,
    )

    assert report.status == "rejected"
    assert "preflight_runtime_rejected" in report.errors
    assert report.deadline_reached is False
    assert report.process_group_reaped is True
    assert report.postflight_runtime_accepted is False
    assert not started_marker.exists()


def test_supervised_interval_rejects_evidence_without_postflight_time_budget(
    tmp_path: Path,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    started_marker = tmp_path / "watcher-started"
    evidence = _runtime_evidence()
    stale_but_preflight_valid = datetime.now(UTC) - timedelta(seconds=150)
    evidence["collected_at"] = stale_but_preflight_valid.isoformat()
    evidence["doctor"]["heartbeat"]["reported_at"] = datetime.now(UTC).isoformat()  # type: ignore[index]

    report = supervisor.supervise(
        command=[
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import time; "
                f"Path({str(started_marker)!r}).write_text('started'); time.sleep(60)"
            ),
        ],
        doctor_command=_doctor_command(),
        duration_seconds=120,
        expected_release_sha=RELEASE_SHA,
        runtime_evidence=evidence,
        termination_grace_seconds=10,
    )

    assert report.status == "rejected"
    assert report.errors == ("preflight_evidence_window_too_short",)
    assert report.deadline_reached is False
    assert report.process_group_reaped is True
    assert not started_marker.exists()


def test_supervised_interval_verifies_runtime_before_and_after_watcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    monkeypatch.setattr(supervisor, "MIN_DURATION_SECONDS", 0.1)
    command, _ = _write_long_running_tree(tmp_path)
    original_verify = supervisor.verify_runtime_evidence
    calls: list[str] = []

    def recording_verify(*args: object, **kwargs: object):
        calls.append("verify")
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(supervisor, "verify_runtime_evidence", recording_verify)
    report = supervisor.supervise(
        command=command,
        doctor_command=_doctor_command(),
        duration_seconds=0.2,
        expected_release_sha=RELEASE_SHA,
        runtime_evidence=_runtime_evidence(),
        termination_grace_seconds=1.0,
    )

    assert report.status == "accepted"
    assert calls == ["verify", "verify"]


def test_supervisor_cli_writes_sanitized_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    monkeypatch.setattr(supervisor, "MIN_DURATION_SECONDS", 0.1)
    command, _ = _write_long_running_tree(tmp_path)
    evidence_path = tmp_path / "runtime.json"
    output_path = tmp_path / "supervised.json"
    evidence_path.write_text(json.dumps(_runtime_evidence()), encoding="utf-8")

    exit_code = supervisor.main(
        [
            "--duration-seconds",
            "0.2",
            "--expected-release-sha",
            RELEASE_SHA,
            "--runtime-evidence",
            str(evidence_path),
            "--output",
            str(output_path),
            "--command-json",
            json.dumps(command),
            "--doctor-command-json",
            json.dumps(_doctor_command()),
        ]
    )

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(stdout)["status"] == "accepted"
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "accepted"
    assert "must-not-appear" not in stdout
    assert "must-not-appear" not in output_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("termination_signal", [signal.SIGTERM, signal.SIGHUP])
def test_supervisor_cli_signal_reaps_watcher_and_descendants(
    tmp_path: Path,
    termination_signal: signal.Signals,
) -> None:
    command, child_pid_path = _write_long_running_tree(tmp_path)
    evidence_path = tmp_path / "runtime.json"
    output_path = tmp_path / "interrupted.json"
    evidence_path.write_text(json.dumps(_runtime_evidence()), encoding="utf-8")
    runner = tmp_path / "supervisor_runner.py"
    runner.write_text(
        """
import sys
import scripts.supervise_remote_crawl as supervisor

supervisor.MIN_DURATION_SECONDS = 0.1
raise SystemExit(supervisor.main(sys.argv[1:]))
""".lstrip(),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(runner),
            "--duration-seconds",
            "60",
            "--expected-release-sha",
            RELEASE_SHA,
            "--runtime-evidence",
            str(evidence_path),
            "--output",
            str(output_path),
            "--command-json",
            json.dumps(command),
            "--doctor-command-json",
            json.dumps(_doctor_command()),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
    )
    deadline = time.monotonic() + 3
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert child_pid_path.exists()
    descendant_pid = int(child_pid_path.read_text(encoding="utf-8"))

    process.send_signal(termination_signal)
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 1, stderr
    receipt = json.loads(output_path.read_text(encoding="utf-8"))
    assert json.loads(stdout) == receipt
    assert receipt["status"] == "rejected"
    assert receipt["deadline_reached"] is False
    assert receipt["process_group_reaped"] is True
    assert "supervision_interrupted" in receipt["errors"]
    deadline = time.monotonic() + 2
    while _pid_exists(descendant_pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not _pid_exists(descendant_pid)


@pytest.mark.parametrize("termination_signal", [signal.SIGTERM, signal.SIGHUP])
def test_supervisor_cli_signal_during_postflight_reaps_doctor_tree(
    tmp_path: Path,
    termination_signal: signal.Signals,
) -> None:
    evidence_path = tmp_path / "runtime.json"
    output_path = tmp_path / "interrupted-postflight.json"
    evidence_path.write_text(json.dumps(_runtime_evidence()), encoding="utf-8")
    doctor_command, doctor_pid_path, doctor_child_pid_path = _blocking_doctor_tree(
        tmp_path
    )
    runner = tmp_path / "postflight_supervisor_runner.py"
    runner.write_text(
        """
import sys
import scripts.supervise_remote_crawl as supervisor

supervisor.MIN_DURATION_SECONDS = 0.1
raise SystemExit(supervisor.main(sys.argv[1:]))
""".lstrip(),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(runner),
            "--duration-seconds",
            "0.2",
            "--expected-release-sha",
            RELEASE_SHA,
            "--runtime-evidence",
            str(evidence_path),
            "--output",
            str(output_path),
            "--command-json",
            json.dumps([sys.executable, "-c", "import time; time.sleep(60)"]),
            "--doctor-command-json",
            json.dumps(doctor_command),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
    )
    doctor_pid = 0
    doctor_child_pid = 0
    try:
        deadline = time.monotonic() + 4
        while (
            not doctor_pid_path.exists() or not doctor_child_pid_path.exists()
        ) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert doctor_pid_path.exists()
        assert doctor_child_pid_path.exists()
        doctor_pid = int(doctor_pid_path.read_text(encoding="utf-8"))
        doctor_child_pid = int(doctor_child_pid_path.read_text(encoding="utf-8"))

        process.send_signal(termination_signal)
        stdout, stderr = process.communicate(timeout=5)

        assert process.returncode == 1, stderr
        receipt = json.loads(output_path.read_text(encoding="utf-8"))
        assert json.loads(stdout) == receipt
        assert receipt["status"] == "rejected"
        assert receipt["process_group_reaped"] is True
        assert "supervision_interrupted" in receipt["errors"]
        assert not _pid_exists(doctor_pid)
        assert not _pid_exists(doctor_child_pid)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        if doctor_pid > 0 and _pid_exists(doctor_pid):
            try:
                os.killpg(doctor_pid, signal.SIGKILL)
            except OSError:
                pass


def test_supervisor_default_duration_and_freshness_contract_is_satisfiable() -> None:
    import scripts.supervise_remote_crawl as supervisor
    import scripts.track_bc_verify as verifier

    assert supervisor.MIN_DURATION_SECONDS == 120
    assert supervisor.MAX_DURATION_SECONDS == 180
    assert supervisor.MAX_TERMINATION_GRACE_SECONDS == 30
    assert (
        supervisor.MAX_DURATION_SECONDS
        + (2 * supervisor.MAX_TERMINATION_GRACE_SECONDS)
        + supervisor.DOCTOR_TIMEOUT_SECONDS
        + supervisor.POSTFLIGHT_SAFETY_MARGIN_SECONDS
        < verifier.RUNTIME_EVIDENCE_MAX_AGE_SECONDS
    )


@pytest.mark.parametrize("duration", [0, -1, 119, 181])
def test_supervisor_rejects_operational_duration_outside_two_to_three_minutes(
    duration: float,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    with pytest.raises(ValueError, match="duration"):
        supervisor.supervise(
            command=[sys.executable, "-c", "pass"],
            doctor_command=_doctor_command(),
            duration_seconds=duration,
            expected_release_sha=RELEASE_SHA,
            runtime_evidence=_runtime_evidence(),
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_supervisor_rejects_nonfinite_duration_and_termination_grace(
    value: float,
) -> None:
    import scripts.supervise_remote_crawl as supervisor

    with pytest.raises(ValueError, match="duration"):
        supervisor._validate_duration(value)
    with pytest.raises(ValueError, match="grace"):
        supervisor._validate_grace(value)
