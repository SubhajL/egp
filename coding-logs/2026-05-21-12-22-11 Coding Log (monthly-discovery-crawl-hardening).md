# Monthly Discovery Crawl Hardening

## Planning (2026-05-21 12:22:11 +0700)

Auggie semantic search unavailable: `mcp__auggie_mcp__codebase-retrieval` returned HTTP 429 twice. Plan is based on direct file inspection plus exact-string searches. Inspected files: `AGENTS.md`, `apps/worker/AGENTS.md`, `packages/AGENTS.md`, `packages/db/AGENTS.md`, `apps/worker/src/egp_worker/workflows/discover.py`, `apps/worker/src/egp_worker/browser_discovery.py`, `apps/worker/src/egp_worker/main.py`, `apps/worker/src/egp_worker/scheduler.py`, `tests/phase1/test_worker_live_discovery.py`, and current `git diff --name-only/--stat`.

### Plan Draft A

#### Overview
Make live discovery fail closed when the crawler proves it did not process real eligible results. Keep the existing monthly entitlement/UI working-tree changes and add focused worker hardening so scheduled/monthly live crawls cannot finish as successful after `keyword_no_results` or dropped eligible detail rows.

#### Files to Change
- `apps/worker/src/egp_worker/workflows/discover.py`: track live crawl anomaly progress events and include them in run status/summary.
- `tests/phase1/test_worker_live_discovery.py`: add regression tests for `keyword_no_results` with zero persisted projects and `project_detail_invalid` while processing eligible rows.
- Existing local entitlement/UI files: preserve and include in the final PR; no extra changes expected unless tests reveal breakage.

#### Implementation Steps
1. Add failing tests in `tests/phase1/test_worker_live_discovery.py`.
2. Run the focused tests and confirm they fail because runs still finish `succeeded`.
3. Add small anomaly tracking helpers in `discover.py`:
   - `_live_progress_is_crawl_anomaly(event)`: returns true for stages that mean an eligible crawl path was unreliable.
   - `_build_live_crawl_anomaly_error(anomaly_count, latest_event)`: returns a stable summary error string.
   - `_record_live_progress(event)`: stores latest progress and increments anomaly counters.
4. Final status selection: if a live run has anomalies, mark `partial` when projects were persisted and `failed` when no projects were persisted.
5. Run focused tests, then worker ruff/compile gates and the already-touched entitlement tests.

#### Test Coverage
- `test_run_discover_workflow_marks_live_keyword_no_results_as_failed`: zero-project live no-results cannot succeed.
- `test_run_discover_workflow_marks_invalid_live_detail_as_failed`: eligible detail invalid cannot be silently dropped.
- Existing live partial/error tests: protect current exception behavior.

#### Decision Completeness
- Goal: monthly/scheduled live discovery must surface crawl anomalies instead of reporting false success.
- Non-goals: no browser selector rewrite, no DB schema change, no entitlement/UI redesign beyond existing local changes.
- Success criteria: focused worker tests fail before implementation and pass after; monthly entitlement/API/web tests still pass.
- Public interfaces: no API, CLI, env var, migration, or message schema changes. Run `summary_json` gains `live_crawl_anomaly_count`, `live_crawl_latest_anomaly`, and `error` for anomalous live runs.
- Edge cases / failure modes: fail closed for anomaly stages; keep non-live seeded zero-project runs unchanged; keep partial status when valid projects were persisted before an anomaly.
- Rollout & monitoring: watch failed/partial scheduled runs and `summary_json.error`; no feature flag or migration needed.
- Acceptance checks: focused pytest for live discovery, worker ruff/compile, existing monthly entitlement/API/web tests.

#### Dependencies
Existing repo Python environment and Node app dependencies.

#### Validation
Run the focused tests first, then relevant worker and entitlement/web gates before PR submission.

#### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Live anomaly tracking in `discover.py` | `run_worker_job()` discover command calls `run_discover_workflow()` | `apps/worker/src/egp_worker/main.py` imports workflow directly | `crawl_runs.summary_json` existing JSON field |
| Live progress events | `crawl_live_discovery(... progress_callback=_record_live_progress)` | `apps/worker/src/egp_worker/workflows/discover.py` live branch | N/A |

### Plan Draft B

#### Overview
Push anomaly classification down into `browser_discovery.py` by raising a typed exception for `keyword_no_results` and `project_detail_invalid`. Let `run_discover_workflow` reuse existing exception handling to fail or partially complete the run.

#### Files to Change
- `apps/worker/src/egp_worker/browser_discovery.py`: add/raise typed anomaly exceptions.
- `apps/worker/src/egp_worker/workflows/discover.py`: catch typed anomaly exceptions.
- `tests/phase1/test_worker_browser_discovery.py` and `tests/phase1/test_worker_live_discovery.py`: broader tests for browser and workflow behavior.

#### Implementation Steps
1. Add tests for browser exception raising and workflow status mapping.
2. Raise a new `LiveDiscoveryAnomalyError` from browser paths.
3. Catch it in the workflow and map to failed/partial run states.
4. Refactor existing partial error handling only if necessary.
5. Run browser and workflow test suites.

#### Test Coverage
- Browser no-results typed error: no-results raises anomaly.
- Browser invalid detail typed error: invalid detail raises anomaly.
- Workflow anomaly mapping: failed/partial status behavior.

#### Decision Completeness
- Goal: prevent false success by making anomalies explicit browser failures.
- Non-goals: no schema/API/env changes, no UI changes.
- Success criteria: anomalies are exceptions and run statuses reflect them.
- Public interfaces: internal Python exception type only.
- Edge cases / failure modes: risk of stopping on one no-results keyword in multi-keyword profile before trying later keywords.
- Rollout & monitoring: same as Draft A.
- Acceptance checks: broader worker browser tests plus workflow tests.

#### Dependencies
Playwright-adjacent test doubles may need updates.

#### Validation
Run browser-discovery and workflow tests.

#### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `LiveDiscoveryAnomalyError` | `crawl_live_discovery()` | Imported/caught by `run_discover_workflow()` | N/A |

### Comparative Analysis

Draft A is smaller and preserves browser crawling behavior: it observes progress events already emitted by the browser layer and changes only run classification. It has lower risk for multi-keyword profiles because the crawler can continue after one no-results keyword while the run still records the anomaly.

Draft B makes anomalies stronger at the source but changes browser control flow and risks aborting later keywords. It also requires more browser-level tests for the same production outcome.

Both drafts keep PostgreSQL as source of truth, avoid schema changes, and follow the worker convention of keeping orchestration in workflow modules. Draft A is the preferred implementation because it fixes the false-success reporting with the smallest runtime blast radius.

### Unified Execution Plan

#### Overview
Implement Draft A. The workflow will treat live progress stages that indicate unreliable discovery as crawl anomalies, include structured anomaly metadata in `crawl_runs.summary_json`, and mark anomalous live runs as `failed` or `partial` rather than `succeeded`.

#### Files to Change
- `apps/worker/src/egp_worker/workflows/discover.py`: add anomaly constants/helpers, track anomaly count/latest event, and adjust final status.
- `tests/phase1/test_worker_live_discovery.py`: add tests for `keyword_no_results` and `project_detail_invalid`.
- `.codex/coding-log.current`: point to this Coding Log.
- Existing local monthly entitlement/UI changes: preserve and validate.

#### Implementation Steps
1. Add tests first:
   - `test_run_discover_workflow_marks_live_keyword_no_results_as_failed`
   - `test_run_discover_workflow_marks_invalid_live_detail_as_failed`
2. Run:
   - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q -k "keyword_no_results or invalid_live_detail"`
   - Expected RED: status remains `succeeded`.
3. Implement:
   - `_LIVE_CRAWL_ANOMALY_STAGES`
   - `_snapshot_live_progress_event(event)`
   - `_live_progress_is_crawl_anomaly(event)`
   - `_build_live_crawl_anomaly_error(anomaly_count, latest_event)`
   - update `_current_summary()`, `_record_live_progress()`, and final status selection in `run_discover_workflow()`.
4. Run focused GREEN test command.
5. Run worker checks:
   - `./.venv/bin/ruff check apps/worker packages`
   - `./.venv/bin/python -m compileall apps/worker/src packages/crawler-core/src packages/shared-types/src`
   - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q`
6. Re-run monthly entitlement/UI checks that were already touched locally:
   - `./.venv/bin/python -m pytest tests/phase2/test_billing_reconciliation.py tests/phase2/test_rules_api.py tests/phase4/test_entitlements.py -q`
   - `(cd apps/web && npm run typecheck)`
   - targeted web e2e tests if the local harness is available.
7. Run QCHECK/g-check review, fix any findings, then package with Graphite and submit PR.
8. After CI is green, merge to `main`, then `gt sync`/local sync.

#### Test Coverage
- `test_run_discover_workflow_marks_live_keyword_no_results_as_failed`: final no-results live crawl fails closed.
- `test_run_discover_workflow_marks_invalid_live_detail_as_failed`: invalid eligible detail row fails closed.
- `test_run_discover_workflow_marks_partial_for_live_pagination_site_error`: existing partial behavior remains intact.
- Existing entitlement tests: monthly unlimited keyword behavior remains covered.

#### Decision Completeness
- Goal: make local and `origin/main` 100% OK for monthly entitlement/UI and crawl discovery false-success handling.
- Non-goals: no project extraction selector rewrite, no operational data backfill, no migration, no Excel fallback.
- Success criteria: no anomalous zero-project live crawl can finish `succeeded`; PR merged to `main`; local `main` synced to remote.
- Public interfaces: no route/schema/env/CLI changes. `summary_json` adds structured anomaly fields using the existing JSON column.
- Edge cases / failure modes: non-live empty manual runs remain unchanged; live anomalies fail closed; valid persisted projects plus later anomaly become `partial`; plain browser exceptions keep existing failed/partial behavior.
- Rollout & monitoring: monitor scheduled run failure/partial counts and `summary_json.error` after deployment; backout is reverting the workflow-only commit.
- Acceptance checks: focused worker tests, worker ruff/compile, entitlement API tests, web typecheck/build if feasible, GitHub CI.

#### Dependencies
Graphite CLI and GitHub CLI credentials for PR/merge; local Python venv and web dependencies.

#### Validation
Use the TDD commands above and record RED/GREEN evidence in this log. Final validation includes PR checks before merge.

#### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Live crawl anomaly classification | `run_discover_workflow()` final status mapping | `apps/worker/src/egp_worker/main.py:run_worker_job()` discover command | `crawl_runs.summary_json` existing JSON field |
| Progress anomaly capture | `_record_live_progress()` receives browser callback events | `crawl_live_discovery(... progress_callback=_record_live_progress)` | N/A |
| Scheduled monthly run behavior | `run_scheduled_discovery()` builds `live=True` discover jobs | `apps/worker/src/egp_worker/main.py` `run_scheduled_discovery` command | `crawl_runs.trigger_type='schedule'` existing value |

#### Cross-Language Schema Verification
No DB migration is planned. Existing storage is `crawl_runs.summary_json`; exact-string searches found it in `packages/db/src/egp_db/repositories/run_repo.py`, API run views, and web run-progress readers.

## Implementation (2026-05-21 12:27:57 +0700)

### Goal
Make monthly/scheduled live discovery runs fail closed when the crawler reports no real results or drops eligible detail rows, while preserving the existing local monthly entitlement/UI fixes.

### What Changed
- `apps/worker/src/egp_worker/workflows/discover.py`: added live crawl anomaly classification for `project_detail_invalid`, `project_detail_missing_required_fields`, and terminal zero-project `keyword_no_results`; anomalous live runs now finish `failed` with no persisted projects or `partial` when valid projects were already persisted. Summary JSON now records `live_crawl_anomaly_count`, `live_crawl_latest_anomaly`, and an anomaly `error`.
- `tests/phase1/test_worker_live_discovery.py`: added regression tests for terminal `keyword_no_results` and invalid eligible project detail.
- Existing local monthly entitlement/UI changes were preserved and validated; no additional edits were made to those files during this implementation unit.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q -k "keyword_no_results or invalid_live_detail"` failed with both new tests seeing `result.run.run.status == "succeeded"` instead of `failed`.
- GREEN: same command passed with `2 passed, 47 deselected`.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q` -> `49 passed`
- `./.venv/bin/ruff check apps/worker packages` -> passed
- `./.venv/bin/python -m compileall apps/worker/src packages/crawler-core/src packages/shared-types/src` -> passed
- `./.venv/bin/python -m pytest tests/phase2/test_billing_reconciliation.py tests/phase2/test_rules_api.py tests/phase4/test_entitlements.py -q` -> `38 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q` -> `12 passed`
- `./.venv/bin/ruff check apps/api packages` -> passed
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages` -> passed
- `cd apps/web && npm run typecheck` -> passed
- `cd apps/web && npm run test:unit` -> `5 passed`, `23 passed`
- `cd apps/web && npm run build` -> passed
- `cd apps/web && npm run lint` -> passed
- `cd apps/web && npm test -- billing-page.spec.ts rules-page.spec.ts` -> `15 passed`
- `cd apps/web && npm run check:api-types` -> passed

### Wiring Verification
- Runtime entry point: `apps/worker/src/egp_worker/main.py:run_worker_job()` still calls `run_discover_workflow()` for discover jobs.
- Scheduled/monthly path: `apps/worker/src/egp_worker/scheduler.py` builds `live=True` discover jobs with `trigger_type="schedule"`.
- Browser progress wiring: `run_discover_workflow()` passes `_record_live_progress` into `crawl_live_discovery(... progress_callback=...)`.
- Storage: anomaly details use the existing `crawl_runs.summary_json` JSON field; no migration required.

### Behavior and Risk Notes
- Fail closed for anomalous live discovery: zero persisted projects plus terminal `keyword_no_results` now fails, and invalid eligible detail rows fail/partial instead of being silently treated as success.
- Non-live empty seeded runs are unchanged.
- A live run with valid persisted projects plus an always-anomalous detail event becomes `partial`.
- Auggie semantic search was unavailable due HTTP 429; implementation was based on direct inspection and exact-string searches.

### Follow-Ups / Known Gaps
- No live browser run against e-GP was executed in this environment; validation is unit/integration-level plus existing Playwright UI checks.

## Review (2026-05-21 12:29:26 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree against `f68c84df`
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `git diff` for worker, entitlement, rules, billing, and web files; targeted `nl -ba` reads for changed logic; focused pytest/ruff/compile/web gates listed in the implementation section.
- Auggie semantic search failed with HTTP 429; review used direct file inspection and exact-string searches.

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
- Assumed the existing local monthly entitlement/UI working-tree changes are intended to ship in the same PR, per the user request.
- Assumed terminal zero-project `keyword_no_results` is the false-success condition to fail closed; a multi-keyword run that persists valid projects and later sees a no-results keyword remains successful unless another always-anomalous stage occurs.

### Recommended Tests / Validation
- Already run: worker live discovery and workflow tests, entitlement/rules/billing pytest, API/worker/package ruff and compileall, web typecheck/unit/build/lint, targeted billing/rules Playwright, and generated API type freshness check.
- Remote CI should still be treated as merge gate after PR submission.

### Rollout Notes
- No DB migration or flag required; the worker writes anomaly metadata into existing `crawl_runs.summary_json`.
- After deploy, monitor scheduled discovery runs with `status in ('failed', 'partial')` and `summary_json.error` beginning with `live crawl anomaly:`.
