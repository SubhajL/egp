from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import egp_worker.main as worker_main

from egp_shared_types.enums import CrawlRunStatus, DiscoveryFailureCode


def test_python_module_worker_entrypoint_executes_main_for_noop() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "egp_worker.main"],
        input='{"command":"noop"}',
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"service": "worker", "status": "idle"}


def test_worker_main_exits_nonzero_for_failed_discover_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = {
        "command": "discover",
        "run_id": "run-failed",
        "run_status": "failed",
        "project_count": 0,
        "project_ids": [],
        "error": "e-GP site error after search submit",
    }
    monkeypatch.setattr(worker_main, "run_worker_job", lambda payload: result)

    with pytest.raises(SystemExit) as exc_info:
        worker_main.main('{"command":"discover"}')

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == result


def test_discover_worker_result_includes_persisted_run_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_main,
        "run_discover_workflow",
        lambda **kwargs: SimpleNamespace(
            run=SimpleNamespace(
                run=SimpleNamespace(
                    id="run-failed",
                    status=CrawlRunStatus.FAILED,
                    summary_json={
                        "error": "e-GP site error after search submit",
                        "failure_code": DiscoveryFailureCode.SEARCH_PAGE_STATE_ERROR,
                    },
                )
            ),
            projects=[],
        ),
    )

    result = worker_main.run_worker_job(
        {
            "command": "discover",
            "database_url": "postgresql://example.test/egp",
            "tenant_id": "tenant-1",
            "keyword": "แพลตฟอร์ม",
        }
    )

    assert result["run_status"] == CrawlRunStatus.FAILED
    assert result["error"] == "e-GP site error after search submit"
    assert result["failure_code"] == DiscoveryFailureCode.SEARCH_PAGE_STATE_ERROR
