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


## Review (2026-05-22 20:31:00) - system

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: concurrent customer crawling launch-readiness
- Commands Run: git rev-parse --show-toplevel; git branch --show-current; git status --porcelain=v1; git log -n 20 --oneline --decorate; read AGENTS.md, CLAUDE.md, docs/PRD.md, docs/LIGHTSAIL_LOW_COST_LAUNCH.md; inspected discovery dispatcher, worker browser launch, discovery job repository, project/document persistence, docker-compose.yml, API Dockerfile; Auggie attempted and returned 429.
- Sources: apps/api/src/egp_api/services/discovery_dispatch.py; apps/api/src/egp_api/services/discovery_worker_dispatcher.py; apps/api/src/egp_api/bootstrap/background.py; apps/api/src/egp_api/executors/discovery_dispatch.py; apps/worker/src/egp_worker/browser_discovery.py; packages/db/src/egp_db/repositories/discovery_job_repo.py; packages/db/src/egp_db/repositories/project_persistence.py; packages/db/src/egp_db/repositories/project_schema.py; docker-compose.yml; apps/api/Dockerfile.

### High-Level Assessment
- The product has the right high-level shape for early launch: API queues discovery jobs, a separate discovery executor claims jobs, and worker subprocesses perform browser crawls.
- The current single-host production-oriented Compose setup correctly defaults the API to external background mode, which keeps discovery dispatch out of the HTTP server.
- The database model is tenant-scoped and has useful uniqueness constraints for project identity.
- Launching with more than one simultaneous crawler is risky as implemented because browser instances are not isolated per worker.
- The Docker runtime also appears mismatched with the browser launcher: Chromium is installed by Playwright, but the launcher default points to a macOS Chrome path.
- Under customer crawl bursts, API responsiveness, worker reliability, duplicate job execution, and DB race handling are the main risks.

### Strengths
- External discovery executor is already supported and enabled in production Compose.
- Worker count is configurable through EGP_DISCOVERY_WORKER_COUNT.
- Project rows are tenant-scoped and protected by a tenant/canonical-project unique constraint.
- Manual recrawl enqueues jobs instead of doing the crawl inside the request handler when external mode is used.
- Tests cover dispatch worker_count behavior, retries, and background mode selection.

### Key Risks / Gaps (severity ordered)
CRITICAL
- Concurrent browser workers share the same default CDP port and browser profile. BrowserDiscoverySettings defaults cdp_port=9222 and a single browser_profile_dir, while launch_real_chrome always launches with those values. With EGP_DISCOVERY_WORKER_COUNT=2 in docker-compose.yml, two customer crawls can attach to or disrupt the same Chrome instance/profile. One worker shutting down can close the browser being used by another worker.
- Production Docker browser launch appears broken or at least unproven. apps/api/Dockerfile installs Playwright Chromium, but BrowserDiscoverySettings defaults chrome_path to /Applications/Google Chrome.app/Contents/MacOS/Google Chrome. The dispatcher only passes max_pages_per_keyword, not a Linux Chromium executable path, unique CDP port, or unique profile directory.

HIGH
- Embedded mode can block the API event loop during crawl dispatch. The API lifespan creates run_discovery_dispatch_loop, which calls synchronous processor.process_pending; the dispatcher then blocks on proc.communicate for up to three hours. Production Compose avoids this with external mode, but embedded remains a serious footgun and matched the local symptom where API endpoints timed out while a worker was running.
- The discovery job lease is a fixed 60-second stale window with no heartbeat. Jobs remain pending while a worker runs; another executor or accidental embedded+external deployment can reclaim and duplicate a long-running crawl after the lease goes stale.
- There is no customer-facing crawl-rate throttle beyond worker_count and keyword entitlements. A few monthly customers with many keywords can create a long queue and monopolize the shared executor/host.

MEDIUM
- Project/document persistence uses select-then-insert around unique constraints rather than database-native upsert/retry. Simultaneous crawls finding the same project/document can raise uniqueness errors instead of cleanly merging.
- Scheduled discovery currently runs as a periodic worker command rather than the same durable queue path, so an overlapping scheduled crawl and manual crawl can contend for browser resources.
- Single-VM launch puts API, Postgres, executors, browser processes, and artifacts on one host. The launch doc acknowledges browser bursts can contend with API resources.

LOW
- Tests cover dispatch concurrency with fake dispatchers, but not real concurrent browser launches with distinct profiles/ports, Linux Docker Chrome resolution, or multi-customer crawl bursts.

### Nit-Picks / Nitty Gritty
- Discovery dispatch creates runs with trigger_type="manual" even when the discovery job trigger_type may be profile_created/profile_updated/schedule.
- The docs recommend cron/systemd for scheduled discovery, but that path bypasses the durable discovery_jobs table.
- The environment has both embedded and external modes; misconfiguration can create duplicate or blocking processors.

### Tactical Improvements (1–3 days)
1. Set production EGP_DISCOVERY_WORKER_COUNT=1 until browser isolation is fixed.
2. Fix Docker browser launch by using Playwright-managed Chromium or a Linux chrome_path passed from configuration.
3. Allocate per-job browser profile directories and CDP ports, or replace CDP launch with Playwright browser.launch using isolated contexts.
4. Keep API in external background mode only for launch; add startup logging/health that makes embedded mode obvious.
5. Add a lease heartbeat or extend processing leases safely while a worker subprocess is alive.
6. Add a smoke test that runs two live/browser workers in parallel and asserts no shared-port/profile interference.

### Strategic Improvements (1–6 weeks)
1. Move all scheduled discovery into the durable discovery_jobs queue so manual and scheduled work share one back-pressure path.
2. Add per-tenant and global crawl quotas: max concurrent tenant workers, max queued jobs, cooldown windows, and admin override.
3. Split browser workers onto separate compute after traction, before increasing worker_count materially.
4. Convert project/document writes to database-native ON CONFLICT upserts or catch/retry IntegrityError as update/read.
5. Add operational dashboards for queue depth, active workers, worker memory, crawl duration, failures by tenant, and API latency during crawl bursts.

### Big Architectural Changes (only if justified)
- Proposal: Move from local subprocess spawning to a dedicated worker service/queue once more than a handful of customers crawl concurrently.
  - Pros: isolates browser CPU/memory from API, enables per-worker resource limits, safer horizontal scaling, clearer observability.
  - Cons: more infrastructure, deployment complexity, queue visibility/retention decisions.
  - Migration Plan: first fix single-host browser isolation; route scheduled discovery through discovery_jobs; add tenant/global throttles; then run discovery-executor on a worker host/container; finally move to managed queue/worker pool if demand proves it.
  - Tests/Rollout: start with worker_count=1 canary; add two-worker integration test; enable worker_count=2 for internal tenant only; monitor API latency and queue duration; then open limited customer concurrency.

### Open Questions / Assumptions
- Assumes launch target is the checked-in single-VM Compose/Lightsail path.
- Assumes crawls are browser-heavy and often exceed 60 seconds.
- Assumes several customers may press recrawl or add active keywords around the same time.


## Review (2026-05-23 09:03:58 +07) - system

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: discovery crawl launch-readiness / concurrency assessment
- Commands Run: git rev-parse --show-toplevel; git branch --show-current; git status --porcelain=v1; git log -n 20 --oneline --decorate; Auggie codebase retrieval (failed with HTTP 429); targeted rg/nl/sed inspections of discovery dispatcher, worker browser settings, project/document persistence, discovery jobs, background bootstrap, PRD, and AGENTS.md files.
- Sources: AGENTS.md, apps/api/AGENTS.md, apps/worker/AGENTS.md, packages/AGENTS.md, packages/db/AGENTS.md, docs/PRD.md, apps/api/src/egp_api/services/discovery_worker_dispatcher.py, apps/api/src/egp_api/services/discovery_dispatch.py, apps/api/src/egp_api/bootstrap/background.py, apps/worker/src/egp_worker/browser_discovery.py, apps/worker/src/egp_worker/main.py, apps/worker/src/egp_worker/workflows/discover.py, packages/db/src/egp_db/repositories/project_persistence.py, packages/db/src/egp_db/repositories/project_aliases.py, packages/db/src/egp_db/repositories/project_lifecycle.py, packages/db/src/egp_db/repositories/document_persistence.py, packages/db/src/egp_db/repositories/discovery_job_repo.py, packages/db/src/egp_db/connection.py.

### High-Level Assessment
- The senior engineer's launch-readiness concern is directionally correct: current discovery crawling is only safe while effectively serialized.
- The intended PRD calls for isolated browser workers and stable multi-tenant production readiness, but the current API dispatch path does not allocate per-worker browser isolation.
- `EGP_DISCOVERY_WORKER_COUNT` defaults to 1, so normal behavior is a global FIFO crawl queue.
- Raising worker count on one host can make subprocess workers attach to the same Chrome CDP endpoint/profile because the worker defaults remain fixed.
- The queue and persistence layers have several check-then-act paths that are acceptable under serialization but fragile under real parallelism.
- One important additional launch risk: the default embedded discovery loop runs blocking subprocess dispatch from the FastAPI event loop, so a live crawl can block the API process unless production uses the external dispatcher mode.

### Strengths
- Tenant scoping is consistently present in the inspected repositories and routes.
- Discovery job claiming uses a conditional update with rowcount checking, so simultaneous claim attempts do not simply double-claim fresh rows.
- The worker already accepts `browser_settings` for `cdp_port` and `browser_profile_dir`, so the browser-isolation fix is mainly dispatcher/runtime wiring plus tests.
- Document storage has a database uniqueness constraint for duplicate hashes/classes/phases, although the application path is not fully concurrent-idempotent.

### Key Risks / Gaps (severity ordered)
CRITICAL
- Browser isolation is missing in the API dispatch path. `BrowserDiscoverySettings` defaults to CDP port 9222 and `~/download/TOR/.browser_profile`; `launch_real_chrome()` and `connect_playwright_to_chrome()` trust that port without verifying process ownership. `SubprocessDiscoveryDispatcher` only forwards `max_pages_per_keyword` in `browser_settings`, so parallel workers on one host can attach to the same Chrome endpoint/profile.
- Default embedded discovery dispatch can block the API event loop. `build_lifespan()` creates an async task that directly calls `run_discovery_dispatch_loop()`, which calls synchronous `processor.process_pending()` and then `proc.communicate()` for up to 3 hours per worker. Production should run discovery dispatch externally or move blocking work off the event loop before launch.

HIGH
- Queue behavior is global FIFO with no tenant fairness. `DiscoveryDispatchProcessor` claims in worker-count-sized batches ordered by due/created time; default worker count is 1. A tenant with many active keywords can hold the queue ahead of later tenants.
- There is no global or per-host rate limiter for gprocurement crawling. The crawler has fixed sleeps and local recovery retries, but no shared limiter, exponential backoff, jitter, or circuit breaker.
- Project upsert is not concurrent-idempotent. `upsert_project()` does select-then-insert/update under a unique `(tenant_id, canonical_project_id)` constraint. Concurrent discovery of the same project can raise an `IntegrityError`; the workflow catches this as a project/task failure and the outbox job may still be marked dispatched rather than retried.
- State transitions are vulnerable to stale-read last-writer-wins behavior. `transition_project()` and `upsert_project()` compute transitions from a row selected without lock/CAS; concurrent close-check and discovery can overwrite each other's state with stale decisions.

MEDIUM
- Discovery-job enqueue deduplication is check-then-insert without a unique constraint, so concurrent manual recrawl/profile updates can create duplicate pending jobs.
- Discovery job stale-claim timeout is 60 seconds while live crawls run for minutes or hours. The conditional claim is atomic for fresh claims, but stale reclaim can double-dispatch a genuinely still-running job across multiple dispatchers or route-triggered processors.
- SQLAlchemy engine creation uses default Postgres pool sizing, with no explicit relationship to worker count, per-worker repositories, document ingest, and API traffic.
- Document duplicate handling is database-protected but not application-idempotent under concurrency: two identical inserts can both pass the pre-check, then one hits the unique index after artifact writes.

LOW
- Existing tests verify worker_count concurrency at the dispatcher abstraction and worker-side parsing of browser settings, but do not cover dispatcher-generated unique CDP/profile settings, concurrent upsert races, stale-claim behavior, or rate-limit/backoff policy.

### Nit-Picks / Nitty Gritty
- The prior assessment slightly overstates one point: project persistence exceptions are caught per project in the discover workflow, so they do not necessarily crash the subprocess. The practical outcome is still bad because the run becomes failed/partial while the discovery outbox can be marked dispatched.
- The prior assessment also calls document storage cleanly duplicate-safe under concurrency. The DB constraint prevents duplicate committed rows, but the application path can still surface an IntegrityError and cleanup path under concurrent same-document inserts.
- The system is not literally using one persistent browser today; it spawns per job, but with a shared default profile/port. That distinction does not reduce the concurrent-crawl risk.

### Tactical Improvements (1-3 days)
1. Add dispatcher-owned browser isolation: allocate unique CDP ports and run-scoped profile dirs, pass them in `browser_settings`, verify worker tests cover the actual API dispatcher payload, and clean profile dirs after safe shutdown.
2. Set production default to external discovery dispatch, or move `processor.process_pending()` onto a dedicated thread/process executor so FastAPI's event loop cannot be blocked by crawl subprocesses.
3. Add a host-level e-GP rate limiter with jittered exponential backoff and a short circuit breaker before increasing `EGP_DISCOVERY_WORKER_COUNT`.
4. Make project upsert and alias/document inserts conflict-aware using Postgres `ON CONFLICT`/retry-read behavior; add a concurrent test using PostgreSQL, not only SQLite.
5. Add per-tenant in-flight caps and queue fairness, even a simple round-robin claim query or bounded per-tenant admission gate.

### Strategic Improvements (1-6 weeks)
1. Treat browser workers as a bounded pool with explicit leases: worker_id, port, profile path, tenant/run/job ownership, heartbeat, and cleanup.
2. Split job lifecycle from dispatch completion: distinguish spawned, running, succeeded, failed, partial, and cancelled instead of marking the outbox `dispatched` after a subprocess exits regardless of run success.
3. Introduce durable crawl scheduling/admission control with per-tenant quotas, retry policy, and observability dashboards for queue age, crawl duration, WAF/rate-limit signals, and failure classes.
4. Add Postgres-backed concurrency tests for project/document idempotency and state transitions.

### Big Architectural Changes (only if justified)
- Proposal: move live discovery dispatch out of the API process entirely and operate it as a dedicated worker service with an explicit browser-worker pool.
  - Pros: protects API availability, gives a clear concurrency boundary, centralizes rate limiting and browser lifecycle, and makes worker_count an operational setting rather than an API footgun.
  - Cons: requires deployment/process supervision work and more explicit run/job state modeling.
  - Migration Plan: first run `EGP_BACKGROUND_RUNTIME_MODE=external` in production; then add browser leases and unique profile/port allocation; then add fair queue/admission controls; then raise concurrency gradually behind metrics.
  - Tests/Rollout: add unit tests for payload isolation, integration tests for concurrent upserts, smoke test external dispatcher, and rollout with worker_count=1 then 2 under rate-limit metrics.

### Open Questions / Assumptions
- I did not run live crawls or Postgres stress tests during this review.
- The browser cross-talk scenario depends on same-host parallel workers; it is a launch blocker if one host can ever run worker_count > 1 or multiple dispatchers share the same host defaults.
- If production is already configured with `EGP_BACKGROUND_RUNTIME_MODE=external`, the API-event-loop blocking risk is mitigated operationally but still unsafe as the repo default.
