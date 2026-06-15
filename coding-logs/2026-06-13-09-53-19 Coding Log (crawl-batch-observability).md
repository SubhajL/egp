# Coding Log: crawl-batch-observability

## Plan Draft A - keyword-run visibility without schema migration

### Overview
Make every keyword crawl produce a durable `crawl_tasks` row, even when it finds zero projects. Reuse the existing `/v1/runs` contract and `summary_json.live_progress` so the frontend can summarize multi-keyword actions without a new table.

### Files to Change
- `apps/worker/src/egp_worker/workflows/discover.py`: create and finish a keyword-level task for zero-result and run-level-error crawls.
- `tests/phase1/test_worker_live_discovery.py`: add/adjust tests for zero-result tasks and terminal anomaly tasks.
- `apps/api/src/egp_api/services/rules_service.py`: route profile-create enqueueing through the same admission/dedupe helper used by manual recrawl.
- `packages/db/src/egp_db/repositories/profile_repo.py`: stop direct profile-create discovery outbox inserts from the repository.
- `tests/phase2/test_rules_api.py`: verify create-profile admission/dedupe behavior and pending job count.
- `apps/api/src/egp_api/services/run_service.py`: normalize absolute worker log paths containing `/tenants/...` to the current artifact root.
- `tests/phase1/test_projects_and_runs_api.py`: add log-path compatibility coverage.
- `apps/web/src/lib/run-progress.ts`: expose batch/keyword helpers from run summaries and tasks.
- `apps/web/src/app/(app)/projects/page.tsx`: show a compact recent keyword-run summary after a multi-keyword recrawl/profile-create.
- `apps/web/tests/e2e/projects-page.spec.ts`: cover recent multi-keyword zero-result/failed summary.

### Implementation Steps
1. Add RED tests:
   - zero-result live discovery creates and succeeds a keyword task.
   - terminal `keyword_no_results` creates and fails a keyword task.
   - create-profile enqueues through dedupe/admission instead of repository inline insert.
   - run log service accepts legacy absolute paths by remapping `/tenants/...`.
   - projects page renders recent multi-keyword completion counts.
2. Run focused tests and confirm failures.
3. Implement smallest worker task creation helper and summary-compatible task result fields.
4. Move profile-created job enqueueing into `RulesService` after profile persistence, guarded by admission before writes.
5. Add log-path candidate normalization for absolute stale paths.
6. Add frontend summary helper and render it in the existing run activity panel.
7. Run format/lint/typecheck/tests/build gates and self-review.

### Test Coverage
- `test_live_discovery_zero_results_records_keyword_task`: zero results remain visible.
- `test_live_discovery_terminal_no_results_records_failed_keyword_task`: anomaly tied to keyword.
- `test_create_profile_checks_run_admission_before_enqueue`: cap enforced pre-outbox.
- `test_create_profile_dedupes_pending_discovery_jobs`: repeated pending job not duplicated.
- `test_run_log_remaps_legacy_absolute_artifact_path`: stale absolute log path readable.
- `projects page summarizes multi-keyword crawl completion`: UI shows batch-like totals.

### Decision Completeness
- Goal: make multi-keyword crawls observable and reduce false "nothing happened" reports.
- Non-goals: no new `crawl_batches` table, no production data repair, no crawler search heuristic rewrite.
- Success criteria: zero-result keywords have task rows; profile creation uses admission/dedupe; stale log paths can be read; UI shows processed/zero/failed counts for recent keyword runs.
- Public interfaces: no new endpoint or migration; existing `/v1/runs` response contains more task rows.
- Edge cases / failure modes: if keyword task creation fails, run fails closed with existing error_count; if log path is outside artifact root and lacks `/tenants/...`, it stays blocked.
- Rollout & monitoring: deploy-compatible; watch recent failed runs and support reports around "crawl stopped".
- Acceptance checks: focused pytest, frontend unit/e2e, typecheck, lint, build.

### Dependencies
- Existing SQLite/Postgres test harnesses.
- Existing Playwright projects page test harness.

### Validation
- Python: `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_projects_and_runs_api.py tests/phase2/test_rules_api.py -q`
- Frontend: `cd apps/web && npm run test:unit && npm run test:e2e -- projects-page.spec.ts && npm run typecheck && npm run lint && npm run build`

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| keyword task recording | `run_discover_workflow()` | worker dispatcher payload calls existing workflow | `crawl_tasks` existing table |
| profile-create enqueue helper | `RulesService.create_profile()` | `routes/rules.py` uses `app.state.rules_service` | `discovery_jobs` existing table |
| log-path remap | `RunService.get_run_log()` | `routes/runs.py` log endpoint | artifact root path, no schema |
| frontend summary | `ProjectsPage` run activity panel | `/projects` route component | `/v1/runs` existing response |

### Cross-Language Schema Verification
- `crawl_tasks` exists in migration `001_initial_schema.sql` and repository `run_repo.py`.
- `discovery_jobs` is used by repository/service/API dispatch code; no new column required.

## Plan Draft B - introduce first-class crawl batches

### Overview
Add `crawl_batches` and `crawl_batch_items` to group one user action into many keyword jobs. The UI reads a new batch endpoint instead of inferring from recent runs.

### Files to Change
- New DB migration and repository for batches/items.
- API rules responses and new `/v1/runs/batches` endpoint.
- Worker/dispatcher links jobs to batch items.
- Frontend projects/runs pages read batch status.

### Implementation Steps
1. Add migration/repository tests.
2. Add batch creation in profile-create/manual-recrawl.
3. Link discovery jobs/runs to batch items.
4. Add endpoint and frontend batch cards.
5. Backfill or tolerate historical runs without batches.

### Test Coverage
- batch repository lifecycle.
- recrawl creates batch and items.
- dispatch marks item completed/failed.
- UI renders batch counts.

### Decision Completeness
- Goal: exact user-action grouping.
- Non-goals: historical backfill in this PR.
- Success criteria: batch endpoint is authoritative.
- Public interfaces: new migration and API endpoint.
- Edge cases: partial deploy skew; old runs without batches.
- Rollout: migration first, then API/web.

### Dependencies
- Migration discipline and OpenAPI regeneration.

### Validation
- Full API/schema/OpenAPI/frontend contract gates.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| batch repo | rules service | bootstrap repositories | new tables |
| batch endpoint | API router | app router include | new tables |
| UI batch cards | projects page | Next app route | new API contract |

### Cross-Language Schema Verification
- Would require grep verification across API, DB, web generated types, tests.

## Comparative Analysis
- Draft A is smaller, deploy-compatible, and directly fixes today's blind spots using existing tables.
- Draft B is cleaner long-term, but expands schema/API/OpenAPI surface and creates deploy-skew risk.
- Draft A leaves "batch" as an inferred UI concept, but creates durable per-keyword evidence and can be extended into real batches later.
- Draft B should follow once product wants batch history as a first-class admin/audit object.

## Unified Execution Plan

### Overview
Implement Draft A now. The PR will make keyword processing visible at the existing run/task layer, reuse manual-recrawl admission semantics for profile creation, make old worker logs recoverable, and improve the project-page activity panel for multi-keyword results.

### Files to Change
- `apps/worker/src/egp_worker/workflows/discover.py`: add keyword task lifecycle for zero-result/error runs.
- `tests/phase1/test_worker_live_discovery.py`: worker RED/GREEN coverage.
- `apps/api/src/egp_api/services/rules_service.py`: profile-created enqueue via service helper.
- `packages/db/src/egp_db/repositories/profile_repo.py`: remove inline outbox enqueue behavior.
- `tests/phase2/test_rules_api.py`: profile-create admission and enqueue coverage.
- `apps/api/src/egp_api/services/run_service.py`: robust log path candidate resolution.
- `tests/phase1/test_projects_and_runs_api.py`: log path compatibility test.
- `apps/web/src/lib/run-progress.ts`: batch summary helper.
- `apps/web/src/app/(app)/projects/page.tsx`: render recent keyword-run summary.
- `apps/web/tests/e2e/projects-page.spec.ts`: UI behavior test.

### Implementation Steps
1. TDD sequence:
   1) Add/stub focused tests.
   2) Run and confirm RED failures.
   3) Implement smallest changes.
   4) Refactor only around duplicate helper logic.
   5) Run relevant fast gates, then broader gates.
2. Worker functions:
   - `_create_keyword_task(...)`: create a discover task at keyword-run start.
   - `_finish_keyword_task(...)`: mark the task succeeded/failed with keyword-level counts/error.
   - `run_discover_workflow(...)`: call the helpers when no project-specific task was created.
3. API functions:
   - `RulesService.create_profile(...)`: check runs admission before profile write, then enqueue `profile_created` jobs through `create_pending_discovery_job_if_absent`.
   - `_queue_profile_created_jobs(...)`: dedupe response-neutral helper for new profile keywords.
   - `_resolve_run_log_candidates(...)`: remap `/tenants/...` suffix from stale absolute paths.
4. Frontend functions:
   - `summarizeRecentKeywordRuns(...)`: count recent run details into processed/zero-result/failed/keywords.
   - `ProjectsPage`: show the summary in the existing crawl activity section.

### Test Coverage
- `test_live_discovery_zero_results_records_keyword_task`: keyword task for no projects.
- `test_live_discovery_terminal_no_results_records_failed_keyword_task`: failed keyword task records anomaly.
- `test_create_profile_uses_discovery_repository_for_profile_created_jobs`: no repository inline enqueue.
- `test_create_profile_denies_before_outbox_insert_when_keyword_queue_cap_exceeded`: admission before DB outbox writes.
- `test_run_log_remaps_legacy_absolute_artifact_path`: old absolute log metadata readable.
- `projects page summarizes multi-keyword crawl completion`: UI shows aggregate counts.

### Decision Completeness
- Goal: close gaps 1-5 from the production diagnosis without a migration.
- Non-goals: new batch tables, production database edits, changing e-GP search heuristics, changing payment/LINE behavior.
- Success criteria: tests fail before implementation and pass after; no unbounded tenant queries; UI copy accurately reflects completed zero-result/failed keyword runs; stale absolute log paths are readable only under artifact-root-equivalent tenant/run suffixes.
- Public interfaces: existing API only; no new env vars, endpoints, migrations, or generated OpenAPI type changes expected.
- Edge cases / failure modes:
  - Keyword task create failure: fail closed at run level with existing error handling.
  - Duplicate pending job: do not insert duplicate.
  - Queue cap exceeded: reject before profile/outbox write.
  - Stale absolute log path: remap only if it contains `tenants/<tenant>/runs/<run>/worker.log`; otherwise deny.
  - Recent runs include unrelated old jobs: summary limits to the current visible recent runs and labels as recent activity, not authoritative lifetime batch.
- Rollout & monitoring: no migration; deploy API/worker/web together; monitor failed runs, task_count changes, and user reports about zero project results.
- Acceptance checks: focused pytest, Python compile/ruff, frontend unit/e2e/typecheck/lint/build, g-check.

### Dependencies
- Existing `.venv` and `apps/web/node_modules`.
- GitHub CLI for PR creation and admin merge.

### Validation
- RED: focused tests before implementation.
- GREEN: focused tests after implementation.
- Gates: `./.venv/bin/python -m compileall apps packages`; `./.venv/bin/ruff check apps/worker apps/api packages`; focused pytest; frontend unit/e2e/typecheck/lint/build.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| keyword task lifecycle | `run_discover_workflow()` | `egp_worker.main` dispatches command `discover` to workflow | `crawl_tasks` existing columns `keyword`, `status`, `result_json` |
| profile-created enqueue helper | `RulesService.create_profile()` | `POST /v1/rules/profiles` route resolves `rules_service` | `discovery_jobs` existing table |
| log path remap | `RunService.get_run_log()` | `GET /v1/runs/{run_id}/log` route | artifact root filesystem only |
| recent keyword summary | `ProjectsPage` | Next `/projects` route imports `run-progress` helper | `/v1/runs` existing response |

### Cross-Language Schema Verification
- No migration planned.
- Verify existing table names via `rg -n "crawl_tasks|discovery_jobs" packages/db/src apps packages`.

### Decision-Complete Checklist
- No open decisions remain.
- Public surface changes are listed: existing API response content only.
- Every behavior change has a focused test.
- Validation commands are specific.
- Wiring table covers each changed runtime seam.
- Rollout/backout is low-risk: revert PR, no migration rollback.

## Implementation Summary - 2026-06-13

### What changed
- `apps/worker/src/egp_worker/workflows/discover.py`
  - records a keyword-level `crawl_tasks` row when a live keyword run creates no project tasks;
  - marks terminal live `keyword_no_results` anomalies as failed keyword tasks;
  - leaves project-specific task behavior unchanged when projects are persisted.
- `apps/api/src/egp_api/services/rules_service.py`
  - checks run admission before profile creation writes;
  - queues `profile_created` discovery jobs via `create_pending_discovery_job_if_absent` after profile persistence.
- `packages/db/src/egp_db/repositories/profile_repo.py`
  - removes inline discovery-job insertion from profile persistence.
- `apps/api/src/egp_api/routes/rules.py`
  - maps profile-create admission failures to the same structured 429 response as manual recrawl.
- `apps/api/src/egp_api/services/run_service.py`
  - remaps stale absolute worker log metadata containing `/tenants/...` to the current artifact root before applying the existing path safety check.
- `apps/web/src/lib/run-progress.ts` and `apps/web/src/app/(app)/projects/page.tsx`
  - summarize recent completed keyword runs as processed/succeeded/zero-result/failed counts;
  - render the summary in the existing projects crawl activity panel.
- Tests added or updated across worker, API, run-log, and projects-page e2e coverage.

### RED evidence
- Focused worker tests initially failed because zero-result and terminal-no-result live runs produced no `crawl_tasks` rows.
- Focused API tests initially failed because profile creation returned `201` instead of admission `429` when queued keyword capacity was exhausted.
- Focused run-log test initially failed with `404` for a legacy absolute path under the old local artifact root.
- Focused projects-page e2e initially failed because no `สรุปล่าสุด 3 คำค้น` summary was rendered.

### GREEN evidence
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/notification-core/src:packages/document-classifier/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_projects_and_runs_api.py tests/phase2/test_rules_api.py -q`
  - passed 3 consecutive runs: `79 passed`.
- `cd apps/web && npm run test:e2e -- projects-page.spec.ts`
  - passed 3 consecutive runs: `7 passed`.
- `cd apps/web && npm run test:unit -- --run`
  - passed 3 consecutive runs: `39 passed`.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/notification-core/src:packages/document-classifier/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m ruff format ...`
  - formatted touched Python files.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/notification-core/src:packages/document-classifier/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m ruff check ...`
  - `All checks passed!`
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/notification-core/src:packages/document-classifier/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps/api/src apps/worker/src packages/db/src`
  - passed.
- `cd apps/web && npm run typecheck`
  - passed.
- `cd apps/web && npm run lint`
  - passed with the existing Next lint deprecation notice.
- `cd apps/web && npm run build`
  - passed with the existing edge-runtime static-generation warning.

### Wiring Verification
- `summarizeRecentKeywordRuns` is imported only by `ProjectsPage` and reads existing `/v1/runs` data.
- `_queue_profile_created_jobs` uses the same `DiscoveryJobRepository.create_pending_discovery_job_if_absent` method as manual recrawl.
- `_resolve_run_log_candidates` still returns candidates that must match the canonical tenant/run artifact-root path before any file is read.
- `crawl_tasks` and `discovery_jobs` references were checked with `rg`; no migration or API contract generation was needed.

## Review (2026-06-13 10:36 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-crawl-batch-observability`
- Branch: `fix/crawl-batch-observability`
- Scope: working tree from base `20782532`
- Commands Run:
  - `git status --short`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/worker/src/egp_worker/workflows/discover.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/services/rules_service.py apps/api/src/egp_api/routes/rules.py packages/db/src/egp_db/repositories/profile_repo.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/services/run_service.py tests/phase1/test_projects_and_runs_api.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/web/src/lib/run-progress.ts apps/web/src/app/(app)/projects/page.tsx`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- tests/phase1/test_worker_live_discovery.py tests/phase2/test_rules_api.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/web/tests/e2e/projects-page.spec.ts`
  - `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/notification-core/src:packages/document-classifier/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_projects_and_runs_api.py tests/phase2/test_rules_api.py -q` repeated 3 times
  - `cd apps/web && npm run test:e2e -- projects-page.spec.ts` repeated 3 times
  - `cd apps/web && npm run test:unit -- --run` repeated 3 times plus one final run
  - `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/notification-core/src:packages/document-classifier/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m ruff check ...`
  - `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/notification-core/src:packages/document-classifier/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps/api/src apps/worker/src packages/db/src`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run lint`
  - `cd apps/web && npm run build`

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
- The project-page summary is intentionally a recent-run aggregation, not a first-class persisted crawl batch. That matches the no-migration plan but should not be treated as authoritative historical batch accounting.
- Profile-created job enqueueing now matches the service-level discovery job path and admission guard. Like the existing profile-update enqueue path, the post-profile queue step is outside the profile repository transaction.

### Recommended Tests / Validation
- Already run: focused worker/API pytest set, projects-page e2e repeated 3 times, web unit repeated 3 times, ruff, compileall, typecheck, lint, build.
- After deploy, verify production with a multi-keyword profile whose expected outcome includes at least one zero-result keyword and one failed/blocked keyword, then check `/runs` and the project-page summary.

### Rollout Notes
- No migration, new env var, or endpoint is required.
- Roll back by reverting the PR; no schema rollback is needed.
- The old absolute worker-log metadata remains path-checked against the current artifact root before file reads.

## Review (2026-06-14 10:40:59 +07) - system

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: live e-GP discovery subsystem, run observability, and prior diagnosis gap for tenant `c717b262-07a8-477d-bb78-f36a4a814eb7` keyword `วิเคราะห์ข้อมูล`
- Commands Run: `git rev-parse --show-toplevel`; `git branch --show-current`; `git status --porcelain=v1`; `git log -n 20 --oneline --decorate`; direct reads of AGENTS/CLAUDE/worker/API/db/web files; production DB tenant/job/run/project queries through `.env.remotecrawl`; worker-log inspection under `.data/artifacts/...`; log aggregation over tenant worker logs.
- Sources: `AGENTS.md`, `CLAUDE.md`, `apps/worker/AGENTS.md`, `packages/AGENTS.md`, `apps/worker/src/egp_worker/browser_discovery.py`, `apps/worker/src/egp_worker/workflows/discover.py`, `apps/api/src/egp_api/services/discovery_dispatch.py`, `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`, `apps/api/src/egp_api/services/run_service.py`, `packages/db/src/egp_db/repositories/run_repo.py`, `packages/crawler-core/src/egp_crawler_core/invitation_rules.py`, `tests/phase1/test_worker_browser_discovery.py`, `tests/phase1/test_worker_live_discovery.py`, current run log `2dcdd3a0-15d4-4754-8bf3-8e1d5e559ebb/worker.log`, user screenshots containing missed project numbers `69059071027`, `69049396882`, `69029301629`, `69039582244`, `68119364483`.

### High-Level Assessment
- The live discovery pipeline is: `discovery_jobs` outbox -> API dispatch processor -> subprocess worker -> `crawl_live_discovery()` browser automation -> search result row filter -> detail-page extraction -> workflow persistence through project event sink -> `projects`, `crawl_tasks`, `crawl_runs` summaries.
- The latest `วิเคราะห์ข้อมูล` run did not fail to search. It scanned 15 pages, 10 rows each, then reported `eligible_count=0` for every page.
- The five screenshot project numbers are absent from `projects`, so the miss happened before persistence.
- The strongest current hypothesis is a brittle search-result-row eligibility boundary: the code trusts `cells[4]` and requires the exact combined status `หนังสือเชิญชวน/ประกาศเชิญชวน` before opening detail pages, while domain ingestion accepts any status containing `ประกาศเชิญชวน` and the screenshots prove the detail page status is eligible.
- My prior answer was incomplete because it treated `projects_seen=0` as if it answered whether eligible projects existed, instead of checking row scan counts, eligibility filters, logs, and external evidence.

### As-Is Pipeline Diagram
A profile/manual action writes one `discovery_jobs` row per keyword. `DiscoveryDispatchProcessor.process_job()` claims a job and `SubprocessDiscoveryDispatcher.dispatch()` creates a `crawl_runs` row, spawns `egp_worker.main`, and stores worker log metadata. `run_worker_job()` calls `run_discover_workflow(live=True)`, which calls `crawl_live_discovery()`. Browser discovery searches the e-GP keyword, paginates result rows, filters rows in `_extract_search_row()`, opens only eligible rows, extracts details, and streams each payload back through `project_callback` for persistence. The workflow writes project-specific `crawl_tasks` only after a project payload is accepted; otherwise it writes a keyword task with `projects_seen: 0` and finishes the run using the last live progress snapshot.

### Strengths
- The dispatch path is tenant-scoped and uses durable run/job/task repositories.
- The worker now records keyword-level task rows for zero-result runs, so old UI ambiguity is reduced.
- Worker logs preserve all page scan progress, even though the DB summary only keeps the latest progress event.
- Browser code already has navigation retries, page restore logic, and row-marker recovery.

### Key Risks / Gaps (severity ordered)
CRITICAL
- Search-result eligibility is too brittle and can skip real eligible projects before detail extraction. Evidence: `apps/worker/src/egp_worker/browser_discovery.py:678-684` hard-codes `cells[4]` as status and rejects unless `status_matches_target()` passes; `status_matches_target()` at `apps/worker/src/egp_worker/browser_discovery.py:1596-1597` requires the exact combined target string. Domain ingestion is more permissive at `packages/crawler-core/src/egp_crawler_core/invitation_rules.py:15-18` and accepts `ประกาศเชิญชวน`. The `วิเคราะห์ข้อมูล` worker log scanned 150 rows with `eligible_count=0`, while screenshots show eligible detail pages for the same keyword.

HIGH
- Run summaries can make an incomplete crawl look confidently successful. Evidence: `apps/worker/src/egp_worker/workflows/discover.py:667-674` marks status `succeeded` when `effective_error_count` is zero, even if every scanned page had rows and zero eligible candidates. The run log showed `row_count=150` and `eligible_count=0`; DB summary/task only exposed `projects_seen=0`.
- Observability loses the evidence needed to debug row filtering. Evidence: `_record_live_progress()` stores only the latest event in `apps/worker/src/egp_worker/workflows/discover.py:351-361`; page-scan events are overwritten by `keyword_finished`. The durable task result for this run is only `{"projects_seen": 0}`.
- Tests encode the idealized row shape instead of the live e-GP row/detail mismatch. Evidence: `tests/phase1/test_worker_browser_discovery.py:428-456` defines fake rows with the status exactly at cell index 4 and the exact combined status text; the `_collect_keyword_projects` tests therefore do not cover rows that require detail-open verification or header-derived column mapping.

MEDIUM
- The crawler clicks to page 16 after scanning page 15 even though `max_pages_per_keyword=15`. Evidence: loop condition is checked at `apps/worker/src/egp_worker/browser_discovery.py:326`, but next-page click happens before the next loop iteration at `apps/worker/src/egp_worker/browser_discovery.py:516-576`; the log shows `pagination_next_finished ... page_num=16` followed by `keyword_finished`. It is extra load and confusing telemetry.
- UI aggregation still treats zero-result success as a normal success. Evidence: `apps/web/src/lib/run-progress.ts:167-187` summarizes zero-result counts, but the underlying run status remains `succeeded`; without row-count/filter diagnostics, operators cannot distinguish true empty searches from filter misses.
- Worker event return semantics are confusing. Evidence: `apps/worker/src/egp_worker/workflows/discover.py:578-586` streams live projects through a callback then sets `resolved_projects = []`, so `crawl_live_discovery()` can return collected payloads in direct use while the workflow intentionally ignores the return list in live mode.

LOW
- `discovery_jobs.job_status='dispatched'` means the subprocess returned, not necessarily that useful discovery happened. This is known but still operator-hostile.
- Some log artifacts are local absolute paths; `RunService.get_run_log()` has a remap helper, but root/path drift remains an operational footgun.

### Drift Matrix
- Intended: Discover invitation-stage projects for a keyword. Implemented: reject rows before opening detail unless one hard-coded result-cell status exactly matches. Impact: real eligible projects can be missed. Fix direction: derive columns by headers, broaden candidate statuses, and verify final eligibility from detail page before persistence.
- Intended: `projects_seen=0` means no eligible projects found. Implemented: it can also mean rows existed but all were filtered before detail extraction. Impact: false negative operator conclusion. Fix direction: persist `rows_scanned`, `candidate_rows`, `rejected_by_status`, `status_buckets`, and sample row text per keyword.
- Intended: successful run means search quality was acceptable. Implemented: a run with 150 scanned rows and 0 candidates succeeds silently. Impact: missed-procurement incident is hidden. Fix direction: flag suspicious `row_count>0 && eligible_count=0` as warning/anomaly unless explicitly expected.
- Intended: tests protect live e-GP row parsing. Implemented: tests use fake rows in the expected exact shape. Impact: parser drift can ship. Fix direction: add fixture-based parser tests from captured live row HTML/text and screenshot-derived cases.
- Intended: max pages limits crawl load. Implemented: crawler advances once past the limit before stopping. Impact: unnecessary e-GP load and confusing logs. Fix direction: do not click next when `page_num >= max_pages_per_keyword`.

### Nit-Picks / Nitty Gritty
- `status_matches_target()` should probably share semantics with `is_invitation_stage_status()` or one canonical helper, not maintain a stricter duplicate rule.
- `page_scan_finished` should include status buckets and sample row signatures. Counts alone are not enough.
- `_extract_project_number_from_text()` only extracts labels shaped like `เลขที่โครงการ ...`; search-row plan text may use a procurement-plan number (`P69...`) rather than project number, so detail extraction remains the authoritative project-number source.
- The current DB has zero rows for screenshot project numbers `69059071027`, `69049396882`, `69029301629`, `69039582244`, `68119364483`.

### Tactical Improvements (1-3 days)
1. Change result-row parsing to derive column indexes from headers and log status buckets whenever `eligible_count=0` with `row_count>0`.
2. Broaden candidate selection to open rows whose status contains `ประกาศเชิญชวน` or `หนังสือเชิญชวน`, and consider a conservative detail-verification fallback for rows whose title/keyword matches but row status is ambiguous.
3. Mark suspicious scans as a non-terminal anomaly: `row_count>0`, `eligible_count=0`, and no persisted projects across multiple pages should not be indistinguishable from a true empty result.
4. Add tests with rows where status is only `ประกาศเชิญชวน`, only `หนังสือเชิญชวน`, shifted columns, and row-level status not matching but detail status eligible.
5. Stop paginating beyond `max_pages_per_keyword`.

### Strategic Improvements (1-6 weeks)
1. Introduce first-class crawl observation records or batch items for per-keyword page scan evidence. Why now: this incident shows summaries/tasks are not enough to audit misses. Why not immediately: can start with summary/task payload enrichment before a migration.
2. Move status/eligibility semantics into a shared canonical module used by browser row filtering, detail ingestion, domain validation, and tests.
3. Build a small replay harness from captured e-GP HTML/row text so parser changes can be regression-tested without hitting the live site.

### Big Architectural Changes (only if justified)
- Proposal: Split browser discovery into two phases: candidate collection and detail validation.
  - Pros: avoids losing projects because the list-page status is stale/ambiguous; makes audit evidence explicit; supports retrying only candidate details.
  - Cons: more artifacts/storage, more code paths, possible extra detail-page load.
  - Migration Plan: first persist candidate scan summaries in existing task/run JSON; next add optional candidate artifacts under run artifacts; later add DB tables if operators need searchable audit history.
  - Tests/Rollout: fixture parser tests, live canary for one tenant/keyword, compare old vs new candidate counts before enabling persistence changes broadly.

### Open Questions / Assumptions
- The screenshots are assumed to be from the same e-GP keyword search context and period as the latest `วิเคราะห์ข้อมูล` run. Even if they are from a manual verification session, they disprove the stronger claim that no eligible projects exist for the keyword.
- I did not run a new live browser crawl during this review; the conclusion is based on production DB rows, existing worker logs, code inspection, and the supplied screenshots.


## Review (2026-06-14 21:46:20 +07) - WS1 QCHECK header-derived columns

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree, limited to WS1 files from `coding-logs/2026-06-14-21-39-33 WS1 QCHECK Tasks (header-derived-columns).md`
- Commit Reviewed: working tree on 4b4bfe2a
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; targeted `nl -ba`/`rg` inspections for WS1 files; `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_invitation_rules.py tests/phase1/test_projects_and_runs_api.py -q`; inline eligibility status sanity check.

### Findings
CRITICAL
- No findings.

HIGH
- `apps/worker/src/egp_worker/browser_close_check.py:250` still opens close-check document revisits with `cells[5]`. The matcher above it was rewired to header-derived `project_name` and `status`, but it returns only the raw `cells` list to `_collect_documents_for_observation`. In the real seven-column layout confirmed by `tests/phase1/test_worker_browser_discovery.py:437`, index 5 is `สถานะโครงการ`; the view action is index 6. Any live close-check run with `include_documents=True` will therefore attempt to click the status cell, fail `_open_project_from_results_cell`, and silently return `downloaded_documents: []` for projects that should be revisited for new artifacts. Fix direction: carry the resolved `columns` mapping or `view` cell out of `_find_matching_result_on_page`, then use `cells[columns["view"]]` with a `len(cells) <= columns["view"]` guard. Add a regression test using the seven-column `_results_row(...)` fixture where only the view cell has a click target, and assert `_collect_documents_for_observation` opens that target and calls `collect_downloaded_documents`.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Assumed the QCHECK scope intentionally excludes unrelated modified coding logs and unrelated pre-existing env/dashboard drift noted in the task file.
- Assumed `status_matches_target` can remain as a legacy helper because non-diagnostic runtime references were absent; the old predicate is no longer part of the discover row filter.

### Recommended Tests / Validation
- Add and run a close-check document revisit regression covering the shifted seven-column layout and view index 6.
- Re-run: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_invitation_rules.py tests/phase1/test_projects_and_runs_api.py -q`.
- Existing targeted run in this review: 92 passed in 45.18s.

### Rollout Notes
- Do not ship WS1 with close-check document revisit enabled until the view-cell index is header-derived in `browser_close_check.py`.
- The main discovery path, row eligibility gate, domain ingest gate, and pagination cap looked consistent under this review.
