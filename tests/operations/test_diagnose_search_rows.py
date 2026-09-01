from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from egp_shared_types.enums import DiscoveryPaginationOutcome
from egp_worker.browser_discovery import (
    PaginationAdvanceResult,
    ParsedResultsPage,
    ParsedResultsRow,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "diagnose_search_rows.py"


@pytest.fixture()
def diagnose_module():
    spec = importlib.util.spec_from_file_location("diagnose_search_rows", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parsed_page(page_num: int) -> ParsedResultsPage:
    invitation = page_num == 2
    row = ParsedResultsRow(
        row_ordinal=1,
        project_name=f"sanitized project page {page_num}",
        organization_name="sanitized organization",
        project_number=f"6900000000{page_num}",
        source_status_text=(
            "หนังสือเชิญชวน/ประกาศเชิญชวน" if invitation else "จัดทำสัญญา/บริหารสัญญา"
        ),
        row_marker={"project_name": f"sanitized project page {page_num}"},
        status_eligible=invitation,
        skip_keyword_hit=None,
        cell_texts=("sanitized",),
    )
    return ParsedResultsPage(
        headers=("หน่วยงาน", "ชื่อโครงการ", "สถานะโครงการ"),
        rows=(row,),
        header_signature="sanitized-signature",
        columns=(("organization", 0), ("project_name", 1), ("status", 2)),
    )


def _patch_observation_browser(monkeypatch, module, *, terminal) -> list[int]:
    page = SimpleNamespace(page_num=1)
    visited: list[int] = []
    browser = SimpleNamespace(close=lambda: None)
    playwright = SimpleNamespace(stop=lambda: None)
    chrome = SimpleNamespace()

    monkeypatch.setattr(module.bd, "launch_real_chrome", lambda settings, **kwargs: chrome)
    monkeypatch.setattr(
        module,
        "sync_playwright",
        lambda: SimpleNamespace(start=lambda: playwright),
    )
    monkeypatch.setattr(
        module.bd,
        "connect_playwright_to_chrome",
        lambda pw, settings: (browser, page),
    )
    monkeypatch.setattr(module.bd, "_goto_with_recovery", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.bd, "wait_for_cloudflare", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        module.bd, "wait_for_cloudflare_or_operator", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(module.bd, "search_keyword", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.bd, "is_no_results_page", lambda page: False)
    monkeypatch.setattr(module.bd, "safe_shutdown", lambda **kwargs: None)
    monkeypatch.setattr(module.time, "sleep", lambda *args, **kwargs: None)

    def parse_results_page(current_page):
        visited.append(current_page.page_num)
        return _parsed_page(current_page.page_num)

    def advance_results_page(current_page, settings, *, page_num):
        assert page_num == current_page.page_num
        if page_num == 5:
            return PaginationAdvanceResult(outcome=terminal, next_page_num=page_num)
        current_page.page_num += 1
        return PaginationAdvanceResult(
            outcome=DiscoveryPaginationOutcome.ADVANCED,
            next_page_num=current_page.page_num,
        )

    monkeypatch.setattr(module.bd, "parse_results_page", parse_results_page)
    monkeypatch.setattr(module.bd, "advance_results_page", advance_results_page)
    return visited


def test_observation_canary_accepts_pages_one_through_five_under_cap_fifteen(
    tmp_path: Path,
    monkeypatch,
    diagnose_module,
) -> None:
    release_sha = "a" * 40
    monkeypatch.setenv("EGP_RELEASE_SHA", release_sha)
    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path / "profile"))
    visited = _patch_observation_browser(
        monkeypatch,
        diagnose_module,
        terminal=DiscoveryPaginationOutcome.NEXT_CONTROL_ABSENT,
    )
    receipt_path = tmp_path / "observation-receipt.json"

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--keyword",
            "วิเคราะห์ข้อมูล",
            "--max-pages",
            "15",
            "--receipt",
            str(receipt_path),
            "--out-dir",
            str(tmp_path / "diagnostics"),
        ]
    )

    assert result == 0
    assert visited == [1, 2, 3, 4, 5]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert set(receipt) == {
        "schema_version",
        "stage",
        "status",
        "release_sha",
        "observed_at",
        "checks",
        "errors",
    }
    assert receipt["schema_version"] == 1
    assert receipt["stage"] == "observation"
    assert receipt["status"] == "accepted"
    assert receipt["release_sha"] == release_sha
    assert receipt["errors"] == []
    assert receipt["checks"] == {
        "browser_started": True,
        "eligible_invitation_page": 2,
        "keyword_exact": True,
        "max_pages_per_keyword": 15,
        "page_sequence": [1, 2, 3, 4, 5],
        "persistence_disabled": True,
        "shared_parser": True,
        "terminal_outcome": "next_control_absent",
    }
    serialized = json.dumps(receipt, ensure_ascii=False).casefold()
    for forbidden in (
        "tenant_id",
        "job_id",
        "profile_id",
        "project_number",
        "profile_dir",
        "database_url",
        "artifact_store",
        "supabase",
        "target_digest",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("terminal", "expected_error"),
    [
        (DiscoveryPaginationOutcome.NEXT_CONTROL_HIDDEN, "pagination_control_hidden"),
        (DiscoveryPaginationOutcome.PAGE_CHANGE_TIMEOUT, "pagination_page_change_timeout"),
        (DiscoveryPaginationOutcome.MAX_PAGES_REACHED, "max_pages_before_pinned_cap"),
    ],
)
def test_observation_canary_rejects_failure_or_premature_cap(
    tmp_path: Path,
    monkeypatch,
    diagnose_module,
    terminal: DiscoveryPaginationOutcome,
    expected_error: str,
) -> None:
    monkeypatch.setenv("EGP_RELEASE_SHA", "b" * 40)
    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path / "profile"))
    _patch_observation_browser(monkeypatch, diagnose_module, terminal=terminal)
    receipt_path = tmp_path / f"{terminal.value}.json"

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--keyword",
            "วิเคราะห์ข้อมูล",
            "--max-pages",
            "15",
            "--receipt",
            str(receipt_path),
            "--out-dir",
            str(tmp_path / "diagnostics"),
        ]
    )

    assert result == 1
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rejected"
    assert expected_error in receipt["errors"]


def test_observation_canary_rejects_attach_and_requires_pinned_cap_and_receipt(
    diagnose_module,
) -> None:
    with pytest.raises(SystemExit) as attach_error:
        diagnose_module.main(
            [
                "--observation-canary",
                "--attach",
                "--keyword",
                "วิเคราะห์ข้อมูล",
                "--max-pages",
                "15",
                "--receipt",
                "ignored.json",
            ]
        )
    assert attach_error.value.code == 2

    with pytest.raises(SystemExit) as cap_error:
        diagnose_module.main(
            [
                "--observation-canary",
                "--keyword",
                "วิเคราะห์ข้อมูล",
                "--max-pages",
                "5",
                "--receipt",
                "ignored.json",
            ]
        )
    assert cap_error.value.code == 2

    with pytest.raises(SystemExit) as receipt_error:
        diagnose_module.main(
            [
                "--observation-canary",
                "--keyword",
                "วิเคราะห์ข้อมูล",
                "--max-pages",
                "15",
            ]
        )
    assert receipt_error.value.code == 2


def test_observation_canary_shutdown_failure_cannot_return_success(
    tmp_path: Path,
    monkeypatch,
    diagnose_module,
) -> None:
    monkeypatch.setenv("EGP_RELEASE_SHA", "c" * 40)
    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path / "profile"))
    _patch_observation_browser(
        monkeypatch,
        diagnose_module,
        terminal=DiscoveryPaginationOutcome.NEXT_CONTROL_ABSENT,
    )
    monkeypatch.setattr(
        diagnose_module.bd,
        "safe_shutdown",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("shutdown failed")),
    )
    receipt_path = tmp_path / "shutdown-failure.json"

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--keyword",
            "วิเคราะห์ข้อมูล",
            "--max-pages",
            "15",
            "--receipt",
            str(receipt_path),
        ]
    )

    assert result == 1
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "rejected"
    assert receipt["errors"] == ["browser_shutdown_failed"]
