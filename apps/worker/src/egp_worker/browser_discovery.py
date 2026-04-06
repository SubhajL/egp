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

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from egp_shared_types.enums import ProcurementType, ProjectState

from .browser_downloads import collect_downloaded_documents
from .profiles import resolve_profile_keywords

MAIN_PAGE_URL = "https://www.gprocurement.go.th/new_index.html"
SEARCH_URL = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement"
TARGET_STATUS = "หนังสือเชิญชวน/ประกาศเชิญชวน"
SKIP_KEYWORDS_IN_PROJECT = ["ทางหลวง", "วิธีคัดเลือก", "บำรุงรักษา"]


@dataclass(frozen=True, slots=True)
class BrowserDiscoverySettings:
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    cdp_port: int = 9222
    nav_timeout_ms: int = 60_000
    cloudflare_timeout_ms: int = 120_000
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
        page.goto(MAIN_PAGE_URL, wait_until="domcontentloaded", timeout=resolved_settings.nav_timeout_ms)
        _logged_sleep(3)
        wait_for_cloudflare(page, resolved_settings.cloudflare_timeout_ms)
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=resolved_settings.nav_timeout_ms)
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
        rows = page.query_selector_all("table tbody tr")
        eligible_rows: list[tuple[int, str]] = []
        for row_index, row in enumerate(rows):
            row_payload = _extract_search_row(row)
            if row_payload is None:
                continue
            if any(blocked in row_payload["project_name"] for blocked in SKIP_KEYWORDS_IN_PROJECT):
                continue
            dedupe_key = str(row_payload.get("project_number") or row_payload["project_name"]).casefold()
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

        next_btn = page.query_selector("a:has-text('ถัดไป'), button:has-text('ถัดไป')")
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
        try:
            page.wait_for_selector("table tbody tr", timeout=settings.nav_timeout_ms)
        except PlaywrightTimeout:
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
    project_state = _infer_project_state(project_name=project_name, organization_name=organization_name)
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


def wait_for_cloudflare(page, timeout_ms: int) -> None:
    start = time.time()
    timeout_s = timeout_ms / 1000
    while time.time() - start < timeout_s:
        search_btn = page.query_selector("button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))")
        if search_btn and search_btn.get_attribute("disabled") is None:
            return
        if not search_btn:
            cf_iframe = page.query_selector("iframe[src*='challenges.cloudflare.com']")
            if not cf_iframe:
                return
        _logged_sleep(2)


def _compact_visible_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def status_matches_target(status_text: str) -> bool:
    return _compact_visible_text(TARGET_STATUS) in _compact_visible_text(status_text)


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


def is_no_results_page(page) -> bool:
    try:
        return bool(
            page.evaluate(
                r"""() => {
                    const table = document.querySelector('table');
                    if (!table) return false;
                    const rows = table.querySelectorAll('tbody tr');
                    if (rows.length > 0) return false;
                    const txt = (table.innerText || '').replace(/\s+/g, ' ').trim();
                    return txt.includes('ไม่พบข้อมูล') || txt.includes('จำนวนโครงการที่พบ : 0');
                }"""
            )
        )
    except Exception:
        return False


def wait_for_results_ready(page, settings: BrowserDiscoverySettings) -> None:
    page.wait_for_selector("table", timeout=settings.nav_timeout_ms)
    try:
        page.wait_for_function(
            r"""() => {
                const table = document.querySelector('table');
                if (!table) return false;
                const rows = table.querySelectorAll('tbody tr');
                if (rows.length > 0) return true;
                const txt = (table.innerText || '').replace(/\s+/g, ' ').trim();
                return txt.includes('ไม่พบข้อมูล') || txt.includes('จำนวนโครงการที่พบ : 0');
            }""",
            timeout=settings.nav_timeout_ms,
        )
    except Exception:
        pass
    for _ in range(3):
        try:
            if page.query_selector("table tbody tr"):
                return
        except Exception:
            pass
        _logged_sleep(1.0)


def search_keyword(page, keyword: str, settings: BrowserDiscoverySettings) -> None:
    wait_for_cloudflare(page, settings.cloudflare_timeout_ms)
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
    search_btn.click()
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
    rows = page.query_selector_all("table tbody tr")
    eligible_idx = 0
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) < 6:
            continue
        if TARGET_STATUS not in cells[4].inner_text().strip():
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
