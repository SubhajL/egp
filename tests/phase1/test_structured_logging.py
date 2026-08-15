"""Acceptance tests for PR-CANARY-01 structured logging primitives.

These tests are the contract — they were authored by Claude (the orchestrator)
and MUST NOT be modified by the delegate.  The delegate's job is to make them
GREEN by implementing the bodies in
``packages/observability/src/egp_observability/logging.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from egp_observability.logging import (
    RESULT_FRAME_BEGIN,
    RESULT_FRAME_END,
    make_event,
    redact_preview,
    rotate_log_copytruncate,
    tail_bounded_preview,
)


# ---------------------------------------------------------------------------
# T1: make_event produces UTC-timestamped single-line JSON
# ---------------------------------------------------------------------------
def test_make_event_produces_utc_timestamped_single_line_json() -> None:
    raw = make_event(
        "dispatch_started",
        run_id="r1",
        owner_pid=42,
        release_sha="abc123",
    )
    assert "\n" not in raw, "output must be a single line"

    payload = json.loads(raw)
    assert payload["event"] == "dispatch_started"
    assert payload["run_id"] == "r1"
    assert payload["owner_pid"] == 42
    assert payload["release_sha"] == "abc123"

    ts = payload["ts"]
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"timestamp must be UTC, got {ts}"

    assert "job_id" not in payload, "None-valued fields must be omitted"


# ---------------------------------------------------------------------------
# T7: make_event omits None fields and sorts keys
# ---------------------------------------------------------------------------
def test_make_event_omits_none_fields_and_sorts_keys() -> None:
    raw = make_event(
        "worker_started",
        release_sha="abc123",
        job_id=None,
        child_pid=None,
    )
    payload = json.loads(raw)
    assert payload["release_sha"] == "abc123"
    assert "job_id" not in payload, "None job_id must be omitted"
    assert "child_pid" not in payload, "None child_pid must be omitted"

    keys = list(payload.keys())
    assert keys == sorted(keys), f"keys must be sorted, got {keys}"


# ---------------------------------------------------------------------------
# T2: framed result is extracted before fallback reverse scan
# ---------------------------------------------------------------------------
def test_framed_result_is_extracted_before_fallback_reverse_scan() -> None:
    from egp_api.services.discovery_worker_dispatcher import (
        _decode_framed_or_fallback_result,
    )

    framed_dict = {"run_id": "framed-1", "run_status": "succeeded"}
    lastline_dict = {"run_id": "lastline-1", "run_status": "failed"}

    stdout = "\n".join(
        [
            "some noise",
            "more noise",
            RESULT_FRAME_BEGIN,
            json.dumps(framed_dict, sort_keys=True),
            RESULT_FRAME_END,
            "trailing noise",
            json.dumps(lastline_dict, sort_keys=True),
        ]
    )

    result = _decode_framed_or_fallback_result(stdout)
    assert result is not None
    assert result["run_id"] == "framed-1", (
        "must extract framed result, not the last-line dict"
    )


# ---------------------------------------------------------------------------
# T3: framed result falls back to reverse scan when no frame
# ---------------------------------------------------------------------------
def test_framed_result_falls_back_to_reverse_scan_when_no_frame() -> None:
    from egp_api.services.discovery_worker_dispatcher import (
        _decode_framed_or_fallback_result,
    )

    expected = {"run_id": "fallback-1", "run_status": "succeeded"}
    stdout = "\n".join(
        [
            "some noise",
            "more noise",
            json.dumps(expected, sort_keys=True),
        ]
    )

    result = _decode_framed_or_fallback_result(stdout)
    assert result is not None
    assert result["run_id"] == "fallback-1", (
        "must fall back to reverse-scan when no frame markers"
    )


# ---------------------------------------------------------------------------
# T4: tail_bounded_preview preserves terminal exception
# ---------------------------------------------------------------------------
def test_tail_bounded_preview_preserves_terminal_exception() -> None:
    node_warnings = "W" * 4000
    traceback = "T" * 970 + "\nRuntimeError: boom"
    text = node_warnings + traceback

    result = tail_bounded_preview(text, limit=2000)
    assert result is not None
    assert result.endswith("RuntimeError: boom"), (
        f"must preserve terminal exception, got tail: ...{result[-40:]}"
    )
    assert result.startswith("..."), "must prepend ... when truncated"
    assert len(result) <= 2003, f"length {len(result)} exceeds limit+3"


# ---------------------------------------------------------------------------
# T5: redact_preview removes known secret patterns
# ---------------------------------------------------------------------------
def test_redact_preview_removes_known_secret_patterns() -> None:
    text = (
        "connecting to postgresql://egp:secret_password@host/db\n"
        "token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSJ9.sig\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig\n"
        "also Basic dXNlcjpwYXNz\n"
    )
    result = redact_preview(text)
    assert "secret_password" not in result, "DB password must be redacted"
    assert "eyJhbGciOi" not in result, "JWT must be redacted"
    assert "[REDACTED]" in result, "must use [REDACTED] marker"
    assert "postgresql://" in result, "non-secret portions must be preserved"


# ---------------------------------------------------------------------------
# T6: rotate_log_copytruncate preserves inode and bounds copies
# ---------------------------------------------------------------------------
def test_rotate_log_copytruncate_preserves_inode_and_bounds_copies(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "crawl.log"
    log_file.write_bytes(b"x" * 200)

    inode_before = os.stat(log_file).st_ino

    rotated = rotate_log_copytruncate(log_file, max_bytes=100, max_files=2)
    assert rotated is True, "must return True when rotation happened"

    assert log_file.exists(), "original file must still exist"
    assert log_file.stat().st_size == 0, "original must be truncated to 0"
    assert os.stat(log_file).st_ino == inode_before, "inode must be preserved"

    rotated_copy = tmp_path / "crawl.log.1"
    assert rotated_copy.exists(), ".1 copy must exist"
    assert rotated_copy.stat().st_size == 200, ".1 must have original content"


# ---------------------------------------------------------------------------
# T8: rotation never removes non-matching files
# ---------------------------------------------------------------------------
def test_rotation_never_removes_non_matching_files(tmp_path: Path) -> None:
    log_file = tmp_path / "crawl.log"
    profile_json = tmp_path / "profile-state.json"
    browser_dir = tmp_path / "browser-profile"

    profile_json.write_text('{"state": "warm"}')
    browser_dir.mkdir()
    (browser_dir / "cookies.db").write_bytes(b"data")

    # Round 1: log exceeds max_bytes, rotate
    log_file.write_bytes(b"a" * 200)
    rotate_log_copytruncate(log_file, max_bytes=100, max_files=1)

    # Round 2: write more, rotate again — .1 becomes .2, .2 exceeds max_files=1
    log_file.write_bytes(b"b" * 200)
    rotate_log_copytruncate(log_file, max_bytes=100, max_files=1)

    assert profile_json.exists(), "profile JSON must not be deleted"
    assert profile_json.read_text() == '{"state": "warm"}'
    assert browser_dir.exists(), "browser-profile directory must not be deleted"
    assert (browser_dir / "cookies.db").exists()

    # Only .1 should exist (max_files=1), .2 should have been removed
    assert (tmp_path / "crawl.log.1").exists(), ".1 must exist"
    assert not (tmp_path / "crawl.log.2").exists(), ".2 must be removed (max_files=1)"


# ---------------------------------------------------------------------------
# T9: dispatcher extracts framed result from fake worker (wiring verification)
# ---------------------------------------------------------------------------
def test_dispatcher_extracts_framed_result_from_fake_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from egp_api.main import _make_discover_spawner

    expected_result = {
        "command": "discover",
        "run_status": "succeeded",
        "project_count": 3,
        "project_ids": ["p1", "p2", "p3"],
    }

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.pid = 99999

        def communicate(
            self, *, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            payload = json.loads((input or b"{}").decode("utf-8"))
            result = {**expected_result, "run_id": payload.get("run_id")}
            framed_stdout = "\n".join(
                [
                    "some logging noise line 1",
                    "WARNING: irrelevant garbage",
                    RESULT_FRAME_BEGIN,
                    json.dumps(result, sort_keys=True),
                    RESULT_FRAME_END,
                    "more trailing noise",
                    json.dumps({"decoy": True}, sort_keys=True),
                ]
            )
            return (framed_stdout.encode("utf-8"), b"")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")
    spawner(
        tenant_id="t1",
        profile_id="profile-1",
        profile_type="custom",
        keyword="test-keyword",
    )


# ---------------------------------------------------------------------------
# T10: dispatch events written to log_handle on success path
# ---------------------------------------------------------------------------
def test_dispatch_events_written_to_log_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from egp_api.main import _make_discover_spawner

    expected_result = {
        "command": "discover",
        "run_status": "succeeded",
        "project_count": 1,
        "project_ids": ["p1"],
    }

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.pid = 88888

        def communicate(
            self, *, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            payload = json.loads((input or b"{}").decode("utf-8"))
            result = {**expected_result, "run_id": payload.get("run_id")}
            framed_stdout = "\n".join(
                [
                    RESULT_FRAME_BEGIN,
                    json.dumps(result, sort_keys=True),
                    RESULT_FRAME_END,
                ]
            )
            return (framed_stdout.encode("utf-8"), b"")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    spawner = _make_discover_spawner(
        "sqlite+pysqlite:///test.sqlite3",
        artifact_root=tmp_path,
    )
    spawner(
        tenant_id="t1",
        profile_id="profile-1",
        profile_type="custom",
        keyword="test-keyword",
    )

    log_files = list(tmp_path.rglob("worker.log"))
    assert log_files, "worker.log must be created under artifact_root"
    log_content = log_files[0].read_text(encoding="utf-8", errors="replace")
    log_lines = log_content.strip().splitlines()

    events = []
    for line in log_lines:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and "event" in parsed:
                events.append(parsed)
        except json.JSONDecodeError:
            continue

    event_names = [e["event"] for e in events]
    assert "dispatch_started" in event_names, (
        f"dispatch_started event must appear in log, got events: {event_names}"
    )
    assert "dispatch_finished" in event_names, (
        f"dispatch_finished event must appear in log, got events: {event_names}"
    )

    started = next(e for e in events if e["event"] == "dispatch_started")
    assert "run_id" in started, "dispatch_started must include run_id"
    assert "owner_pid" in started, "dispatch_started must include owner_pid"
    assert started.get("execution_backend") == "subprocess", (
        "dispatch_started must include execution_backend=subprocess"
    )


# ---------------------------------------------------------------------------
# T11: dispatch_failed event on nonzero exit
# ---------------------------------------------------------------------------
def test_dispatch_failed_event_on_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from egp_api.main import _make_discover_spawner
    from egp_api.services.discovery_worker_dispatcher import DiscoverySpawnError

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 1
            self.pid = 77777

        def communicate(
            self, *, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            return (b"not valid json output", b"some stderr output")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    spawner = _make_discover_spawner(
        "sqlite+pysqlite:///test.sqlite3",
        artifact_root=tmp_path,
    )

    with pytest.raises(DiscoverySpawnError):
        spawner(
            tenant_id="t1",
            profile_id="profile-1",
            profile_type="custom",
            keyword="test-keyword",
        )

    log_files = list(tmp_path.rglob("worker.log"))
    assert log_files, "worker.log must be created under artifact_root"
    log_content = log_files[0].read_text(encoding="utf-8", errors="replace")
    log_lines = log_content.strip().splitlines()

    events = []
    for line in log_lines:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and "event" in parsed:
                events.append(parsed)
        except json.JSONDecodeError:
            continue

    event_names = [e["event"] for e in events]
    assert "dispatch_failed" in event_names, (
        f"dispatch_failed event must appear in log on failure, got events: {event_names}"
    )
    failed = next(e for e in events if e["event"] == "dispatch_failed")
    assert "reason" in failed, "dispatch_failed must include reason"


# ---------------------------------------------------------------------------
# T12: framed result fails closed on malformed content between markers
# ---------------------------------------------------------------------------
def test_framed_result_fails_closed_on_malformed_content() -> None:
    from egp_api.services.discovery_worker_dispatcher import (
        _decode_framed_or_fallback_result,
    )

    lastline_dict = {"run_id": "should-not-get-this", "run_status": "succeeded"}
    stdout = "\n".join(
        [
            "some noise",
            RESULT_FRAME_BEGIN,
            "not valid json{{{",
            RESULT_FRAME_END,
            json.dumps(lastline_dict, sort_keys=True),
        ]
    )

    result = _decode_framed_or_fallback_result(stdout)
    assert result is None, (
        "must return None (fail-closed) when frame markers are present "
        f"but content is malformed, got {result!r}"
    )


# ---------------------------------------------------------------------------
# T13: NonRetriableDiscoveryDispatchError gets specific dispatch_failed reason
# ---------------------------------------------------------------------------
def test_non_retriable_error_gets_specific_dispatch_failed_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from egp_api.main import _make_discover_spawner
    from egp_api.services.discovery_dispatch import (
        NonRetriableDiscoveryDispatchError,
    )

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 1
            self.pid = 66666

        def communicate(
            self, *, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            stderr = b'{"error_type":"entitlement_denied","detail":"subscription required"}\n'
            return (b"", stderr)

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    spawner = _make_discover_spawner(
        "sqlite+pysqlite:///test.sqlite3",
        artifact_root=tmp_path,
    )

    with pytest.raises(NonRetriableDiscoveryDispatchError):
        spawner(
            tenant_id="t1",
            profile_id="profile-1",
            profile_type="custom",
            keyword="test-keyword",
        )

    log_files = list(tmp_path.rglob("worker.log"))
    assert log_files, "worker.log must be created"
    log_content = log_files[0].read_text(encoding="utf-8", errors="replace")

    events = []
    for line in log_content.strip().splitlines():
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict) and "event" in parsed:
                events.append(parsed)
        except json.JSONDecodeError:
            continue

    failed_events = [e for e in events if e.get("event") == "dispatch_failed"]
    assert failed_events, (
        f"dispatch_failed event must exist, got events: {[e['event'] for e in events]}"
    )
    failed = failed_events[0]
    assert failed["reason"] == "non_retriable_error", (
        f"reason must be 'non_retriable_error', got {failed['reason']!r}"
    )
    assert "child_pid" in failed, (
        "dispatch_failed for non-retriable must include child_pid"
    )


# ---------------------------------------------------------------------------
# T14: stdout_capture.close failure does not prevent log_handle.close
# ---------------------------------------------------------------------------
def test_stdout_capture_close_failure_does_not_prevent_log_handle_close(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import tempfile as _tempfile

    from egp_api.main import _make_discover_spawner

    expected_result = {
        "command": "discover",
        "run_status": "succeeded",
        "project_count": 1,
        "project_ids": ["p1"],
    }

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = 0
            self.pid = 55555

        def communicate(
            self, *, input: bytes | None = None, timeout: float | None = None
        ) -> tuple[bytes, bytes]:
            payload = json.loads((input or b"{}").decode("utf-8"))
            result = {**expected_result, "run_id": payload.get("run_id")}
            framed_stdout = "\n".join(
                [
                    RESULT_FRAME_BEGIN,
                    json.dumps(result, sort_keys=True),
                    RESULT_FRAME_END,
                ]
            )
            return (framed_stdout.encode("utf-8"), b"")

    close_calls = []

    def bomb_close(self: _tempfile.SpooledTemporaryFile) -> None:
        close_calls.append("spool_close_called")
        raise OSError("simulated SpooledTemporaryFile.close failure")

    log_handle_close_calls: list[str] = []
    original_path_open = Path.open

    def tracking_open(self: Path, *args: object, **kwargs: object):
        fh = original_path_open(self, *args, **kwargs)
        if self.name == "worker.log":
            original_close = fh.close

            def tracked_close() -> None:
                log_handle_close_calls.append("log_handle_closed")
                return original_close()

            fh.close = tracked_close
        return fh

    monkeypatch.setattr(Path, "open", tracking_open)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(_tempfile.SpooledTemporaryFile, "close", bomb_close)

    spawner = _make_discover_spawner(
        "sqlite+pysqlite:///test.sqlite3",
        artifact_root=tmp_path,
    )
    spawner(
        tenant_id="t1",
        profile_id="profile-1",
        profile_type="custom",
        keyword="test-keyword",
    )

    assert close_calls, "SpooledTemporaryFile.close must have been called"
    assert "log_handle_closed" in log_handle_close_calls, (
        "log_handle.close() must still run even when stdout_capture.close() fails"
    )


# ---------------------------------------------------------------------------
# T15: log_handle closed on payload serialization failure
# ---------------------------------------------------------------------------
def test_log_handle_closed_on_payload_serialization_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from egp_api.main import _make_discover_spawner

    original_json_dumps = json.dumps
    call_count = {"n": 0}
    close_tracker: list[str] = []

    original_path_open = Path.open

    def tracking_open(self: Path, *args: object, **kwargs: object):
        fh = original_path_open(self, *args, **kwargs)
        if self.name == "worker.log":
            original_close = fh.close

            def tracked_close() -> None:
                close_tracker.append("log_handle_closed")
                return original_close()

            fh.close = tracked_close
        return fh

    def failing_dumps(*args: object, **kwargs: object) -> str:
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise TypeError("simulated json.dumps failure")
        return original_json_dumps(*args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    monkeypatch.setattr(json, "dumps", failing_dumps)
    spawner = _make_discover_spawner(
        "sqlite+pysqlite:///test.sqlite3",
        artifact_root=tmp_path,
    )

    with pytest.raises(TypeError, match="simulated"):
        spawner(
            tenant_id="t1",
            profile_id="profile-1",
            profile_type="custom",
            keyword="test-keyword",
        )

    assert "log_handle_closed" in close_tracker, (
        "log_handle must be closed even when payload serialization fails"
    )
