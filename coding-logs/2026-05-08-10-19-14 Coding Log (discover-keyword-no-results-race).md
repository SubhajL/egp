# Plan Draft A

## Overview
Stabilize the worker-side e-GP search flow so a transient `ไม่พบข้อมูล` placeholder is not treated as a final empty result set. Then tighten run/UI semantics so ambiguous zero-result crawls are not reported as plain success, and add targeted regression tests around the live race we reproduced for keyword `คลังข้อมูล`.

## Files to Change
- `apps/worker/src/egp_worker/browser_discovery.py`: result readiness, no-results stabilization, debug snapshot emission.
- `apps/worker/src/egp_worker/workflows/discover.py`: run outcome semantics for suspicious zero-result live crawls.
- `apps/web/src/lib/run-progress.ts`: clearer progress/status wording for ambiguous zero-result runs.
- `tests/phase1/test_worker_browser_discovery.py`: browser discovery race regression tests.
- `tests/phase1/test_worker_workflows.py`: workflow-level run outcome tests.

## Implementation Steps
1. TDD sequence
   1) Add worker/browser tests that fail when a placeholder no-results row appears before real rows.
   2) Run those tests and confirm they fail for the current premature no-results behavior.
   3) Implement the smallest worker-side stabilization to pass.
   4) Add/adjust workflow and UI-facing tests for ambiguous zero-result semantics.
   5) Run focused tests, then lint/typecheck/compile gates.
2. `wait_for_results_ready(page, settings)`
   - Replace the current three-poll early-return logic with a bounded settle loop that requires stable no-results before accepting it as final.
   - Keep the fail-closed bias: if the page stays ambiguous, prefer surfacing uncertainty over silently returning zero matches.
3. `search_keyword(page, keyword, settings, ...)`
   - Distinguish between “stable no results” and “transient no-results shell”.
   - Trigger debug snapshot capture before finalizing a no-results outcome.
4. `crawl_live_discovery(...)` no-results branch
   - Carry enough debug/progress context to support downstream run classification.
5. `run_discover_workflow(...)`
   - Mark suspicious live zero-result crawls as `partial`/non-green with an explanatory summary error instead of `succeeded`.
6. `formatRunProgress(...)`
   - Render ambiguous zero-result states in operator-facing wording that implies investigation, not clean success.

## Test Coverage
- `test_wait_for_results_ready_ignores_transient_no_results_placeholder`
  - Does not settle on shell row.
- `test_search_keyword_does_not_finalize_transient_no_results_before_rows`
  - Waits for hydrated result rows.
- `test_search_keyword_logs_debug_snapshot_before_final_no_results`
  - Emits diagnostics for true empty result.
- `test_run_discover_workflow_marks_ambiguous_live_zero_results_partial`
  - Non-green run when live crawl is suspiciously empty.
- `test_format_run_progress_handles_ambiguous_zero_results`
  - UI wording reflects uncertainty.

## Decision Completeness
- Goal: prevent false `keyword_no_results` outcomes and misleading green runs.
- Non-goals: changing business keyword/status matching, adding new crawler features, or broad UI redesign.
- Success criteria:
  - The reproduced transient placeholder case no longer ends `keyword_no_results`.
  - Live empty runs with crawler uncertainty are not plain `succeeded`.
  - Regression tests cover both race and run semantics.
- Public interfaces:
  - No new API routes or DB schema.
  - Run summary JSON may include additional diagnostic/error fields.
- Edge cases / failure modes:
  - True empty result set: fail open to a stable zero-result outcome with debug context.
  - Delayed row hydration: fail closed against premature zero results.
  - Site error toast/network failure: continue surfacing as failed/partial run errors.
- Rollout & monitoring:
  - No feature flag.
  - Watch worker logs for new debug snapshots and compare zero-result rate before/after.
- Acceptance checks:
  - Focused pytest runs for browser discovery/workflow tests pass.
  - Live smoke for keyword `คลังข้อมูล` reaches real rows or a non-green uncertain outcome.

## Dependencies
- Local Playwright/Chrome worker environment for live smoke.
- Existing Postgres/dev stack.

## Validation
- Run targeted pytest files.
- Reproduce the live keyword search against the public site.
- Inspect resulting `crawl_runs.summary_json` and UI progress wording.

## Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Search stabilization | `crawl_live_discovery()` | `apps/worker/src/egp_worker/browser_discovery.py` direct call chain from worker | N/A |
| Zero-result run semantics | `run_discover_workflow()` | `apps/worker/src/egp_worker/main.py:run_worker_job()` | `crawl_runs` summary/status |
| UI progress wording | `formatRunProgress()` | imported by run/dashboard UI consumers | N/A |

# Plan Draft B

## Overview
Minimize behavioral change in the crawler by keeping the existing flow structure but inserting an explicit post-submit “result stabilization” helper that waits for either real rows, a stable no-results state, or a hard timeout. Keep run statuses mostly unchanged, but attach stronger summary diagnostics so the UI can highlight uncertain zero-result outcomes without changing persistence semantics as much.

## Files to Change
- `apps/worker/src/egp_worker/browser_discovery.py`: new stabilization helper and diagnostics.
- `apps/worker/src/egp_worker/workflows/discover.py`: optional summary flag for suspicious zero-result live crawls.
- `apps/web/src/lib/run-progress.ts`: derive investigation wording from summary flag.
- `tests/phase1/test_worker_browser_discovery.py`
- `tests/phase1/test_worker_workflows.py`

## Implementation Steps
1. TDD sequence as above.
2. Add `_wait_for_stable_results_state(...)`
   - Track whether the table ever showed rows after submit.
   - Require consecutive stable no-results observations before final acceptance.
3. Keep `search_keyword()` mostly intact
   - Replace the current immediate `wait_for_results_ready()` call with the new helper.
4. Store a summary flag such as `suspected_results_race=true` when the worker sees an unstable empty state.
5. Leave persisted run status as `succeeded` only when the state is truly stable; otherwise upgrade to `partial`.

## Test Coverage
- Same test families as Draft A, but centered on the helper contract and summary flag propagation.

## Decision Completeness
- Goal: smallest viable fix for transient no-results race.
- Non-goals: revisiting project status filters, pagination logic, or procurement matching.
- Success criteria:
  - Transient placeholder no longer produces immediate `keyword_no_results`.
  - Operator can distinguish suspicious zero-result runs from normal empty searches.
- Public interfaces:
  - No route/schema changes.
  - Additional summary flag only.
- Edge cases / failure modes:
  - True empty pages still complete.
  - If stabilization times out, mark run uncertain rather than silently green.
- Rollout & monitoring:
  - Compare counts of `keyword_no_results` runs before and after.
- Acceptance checks:
  - Focused tests pass.
  - Live smoke against `คลังข้อมูล` no longer short-circuits at `t=0`.

## Dependencies
- Same as Draft A.

## Validation
- Same as Draft A.

## Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Stabilization helper | `search_keyword()` | local call in `browser_discovery.py` | N/A |
| Summary flag propagation | `run_discover_workflow()` | worker main dispatch | `crawl_runs.summary_json` |
| UI wording | `formatRunProgress()` | dashboard/runs pages via shared helper | N/A |

# Unified Execution Plan

## Overview
Implement the narrower Draft B structure, but keep Draft A’s stronger outcome semantics: stabilize the search page before accepting `keyword_no_results`, capture diagnostics when zero results are finalized, and mark suspicious live zero-result runs as non-green. This fixes the confirmed race with minimal churn and gives operators truthful signals when the public site behaves asynchronously.

## Files to Change
- `apps/worker/src/egp_worker/browser_discovery.py`: add stable result/no-result settling and no-results diagnostics.
- `apps/worker/src/egp_worker/workflows/discover.py`: classify suspicious live zero-result runs as non-green with summary error/flag.
- `apps/web/src/lib/run-progress.ts`: surface a clearer investigation-oriented message for uncertain zero-result runs.
- `tests/phase1/test_worker_browser_discovery.py`: regressions for placeholder-then-rows and final no-results diagnostics.
- `tests/phase1/test_worker_workflows.py`: run outcome semantics.

## Implementation Steps
1. TDD sequence
   1) Add browser-discovery tests for transient placeholder no-results and final stable no-results.
   2) Run them red.
   3) Implement worker stabilization and diagnostics.
   4) Add workflow/UI semantic tests and run them red.
   5) Implement run-summary / UI wording changes.
   6) Run focused pytest, compile, ruff, and relevant web checks.
2. Add a result stabilization helper in `browser_discovery.py`
   - Wait for one of three terminal states: visible result rows, stable no-results for consecutive polls, or timeout/uncertain state.
   - Preserve the existing search recovery path but stop treating the first `ไม่พบข้อมูล` render as final.
3. Update `search_keyword()` and the crawl loop
   - Use the stabilization helper after submit.
   - Emit `log_results_debug_snapshot()` before final `keyword_no_results`.
4. Update `run_discover_workflow()`
   - When live discovery ends with zero persisted projects and evidence of unstable/ambiguous zero-result search, mark the run `partial` and record an explanatory summary field.
5. Update UI progress formatting
   - If summary indicates crawler uncertainty, render wording that implies investigation rather than a clean “no results” success.

## Test Coverage
- `test_wait_for_results_ready_ignores_transient_no_results_placeholder`
  - Placeholder row does not terminate search.
- `test_search_keyword_finalizes_only_after_stable_no_results`
  - True empty results still finish.
- `test_search_keyword_logs_debug_snapshot_before_keyword_no_results`
  - Diagnostics captured on final empty outcome.
- `test_run_discover_workflow_marks_uncertain_zero_result_live_run_partial`
  - Suspicious zero-result live run is non-green.
- `test_format_run_progress_surfaces_uncertain_zero_result_state`
  - Operator-facing message is not falsely reassuring.

## Decision Completeness
- Goal: eliminate the confirmed false `keyword_no_results` race and stop reporting those runs as clean success.
- Non-goals:
  - Rewriting the whole crawler
  - Changing procurement target status matching
  - Adding new endpoints or migrations
- Success criteria:
  - The live reproduced `t=0 no results / t=1 rows` pattern no longer terminates the crawl early.
  - Runs with crawler uncertainty and zero projects are not marked plain `succeeded`.
  - Targeted regression tests pass and cover both worker and UI semantics.
- Public interfaces:
  - No API or DB schema changes.
  - `crawl_runs.summary_json` may include new diagnostic fields consumed by the UI.
- Edge cases / failure modes:
  - True empty results: accepted after stable confirmation, with debug snapshot.
  - Delayed hydration: do not finalize until stability threshold is met.
  - Timeout without stable signal: fail closed to `partial`/uncertain summary, not green success.
  - Site toast/network failures: remain failed/partial with explicit error.
- Rollout & monitoring:
  - No flags.
  - Watch worker logs and `crawl_runs.summary_json` for uncertain-zero-result markers.
  - Re-test tenant `lll`, profile `dca2b7a1-12c1-413b-8876-a0e53d915fa4`, keyword `คลังข้อมูล`.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_workflows.py -q`
  - `./.venv/bin/python -m ruff check apps/worker apps/api packages tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_workflows.py`
  - `./.venv/bin/python -m compileall apps/worker/src apps/api/src packages`
  - `cd apps/web && npm run typecheck`
  - Live smoke of the `คลังข้อมูล` query no longer short-circuits at the initial shell row.

## Dependencies
- Playwright + Chrome available locally.
- Local API/worker/web/dev Postgres environment.

## Validation
- Run the focused red/green tests.
- Reproduce the live keyword search and inspect the worker log plus `crawl_runs.summary_json`.
- Confirm UI wording changes on the runs/dashboard surfaces.

## Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Result stabilization helper | `search_keyword()` from `crawl_live_discovery()` | `apps/worker/src/egp_worker/browser_discovery.py` local call chain | N/A |
| No-results diagnostics | `crawl_live_discovery()` `keyword_no_results` branch | `apps/worker/src/egp_worker/browser_discovery.py` | run artifact log only |
| Uncertain zero-result run classification | `run_discover_workflow()` | `apps/worker/src/egp_worker/main.py:run_worker_job()` | `crawl_runs.status`, `crawl_runs.summary_json` |
| UI progress wording | `formatRunProgress()` | imported by runs/dashboard UI helpers | N/A |

## Planning Notes
- Auggie semantic search unavailable; plan is based on direct file inspection + exact-string searches.
- Inspected files:
  - `apps/worker/src/egp_worker/browser_discovery.py`
  - `apps/worker/src/egp_worker/workflows/discover.py`
  - `apps/web/src/lib/run-progress.ts`
  - `tests/phase1/test_worker_browser_discovery.py`
  - `tests/phase1/test_worker_workflows.py`

## 2026-05-08 10:39:32 +0700 Implementation Summary

### Goal
- Fix the confirmed browser-discovery race where the first placeholder `ไม่พบข้อมูล` shell caused `keyword_no_results` before hydrated rows appeared for the same keyword.

### What Changed
- `apps/worker/src/egp_worker/browser_discovery.py`
  - Added explicit search-results settling constants and changed `wait_for_results_ready()` to return a terminal state: `"rows"`, `"no_results"`, or `"unstable_no_results"`.
  - Required `no_results` to stay visible for a stability window before treating it as final.
  - Made `search_keyword()` fail closed on unstable search results, keep the clean-page retry path, and emit `log_results_debug_snapshot()` on both stable and unstable empty outcomes.
- `tests/phase1/test_worker_browser_discovery.py`
  - Added a regression test proving a transient placeholder no-results shell does not terminate the search when rows appear shortly after.
  - Added a regression test proving final stable no-results captures a debug snapshot.
  - Updated older `search_keyword()` tests to the new result-state contract so they model `"rows"` vs `"no_results"` intentionally instead of assuming a `None` return.

### TDD Evidence
- Added/changed tests:
  - `test_wait_for_results_ready_waits_out_transient_no_results_placeholder`
  - `test_search_keyword_logs_debug_snapshot_before_final_no_results`
  - Existing `search_keyword()` retry/recovery tests updated for the new helper contract.
- RED:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -x -q`
  - Initial failures showed older tests still forcing the wrong post-search state, for example `test_search_keyword_preserves_clean_page_retry_after_cloudflare_recovery` expecting a second clean-page retry while its fixture still returned `"rows"`.
- GREEN:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q`
  - `70 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q -k 'search_page_state_error or uses_live_discovery_source_when_projects_missing or persists_live_progress'`
  - `3 passed, 39 deselected`
- `./.venv/bin/python -m ruff check apps/worker/src tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_live_discovery.py`
  - `All checks passed!`
- `./.venv/bin/python -m compileall apps/worker/src`
  - completed successfully

### Wiring Verification Evidence
- Runtime entry point remains `crawl_live_discovery()` in `apps/worker/src/egp_worker/browser_discovery.py`, which calls `search_keyword()` per keyword and only emits `keyword_no_results` after `search_keyword()` returns.
- `search_keyword()` now routes all post-submit settling through `wait_for_results_ready()` and logs diagnostics before final empty-state acceptance.
- No new modules, endpoints, env vars, or schema changes were introduced.

### Behavior Changes And Risks
- Delayed hydration now stays in the polling loop until rows appear or the no-results shell remains stable long enough to trust.
- Ambiguous empty searches now fail closed via `SearchPageStateError` after diagnostics instead of silently succeeding as zero-result runs.
- True stable no-results still remain successful empty searches.

### Follow-ups / Known Gaps
- Auggie semantic search was unavailable (`429 Too Many Requests`), so implementation used direct file inspection plus exact-string searches.
- I did not rerun a full live browser smoke for tenant `lll` after the code fix in this pass; the regression coverage is local-test based.
