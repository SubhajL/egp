from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from egp_shared_types.enums import ArtifactBucket, ProcurementType, ProjectState
from egp_worker.browser_close_check import _find_matching_observation_on_page
from egp_worker.browser_discovery import (
    BrowserClosedDuringKeyword,
    BrowserDiscoverySettings,
    LiveDiscoveryPartialError,
    NEXT_PAGE_SELECTOR,
    ResultsPageRecoveryError,
    SearchPageStateError,
    _collect_documents_for_payload,
    _collect_keyword_projects,
    _resolve_results_row_index,
    _run_project_extraction_with_timeout,
    _return_to_results,
    _goto_with_recovery,
    _infer_procurement_type,
    build_results_debug_snapshot,
    click_search_button,
    connect_playwright_to_chrome,
    crawl_live_discovery,
    get_results_rows,
    get_results_page_marker,
    is_no_results_page,
    log_results_debug_snapshot,
    navigate_to_project_by_row,
    open_and_extract_project,
    results_page_marker_changed,
    restore_results_page,
    search_keyword,
    wait_for_cloudflare,
    _wait_for_search_controls_ready,
)


class FakeButton:
    def __init__(self) -> None:
        self.click_calls = 0

    def click(self) -> None:
        self.click_calls += 1


class FakePage:
    def __init__(self, *, evaluate_results: list[object] | None = None) -> None:
        self.evaluate_results = list(evaluate_results or [])
        self.evaluate_calls: list[object] = []
        self.wait_calls: list[tuple[str, int | None]] = []
        self.buttons: list[FakeButton] = []

    def evaluate(self, script, arg=None):
        self.evaluate_calls.append((script, arg))
        if self.evaluate_results:
            result = self.evaluate_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return False

    def wait_for_selector(self, selector: str, timeout: int | None = None):
        self.wait_calls.append((selector, timeout))
        button = FakeButton()
        self.buttons.append(button)
        return button


class FakeCloudflareButton:
    def __init__(self, *, disabled: bool) -> None:
        self.disabled = disabled

    def get_attribute(self, name: str):
        if name == "disabled":
            return "" if self.disabled else None
        return None


class FakeCloudflarePage:
    def __init__(self, *, enabled_after_reload: bool = True) -> None:
        self.enabled_after_reload = enabled_after_reload
        self.reload_calls = 0
        self.goto_calls: list[tuple[str, str | None, int | None]] = []
        self.url = "https://example.test/announcement"

    def query_selector(self, selector: str):
        if "button:has-text('ค้นหา')" in selector:
            disabled = self.reload_calls == 0 or not self.enabled_after_reload
            return FakeCloudflareButton(disabled=disabled)
        if "iframe[src*='challenges.cloudflare.com']" in selector:
            return object()
        return None

    def reload(self, wait_until=None, timeout=None):
        self.reload_calls += 1

    def goto(self, url: str, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        self.reload_calls += 1
        self.url = url


class FakeSearchInput:
    def __init__(self, value: str = "") -> None:
        self._value = value
        self.values: list[str] = []

    def click(self) -> None:
        return None

    def fill(self, value: str) -> None:
        self._value = value
        self.values.append(value)

    def input_value(self) -> str:
        return self._value


class FakeSearchPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str | None, int | None]] = []
        self.url = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement"
        self._button = object()

    def query_selector(self, selector: str):
        if "button:has-text('ค้นหา')" in selector:
            return self._button
        return None

    def wait_for_selector(self, selector: str, timeout: int | None = None):
        if "button:has-text('ค้นหา')" in selector:
            return self._button
        raise AssertionError(f"unexpected selector: {selector}")

    def goto(self, url: str, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url


class FakeSearchRecoveryPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str | None, int | None]] = []
        self.url = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/detail"
        self._button = object()

    def query_selector(self, selector: str):
        if "button:has-text('ค้นหา')" in selector and self.url.endswith("/announcement"):
            return self._button
        return None

    def wait_for_selector(self, selector: str, timeout: int | None = None):
        if "button:has-text('ค้นหา')" not in selector:
            raise AssertionError(f"unexpected selector: {selector}")
        if not self.url.endswith("/announcement"):
            raise AssertionError(
                "search button wait attempted before returning to search page"
            )
        return self._button

    def goto(self, url: str, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url


class FakeGotoPage:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.goto_calls: list[tuple[str, str | None, int | None]] = []
        self.url = "https://example.test/start"

    def goto(self, url: str, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeNextPage:
    def __init__(self, *, pages_to_advance: int) -> None:
        self.remaining_clicks = pages_to_advance

    def query_selector(self, selector: str):
        if selector == NEXT_PAGE_SELECTOR:
            return FakeNextButton(self)
        return None

    def evaluate(self, script, arg=None):
        if hasattr(arg, "click"):
            arg.click()
        return None


class FakeNextButton:
    def __init__(self, page: FakeNextPage) -> None:
        self.page = page

    def is_visible(self) -> bool:
        return self.page.remaining_clicks > 0

    def click(self, timeout=None) -> None:
        self.page.remaining_clicks -= 1


class FakeHeaderCell:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class FakeClickTarget:
    def __init__(self, *, navigate_url: str | None = None) -> None:
        self.click_calls = 0
        self.navigate_url = navigate_url
        self.page = None

    def click(self, timeout=None) -> None:
        self.click_calls += 1
        if self.page is not None and self.navigate_url is not None:
            self.page.url = self.navigate_url


class FakeCell:
    def __init__(
        self,
        text: str,
        *,
        click_target: FakeClickTarget | None = None,
        selector_targets: dict[str, FakeClickTarget] | None = None,
    ) -> None:
        self._text = text
        self._click_target = click_target
        self._selector_targets = dict(selector_targets or {})

    def inner_text(self) -> str:
        return self._text

    def query_selector(self, selector: str):
        if selector in self._selector_targets:
            return self._selector_targets[selector]
        if self._click_target is None:
            return None
        if selector in {
            "a[href]",
            "a",
            "button:not([disabled])",
            "[role='button']",
            "egp-all-button",
            ".btn-icon",
            "svg",
            "i",
            "a, button, [role='button'], svg, i",
        }:
            return self._click_target
        return None

    def click(self) -> None:
        if self._click_target is not None:
            self._click_target.click()


class FakeRow:
    def __init__(self, cells: list[FakeCell]) -> None:
        self._cells = cells

    def query_selector_all(self, selector: str):
        if selector == "td":
            return self._cells
        return []

    def inner_text(self) -> str:
        return " ".join(cell.inner_text() for cell in self._cells)


class FakeTable:
    def __init__(
        self, headers: list[str], rows: list[FakeRow], *, body_text: str | None = None
    ) -> None:
        self._headers = [FakeHeaderCell(header) for header in headers]
        self._rows = rows
        self._body_text = body_text

    def query_selector_all(self, selector: str):
        if selector in (
            "thead th, thead td",
            "th",
            "tr:first-child th, tr:first-child td",
        ):
            return self._headers
        if selector == "tbody tr":
            return self._rows
        return []

    def inner_text(self) -> str:
        if self._body_text is not None:
            return self._body_text
        parts = [header.inner_text() for header in self._headers]
        parts.extend(row.inner_text() for row in self._rows)
        return "\n".join(parts)


class FakeActivePageMarker:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class FakeResultsPage:
    def __init__(
        self,
        tables: list[FakeTable],
        *,
        active_page: str = "1",
        url: str = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement",
    ) -> None:
        self._tables = tables
        self._active_page = active_page
        self.url = url
        for table in self._tables:
            for row in table.query_selector_all("tbody tr"):
                for cell in row.query_selector_all("td"):
                    for selector in (
                        "a[href]",
                        "a",
                        "button:not([disabled])",
                        "[role='button']",
                        "egp-all-button",
                        ".btn-icon",
                        "svg",
                        "i",
                    ):
                        target = cell.query_selector(selector)
                        if isinstance(target, FakeClickTarget):
                            target.page = self

    def query_selector_all(self, selector: str):
        if selector == "table":
            return self._tables
        return []

    def query_selector(self, selector: str):
        if selector == "li.page-item.active, li.active, .pagination .active":
            return FakeActivePageMarker(self._active_page)
        return None

    def inner_text(self, selector: str) -> str:
        if selector != "body":
            raise AssertionError(f"unexpected selector: {selector}")
        return "\n".join(table.inner_text() for table in self._tables)


class FakeReturnToResultsPage:
    def __init__(self, *, go_back_error: Exception | None = None) -> None:
        self.go_back_error = go_back_error
        self.go_back_calls = 0

    def go_back(self, wait_until=None, timeout=None) -> None:
        self.go_back_calls += 1
        if self.go_back_error is not None:
            raise self.go_back_error


class FakeDetailReturnPage:
    def __init__(self) -> None:
        self.url = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/detail"
        self.go_back_calls = 0
        self.main_back_clicks = 0

    def go_back(self, wait_until=None, timeout=None) -> None:
        self.go_back_calls += 1
        raise AssertionError(
            "history back should not be used when main-back button is available"
        )

    def evaluate(self, script, arg=None):
        if "กลับหน้าหลัก" in script:
            self.main_back_clicks += 1
            self.url = "https://process5.gprocurement.go.th/egp-agpc01-web/announcement"
            return True
        return None


class FakeConnectedPage:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeConnectedContext:
    def __init__(self) -> None:
        self.pages = [FakeConnectedPage("stale-page")]
        self.default_timeout: int | None = None
        self.new_page_calls = 0

    def set_default_timeout(self, timeout: int) -> None:
        self.default_timeout = timeout

    def new_page(self):
        self.new_page_calls += 1
        page = FakeConnectedPage(f"fresh-page-{self.new_page_calls}")
        self.pages.append(page)
        return page


class FakeConnectedBrowser:
    def __init__(self, context: FakeConnectedContext) -> None:
        self.contexts = [context]


class FakeConnectedPlaywright:
    def __init__(self, browser: FakeConnectedBrowser) -> None:
        self.chromium = SimpleNamespace(connect_over_cdp=lambda url: browser)


def _results_headers() -> list[str]:
    return [
        "ลำดับ",
        "หน่วยจัดซื้อ",
        "ชื่อโครงการ",
        "วงเงินงบประมาณ (บาท)",
        "สถานะโครงการ",
        "ดูข้อมูล",
    ]


def _results_row(
    *,
    index: str,
    organization: str,
    project_name: str,
    budget: str = "100.00",
    status: str = "หนังสือเชิญชวน/ประกาศเชิญชวน",
    click_target: FakeClickTarget | None = None,
) -> FakeRow:
    return FakeRow(
        [
            FakeCell(index),
            FakeCell(organization),
            FakeCell(project_name),
            FakeCell(budget),
            FakeCell(status),
            FakeCell("ดูข้อมูล", click_target=click_target),
        ]
    )


def test_results_page_marker_changed_detects_active_page_change() -> None:
    previous = {"active_page": "1", "row_count": 12, "row_sample": "a|b|c"}
    current = {"active_page": "2", "row_count": 12, "row_sample": "a|b|c"}

    assert results_page_marker_changed(previous, current) is True


def test_results_page_marker_changed_detects_row_sample_change() -> None:
    previous = {"active_page": "1", "row_count": 12, "row_sample": "a|b|c"}
    current = {"active_page": "1", "row_count": 12, "row_sample": "d|e|f"}

    assert results_page_marker_changed(previous, current) is True


def test_results_page_marker_changed_false_when_same() -> None:
    previous = {"active_page": "1", "row_count": 12, "row_sample": "a|b|c"}
    current = {"active_page": "1", "row_count": 12, "row_sample": "a|b|c"}

    assert results_page_marker_changed(previous, current) is False


def test_click_search_button_uses_dom_fallback_before_direct_click() -> None:
    page = FakePage(evaluate_results=[True])
    stale_button = FakeButton()

    click_search_button(page, stale_button, timeout_ms=1234)

    assert len(page.evaluate_calls) == 1
    assert stale_button.click_calls == 0
    assert page.wait_calls == []


def test_click_search_button_falls_back_to_selector_when_dom_click_fails() -> None:
    page = FakePage(evaluate_results=[False])

    click_search_button(page, None, timeout_ms=4321)

    assert page.wait_calls == [
        ("button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))", 4321)
    ]
    assert page.buttons[0].click_calls == 1


def test_wait_for_cloudflare_reloads_once_and_then_passes(monkeypatch) -> None:
    page = FakeCloudflarePage(enabled_after_reload=True)
    clock = iter([0.0, 0.0, 1.0, 2.0, 2.0])

    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("egp_worker.browser_discovery.time.time", lambda: next(clock))

    assert wait_for_cloudflare(page, timeout_ms=500, reload_retries=1) is True
    assert page.reload_calls == 1


def test_wait_for_search_controls_ready_requires_stable_window(monkeypatch) -> None:
    ready_states = iter([False, True, True, True, True, True])
    current_time = [0.0]

    monkeypatch.setattr(
        "egp_worker.browser_discovery._search_controls_ready",
        lambda page: next(ready_states),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.time.monotonic",
        lambda: current_time[0],
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep",
        lambda seconds: current_time.__setitem__(0, current_time[0] + seconds),
    )

    _wait_for_search_controls_ready(object(), timeout_ms=10_000)

    assert current_time[0] == pytest.approx(2.5)


def test_search_keyword_retries_from_fresh_search_page_after_cloudflare_failure(
    monkeypatch,
) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    cloudflare_results = iter([False, True])
    settings = BrowserDiscoverySettings(
        nav_timeout_ms=60_000,
        cloudflare_timeout_ms=500,
        cloudflare_reload_retries=0,
        search_page_recovery_retries=1,
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: next(cloudflare_results),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(page, "ธรรมาภิบาลข้อมูล", settings)

    assert page.goto_calls == [
        (
            "https://process5.gprocurement.go.th/egp-agpc01-web/announcement",
            "domcontentloaded",
            60_000,
        )
    ]
    assert search_input.values == ["", "ธรรมาภิบาลข้อมูล"]


def test_search_keyword_preserves_clean_page_retry_after_cloudflare_recovery(
    monkeypatch,
) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    cloudflare_results = iter([False, True, True])
    no_results_states = iter([True, False, False])
    goto_calls: list[str] = []
    settings = BrowserDiscoverySettings(
        nav_timeout_ms=60_000,
        cloudflare_timeout_ms=500,
        cloudflare_reload_retries=0,
        search_page_recovery_retries=1,
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: next(cloudflare_results),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: next(no_results_states),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._goto_with_recovery",
        lambda page, url, settings: goto_calls.append(url),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(page, "แพลตฟอร์ม", settings)

    assert goto_calls == [
        "https://process5.gprocurement.go.th/egp-agpc01-web/announcement",
        "https://process5.gprocurement.go.th/egp-agpc01-web/announcement",
    ]
    assert search_input.values == ["", "แพลตฟอร์ม", "", "แพลตฟอร์ม"]


def test_search_keyword_waits_for_controls_to_settle_after_cloudflare(
    monkeypatch,
) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    call_order: list[str] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._wait_for_search_controls_ready",
        lambda page, timeout_ms: call_order.append("settle"),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input",
        lambda page, btn: call_order.append("find_input") or search_input,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(page, "แพลตฟอร์ม", BrowserDiscoverySettings())

    assert call_order[:2] == ["settle", "find_input"]


def test_search_keyword_recovers_from_procurement_detail_page_before_waiting_for_button(
    monkeypatch,
) -> None:
    page = FakeSearchRecoveryPage()
    search_input = FakeSearchInput()
    settings = BrowserDiscoverySettings(
        nav_timeout_ms=60_000,
        cloudflare_timeout_ms=500,
        cloudflare_reload_retries=0,
        search_page_recovery_retries=1,
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(page, "แพลตฟอร์ม", settings)

    assert page.goto_calls == [
        (
            "https://process5.gprocurement.go.th/egp-agpc01-web/announcement",
            "domcontentloaded",
            60_000,
        )
    ]
    assert search_input.values == ["", "แพลตฟอร์ม"]


def test_search_keyword_raises_on_site_error_toast_after_submit(monkeypatch) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: True,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.clear_site_error_toast",
        lambda page: True,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="ระบบเกิดข้อผิดพลาด"):
        search_keyword(
            page,
            "แพลตฟอร์ม",
            BrowserDiscoverySettings(search_page_recovery_retries=0),
        )


def test_search_keyword_retries_site_error_toast_from_clean_page(monkeypatch) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    toast_states = [True, False, False, False]
    goto_calls: list[str] = []

    def has_toast(page) -> bool:
        return toast_states.pop(0) if toast_states else False

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        has_toast,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.clear_site_error_toast",
        lambda page: True,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._goto_with_recovery",
        lambda page, url, settings: goto_calls.append(url),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(
        page,
        "แพลตฟอร์ม",
        BrowserDiscoverySettings(search_page_recovery_retries=1),
    )

    assert len(goto_calls) == 1
    assert search_input.values == ["", "แพลตฟอร์ม", "", "แพลตฟอร์ม"]


def test_search_keyword_rejects_stale_results_after_submit(monkeypatch) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    stale_marker = {"active_page": "2", "row_count": 3, "row_sample": "stale"}

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: stale_marker,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: [object(), object(), object()],
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="did not refresh"):
        search_keyword(page, "แพลตฟอร์ม", BrowserDiscoverySettings())


def test_search_keyword_accepts_same_keyword_unchanged_results(monkeypatch) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput(value="แพลตฟอร์ม")
    same_marker = {"active_page": "1", "row_count": 3, "row_sample": "แพลตฟอร์ม"}

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: same_marker,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: [object(), object(), object()],
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )

    search_keyword(page, "แพลตฟอร์ม", BrowserDiscoverySettings())

    assert search_input.values == ["", "แพลตฟอร์ม"]


def test_search_keyword_accepts_unchanged_results_matching_keyword_rows(
    monkeypatch,
) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    same_marker = {
        "active_page": "1",
        "row_count": 3,
        "row_sample": "1|หน่วยงาน|ประกวดราคาจ้างทำแพลตฟอร์ม|100|ประกาศเชิญชวน",
    }

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: same_marker,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: [object(), object(), object()],
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )

    search_keyword(page, "แพลตฟอร์ม", BrowserDiscoverySettings())

    assert search_input.values == ["", "แพลตฟอร์ม"]


def test_search_keyword_accepts_clean_retry_when_first_page_marker_is_unchanged(
    monkeypatch,
) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    rows_by_phase = iter([[object()], [object()], [object()], [object()]])
    marker_by_phase = iter(
        [
            {"active_page": "1", "row_count": 1, "row_sample": "same-first-page"},
            {"active_page": "1", "row_count": 1, "row_sample": "same-first-page"},
            {"active_page": "1", "row_count": 1, "row_sample": "same-first-page"},
            {"active_page": "1", "row_count": 1, "row_sample": "same-first-page"},
        ]
    )
    goto_calls: list[str] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: next(rows_by_phase),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: next(marker_by_phase),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._goto_with_recovery",
        lambda page, url, settings: goto_calls.append(url),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(
        page,
        "แพลตฟอร์ม",
        BrowserDiscoverySettings(search_page_recovery_retries=1),
    )

    assert len(goto_calls) == 1
    assert search_input.values == ["", "แพลตฟอร์ม", "", "แพลตฟอร์ม"]


def test_search_keyword_retries_stale_results_from_clean_search_page(
    monkeypatch,
) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput()
    rows_by_phase = iter([[object()], [object()], [], [object()]])
    marker_by_phase = iter(
        [
            {"active_page": "1", "row_count": 1, "row_sample": "same"},
            {"active_page": "1", "row_count": 1, "row_sample": "same"},
            {"active_page": "", "row_count": 0, "row_sample": ""},
            {"active_page": "1", "row_count": 1, "row_sample": "same"},
        ]
    )
    goto_calls: list[str] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: next(rows_by_phase),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: next(marker_by_phase),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._goto_with_recovery",
        lambda page, url, settings: goto_calls.append(url),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(
        page,
        "แพลตฟอร์ม",
        BrowserDiscoverySettings(search_page_recovery_retries=1),
    )

    assert len(goto_calls) == 1
    assert search_input.values == ["", "แพลตฟอร์ม", "", "แพลตฟอร์ม"]


def test_search_keyword_retries_same_keyword_no_results_shell_from_clean_search_page(
    monkeypatch,
) -> None:
    page = FakeSearchPage()
    search_input = FakeSearchInput(value="แพลตฟอร์ม")
    same_marker = {"active_page": "1", "row_count": 1, "row_sample": "same-first-page"}
    goto_calls: list[str] = []
    no_results_states = iter([True, False, False])

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda page, timeout_ms, reload_retries=1: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_search_input", lambda page, btn: search_input
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.click_search_button",
        lambda page, btn=None, timeout_ms=None: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: [object()],
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: same_marker,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: next(no_results_states),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._goto_with_recovery",
        lambda page, url, settings: goto_calls.append(url),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    search_keyword(
        page,
        "แพลตฟอร์ม",
        BrowserDiscoverySettings(search_page_recovery_retries=1),
    )

    assert len(goto_calls) == 1
    assert search_input.values == ["", "แพลตฟอร์ม", "", "แพลตฟอร์ม"]


def test_goto_with_recovery_retries_err_aborted_once(monkeypatch) -> None:
    page = FakeGotoPage(
        [
            RuntimeError("Page.goto: net::ERR_ABORTED at https://example.test/main"),
            None,
        ]
    )
    settings = BrowserDiscoverySettings(
        nav_timeout_ms=60_000, search_page_recovery_retries=1
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    _goto_with_recovery(page, "https://example.test/main", settings)

    assert page.goto_calls == [
        ("https://example.test/main", "domcontentloaded", 60_000),
        ("https://example.test/main", "domcontentloaded", 60_000),
    ]


def test_goto_with_recovery_reraises_non_retryable_errors(monkeypatch) -> None:
    page = FakeGotoPage([RuntimeError("boom")])
    settings = BrowserDiscoverySettings(
        nav_timeout_ms=60_000, search_page_recovery_retries=1
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    with pytest.raises(RuntimeError, match="boom"):
        _goto_with_recovery(page, "https://example.test/main", settings)


def test_next_page_selector_includes_known_fallback_variants() -> None:
    assert "a:has-text('ถัดไป')" in NEXT_PAGE_SELECTOR
    assert "button[aria-label='next']" in NEXT_PAGE_SELECTOR
    assert "li.next:not(.disabled) a" in NEXT_PAGE_SELECTOR


def test_connect_playwright_to_chrome_uses_fresh_page_even_when_context_has_stale_tabs(
    monkeypatch,
) -> None:
    context = FakeConnectedContext()
    browser = FakeConnectedBrowser(context)
    pw = FakeConnectedPlaywright(browser)
    settings = BrowserDiscoverySettings(cdp_port=9333, nav_timeout_ms=45_000)

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_local_tcp_listen",
        lambda host, port, timeout_seconds: True,
    )

    connected_browser, page = connect_playwright_to_chrome(pw, settings)

    assert connected_browser is browser
    assert page.name == "fresh-page-1"
    assert context.default_timeout == 45_000
    assert context.new_page_calls == 1


def test_restore_results_page_replays_search_and_advances_pages(monkeypatch) -> None:
    page = FakeNextPage(pages_to_advance=2)
    settings = BrowserDiscoverySettings()
    markers = iter(
        [
            {"active_page": "1", "row_count": 10, "row_sample": "a"},
            {"active_page": "2", "row_count": 10, "row_sample": "b"},
        ]
    )
    search_calls: list[str] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.search_keyword",
        lambda page, keyword, settings: search_calls.append(keyword),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: next(markers),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_page_change",
        lambda page, previous_marker, timeout_ms=None: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    restore_results_page(page, "ระบบวิเคราะห์", 3, settings)

    assert search_calls == ["ระบบวิเคราะห์"]
    assert page.remaining_clicks == 0


def test_get_results_page_marker_uses_procurement_results_table_only() -> None:
    unrelated_table = FakeTable(
        ["หัวข้อ", "ค่า"],
        [FakeRow([FakeCell("noise"), FakeCell("ignore me")])],
    )
    results_table = FakeTable(
        _results_headers(),
        [_results_row(index="1", organization="หน่วยงาน A", project_name="โครงการจริง")],
    )
    page = FakeResultsPage([unrelated_table, results_table], active_page="4")

    marker = get_results_page_marker(page)

    assert marker["active_page"] == "4"
    assert marker["row_count"] == 1
    assert "โครงการจริง" in marker["row_sample"]
    assert "ignore me" not in marker["row_sample"]


def test_is_no_results_page_ignores_unrelated_empty_table() -> None:
    unrelated_empty = FakeTable(["หัวข้อ"], [], body_text="ไม่พบข้อมูล ใน widget อื่น")
    results_table = FakeTable(
        _results_headers(),
        [_results_row(index="1", organization="หน่วยงาน A", project_name="โครงการจริง")],
    )
    page = FakeResultsPage([unrelated_empty, results_table])

    assert is_no_results_page(page) is False


def test_get_results_rows_filters_placeholder_no_results_row() -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [FakeRow([FakeCell("ไม่พบข้อมูล")])],
                body_text="ลำดับ\nหน่วยจัดซื้อ\nชื่อโครงการ\nวงเงินงบประมาณ (บาท)\nสถานะโครงการ\nดูข้อมูล\nไม่พบข้อมูล",
            )
        ]
    )

    assert get_results_rows(page) == []
    assert is_no_results_page(page) is True


def test_navigate_to_project_by_row_uses_results_table_only() -> None:
    wrong_click = FakeClickTarget()
    expected_click = FakeClickTarget(
        navigate_url="https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/good"
    )
    unrelated_table = FakeTable(
        ["หัวข้อ", "ค่า", "อื่น", "อื่น", "อื่น", "ดูข้อมูล"],
        [
            FakeRow(
                [
                    FakeCell("x"),
                    FakeCell("noise"),
                    FakeCell("not a procurement row"),
                    FakeCell("0"),
                    FakeCell("หนังสือเชิญชวน/ประกาศเชิญชวน"),
                    FakeCell("ดูข้อมูล", click_target=wrong_click),
                ]
            )
        ],
    )
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(index="1", organization="หน่วยงาน A", project_name="โครงการ A"),
            _results_row(
                index="2",
                organization="หน่วยงาน B",
                project_name="โครงการ B",
                click_target=expected_click,
            ),
        ],
    )
    page = FakeResultsPage([unrelated_table, results_table])

    assert navigate_to_project_by_row(page, 1) is True
    assert wrong_click.click_calls == 0
    assert expected_click.click_calls == 1


def test_navigate_to_project_by_row_prefers_anchor_target_over_cell_fallback(
    monkeypatch,
) -> None:
    anchor_click = FakeClickTarget(
        navigate_url="https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/abc"
    )
    cell_click = FakeClickTarget(
        navigate_url="https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/bad"
    )
    results_table = FakeTable(
        _results_headers(),
        [
            FakeRow(
                [
                    FakeCell("1"),
                    FakeCell("หน่วยงาน A"),
                    FakeCell("โครงการ A"),
                    FakeCell("100.00"),
                    FakeCell("หนังสือเชิญชวน/ประกาศเชิญชวน"),
                    FakeCell(
                        "ดูข้อมูล",
                        click_target=cell_click,
                        selector_targets={"a[href]": anchor_click, "a": anchor_click},
                    ),
                ]
            )
        ],
    )
    page = FakeResultsPage([results_table])
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    assert navigate_to_project_by_row(page, 0) is True
    assert anchor_click.click_calls == 1
    assert cell_click.click_calls == 0
    assert page.url.endswith("/procurement/abc")


def test_collect_keyword_projects_processes_all_eligible_rows_on_mixed_status_page(
    monkeypatch,
) -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="หน่วยงาน A",
                        project_name="สถานะไม่ตรง",
                        status="จัดทำสัญญา/บริหารสัญญา",
                    ),
                    _results_row(
                        index="2",
                        organization="หน่วยงาน B",
                        project_name="โครงการ A",
                    ),
                    _results_row(
                        index="3",
                        organization="หน่วยงาน C",
                        project_name="โครงการ B",
                    ),
                ],
            )
        ]
    )
    opened_rows: list[int] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        lambda *, page, row_index, keyword, search_name=None, include_documents, source_status_text: (
            opened_rows.append(row_index)
            or {
                "project_name": f"row-{row_index}",
                "project_number": f"EGP-{row_index}",
                "source_status_text": source_status_text,
            }
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        lambda page, settings, keyword, target_page_num, row_marker=None: None,
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ระบบข้อมูล",
        settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
        seen_keys=set(),
        include_documents=False,
    )

    assert opened_rows == [0, 1]
    assert [result["project_name"] for result in results] == ["row-0", "row-1"]


def test_collect_keyword_projects_reopens_reordered_row_by_marker(
    monkeypatch,
) -> None:
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(
                index="1",
                organization="หน่วยงาน A",
                project_name="โครงการ A",
            ),
            _results_row(
                index="2",
                organization="หน่วยงาน B",
                project_name="โครงการ B",
            ),
        ],
    )
    page = FakeResultsPage([results_table])
    opened_targets: list[str] = []
    restore_calls = 0

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        eligible_names: list[str] = []
        for row in page._tables[0].query_selector_all("tbody tr"):
            cells = row.query_selector_all("td")
            if "หนังสือเชิญชวน/ประกาศเชิญชวน" not in cells[4].inner_text():
                continue
            eligible_names.append(cells[2].inner_text())
        project_name = eligible_names[row_index]
        opened_targets.append(project_name)
        return {
            "project_name": project_name,
            "project_number": f"EGP-{project_name}",
            "source_status_text": source_status_text,
        }

    def fake_return_to_results(
        page, settings, keyword, target_page_num, row_marker=None
    ) -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            page._tables[0]._rows = [
                _results_row(
                    index="1",
                    organization="หน่วยงาน B",
                    project_name="โครงการ B",
                ),
                _results_row(
                    index="2",
                    organization="หน่วยงาน A",
                    project_name="โครงการ A",
                ),
            ]

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        fake_return_to_results,
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ระบบข้อมูล",
        settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
        seen_keys=set(),
        include_documents=False,
    )

    assert opened_targets == ["โครงการ A", "โครงการ B"]
    assert [result["project_name"] for result in results] == ["โครงการ A", "โครงการ B"]


def test_collect_keyword_projects_raises_when_marker_missing_after_restore(
    monkeypatch,
) -> None:
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(
                index="1",
                organization="หน่วยงาน A",
                project_name="โครงการ A",
            ),
            _results_row(
                index="2",
                organization="หน่วยงาน B",
                project_name="โครงการ B",
            ),
        ],
    )
    page = FakeResultsPage([results_table])
    restore_calls = 0

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        eligible_names: list[str] = []
        for row in page._tables[0].query_selector_all("tbody tr"):
            cells = row.query_selector_all("td")
            if "หนังสือเชิญชวน/ประกาศเชิญชวน" not in cells[4].inner_text():
                continue
            eligible_names.append(cells[2].inner_text())
        project_name = eligible_names[row_index]
        return {
            "project_name": project_name,
            "project_number": f"EGP-{project_name}",
            "source_status_text": source_status_text,
        }

    def fake_return_to_results(
        page, settings, keyword, target_page_num, row_marker=None
    ) -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            page._tables[0]._rows = [
                _results_row(
                    index="1",
                    organization="หน่วยงาน A",
                    project_name="โครงการ A",
                )
            ]

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        fake_return_to_results,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._results_page_available",
        lambda page, allow_no_results=False: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    with pytest.raises(ResultsPageRecoveryError, match="โครงการ B"):
        _collect_keyword_projects(
            page=page,
            keyword="ระบบข้อมูล",
            settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
            seen_keys=set(),
            include_documents=False,
        )


def test_collect_keyword_projects_continues_after_marker_missing_when_results_page_usable(
    monkeypatch,
) -> None:
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(index="1", organization="หน่วยงาน A", project_name="โครงการ A"),
            _results_row(index="2", organization="หน่วยงาน B", project_name="โครงการ B"),
            _results_row(index="3", organization="หน่วยงาน C", project_name="โครงการ C"),
        ],
    )
    page = FakeResultsPage([results_table])
    opened_targets: list[str] = []
    restore_calls = 0

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        eligible_names: list[str] = []
        for row in page._tables[0].query_selector_all("tbody tr"):
            cells = row.query_selector_all("td")
            if "หนังสือเชิญชวน/ประกาศเชิญชวน" not in cells[4].inner_text():
                continue
            eligible_names.append(cells[2].inner_text())
        project_name = eligible_names[row_index]
        opened_targets.append(project_name)
        return {
            "project_name": project_name,
            "project_number": f"EGP-{project_name}",
            "source_status_text": source_status_text,
        }

    def fake_return_to_results(
        page, settings, keyword, target_page_num, row_marker=None
    ) -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            page._tables[0]._rows = [
                _results_row(
                    index="1", organization="หน่วยงาน A", project_name="โครงการ A"
                ),
                _results_row(
                    index="3", organization="หน่วยงาน C", project_name="โครงการ C"
                ),
            ]

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        fake_return_to_results,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ระบบข้อมูล",
        settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
        seen_keys=set(),
        include_documents=False,
    )

    assert opened_targets == ["โครงการ A", "โครงการ C"]
    assert [result["project_name"] for result in results] == ["โครงการ A", "โครงการ C"]


def test_collect_keyword_projects_continues_after_project_level_restore_error_when_page_usable(
    monkeypatch,
) -> None:
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(index="1", organization="หน่วยงาน A", project_name="โครงการ A"),
            _results_row(index="2", organization="หน่วยงาน B", project_name="โครงการ B"),
        ],
    )
    page = FakeResultsPage([results_table])
    opened_targets: list[str] = []
    restore_calls = 0

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        eligible_names: list[str] = []
        for row in page._tables[0].query_selector_all("tbody tr"):
            cells = row.query_selector_all("td")
            if "หนังสือเชิญชวน/ประกาศเชิญชวน" not in cells[4].inner_text():
                continue
            eligible_names.append(cells[2].inner_text())
        project_name = eligible_names[row_index]
        opened_targets.append(project_name)
        return {
            "project_name": project_name,
            "project_number": f"EGP-{project_name}",
            "source_status_text": source_status_text,
        }

    def fake_return_to_results(
        page, settings, keyword, target_page_num, row_marker=None
    ) -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            raise ResultsPageRecoveryError(
                keyword=keyword,
                target_page_num=target_page_num,
                row_marker=row_marker,
                reason="results row marker missing on current page",
            )

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        fake_return_to_results,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ระบบข้อมูล",
        settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
        seen_keys=set(),
        include_documents=False,
    )

    assert opened_targets == ["โครงการ A", "โครงการ B"]
    assert [result["project_name"] for result in results] == ["โครงการ A", "โครงการ B"]


def test_collect_keyword_projects_continues_after_row_level_site_state_error_when_results_page_usable(
    monkeypatch,
) -> None:
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(index="1", organization="หน่วยงาน A", project_name="โครงการ A"),
            _results_row(index="2", organization="หน่วยงาน B", project_name="โครงการ B"),
        ],
    )
    page = FakeResultsPage([results_table])
    opened_targets: list[str] = []
    restore_markers: list[str] = []

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        eligible_names: list[str] = []
        for row in page._tables[0].query_selector_all("tbody tr"):
            cells = row.query_selector_all("td")
            if "หนังสือเชิญชวน/ประกาศเชิญชวน" not in cells[4].inner_text():
                continue
            eligible_names.append(cells[2].inner_text())
        project_name = eligible_names[row_index]
        opened_targets.append(project_name)
        if project_name == "โครงการ A":
            raise SearchPageStateError("e-GP site error after search results load")
        return {
            "project_name": project_name,
            "project_number": f"EGP-{project_name}",
            "source_status_text": source_status_text,
        }

    def fake_return_to_results(
        page, settings, keyword, target_page_num, row_marker=None
    ) -> None:
        restore_markers.append(str((row_marker or {}).get("project_name") or ""))

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        fake_return_to_results,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._results_page_available",
        lambda page, allow_no_results=False: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ระบบข้อมูล",
        settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
        seen_keys=set(),
        include_documents=False,
    )

    assert opened_targets == ["โครงการ A", "โครงการ B"]
    assert restore_markers == ["โครงการ A", "โครงการ B"]
    assert [result["project_name"] for result in results] == ["โครงการ B"]


def test_collect_keyword_projects_skips_timed_out_project_and_restores_results(
    monkeypatch,
) -> None:
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(index="1", organization="หน่วยงาน A", project_name="โครงการ A"),
            _results_row(index="2", organization="หน่วยงาน B", project_name="โครงการ B"),
        ],
    )
    page = FakeResultsPage([results_table])
    opened_targets: list[str] = []
    restore_markers: list[str] = []

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        eligible_names: list[str] = []
        for row in page._tables[0].query_selector_all("tbody tr"):
            cells = row.query_selector_all("td")
            if "หนังสือเชิญชวน/ประกาศเชิญชวน" not in cells[4].inner_text():
                continue
            eligible_names.append(cells[2].inner_text())
        project_name = eligible_names[row_index]
        opened_targets.append(project_name)
        if project_name == "โครงการ A":
            raise TimeoutError("project detail extraction timed out after 1.0s")
        return {
            "project_name": project_name,
            "project_number": f"EGP-{project_name}",
            "source_status_text": source_status_text,
        }

    def fake_return_to_results(
        page, settings, keyword, target_page_num, row_marker=None
    ) -> None:
        restore_markers.append(str((row_marker or {}).get("project_name") or ""))

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        fake_return_to_results,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ระบบข้อมูล",
        settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
        seen_keys=set(),
        include_documents=True,
    )

    assert opened_targets == ["โครงการ A", "โครงการ B"]
    assert restore_markers == ["โครงการ A", "โครงการ B"]
    assert [result["project_name"] for result in results] == ["โครงการ B"]


def test_collect_keyword_projects_keeps_metadata_when_document_collection_times_out(
    monkeypatch,
) -> None:
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(index="1", organization="หน่วยงาน A", project_name="โครงการ A"),
        ],
    )
    page = FakeResultsPage([results_table])
    include_document_flags: list[bool] = []
    restore_markers: list[str] = []

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        include_document_flags.append(include_documents)
        return {
            "keyword": keyword,
            "project_name": "โครงการ A",
            "organization_name": "หน่วยงาน A",
            "project_number": "EGP-A",
            "proposal_submission_date": "2026-04-10",
            "budget_amount": "1000.00",
            "procurement_type": "consulting",
            "project_state": ProjectState.OPEN_CONSULTING.value,
            "artifact_bucket": ArtifactBucket.NO_ARTIFACT_EVIDENCE.value,
            "downloaded_documents": [],
            "source_status_text": source_status_text,
            "raw_snapshot": {
                "project_name": "โครงการ A",
                "organization_name": "หน่วยงาน A",
                "project_number": "EGP-A",
                "downloaded_documents": [],
                "source_status_text": source_status_text,
                "project_state": ProjectState.OPEN_CONSULTING.value,
                "artifact_bucket": ArtifactBucket.NO_ARTIFACT_EVIDENCE.value,
            },
        }

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            TimeoutError("document collection timed out after 5.0s")
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        lambda page, settings, keyword, target_page_num, row_marker=None: (
            restore_markers.append(str((row_marker or {}).get("project_name") or ""))
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ที่ปรึกษา",
        settings=BrowserDiscoverySettings(
            max_pages_per_keyword=1, project_detail_timeout_s=5
        ),
        seen_keys=set(),
        include_documents=True,
    )

    assert include_document_flags == [False]
    assert restore_markers == ["โครงการ A"]
    assert len(results) == 1
    assert results[0]["project_name"] == "โครงการ A"
    assert results[0]["document_collection_status"] == "timeout"
    assert results[0]["document_collection_reason"] == "document_collection_timeout"
    assert results[0]["downloaded_documents"] == []
    assert results[0]["raw_snapshot"]["document_collection_status"] == "timeout"


def test_collect_documents_for_payload_does_not_use_signal_timeout_wrapper(
    monkeypatch,
) -> None:
    page = SimpleNamespace(inner_text=lambda selector: "รายละเอียดโครงการ")
    payload = {
        "keyword": "แพลตฟอร์ม",
        "project_name": "โครงการ A",
        "organization_name": "หน่วยงาน A",
        "project_number": "EGP-A",
        "project_state": ProjectState.OPEN_INVITATION.value,
        "artifact_bucket": ArtifactBucket.NO_ARTIFACT_EVIDENCE.value,
        "downloaded_documents": [],
        "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
        "raw_snapshot": {
            "project_name": "โครงการ A",
            "organization_name": "หน่วยงาน A",
            "project_number": "EGP-A",
            "project_state": ProjectState.OPEN_INVITATION.value,
            "artifact_bucket": ArtifactBucket.NO_ARTIFACT_EVIDENCE.value,
            "downloaded_documents": [],
        },
    }

    monkeypatch.setattr(
        "egp_worker.browser_discovery._run_project_extraction_with_timeout",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("document collection must not use SIGALRM wrapper")
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda page, source_status_text, source_page_text, project_state: [
            {
                "file_name": "invite.pdf",
                "file_bytes": b"invite",
                "source_label": "ประกาศเชิญชวน",
            }
        ],
    )

    updated = _collect_documents_for_payload(
        page,
        payload=payload,
        keyword="แพลตฟอร์ม",
        timeout_s=5,
    )

    assert updated["document_collection_status"] == "succeeded"
    assert updated["downloaded_documents"] == [
        {
            "file_name": "invite.pdf",
            "file_bytes": b"invite",
            "source_label": "ประกาศเชิญชวน",
        }
    ]


def test_collect_documents_for_payload_marks_zero_documents_as_no_documents(
    monkeypatch,
) -> None:
    page = SimpleNamespace(inner_text=lambda selector: "รายละเอียดโครงการ")
    payload = {
        "keyword": "แพลตฟอร์ม",
        "project_name": "โครงการ A",
        "organization_name": "หน่วยงาน A",
        "project_number": "EGP-A",
        "project_state": ProjectState.OPEN_INVITATION.value,
        "artifact_bucket": ArtifactBucket.NO_ARTIFACT_EVIDENCE.value,
        "downloaded_documents": [],
        "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
        "raw_snapshot": {
            "project_name": "โครงการ A",
            "organization_name": "หน่วยงาน A",
            "project_number": "EGP-A",
            "project_state": ProjectState.OPEN_INVITATION.value,
            "artifact_bucket": ArtifactBucket.NO_ARTIFACT_EVIDENCE.value,
            "downloaded_documents": [],
        },
    }

    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda page, source_status_text, source_page_text, project_state: [],
    )

    updated = _collect_documents_for_payload(
        page,
        payload=payload,
        keyword="แพลตฟอร์ม",
        timeout_s=5,
    )

    assert updated["document_collection_status"] == "no_documents"
    assert updated["document_collection_reason"] == "document_collection_empty"
    assert updated["downloaded_documents"] == []
    assert updated["raw_snapshot"]["document_collection_status"] == "no_documents"
    assert updated["raw_snapshot"]["document_collection_reason"] == "document_collection_empty"


def test_collect_keyword_projects_reaches_next_page_after_row_level_site_state_error(
    monkeypatch,
) -> None:
    page = FakeNextPage(pages_to_advance=1)
    opened_targets: list[str] = []
    rows_by_page = {
        "1": [
            _results_row(index="1", organization="หน่วยงาน A", project_name="โครงการ A"),
        ],
        "2": [
            _results_row(index="1", organization="หน่วยงาน B", project_name="โครงการ B"),
        ],
    }
    page._active_page = "1"

    def fake_get_results_rows(page):
        active_page = getattr(page, "_active_page", "1")
        return list(rows_by_page[active_page])

    def fake_get_results_page_marker(page):
        active_page = getattr(page, "_active_page", "1")
        rows = rows_by_page[active_page]
        return {
            "active_page": active_page,
            "row_count": len(rows),
            "row_sample": rows[0].inner_text() if rows else "",
        }

    def fake_open_and_extract_project(
        *, page, row_index, keyword, search_name=None, include_documents, source_status_text
    ) -> dict[str, object]:
        active_page = getattr(page, "_active_page", "1")
        row = rows_by_page[active_page][row_index]
        project_name = row.query_selector_all("td")[2].inner_text()
        opened_targets.append(f"{active_page}:{project_name}")
        if active_page == "1":
            raise SearchPageStateError("e-GP site error after search results load")
        return {
            "project_name": project_name,
            "project_number": f"EGP-{project_name}",
            "source_status_text": source_status_text,
        }

    def fake_return_to_results(
        page, settings, keyword, target_page_num, row_marker=None
    ) -> None:
        page._active_page = str(target_page_num)

    def fake_wait_for_results_page_change(page, previous_marker, timeout_ms):
        page._active_page = "2"
        return True

    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        fake_get_results_rows,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        fake_get_results_page_marker,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        fake_open_and_extract_project,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        fake_return_to_results,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._results_page_available",
        lambda page, allow_no_results=False: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_page_change",
        fake_wait_for_results_page_change,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: False,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    results = _collect_keyword_projects(
        page=page,
        keyword="ระบบข้อมูล",
        settings=BrowserDiscoverySettings(max_pages_per_keyword=2),
        seen_keys=set(),
        include_documents=False,
    )

    assert opened_targets == ["1:โครงการ A", "2:โครงการ B"]
    assert [result["project_name"] for result in results] == ["โครงการ B"]


def test_collect_keyword_projects_emits_project_callback_before_restore_failure(
    monkeypatch,
) -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="หน่วยงาน A",
                        project_name="โครงการ A",
                    )
                ],
            )
        ]
    )
    emitted: list[dict[str, object]] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        lambda **kwargs: {
            "keyword": "แพลตฟอร์ม",
            "project_name": "โครงการ A",
            "organization_name": "หน่วยงาน A",
            "project_number": "EGP-A",
            "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
        },
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ResultsPageRecoveryError(
                keyword="แพลตฟอร์ม",
                target_page_num=1,
                row_marker={"project_name": "โครงการ A"},
                reason="restore failed",
            )
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._results_page_available",
        lambda page, allow_no_results=True: False,
    )

    with pytest.raises(ResultsPageRecoveryError):
        _collect_keyword_projects(
            page=page,
            keyword="แพลตฟอร์ม",
            settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
            seen_keys=set(),
            include_documents=False,
            project_callback=emitted.append,
        )

    assert [project["project_number"] for project in emitted] == ["EGP-A"]


def test_collect_keyword_projects_restarts_browser_when_restore_hits_site_error(
    monkeypatch,
) -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="หน่วยงาน A",
                        project_name="โครงการ A",
                    )
                ],
            )
        ]
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project", lambda **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SearchPageStateError("e-GP site error after search results load")
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    seen_keys: set[str] = set()

    with pytest.raises(BrowserClosedDuringKeyword) as exc_info:
        _collect_keyword_projects(
            page=page,
            keyword="แพลตฟอร์ม",
            settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
            seen_keys=seen_keys,
            include_documents=False,
        )

    assert exc_info.value.page_num == 1
    assert "e-GP site error" in str(exc_info.value)
    assert "โครงการ a" in seen_keys


def test_collect_keyword_projects_marks_timed_out_row_seen_when_restore_needs_browser_restart(
    monkeypatch,
) -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="หน่วยงาน A",
                        project_name="โครงการ A",
                    )
                ],
            )
        ]
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery.open_and_extract_project",
        lambda **kwargs: (_ for _ in ()).throw(
            TimeoutError("project detail extraction timed out after 1.0s")
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._return_to_results",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            BrowserClosedDuringKeyword(
                page_num=1,
                message="Page.goto: net::ERR_CONNECTION_TIMED_OUT at https://process5.gprocurement.go.th/egp-agpc01-web/announcement",
            )
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )

    seen_keys: set[str] = set()

    with pytest.raises(BrowserClosedDuringKeyword) as exc_info:
        _collect_keyword_projects(
            page=page,
            keyword="แพลตฟอร์ม",
            settings=BrowserDiscoverySettings(max_pages_per_keyword=1),
            seen_keys=seen_keys,
            include_documents=True,
        )

    assert exc_info.value.page_num == 1
    assert "ERR_CONNECTION_TIMED_OUT" in str(exc_info.value)
    assert "โครงการ a" in seen_keys


def test_project_extraction_timeout_interrupts_blocking_action(monkeypatch) -> None:
    monkeypatch.setattr(
        "egp_worker.browser_discovery._can_use_signal_timeout", lambda: True
    )

    with pytest.raises(TimeoutError, match="project detail extraction timed out"):
        _run_project_extraction_with_timeout(
            lambda: time.sleep(1),
            timeout_s=0.01,
            keyword="แพลตฟอร์ม",
            row_marker={"project_name": "โครงการค้าง"},
        )


def test_resolve_results_row_index_uses_project_number_when_available() -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="หน่วยงาน A",
                        project_name=(
                            "ซื้อเครดิตสำหรับแพลตฟอร์ม UP AI Connect ฉบับปรับปรุง "
                            "(เลขที่โครงการ : 69039449432)"
                        ),
                    ),
                    _results_row(
                        index="2",
                        organization="หน่วยงาน B",
                        project_name="โครงการอื่น (เลขที่โครงการ : 69039999999)",
                    ),
                ],
            )
        ]
    )

    resolved = _resolve_results_row_index(
        page,
        {
            "row_marker": {
                "organization_name": "หน่วยงาน A",
                "project_name": "ซื้อเครดิตสำหรับแพลตฟอร์ม UP AI Connect",
                "project_number": "69039449432",
                "budget_text": "450,000.00",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "visible_signature": "stale-signature",
            }
        },
    )

    assert resolved == 0


def test_resolve_results_row_index_uses_single_best_candidate_after_restore() -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="สำนักงานกรมตัวอย่าง",
                        project_name="โครงการ A",
                        budget="100.00",
                    ),
                    _results_row(
                        index="2",
                        organization="หน่วยงานอื่น",
                        project_name="โครงการอื่น",
                        budget="100.00",
                    ),
                ],
            )
        ]
    )

    resolved = _resolve_results_row_index(
        page,
        {
            "row_marker": {
                "organization_name": "กรมตัวอย่าง",
                "project_name": "โครงการ A",
                "budget_text": "100.00",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "visible_signature": "stale-signature",
            }
        },
    )

    assert resolved == 0


def test_resolve_results_row_index_rejects_ambiguous_candidates() -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="สำนักงานกรมตัวอย่าง",
                        project_name="โครงการ A",
                        budget="100.00",
                    ),
                    _results_row(
                        index="2",
                        organization="หน่วยงานร่วม",
                        project_name="โครงการ A",
                        budget="100.00",
                    ),
                ],
            )
        ]
    )

    resolved = _resolve_results_row_index(
        page,
        {
            "row_marker": {
                "organization_name": "กรมตัวอย่าง",
                "project_name": "โครงการ A",
                "budget_text": "100.00",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "visible_signature": "stale-signature",
            }
        },
    )

    assert resolved is None


def test_resolve_results_row_index_rejects_project_name_only_match() -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1",
                        organization="หน่วยงานใหม่",
                        project_name="โครงการ A",
                        budget="999.00",
                    ),
                    _results_row(
                        index="2",
                        organization="หน่วยงานอื่น",
                        project_name="โครงการอื่น",
                        budget="100.00",
                    ),
                ],
            )
        ]
    )

    resolved = _resolve_results_row_index(
        page,
        {
            "row_marker": {
                "organization_name": "กรมตัวอย่าง",
                "project_name": "โครงการ A",
                "budget_text": "100.00",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "visible_signature": "stale-signature",
            }
        },
    )

    assert resolved is None


def test_build_results_debug_snapshot_includes_expected_marker_and_candidate_rows() -> (
    None
):
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1", organization="หน่วยงาน A", project_name="โครงการ A"
                    ),
                    _results_row(
                        index="2", organization="หน่วยงาน B", project_name="โครงการ B"
                    ),
                    _results_row(
                        index="3", organization="หน่วยงาน C", project_name="โครงการ C"
                    ),
                ],
            )
        ],
        active_page="3",
    )

    snapshot = build_results_debug_snapshot(
        page,
        expected_marker={
            "project_name": "โครงการ B",
            "organization_name": "หน่วยงาน B",
            "row_marker": {
                "project_name": "โครงการ B",
                "organization_name": "หน่วยงาน B",
                "budget_text": "100.00",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "visible_signature": "stale-signature",
            },
        },
    )

    assert snapshot["expected_marker"]["project_name"] == "โครงการ B"
    assert snapshot["expected_marker"]["organization_name"] == "หน่วยงาน B"
    assert snapshot["candidate_rows"][0]["project_name"] == "โครงการ B"
    assert (
        snapshot["candidate_rows"][0]["score"] >= snapshot["candidate_rows"][1]["score"]
    )


def test_log_results_debug_snapshot_prints_expected_marker_and_candidate_rows(
    capsys,
) -> None:
    page = FakeResultsPage(
        [
            FakeTable(
                _results_headers(),
                [
                    _results_row(
                        index="1", organization="หน่วยงาน A", project_name="โครงการ A"
                    ),
                    _results_row(
                        index="2", organization="หน่วยงาน B", project_name="โครงการ B"
                    ),
                ],
            )
        ]
    )

    log_results_debug_snapshot(
        page,
        "ระบบข้อมูล",
        "project_restore_skipped:โครงการ B",
        expected_marker={
            "project_name": "โครงการ B",
            "organization_name": "หน่วยงาน B",
            "row_marker": {
                "project_name": "โครงการ B",
                "organization_name": "หน่วยงาน B",
                "budget_text": "100.00",
                "source_status_text": "หนังสือเชิญชวน/ประกาศเชิญชวน",
                "visible_signature": "stale-signature",
            },
        },
    )

    captured = capsys.readouterr().out

    assert "DEBUG expected_marker:" in captured
    assert "project_name=โครงการ B" in captured
    assert "DEBUG candidate1:" in captured
    assert "score=" in captured


def test_close_check_matching_uses_results_table_only() -> None:
    unrelated_table = FakeTable(
        ["หัวข้อ", "ค่า", "อื่น", "อื่น", "อื่น"],
        [
            FakeRow(
                [
                    FakeCell("x"),
                    FakeCell("noise"),
                    FakeCell("project name collision"),
                    FakeCell("0"),
                    FakeCell("สถานะอื่น"),
                ]
            )
        ],
    )
    results_table = FakeTable(
        _results_headers(),
        [
            _results_row(
                index="1",
                organization="หน่วยงาน A",
                project_name="โครงการที่ตรงกัน",
                status="หนังสือเชิญชวน/ประกาศเชิญชวน",
            )
        ],
    )
    page = FakeResultsPage([unrelated_table, results_table])

    match = _find_matching_observation_on_page(
        page,
        project={
            "project_id": "project-1",
            "project_name": "โครงการที่ตรงกัน",
            "project_number": "",
        },
    )

    assert match is not None
    assert match["project_id"] == "project-1"
    assert match["search_name"] == "โครงการที่ตรงกัน"


def test_open_and_extract_project_promotes_state_from_downloaded_artifacts(
    monkeypatch,
) -> None:
    page = object()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row",
        lambda page, row_index: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.check_has_preliminary_pricing", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.extract_project_info",
        lambda page: {
            "project_name": "โครงการระบบข้อมูลกลาง",
            "organization": "กรมตัวอย่าง",
            "project_number": "69010000001",
            "proposal_submission_date": "10/04/2569",
            "budget": "1,000,000.00",
        },
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda page, source_status_text, source_page_text, project_state: [
            {"file_name": "price.zip", "source_label": "ประกาศราคากลาง"},
            {"file_name": "tor.zip", "source_label": "เอกสารประกวดราคา"},
        ],
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="ระบบสารสนเทศ",
        include_documents=True,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
    )

    assert payload is not None
    assert payload["artifact_bucket"] == ArtifactBucket.FINAL_TOR_DOWNLOADED.value
    assert payload["project_state"] == ProjectState.TOR_DOWNLOADED.value


def test_open_and_extract_project_preserves_exact_row_status_text(monkeypatch) -> None:
    page = object()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row",
        lambda page, row_index: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.check_has_preliminary_pricing", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.extract_project_info",
        lambda page: {
            "project_name": "โครงการระบบข้อมูลกลาง",
            "organization": "กรมตัวอย่าง",
            "project_number": "69010000001",
            "proposal_submission_date": "10/04/2569",
            "budget": "1,000,000.00",
        },
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda page, source_status_text, source_page_text, project_state: [],
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="ระบบสารสนเทศ",
        include_documents=True,
        source_status_text="หนังสือเชิญชวน /\n ประกาศเชิญชวน",
    )

    assert payload is not None
    assert payload["source_status_text"] == "หนังสือเชิญชวน /\n ประกาศเชิญชวน"


def test_open_and_extract_project_marks_zero_documents_as_no_documents(
    monkeypatch,
) -> None:
    page = object()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row",
        lambda page, row_index: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.check_has_preliminary_pricing", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.extract_project_info",
        lambda page: {
            "project_name": "โครงการระบบข้อมูลกลาง",
            "organization": "กรมตัวอย่าง",
            "project_number": "69010000001",
            "proposal_submission_date": "10/04/2569",
            "budget": "1,000,000.00",
        },
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda page, source_status_text, source_page_text, project_state: [],
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="ระบบสารสนเทศ",
        include_documents=True,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
    )

    assert payload is not None
    assert payload["document_collection_status"] == "no_documents"
    assert payload["document_collection_reason"] == "document_collection_empty"
    assert payload["raw_snapshot"]["document_collection_status"] == "no_documents"
    assert payload["raw_snapshot"]["document_collection_reason"] == "document_collection_empty"


def test_open_and_extract_project_preserves_row_search_name_when_detail_title_differs(
    monkeypatch,
) -> None:
    page = object()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row",
        lambda page, row_index: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.check_has_preliminary_pricing", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.extract_project_info",
        lambda page: {
            "project_name": "รายละเอียดแพลตฟอร์มข้อมูลสุขภาพ",
            "organization": "กรมตัวอย่าง",
            "project_number": "69010000009",
            "proposal_submission_date": "10/04/2569",
            "budget": "1,000,000.00",
        },
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda page, source_status_text, source_page_text, project_state: [],
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="แพลตฟอร์ม",
        search_name="แพลตฟอร์มข้อมูลสุขภาพ",
        include_documents=True,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
    )

    assert payload is not None
    assert payload["project_name"] == "รายละเอียดแพลตฟอร์มข้อมูลสุขภาพ"
    assert payload["detail_name"] == "รายละเอียดแพลตฟอร์มข้อมูลสุขภาพ"
    assert payload["search_name"] == "แพลตฟอร์มข้อมูลสุขภาพ"


def test_open_and_extract_project_skips_preliminary_pricing_from_source_status(
    monkeypatch,
) -> None:
    page = object()
    extract_calls: list[object] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row",
        lambda page, row_index: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.extract_project_info",
        lambda page: extract_calls.append(page)
        or {
            "project_name": "ควรไม่ถูกอ่าน",
            "organization": "กรมตัวอย่าง",
            "project_number": "69010000010",
            "proposal_submission_date": "10/04/2569",
            "budget": "1,000,000.00",
        },
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="แพลตฟอร์ม",
        include_documents=True,
        source_status_text="สรุปข้อมูลการเสนอราคาเบื้องต้น",
    )

    assert payload is None
    assert extract_calls == []


def test_open_and_extract_project_ignores_detail_page_preliminary_pricing_text_when_row_status_matches_target(
    monkeypatch,
) -> None:
    page = SimpleNamespace(content=lambda: "สรุปข้อมูลการเสนอราคาเบื้องต้น")

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row",
        lambda page, row_index: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.extract_project_info",
        lambda page: {
            "project_name": "โครงการระบบข้อมูลกลาง",
            "organization": "กรมตัวอย่าง",
            "project_number": "69010000011",
            "proposal_submission_date": "10/04/2569",
            "budget": "1,000,000.00",
        },
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda page, source_status_text, source_page_text, project_state: [],
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="แพลตฟอร์ม",
        include_documents=True,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
    )

    assert payload is not None
    assert payload["project_number"] == "69010000011"


def test_open_and_extract_project_rejects_error_detail_pages(monkeypatch) -> None:
    page = SimpleNamespace(
        url="https://process5.gprocurement.go.th/egp-agpc01-web/announcement/procurement/bad",
        inner_text=lambda selector: (
            "ข้อมูลโครงการ\nข้อความปฎิเสธ : E1530 : ค้นหาข้อมูลในฐานข้อมูลไม่พบ"
        ),
    )

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row",
        lambda page, row_index: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.check_has_preliminary_pricing", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.extract_project_info",
        lambda page: {
            "project_name": "ชื่อหน่วยงาน",
            "organization": "วิธีการจัดชื้อจัดจ้าง\t-",
            "project_number": "ชื่อโครงการ",
            "proposal_submission_date": "",
            "budget": "",
        },
    )
    collect_calls: list[object] = []
    monkeypatch.setattr(
        "egp_worker.browser_discovery.collect_downloaded_documents",
        lambda *args, **kwargs: collect_calls.append((args, kwargs)),
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="แพลตฟอร์ม",
        include_documents=True,
        source_status_text="หนังสือเชิญชวน/ประกาศเชิญชวน",
    )

    assert payload is None
    assert collect_calls == []


def test_infer_procurement_type_returns_goods_for_purchase_terms() -> None:
    procurement_type = _infer_procurement_type(
        project_name="จัดซื้อ Smart TV เพื่อห้องประชุม",
        organization_name="กรมตัวอย่าง",
        procurement_method_text="ประกวดราคาอิเล็กทรอนิกส์ (e-bidding)",
    )

    assert procurement_type == ProcurementType.GOODS.value


def test_infer_procurement_type_prefers_consulting_over_goods_terms() -> None:
    procurement_type = _infer_procurement_type(
        project_name="จัดจ้างที่ปรึกษาสำหรับระบบข้อมูลกลาง",
        organization_name="กรมตัวอย่าง",
        procurement_method_text="ประกวดราคาซื้ออุปกรณ์ประกอบโครงการ",
    )

    assert procurement_type == ProcurementType.CONSULTING.value


def test_return_to_results_restores_keyword_and_page_after_navigation_fallback(
    monkeypatch,
) -> None:
    page = FakeReturnToResultsPage(go_back_error=RuntimeError("history lost"))
    settings = BrowserDiscoverySettings()
    search_calls: list[str] = []
    restore_calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.search_keyword",
        lambda page, keyword, settings: search_calls.append(keyword),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.restore_results_page",
        lambda page, keyword, target_page_num, settings: restore_calls.append(
            (keyword, target_page_num)
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_results_table",
        lambda page: object(),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: [object()],
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    _return_to_results(
        page,
        settings,
        keyword="แพลตฟอร์ม",
        target_page_num=3,
        row_marker={"project_name": "โครงการ A"},
    )

    assert page.go_back_calls == 1
    assert search_calls == []
    assert restore_calls == [("แพลตฟอร์ม", 3)]


def test_collect_keyword_projects_raises_partial_on_pagination_site_error_toast(
    monkeypatch,
) -> None:
    page = FakeNextPage(pages_to_advance=2)
    wait_calls: list[object] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows", lambda page: []
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_page_marker",
        lambda page: {"active_page": "1", "row_count": 0, "row_sample": ""},
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_page_change",
        lambda *args, **kwargs: wait_calls.append(args) or True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.has_site_error_toast",
        lambda page: True,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.clear_site_error_toast",
        lambda page: True,
        raising=False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    with pytest.raises(LiveDiscoveryPartialError, match="pagination site error"):
        _collect_keyword_projects(
            page=page,
            keyword="แพลตฟอร์ม",
            settings=BrowserDiscoverySettings(max_pages_per_keyword=5),
            seen_keys=set(),
            include_documents=False,
        )

    assert page.remaining_clicks == 1
    assert wait_calls == []


def test_return_to_results_prefers_main_back_button_from_detail_page(
    monkeypatch,
) -> None:
    page = FakeDetailReturnPage()
    settings = BrowserDiscoverySettings()
    search_calls: list[str] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_results_table",
        lambda page: object() if page.url.endswith("/announcement") else None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.get_results_rows",
        lambda page: [object()] if page.url.endswith("/announcement") else [],
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.search_keyword",
        lambda page, keyword, settings: search_calls.append(keyword),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    _return_to_results(
        page,
        settings,
        keyword="แพลตฟอร์ม",
        target_page_num=2,
        row_marker={"project_name": "โครงการ A"},
    )

    assert page.main_back_clicks == 1
    assert page.go_back_calls == 0
    assert search_calls == []


def test_return_to_results_raises_when_recovery_lands_on_no_results(
    monkeypatch,
) -> None:
    page = FakeReturnToResultsPage(go_back_error=RuntimeError("history lost"))
    settings = BrowserDiscoverySettings()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.search_keyword",
        lambda page, keyword, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.restore_results_page",
        lambda page, keyword, target_page_num, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_results_table",
        lambda page: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    with pytest.raises(ResultsPageRecoveryError, match="แพลตฟอร์ม"):
        _return_to_results(
            page,
            settings,
            keyword="แพลตฟอร์ม",
            target_page_num=3,
            row_marker={"project_name": "โครงการ A"},
        )


def test_return_to_results_escalates_recovery_navigation_transport_failure(
    monkeypatch,
) -> None:
    page = FakeReturnToResultsPage(go_back_error=RuntimeError("history lost"))
    settings = BrowserDiscoverySettings()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.search_keyword",
        lambda page, keyword, settings: (_ for _ in ()).throw(
            RuntimeError(
                "Page.goto: net::ERR_CONNECTION_TIMED_OUT at "
                "https://process5.gprocurement.go.th/egp-agpc01-web/announcement"
            )
        ),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    with pytest.raises(BrowserClosedDuringKeyword) as exc_info:
        _return_to_results(
            page,
            settings,
            keyword="แพลตฟอร์ม",
            target_page_num=1,
            row_marker={"project_name": "โครงการ A"},
        )

    assert exc_info.value.page_num == 1
    assert "ERR_CONNECTION_TIMED_OUT" in str(exc_info.value)


def test_return_to_results_raises_when_results_table_still_missing_after_replay(
    monkeypatch,
) -> None:
    page = FakeReturnToResultsPage(go_back_error=RuntimeError("history lost"))
    settings = BrowserDiscoverySettings()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_results_ready",
        lambda page, settings: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.search_keyword",
        lambda page, keyword, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.restore_results_page",
        lambda page, keyword, target_page_num, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.find_results_table",
        lambda page: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page",
        lambda page: False,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.log_results_debug_snapshot",
        lambda page, keyword, reason, **kwargs: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    with pytest.raises(ResultsPageRecoveryError, match="โครงการ A"):
        _return_to_results(
            page,
            settings,
            keyword="แพลตฟอร์ม",
            target_page_num=3,
            row_marker={"project_name": "โครงการ A"},
        )


def test_crawl_live_discovery_resumes_same_keyword_after_browser_close(
    monkeypatch,
) -> None:
    settings = BrowserDiscoverySettings()
    page = FakeSearchPage()
    browser = SimpleNamespace(close=lambda: None)
    playwright = SimpleNamespace(stop=lambda: None)
    chrome = SimpleNamespace()
    connect_results = iter([(browser, page), (browser, page)])
    collect_calls: list[str] = []

    monkeypatch.setattr(
        "egp_worker.browser_discovery.launch_real_chrome", lambda settings: chrome
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.sync_playwright",
        lambda: SimpleNamespace(start=lambda: playwright),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.connect_playwright_to_chrome",
        lambda pw, settings: next(connect_results),
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.wait_for_cloudflare",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.search_keyword",
        lambda page, keyword, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.clear_search", lambda page, settings: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.is_no_results_page", lambda page: False
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.restore_results_page",
        lambda page, keyword, target_page_num, settings: None,
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery.safe_shutdown", lambda **kwargs: None
    )
    monkeypatch.setattr(
        "egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None
    )

    def fake_collect_keyword_projects(
        *, page, keyword, settings, seen_keys, include_documents, project_callback=None
    ) -> list[dict[str, object]]:
        collect_calls.append(keyword)
        if len(collect_calls) == 1:
            raise BrowserClosedDuringKeyword(page_num=4)
        return [{"project_name": "Recovered", "project_number": "6901"}]

    monkeypatch.setattr(
        "egp_worker.browser_discovery._collect_keyword_projects",
        fake_collect_keyword_projects,
    )

    discovered = crawl_live_discovery(
        keyword="ที่ปรึกษา",
        settings=settings,
        include_documents=False,
    )

    assert collect_calls == ["ที่ปรึกษา", "ที่ปรึกษา"]
    assert discovered == [{"project_name": "Recovered", "project_number": "6901"}]
