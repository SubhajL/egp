"""TDD: persistent warmed-profile mode + proxy/xvfb pass-through in the dispatcher.

Default (per_run) behaviour is covered by apps/api/tests/test_browser_isolation.py
and must remain unchanged; these tests cover the new persistent path.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable
from pathlib import Path

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
    ) -> None:
        self.returncode = returncode
        self.pid = 51515
        self.payload: bytes | None = None
        self._on_communicate = on_communicate

    def communicate(self, input=None, timeout=None):
        del timeout
        self.payload = input
        payload = json.loads((input or b"{}").decode("utf-8"))
        if self._on_communicate is not None:
            self._on_communicate(payload)
        return (b"", b"")


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
