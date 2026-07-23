from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from egp_api.main import _make_discover_spawner
from egp_api.services.discovery_dispatch import NonRetriableDiscoveryDispatchError
from egp_api.services.discovery_worker_dispatcher import DiscoverySpawnError


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        pid: int = 43210,
        run_status: str = "succeeded",
        error: str | None = None,
        emit_result: bool = True,
        raw_stdout: bytes = b"",
        run_id_override: str | None = None,
    ) -> None:
        self.returncode = returncode
        self.pid = pid
        self.payload: bytes | None = None
        self.run_status = run_status
        self.error = error
        self.emit_result = emit_result
        self.raw_stdout = raw_stdout
        self.run_id_override = run_id_override

    def communicate(self, input=None, timeout=None):
        del timeout
        self.payload = input
        payload = json.loads((input or b"{}").decode("utf-8"))
        if not self.emit_result:
            return (self.raw_stdout, b"")
        result = {
            "command": "discover",
            "run_id": self.run_id_override or payload.get("run_id"),
            "run_status": self.run_status,
            "project_count": 0,
            "project_ids": [],
        }
        if self.error is not None:
            result["error"] = self.error
        return (json.dumps(result).encode("utf-8"), b"")


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
    assert popen_kwargs["stdout"] is not subprocess.PIPE
    assert hasattr(popen_kwargs["stdout"], "write")
    assert popen_kwargs["stderr"] is not subprocess.PIPE


def test_discover_spawner_retries_semantic_failed_worker_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = _FakeProcess(
        returncode=0,
        run_status="failed",
        error="e-GP site error after search results load",
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
    )

    with pytest.raises(
        DiscoverySpawnError,
        match="e-GP site error after search results load",
    ):
        spawner(
            tenant_id="11111111-1111-1111-1111-111111111111",
            profile_id="22222222-2222-2222-2222-222222222222",
            profile_type="manual",
            keyword="แพลตฟอร์ม",
        )


def test_discover_spawner_accepts_partial_worker_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(run_status="partial"),
    )
    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
    )

    spawner(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id="22222222-2222-2222-2222-222222222222",
        profile_type="manual",
        keyword="แพลตฟอร์ม",
    )


@pytest.mark.parametrize("raw_stdout", [b"", b"LIVE_PROGRESS page=1\nnot-json\n"])
def test_discover_spawner_retries_missing_or_malformed_worker_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_stdout: bytes,
) -> None:
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(
            emit_result=False,
            raw_stdout=raw_stdout,
        ),
    )
    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
    )

    with pytest.raises(DiscoverySpawnError, match="returned no result"):
        spawner(
            tenant_id="11111111-1111-1111-1111-111111111111",
            profile_id="22222222-2222-2222-2222-222222222222",
            profile_type="manual",
            keyword="แพลตฟอร์ม",
        )


def test_discover_spawner_retries_mismatched_worker_run_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(run_id_override="wrong-run"),
    )
    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "artifacts",
    )

    with pytest.raises(DiscoverySpawnError, match="invalid run_id"):
        spawner(
            tenant_id="11111111-1111-1111-1111-111111111111",
            profile_id="22222222-2222-2222-2222-222222222222",
            profile_type="manual",
            keyword="แพลตฟอร์ม",
        )


def test_discover_spawner_forwards_artifact_storage_config(
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

    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: process,
    )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "managed-artifacts",
        run_repository=FakeRunRepository(),
        artifact_storage_backend="s3",
        artifact_bucket="egp-documents",
        artifact_prefix="prod",
    )

    spawner(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id="22222222-2222-2222-2222-222222222222",
        profile_type="manual",
        keyword="แพลตฟอร์ม",
    )

    payload = json.loads((process.payload or b"{}").decode("utf-8"))

    assert payload["artifact_storage_backend"] == "s3"
    assert payload["artifact_bucket"] == "egp-documents"
    assert payload["artifact_prefix"] == "prod"


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

    assert payload["browser_settings"]["max_pages_per_keyword"] == 37
    assert isinstance(payload["browser_settings"]["browser_cdp_port"], int)
    assert payload["browser_settings"]["browser_profile_dir"]


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


def test_discover_spawner_emits_scan_metrics_from_finished_run(tmp_path) -> None:
    from egp_observability.metrics import render_prometheus_metrics, reset_metrics_for_tests

    reset_metrics_for_tests()

    class FakeRunRepository:
        def get_run_detail(self, *, tenant_id: str, run_id: str):
            return SimpleNamespace(
                run=SimpleNamespace(
                    summary_json={
                        "keyword_scans": {
                            "แพลตฟอร์ม": {
                                "outcome": "anomaly",
                                "reason_code": "no_eligible_rows",
                                "rows_scanned": 5,
                                "eligible": 0,
                                "header_signature_drift": False,
                            }
                        }
                    }
                ),
                tasks=[],
            )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path,
        run_repository=FakeRunRepository(),
    )

    spawner._emit_discovery_run_metrics(tenant_id="tenant-1", run_id="run-1")

    text = render_prometheus_metrics()[0].decode("utf-8")
    assert (
        'egp_discovery_keyword_scans_total{outcome="anomaly",reason="no_eligible_rows"} 1.0'
        in text
    )
    assert 'egp_discovery_rows_scanned_total{outcome="anomaly"} 5.0' in text
    assert 'egp_discovery_anomalies_total{reason="no_eligible_rows"} 1.0' in text


def test_discover_spawner_metric_emit_is_nonblocking(tmp_path) -> None:
    from egp_observability.metrics import reset_metrics_for_tests

    reset_metrics_for_tests()

    class BrokenRunRepository:
        def get_run_detail(self, *, tenant_id: str, run_id: str):
            raise RuntimeError("database unavailable")

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path,
        run_repository=BrokenRunRepository(),
    )

    # Metric emission must never fail dispatch — a broken read is swallowed.
    spawner._emit_discovery_run_metrics(tenant_id="tenant-1", run_id="run-1")


@pytest.mark.parametrize("bad_summary", ["not-a-dict", [1, 2, 3], None])
def test_discover_spawner_metric_emit_tolerates_non_dict_summary(
    tmp_path, bad_summary
) -> None:
    from egp_observability.metrics import reset_metrics_for_tests

    reset_metrics_for_tests()

    class WeirdRunRepository:
        def get_run_detail(self, *, tenant_id: str, run_id: str):
            return SimpleNamespace(
                run=SimpleNamespace(summary_json=bad_summary), tasks=[]
            )

    spawner = _make_discover_spawner(
        "postgresql://example.test/egp",
        artifact_root=tmp_path,
        run_repository=WeirdRunRepository(),
    )

    # A malformed/missing summary_json must not raise out of dispatch.
    spawner._emit_discovery_run_metrics(tenant_id="tenant-1", run_id="run-1")
