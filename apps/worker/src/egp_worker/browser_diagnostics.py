"""Private, redacted, fail-open browser diagnostics (PR-CANARY-03 F3).

Captures at most one screenshot + a redacted metadata manifest per terminal
candidate/keyword anomaly. Everything here is **fail-open**: a capture failure
returns a bounded status and never raises, so a diagnostic can never change a
crawl outcome. The manifest is safe *by construction* — it carries only
structured e-GP fields (project number/name/status), never the page URL, HTML,
cookies, auth headers, proxy credentials, or full exception text — with the
shared ``egp_observability`` redactor as defense-in-depth.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from egp_observability import (
    tail_bounded_preview,
)  # tail_bounded_preview redacts secrets internally

_MANIFEST_SCHEMA = "egp.browser_diagnostic.v1"
_URL_RE = re.compile(r"https?://\S+")
# Bound the screenshot so a hung page cannot stall an (opt-in) diagnostic capture.
_SCREENSHOT_TIMEOUT_MS = 15_000

__all__ = ["capture_detail_diagnostic", "capture_keyword_diagnostic"]


def _strip_urls(text: str) -> str:
    return _URL_RE.sub("[url-removed]", text)


def _sanitize(text: object, *, limit: int) -> str:
    # Strip URLs first (redact_preview only removes userinfo, not whole URLs),
    # then redact credentials + tail-truncate via the shared helper.
    stripped = _strip_urls(str(text or ""))
    return tail_bounded_preview(stripped, limit=limit) or ""


def _marker_preview(marker: dict) -> str:
    parts = [
        str(marker.get("project_number") or ""),
        str(marker.get("project_name") or ""),
        str(marker.get("source_status_text") or ""),
    ]
    return " | ".join(part for part in parts if part)


def _opaque_stem(keyword: str, marker: dict, reason: str) -> str:
    """Opaque per-anomaly filename stem so distinct anomalies with byte-identical
    screenshots do not overwrite each other's metadata."""
    identity = "|".join(
        [
            str(keyword or ""),
            str(marker.get("project_number") or ""),
            str(marker.get("project_name") or ""),
            str(reason or ""),
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _build_manifest(reason: str, content_sha: str, size: int, keyword: str, marker: dict) -> dict:
    return {
        "schema": _MANIFEST_SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "reason": str(reason),
        "screenshot_sha256": content_sha,
        "screenshot_bytes": size,
        "keyword": _sanitize(keyword, limit=120),
        "marker": _sanitize(_marker_preview(marker), limit=240),
    }


def _write_private_contained(directory: Path, name: str, data: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / name
    if not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError("diagnostic path escapes the diagnostics directory")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, data)
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _capture(
    page,
    *,
    reason: str,
    marker: dict,
    keyword: str,
    diagnostics_dir: Path | None,
) -> dict:
    if diagnostics_dir is None:
        return {"status": "disabled"}
    try:
        png = page.screenshot(full_page=True, timeout=_SCREENSHOT_TIMEOUT_MS)
        content_sha = hashlib.sha256(png).hexdigest()
        stem = _opaque_stem(keyword, marker, reason)
        manifest = _build_manifest(reason, content_sha, len(png), keyword, marker)
        directory = Path(diagnostics_dir)
        _write_private_contained(directory, f"{stem}.png", png)
        _write_private_contained(
            directory,
            f"{stem}.json",
            json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        )
        return {"status": "captured", "artifact_stem": stem, "screenshot_sha256": content_sha}
    except Exception:  # noqa: BLE001 - fail-open: a diagnostic must never fail a crawl
        return {"status": "failed"}


def capture_detail_diagnostic(
    page,
    *,
    reason: str,
    marker: dict,
    keyword: str,
    diagnostics_dir: Path | None,
) -> dict:
    """Capture one private diagnostic for a terminal candidate anomaly. Fail-open;
    returns ``{"status": "captured"|"disabled"|"failed", ...}`` and never raises."""
    return _capture(
        page, reason=reason, marker=marker, keyword=keyword, diagnostics_dir=diagnostics_dir
    )


def capture_keyword_diagnostic(page, *, keyword: str, diagnostics_dir: Path | None) -> dict:
    """Capture one private diagnostic for a terminal ``keyword_no_results`` anomaly."""
    return _capture(
        page,
        reason="keyword_no_results",
        marker={"keyword": keyword},
        keyword=keyword,
        diagnostics_dir=diagnostics_dir,
    )
