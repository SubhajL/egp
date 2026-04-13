"""Focused browser-driven e-GP discovery extracted from the legacy crawler."""

from __future__ import annotations

import re
import signal
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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


from egp_shared_types.enums import ProcurementType, ProjectState

from .browser_downloads import collect_downloaded_documents
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


@dataclass(frozen=True, slots=True)
class BrowserDiscoverySettings:
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    cdp_port: int = 9222
    nav_timeout_ms: int = 60_000
    cloudflare_timeout_ms: int = 120_000
    cloudflare_reload_retries: int = 1
    search_page_recovery_retries: int = 1
    max_pages_per_keyword: int = 15
    browser_profile_dir: Path = Path.home() / "download" / "TOR" / ".browser_profile"


def crawl_live_discovery(
    *,
    keyword: str | None = None,
    profile: str | None = None,
    settings: BrowserDiscoverySettings | None = None,
    include_documents: bool = False,
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
        page.goto(
            MAIN_PAGE_URL, wait_until="domcontentloaded", timeout=resolved_settings.nav_timeout_ms
        )
        _logged_sleep(3)
        wait_for_cloudflare(page, resolved_settings.cloudflare_timeout_ms)
        page.goto(
            SEARCH_URL, wait_until="domcontentloaded", timeout=resolved_settings.nav_timeout_ms
        )
        _logged_sleep(5)
        wait_for_cloudflare(page, resolved_settings.cloudflare_timeout_ms)

        for index, active_keyword in enumerate(keywords):
            if index > 0:
                clear_search(page, resolved_settings)
            search_keyword(page, active_keyword, resolved_settings)
            if is_no_results_page(page):
                continue
            discovered.extend(
                _collect_keyword_projects(
                    page=page,
                    keyword=active_keyword,
                    settings=resolved_settings,
                    seen_keys=seen_keys,
                    include_documents=include_documents,
                )
            )
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
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    page_num = 1
    while page_num <= settings.max_pages_per_keyword:
        rows = get_results_rows(page)
        eligible_rows: list[tuple[int, str]] = []
        for row_index, row in enumerate(rows):
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
            eligible_rows.append((row_index, row_payload["project_name"]))

        for row_index, _ in eligible_rows:
            payload = open_and_extract_project(
                page=page,
                row_index=row_index,
                keyword=keyword,
                include_documents=include_documents,
            )
            if payload is None:
                _return_to_results(page, settings)
                continue
            dedupe_key = str(payload.get("project_number") or payload["project_name"]).casefold()
            if dedupe_key not in seen_keys:
                seen_keys.add(dedupe_key)
                results.append(payload)
            _return_to_results(page, settings)

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
        if not wait_for_results_page_change(
            page, previous_marker, timeout_ms=settings.nav_timeout_ms
        ):
            break
        if is_no_results_page(page):
            break
        page_num += 1
    return results


def _extract_search_row(row) -> dict[str, object] | None:
    cells = row.query_selector_all("td")
    if len(cells) < 6:
        return None
    status_text = cells[4].inner_text().strip()
    if not status_matches_target(status_text):
        return None
    search_name = cells[2].inner_text().strip()
    return {
        "search_name": search_name,
        "project_name": search_name,
        "organization_name": cells[1].inner_text().strip(),
        "source_status_text": status_text,
    }


def open_and_extract_project(
    *,
    page,
    row_index: int,
    keyword: str,
    include_documents: bool = False,
) -> dict[str, object] | None:
    if not navigate_to_project_by_row(page, row_index):
        return None
    _logged_sleep(2)
    if check_has_preliminary_pricing(page):
        return None
    detail = extract_project_info(page)
    project_name = detail.get("project_name") or ""
    organization_name = detail.get("organization") or ""
    if not project_name or not organization_name:
        return None
    proposal_submission_date = _normalize_buddhist_date(detail.get("proposal_submission_date"))
    budget_amount = _normalize_budget(detail.get("budget"))
    project_state = _infer_project_state(
        project_name=project_name, organization_name=organization_name
    )
    downloaded_documents = collect_downloaded_documents(page) if include_documents else []
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
        "downloaded_documents": downloaded_documents,
        "source_status_text": TARGET_STATUS,
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
            "downloaded_documents": [
                {
                    "file_name": document.get("file_name"),
                    "source_label": document.get("source_label"),
                }
                for document in downloaded_documents
            ],
            "source_status_text": TARGET_STATUS,
        },
    }


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
    page = context.pages[0] if context.pages else context.new_page()
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
        return table.query_selector_all("tbody tr")
    except Exception:
        return []


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
        return "ไม่พบข้อมูล" in text or "จำนวนโครงการที่พบ : 0" in text
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


def search_keyword(page, keyword: str, settings: BrowserDiscoverySettings) -> None:
    cloudflare_ok = wait_for_cloudflare(
        page,
        settings.cloudflare_timeout_ms,
        reload_retries=settings.cloudflare_reload_retries,
    )
    if not cloudflare_ok and settings.search_page_recovery_retries > 0:
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
        _logged_sleep(3)
        retry_settings = BrowserDiscoverySettings(
            chrome_path=settings.chrome_path,
            cdp_port=settings.cdp_port,
            nav_timeout_ms=settings.nav_timeout_ms,
            cloudflare_timeout_ms=settings.cloudflare_timeout_ms,
            cloudflare_reload_retries=settings.cloudflare_reload_retries,
            search_page_recovery_retries=settings.search_page_recovery_retries - 1,
            max_pages_per_keyword=settings.max_pages_per_keyword,
            browser_profile_dir=settings.browser_profile_dir,
        )
        search_keyword(page, keyword, retry_settings)
        return
    search_btn = page.query_selector("button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))")
    if not search_btn:
        search_btn = page.wait_for_selector(
            "button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))",
            timeout=settings.nav_timeout_ms,
        )
    search_input = find_search_input(page, search_btn)
    search_input.click()
    search_input.fill("")
    search_input.fill(keyword)
    _logged_sleep(0.5)
    click_search_button(page, search_btn, timeout_ms=settings.nav_timeout_ms)
    wait_for_results_ready(page, settings)


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
            view_btn = cells[5].query_selector("a, button, [role='button'], svg, i")
            if view_btn:
                view_btn.click()
                return True
            cells[5].click()
            return True
        eligible_idx += 1
    return False


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


def _return_to_results(page, settings: BrowserDiscoverySettings) -> None:
    try:
        page.go_back(wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
    except Exception:
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=settings.nav_timeout_ms)
    _logged_sleep(2)
    wait_for_results_ready(page, settings)


def _logged_sleep(seconds: float) -> None:
    time.sleep(seconds)
