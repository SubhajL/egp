from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from egp_api.main import _make_discover_spawner
from egp_api.services.discovery_dispatch import NonRetriableDiscoveryDispatchError


class _FakeProcess:
    def __init__(self, *, returncode: int = 0) -> None:
        self.returncode = returncode
        self.payload: bytes | None = None

    def communicate(self, input=None, timeout=None):
        del timeout
        self.payload = input
        return (b"", b"")


def test_discover_spawner_reserves_run_and_forwards_artifact_root(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
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
            del summary_json
            captured["tenant_id"] = tenant_id
            captured["trigger_type"] = trigger_type
            captured["profile_id"] = profile_id
            captured["run_id"] = run_id
            return None

    monkeypatch.setattr(
        "egp_api.main.subprocess.Popen",
        lambda *args, **kwargs: process,
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


def test_discover_spawner_treats_terminated_worker_as_non_retriable(monkeypatch) -> None:
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
        "egp_api.main.subprocess.Popen",
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
    assert captured["error"] == "discover worker terminated by signal SIGTERM for keyword 'แพลตฟอร์ม'"
