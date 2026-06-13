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
