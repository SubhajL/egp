"""TDD: persistent warmed-profile mode + proxy/xvfb pass-through in the dispatcher.

Default (per_run) behaviour is covered by apps/api/tests/test_browser_isolation.py
and must remain unchanged; these tests cover the new persistent path.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from egp_api.services.discovery_dispatch import DiscoveryDispatchRequest
from egp_api.services.discovery_worker_dispatcher import (
    DiscoverySpawnError,
    SubprocessDiscoveryDispatcher,
)


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        on_communicate: Callable[[dict[str, object]], None] | None = None,
        run_status: str = "succeeded",
        error: str | None = None,
    ) -> None:
        self.returncode = returncode
        self.pid = 51515
        self.payload: bytes | None = None
        self._on_communicate = on_communicate
        self._run_status = run_status
        self._error = error

    def communicate(self, input=None, timeout=None):
        del timeout
        self.payload = input
        payload = json.loads((input or b"{}").decode("utf-8"))
        if self._on_communicate is not None:
            self._on_communicate(payload)
        result = {
            "command": "discover",
            "run_id": payload.get("run_id"),
            "run_status": self._run_status,
            "project_count": 0,
            "project_ids": [],
        }
        if self._error is not None:
            result["error"] = self._error
        return (json.dumps(result).encode("utf-8"), b"")


class _FakeRunRepository:
    def create_run(self, **kwargs) -> None:
        del kwargs

    def update_run_summary(self, run_id: str, *, summary_json) -> None:
        del run_id, summary_json

    def fail_run_if_active(self, *args, **kwargs):
        del args, kwargs
        return None


def _request() -> DiscoveryDispatchRequest:
    return DiscoveryDispatchRequest(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id="22222222-2222-2222-2222-222222222222",
        profile_type="manual",
        keyword="แพลตฟอร์ม",
    )


def _make_dispatcher(tmp_path: Path, warm_dir: Path) -> SubprocessDiscoveryDispatcher:
    warm_dir.mkdir(parents=True, exist_ok=True)
    (warm_dir / ".egp-profile-state.json").write_text(
        json.dumps(
            {"last_success_at": datetime.now(UTC).isoformat(), "source": "warm"}
        ),
        encoding="utf-8",
    )
    return SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
        browser_profile_mode="persistent",
        browser_persistent_profile_dir=warm_dir,
        browser_proxy_server="http://1.2.3.4:8000",
        browser_use_xvfb=True,
        browser_chrome_path="/opt/chrome/chrome",
    )


def test_persistent_mode_warms_stale_profile_before_worker_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    events: list[str] = []

    def fake_warm(settings, **kwargs) -> bool:
        events.append(f"warm:{settings.browser_profile_dir}")
        assert kwargs["acquire_lock"] is False
        return True

    def fake_popen(*args, **kwargs):
        events.append("spawn")
        return _FakeProcess()

    monkeypatch.setattr("egp_worker.warmup.run_profile_warmup", fake_warm)
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        fake_popen,
    )

    dispatcher = SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
        browser_profile_mode="persistent",
        browser_persistent_profile_dir=warm_dir,
        browser_warmup_stale_after_seconds=1_800,
        browser_predispatch_warm_seconds=0,
    )

    dispatcher.dispatch(_request())

    assert events == [f"warm:{warm_dir.resolve()}", "spawn"]


def test_persistent_mode_skips_warm_when_profile_recently_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    warm_dir.mkdir(parents=True)
    (warm_dir / ".egp-profile-state.json").write_text(
        json.dumps(
            {
                "last_success_at": datetime.now(UTC).isoformat(),
                "source": "crawl",
            }
        ),
        encoding="utf-8",
    )

    def fail_warm(*args, **kwargs) -> bool:
        del args, kwargs
        raise AssertionError("recent profile should not be warmed")

    monkeypatch.setattr("egp_worker.warmup.run_profile_warmup", fail_warm)
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *a, **k: _FakeProcess(),
    )

    SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
        browser_profile_mode="persistent",
        browser_persistent_profile_dir=warm_dir,
        browser_warmup_stale_after_seconds=1_800,
    ).dispatch(_request())


def test_persistent_mode_records_successful_crawl_as_recent_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    warm_dir.mkdir(parents=True)
    stale_time = datetime.now(UTC) - timedelta(hours=2)
    (warm_dir / ".egp-profile-state.json").write_text(
        json.dumps({"last_success_at": stale_time.isoformat(), "source": "warm"}),
        encoding="utf-8",
    )
    warm_calls = {"count": 0}

    def fake_warm(*args, **kwargs) -> bool:
        del args, kwargs
        warm_calls["count"] += 1
        return True

    monkeypatch.setattr("egp_worker.warmup.run_profile_warmup", fake_warm)
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *a, **k: _FakeProcess(),
    )
    dispatcher = SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
        browser_profile_mode="persistent",
        browser_persistent_profile_dir=warm_dir,
        browser_warmup_stale_after_seconds=1_800,
    )

    dispatcher.dispatch(_request())
    dispatcher.dispatch(_request())

    state = json.loads(
        (warm_dir / ".egp-profile-state.json").read_text(encoding="utf-8")
    )
    assert warm_calls["count"] == 1
    assert state["source"] == "crawl"


def test_persistent_mode_does_not_record_failed_crawl_as_recent_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    warm_dir.mkdir(parents=True)
    state_path = warm_dir / ".egp-profile-state.json"
    state_path.write_text(
        json.dumps({"last_success_at": datetime.now(UTC).isoformat(), "source": "warm"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *a, **k: _FakeProcess(
            returncode=0,
            run_status="failed",
            error="e-GP site error after search submit",
        ),
    )

    dispatcher = _make_dispatcher(tmp_path, warm_dir)
    previous_state = json.loads(state_path.read_text(encoding="utf-8"))

    with pytest.raises(DiscoverySpawnError, match="e-GP site error"):
        dispatcher.dispatch(_request())

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "last_success_at" not in state
    assert state["source"] == "crawl_failure"
    assert state["last_crawl_failure_at"]
    assert "e-GP site error" in state["last_crawl_failure_error"]
    assert previous_state["last_success_at"]


def test_persistent_mode_reuses_dir_and_passes_proxy_xvfb_chrome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    captured = _FakeProcess()
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *a, **k: captured,
    )

    _make_dispatcher(tmp_path, warm_dir).dispatch(_request())

    payload = json.loads((captured.payload or b"{}").decode("utf-8"))
    bs = payload["browser_settings"]
    assert bs["browser_profile_dir"] == str(warm_dir.resolve())
    assert bs["browser_proxy_server"] == "http://1.2.3.4:8000"
    assert bs["browser_use_xvfb"] is True
    assert bs["browser_chrome_path"] == "/opt/chrome/chrome"


def test_persistent_mode_does_not_delete_profile_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"

    def write_cookie(payload: dict[str, object]) -> None:
        profile_dir = Path(str(payload["browser_settings"]["browser_profile_dir"]))
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "Cookies").write_text("warm", encoding="utf-8")

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *a, **k: _FakeProcess(on_communicate=write_cookie),
    )

    _make_dispatcher(tmp_path, warm_dir).dispatch(_request())

    assert warm_dir.exists()
    assert (warm_dir / "Cookies").exists()


def test_persistent_mode_blocks_when_profile_already_locked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    warm_dir.mkdir(parents=True)
    # Hold the lock the dispatcher will try to acquire.
    lock_handle = open(warm_dir / ".egp-crawl.lock", "w")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        monkeypatch.setattr(
            "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
            lambda *a, **k: _FakeProcess(),
        )
        with pytest.raises(DiscoverySpawnError):
            _make_dispatcher(tmp_path, warm_dir).dispatch(_request())
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def test_prepare_for_dispatch_defers_when_profile_already_locked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    warm_dir.mkdir(parents=True)
    lock_handle = open(warm_dir / ".egp-crawl.lock", "w")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def must_not_warm(*args, **kwargs) -> bool:
        del args, kwargs
        raise AssertionError("locked profile should defer before warm")

    monkeypatch.setattr("egp_worker.warmup.run_profile_warmup", must_not_warm)
    try:
        assert _make_dispatcher(tmp_path, warm_dir).prepare_for_dispatch() is False
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def test_prepare_for_dispatch_defers_when_shared_egp_circuit_is_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.get_default_rate_limiter",
        lambda: SimpleNamespace(is_circuit_open=lambda: True),
    )
    dispatcher = SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
    )

    assert dispatcher.prepare_for_dispatch() is False


def test_prepare_for_dispatch_pauses_after_repeated_warm_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    warm_calls = {"count": 0}

    def fail_warm(*args, **kwargs) -> bool:
        del args, kwargs
        warm_calls["count"] += 1
        raise RuntimeError("warm-up failed: Cloudflare not cleared on announcement")

    monkeypatch.setattr("egp_worker.warmup.run_profile_warmup", fail_warm)
    dispatcher = SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
        browser_profile_mode="persistent",
        browser_persistent_profile_dir=warm_dir,
        browser_warmup_stale_after_seconds=1_800,
        browser_warmup_failure_pause_threshold=2,
    )

    assert dispatcher.prepare_for_dispatch() is False
    assert dispatcher.prepare_for_dispatch() is False
    assert dispatcher.prepare_for_dispatch() is False

    state = json.loads(
        (warm_dir / ".egp-profile-state.json").read_text(encoding="utf-8")
    )
    assert warm_calls["count"] == 2
    assert state["consecutive_warm_failures"] == 2
    assert state["operator_action_required"] is True
    assert "Cloudflare not cleared" in state["last_failure_error"]


def test_dispatch_fails_fast_when_cloudflare_operator_action_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    warm_dir = tmp_path / "warm-profile"
    warm_dir.mkdir(parents=True)
    (warm_dir / ".egp-profile-state.json").write_text(
        json.dumps(
            {
                "consecutive_warm_failures": 2,
                "last_failure_at": datetime.now(UTC).isoformat(),
                "last_failure_error": "warm-up failed: Cloudflare not cleared",
                "operator_action_required": True,
            }
        ),
        encoding="utf-8",
    )

    def must_not_warm(*args, **kwargs) -> bool:
        del args, kwargs
        raise AssertionError("paused profile should not launch Chrome")

    monkeypatch.setattr("egp_worker.warmup.run_profile_warmup", must_not_warm)
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("worker should not spawn")
        ),
    )

    dispatcher = SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
        browser_profile_mode="persistent",
        browser_persistent_profile_dir=warm_dir,
        browser_warmup_stale_after_seconds=1_800,
        browser_warmup_failure_pause_threshold=2,
    )

    with pytest.raises(DiscoverySpawnError, match="operator action required"):
        dispatcher.dispatch(_request())


def test_persistent_mode_rejects_synced_folder(tmp_path: Path) -> None:
    bad = tmp_path / "OneDrive" / "egp-profile"
    with pytest.raises(RuntimeError):
        SubprocessDiscoveryDispatcher(
            "postgresql://example.test/egp",
            artifact_root=tmp_path / "artifacts",
            run_repository=_FakeRunRepository(),
            browser_profile_mode="persistent",
            browser_persistent_profile_dir=bad,
        )


def test_persistent_mode_requires_profile_dir(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        SubprocessDiscoveryDispatcher(
            "postgresql://example.test/egp",
            artifact_root=tmp_path / "artifacts",
            run_repository=_FakeRunRepository(),
            browser_profile_mode="persistent",
            browser_persistent_profile_dir=None,
        )


def test_timeout_kills_process_group_and_uses_new_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import subprocess as _sp

    captured: dict[str, object] = {"popen_kwargs": None, "killpg": []}

    class _TimeoutProc:
        pid = 90909
        returncode = None

        def __init__(self) -> None:
            self._first = True

        def communicate(self, input=None, timeout=None):
            if self._first:
                self._first = False
                raise _sp.TimeoutExpired(cmd="egp_worker", timeout=timeout)
            return (b"", b"")

        def kill(self) -> None:
            pass

    def fake_popen(*args, **kwargs):
        captured["popen_kwargs"] = kwargs
        return _TimeoutProc()

    monkeypatch.setenv("EGP_BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen", fake_popen
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.os.getpgid", lambda pid: pid
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.os.killpg",
        lambda pgid, sig: captured["killpg"].append((pgid, sig)),
    )

    dispatcher = SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
    )  # per_run default
    with pytest.raises(DiscoverySpawnError):
        dispatcher.dispatch(_request())

    assert captured["popen_kwargs"].get("start_new_session") is True
    assert captured["killpg"] and captured["killpg"][0][0] == 90909


def test_dispatch_payload_includes_timeout_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured = _FakeProcess()
    monkeypatch.setenv("EGP_BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *a, **k: captured,
    )
    SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
        run_repository=_FakeRunRepository(),
    ).dispatch(_request())  # per_run default
    bs = json.loads((captured.payload or b"{}").decode("utf-8"))["browser_settings"]
    assert bs["browser_nav_timeout_ms"] == 60000
    assert bs["browser_cloudflare_timeout_ms"] == 120000
    assert bs["browser_cloudflare_reload_retries"] == 1
    assert bs["browser_cloudflare_operator_wait_timeout_ms"] == 600000
    assert bs["browser_project_detail_timeout_s"] == 240.0
