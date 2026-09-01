from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from egp_shared_types.enums import DiscoveryPaginationOutcome
from egp_shared_types.exact_canary import ExactIngestionCanaryTarget
from egp_worker.browser_discovery import (
    PaginationAdvanceResult,
    ParsedResultsPage,
    ParsedResultsRow,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "diagnose_search_rows.py"
TARGET_PAYLOAD = {
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


def _private_target(tmp_path: Path, payload: dict[str, object] | None = None) -> Path:
    path = tmp_path / "exact-target.json"
    path.write_text(json.dumps(payload or TARGET_PAYLOAD), encoding="utf-8")
    path.chmod(0o600)
    return path


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
    monkeypatch.setattr(module, "acquire_profile_lock", lambda path: object(), raising=False)
    monkeypatch.setattr(module, "release_profile_lock", lambda handle: None, raising=False)

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
    target_path = _private_target(tmp_path)

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--target-file",
            str(target_path),
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
        "target_fingerprint",
    }
    assert receipt["schema_version"] == 1
    assert receipt["stage"] == "observation"
    assert receipt["status"] == "accepted"
    assert receipt["release_sha"] == release_sha
    assert receipt["errors"] == []
    assert receipt["target_fingerprint"] == ExactIngestionCanaryTarget.from_mapping(
        TARGET_PAYLOAD
    ).canonical_digest()
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
        '"target_digest"',
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
    target_path = _private_target(tmp_path)

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--target-file",
            str(target_path),
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
                "--target-file",
                "target.json",
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
                "--target-file",
                "target.json",
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
                "--target-file",
                "target.json",
                "--max-pages",
                "15",
            ]
        )
    assert receipt_error.value.code == 2


def test_observation_canary_rejects_profile_dir_override_before_chrome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diagnose_module,
) -> None:
    monkeypatch.setenv("EGP_RELEASE_SHA", "1" * 40)
    monkeypatch.setenv(
        "EGP_BROWSER_PERSISTENT_PROFILE_DIR",
        str(tmp_path / "native-profile"),
    )
    monkeypatch.setattr(
        diagnose_module.bd,
        "launch_real_chrome",
        lambda *args, **kwargs: pytest.fail("Chrome launched with overridden profile"),
    )

    with pytest.raises(SystemExit) as error:
        diagnose_module.main(
            [
                "--observation-canary",
                "--target-file",
                str(_private_target(tmp_path)),
                "--profile-dir",
                str(tmp_path / "disposable-profile"),
                "--receipt",
                str(tmp_path / "rejected.json"),
            ]
        )

    assert error.value.code == 2


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
    target_path = _private_target(tmp_path)

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--target-file",
            str(target_path),
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


def test_observation_canary_closes_connected_browser_and_releases_profile_lock(
    tmp_path: Path,
    monkeypatch,
    diagnose_module,
) -> None:
    monkeypatch.setenv("EGP_RELEASE_SHA", "d" * 40)
    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path / "profile"))
    _patch_observation_browser(
        monkeypatch,
        diagnose_module,
        terminal=DiscoveryPaginationOutcome.NEXT_CONTROL_ABSENT,
    )
    shutdown: dict[str, object] = {}
    released: list[object] = []
    monkeypatch.setattr(
        diagnose_module.bd,
        "safe_shutdown",
        lambda **kwargs: shutdown.update(kwargs),
    )
    monkeypatch.setattr(
        diagnose_module,
        "release_profile_lock",
        released.append,
        raising=False,
    )

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--target-file",
            str(_private_target(tmp_path)),
            "--receipt",
            str(tmp_path / "cleanup.json"),
        ]
    )

    assert result == 0
    assert shutdown["browser"] is not None
    assert len(released) == 1


def test_observation_canary_rejects_invalid_private_target_before_chrome(
    tmp_path: Path,
    monkeypatch,
    diagnose_module,
) -> None:
    monkeypatch.setenv("EGP_RELEASE_SHA", "e" * 40)
    invalid = _private_target(
        tmp_path,
        {**TARGET_PAYLOAD, "keyword": " วิเคราะห์ข้อมูล "},
    )
    monkeypatch.setattr(
        diagnose_module.bd,
        "launch_real_chrome",
        lambda *args, **kwargs: pytest.fail("Chrome launched for invalid target"),
    )

    with pytest.raises(SystemExit) as error:
        diagnose_module.main(
            [
                "--observation-canary",
                "--target-file",
                str(invalid),
                "--receipt",
                str(tmp_path / "invalid.json"),
            ]
        )

    assert error.value.code == 2


def test_observation_canary_fails_closed_when_profile_lock_is_busy(
    tmp_path: Path,
    monkeypatch,
    diagnose_module,
) -> None:
    monkeypatch.setenv("EGP_RELEASE_SHA", "f" * 40)
    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(
        diagnose_module,
        "acquire_profile_lock",
        lambda path: (_ for _ in ()).throw(RuntimeError("busy")),
        raising=False,
    )
    monkeypatch.setattr(
        diagnose_module.bd,
        "launch_real_chrome",
        lambda *args, **kwargs: pytest.fail("Chrome launched without profile lock"),
    )
    receipt = tmp_path / "locked.json"

    result = diagnose_module.main(
        [
            "--observation-canary",
            "--target-file",
            str(_private_target(tmp_path)),
            "--receipt",
            str(receipt),
        ]
    )

    assert result == 1
    assert "profile_locked" in json.loads(receipt.read_text())["errors"]
