from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

import egp_worker.main as worker_main

from egp_shared_types.enums import CrawlRunStatus, DiscoveryFailureCode
from egp_shared_types.exact_canary import ExactIngestionCanaryTarget


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
    stdout_lines = capsys.readouterr().out.strip().splitlines()
    assert stdout_lines[0] == "---EGP_RESULT_BEGIN---"
    assert json.loads(stdout_lines[1]) == result
    assert stdout_lines[2] == "---EGP_RESULT_END---"


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


def test_exact_canary_worker_forwards_target_and_returns_bounded_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ExactIngestionCanaryTarget.from_mapping(
        {
            "contract_version": 1,
            "kind": "exact_ingestion_canary",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "job_id": "22222222-2222-2222-2222-222222222222",
            "profile_id": "33333333-3333-3333-3333-333333333333",
            "keyword": "วิเคราะห์ข้อมูล",
            "live": True,
            "execution_backend": "legacy",
            "browser_required": True,
            "max_pages_per_keyword": 15,
        }
    )
    proof = {
        "contract_version": 1,
        "target_digest": target.canonical_digest(),
        "browser_started": True,
        "page_sequence": [1, 2, 3, 4, 5],
        "max_pages_per_keyword": 15,
        "terminal_outcome": "next_control_absent",
        "later_page_persisted": True,
    }
    captured: dict[str, object] = {}

    def fake_run_discover_workflow(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            run=SimpleNamespace(
                run=SimpleNamespace(
                    id="44444444-4444-4444-4444-444444444444",
                    status=CrawlRunStatus.SUCCEEDED,
                    summary_json={"canary_proof": proof},
                )
            ),
            projects=[],
        )

    monkeypatch.setattr(
        worker_main, "run_discover_workflow", fake_run_discover_workflow
    )

    result = worker_main.run_worker_job(
        {
            "command": "discover",
            "database_url": "postgresql://example.test/egp",
            "tenant_id": target.tenant_id,
            "profile_id": target.profile_id,
            "agent_job_id": target.job_id,
            "keyword": target.keyword,
            "live": True,
            "execution_backend": "legacy",
            "browser_max_pages_per_keyword": 15,
            "exact_canary_target": target.to_mapping(),
        }
    )

    assert captured["exact_canary_target"] == target
    assert result["canary_proof"] == proof


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "99999999-9999-9999-9999-999999999999"),
        ("profile_id", "99999999-9999-9999-9999-999999999999"),
        ("agent_job_id", "99999999-9999-9999-9999-999999999999"),
        ("keyword", "wrong keyword"),
        ("live", False),
        ("execution_backend", "agent"),
        ("browser_max_pages_per_keyword", 5),
    ],
)
def test_exact_canary_worker_rejects_effective_input_mismatch_before_workflow(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    target = ExactIngestionCanaryTarget.from_mapping(
        {
            "contract_version": 1,
            "kind": "exact_ingestion_canary",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "job_id": "22222222-2222-2222-2222-222222222222",
            "profile_id": "33333333-3333-3333-3333-333333333333",
            "keyword": "วิเคราะห์ข้อมูล",
            "live": True,
            "execution_backend": "legacy",
            "browser_required": True,
            "max_pages_per_keyword": 15,
        }
    )
    payload: dict[str, object] = {
        "command": "discover",
        "database_url": "postgresql://example.test/egp",
        "tenant_id": target.tenant_id,
        "profile_id": target.profile_id,
        "agent_job_id": target.job_id,
        "keyword": target.keyword,
        "live": True,
        "execution_backend": "legacy",
        "browser_max_pages_per_keyword": 15,
        "exact_canary_target": target.to_mapping(),
    }
    payload[field] = value
    monkeypatch.setattr(
        worker_main,
        "run_discover_workflow",
        lambda **kwargs: pytest.fail(
            f"workflow started with mismatched target: {kwargs}"
        ),
    )

    with pytest.raises(ValueError, match="exact canary target mismatch"):
        worker_main.run_worker_job(payload)
