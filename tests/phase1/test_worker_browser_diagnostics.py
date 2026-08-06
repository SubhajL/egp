from __future__ import annotations

import hashlib
import json

from egp_worker.browser_diagnostics import (
    capture_detail_diagnostic,
    capture_keyword_diagnostic,
)


class _ShotPage:
    """Minimal fake Playwright page: screenshot() returns bytes or raises."""

    def __init__(self, data: bytes = b"PNGDATA", raise_exc: Exception | None = None) -> None:
        self._data = data
        self._raise = raise_exc
        self.shots = 0

    def screenshot(self, full_page: bool = False, timeout: int | None = None) -> bytes:
        self.shots += 1
        if self._raise is not None:
            raise self._raise
        return self._data


def test_capture_detail_diagnostic_writes_stem_png_and_manifest(tmp_path) -> None:
    page = _ShotPage(b"PNGDATA")
    manifest = capture_detail_diagnostic(
        page,
        reason="rejection_page",
        marker={"project_name": "P", "project_number": "123", "source_status_text": "S"},
        keyword="k",
        diagnostics_dir=tmp_path,
    )
    assert manifest["status"] == "captured"
    pngs = list(tmp_path.glob("*.png"))
    jsons = list(tmp_path.glob("*.json"))
    assert len(pngs) == 1 and len(jsons) == 1
    assert pngs[0].read_bytes() == b"PNGDATA"
    on_disk = json.loads(jsons[0].read_text())
    assert on_disk["screenshot_sha256"] == hashlib.sha256(b"PNGDATA").hexdigest()
    assert on_disk["screenshot_bytes"] == 7
    assert on_disk["reason"] == "rejection_page"
    assert manifest["screenshot_sha256"] == on_disk["screenshot_sha256"]


def test_capture_manifest_has_no_url_or_redactable_secret(tmp_path) -> None:
    page = _ShotPage(b"X")
    capture_detail_diagnostic(
        page,
        reason="rejection_page",
        marker={
            "project_name": "proj http://user:pass@egp.go.th/x page",
            "project_number": "Bearer abcdefghij.klmnop.qrstuv",
            "source_status_text": "หนังสือเชิญชวน",
        },
        keyword="kw",
        diagnostics_dir=tmp_path,
    )
    blob = list(tmp_path.glob("*.json"))[0].read_text()
    assert "http" not in blob
    assert "://" not in blob
    assert "pass" not in blob
    assert "Bearer abc" not in blob
    # structured, non-secret content is still preserved after sanitising
    assert "proj" in blob


def test_capture_disabled_when_dir_none() -> None:
    page = _ShotPage()
    result = capture_detail_diagnostic(
        page, reason="rejection_page", marker={}, keyword="k", diagnostics_dir=None
    )
    assert result == {"status": "disabled"}
    assert page.shots == 0


def test_capture_fail_open_on_screenshot_error(tmp_path) -> None:
    page = _ShotPage(raise_exc=RuntimeError("boom"))
    result = capture_detail_diagnostic(
        page, reason="rejection_page", marker={}, keyword="k", diagnostics_dir=tmp_path
    )
    assert result == {"status": "failed"}
    assert list(tmp_path.iterdir()) == []


def test_capture_files_are_private_and_contained(tmp_path) -> None:
    page = _ShotPage(b"PNGDATA")
    capture_detail_diagnostic(
        page,
        reason="rejection_page",
        marker={"project_name": "P"},
        keyword="k",
        diagnostics_dir=tmp_path,
    )
    for written in tmp_path.iterdir():
        assert (written.stat().st_mode & 0o777) == 0o600
        assert written.resolve().is_relative_to(tmp_path.resolve())
    assert (tmp_path.stat().st_mode & 0o777) == 0o700


def test_capture_distinct_anomalies_do_not_overwrite(tmp_path) -> None:
    page = _ShotPage(b"SAME")
    capture_detail_diagnostic(
        page,
        reason="rejection_page",
        marker={"project_name": "A", "project_number": "1"},
        keyword="k",
        diagnostics_dir=tmp_path,
    )
    capture_detail_diagnostic(
        page,
        reason="rejection_page",
        marker={"project_name": "B", "project_number": "2"},
        keyword="k",
        diagnostics_dir=tmp_path,
    )
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_capture_keyword_diagnostic_writes_one(tmp_path) -> None:
    page = _ShotPage(b"KW")
    manifest = capture_keyword_diagnostic(page, keyword="kw", diagnostics_dir=tmp_path)
    assert manifest["status"] == "captured"
    assert len(list(tmp_path.glob("*.png"))) == 1
    assert (
        capture_keyword_diagnostic(page, keyword="kw", diagnostics_dir=None)
        == {"status": "disabled"}
    )
