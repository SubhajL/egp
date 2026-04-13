## Plan Draft A

### Overview
Port the proven standalone crawler fixes into the worker browser layer with minimal surface area changes. Keep the behavioral change focused on search submission and next-page advancement so discovery and close-check stop breaking on SPA rerenders and pagination transitions.

### Files to Change
- `apps/worker/src/egp_worker/browser_discovery.py`: add shared search/pagination helpers and switch discovery to them.
- `apps/worker/src/egp_worker/browser_close_check.py`: reuse the new helpers for close-check pagination/search.
- `tests/...`: add focused unit tests for helper behavior and module wiring.

### Implementation Steps
1. TDD sequence:
   1) Add helper-level unit tests for next-page selector coverage, page-marker change detection, and search-button fallback behavior.
   2) Run targeted tests and confirm they fail because worker helpers do not exist yet.
   3) Implement the smallest helper set in `browser_discovery.py`.
   4) Rewire discovery and close-check to use them.
   5) Run worker tests and lint.
2. Functions:
- `click_search_button(...)`: DOM-query fallback when a stored handle detaches.
- `get_results_page_marker(...)`: compact page signature from active page + visible rows.
- `results_page_marker_changed(...)`: compare previous/current result-page signatures.
- `wait_for_results_page_change(...)`: wait for actual page transition rather than visible-row selector semantics.
3. Edge cases:
- next button exists but page does not transition
- table attached but not visibly “ready” to Playwright
- search button rerenders between discovery and click

### Test Coverage
- helper detects page-number change
- helper detects row-sample change
- helper returns false when marker unchanged
- search click fallback uses DOM-evaluated click when direct handle fails
- discovery/close-check pagination uses broader selector and transition wait

### Decision Completeness
- Goal: eliminate the known page-1-only failure mode in worker discovery/close-check.
- Non-goals: skip-rule drift, document-label drift, env-based runtime config.
- Success criteria: worker browser paths no longer depend on `wait_for_selector("table tbody tr")` after next-page click; tests cover the new helpers.
- Public interfaces: no API/schema/env changes.
- Failure modes: if next-page transition cannot be proven, stop crawling that keyword/check safely (fail closed).
- Rollout & monitoring: code-only change; monitor live discovery counts/pages seen in next manual run.
- Acceptance checks: targeted pytest green, full relevant worker test subset green, ruff green.

### Dependencies
- Existing worker browser modules and Playwright abstractions.

### Validation
- Unit tests around new helpers plus existing worker workflow tests.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| search/pagination helpers in `browser_discovery.py` | `crawl_live_discovery()` and `_search_and_observe_project()` | direct imports/functions in worker browser modules | N/A |

## Plan Draft B

### Overview
Keep helper count smaller by only introducing one page-transition helper and one search-click helper, leaving most existing discovery flow intact. This minimizes edits but still replaces the brittle waits at both call sites.

### Files to Change
- `apps/worker/src/egp_worker/browser_discovery.py`
- `apps/worker/src/egp_worker/browser_close_check.py`
- `tests/...`

### Implementation Steps
1. Add `click_search_button()` and `wait_for_results_page_change()` with any tiny helper functions they require.
2. Replace direct `search_button.click()` and raw post-pagination waits in both modules.
3. Add regression tests centered on those public helper behaviors.

### Test Coverage
- direct click fallback path
- next-page transition wait path
- no-transition timeout path

### Decision Completeness
- Goal: smallest safe patch for the broken pagination/search interaction.
- Non-goals: broader refactor of crawler-core or document extraction.
- Success criteria: both browser modules stop using the fragile post-click table-row wait.
- Public interfaces: unchanged.
- Failure modes: transition timeout breaks traversal safely.
- Rollout & monitoring: manual live discovery smoke after merge.
- Acceptance checks: targeted pytest + ruff.

### Dependencies
- None beyond current worker modules.

### Validation
- Unit tests plus static inspection of call sites.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| transition wait helper | discovery loop and close-check loop | function call sites in browser modules | N/A |

## Unified Execution Plan

### Overview
Implement the focused helper-based patch from Draft B, but keep Draft A’s stronger test coverage and explicit page-marker helpers so the same logic is shared by discovery and close-check. The goal is a minimal code delta with enough structure to prevent the exact regression class from reappearing.

### Files to Change
- `apps/worker/src/egp_worker/browser_discovery.py`: add `NEXT_PAGE_SELECTOR`, `click_search_button`, result-page marker helpers, and switch discovery/search flows to them.
- `apps/worker/src/egp_worker/browser_close_check.py`: import and reuse `NEXT_PAGE_SELECTOR`, `click_search_button`, `get_results_page_marker`, and `wait_for_results_page_change`.
- `tests/phase1/test_worker_browser_discovery.py` (new): helper-level regression coverage for pagination/search behavior.

### Implementation Steps
1. TDD sequence:
   1) Add `tests/phase1/test_worker_browser_discovery.py` covering the helper contracts.
   2) Run the new test file and confirm RED for missing helpers/imports.
   3) Implement helper functions/constants in `browser_discovery.py`.
   4) Rewire `search_keyword`, `_collect_keyword_projects`, and `_search_and_observe_project`.
   5) Run targeted tests, then fast worker gates.
2. Function names:
- `click_search_button(page, search_btn=None, timeout_ms=None)`: click the active primary search button using DOM evaluation first, then locator fallback.
- `get_results_page_marker(page)`: capture active page text, row count, and a compact row sample.
- `results_page_marker_changed(previous, current)`: pure comparison helper for unit tests.
- `wait_for_results_page_change(page, previous_marker, timeout_ms)`: wait for DOM state change or empty result state.
3. Expected behavior and edge cases:
- Use a broad next-page selector set, not only exact Thai text.
- Treat a page as changed only if active page, row count, or row sample changes.
- On failure to prove transition, stop that traversal safely rather than looping blindly.
- If the search button rerenders, still submit the query.

### Test Coverage
- `test_results_page_marker_changed_detects_active_page_change`: page number transition is recognized.
- `test_results_page_marker_changed_detects_row_sample_change`: content change without page-number text still counts.
- `test_results_page_marker_changed_false_when_same`: unchanged page marker stays false.
- `test_click_search_button_uses_dom_fallback_before_direct_click`: rerender-safe search submit path.
- `test_next_page_selector_includes_fallback_variants`: selector remains broad enough for known site markup.

### Decision Completeness
- Goal: fix the critical worker browser pagination/search robustness gap.
- Non-goals: skip-rule alignment, download-label expansion, env/runtime configurability.
- Success criteria:
  - discovery and close-check no longer call raw `wait_for_selector("table tbody tr")` after next-page click
  - search submission uses the resilient helper path
  - new helper tests exist and pass
- Public interfaces: no endpoint/schema/contract changes.
- Edge cases / failure modes:
  - next button visible but disabled -> stop traversal
  - next button clicked but page marker unchanged -> stop traversal (fail closed)
  - empty result page after transition -> stop traversal
  - detached search button -> retry through DOM-evaluated click
- Rollout & monitoring:
  - no flag needed
  - verify next manual live discovery run sees multi-page traversal again
  - inspect worker logs for page counts/keyword progression
- Acceptance checks:
  - `./.venv/bin/python -m pytest -q tests/phase1/test_worker_browser_discovery.py`
  - `./.venv/bin/python -m pytest -q tests/phase1/test_worker_live_discovery.py`
  - `./.venv/bin/python -m ruff check apps/worker/src/egp_worker tests/phase1/test_worker_browser_discovery.py`

### Dependencies
- Existing worker browser modules and Playwright abstractions; no new packages.

### Validation
- Unit-test helper logic directly.
- Re-run worker live-discovery workflow tests to ensure no orchestration regressions.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `click_search_button` | `search_keyword()` in browser discovery and `_search_and_observe_project()` in close-check | direct call in `browser_discovery.py` / import in `browser_close_check.py` | N/A |
| `get_results_page_marker` + `wait_for_results_page_change` | discovery pagination loop and close-check pagination loop | direct call in `_collect_keyword_projects()` and `_search_and_observe_project()` | N/A |
| `NEXT_PAGE_SELECTOR` | next-page button lookup at runtime | constant in `browser_discovery.py`, imported by close-check | N/A |


## 2026-04-11 09:59 (+07) — Fix worker pagination/search robustness gap

### Goal
- Eliminate the worker crawler's page-1-only failure mode by porting the proven standalone pagination/search hardening into the repo browser layer.

### What changed (by file) and why
- `apps/worker/src/egp_worker/browser_discovery.py`
  - Added `NEXT_PAGE_SELECTOR` so discovery is not limited to exact `ถัดไป` text markup.
  - Added `click_search_button()` to survive SPA rerenders/detached search-button handles.
  - Added `get_results_page_marker()`, `results_page_marker_changed()`, and `wait_for_results_page_change()` so page advancement waits for a real result-page transition instead of visible-row selector semantics.
  - Updated `wait_for_results_ready()` to tolerate tables that are attached but not Playwright-visible yet.
  - Rewired `search_keyword()` and `_collect_keyword_projects()` to use the new helpers.
- `apps/worker/src/egp_worker/browser_close_check.py`
  - Imported and reused the new search/pagination helpers so close-check uses the same hardened behavior as discovery.
- `tests/phase1/test_worker_browser_discovery.py`
  - Added direct unit tests for the new helper contracts and selector coverage.

### TDD evidence
- RED:
  - Command: `./.venv/bin/python -m pytest -q tests/phase1/test_worker_browser_discovery.py`
  - Failure: `ImportError: cannot import name 'NEXT_PAGE_SELECTOR' from 'egp_worker.browser_discovery'`
- GREEN:
  - Command: `./.venv/bin/python -m pytest -q tests/phase1/test_worker_browser_discovery.py`

### Tests run
- `./.venv/bin/python -m pytest -q tests/phase1/test_worker_browser_discovery.py`
  - Result: `6 passed`
- `./.venv/bin/python -m pytest -q tests/phase1/test_worker_live_discovery.py`
  - Result: `19 passed`
- `./.venv/bin/python -m ruff check apps/worker/src/egp_worker tests/phase1/test_worker_browser_discovery.py`
  - Result: passed

### Wiring verification evidence
- Discovery entrypoint `crawl_live_discovery()` still flows through `search_keyword()` and `_collect_keyword_projects()` in `browser_discovery.py`; both now call the new helpers.
- Close-check entrypoint `crawl_live_close_check()` still flows through `_search_and_observe_project()` in `browser_close_check.py`; it now imports and uses the same helpers from `browser_discovery.py`.
- No DB schema or API wiring changed; this is runtime browser-navigation logic only.

### Behavior changes and risk notes
- After clicking next, worker traversal now succeeds only when active page text, row count, or visible row sample changes.
- This is intentionally fail-closed: if the site does not prove a page transition, traversal stops instead of pretending it advanced.
- Search submission now retries via DOM-evaluated click when the stored button handle is stale.

### Follow-ups / known gaps
- Skip-rule drift, document-label drift, and env/runtime configurability remain separate follow-up items.
- There is still no full live browser test harness in the repo; these helpers are covered by focused unit tests plus workflow-level tests.

## Review (2026-04-11 10:22:14) - system

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: standalone e-GP crawler subsystem review (`/Users/subhajlimanond/download/TOR/egp_crawler.py`) against current runtime logs and live diagnostics
- Commands Run: `git rev-parse --show-toplevel`; `git branch --show-current`; `git status --porcelain=v1 | head -n 50`; `git log -n 10 --oneline --decorate`; `sed -n '1,220p' AGENTS.md`; direct `rg`/`sed` inspection of `/Users/subhajlimanond/download/TOR/egp_crawler.py`; targeted log inspection of `/Users/subhajlimanond/OneDrive/Download/TOR/egp_crawler_runtime.log`; live Playwright probes against the e-GP announcement page
- Sources: root `AGENTS.md`; `/Users/subhajlimanond/download/TOR/egp_crawler.py`; `/Users/subhajlimanond/OneDrive/Download/TOR/egp_crawler_runtime.log`; live DOM/request inspection of `https://process5.gprocurement.go.th/egp-agpc01-web/announcement`

### High-Level Assessment
- The standalone crawler is now better on click robustness than the earlier version, but the current search-results interpretation is still structurally wrong for the live announcement page.
- The page renders multiple tables at once, including unrelated TOR/error widgets, while the crawler still uses global selectors such as `document.querySelector('table')` and `page.query_selector_all("table tbody tr")`.
- In live diagnostics, a search for `ระบบคลังข้อมูล` submitted the correct keyword request but the DOM ended on a zero-results state with four tables on the page and only the fourth table being the procurement results widget.
- The crawler logged `rows: 3` because it counted rows across all tables, not because there were three procurement results.
- This mis-scoping contaminates empty-state detection, page markers, row eligibility scans, and likely pagination decisions.
- Cloudflare timeout is a contributing failure amplifier because the crawler currently fails open and continues searching after timeout, but it is not the only issue: even when Cloudflare passed during the live probe, the page interpretation remained wrong.

### Strengths
- Search button clicking is more resilient than before because the script now has a DOM-query fallback instead of relying only on a stale handle.
- Pagination change detection is more thoughtful than the original `wait_for_selector("table tbody tr")` approach.
- The script has useful runtime logging and enough helper structure to support targeted hardening without a rewrite.

### Key Risks / Gaps (severity ordered)
CRITICAL
- Results-table targeting is incorrect throughout the search flow. `is_no_results_page()` and `wait_for_results_ready()` use `document.querySelector('table')`, and `search_keyword()` / the main scan loop use global `table tbody tr` selectors instead of scoping to the procurement results table. Evidence: live DOM for `ระบบคลังข้อมูล` produced four tables, with table 0 containing `E1530`, table 2 containing a separate clarification widget, and table 3 being the real procurement results table. File refs: `/Users/subhajlimanond/download/TOR/egp_crawler.py:770`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:1561`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:1580`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:1684`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:3054`. Observable symptom: the crawler logs `rows: 3` and `Found 0 new eligible projects` even when the manual site shows qualifying rows.
- The row count / empty-state logging is materially misleading. In the live probe, `rows: 3` was just `1 + 0 + 1 + 1` across unrelated tables, while the actual procurement results table had zero rows. This hides the real failure boundary and makes the crawler look partially correct when it is not. File refs: `/Users/subhajlimanond/download/TOR/egp_crawler.py:1684`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:3054`.

HIGH
- Cloudflare handling is fail-open. `wait_for_cloudflare()` prints `WARNING: Cloudflare timeout — continuing anyway` and the crawler proceeds with search/scan logic. The current log shows this on April 11 for both `เทคโนโลยีสารสนเทศ` and `ระบบคลังข้อมูล`. File refs: `/Users/subhajlimanond/download/TOR/egp_crawler.py:1424`; log refs: `/Users/subhajlimanond/OneDrive/Download/TOR/egp_crawler_runtime.log:27224`, `/Users/subhajlimanond/OneDrive/Download/TOR/egp_crawler_runtime.log:27297`. Impact: the script can search in a partially verified session and accept degraded or anti-bot-shaped responses as real results.
- Pagination still relies on global page markers and a global `NEXT_PAGE_SELECTOR`, so even after the recent pagination hardening it can still bind to the wrong table/widget on a multi-table page. File refs: `/Users/subhajlimanond/download/TOR/egp_crawler.py:462`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:770`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:1615`, `/Users/subhajlimanond/download/TOR/egp_crawler.py:3127`. Impact: page 1 only remains plausible even when the click/wait logic itself is sound.
- There is no regression coverage around the live-risk areas: Cloudflare gate behavior, results-table identification, zero-results detection, and multi-table pagination. `test_egp_crawler.py` does not currently cover these helpers. Impact: operator-facing breakage can recur unnoticed.

MEDIUM
- The search request itself appears correct, so the main failure is downstream. A live diagnostic captured `GET .../announcement?budgetYear=2569&announcementTodayFlag=false&keywordSearch=ระบบคลังข้อมูล&page=1`, which means the visible input locator is not the primary bug. That is useful because it narrows the fix surface: focus on session validity and results-table parsing, not the basic input selection.
- The visible keyword field updates, but `keywordSearchModel` remains empty under both `.fill()` and `.type()`. This may be an unused field, but it is a sharp edge worth understanding before more search logic is layered on top.

LOW
- The environment still points downloads to a OneDrive-synced directory, which the root `AGENTS.md` explicitly warns against for browser profiles/temp-like state. That is not the immediate cause of the current miss, but it increases flakiness and recovery risk.

### Nit-Picks / Nitty Gritty
- `rows: {row_count}` should be renamed or redefined to mean “procurement result rows” only; the current number is not actionable.
- `is_no_results_page()` should not treat any first table with `ไม่พบข้อมูล` as authoritative.
- When Cloudflare times out, the script should emit a distinct keyword-level failure state instead of continuing with normal search semantics.

### Tactical Improvements (1–3 days)
1. Introduce a single `find_results_table()` helper that positively identifies the procurement results table by header set (`ลำดับ`, `หน่วยจัดซื้อ`, `ชื่อโครงการ`, `วงเงินงบประมาณ (บาท)`, `สถานะโครงการ`, `ดูข้อมูล`) and scope all row, empty-state, marker, and pagination logic to that table only.
2. Change Cloudflare handling to fail closed for a keyword: if verification does not pass, mark that keyword as blocked/retryable and do not trust page results.
3. Add targeted diagnostics when no eligible rows are found: dump the identified results-table headers, row count, active page, and first 2 row samples.
4. Add tests for multi-table pages, false `ไม่พบข้อมูล` in non-results tables, and page-marker changes scoped to the results table.

### Strategic Improvements (1–6 weeks)
1. Split the standalone crawler into explicit phases with typed interfaces: `session_gate`, `search_submit`, `results_table`, `project_detail`, `downloads`. That would reduce the current entanglement where global DOM helpers are reused across incompatible page widgets.
2. Create a reproducible live-diagnostic mode that records the search request URL, results-table identity, and key DOM snapshots for one keyword. This would reduce future debugging time substantially.

### Big Architectural Changes (only if justified)
- No big architectural change justified yet. The incident is still addressable with scoped DOM/session hardening.

### Open Questions / Assumptions
- Assumption: the manual searches were run against the same budget year (`2569`) and the same announcement page variant.
- Open question: whether the live `E1530`/zero-results response is caused by residual anti-bot gating after Cloudflare, or by application-level behavior differences between manual and automated sessions. The current evidence shows the request is correct but the response differs from manual expectations.

## Implementation (2026-04-11 10:36:59) - standalone-egp-results-table-scoping

### Goal
- Fix the standalone crawler regression where later-page eligible projects could open the wrong page, extract bogus detail fields like `Project: ชื่อหน่วยงาน`, and skip all downloads for real projects such as the `ธรรมาภิบาลข้อมูล` consultant result.

### What Changed
- `/Users/subhajlimanond/download/TOR/egp_crawler.py`
  - Added results-table identification helpers so the crawler now targets the procurement results table by required headers instead of using global `table tbody tr` selectors.
  - Rewired `is_no_results_page()`, `wait_for_results_ready()`, `get_results_page_marker()`, `search_keyword()`, `collect_eligible_project_links()`, the main keyword loop, `navigate_to_project_by_row()`, and `_process_one_project()` to use scoped results rows.
  - Hardened `extract_project_info()` with label-aware line parsing so field headers like `ชื่อหน่วยงาน` no longer get misread as the project name.
  - Added a defensive fallback so `_process_one_project()` falls back to the search-row preview if a parsed project name still looks like a field label.
- `/Users/subhajlimanond/download/TOR/test_egp_crawler.py`
  - Added regression tests for results-table selection on multi-table pages, detail text extraction across broken label/value layouts, and `_process_one_project()` row selection when unrelated tables appear before the actual results table.

### TDD Evidence
- RED:
  - Command: `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "ResultsTableSelection or ExtractProjectInfo or ProcessOneProject"`
  - Failure: `TestExtractProjectInfo.test_skips_following_label_lines_when_extracting_name_and_org` failed because organization extraction still returned the project-name line instead of `สำนักงานกิจการยุติธรรม กรุงเทพมหานคร`.
- GREEN:
  - Command: `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "ResultsTableSelection or ExtractProjectInfo or ProcessOneProject"`
  - Result: `3 passed, 145 deselected`.

### Tests Run
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "ResultsTableSelection or ExtractProjectInfo or ProcessOneProject"` → passed
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py` → `148 passed`
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m ruff check egp_crawler.py test_egp_crawler.py` → passed

### Wiring Verification Evidence
- The main keyword scan in `main()` now uses `get_results_rows(page)` instead of global table rows before building `eligible_indices`.
- `_process_one_project()` now re-queries scoped results rows before clicking the detail button, so row indexes from the keyword loop still line up on later pages.
- `search_keyword()` now reports results-row counts from the scoped procurement table rather than counting unrelated rows from other tables.

### Behavior Changes And Risk Notes
- The crawler now treats only the procurement results table as authoritative for row counts, empty-state detection, and later-page project clicks.
- Live probe after the fix reached the exact `จ้างที่ปรึกษากิจกรรมที่ ๖ ...` project and extracted correct detail fields: project name, organization `สำนักงานคณะกรรมการคุ้มครองข้อมูลส่วนบุคคล`, project number `69049100425`, and budget `2,000,000.00`.
- Live probe on that exact project successfully downloaded `ประกาศเชิญชวน.pdf` and `ประกาศราคากลาง.zip`; `TOR_RESULT` remained `False` because the current page exposed no TOR-like downloadable row, only announcement-related documents.
- Risk: Cloudflare still fails open on timeout in the standalone crawler. This patch fixes the wrong-table / wrong-row bug but does not yet change the Cloudflare policy.

### Follow-Ups / Known Gaps
- Consider changing Cloudflare timeout from fail-open to keyword-level retry/fail-closed.
- Add optional diagnostic logging of results-table headers/row samples when a keyword yields zero eligible projects.
- If operators want announcement-only projects counted differently from TOR availability, the `tor_downloaded` semantics may need to be split from “downloaded any document”.

## Implementation (2026-04-11 10:44:45) - standalone-egp-cloudflare-reload-retry

### Goal
- Change standalone crawler Cloudflare handling so a timeout reloads the page and retries verification instead of immediately falling through.

### What Changed
- `/Users/subhajlimanond/download/TOR/egp_crawler.py`
  - Added `CLOUDFLARE_RELOAD_RETRIES` from `EGP_CLOUDFLARE_RELOAD_RETRIES` with default `1`.
  - Updated `wait_for_cloudflare()` to reload the current page once on timeout, wait briefly, and retry verification before finally continuing.
  - Added a `goto(page.url)` fallback if `page.reload()` itself fails.
- `/Users/subhajlimanond/download/TOR/test_egp_crawler.py`
  - Added regression coverage for the reload-and-pass path and the exhausted-retry path.

### TDD Evidence
- RED:
  - Command: `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "WaitForCloudflare"`
  - Reason: no existing Cloudflare tests; the new cases would have failed before the reload-retry behavior existed.
- GREEN:
  - Command: `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "WaitForCloudflare"`
  - Result: `2 passed, 148 deselected`.

### Tests Run
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "WaitForCloudflare"` → passed
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py` → `150 passed`
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m ruff check egp_crawler.py test_egp_crawler.py` → passed

### Wiring Verification Evidence
- `search_keyword()`, `clear_search()`, and the top-level startup/search-page flow all still call `wait_for_cloudflare()`, so the reload-retry behavior is now active for the same runtime entry points without extra wiring changes.

### Behavior Changes And Risk Notes
- First Cloudflare timeout now triggers a page reload and one retry by default.
- After retries are exhausted, behavior remains fail-open and the crawler continues, matching your request not to fail closed.
- Risk: if Cloudflare is persistently blocking automation, reload may still not recover; it just adds a lightweight recovery step before proceeding.

### Follow-Ups / Known Gaps
- If you want more aggressive recovery later, the next step would be keyword-level retry with a fresh navigation back to the search page instead of a single reload.

## Implementation (2026-04-11 10:50:32) - standalone-egp-fresh-search-retry

### Goal
- After Cloudflare reload recovery is exhausted, reopen the search page and retry the keyword flow once before falling through.

### What Changed
- `/Users/subhajlimanond/download/TOR/egp_crawler.py`
  - Added `SEARCH_PAGE_RECOVERY_RETRIES` from `EGP_SEARCH_PAGE_RECOVERY_RETRIES` with default `1`.
  - Changed `wait_for_cloudflare()` to return `True` on successful clearance/readiness and `False` when recovery is exhausted.
  - Updated `search_keyword()` so a failed Cloudflare recovery now triggers a fresh `SEARCH_URL` navigation plus a single keyword-flow retry.
  - Wired both `CLOUDFLARE_RELOAD_RETRIES` and `SEARCH_PAGE_RECOVERY_RETRIES` into `apply_env_config_overrides()` so `.env` values affect runtime behavior.
- `/Users/subhajlimanond/download/TOR/test_egp_crawler.py`
  - Added a regression test proving `search_keyword()` reopens `SEARCH_URL` and retries the keyword after Cloudflare recovery returns `False`.

### TDD Evidence
- RED:
  - Command: `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "SearchKeyword or WaitForCloudflare"`
  - Reason: the new `search_keyword()` retry-path test would have failed before the fresh-search-page retry logic existed.
- GREEN:
  - Command: `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "SearchKeyword or WaitForCloudflare"`
  - Result: `3 passed, 148 deselected`.

### Tests Run
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py -k "SearchKeyword or WaitForCloudflare"` → passed
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m pytest -q test_egp_crawler.py` → `151 passed`
- `cd /Users/subhajlimanond/download/TOR && ./.venv/bin/python -m ruff check egp_crawler.py test_egp_crawler.py` → passed

### Wiring Verification Evidence
- `search_keyword()` is the runtime entry point for every keyword submission, so the new fresh-search-page retry is active for the main crawl loop without additional caller changes.
- `apply_env_config_overrides()` now updates both Cloudflare recovery knobs, so `.env` changes affect the live crawler after startup configuration is loaded.

### Behavior Changes And Risk Notes
- Recovery order is now: wait for Cloudflare -> reload current page if timeout -> if still blocked, reopen `SEARCH_URL` and retry the keyword once -> if still blocked, proceed with the existing fail-open behavior.
- Risk: this still does not guarantee a valid session if the site is persistently anti-botting the browser, but it gives the search flow one full fresh-page retry before accepting degraded behavior.

### Follow-Ups / Known Gaps
- If this still proves flaky in practice, the next escalation would be a browser/session restart for the current keyword rather than another in-page retry.

## Implementation (2026-04-11 12:05:49) - keyword-ระบบวิเคราะห์-pagination-debug

### Goal
- Diagnose why the standalone crawler was bypassing manual `ระบบวิเคราะห์` matches and harden the runtime path so the real keyword loop reaches later result pages instead of stalling on partial renders or broad table selectors.

### What Changed
- [egp_crawler.py](/Users/subhajlimanond/dev/egp/egp_crawler.py:1410)
  - Added procurement-results-table helpers: `find_results_table()`, `get_results_rows()`, `build_results_debug_snapshot()`, `log_results_debug_snapshot()`, `get_results_page_marker()`, `results_page_marker_changed()`, and `wait_for_results_page_change()`.
  - Changed `is_no_results_page()` to inspect the scoped procurement results table instead of the first generic table on the page.
  - Changed `wait_for_results_ready()` to wait for `table` in `state="attached"` so hidden non-results tables do not block the keyword.
  - Hardened `search_keyword()` row stabilization so it no longer locks in an early partial count like `1` when the page is still expanding to the full `10` visible rows.
  - Rewired the main keyword pagination loop, `collect_eligible_project_links()`, `navigate_to_project_by_row()`, and `_process_one_project()` to use scoped results rows plus marker-based page-change waits.
  - Added keyword-level debug logging when the crawler truly reaches the no-results branch.
- [test_egp_crawler.py](/Users/subhajlimanond/dev/egp/test_egp_crawler.py:1139)
  - Added fake results-page/search-page fixtures plus regressions for debug snapshots, results-page markers, attached-table waits, and delayed full-row stabilization in `search_keyword()`.

### TDD Evidence
- RED:
  - Command: `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k ResultsDebugSnapshot -q`
  - Reason: import failed because `build_results_debug_snapshot` did not exist in the repo copy.
  - Command: `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k WaitForResultsReady -q`
  - Reason: `wait_for_results_ready()` waited on a visible generic `table`, so the new test saw `state=None` instead of `attached`.
  - Command: `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k ResultsPageMarker -q`
  - Reason: import failed because `get_results_page_marker` / `results_page_marker_changed` did not exist yet.
  - Command: `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k "SearchKeyword and full_row_stabilization" -q`
  - Reason: `search_keyword()` reported `rows: 1` for a synthetic `1,1,10,10,10` render sequence instead of waiting for the full result count.
- GREEN:
  - Command: `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -q`
  - Result: `142 passed`.

### Tests Run
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k ResultsDebugSnapshot -q` → passed after helper implementation
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k WaitForResultsReady -q` → passed after attached-table wait change
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k ResultsPageMarker -q` → passed after pagination marker helpers
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k "SearchKeyword and full_row_stabilization" -q` → passed after row-stabilization change
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -q` → `142 passed`

### Wiring Verification Evidence
- The live runtime path `main() -> search_keyword() -> is_no_results_page() / get_results_rows() -> pagination loop -> _process_one_project()` now uses the new scoped results helpers and marker-based page-advance waits.
- A bounded live crawl with `EGP_KEYWORDS='ระบบวิเคราะห์'` and `EGP_MAX_PAGES_PER_KEYWORD=2` now reaches page 2 in the real crawler loop and reports `Found 2 new eligible projects on this page`, matching the manual page-2 screenshots.
- A focused live probe across pages 1-8 found all six manual project IDs in the active results set with `status_ok=True` and `skip_keyword=False`:
  - page 2: `69049021973`, `69029063192`
  - page 4: `69019022697`, `68119275612`
  - page 5: `68129029207`
  - page 8: `68129221581`

### Behavior Changes And Risk Notes
- The crawler no longer aborts `ระบบวิเคราะห์` at the old broad-table wait boundary and no longer settles on an early partial row count during search-result rendering.
- Pagination now waits for the actual results page marker to change instead of blindly waiting for any `table tbody tr`.
- Risk: `wait_for_results_ready()` still uses a generic browser-side `document.querySelector('table')` inside `wait_for_function()`, although the attached-table wait plus scoped row polling now mitigates the failure observed in this debug session.
- During the bounded runtime check, I interrupted the crawl after it proved page-2 eligibility; that run had already saved one file under the temporary debug download area: `.data/kw-debug/download/.../ประกาศราคากลาง.zip`.

### Follow-Ups / Known Gaps
- If the site keeps rendering partial results beyond the current stabilization window, the next hardening step would be to move the `wait_for_function()` logic itself off the generic first-table selector and onto a header-aware results-table probe.

## Implementation (2026-04-11 14:35:19) - consolidate-canonical-crawler-recovery

### Goal
- Stop the standalone TOR script, repo root script, and worker discovery code from drifting on Cloudflare recovery behavior by making the repo root crawler the canonical superset and aligning the worker code with the same recovery contract.

### What Changed
- [egp_crawler.py](/Users/subhajlimanond/dev/egp/egp_crawler.py:225)
  - Added `CLOUDFLARE_RELOAD_RETRIES` and `SEARCH_PAGE_RECOVERY_RETRIES` module defaults plus `EGP_CLOUDFLARE_RELOAD_RETRIES` / `EGP_SEARCH_PAGE_RECOVERY_RETRIES` wiring in `apply_env_config_overrides()`.
  - Changed `wait_for_cloudflare()` to return `bool`, reload once on timeout, and fall back to `page.goto(page.url)` if reload fails.
  - Added `click_search_button()` so search submission survives SPA button rerenders and detached handles.
  - Changed `search_keyword()` to reopen `SEARCH_URL` and retry the keyword flow once after Cloudflare recovery is exhausted, while keeping the newer row-stabilization and pagination fixes from the repo version.
- [test_egp_crawler.py](/Users/subhajlimanond/dev/egp/test_egp_crawler.py:1271)
  - Added root regression tests for Cloudflare reload retry and fresh-search-page retry after Cloudflare exhaustion.
- [browser_discovery.py](/Users/subhajlimanond/dev/egp/apps/worker/src/egp_worker/browser_discovery.py:46)
  - Extended `BrowserDiscoverySettings` with `cloudflare_reload_retries` and `search_page_recovery_retries`.
  - Updated worker `wait_for_cloudflare()` to return `bool` and retry via reload.
  - Updated worker `search_keyword()` to reopen `SEARCH_URL` and retry once when Cloudflare recovery fails.
- [test_worker_browser_discovery.py](/Users/subhajlimanond/dev/egp/tests/phase1/test_worker_browser_discovery.py:44)
  - Added worker regression tests for Cloudflare reload recovery and fresh-search-page retry.

### TDD Evidence
- RED:
  - Command: `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k "WaitForCloudflare or TestSearchKeyword" -q`
  - Reason: before consolidation, the root repo copy had no Cloudflare reload/fresh-search retry coverage and no matching recovery implementation.
- GREEN:
  - Command: `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k "WaitForCloudflare or TestSearchKeyword" -q`
  - Result: `4 passed, 141 deselected`.

### Tests Run
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -k "WaitForCloudflare or TestSearchKeyword" -q` → passed
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q` → `8 passed`
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest test_egp_crawler.py -q` → `145 passed`
- `cd /Users/subhajlimanond/dev/egp && ./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q` → `8 passed`

### Wiring Verification Evidence
- Root runtime path now has the combined behavior:
  - `main()` / `clear_search()` / `search_keyword()` call the new boolean `wait_for_cloudflare()` and inherit reload retry behavior.
  - `search_keyword()` also gets the fresh-search-page retry path before continuing with the repo’s newer results-table and pagination fixes.
- Worker runtime path now matches the same recovery contract:
  - `crawl_live_discovery()` → `search_keyword()` → `wait_for_cloudflare()` uses reload retries and search-page recovery via `BrowserDiscoverySettings`.

### Behavior Changes And Risk Notes
- Canonical crawler behavior now lives in the repo root script: it is the only copy that combines Cloudflare retry, safer search-button clicks, attached-table waits, row stabilization, page-marker pagination, and no-results diagnostics.
- The standalone `/Users/subhajlimanond/download/TOR/egp_crawler.py` is now intentionally behind and should be treated as legacy until either archived or replaced.
- Risk: I did not rerun a full live browser crawl after this consolidation pass because the changes were covered by unit regressions and the earlier live `ระบบวิเคราะห์` runtime verification already proved the repo root script’s pagination path.

### Follow-Ups / Known Gaps
- The next cleanup step is operational, not algorithmic: either delete or archive `/Users/subhajlimanond/download/TOR/egp_crawler.py` after confirming nothing still invokes it directly.

## 2026-04-11 16:56:10 +0700 - Invitation Popup Final TOR Download

### Goal
- Download both draft and final TOR variants.
- Treat public-hearing draft TOR as incomplete so the crawler revisits the project until the final invitation-stage TOR is available.
- Mirror the same invitation-popup behavior in the worker codebase.

### What Changed
- `egp_crawler.py`
  - Added `เอกสารประกวดราคา` to `DOCS_TO_DOWNLOAD`.
  - Split TOR label handling into draft vs final helpers.
  - Changed `download_project_documents()` so draft-only projects remain incomplete and only final TOR availability marks completion.
  - Updated `_download_one_document()` so `ประกาศเชิญชวน` falls through to a related-documents popup/page scan and counts final TOR rows from that listing.
  - Extracted `_download_documents_from_current_view()` so both draft subpages and invitation popups share the same download-table logic.
- `apps/worker/src/egp_worker/browser_downloads.py`
  - Mirrored the same draft/final TOR separation.
  - Added invitation-popup related-documents scanning for final TOR collection.
  - Added direct final-TOR target support on the main related-docs page.
- `test_egp_crawler.py`
  - Added coverage for the final TOR target list, draft-only incomplete semantics, and invitation-popup final TOR counting.
- `tests/phase1/test_worker_browser_downloads.py`
  - Added worker coverage for the final TOR target list and invitation-popup final TOR collection.

### TDD Evidence
- Added/changed tests:
  - `TestProjectDocumentDownloads.test_doc_targets_include_final_tor`
  - `TestProjectDocumentDownloads.test_returns_incomplete_when_only_draft_tor_is_downloaded`
  - `TestProjectDocumentDownloads.test_invitation_popup_counts_final_tor_download`
  - `tests/phase1/test_worker_browser_downloads.py::test_doc_targets_include_final_tor`
  - `tests/phase1/test_worker_browser_downloads.py::test_invitation_popup_collects_final_tor`
- RED:
  - `./.venv/bin/python -m pytest test_egp_crawler.py -q -k "ProjectDocumentDownloads"`
    - Failed because `DOCS_TO_DOWNLOAD` did not include final TOR, draft-only projects still returned complete, and invitation-popup final TOR rows were ignored.
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
    - Failed because the worker downloader also lacked the final TOR target and invitation-popup extraction path.
- GREEN:
  - `./.venv/bin/python -m pytest test_egp_crawler.py -q -k "ProjectDocumentDownloads"`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`

### Tests Run
- `./.venv/bin/python -m pytest test_egp_crawler.py -q` → `148 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_browser_downloads.py -q` → `10 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q -k "downloaded_documents or payload_json_safe"` → `2 passed, 17 deselected`
- `./.venv/bin/ruff check egp_crawler.py apps/worker/src/egp_worker/browser_downloads.py test_egp_crawler.py tests/phase1/test_worker_browser_downloads.py` → `All checks passed`

### Wiring Verification Evidence
- Root crawler path:
  - `_process_one_project()` → `download_project_documents()` → `_download_one_document()` → `_download_documents_from_current_view()` for invitation popup rows and draft subpages.
- Worker path:
  - `open_and_extract_project()` → `collect_downloaded_documents()` → `_download_one_document()` → `_download_documents_from_current_view()`.
  - `run_discover_workflow()` still ingests the collected artifacts through `ingest_downloaded_documents()`.

### Behavior Changes And Risks
- Draft TOR downloads are now preserved without marking the project complete; the crawler should revisit those projects until a final invitation-stage TOR is present.
- Invitation rows that open a related-documents popup/page now download both the invitation artifact and the final `เอกสารประกวดราคา` when present.
- Risk remains label variance: if e-GP introduces a materially different final-TOR label outside the current TOR match terms, it will still need another label expansion.

### Follow-ups / Known Gaps
- The root fallback script still records only `tor_downloaded` in Excel; if you want explicit draft-vs-final reporting there, that needs a schema/export change.
- A live bounded probe against a known project with only invitation-popup final TOR would be the next end-to-end confirmation step.

## Review (2026-04-11 16:56:10 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- egp_crawler.py test_egp_crawler.py apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py | sed -n '1,260p'`; `./.venv/bin/python -m pytest test_egp_crawler.py -q`; `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_browser_downloads.py -q`; `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q -k "downloaded_documents or payload_json_safe"`; `./.venv/bin/ruff check egp_crawler.py apps/worker/src/egp_worker/browser_downloads.py test_egp_crawler.py tests/phase1/test_worker_browser_downloads.py`

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Assumed invitation-popup final TOR rows continue to use labels matched by `is_final_tor_doc_label()` such as `เอกสารประกวดราคา` or equivalent TOR terms.

### Recommended Tests / Validation
- Run one live keyword/project probe where the main related-docs table has `ประกาศเชิญชวน` but no `ร่างเอกสารประกวดราคา`, and confirm the popup path saves the final TOR artifact.
- Run one live public-hearing project probe and confirm the draft TOR is saved while the project remains revisit-eligible until the final TOR appears.

### Rollout Notes
- This is fail-open for document collection on invitation popup rows and fail-closed for completion: projects stay incomplete unless final TOR is found.

## 2026-04-11 17:14:00 +0700 - Live Invitation Popup Validation

### Goal
- Verify on live e-GP data that an invitation-only project with no draft TOR on the main page now reaches the popup/listing path and saves a final TOR artifact.

### What Changed
- No code changes in this step.
- Ran an isolated live probe under a temp download dir, temp Excel path, and temp Chrome profile.

### TDD Evidence
- No RED/GREEN cycle in this step because this was live runtime verification of already-implemented behavior.

### Tests Run
- Live bounded probe using `./.venv/bin/python` with temp env overrides and keyword `ระบบสารสนเทศ`.
- Probe located project `69039116473` (`มหาวิทยาลัยราชภัฏพิบูลสงคราม`) where the main project page had `ประกาศเชิญชวน` and `ประกาศราคากลาง`, but no `ร่างเอกสารประกวดราคา`.
- Probe result: `tor_downloaded = true` and saved `69039116473_09042569.zip` under the temp project folder.
- ZIP inspection showed final invitation-stage package contents including:
  - `doc_146521520065000000_69039116473.pdf`
  - `annoudoc_146521520065000000_69039116473.pdf`
  - `Document Part1.pdf`
  - `Document Part2.pdf`
  - `quotation.pdf`

### Wiring Verification Evidence
- Live path exercised: `download_project_documents()` → `_download_one_document('ประกาศเชิญชวน')` → `_download_documents_from_current_view()` → new-tab save/request fallback.
- Runtime logs confirmed the direct invitation click failed first, then the popup/listing branch handled the artifact successfully.

### Behavior Changes And Risks
- Verified that invitation-only projects can now be marked complete when the popup exposes the final TOR package, even when the main page lacks a draft TOR row.
- Residual risk remains around blob-only viewer tabs where the package is not exposed as a downloadable row or requestable URL.

### Follow-ups / Known Gaps
- Optional next step: add a narrow integration-style fake for the blob-viewer fallback path if we want stronger non-live regression coverage around this exact branch.

## 2026-04-11 17:22:00 +0700 - Blob Viewer Fallback Regression Tests

### Goal
- Add regression coverage for the live blob-viewer/new-tab fallback path in both the root crawler and the worker downloader.

### What Changed
- `test_egp_crawler.py`
  - Added `TestNewTabFallback.test_save_from_new_tab_uses_request_for_blob_viewer`.
  - Introduced lightweight fake response/request/keyboard/viewer-page helpers for the root `_save_from_new_tab()` test seam.
- `tests/phase1/test_worker_browser_downloads.py`
  - Added `test_save_from_new_tab_uses_request_for_blob_viewer`.
  - Added matching fake response/request/keyboard/viewer-page helpers for the worker `_save_from_new_tab()` seam.

### TDD Evidence
- Added/changed tests:
  - `TestNewTabFallback.test_save_from_new_tab_uses_request_for_blob_viewer`
  - `tests/phase1/test_worker_browser_downloads.py::test_save_from_new_tab_uses_request_for_blob_viewer`
- RED:
  - No meaningful RED run for this pass. This was a test-only change capturing behavior already verified live on the fixed implementation; producing a RED would have required intentionally breaking working code.
- GREEN:
  - `./.venv/bin/python -m pytest test_egp_crawler.py -q -k "NewTabFallback or ProjectDocumentDownloads"`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`

### Tests Run
- `./.venv/bin/python -m pytest test_egp_crawler.py -q -k "NewTabFallback or ProjectDocumentDownloads"` → `4 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q` → `3 passed`
- `./.venv/bin/python -m pytest test_egp_crawler.py -q` → `149 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_browser_downloads.py -q` → `11 passed`
- `./.venv/bin/ruff check test_egp_crawler.py tests/phase1/test_worker_browser_downloads.py` → `All checks passed`

### Wiring Verification Evidence
- Root regression covers `_save_from_new_tab()` → `_save_via_request()` → `_infer_document_url_from_page()` when the viewer URL is `blob:` and the embedded source resolves to an allowed e-GP download URL.
- Worker regression covers the same chain in `apps/worker/src/egp_worker/browser_downloads.py`.

### Behavior Changes And Risks
- No runtime behavior change in this pass.
- Regression coverage now locks in the blob-viewer request fallback that was exercised during live validation.

### Follow-ups / Known Gaps
- If we later add richer blob-viewer URL inference, these tests should be expanded to cover `chrome-extension://` PDF viewer URLs as well.
