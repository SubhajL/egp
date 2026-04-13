from __future__ import annotations

from types import SimpleNamespace

from egp_shared_types.enums import ArtifactBucket, ProjectState
from egp_worker.browser_discovery import (
    BrowserClosedDuringKeyword,
    NEXT_PAGE_SELECTOR,
    BrowserDiscoverySettings,
    click_search_button,
    crawl_live_discovery,
    open_and_extract_project,
    restore_results_page,
    results_page_marker_changed,
    search_keyword,
    wait_for_cloudflare,
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
    def __init__(self) -> None:
        self.values: list[str] = []

    def click(self) -> None:
        return None

    def fill(self, value: str) -> None:
        self.values.append(value)


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


def test_next_page_selector_includes_known_fallback_variants() -> None:
    assert "a:has-text('ถัดไป')" in NEXT_PAGE_SELECTOR
    assert "button[aria-label='next']" in NEXT_PAGE_SELECTOR
    assert "li.next:not(.disabled) a" in NEXT_PAGE_SELECTOR


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
        "egp_worker.browser_discovery.get_results_page_marker", lambda page: next(markers)
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


def test_open_and_extract_project_promotes_state_from_downloaded_artifacts(
    monkeypatch,
) -> None:
    page = object()

    monkeypatch.setattr(
        "egp_worker.browser_discovery.navigate_to_project_by_row", lambda page, row_index: True
    )
    monkeypatch.setattr("egp_worker.browser_discovery._logged_sleep", lambda *args, **kwargs: None)
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
        lambda page: [
            {"file_name": "price.zip", "source_label": "ประกาศราคากลาง"},
            {"file_name": "tor.zip", "source_label": "เอกสารประกวดราคา"},
        ],
    )

    payload = open_and_extract_project(
        page=page,
        row_index=0,
        keyword="ระบบสารสนเทศ",
        include_documents=True,
    )

    assert payload is not None
    assert payload["artifact_bucket"] == ArtifactBucket.FINAL_TOR_DOWNLOADED.value
    assert payload["project_state"] == ProjectState.TOR_DOWNLOADED.value


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
    monkeypatch.setattr("egp_worker.browser_discovery.is_no_results_page", lambda page: False)
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
        *, page, keyword, settings, seen_keys, include_documents
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
