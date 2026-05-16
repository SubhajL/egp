from __future__ import annotations

import json
import os
import signal
from pathlib import Path

import pytest

from egp_api.main import _make_discover_spawner
from egp_api.services.discovery_dispatch import NonRetriableDiscoveryDispatchError


class _FakeProcess:
    def __init__(self, *, returncode: int = 0, pid: int = 43210) -> None:
        self.returncode = returncode
        self.pid = pid
        self.payload: bytes | None = None

    def communicate(self, input=None, timeout=None):
        del timeout
        self.payload = input
        return (b"", b"")


def test_discover_spawner_reserves_run_and_forwards_artifact_root(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}
    process = _FakeProcess(returncode=0)
    popen_kwargs: dict[str, object] = {}

    class FakeRunRepository:
        def create_run(
            self,
            *,
            tenant_id: str,
            trigger_type: str,
            profile_id: str | None = None,
            summary_json: dict[str, object] | None = None,
            run_id: str | None = None,
        ):
            del summary_json
            captured["tenant_id"] = tenant_id
            captured["trigger_type"] = trigger_type
            captured["profile_id"] = profile_id
            captured["run_id"] = run_id
            return None

        def update_run_summary(
            self, run_id: str, *, summary_json: dict[str, object] | None
        ):
            captured["summary_run_id"] = run_id
            captured["summary_json"] = summary_json

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: popen_kwargs.update(kwargs) or process,
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "managed-artifacts",
        run_repository=FakeRunRepository(),
    )

    spawner(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id="22222222-2222-2222-2222-222222222222",
        profile_type="manual",
        keyword="แพลตฟอร์ม",
    )

    payload = json.loads((process.payload or b"{}").decode("utf-8"))

    assert captured["tenant_id"] == "11111111-1111-1111-1111-111111111111"
    assert captured["profile_id"] == "22222222-2222-2222-2222-222222222222"
    assert captured["trigger_type"] == "manual"
    assert isinstance(captured["run_id"], str)
    assert payload["run_id"] == captured["run_id"]
    assert payload["artifact_root"] == str(tmp_path / "managed-artifacts")
    assert payload["live_include_documents"] is True
    assert captured["summary_run_id"] == captured["run_id"]
    assert captured["summary_json"] == {
        "worker_log_path": str(
            tmp_path
            / "managed-artifacts"
            / "tenants"
            / "11111111-1111-1111-1111-111111111111"
            / "runs"
            / str(captured["run_id"])
            / "worker.log"
        ),
        "worker_owner_pid": os.getpid(),
        "worker_pid": process.pid,
    }
    assert popen_kwargs["stdout"] is popen_kwargs["stderr"]


def test_discover_spawner_treats_terminated_worker_as_non_retriable(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeRunRepository:
        def create_run(
            self,
            *,
            tenant_id: str,
            trigger_type: str,
            profile_id: str | None = None,
            summary_json: dict[str, object] | None = None,
            run_id: str | None = None,
        ):
            del tenant_id, trigger_type, profile_id, summary_json
            captured["created_run_id"] = run_id
            return None

        def update_run_summary(
            self, run_id: str, *, summary_json: dict[str, object] | None
        ):
            captured["summary_run_id"] = run_id
            captured["summary_json"] = summary_json

        def fail_run_if_active(
            self,
            run_id: str,
            *,
            error: str,
            failure_reason: str = "worker_timeout",
        ):
            captured["failed_run_id"] = run_id
            captured["error"] = error
            captured["failure_reason"] = failure_reason
            return None

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(returncode=-signal.SIGTERM),
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=Path("artifacts"),
        run_repository=FakeRunRepository(),
    )

    with pytest.raises(
        NonRetriableDiscoveryDispatchError,
        match="discover worker terminated by signal SIGTERM for keyword 'แพลตฟอร์ม'",
    ):
        spawner(
            tenant_id="11111111-1111-1111-1111-111111111111",
            profile_id="22222222-2222-2222-2222-222222222222",
            profile_type="manual",
            keyword="แพลตฟอร์ม",
        )

    assert captured["failed_run_id"] == captured["created_run_id"]
    assert captured["failure_reason"] == "worker_terminated"
    assert (
        captured["error"]
        == "discover worker terminated by signal SIGTERM for keyword 'แพลตฟอร์ม'"
    )
    assert captured["summary_run_id"] == captured["created_run_id"]
    assert captured["summary_json"] is not None
    assert "worker_log_path" in captured["summary_json"]


def test_discover_spawner_forwards_profile_max_pages_to_worker_payload(
    monkeypatch, tmp_path
) -> None:
    process = _FakeProcess(returncode=0)

    class FakeRunRepository:
        def create_run(
            self,
            *,
            tenant_id: str,
            trigger_type: str,
            profile_id: str | None = None,
            summary_json: dict[str, object] | None = None,
            run_id: str | None = None,
        ):
            del tenant_id, trigger_type, profile_id, summary_json, run_id
            return None

        def update_run_summary(
            self, run_id: str, *, summary_json: dict[str, object] | None
        ):
            del run_id, summary_json

    class FakeProfileRepository:
        def get_profile_detail(self, *, tenant_id: str, profile_id: str):
            del tenant_id, profile_id
            return type(
                "ProfileDetail",
                (),
                {"profile": type("ProfileRecord", (), {"max_pages_per_keyword": 37})()},
            )()

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "managed-artifacts",
        run_repository=FakeRunRepository(),
        profile_repository=FakeProfileRepository(),
    )

    spawner(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id="22222222-2222-2222-2222-222222222222",
        profile_type="manual",
        keyword="แพลตฟอร์ม",
    )

    payload = json.loads((process.payload or b"{}").decode("utf-8"))

    assert payload["browser_settings"] == {"max_pages_per_keyword": 37}


def test_discover_spawner_persists_absolute_worker_log_path_for_relative_artifact_root(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}
    process = _FakeProcess(returncode=0)
    relative_artifact_root = Path(".data") / "artifacts"
    launch_cwd = tmp_path / "launch-cwd"
    launch_cwd.mkdir()
    monkeypatch.chdir(launch_cwd)

    class FakeRunRepository:
        def create_run(
            self,
            *,
            tenant_id: str,
            trigger_type: str,
            profile_id: str | None = None,
            summary_json: dict[str, object] | None = None,
            run_id: str | None = None,
        ):
            del tenant_id, trigger_type, profile_id, summary_json
            captured["run_id"] = run_id
            return None

        def update_run_summary(
            self, run_id: str, *, summary_json: dict[str, object] | None
        ):
            captured["summary_run_id"] = run_id
            captured["summary_json"] = summary_json

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=relative_artifact_root,
        run_repository=FakeRunRepository(),
    )

    spawner(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id="22222222-2222-2222-2222-222222222222",
        profile_type="manual",
        keyword="แพลตฟอร์ม",
    )

    payload = json.loads((process.payload or b"{}").decode("utf-8"))
    expected_root = (launch_cwd / relative_artifact_root).resolve()
    expected_log_path = (
        expected_root
        / "tenants"
        / "11111111-1111-1111-1111-111111111111"
        / "runs"
        / str(captured["run_id"])
        / "worker.log"
    )

    assert payload["artifact_root"] == str(expected_root)
    assert captured["summary_run_id"] == captured["run_id"]
    assert captured["summary_json"] == {
        "worker_log_path": str(expected_log_path),
        "worker_owner_pid": os.getpid(),
        "worker_pid": process.pid,
    }
