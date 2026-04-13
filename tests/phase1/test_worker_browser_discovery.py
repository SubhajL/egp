from __future__ import annotations

from egp_worker.browser_close_check import _find_matching_observation_on_page
from egp_worker.browser_discovery import (
    NEXT_PAGE_SELECTOR,
    BrowserDiscoverySettings,
    click_search_button,
    get_results_page_marker,
    is_no_results_page,
    navigate_to_project_by_row,
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


class FakeHeaderCell:
    def __init__(self, text: str) -> None:
        self._text = text

    def inner_text(self) -> str:
        return self._text


class FakeClickTarget:
    def __init__(self) -> None:
        self.click_calls = 0

    def click(self, timeout=None) -> None:
        self.click_calls += 1


class FakeCell:
    def __init__(
        self, text: str, *, click_target: FakeClickTarget | None = None
    ) -> None:
        self._text = text
        self._click_target = click_target

    def inner_text(self) -> str:
        return self._text

    def query_selector(self, selector: str):
        if self._click_target is None:
            return None
        if selector == "a, button, [role='button'], svg, i":
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
    def __init__(self, tables: list[FakeTable], *, active_page: str = "1") -> None:
        self._tables = tables
        self._active_page = active_page

    def query_selector_all(self, selector: str):
        if selector == "table":
            return self._tables
        return []

    def query_selector(self, selector: str):
        if selector == "li.page-item.active, li.active, .pagination .active":
            return FakeActivePageMarker(self._active_page)
        return None


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


def test_navigate_to_project_by_row_uses_results_table_only() -> None:
    wrong_click = FakeClickTarget()
    expected_click = FakeClickTarget()
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
