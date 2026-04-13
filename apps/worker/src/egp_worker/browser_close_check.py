"""Browser-driven close-check sweep for existing projects."""

from __future__ import annotations

try:
    from playwright.sync_api import sync_playwright
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised in CI import environments without Playwright

    def sync_playwright():
        raise ModuleNotFoundError("playwright is required for live browser close checks")


from .browser_discovery import (
    MAIN_PAGE_URL,
    NEXT_PAGE_SELECTOR,
    SEARCH_URL,
    BrowserDiscoverySettings,
    _logged_sleep,
    click_search_button,
    clear_search,
    connect_playwright_to_chrome,
    find_search_input,
    get_results_page_marker,
    launch_real_chrome,
    pagination_button_is_disabled,
    safe_shutdown,
    wait_for_cloudflare,
    wait_for_results_page_change,
    wait_for_results_ready,
)


def crawl_live_close_check(
    *,
    projects: list[dict[str, object]],
    settings: BrowserDiscoverySettings | None = None,
) -> list[dict[str, object]]:
    resolved_settings = settings or BrowserDiscoverySettings()
    if not projects:
        return []

    pw = None
    browser = None
    chrome_proc = None
    page = None
    observations: list[dict[str, object]] = []
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

        for index, project in enumerate(projects):
            if index > 0:
                clear_search(page, resolved_settings)
            observation = _search_and_observe_project(
                page, project=project, settings=resolved_settings
            )
            if observation is not None:
                observations.append(observation)
        return observations
    finally:
        safe_shutdown(browser=browser, pw=pw, chrome_proc=chrome_proc)


def _search_and_observe_project(
    page, *, project: dict[str, object], settings: BrowserDiscoverySettings
):
    term = str(project.get("project_number") or project.get("project_name") or "").strip()
    if not term:
        return None
    search_button = page.query_selector("button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))")
    if not search_button:
        search_button = page.wait_for_selector(
            "button:has-text('ค้นหา'):not(:has-text('ค้นหาขั้นสูง'))",
            timeout=settings.nav_timeout_ms,
        )
    search_input = find_search_input(page, search_button)
    search_input.click()
    search_input.fill("")
    search_input.fill(term)
    _logged_sleep(0.5)
    click_search_button(page, search_button, timeout_ms=settings.nav_timeout_ms)
    wait_for_results_ready(page, settings)

    page_number = 1
    while page_number <= settings.max_pages_per_keyword:
        match = _find_matching_observation_on_page(page, project=project)
        if match is not None:
            return match
        previous_marker = get_results_page_marker(page)
        next_button = page.query_selector(NEXT_PAGE_SELECTOR)
        if not (next_button and next_button.is_visible()):
            return None
        state = None
        try:
            state = next_button.evaluate(
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
            return None
        try:
            page.evaluate("(el) => el.click()", next_button)
        except Exception:
            try:
                next_button.click(timeout=10_000)
            except Exception:
                return None
        _logged_sleep(3)
        if not wait_for_results_page_change(
            page, previous_marker, timeout_ms=settings.nav_timeout_ms
        ):
            return None
        page_number += 1
    return None


def _find_matching_observation_on_page(
    page, *, project: dict[str, object]
) -> dict[str, object] | None:
    expected_number = str(project.get("project_number") or "").strip()
    expected_name = str(project.get("project_name") or "").strip()
    for row in page.query_selector_all("table tbody tr"):
        cells = row.query_selector_all("td")
        if len(cells) < 5:
            continue
        search_name = cells[2].inner_text().strip()
        status_text = cells[4].inner_text().strip()
        if expected_number and expected_number in row.inner_text():
            return {
                "project_id": str(project["project_id"]),
                "source_status_text": status_text,
                "search_name": search_name,
                "raw_snapshot": {
                    "project_number": expected_number,
                    "project_name": expected_name,
                    "search_name": search_name,
                    "source_status_text": status_text,
                },
            }
        if expected_name and expected_name in search_name:
            return {
                "project_id": str(project["project_id"]),
                "source_status_text": status_text,
                "search_name": search_name,
                "raw_snapshot": {
                    "project_number": expected_number,
                    "project_name": expected_name,
                    "search_name": search_name,
                    "source_status_text": status_text,
                },
            }
    return None
