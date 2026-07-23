from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from egp_api.main import _make_discover_spawner
from egp_api.services.discovery_worker_dispatcher import (
    DiscoverySpawnError,
    _browser_cdp_port_for_run_id,
)


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        on_communicate: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self.returncode = returncode
        self.pid = 43210
        self.payload: bytes | None = None
        self._on_communicate = on_communicate

    def communicate(self, input=None, timeout=None):
        del timeout
        self.payload = input
        payload = json.loads((input or b"{}").decode("utf-8"))
        if self._on_communicate is not None:
            self._on_communicate(payload)
        result = {
            "command": "discover",
            "run_id": payload.get("run_id"),
            "run_status": "succeeded",
            "project_count": 0,
            "project_ids": [],
        }
        return (json.dumps(result).encode("utf-8"), b"")


class _FakeRunRepository:
    def create_run(
        self,
        *,
        tenant_id: str,
        trigger_type: str,
        profile_id: str | None = None,
        summary_json: dict[str, object] | None = None,
        run_id: str | None = None,
    ) -> None:
        del tenant_id, trigger_type, profile_id, summary_json, run_id

    def update_run_summary(
        self,
        run_id: str,
        *,
        summary_json: dict[str, object] | None,
    ) -> None:
        del run_id, summary_json


def _dispatch_once(spawner) -> None:
    spawner(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id="22222222-2222-2222-2222-222222222222",
        profile_type="manual",
        keyword="แพลตฟอร์ม",
    )


def test_discover_spawner_assigns_distinct_browser_isolation_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_ids = iter(
        [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ]
    )
    process_queue = [_FakeProcess(), _FakeProcess()]
    launched_processes: list[_FakeProcess] = []
    profile_root = tmp_path / "profiles"
    cdp_base = 12000
    cdp_range = 10000

    monkeypatch.setenv("EGP_BROWSER_CDP_PORT_BASE", str(cdp_base))
    monkeypatch.setenv("EGP_BROWSER_CDP_PORT_RANGE", str(cdp_range))
    monkeypatch.setenv("EGP_BROWSER_PROFILE_ROOT", str(profile_root))
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.uuid4",
        lambda: next(run_ids),
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: launched_processes.append(process_queue.pop(0))
        or launched_processes[-1],
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "managed-artifacts",
        run_repository=_FakeRunRepository(),
    )

    _dispatch_once(spawner)
    _dispatch_once(spawner)

    payloads = [
        json.loads((process.payload or b"{}").decode("utf-8"))
        for process in launched_processes
    ]
    browser_settings = [payload["browser_settings"] for payload in payloads]
    ports = [settings["browser_cdp_port"] for settings in browser_settings]
    profile_dirs = [settings["browser_profile_dir"] for settings in browser_settings]

    assert ports == [
        _browser_cdp_port_for_run_id(
            "00000000-0000-0000-0000-000000000001",
            base=cdp_base,
            port_range=cdp_range,
        ),
        _browser_cdp_port_for_run_id(
            "00000000-0000-0000-0000-000000000002",
            base=cdp_base,
            port_range=cdp_range,
        ),
    ]
    assert ports[0] != ports[1]
    assert profile_dirs == [
        str((profile_root / "00000000-0000-0000-0000-000000000001").resolve()),
        str((profile_root / "00000000-0000-0000-0000-000000000002").resolve()),
    ]


def test_discover_spawner_cleans_browser_profile_dir_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created_profile_dirs: list[Path] = []
    profile_root = tmp_path / "profiles"

    def create_profile_dir(payload: dict[str, object]) -> None:
        browser_settings = payload["browser_settings"]
        assert isinstance(browser_settings, dict)
        profile_dir = Path(str(browser_settings["browser_profile_dir"]))
        profile_dir.mkdir(parents=True)
        (profile_dir / "SingletonLock").write_text("locked", encoding="utf-8")
        created_profile_dirs.append(profile_dir)

    monkeypatch.setenv("EGP_BROWSER_PROFILE_ROOT", str(profile_root))
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.uuid4",
        lambda: "00000000-0000-0000-0000-000000000003",
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(on_communicate=create_profile_dir),
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "managed-artifacts",
        run_repository=_FakeRunRepository(),
    )

    _dispatch_once(spawner)

    assert created_profile_dirs
    assert not created_profile_dirs[0].exists()
    assert profile_root.exists()


def test_discover_spawner_cleans_browser_profile_dir_after_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created_profile_dirs: list[Path] = []
    profile_root = tmp_path / "profiles"

    def create_profile_dir(payload: dict[str, object]) -> None:
        browser_settings = payload["browser_settings"]
        assert isinstance(browser_settings, dict)
        profile_dir = Path(str(browser_settings["browser_profile_dir"]))
        profile_dir.mkdir(parents=True)
        (profile_dir / "SingletonLock").write_text("locked", encoding="utf-8")
        created_profile_dirs.append(profile_dir)

    monkeypatch.setenv("EGP_BROWSER_PROFILE_ROOT", str(profile_root))
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.uuid4",
        lambda: "00000000-0000-0000-0000-000000000004",
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(
            returncode=1,
            on_communicate=create_profile_dir,
        ),
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "managed-artifacts",
        run_repository=_FakeRunRepository(),
    )

    with pytest.raises(DiscoverySpawnError):
        _dispatch_once(spawner)

    assert created_profile_dirs
    assert not created_profile_dirs[0].exists()
    assert profile_root.exists()
