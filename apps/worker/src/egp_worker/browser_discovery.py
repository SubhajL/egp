"""Focused browser-driven e-GP discovery extracted from the legacy crawler."""

from __future__ import annotations

import re
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from egp_document_classifier import derive_artifact_bucket

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised in CI import environments without Playwright

    class PlaywrightTimeout(Exception):
        pass

    def sync_playwright():
        raise ModuleNotFoundError("playwright is required for live browser discovery")


from egp_shared_types.enums import ArtifactBucket, ProcurementType, ProjectState

from .browser_downloads import collect_downloaded_documents
from .browser_site_state import clear_site_error_toast, has_site_error_toast
from .profiles import resolve_profile_keywords

MAIN_PAGE_URL = "https://www.gprocurement.go.th/new_index.html"
SEARCH_URL = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement"
TARGET_STATUS = "หนังสือเชิญชวน/ประกาศเชิญชวน"
SKIP_KEYWORDS_IN_PROJECT = ["ทางหลวง", "วิธีคัดเลือก", "บำรุงรักษา"]
NEXT_PAGE_SELECTOR = (
    "a:has-text('ถัดไป'), "
    "button:has-text('ถัดไป'), "
    "button[aria-label='next'], "
    "a:has-text('»'), "
    "li.next:not(.disabled) a"
)
RESULTS_TABLE_REQUIRED_HEADERS = [
    "ลำดับ",
    "หน่วยจัดซื้อ",
    "ชื่อโครงการ",
    "วงเงินงบประมาณ",
    "สถานะโครงการ",
    "ดูข้อมูล",
]
SEARCH_CONTROLS_STABLE_SECONDS = 2.0
SEARCH_CONTROLS_SETTLE_TIMEOUT_S = 10.0
NO_RESULTS_MARKERS = ("ไม่พบข้อมูล", "จำนวนโครงการที่พบ : 0")


@dataclass(frozen=True, slots=True)
class BrowserDiscoverySettings:
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    cdp_port: int = 9222
    nav_timeout_ms: int = 60_000
    cloudflare_timeout_ms: int = 120_000
    cloudflare_reload_retries: int = 1
    search_page_recovery_retries: int = 1
    max_pages_per_keyword: int = 15
    project_detail_timeout_s: float = 240.0
    browser_profile_dir: Path = Path.home() / "download" / "TOR" / ".browser_profile"


@dataclass(frozen=True, slots=True)
class DiscoveryResumeState:
    keyword_index: int
    keyword: str
    page_num: int = 1


class BrowserClosedDuringKeyword(RuntimeError):
    def __init__(self, *, page_num: int, message: str = "browser has been closed") -> None:
        super().__init__(message)
        self.page_num = page_num


class ResultsPageRecoveryError(RuntimeError):
    def __init__(
        self,
        *,
        keyword: str,
        target_page_num: int,
        row_marker: dict[str, object] | None = None,
        reason: str,
    ) -> None:
        marker_name = str((row_marker or {}).get("project_name") or "unknown-row")
        super().__init__(
            f"failed to restore results for keyword '{keyword}' page {target_page_num}: "
            f"{reason} ({marker_name})"
        )
        self.keyword = keyword
        self.target_page_num = target_page_num
        self.row_marker = row_marker
        self.reason = reason


class SearchPageStateError(RuntimeError):
    """Raised when e-GP search/pagination leaves the page in an unsafe state."""


class ProjectExtractionTimeout(TimeoutError):
    """Raised when a project detail/documents phase exceeds the per-project budget."""


class LiveDiscoveryPartialError(RuntimeError):
    """Raised when a live crawl must stop but already-streamed projects are valid."""


DOCUMENT_COLLECTION_SUCCEEDED = "succeeded"
DOCUMENT_COLLECTION_TIMEOUT = "timeout"

RECOVERY_BROWSER_ERROR_MARKERS = (
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_DNS_NO_MATCHING_SUPPORTED_ALPN",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_NETWORK_CHANGED",
    "ERR_NETWORK_ACCESS_DENIED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_TIMED_OUT",
    "Target page, context or browser has been closed",
    "has been closed",
)
DOCUMENT_COLLECTION_FAILED = "failed"
DOCUMENT_COLLECTION_TIMEOUT_REASON = "document_collection_timeout"
DOCUMENT_COLLECTION_FAILED_REASON = "document_collection_failed"
DOCUMENT_COLLECTION_TIMEOUT_CAP_S = 45.0


def crawl_live_discovery(
    *,
    keyword: str | None = None,
    profile: str | None = None,
    settings: BrowserDiscoverySettings | None = None,
    include_documents: bool = False,
    project_callback: Callable[[dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    resolved_settings = settings or BrowserDiscoverySettings()
    keywords = resolve_profile_keywords(profile=profile, keyword=keyword)

    pw = None
    browser = None
    chrome_proc = None
    page = None
    discovered: list[dict[str, object]] = []
    seen_keys: set[str] = set()

    try:
        chrome_proc = launch_real_chrome(resolved_settings)
        pw = sync_playwright().start()
        browser, page = connect_playwright_to_chrome(pw, resolved_settings)
        _goto_with_recovery(page, MAIN_PAGE_URL, resolved_settings)
        _logged_sleep(3)
        wait_for_cloudflare(page, resolved_settings.cloudflare_timeout_ms)
        _goto_with_recovery(page, SEARCH_URL, resolved_settings)
        _logged_sleep(5)
        wait_for_cloudflare(page, resolved_settings.cloudflare_timeout_ms)

        keyword_index = 0
        resume_state: DiscoveryResumeState | None = None
        while keyword_index < len(keywords):
            active_keyword = keywords[keyword_index]
            try:
                if resume_state is not None and resume_state.keyword_index == keyword_index:
                    restore_results_page(
                        page,
                        active_keyword,
                        resume_state.page_num,
                        resolved_settings,
                    )
                else:
                    if keyword_index > 0:
                        clear_search(page, resolved_settings)
                    search_keyword(page, active_keyword, resolved_settings)
                    if is_no_results_page(page):
                        keyword_index += 1
                        resume_state = None
                        continue
                discovered.extend(
                    _collect_keyword_projects(
                        page=page,
                        keyword=active_keyword,
                        settings=resolved_settings,
                        seen_keys=seen_keys,
                        include_documents=include_documents,
                        project_callback=project_callback,
                    )
                )
                keyword_index += 1
                resume_state = None
            except BrowserClosedDuringKeyword as exc:
                resume_state = DiscoveryResumeState(
                    keyword_index=keyword_index,
                    keyword=active_keyword,
                    page_num=exc.page_num,
                )
                safe_shutdown(browser=browser, pw=pw, chrome_proc=chrome_proc)
                chrome_proc = launch_real_chrome(resolved_settings)
                pw = sync_playwright().start()
                browser, page = connect_playwright_to_chrome(pw, resolved_settings)
                _goto_with_recovery(page, MAIN_PAGE_URL, resolved_settings)
                _logged_sleep(3)
                wait_for_cloudflare(page, resolved_settings.cloudflare_timeout_ms)
                _goto_with_recovery(page, SEARCH_URL, resolved_settings)
                _logged_sleep(5)
                wait_for_cloudflare(page, resolved_settings.cloudflare_timeout_ms)
        return discovered
    finally:
        safe_shutdown(browser=browser, pw=pw, chrome_proc=chrome_proc)


def _collect_keyword_projects(
    *,
    page,
    keyword: str,
    settings: BrowserDiscoverySettings,
    seen_keys: set[str],
    include_documents: bool,
    project_callback: Callable[[dict[str, object]], None] | None = None,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    page_num = 1
    while page_num <= settings.max_pages_per_keyword:
        try:
            rows = get_results_rows(page)
        except Exception as exc:
            _raise_browser_closed(exc, page_num)
            raise
        eligible_rows: list[dict[str, object]] = []
        for row in rows:
            row_payload = _extract_search_row(row)
            if row_payload is None:
                continue
            if any(blocked in row_payload["project_name"] for blocked in SKIP_KEYWORDS_IN_PROJECT):
                continue
            dedupe_key = str(
                row_payload.get("project_number") or row_payload["project_name"]
            ).casefold()
            if dedupe_key in seen_keys:
                continue
            eligible_rows.append(
                {
                    "project_name": row_payload["project_name"],
                    "organization_name": row_payload["organization_name"],
                    "project_number": row_payload.get("project_number"),
                    "source_status_text": row_payload["source_status_text"],
                    "row_marker": row_payload["row_marker"],
                }
            )

        for row_info in eligible_rows:
            try:
                resolved_row_index = _resolve_results_row_index(page, row_info)
                if resolved_row_index is None:
                    raise ResultsPageRecoveryError(
                        keyword=keyword,
                        target_page_num=page_num,
                        row_marker=row_info,
                        reason="results row marker missing on current page",
                    )
                _log_live_progress("project_open_start", keyword=keyword, row_marker=row_info)
                payload = _run_project_extraction_with_timeout(
                    lambda: open_and_extract_project(
                        page=page,
                        row_index=resolved_row_index,
                        keyword=keyword,
                        include_documents=False if include_documents else include_documents,
                        source_status_text=str(row_info["source_status_text"]),
                    ),
                    timeout_s=settings.project_detail_timeout_s,
                    keyword=keyword,
                    row_marker=row_info,
                )
                if payload is not None and include_documents:
                    payload = _collect_documents_for_payload(
                        page,
                        payload=payload,
                        keyword=keyword,
                        timeout_s=settings.project_detail_timeout_s,
                    )
                _log_live_progress(
                    "project_open_finished", keyword=keyword, row_marker=payload or row_info
                )
                if payload is None:
                    seen_keys.add(
                        str(row_info.get("project_number") or row_info["project_name"]).casefold()
                    )
                    _return_to_results(
                        page,
                        settings,
                        keyword=keyword,
                        target_page_num=page_num,
                        row_marker=row_info,
                    )
                    continue
                dedupe_key = str(
                    payload.get("project_number") or payload["project_name"]
                ).casefold()
                if dedupe_key not in seen_keys:
                    seen_keys.add(dedupe_key)
                    results.append(payload)
                    if project_callback is not None:
                        project_callback(payload)
                _return_to_results(
                    page,
                    settings,
                    keyword=keyword,
                    target_page_num=page_num,
                    row_marker=payload,
                )
            except BrowserClosedDuringKeyword:
                _mark_row_seen(seen_keys, row_info)
                raise
            except TimeoutError as exc:
                _log_live_progress(
                    "project_timeout",
                    keyword=keyword,
                    row_marker=row_info,
                    extra={
                        "timeout_s": settings.project_detail_timeout_s,
                        "error": str(exc),
                    },
                )
                log_results_debug_snapshot(
                    page,
                    keyword,
                    f"project_timeout:{row_info.get('project_name') or 'unknown-row'}",
                    expected_marker=row_info,
                )
                try:
                    _return_to_results(
                        page,
                        settings,
                        keyword=keyword,
                        target_page_num=page_num,
                        row_marker=row_info,
                    )
                    continue
                except ResultsPageRecoveryError:
                    if _results_page_available(page, allow_no_results=False):
                        continue
                    _mark_row_seen(seen_keys, row_info)
                    raise BrowserClosedDuringKeyword(page_num=page_num, message=str(exc)) from exc
                except BrowserClosedDuringKeyword:
                    _mark_row_seen(seen_keys, row_info)
                    raise
            except ResultsPageRecoveryError:
                if _results_page_available(page, allow_no_results=False):
                    marker_name = str(row_info.get("project_name") or "unknown-row")
                    log_results_debug_snapshot(
                        page,
                        keyword,
                        f"project_restore_skipped:{marker_name}",
                        expected_marker=row_info,
                    )
                    continue
                raise
            except SearchPageStateError as exc:
                log_results_debug_snapshot(
                    page,
                    keyword,
                    f"project_restore_site_state_reset:{row_info.get('project_name') or 'unknown-row'}",
                    expected_marker=row_info,
                )
                try:
                    _return_to_results(
                        page,
                        settings,
                        keyword=keyword,
                        target_page_num=page_num,
                        row_marker=row_info,
                    )
                    continue
                except ResultsPageRecoveryError:
                    if _results_page_available(page, allow_no_results=False):
                        continue
                    _mark_row_seen(seen_keys, row_info)
                    raise BrowserClosedDuringKeyword(page_num=page_num, message=str(exc)) from exc
                except SearchPageStateError:
                    _mark_row_seen(seen_keys, row_info)
                    raise BrowserClosedDuringKeyword(page_num=page_num, message=str(exc)) from exc
                except BrowserClosedDuringKeyword:
                    _mark_row_seen(seen_keys, row_info)
                    raise BrowserClosedDuringKeyword(page_num=page_num, message=str(exc)) from exc
            except Exception as exc:
                _raise_browser_closed(exc, page_num)
                raise

        previous_marker = get_results_page_marker(page)
        next_btn = page.query_selector(NEXT_PAGE_SELECTOR)
        if not (next_btn and next_btn.is_visible()):
            break
        state = None
        try:
            state = next_btn.evaluate(
                """el => {
                    const li = el.closest('li');
                    const src = li || el;
                    return {
                        ariaDisabled: el.getAttribute('aria-disabled') ||
                                     (src && src.getAttribute ? src.getAttribute('aria-disabled') : null),
                        disabled: ('disabled' in el) ? el.disabled : null,
                        className: (src && src.className) ? String(src.className) : '',
                    };
                }"""
            )
        except Exception:
            state = None
        if state and pagination_button_is_disabled(
            state.get("ariaDisabled"),
            state.get("disabled"),
            state.get("className"),
        ):
            break
        try:
            page.evaluate("(el) => el.click()", next_btn)
        except Exception:
            try:
                next_btn.click(timeout=10_000)
            except Exception:
                break
        _logged_sleep(3)
        if has_site_error_toast(page):
            clear_site_error_toast(page)
            _log_live_progress(
                "pagination_site_error",
                keyword=keyword,
                extra={"page_num": page_num + 1},
            )
            raise LiveDiscoveryPartialError(
                f"pagination site error after page {page_num} for keyword '{keyword}'"
            )
        if not wait_for_results_page_change(
            page, previous_marker, timeout_ms=settings.nav_timeout_ms
        ):
            break
        if is_no_results_page(page):
            break
        page_num += 1
    return results


def _raise_browser_closed(exc: Exception, page_num: int) -> None:
    if "has been closed" in str(exc):
        raise BrowserClosedDuringKeyword(page_num=page_num) from exc


def _mark_row_seen(seen_keys: set[str], row_info: dict[str, object] | None) -> None:
    if not row_info:
        return
    seen_keys.add(
        str(row_info.get("project_number") or row_info.get("project_name") or "").casefold()
    )


def _is_recovery_browser_error(exc: Exception) -> bool:
    message = str(exc or "")
    return any(marker in message for marker in RECOVERY_BROWSER_ERROR_MARKERS)


def _run_project_extraction_with_timeout(
    action,
    *,
    timeout_s: float,
    keyword: str,
    row_marker: dict[str, object] | None = None,
):
    if timeout_s <= 0 or not _can_use_signal_timeout():
        return action()
    marker_name = str((row_marker or {}).get("project_name") or "unknown-row")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def _handle_timeout(signum, frame) -> None:
        raise ProjectExtractionTimeout(
            f"project detail extraction timed out after {timeout_s:.1f}s "
            f"for keyword '{keyword}' ({marker_name})"
        )

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return action()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def _can_use_signal_timeout() -> bool:
    return (
        threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
        and hasattr(signal, "getitimer")
    )


def restore_results_page(
    page,
    keyword: str,
    target_page_num: int,
    settings: BrowserDiscoverySettings,
) -> None:
    search_keyword(page, keyword, settings)
    current_page = 1
    while current_page < max(target_page_num, 1):
        previous_marker = get_results_page_marker(page)
        next_btn = page.query_selector(NEXT_PAGE_SELECTOR)
        if not (next_btn and next_btn.is_visible()):
            break
        try:
            page.evaluate("(el) => el.click()", next_btn)
        except Exception:
            next_btn.click(timeout=10_000)
        _logged_sleep(3)
        _raise_on_site_error_toast(page, action=f"restore page {current_page + 1}")
        if not wait_for_results_page_change(
            page, previous_marker, timeout_ms=settings.nav_timeout_ms
        ):
            raise SearchPageStateError(
                f"results page did not advance while restoring page {target_page_num}"
            )
        current_page += 1


def _extract_search_row(row) -> dict[str, object] | None:
    cells = row.query_selector_all("td")
    if len(cells) < 6:
        return None
    status_text = cells[4].inner_text().strip()
    if not status_matches_target(status_text):
        return None
    search_name = cells[2].inner_text().strip()
    project_number = _extract_project_number_from_text(row.inner_text())
    row_marker = _build_results_row_marker(cells)
    if project_number and not row_marker.get("project_number"):
        row_marker["project_number"] = project_number
    return {
        "search_name": search_name,
        "project_name": search_name,
        "organization_name": cells[1].inner_text().strip(),
        "project_number": project_number,
        "source_status_text": status_text,
        "row_marker": row_marker,
    }


def _build_results_row_marker(cells) -> dict[str, str]:
    project_name = cells[2].inner_text().strip()
    organization_name = cells[1].inner_text().strip()
    budget_text = cells[3].inner_text().strip()
    source_status_text = cells[4].inner_text().strip()
    return {
        "organization_name": organization_name,
        "project_name": project_name,
        "project_number": _extract_project_number_from_text(project_name) or "",
        "budget_text": budget_text,
        "source_status_text": source_status_text,
        "visible_signature": " || ".join(
            _compact_visible_text(cell.inner_text().strip()) for cell in cells[1:5]
        ),
    }


def _row_marker_matches(current: dict[str, str], expected: dict[str, object]) -> bool:
    current_project_number = _normalize_project_number(current.get("project_number"))
    expected_project_number = _normalize_project_number(str(expected.get("project_number") or ""))
    if current_project_number and expected_project_number:
        return current_project_number == expected_project_number
    current_signature = _compact_visible_text(current.get("visible_signature"))
    expected_signature = _compact_visible_text(str(expected.get("visible_signature") or ""))
    if current_signature and expected_signature:
        return current_signature == expected_signature
    return (
        _compact_visible_text(current.get("organization_name"))
        == _compact_visible_text(str(expected.get("organization_name") or ""))
        and _compact_visible_text(current.get("project_name"))
        == _compact_visible_text(str(expected.get("project_name") or ""))
        and _compact_visible_text(current.get("source_status_text"))
        == _compact_visible_text(str(expected.get("source_status_text") or ""))
    )


def _normalize_project_number(value: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z-]+", "", value or "")


def _extract_project_number_from_text(value: str | None) -> str | None:
    match = re.search(r"เลขที่โครงการ\s*[:：]?\s*([0-9A-Za-z-]+)", value or "")
    if not match:
        return None
    project_number = _normalize_project_number(match.group(1))
    return project_number or None


def _score_row_marker_candidate(current: dict[str, str], expected: dict[str, object]) -> int:
    current_project_number = _normalize_project_number(current.get("project_number"))
    expected_project_number = _normalize_project_number(str(expected.get("project_number") or ""))
    if current_project_number and expected_project_number:
        return 100 if current_project_number == expected_project_number else 0
    score = 0
    if _compact_visible_text(current.get("project_name")) == _compact_visible_text(
        str(expected.get("project_name") or "")
    ):
        score += 40
    if _compact_visible_text(current.get("organization_name")) == _compact_visible_text(
        str(expected.get("organization_name") or "")
    ):
        score += 20
    if _compact_visible_text(current.get("source_status_text")) == _compact_visible_text(
        str(expected.get("source_status_text") or "")
    ):
        score += 20
    if _compact_visible_text(current.get("budget_text")) == _compact_visible_text(
        str(expected.get("budget_text") or "")
    ):
        score += 10
    return score


def _resolve_results_row_index(page, row_marker: dict[str, object]) -> int | None:
    expected_marker = row_marker.get("row_marker")
    if isinstance(expected_marker, dict):
        marker_payload: dict[str, object] = expected_marker
    else:
        marker_payload = row_marker
    ranked_candidates: list[tuple[int, int]] = []
    eligible_index = 0
    for row in get_results_rows(page):
        row_payload = _extract_search_row(row)
        if row_payload is None:
            continue
        current_marker = row_payload.get("row_marker")
        if isinstance(current_marker, dict) and _row_marker_matches(current_marker, marker_payload):
            return eligible_index
        if isinstance(current_marker, dict):
            ranked_candidates.append(
                (_score_row_marker_candidate(current_marker, marker_payload), eligible_index)
            )
        eligible_index += 1
    if not ranked_candidates:
        return None
    ranked_candidates.sort(reverse=True)
    best_score, best_index = ranked_candidates[0]
    if best_score < 70:
        return None
    if sum(1 for score, _ in ranked_candidates if score == best_score) > 1:
        return None
    return best_index


def _expected_marker_payload(expected_marker: dict[str, object] | None) -> dict[str, object] | None:
    if not expected_marker:
        return None
    nested_marker = expected_marker.get("row_marker")
    if isinstance(nested_marker, dict):
        return nested_marker
    return expected_marker


def _format_expected_marker(expected_marker: dict[str, object] | None) -> dict[str, str]:
    marker_payload = _expected_marker_payload(expected_marker)
    if not marker_payload:
        return {}
    fields = (
        "project_name",
        "organization_name",
        "project_number",
        "budget_text",
        "source_status_text",
        "visible_signature",
    )
    return {
        field: str(marker_payload.get(field) or "").strip()
        for field in fields
        if str(marker_payload.get(field) or "").strip()
    }


def _build_candidate_row_snapshot(
    page,
    expected_marker: dict[str, object] | None,
    *,
    candidate_limit: int = 3,
) -> list[dict[str, object]]:
    marker_payload = _expected_marker_payload(expected_marker)
    if not marker_payload:
        return []
    candidates: list[dict[str, object]] = []
    eligible_index = 0
    for row in get_results_rows(page):
        row_payload = _extract_search_row(row)
        if row_payload is None:
            continue
        current_marker = row_payload.get("row_marker")
        if not isinstance(current_marker, dict):
            eligible_index += 1
            continue
        candidates.append(
            {
                "eligible_index": eligible_index,
                "score": _score_row_marker_candidate(current_marker, marker_payload),
                "project_name": str(current_marker.get("project_name") or ""),
                "organization_name": str(current_marker.get("organization_name") or ""),
                "project_number": str(current_marker.get("project_number") or ""),
                "budget_text": str(current_marker.get("budget_text") or ""),
                "source_status_text": str(current_marker.get("source_status_text") or ""),
            }
        )
        eligible_index += 1
    candidates.sort(
        key=lambda candidate: (int(candidate["score"]), -int(candidate["eligible_index"])),
        reverse=True,
    )
    return candidates[:candidate_limit]


def open_and_extract_project(
    *,
    page,
    row_index: int,
    keyword: str,
    include_documents: bool = False,
    source_status_text: str = TARGET_STATUS,
) -> dict[str, object] | None:
    _log_live_progress(
        "project_detail_click_start",
        keyword=keyword,
        row_marker={"row_index": row_index, "source_status_text": source_status_text},
    )
    if not navigate_to_project_by_row(page, row_index):
        _log_live_progress(
            "project_detail_click_failed",
            keyword=keyword,
            row_marker={"row_index": row_index, "source_status_text": source_status_text},
        )
        return None
    _log_live_progress(
        "project_detail_click_finished",
        keyword=keyword,
        row_marker={"row_index": row_index, "source_status_text": source_status_text},
    )
    _logged_sleep(2)
    if check_has_preliminary_pricing(page):
        _log_live_progress(
            "project_detail_skipped_preliminary_pricing",
            keyword=keyword,
            row_marker={"row_index": row_index, "source_status_text": source_status_text},
        )
        return None
    _log_live_progress(
        "project_detail_extract_start",
        keyword=keyword,
        row_marker={"row_index": row_index, "source_status_text": source_status_text},
    )
    detail = extract_project_info(page)
    if _detail_page_is_invalid(page, detail):
        _log_live_progress(
            "project_detail_invalid",
            keyword=keyword,
            row_marker={
                "row_index": row_index,
                "source_status_text": source_status_text,
                "project_name": str(detail.get("project_name") or ""),
                "organization_name": str(detail.get("organization") or ""),
                "project_number": str(detail.get("project_number") or ""),
            },
        )
        return None
    project_name = detail.get("project_name") or ""
    organization_name = detail.get("organization") or ""
    if not project_name or not organization_name:
        _log_live_progress(
            "project_detail_missing_required_fields",
            keyword=keyword,
            row_marker={
                "row_index": row_index,
                "source_status_text": source_status_text,
                "project_name": str(project_name),
                "organization_name": str(organization_name),
                "project_number": str(detail.get("project_number") or ""),
            },
        )
        return None
    project_marker = {
        "row_index": row_index,
        "source_status_text": source_status_text,
        "project_name": str(project_name),
        "organization_name": str(organization_name),
        "project_number": str(detail.get("project_number") or ""),
    }
    _log_live_progress(
        "project_detail_extract_finished", keyword=keyword, row_marker=project_marker
    )
    proposal_submission_date = _normalize_buddhist_date(detail.get("proposal_submission_date"))
    budget_amount = _normalize_budget(detail.get("budget"))
    project_state = _infer_project_state(
        project_name=project_name, organization_name=organization_name
    )
    source_page_text = _build_source_page_text(page)
    if include_documents:
        _log_live_progress("project_documents_start", keyword=keyword, row_marker=project_marker)
    downloaded_documents = (
        collect_downloaded_documents(
            page,
            source_status_text=source_status_text,
            source_page_text=source_page_text,
            project_state=project_state,
        )
        if include_documents
        else []
    )
    if include_documents:
        _log_live_progress(
            "project_documents_finished",
            keyword=keyword,
            row_marker=project_marker,
            extra={"document_count": len(downloaded_documents)},
        )
    artifact_bucket = derive_artifact_bucket(
        labels=[str(document.get("source_label") or "") for document in downloaded_documents]
    )
    if artifact_bucket is ArtifactBucket.FINAL_TOR_DOWNLOADED:
        project_state = ProjectState.TOR_DOWNLOADED.value
    elif artifact_bucket is ArtifactBucket.DRAFT_PLUS_PRICING:
        project_state = ProjectState.OPEN_PUBLIC_HEARING.value
    return {
        "keyword": keyword,
        "project_name": project_name,
        "organization_name": organization_name,
        "project_number": detail.get("project_number") or None,
        "search_name": project_name,
        "detail_name": project_name,
        "proposal_submission_date": proposal_submission_date,
        "budget_amount": budget_amount,
        "procurement_type": _infer_procurement_type(
            project_name=project_name,
            organization_name=organization_name,
        ),
        "project_state": project_state,
        "artifact_bucket": artifact_bucket.value,
        "downloaded_documents": downloaded_documents,
        "source_status_text": source_status_text,
        "raw_snapshot": {
            "keyword": keyword,
            "project_name": project_name,
            "organization_name": organization_name,
            "project_number": detail.get("project_number") or None,
            "proposal_submission_date": proposal_submission_date,
            "budget_amount": budget_amount,
            "procurement_type": _infer_procurement_type(
                project_name=project_name,
                organization_name=organization_name,
            ),
            "project_state": project_state,
            "artifact_bucket": artifact_bucket.value,
            "downloaded_documents": [
                {
                    "file_name": document.get("file_name"),
                    "source_label": document.get("source_label"),
                    "source_status_text": document.get("source_status_text"),
                    "source_page_text": document.get("source_page_text"),
                    "project_state": document.get("project_state"),
                }
                for document in downloaded_documents
            ],
            "source_status_text": source_status_text,
        },
    }


def _document_snapshot_list(
    downloaded_documents: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "file_name": document.get("file_name"),
            "source_label": document.get("source_label"),
            "source_status_text": document.get("source_status_text"),
            "source_page_text": document.get("source_page_text"),
            "project_state": document.get("project_state"),
        }
        for document in downloaded_documents
    ]


def _mark_document_collection_status(
    payload: dict[str, object],
    *,
    status: str,
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    updated = dict(payload)
    updated["document_collection_status"] = status
    if reason:
        updated["document_collection_reason"] = reason
    elif "document_collection_reason" in updated:
        updated.pop("document_collection_reason", None)
    if error:
        updated["document_collection_error"] = error
    elif "document_collection_error" in updated:
        updated.pop("document_collection_error", None)
    raw_snapshot = dict(updated.get("raw_snapshot") or {})
    raw_snapshot["document_collection_status"] = status
    if reason:
        raw_snapshot["document_collection_reason"] = reason
    else:
        raw_snapshot.pop("document_collection_reason", None)
    if error:
        raw_snapshot["document_collection_error"] = error
    else:
        raw_snapshot.pop("document_collection_error", None)
    updated["raw_snapshot"] = raw_snapshot
    return updated


def _apply_downloaded_documents_to_payload(
    payload: dict[str, object],
    downloaded_documents: list[dict[str, object]],
) -> dict[str, object]:
    updated = dict(payload)
    updated["downloaded_documents"] = downloaded_documents
    artifact_bucket = derive_artifact_bucket(
        labels=[str(document.get("source_label") or "") for document in downloaded_documents]
    )
    updated["artifact_bucket"] = artifact_bucket.value
    project_state = str(updated.get("project_state") or "")
    if artifact_bucket is ArtifactBucket.FINAL_TOR_DOWNLOADED:
        project_state = ProjectState.TOR_DOWNLOADED.value
    elif artifact_bucket is ArtifactBucket.DRAFT_PLUS_PRICING:
        project_state = ProjectState.OPEN_PUBLIC_HEARING.value
    updated["project_state"] = project_state

    raw_snapshot = dict(updated.get("raw_snapshot") or {})
    raw_snapshot["project_state"] = project_state
    raw_snapshot["artifact_bucket"] = artifact_bucket.value
    raw_snapshot["downloaded_documents"] = _document_snapshot_list(downloaded_documents)
    updated["raw_snapshot"] = raw_snapshot
    return updated


def _collect_documents_for_payload(
    page,
    *,
    payload: dict[str, object],
    keyword: str,
    timeout_s: float,
) -> dict[str, object]:
    project_marker = {
        "project_name": str(payload.get("project_name") or ""),
        "organization_name": str(payload.get("organization_name") or ""),
        "project_number": str(payload.get("project_number") or ""),
        "source_status_text": str(payload.get("source_status_text") or ""),
    }
    _log_live_progress("project_documents_start", keyword=keyword, row_marker=project_marker)
    started_at = time.monotonic()
    try:
        downloaded_documents = collect_downloaded_documents(
            page,
            source_status_text=str(payload.get("source_status_text") or ""),
            source_page_text=_build_source_page_text(page),
            project_state=(
                str(payload["project_state"]) if payload.get("project_state") is not None else None
            ),
        )
    except TimeoutError as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _log_live_progress(
            "project_documents_timeout",
            keyword=keyword,
            row_marker=project_marker,
            extra={
                "timeout_s": timeout_s,
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            },
        )
        return _mark_document_collection_status(
            payload,
            status=DOCUMENT_COLLECTION_TIMEOUT,
            reason=DOCUMENT_COLLECTION_TIMEOUT_REASON,
            error=str(exc),
        )
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _log_live_progress(
            "project_documents_failed",
            keyword=keyword,
            row_marker=project_marker,
            extra={
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            },
        )
        return _mark_document_collection_status(
            payload,
            status=DOCUMENT_COLLECTION_FAILED,
            reason=DOCUMENT_COLLECTION_FAILED_REASON,
            error=str(exc),
        )

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    updated_payload = _apply_downloaded_documents_to_payload(payload, downloaded_documents)
    updated_payload = _mark_document_collection_status(
        updated_payload,
        status=DOCUMENT_COLLECTION_SUCCEEDED,
    )
    _log_live_progress(
        "project_documents_finished",
        keyword=keyword,
        row_marker=project_marker,
        extra={
            "document_count": len(downloaded_documents),
            "document_collection_status": DOCUMENT_COLLECTION_SUCCEEDED,
            "elapsed_ms": elapsed_ms,
        },
    )
    return updated_payload


def _detail_page_is_invalid(page, detail: dict[str, str]) -> bool:
    try:
        body_text = page.inner_text("body")
    except Exception:
        body_text = ""
    compact_body = _compact_visible_text(body_text)
    if "ข้อความปฎิเสธ" in body_text or "E1530" in body_text:
        return True
    invalid_values = {
        "",
        "ชื่อโครงการ",
        "ชื่อหน่วยงาน",
        "เลขที่โครงการ",
        "วิธีการจัดชื้อจัดจ้าง",
    }
    project_name = str(detail.get("project_name") or "").strip()
    organization = str(detail.get("organization") or "").strip()
    project_number = str(detail.get("project_number") or "").strip()
    if (
        project_name in invalid_values
        or organization in invalid_values
        or project_number in invalid_values
    ):
        return True
    if project_name and _compact_visible_text(project_name) in {
        _compact_visible_text("วงเงินงบประมาณ (บาท) สถานะโครงการ ดูข้อมูล"),
        _compact_visible_text("ชื่อโครงการ วงเงินงบประมาณ (บาท) สถานะโครงการ ดูข้อมูล"),
    }:
        return True
    if compact_body and "จำนวนโครงการที่พบ" in body_text and "/procurement/" not in page.url:
        return True
    return False


def launch_real_chrome(settings: BrowserDiscoverySettings) -> subprocess.Popen:
    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            settings.chrome_path,
            f"--remote-debugging-port={settings.cdp_port}",
            f"--user-data-dir={settings.browser_profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,900",
            "--disable-features=DownloadBubble",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_for_local_tcp_listen("127.0.0.1", settings.cdp_port, timeout_seconds=15)
    return proc


def connect_playwright_to_chrome(pw, settings: BrowserDiscoverySettings):
    if not wait_for_local_tcp_listen("127.0.0.1", settings.cdp_port, timeout_seconds=15):
        raise RuntimeError(f"Chrome CDP port {settings.cdp_port} is not reachable")
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{settings.cdp_port}")
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    context.set_default_timeout(settings.nav_timeout_ms)
    page = context.new_page()
    return browser, page


def wait_for_local_tcp_listen(host: str, port: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect((host, int(port)))
            return True
        except OSError:
            pass
        finally:
            sock.close()
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.15)


def _goto_with_recovery(
    page,
    url: str,
    settings: BrowserDiscoverySettings,
    *,
    retries_remaining: int | None = None,
) -> None:
    retry_budget = (
        settings.search_page_recovery_retries
        if retries_remaining is None
        else max(0, int(retries_remaining))
    )
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
        return
    except Exception as exc:
        if "ERR_ABORTED" not in str(exc) or retry_budget <= 0:
            raise
        _logged_sleep(1)
        _goto_with_recovery(
            page,
            url,
            settings,
            retries_remaining=retry_budget - 1,
        )


def safe_shutdown(*, browser=None, pw=None, chrome_proc: subprocess.Popen | None = None) -> None:
    old_sigint = None
    try:
        old_sigint = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        old_sigint = None
    try:
        if browser is not None:
            try:
                browser.close()
            except BaseException:
                pass
        if pw is not None:
            try:
                pw.stop()
            except BaseException:
                pass
        if chrome_proc is not None:
            try:
                chrome_proc.send_signal(signal.SIGTERM)
                chrome_proc.wait(timeout=5)
            except BaseException:
                try:
                    chrome_proc.kill()
                    chrome_proc.wait(timeout=5)
                except BaseException:
                    pass
    finally:
        if old_sigint is not None:
            try:
                signal.signal(signal.SIGINT, old_sigint)
            except Exception:
                pass


def wait_for_cloudflare(page, timeout_ms: int, reload_retries: int = 1) -> bool:
    start = time.time()
    timeout_s = timeout_ms / 1000
    while time.time() - start < timeout_s:
        search_btn = page.query_selector("button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))")
        if search_btn and search_btn.get_attribute("disabled") is None:
            return True
        if not search_btn:
            cf_iframe = page.query_selector("iframe[src*='challenges.cloudflare.com']")
            if not cf_iframe:
                return True
        _logged_sleep(2)
    if reload_retries > 0:
        try:
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            try:
                page.goto(page.url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                return False
        _logged_sleep(3)
        return wait_for_cloudflare(page, timeout_ms, reload_retries=reload_retries - 1)
    return False


def _raise_on_site_error_toast(page, *, action: str) -> None:
    if not has_site_error_toast(page):
        return
    clear_site_error_toast(page)
    raise SearchPageStateError(f"e-GP site error after {action}: ระบบเกิดข้อผิดพลาด กรุณาตรวจสอบ")


def _compact_visible_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def status_matches_target(status_text: str) -> bool:
    return _compact_visible_text(TARGET_STATUS) in _compact_visible_text(status_text)


def _table_matches_results_headers(table) -> bool:
    """Return True when a table looks like the procurement results table."""
    header_selectors = ("thead th, thead td", "th", "tr:first-child th, tr:first-child td")
    headers: list[str] = []
    for selector in header_selectors:
        try:
            header_els = table.query_selector_all(selector)
        except Exception:
            header_els = []
        headers = [
            header.inner_text().strip() for header in header_els if header.inner_text().strip()
        ]
        if headers:
            break
    if not headers:
        return False
    compact_headers = [_compact_visible_text(header) for header in headers]
    return all(
        any(_compact_visible_text(required) in header for header in compact_headers)
        for required in RESULTS_TABLE_REQUIRED_HEADERS
    )


def find_results_table(page):
    """Return the procurement search results table, if present."""
    for table in page.query_selector_all("table"):
        try:
            if _table_matches_results_headers(table):
                return table
        except Exception:
            continue
    return None


def get_results_rows(page) -> list:
    """Return rows from the procurement search results table only."""
    table = find_results_table(page)
    if not table:
        return []
    try:
        rows = table.query_selector_all("tbody tr")
    except Exception:
        return []
    filtered_rows = [row for row in rows if not _results_row_is_no_results_placeholder(row)]
    return filtered_rows


def _results_row_is_no_results_placeholder(row) -> bool:
    try:
        cells = row.query_selector_all("td")
    except Exception:
        cells = []
    try:
        text = re.sub(r"\s+", " ", row.inner_text() or "").strip()
    except Exception:
        text = ""
    if not text:
        return False
    compact = _compact_visible_text(text)
    return len(cells) <= 1 and any(
        _compact_visible_text(marker) in compact for marker in NO_RESULTS_MARKERS
    )


def find_search_input(page, search_btn):
    try:
        handle = search_btn.evaluate_handle(
            """(btn) => {
                const root = btn.closest('form') || btn.closest('div') || document;
                const selectors = [
                    "input[placeholder*='ระบุ']",
                    "input[name*='keyword' i]",
                    "input[id*='keyword' i]",
                    "input[formcontrolname*='keyword' i]",
                    "input[type='text']",
                ];
                for (const sel of selectors) {
                    const el = root.querySelector(sel);
                    if (el) return el;
                }
                return document.querySelector("input[placeholder*='ระบุ'], input[type='text']");
            }"""
        )
        element = handle.as_element()
        if element:
            return element
    except Exception:
        pass
    for candidate in page.query_selector_all(
        "input[placeholder*='ระบุ'], input[name*='keyword' i], input[id*='keyword' i], input[type='text']"
    ):
        try:
            if candidate.is_visible():
                return candidate
        except Exception:
            continue
    return page.wait_for_selector("input[type='text']")


def _safe_search_input_value(search_input) -> str:
    try:
        return str(search_input.input_value() or "")
    except Exception:
        try:
            return str(search_input.evaluate("(el) => el.value || ''") or "")
        except Exception:
            return ""


def _retry_search_from_clean_page(
    page,
    keyword: str,
    settings: BrowserDiscoverySettings,
) -> bool:
    if settings.search_page_recovery_retries <= 0:
        return False
    clear_site_error_toast(page)
    _goto_with_recovery(page, SEARCH_URL, settings)
    _logged_sleep(3)
    retry_settings = replace(
        settings,
        search_page_recovery_retries=settings.search_page_recovery_retries - 1,
    )
    search_keyword(page, keyword, retry_settings)
    return True


def click_search_button(page, search_btn=None, timeout_ms: int | None = None) -> None:
    """Click the primary search button with a DOM-query fallback for SPA rerenders."""
    try:
        clicked = page.evaluate(
            """() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                for (const btn of buttons) {
                    const txt = (btn.innerText || '').trim();
                    if (
                        txt.includes('ค้นหา') &&
                        !txt.includes('ค้นหาขั้นสูง') &&
                        btn.offsetParent !== null &&
                        !btn.disabled
                    ) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }"""
        )
        if clicked:
            return
    except Exception:
        pass

    selector = "button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))"
    effective_timeout = timeout_ms or 60_000

    try:
        if search_btn is None:
            search_btn = page.wait_for_selector(selector, timeout=effective_timeout)
        search_btn.click()
        return
    except Exception:
        fallback_btn = page.wait_for_selector(selector, timeout=effective_timeout)
        page.evaluate("(el) => el.click()", fallback_btn)


def is_no_results_page(page) -> bool:
    try:
        table = find_results_table(page)
        if not table:
            return False
        if get_results_rows(page):
            return False
        text = re.sub(r"\s+", " ", table.inner_text() or "").strip()
        return any(marker in text for marker in NO_RESULTS_MARKERS)
    except Exception:
        return False


def wait_for_results_ready(page, settings: BrowserDiscoverySettings) -> None:
    try:
        page.wait_for_selector("table", state="attached", timeout=settings.nav_timeout_ms)
    except Exception:
        pass
    for _ in range(3):
        try:
            if get_results_rows(page):
                return
        except Exception:
            pass
        if is_no_results_page(page):
            return
        _logged_sleep(1.0)


def _search_controls_ready(page) -> bool:
    search_btn = page.query_selector("button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))")
    if search_btn is None:
        return False
    try:
        if search_btn.get_attribute("disabled") is not None:
            return False
    except Exception:
        pass
    try:
        search_input = find_search_input(page, search_btn)
    except Exception:
        return False
    try:
        if (
            hasattr(search_input, "get_attribute")
            and search_input.get_attribute("disabled") is not None
        ):
            return False
    except Exception:
        pass
    try:
        if hasattr(search_input, "is_visible") and not search_input.is_visible():
            return False
    except Exception:
        pass
    return True


def _wait_for_search_controls_ready(page, timeout_ms: int) -> None:
    settle_timeout_s = min(timeout_ms / 1000, SEARCH_CONTROLS_SETTLE_TIMEOUT_S)
    deadline = time.monotonic() + max(1.0, settle_timeout_s)
    stable_since: float | None = None
    while time.monotonic() < deadline:
        if _search_controls_ready(page):
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= SEARCH_CONTROLS_STABLE_SECONDS:
                return
        else:
            stable_since = None
        _logged_sleep(0.5)


def get_results_page_marker(page) -> dict[str, str | int]:
    """Capture a compact signature for the current results page."""
    rows = get_results_rows(page)[:3]
    row_sample_parts: list[str] = []
    for row in rows:
        try:
            cells = row.query_selector_all("td")[:5]
            row_sample_parts.append("|".join((cell.inner_text() or "").strip() for cell in cells))
        except Exception:
            continue
    try:
        active = page.query_selector("li.page-item.active, li.active, .pagination .active")
        active_page = active.inner_text().strip() if active else ""
    except Exception:
        active_page = ""
    return {
        "active_page": active_page,
        "row_count": len(rows),
        "row_sample": " || ".join(row_sample_parts),
    }


def results_page_marker_changed(
    previous: dict[str, str | int], current: dict[str, str | int]
) -> bool:
    """Return True once pagination changes the active page or visible row sample."""
    return (
        str(previous.get("active_page", "") or "") != str(current.get("active_page", "") or "")
        or int(previous.get("row_count", -1) or -1) != int(current.get("row_count", -1) or -1)
        or str(previous.get("row_sample", "") or "") != str(current.get("row_sample", "") or "")
    )


def wait_for_results_page_change(
    page, previous_marker: dict[str, str | int], timeout_ms: int
) -> bool:
    """Wait for the result table to move to a different page or row sample."""
    deadline = time.monotonic() + max(1.0, timeout_ms / 1000)
    fallback_settings = BrowserDiscoverySettings(nav_timeout_ms=timeout_ms)
    while time.monotonic() < deadline:
        wait_for_results_ready(page, fallback_settings)
        current_marker = get_results_page_marker(page)
        if results_page_marker_changed(previous_marker, current_marker):
            return True
        if is_no_results_page(page):
            return True
        _logged_sleep(0.5)
    current_marker = get_results_page_marker(page)
    return results_page_marker_changed(previous_marker, current_marker) or is_no_results_page(page)


def _safe_results_page_marker(page) -> dict[str, str | int]:
    try:
        return get_results_page_marker(page)
    except Exception:
        return {"active_page": "", "row_count": 0, "row_sample": ""}


def _results_marker_matches_keyword(marker: dict[str, str | int], keyword: str) -> bool:
    row_sample = _compact_visible_text(str(marker.get("row_sample") or ""))
    return bool(row_sample and _compact_visible_text(keyword) in row_sample)


def _results_marker_is_first_page_with_rows(marker: dict[str, str | int]) -> bool:
    active_page = _compact_visible_text(str(marker.get("active_page") or ""))
    try:
        row_count = int(marker.get("row_count", 0) or 0)
    except (TypeError, ValueError):
        row_count = 0
    return row_count > 0 and active_page in {"", "1"}


def _safe_has_result_rows(page) -> bool:
    try:
        return bool(get_results_rows(page))
    except Exception:
        return False


def search_keyword(
    page,
    keyword: str,
    settings: BrowserDiscoverySettings,
    *,
    _page_recovery_retries_remaining: int | None = None,
) -> None:
    clear_site_error_toast(page)
    previous_marker = _safe_results_page_marker(page)
    had_previous_results = _safe_has_result_rows(page)
    page_recovery_retries_remaining = (
        settings.search_page_recovery_retries
        if _page_recovery_retries_remaining is None
        else max(0, int(_page_recovery_retries_remaining))
    )
    cloudflare_ok = wait_for_cloudflare(
        page,
        settings.cloudflare_timeout_ms,
        reload_retries=settings.cloudflare_reload_retries,
    )
    search_btn = page.query_selector("button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))")
    if (not cloudflare_ok or not search_btn) and page_recovery_retries_remaining > 0:
        _goto_with_recovery(page, SEARCH_URL, settings)
        _logged_sleep(3)
        search_keyword(
            page,
            keyword,
            settings,
            _page_recovery_retries_remaining=page_recovery_retries_remaining - 1,
        )
        return
    if not search_btn:
        search_btn = page.wait_for_selector(
            "button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))",
            timeout=settings.nav_timeout_ms,
        )
    _wait_for_search_controls_ready(page, settings.nav_timeout_ms)
    search_input = find_search_input(page, search_btn)
    previous_search_value = _safe_search_input_value(search_input)
    search_input.click()
    search_input.fill("")
    search_input.fill(keyword)
    _logged_sleep(0.5)
    click_search_button(page, search_btn, timeout_ms=settings.nav_timeout_ms)
    if has_site_error_toast(page) and _retry_search_from_clean_page(page, keyword, settings):
        return
    _raise_on_site_error_toast(page, action="search submit")
    wait_for_results_ready(page, settings)
    if has_site_error_toast(page) and _retry_search_from_clean_page(page, keyword, settings):
        return
    _raise_on_site_error_toast(page, action="search results load")
    same_keyword_retry = _compact_visible_text(previous_search_value) == _compact_visible_text(
        keyword
    )
    if (
        is_no_results_page(page)
        and settings.search_page_recovery_retries > 0
        and (not had_previous_results or same_keyword_retry)
    ):
        _retry_search_from_clean_page(page, keyword, settings)
        return
    current_marker = _safe_results_page_marker(page)
    if (
        had_previous_results
        and not is_no_results_page(page)
        and not results_page_marker_changed(previous_marker, current_marker)
    ):
        if settings.search_page_recovery_retries > 0 and (
            _compact_visible_text(previous_search_value) == _compact_visible_text(keyword)
            or _results_marker_matches_keyword(current_marker, keyword)
        ):
            return
        if settings.search_page_recovery_retries > 0:
            _retry_search_from_clean_page(page, keyword, settings)
            return
        if _results_marker_is_first_page_with_rows(current_marker):
            return
        raise SearchPageStateError(f"search results did not refresh for keyword '{keyword}'")


def clear_search(page, settings: BrowserDiscoverySettings) -> None:
    try:
        clear_btn = page.wait_for_selector("button:has-text('ล้างตัวเลือก')", timeout=10_000)
        clear_btn.click()
        _logged_sleep(1)
    except PlaywrightTimeout:
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
        _logged_sleep(3)
        wait_for_cloudflare(page, settings.cloudflare_timeout_ms)


def navigate_to_project_by_row(page, row_index: int) -> bool:
    rows = get_results_rows(page)
    eligible_idx = 0
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) < 6:
            continue
        if not status_matches_target(cells[4].inner_text().strip()):
            continue
        if eligible_idx == row_index:
            return _open_project_from_results_cell(page, cells[5])
        eligible_idx += 1
    return False


def _cell_click_targets(cell) -> list:
    selectors = [
        "a[href]",
        "a",
        "button:not([disabled])",
        "[role='button']",
        "egp-all-button",
        ".btn-icon",
        "svg",
        "i",
    ]
    targets = []
    for selector in selectors:
        try:
            target = cell.query_selector(selector)
        except Exception:
            target = None
        if target is None or target in targets:
            continue
        targets.append(target)
    return targets


def _open_project_from_results_cell(page, cell) -> bool:
    url_before = str(getattr(page, "url", "") or "")
    for target in _cell_click_targets(cell):
        for click_mode in ("native", "dom"):
            try:
                if click_mode == "native":
                    target.click()
                else:
                    page.evaluate("(el) => el.click()", target)
            except Exception:
                continue
            if _wait_for_project_detail_navigation(page, url_before=url_before):
                return True
    try:
        cell.click()
    except Exception:
        return False
    return _wait_for_project_detail_navigation(page, url_before=url_before)


def _wait_for_project_detail_navigation(page, *, url_before: str, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + max(0.1, timeout_s)
    while time.monotonic() < deadline:
        current_url = str(getattr(page, "url", "") or "")
        if current_url != url_before and "/procurement/" in current_url:
            return True
        _logged_sleep(0.1)
    current_url = str(getattr(page, "url", "") or "")
    return current_url != url_before and "/procurement/" in current_url


def check_has_preliminary_pricing(page) -> bool:
    return "สรุปข้อมูลการเสนอราคาเบื้องต้น" in page.content()


def extract_project_info(page) -> dict[str, str]:
    info = {
        "project_name": "",
        "organization": "",
        "project_number": "",
        "budget": "",
        "proposal_submission_date": "",
    }
    body_text = page.inner_text("body")
    name_match = re.search(r"ชื่อโครงการ\s*[:\s]\s*(.+?)(?:\n|เลขที่)", body_text, re.DOTALL)
    if name_match:
        info["project_name"] = name_match.group(1).strip()
    org_match = re.search(
        r"(?:หน่วยจัดซื้อ|หน่วยงาน)\s*[:\s]\s*(.+?)(?:\n|ชื่อโครงการ|วิธี)",
        body_text,
        re.DOTALL,
    )
    if org_match:
        info["organization"] = org_match.group(1).strip()
    num_match = re.search(r"เลขที่โครงการ\s*[:\s]\s*(\S+)", body_text)
    if num_match:
        info["project_number"] = num_match.group(1).strip()
    budget_match = re.search(r"วงเงินงบประมาณ\s*\n?\s*([\d,]+\.?\d*)", body_text)
    if budget_match:
        info["budget"] = budget_match.group(1).strip()
    date_match = re.search(
        r"(?:วันที่ยื่นข้อเสนอ|ยื่นซอง|วันยื่นข้อเสนอ|สิ้นสุดยื่นข้อเสนอ)\s*[:\s]\s*(\d{2}/\d{2}/\d{4})",
        body_text,
    )
    if date_match:
        info["proposal_submission_date"] = date_match.group(1).strip()
    return info


def parse_buddhist_date(text: str) -> date | None:
    normalized = text.strip()
    match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", normalized)
    if not match:
        return None
    day, month, buddhist_year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(buddhist_year - 543, month, day)
    except ValueError:
        return None


def _normalize_buddhist_date(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    parsed = parse_buddhist_date(value)
    return parsed.isoformat() if parsed is not None else None


def _normalize_budget(value: str | None) -> str | None:
    normalized = str(value or "").strip().replace(",", "")
    return normalized or None


def _split_visible_lines(text: str) -> list[str]:
    return [line.strip() for line in re.split(r"[\r\n]+", text or "") if line.strip()]


def _build_source_page_text(page, *, max_lines: int = 20, max_chars: int = 2_000) -> str:
    try:
        body_text = page.inner_text("body")
    except Exception:
        return ""
    compact = " | ".join(_split_visible_lines(body_text)[:max_lines])
    return compact[:max_chars]


def _infer_procurement_type(*, project_name: str, organization_name: str) -> str:
    combined = f"{project_name} {organization_name}"
    if "ที่ปรึกษา" in combined:
        return ProcurementType.CONSULTING.value
    return ProcurementType.SERVICES.value


def _infer_project_state(*, project_name: str, organization_name: str) -> str:
    procurement_type = _infer_procurement_type(
        project_name=project_name,
        organization_name=organization_name,
    )
    if procurement_type == ProcurementType.CONSULTING.value:
        return ProjectState.OPEN_CONSULTING.value
    return ProjectState.OPEN_INVITATION.value


def pagination_button_is_disabled(
    aria_disabled: str | None,
    disabled: bool | None,
    class_name: str | None,
) -> bool:
    if disabled is True:
        return True
    if aria_disabled and aria_disabled.strip().lower() == "true":
        return True
    if class_name and re.search(r"(?:^|\s)disabled(?:\s|$)", class_name):
        return True
    return False


def build_results_debug_snapshot(
    page,
    sample_limit: int = 3,
    *,
    expected_marker: dict[str, object] | None = None,
    candidate_limit: int = 3,
) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "url": getattr(page, "url", ""),
        "active_page": "",
        "results_headers": [],
        "results_row_count": 0,
        "results_row_samples": [],
        "expected_marker": {},
        "candidate_rows": [],
        "table_count": 0,
        "body_snippet": "",
    }

    try:
        tables = page.query_selector_all("table")
    except Exception:
        tables = []
    snapshot["table_count"] = len(tables)

    table = find_results_table(page)
    if table:
        header_selectors = ("thead th, thead td", "th", "tr:first-child th, tr:first-child td")
        headers: list[str] = []
        for selector in header_selectors:
            try:
                header_els = table.query_selector_all(selector)
            except Exception:
                header_els = []
            headers = [h.inner_text().strip() for h in header_els if h.inner_text().strip()]
            if headers:
                break
        snapshot["results_headers"] = headers

        rows = get_results_rows(page)
        snapshot["results_row_count"] = len(rows)
        samples: list[list[str]] = []
        for row in rows[:sample_limit]:
            try:
                samples.append([cell.inner_text().strip() for cell in row.query_selector_all("td")])
            except Exception:
                continue
        snapshot["results_row_samples"] = samples

    try:
        active = page.query_selector("li.page-item.active, li.active, .pagination .active")
        snapshot["active_page"] = active.inner_text().strip() if active else ""
    except Exception:
        pass

    try:
        body_text = page.inner_text("body")
        snapshot["body_snippet"] = " | ".join(_split_visible_lines(body_text)[:10])
    except Exception:
        pass

    snapshot["expected_marker"] = _format_expected_marker(expected_marker)
    try:
        snapshot["candidate_rows"] = _build_candidate_row_snapshot(
            page,
            expected_marker,
            candidate_limit=candidate_limit,
        )
    except Exception:
        snapshot["candidate_rows"] = []

    return snapshot


def log_results_debug_snapshot(
    page,
    keyword: str,
    reason: str,
    *,
    expected_marker: dict[str, object] | None = None,
) -> None:
    snapshot = build_results_debug_snapshot(page, expected_marker=expected_marker)
    print(
        f"    DEBUG [{reason}] keyword={keyword} active_page={snapshot['active_page'] or '-'} "
        f"tables={snapshot['table_count']} results_rows={snapshot['results_row_count']} "
        f"url={snapshot['url']}"
    )
    headers = snapshot.get("results_headers") or []
    if headers:
        print(f"    DEBUG headers: {' | '.join(str(h) for h in headers)}")
    for idx, row in enumerate(snapshot.get("results_row_samples") or [], start=1):
        print(f"    DEBUG row{idx}: {' | '.join(str(cell) for cell in row)}")
    expected = snapshot.get("expected_marker") or {}
    if expected:
        expected_parts = [f"{key}={value}" for key, value in expected.items()]
        print(f"    DEBUG expected_marker: {' | '.join(expected_parts)}")
    for idx, candidate in enumerate(snapshot.get("candidate_rows") or [], start=1):
        candidate_parts = [
            f"score={candidate['score']}",
            f"eligible_index={candidate['eligible_index']}",
        ]
        for field in (
            "project_name",
            "organization_name",
            "project_number",
            "budget_text",
            "source_status_text",
        ):
            value = str(candidate.get(field) or "").strip()
            if value:
                candidate_parts.append(f"{field}={value}")
        print(f"    DEBUG candidate{idx}: {' | '.join(candidate_parts)}")
    body_snippet = str(snapshot.get("body_snippet") or "")
    if body_snippet:
        print(f"    DEBUG body: {body_snippet[:500]}")


def _log_live_progress(
    stage: str,
    *,
    keyword: str,
    row_marker: dict[str, object] | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    fields: list[str] = [f"stage={stage}", f"keyword={keyword}"]
    marker = row_marker or {}
    for key in (
        "row_index",
        "project_name",
        "organization_name",
        "project_number",
        "source_status_text",
    ):
        value = str(marker.get(key) or "").strip()
        if value:
            fields.append(f"{key}={value}")
    for key, value in (extra or {}).items():
        rendered = str(value).replace("\n", " ").strip()
        if rendered:
            fields.append(f"{key}={rendered}")
    print(f"LIVE_PROGRESS {' | '.join(fields)}", flush=True)


def _results_page_available(page, *, allow_no_results: bool = True) -> bool:
    try:
        if has_site_error_toast(page):
            return False
        if get_results_rows(page):
            return True
        return allow_no_results and is_no_results_page(page)
    except Exception:
        return False


def _click_main_back_to_results(page) -> bool:
    try:
        clicked = page.evaluate(
            """() => {
                const labels = ['กลับหน้าหลัก', 'กลับ'];
                for (const label of labels) {
                    for (const button of document.querySelectorAll('button')) {
                        if (button.textContent.trim().includes(label) && button.offsetParent !== null) {
                            button.click();
                            return true;
                        }
                    }
                }
                for (const label of labels) {
                    for (const link of document.querySelectorAll('a')) {
                        if (link.textContent.trim().includes(label) && link.offsetParent !== null) {
                            link.click();
                            return true;
                        }
                    }
                }
                return false;
            }"""
        )
    except Exception:
        return False
    if clicked:
        _logged_sleep(2)
    return bool(clicked)


def _return_to_results(
    page,
    settings: BrowserDiscoverySettings,
    *,
    keyword: str,
    target_page_num: int,
    row_marker: dict[str, object] | None = None,
) -> None:
    recovery_reason = "ok"
    try:
        if _click_main_back_to_results(page):
            wait_for_results_ready(page, settings)
            if _results_page_available(page, allow_no_results=False):
                return
            recovery_reason = "results table missing after main back"
    except Exception as exc:
        recovery_reason = f"main back failed: {exc}"
    try:
        page.go_back(wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
        _logged_sleep(2)
        wait_for_results_ready(page, settings)
        if _results_page_available(page, allow_no_results=False):
            return
        recovery_reason = "results table missing after go_back"
    except Exception as exc:
        recovery_reason = f"go_back failed: {exc}"

    log_results_debug_snapshot(
        page,
        keyword,
        f"return_to_results:{recovery_reason}",
        expected_marker=row_marker,
    )
    try:
        if target_page_num > 1:
            restore_results_page(page, keyword, target_page_num, settings)
        else:
            search_keyword(page, keyword, settings)
    except Exception as exc:
        if _is_recovery_browser_error(exc):
            raise BrowserClosedDuringKeyword(
                page_num=target_page_num,
                message=str(exc),
            ) from exc
        raise
    if not _results_page_available(page, allow_no_results=False):
        marker_name = str((row_marker or {}).get("project_name") or "")
        log_results_debug_snapshot(
            page,
            keyword,
            f"return_to_results_recovery_failed:{marker_name or 'unknown-row'}",
            expected_marker=row_marker,
        )
        raise ResultsPageRecoveryError(
            keyword=keyword,
            target_page_num=target_page_num,
            row_marker=row_marker,
            reason=recovery_reason,
        )


def _logged_sleep(seconds: float) -> None:
    time.sleep(seconds)
