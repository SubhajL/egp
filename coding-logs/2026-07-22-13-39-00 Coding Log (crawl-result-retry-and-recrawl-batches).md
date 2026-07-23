# Coding Log: crawl result retry and recrawl batches

- Started: 2026-07-22 13:39:00 +0700
- Goal source: `/Users/subhajlimanond/.codex/attachments/25f2d518-4e98-4c1a-853f-46937193f44b/pasted-text-1.txt`
- Starting checkout: `feature/keyword-group-lifecycle` at `f19531af40a6e004090234791f4db0feb89b5081`
- Required predecessor: PR #170 (`feature/keyword-group-lifecycle`) must land and exact merged `main` must be verified before implementation branches begin.
- Protected pre-existing work: this checkout already has an unstaged review append in `coding-logs/2026-07-21-12-41-53 Coding Log (keyword-groups-membership-restoration).md` and untracked `docs/TOR KEYWORDS.md`; neither belongs to this feature.
- Exploration note: Auggie semantic retrieval was attempted first and exceeded the required two-second limit. Planning therefore uses direct inspection plus exact-string searches of the files listed below.

## Requirements extracted from the incident specification

1. A worker result with `run_status="failed"` must be a failed dispatch attempt and must follow the existing bounded retry path; subprocess transport success cannot erase business failure.
2. A failed crawl must not mark a persistent browser profile successful/fresh.
3. Repeated e-GP application-error toasts must feed a host-shared, bounded cooldown/circuit breaker so one poisoned session cannot drain the queue.
4. A manual recrawl must receive a durable request/batch ID, and the Projects UI must summarize that batch rather than an arbitrary latest-ten-run window.
5. Only after protections are merged, deployed, and live-verified may the ten failed 2026-07-22 manual keywords be re-enqueued or drained in a bounded operation.
6. Preserve tenant isolation, PostgreSQL as source of truth, worker/control-plane ownership boundaries, and the standard one-PR-at-a-time lifecycle.

## Inspected current-state files

- `apps/worker/src/egp_worker/main.py`
- `apps/worker/src/egp_worker/browser_discovery.py`
- `packages/crawler-core/src/egp_crawler_core/rate_limiter.py`
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
- `apps/api/src/egp_api/services/discovery_dispatch.py`
- `apps/api/src/egp_api/executors/discovery_dispatch.py`
- `apps/api/src/egp_api/services/rules_service.py`
- `apps/api/src/egp_api/routes/rules.py`
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`
- `packages/db/src/egp_db/repositories/run_repo.py`
- `packages/db/src/migrations/001_initial_schema.sql`
- `packages/db/src/migrations/015_discovery_jobs_outbox.sql`
- `packages/db/src/migrations/028_keyword_group_lifecycle.sql`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/lib/run-progress.ts`
- `apps/web/src/app/(app)/projects/page.tsx`
- Related API, worker, rate-limiter, repository, frontend unit, and Projects E2E tests.

---

## Plan Draft A: contract first, first-class request model

### 1. Overview

Deliver three sequential PRs after PR #170: first make semantic crawl outcomes control retries/profile health and add the shared toast circuit; second add a first-class recrawl request model, job/run correlation, tenant-scoped status API, and batch-scoped UI; third add and exercise a dry-run-first recovery command for the exact ten failed runs. This is the most explicit and auditable design and keeps safety fixes live before any recovery mutation.

### 2. Files to change

PR A1, result semantics and circuit:

- `apps/worker/src/egp_worker/main.py` — canonical worker outcome/exit behavior.
- `apps/worker/src/egp_worker/browser_discovery.py` — record semantic site-error/site-success outcomes at the toast boundary.
- `packages/crawler-core/src/egp_crawler_core/rate_limiter.py` — host-shared toast streak and bounded cooldown.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` — parse worker stdout into a typed result; raise retriable semantic failures; update profile health only for accepted outcomes.
- `apps/api/src/egp_api/services/discovery_dispatch.py` — preserve job ID in the dispatch request and let semantic failure reuse bounded retry.
- `tests/concurrency/test_rate_limiter.py`, `tests/phase1/test_worker_browser_discovery.py`, `tests/phase1/test_worker_entrypoint.py`, `tests/phase1/test_api_discovery_spawn.py`, `tests/phase2/test_persistent_browser_profile.py`, `tests/phase2/test_discovery_dispatch.py` — RED/GREEN contract coverage.
- Example/runbook env files and `docs/` operational configuration references found by exact env-key search — document new circuit knobs.

PR A2, request correlation and UI:

- `packages/db/src/migrations/029_recrawl_requests_and_discovery_correlation.sql` — request table and nullable job/run correlations with indexes/FKs.
- `packages/db/src/egp_db/repositories/recrawl_request_repo.py` — tenant-scoped request creation and batch status projection.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py` — `recrawl_request_id` field and transactional manual-batch enqueue.
- `packages/db/src/egp_db/repositories/run_repo.py` — `discovery_job_id` and `recrawl_request_id` on runs plus latest-attempt batch query support.
- `apps/api/src/egp_api/services/discovery_dispatch.py` and `discovery_worker_dispatcher.py` — forward job/request identity into run creation.
- `apps/api/src/egp_api/services/rules_service.py` — create/return the durable request and provide status.
- `apps/api/src/egp_api/routes/rules.py` — extend POST and add tenant-scoped GET batch endpoints.
- `apps/web/src/lib/generated/openapi.json`, `apps/web/src/lib/generated/api-types.ts` — regenerated contracts only.
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/hooks.ts`, `apps/web/src/lib/run-progress.ts` — batch status client/query/presentation helpers; delete latest-window batch inference.
- `apps/web/src/app/(app)/projects/page.tsx` — retain/poll request ID and render exact counts.
- `tests/phase1/test_migration_runner.py`, `tests/phase2/test_rules_api.py`, `tests/phase2/test_discovery_dispatch.py`, `tests/phase2/test_openapi_generation_pipeline.py`, `apps/web/tests/unit/run-progress.test.ts`, `apps/web/tests/e2e/projects-page.spec.ts` — schema/API/UI coverage.

PR A3, bounded recovery:

- `scripts/requeue_failed_discovery_runs.py` — dry-run default; require tenant plus explicit run IDs and `--execute`; validate manual+failed outcomes and exact keywords before enqueue.
- `tests/operations/test_requeue_failed_discovery_runs.py` — validation, tenant isolation, idempotency, dry-run, and execute coverage.
- `docs/` crawler operations runbook selected by exact existing reference search — recovery procedure, evidence capture, and backout/stop conditions.

### 3. Implementation steps and functions

For each coherent slice: add/stub tests, run them and record the expected RED, implement the smallest passing change, refactor only if needed, then run formatter/lint/typecheck/tests before the next slice.

PR A1:

1. Add `WorkerDiscoveryResult` in `discovery_worker_dispatcher.py`; `_parse_worker_discovery_result(stdout, expected_run_id)` accepts exactly one final JSON object and validates `run_id`, `run_status`, optional `error`, and counts. Missing/malformed/mismatched output fails closed as retriable transport failure.
2. Change `SubprocessDiscoveryDispatcher.dispatch()` to capture stdout, append it to `worker.log`, parse the final result, and return the typed result only for `succeeded` or accepted `partial`. `failed` raises `DiscoverySpawnError` with the worker error and run ID; termination/entitlement rules stay as currently classified.
3. Change worker `main()` metrics so discovery `failed` is recorded as `error`; emit the JSON result before exiting nonzero. `partial` remains an accepted process result because replaying persisted projects is outside this incident scope.
4. Add `_record_persistent_profile_failure()`/profile invalidation and call it for semantic failed results. Only `succeeded` and `partial` call `_record_persistent_profile_success(source="crawl")`.
5. Extend `RateLimiterConfig` with site-error threshold, base cooldown, and max cooldown. `record_outcome("site_error")` increments a host-shared semantic streak and opens the same circuit with bounded exponential delay; `record_outcome("site_success")` resets only the semantic streak. Ordinary click `success` must not reset semantic toast history.
6. `_raise_on_site_error_toast()` records `site_error` before raising. Successful stabilized search results record `site_success`; pagination toast uses the same helper and therefore the same host-shared circuit.
7. Verify `DiscoveryDispatchProcessor.process_job()` turns the raised semantic failure into pending+backoff until `max_attempts`, preserves `last_error`, and stops same-call reclaims through `processed_job_ids`.

PR A2:

1. Add migration `029`: `recrawl_requests(id, tenant_id, source, requested_keyword_count, created_at, updated_at)`; `discovery_jobs.recrawl_request_id`; `crawl_runs.discovery_job_id` and `crawl_runs.recrawl_request_id`; tenant/time and FK indexes. All new correlations are nullable for old rows and non-manual jobs.
2. Implement `SqlRecrawlRequestRepository.create_manual_request()` as one transaction that records one request and its newly enqueued manual jobs; an already-active request is returned rather than creating overlapping ownership.
3. Implement `get_request_status(tenant_id, request_id)` and `get_latest_request_status(tenant_id)`. Aggregate requested, queued, running, retrying, succeeded, zero-result, partial, terminal-failed, failed keywords, and completion time from jobs plus the latest run per job; every query includes `tenant_id`.
4. Extend `DiscoveryJobRecord`, `build_discovery_job_values()`, and `DiscoveryDispatchRequest` with request/job IDs. `SubprocessDiscoveryDispatcher` creates each `crawl_run` with both IDs; each retry creates a new correlated run without overwriting earlier attempts.
5. POST `/v1/rules/recrawl` returns `request_id` plus existing queued fields. GET `/v1/rules/recrawl` returns the latest request or null; GET `/v1/rules/recrawl/{request_id}` returns the exact tenant-scoped request or 404.
6. Regenerate OpenAPI/types. Add `fetchRecrawlStatus()`/`useRecrawlStatus(requestId)` and replace `summarizeRecentKeywordRuns(latest 10)` with `summarizeRecrawlRequest(status)` or direct typed rendering.
7. Projects page stores the returned ID in session storage, restores the latest request after reload, polls only while nonterminal, invalidates projects when the batch advances/completes, and labels counts as jobs/keywords accurately.

PR A3:

1. Implement `load_failed_manual_runs()` to require explicit run IDs, one tenant, status `failed`, trigger `manual`, a resolvable profile, and exactly one task keyword per run; reject any mismatch before writing.
2. Implement `build_recovery_plan()` to dedupe profile+keyword, display all ten source run IDs/keywords, and detect existing pending/recovery jobs.
3. Implement `execute_recovery_plan()` to create one `source="operator_recovery"` request and `retry` jobs transactionally, returning the request ID. Default mode writes nothing; `--execute` is required.
4. After merge/deploy/migration/restart verification, query production read-only to resolve the ten exact run IDs, save a manifest outside git, run dry-run, require exactly ten accepted keywords and zero mismatches, execute once, then monitor the exact request ID. Stop on circuit-open, profile pause, unexpected keyword count, or any new semantic failure burst.

### 4. Test coverage

PR A1 tests:

- `test_worker_main_exits_nonzero_for_failed_discovery` — failed semantic result cannot exit zero.
- `test_parse_worker_result_rejects_missing_json` — absent result fails closed and retries.
- `test_parse_worker_result_rejects_mismatched_run_id` — cross-run output cannot complete job.
- `test_dispatcher_retries_failed_worker_result` — failed JSON keeps job pending with error.
- `test_dispatcher_accepts_succeeded_worker_result` — success JSON marks durable job dispatched.
- `test_dispatcher_accepts_partial_worker_result` — persisted partial remains accepted terminal attempt.
- `test_failed_result_does_not_refresh_persistent_profile` — semantic failure leaves profile stale.
- `test_site_error_circuit_opens_after_shared_threshold` — repeated toasts open host circuit.
- `test_site_error_cooldown_is_bounded_exponential` — repeated trips grow but cap cooldown.
- `test_transport_success_does_not_reset_site_errors` — click success cannot hide toast streak.
- `test_search_success_resets_site_error_streak` — confirmed results recover semantic circuit state.

PR A2 tests:

- `test_migration_adds_nullable_recrawl_correlations` — old jobs and runs migrate safely.
- `test_manual_recrawl_returns_durable_request_id` — POST returns tenant-owned batch identity.
- `test_overlapping_recrawl_returns_active_request` — duplicate click keeps one batch owner.
- `test_dispatch_forwards_job_and_request_ids` — run correlation survives subprocess boundary.
- `test_recrawl_status_uses_latest_attempt_per_job` — retries do not double-count keywords.
- `test_recrawl_status_counts_zero_partial_failed_retrying` — batch taxonomy matches durable state.
- `test_recrawl_status_is_tenant_scoped` — cross-tenant request returns not found.
- `test_projects_page_renders_requested_batch_only` — unrelated latest runs never affect summary.
- `test_projects_page_restores_batch_after_reload` — request identity survives browser refresh.
- `test_generated_api_types_are_current` — checked-in OpenAPI artifacts match server.

PR A3 tests:

- `test_recovery_defaults_to_dry_run` — command performs no writes by default.
- `test_recovery_rejects_nonfailed_or_nonmanual_run` — unsafe source run blocks whole batch.
- `test_recovery_rejects_cross_tenant_run_ids` — tenant isolation fails closed.
- `test_recovery_deduplicates_profile_keyword_pairs` — repeated historical attempts enqueue once.
- `test_recovery_execute_creates_one_correlated_request` — exact validated set writes atomically.
- `test_recovery_execute_is_idempotent` — repeated manifest cannot duplicate pending recovery.

### 5. Decision completeness

- Goal: make crawl semantic failure durable and retryable, prevent poisoned-session drain, expose truthful manual-batch progress, then recover exactly ten lost keywords.
- Non-goals: rename the entire queue state machine; add discovery attempt history beyond existing `crawl_runs`; retry `partial`; redesign browser automation; infer the upstream e-GP root cause; requeue arbitrary active keywords.
- Success: a failed JSON result leaves the job pending with backoff and error; profile freshness is not refreshed; two default toast failures open a shared circuit; POST returns a request ID; UI counts only that request; exact ten-keyword recovery is dry-run-proven, executed once, and reaches a terminal batch without silent loss.
- Public interfaces: three new circuit env vars; POST response gains `request_id`; GET latest/exact recrawl status endpoints; migration `029`; recovery CLI with explicit tenant/run IDs and `--execute`.
- Compatibility: new DB fields nullable; existing run list stays unchanged; POST only adds a response field; older rows have no batch and are excluded from batch API unless used as recovery sources.
- Failure policy: malformed worker output, mismatched run ID, failed status, missing recovery keyword/profile, cross-tenant IDs, and ambiguous active batches all fail closed. `partial` is accepted but visible. Circuit state is host-shared and blocks acquisition until cooldown.
- Rollout: land A1, deploy and verify; land/apply A2, deploy API then web; land A3; only then execute recovery. Backout A1 by reverting code/env while leaving no schema. Backout A2 by reverting readers/writers while nullable additive schema remains. Recovery backout is stop-only: do not delete audit rows; halt watcher and leave pending jobs recoverable.
- Observability: worker outcome metric must agree with run status; logs include parsed run ID/status/error; circuit state records last outcome/open-until; request API exposes retrying/failed counts; alert/operator stop on new toast burst, terminal failure, profile pause, or count mismatch.

### 6. Dependencies

- PR #170 merged and verified on exact `main`.
- GitHub Actions billing/check infrastructure restored, or explicit documented authorization to override the protected-check blocker.
- Local PostgreSQL for migration/integration gates; Node dependencies for frontend gates.
- Production DB tunnel/profile/watcher access only after code deployment; no production writes during coding.

### 7. Validation

- PR A1: targeted pytest files above; `ruff check`; `compileall`; three consecutive targeted pytest passes; supervisor-style seam test proving failed JSON -> pending job; inspect profile state and circuit file in temp dirs.
- PR A2: fresh and upgrade migration smoke; rules/dispatch API tests; generated API check; frontend unit, typecheck, lint, build, Projects Playwright; three consecutive relevant tests.
- PR A3: operations pytest three times; CLI `--help`; local seeded dry-run and execute/idempotency smoke.
- Each PR: wiring grep, QCHECK, formal `g-check`, commit/push/PR/checks/merge, local `main == origin/main`, exact-merge post-merge gates.
- Production: verify deployed SHA/cwd, migration `029`, watcher/tunnel/profile state, dry-run manifest count=10, executed request ID, batch status, queue state, run outcomes, circuit state, and no unrelated enqueue.

### 8. Wiring verification

| Component | Entry point | Registration/call site | Schema/table |
|---|---|---|---|
| `WorkerDiscoveryResult` parser | worker subprocess completion | `SubprocessDiscoveryDispatcher.dispatch()` | `crawl_runs.status`, `summary_json` |
| Semantic toast circuit | `_raise_on_site_error_toast()` and successful stable result | `get_default_rate_limiter()` in worker browser flow | host JSON state file, no DB |
| Profile failure invalidation | parsed failed worker result | dispatcher persistent-mode branch | `.egp-profile-state.json` |
| `recrawl_requests` repository | POST/GET recrawl service methods | app repository/service construction in `egp_api/main.py` | `recrawl_requests` |
| Job/request correlation | manual enqueue and dispatch claim | `RulesService` -> job repo -> processor | `discovery_jobs.recrawl_request_id` |
| Run/job correlation | dispatcher reserves run | `SubprocessDiscoveryDispatcher.dispatch()` -> `run_repo.create_run()` | `crawl_runs.discovery_job_id`, `recrawl_request_id` |
| Recrawl status API | `GET /v1/rules/recrawl[/{id}]` | existing rules router already included by API main | all three tables, tenant scoped |
| Projects batch status | Projects page load and POST response | `useRecrawlStatus()` -> `fetchRecrawlStatus()` | API only |
| Recovery command | `scripts/requeue_failed_discovery_runs.py` CLI | operator explicit invocation | old `crawl_runs`/`crawl_tasks`; new request/jobs |

### 9. Cross-language schema verification

- Python currently creates/queries `crawl_runs`, `crawl_tasks`, and `discovery_jobs`; migration names match those exact identifiers.
- TypeScript performs no direct SQL and consumes generated FastAPI contracts.
- Migration `029` must be verified across SQL migration, SQLAlchemy tables, repository row mappers, FastAPI schemas, generated OpenAPI, and TypeScript types before merge.
- Exact pre-migration searches: `rg -n 'discovery_jobs|crawl_runs|crawl_tasks' apps packages tests --glob '*.py' --glob '*.sql'`; `rg -n 'ManualRecrawl|RunResponse' apps/web apps/api`.

### 10. Decision-complete checklist

- [x] Goals/non-goals/success criteria locked.
- [x] Public API, env, migration, and CLI surfaces named.
- [x] Failed/partial/malformed/circuit/profile/tenant/dedup behaviors decided.
- [x] Every behavior has a defect-sensitive test.
- [x] Validation commands are scoped per PR.
- [x] Every component has runtime wiring and schema mapping.
- [x] Rollout, backout, production stop conditions, and recovery ordering specified.
- [x] No implementer decision remains open.

---

## Plan Draft B: schema-light result enforcement and JSON-tagged batches

### 1. Overview

Fix result parsing/profile/circuit exactly as in Draft A, but avoid a first-class request table: generate a request UUID in the POST handler, store it in `discovery_jobs` and `crawl_runs` nullable columns (or run `summary_json`), and derive status directly from those rows. Recovery uses the existing repository/API with an explicit request UUID rather than a dedicated request record.

### 2. Files to change

- Same PR B1 worker/circuit/dispatcher/test files as A1.
- `029_add_recrawl_request_id.sql`, `discovery_job_repo.py`, `run_repo.py`, rules service/routes, OpenAPI/types, web API/hooks/page, and their tests for B2.
- Recovery script/tests/runbook for B3; no `recrawl_request_repo.py` or `recrawl_requests` table.

### 3. Implementation steps and functions

1. Follow identical RED/GREEN implementation for worker result parsing, profile health, and the shared toast circuit.
2. `RulesService.queue_active_discovery_jobs()` generates a UUID and passes it to each job; POST returns it.
3. Dispatcher forwards job/request IDs into each run. `RunRepository.list_runs_by_request_id()` derives batch status from runs plus jobs.
4. GET status endpoints query by `request_id`; UI polls that UUID and removes latest-ten inference.
5. Recovery script assigns a fresh request UUID to the exact validated ten retry jobs.

### 4. Test coverage

- All A1 and A3 tests.
- `test_manual_recrawl_tags_all_jobs_with_request_id` — one UUID spans newly queued jobs.
- `test_status_derives_latest_attempt_without_request_row` — run/job projection yields exact counts.
- `test_empty_or_fully_deduped_request_is_not_reportable` — schema-light limitation is explicit.
- Same tenant, UI isolation, reload, OpenAPI, and migration tests as A2.

### 5. Decision completeness

- Goal/non-goals and failure policies match Draft A.
- Public surface is the same except no durable `recrawl_requests` record and no `source/requested_keyword_count` fields.
- Success requires at least one job to exist for every returned request ID; a fully deduped click must return an existing active request or a conflict.
- Rollout/backout and monitoring match Draft A, with fewer schema objects but less durable request intent.

### 6. Dependencies

- Same as Draft A; migration is smaller but still waits for PR #170 and restored/overridden checks.

### 7. Validation

- Same commands and three-run reliability gates as Draft A, plus upgrade tests proving nullable IDs on historical rows.

### 8. Wiring verification

| Component | Entry point | Registration/call site | Schema/table |
|---|---|---|---|
| Result parser/circuit/profile handling | subprocess/browser completion | same as Draft A | run/profile/host state |
| Request UUID | POST `/v1/rules/recrawl` | `RulesService.queue_active_discovery_jobs()` | `discovery_jobs.recrawl_request_id` |
| Run correlation/status | dispatcher + GET recrawl status | run repository and rules router | `crawl_runs.discovery_job_id`, `recrawl_request_id` |
| UI | Projects page POST/load | API hook | API only |
| Recovery | explicit CLI | operator | old runs, new jobs |

### 9. Cross-language schema verification

- Same exact identifier checks as Draft A, minus `recrawl_requests`.
- TypeScript remains generated-contract-only and performs no SQL.

### 10. Decision-complete checklist

- [x] Interfaces, tests, wiring, rollout, and failure policy specified.
- [x] Meaningful limitation documented: no durable zero-job request record or immutable requested count.
- [x] No implementation decision remains open inside this alternative.

---

## Comparative analysis

- Draft A strength: preserves request intent independently of mutable job/run attempts, provides immutable requested counts and source, makes reload/latest lookup truthful, and gives recovery an audit anchor.
- Draft A cost: one table and repository layer more; transactional batch creation requires careful SQLite/Postgres coverage.
- Draft B strength: fewer moving parts and a smaller additive migration.
- Draft B gap: request existence depends on jobs, a fully deduped request is awkward, requested-versus-enqueued counts can drift, and latest-request lookup lacks an authoritative row.
- Both comply with tenant scoping, control-plane ownership, TDD, nullable additive migration safety, generated contracts, and sequential PR delivery.
- The incident specifically demonstrated loss of batch intent, so Draft A's durable request is worth the modest schema cost.

---

## Unified Execution Plan

### 1. Overview

Use Draft A's first-class request model and Draft B's narrow additive rollout. Deliver three independent PRs after PR #170: (1) result/retry/profile/circuit safety, (2) durable request correlation and truthful UI, and (3) bounded recovery tooling plus the exact production recovery. Do not combine schema/UI work with the urgent semantic safety fix, and do not mutate production until all protections are deployed and live-verified.

### 2. Files to change

- PR U1: worker main/browser discovery, crawler-core rate limiter, API worker dispatcher/dispatch request, six focused Python test surfaces, config/runbook references.
- PR U2: migration `029`, new recrawl request repository, discovery job/run repositories, dispatch wiring, rules service/routes, generated OpenAPI/types, web API/hooks/progress/projects page, migration/API/frontend tests.
- PR U3: recovery CLI, operations tests, crawler operations runbook, and the current Coding Log.
- Preserve `docs/TOR KEYWORDS.md` and the pre-existing dirty Coding Log append unless separately archived with explicit scope.

### 3. Tests-first implementation sequence

1. Resolve predecessor: get PR #170 required checks green and merge normally, or obtain explicit documented override; sync local `main` to exact `origin/main`; archive/preserve existing log changes separately.
2. PR U1 RED: add failed-result/exit/parser/profile/circuit seam tests and run the exact targeted suite to capture the right failures.
3. PR U1 GREEN: implement typed stdout parsing, nonzero worker failure exit, retriable semantic exception, accepted-partial rule, profile failure invalidation, separate semantic toast outcomes, bounded host-shared circuit. Run targeted gates and three consecutive passes.
4. PR U1 review/land: verify call paths, self-QCHECK, stage intended files, formal `g-check`, fix issues, commit/push/PR/checks/merge, sync exact merged main, rerun post-merge gates.
5. PR U2 RED: add migration/repository/API/OpenAPI/frontend unit/E2E tests for durable request ID, latest-attempt aggregation, tenant isolation, duplicate click, reload, and unrelated-run exclusion.
6. PR U2 GREEN: implement migration/repositories/correlation/status endpoints, regenerate contracts, replace latest-ten summary with request polling. Run fresh+upgrade DB smoke, Python/web gates, and three consecutive relevant tests.
7. PR U2 review/land with the same wiring/QCHECK/`g-check`/exact-main process; apply migration before new API deployment, then deploy web.
8. PR U3 RED/GREEN: add dry-run-first exact-run recovery CLI and tests; validate one-transaction request/job creation and idempotency; review/land normally.
9. Production completion: verify deployed SHA/cwd/migration/watcher/tunnel/profile/circuit; resolve the exact ten source run IDs read-only; save and review dry-run manifest; execute once; monitor only returned request ID until terminal; prove no failed semantic result was marked dispatched, no failed result refreshed profile success, circuit stopped any repeated toast burst, and all ten keywords have explicit terminal outcomes.

Key functions and responsibilities:

- `main()` in worker: output one machine-readable result and exit consistently with semantic status.
- `_parse_worker_discovery_result()`: strict run-correlated stdout contract.
- `SubprocessDiscoveryDispatcher.dispatch()`: transport + semantic boundary, logging, result classification, profile health.
- `FileLockRateLimiter.record_outcome()`: independent 429/action and semantic-toast streaks with one acquisition gate.
- `_raise_on_site_error_toast()`/confirmed-search helper: semantic circuit inputs.
- `SqlRecrawlRequestRepository.create_manual_request()`: atomic tenant-scoped request/job creation.
- `get_request_status()`: latest-attempt-per-job truth projection.
- `RulesService.queue_active_discovery_jobs()`: entitlement/admission plus durable request orchestration.
- `fetchRecrawlStatus()`/`useRecrawlStatus()`: exact request polling.
- `build_recovery_plan()`/`execute_recovery_plan()`: fail-closed incident recovery.

### 4. Test coverage

Use the exact named tests from Draft A. Minimum defect-sensitive matrix:

- statuses: succeeded, zero-result succeeded, partial, failed, malformed/missing result, timeout, signal termination, entitlement denial;
- queue: first retry pending+error, max-attempt terminal failure, no same-call reclaim, partial accepted;
- profile: success refreshes, failed invalidates/does not refresh, warm failure unchanged;
- circuit: cross-instance shared threshold, transport success separation, explicit semantic recovery, exponential cap, acquire fail-fast;
- batch: requested/queued/running/retrying/succeeded/zero/partial/failed, repeated attempts count once, duplicate request, reload/latest, tenant isolation;
- recovery: dry-run, exact explicit IDs, invalid source all-or-nothing, dedupe, execute, idempotency.

### 5. Decision completeness

- Goal, non-goals, interfaces, success criteria, accepted-partial policy, fail-closed cases, rollout/backout, monitoring, and exact recovery stop conditions are locked as in Draft A.
- Defaults: site-error threshold `2`; base cooldown `300s`; max cooldown `1800s`; existing retry attempts `3` and delay `30s` remain unless tests expose a production mismatch. These are env-configurable and documented.
- `partial` is terminal/accepted for the queue but counted separately and can trip the semantic circuit when caused by a toast. It is not automatically replayed.
- Worker stdout is the immediate dispatch contract; persisted `crawl_runs` remains the audit authority and metrics source. Run ID mismatch fails closed.
- Recovery targets explicit historical run IDs, not a time-only query or all active keywords.

Acceptance checks:

- `./.venv/bin/python -m pytest tests/concurrency/test_rate_limiter.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_entrypoint.py tests/phase1/test_api_discovery_spawn.py tests/phase2/test_persistent_browser_profile.py tests/phase2/test_discovery_dispatch.py -q`
- `./.venv/bin/python -m pytest tests/phase1/test_migration_runner.py tests/phase2/test_rules_api.py tests/phase2/test_openapi_generation_pipeline.py -q`
- `(cd apps/web && npm run check:api-types && npm run test:unit && npm run typecheck && npm run lint && npm run build)`
- Targeted Projects Playwright spec after API mocks are batch-aware.
- `./.venv/bin/ruff check apps packages scripts tests` on touched Python scope and `./.venv/bin/python -m compileall` on touched packages.
- Relevant tests three consecutive times, QCHECK, and formal `g-check` before each commit.
- `./.venv/bin/python scripts/check_main_sync.py --json` plus exact local/origin/deployed SHA checks at each landing/deploy boundary.

### 6. Dependencies

- Same as Draft A. Current external blocker evidence: PR #170 is open/mergeable but `mergeStateStatus=BLOCKED`; required GitHub jobs fail before steps due the account billing lock recorded in the predecessor log. No protected-check bypass is assumed.

### 7. Validation

- Validation is proportional per PR, then repeated on exact merged commits.
- Production completion requires authoritative DB/job/run/request/profile/circuit evidence for each of the five incident requirements; a green local test suite alone is insufficient.

### 8. Wiring verification

| Component | Runtime entry point | Registration | Authoritative state |
|---|---|---|---|
| Worker result contract | `python -m egp_worker.main` spawned per job | `SubprocessDiscoveryDispatcher.dispatch()` | stdout JSON + `crawl_runs` |
| Retry classification | dispatcher raises into processor | `DiscoveryDispatchProcessor.process_job()` | `discovery_jobs` |
| Profile health | dispatcher accepted/failed branch | persistent profile mode | profile state JSON |
| Toast circuit | search/pagination toast helpers | default host limiter used by browser actions | limiter state JSON |
| Recrawl request | POST rules recrawl | existing rules router/service factory | `recrawl_requests` |
| Job correlation | request enqueue -> processor claim | discovery job repository | `discovery_jobs.recrawl_request_id` |
| Run correlation | dispatcher run reservation | run repository | `crawl_runs.discovery_job_id`, `recrawl_request_id` |
| Status API | GET recrawl endpoints | existing rules router inclusion | request+job+run projection |
| UI summary | Projects page load/POST | React Query hook/API client | exact API request ID |
| Recovery | explicit operator CLI | direct, documented invocation | validated old runs + one new request |

### 9. Cross-language schema verification

- SQL and Python use exact names: `recrawl_requests`, `discovery_jobs.recrawl_request_id`, `crawl_runs.discovery_job_id`, `crawl_runs.recrawl_request_id`.
- FastAPI response field names must match generated OpenAPI/TypeScript exactly: `request_id`, `requested_keyword_count`, `queued_count`, `running_count`, `retrying_count`, `succeeded_count`, `zero_result_count`, `partial_count`, `failed_count`, `failed_keywords`, `is_terminal`, timestamps.
- Run exact identifier searches across migrations, SQLAlchemy tables, row mappers, routes, generated schema/types, and UI before review.

### 10. Decision-complete checklist

- [x] No implementation decision remains open.
- [x] Every interface and exact name is listed.
- [x] Every behavior has at least one failing-first test.
- [x] Commands and expected outcomes are scoped.
- [x] Wiring covers every new module, migration, endpoint, hook, and CLI.
- [x] Rollout/backout/monitoring and recovery stop conditions are explicit.
- [ ] Lifecycle prerequisite is externally unblocked: PR #170 checks/merge.

## Planning checkpoint

Planning is complete. Implementation must not begin on a new feature branch until PR #170 is merged and verified, per the selected `g-coding` lifecycle. The current check blocker requires either GitHub billing restoration followed by successful reruns, or explicit user authorization for a documented protected-check override based on the already-recorded local gates.

## Review (2026-07-22 13:44:19 +0700) - predecessor Coding Log append

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feature/keyword-group-lifecycle`
- Scope: working tree, staged append to `coding-logs/2026-07-21-12-41-53 Coding Log (keyword-groups-membership-restoration).md`
- Commit: `f19531af40a6e004090234791f4db0feb89b5081`
- Commands Run: `git status --short --branch`; `git diff --staged --stat`; `git diff --staged --check`; bounded `sed` reads of all 518 appended lines; exact secret-pattern scan; current PR #170 metadata/check query.
- Auggie semantic retrieval exceeded the required two-second limit; direct staged-diff inspection was used.

### Findings

CRITICAL

- No findings.

HIGH

- No findings.

MEDIUM

- No findings.

LOW

- No findings.

The append is documentation-only, internally distinguishes the earlier executor outage from the later semantic-result defect, records production mutations and read-only checks explicitly, preserves commit/worktree provenance, contains no credential material, and keeps `docs/TOR KEYWORDS.md` outside its scope.

### Open Questions / Assumptions

- Operational PIDs, queue counts, and run IDs are timestamped incident evidence rather than claims about current runtime state.
- The open `partial` retry policy is resolved only in the new execution plan, not retroactively rewritten into the historical review.

### Recommended Tests / Validation

- No product test is required for a documentation-only append.
- `git diff --staged --check` passed.
- Verify the staged path is the only path included before commit.

### Rollout Notes

- This append has no runtime, schema, API, or configuration effect.
- Commit it to PR #170 before merging so the operational and review lineage is preserved.
- PR #170 remains externally blocked by GitHub's account billing lock; do not bypass protected checks without explicit authorization.

## Implementation Update (2026-07-22 13:45:58 +0700) - predecessor lineage preservation

### Goal

Preserve the uncommitted operational-recovery and crawl-result review evidence on PR #170, then use the new PR head as a current check-infrastructure canary before beginning the next implementation branch.

### What changed and why

- Staged only `coding-logs/2026-07-21-12-41-53 Coding Log (keyword-groups-membership-restoration).md`.
- Committed its 518-line append as `198301c31a00547f90bcfbe8e3feb305286835b0` with message `docs(log): record crawler recovery and dispatch review`.
- Pushed `feature/keyword-group-lifecycle`; local HEAD and `origin/feature/keyword-group-lifecycle` now match exactly.
- Left this new plan log untracked for the future implementation branch and left `docs/TOR KEYWORDS.md` untracked/untouched.

### TDD evidence

- Tests added or changed: none; this was documentation-only lineage preservation.
- RED: not applicable because no executable behavior changed.
- GREEN: the repository's staged pre-commit quality gates passed during `git commit`.

### Tests and review

- `git diff --staged --check`: passed before commit.
- Bounded inspection covered every appended line and an exact secret-pattern scan found no credential material.
- Formal `g-check`: no findings at any severity; report recorded immediately above.

### Wiring verification

- No runtime component, schema, route, or configuration changed.
- Git wiring verified by exact equality of local HEAD and remote feature-branch SHA at `198301c3`.

### Behavior and risk notes

- No product or production behavior changed.
- The push created fresh required checks. All seven GitHub Actions jobs and `claude-review` failed within seconds without executing steps.
- Current annotation: `The job was not started because your account is locked due to a billing issue.`
- Vercel Preview Comments passed; PR #170 remains open, mergeable, and protected-check blocked.

### Follow-ups / known gaps

- The first unified-plan step remains active: restore billing/check execution or obtain explicit authorization for a documented protected-check override, then merge and exact-main verify PR #170.
- Do not start PR U1 until that predecessor is landed.

## Blocker Recheck (2026-07-22 21:26:43 +0700) - resumed lifecycle

- Reverified local and remote feature-branch SHA equality at `198301c31a00547f90bcfbe8e3feb305286835b0`.
- PR #170 remains open, mergeable, and protected-check blocked; Vercel is green.
- Because more than eight hours had elapsed, reran CI Pipeline run `29897765077` as a fresh infrastructure canary.
- Attempt 2 failed every job within seconds without executing steps. Python Lint & Format check `88952199334` reports: `The job was not started because your account is locked due to a billing issue.`
- No product code, production data, schema, or configuration changed. No RED/GREEN test applies to this external infrastructure recheck.
- The prerequisite remains: restore GitHub billing/check execution or explicitly authorize a documented protected-check override before PR #170 can land and PR U1 can begin.

## Blocker Recheck (2026-07-23 07:44:21 +0700) - next-day resumed lifecycle

- PR #170 remained open, mergeable, and protected-check blocked on exact head `198301c31a00547f90bcfbe8e3feb305286835b0`.
- Reran CI Pipeline run `29897765077` because the prior canary was from the previous day.
- Attempt 3 failed every job within seconds without executing steps. Python Lint & Format check `89089509626` reports: `The job was not started because your account is locked due to a billing issue.`
- No product code, production data, schema, or configuration changed. No RED/GREEN test applies to this external infrastructure recheck.
- The next safe action remains external billing restoration or explicit authorization for a documented protected-check override.

## Implementation Update (2026-07-23 07:56:41 +0700) - PR U1 RED/GREEN

### Lifecycle prerequisite

- The user explicitly authorized an admin merge of PR #170 despite the protected checks being blocked by the recorded GitHub billing failure.
- Ran `gh pr merge 170 --squash --admin`; PR #170 is merged as `1de42db659be4ebbd14b7686eef149479b307fc8`.
- Fast-forwarded local `main` and verified exact equality with `origin/main` at `1de42db659be4ebbd14b7686eef149479b307fc8`.
- Created `fix/discovery-result-retry-circuit` from that exact merged base.
- Preserved the untracked incident plan and left `docs/TOR KEYWORDS.md` untouched.

### Goal

Make discovery dispatch honor the worker's semantic run result, stop failed crawls from refreshing persistent-profile success, and feed repeated e-GP site-error toasts into the existing host-shared circuit breaker before any incident recovery jobs are queued.

### Tests-first evidence

- Auggie semantic retrieval was attempted with the required detailed U1 query and exceeded the two-second limit; bounded direct reads of the exact planned files and nearest `AGENTS.md` guidance were used.
- RED command: `./.venv/bin/python -m pytest tests/phase1/test_worker_entrypoint.py tests/phase1/test_api_discovery_spawn.py tests/phase2/test_persistent_browser_profile.py tests/concurrency/test_rate_limiter.py tests/phase1/test_worker_browser_discovery.py -q`.
- RED result: `8 failed, 115 passed`; every failure matched a new contract seam: failed-discover exit, captured stdout, semantic failure parsing, profile freshness, site-error config/cooldown, and toast outcome wiring.
- Focused GREEN result: the eight defect tests passed after implementation except one test-fixture setup error; the fixture was corrected to snapshot the helper-created warm state before dispatch, after which all eight passed.
- Expanded GREEN command including dispatch retry and API dispatcher compatibility tests: `./.venv/bin/python -m pytest apps/api/tests/test_browser_isolation.py apps/api/tests/test_dispatch_trigger_metadata.py tests/phase1/test_worker_entrypoint.py tests/phase1/test_api_discovery_spawn.py tests/phase2/test_persistent_browser_profile.py tests/concurrency/test_rate_limiter.py tests/phase1/test_worker_browser_discovery.py tests/phase2/test_discovery_dispatch.py -q`.
- Expanded GREEN result: `141 passed in 66.29s`.
- Focused ruff command over every touched Python source/test path passed with `All checks passed!`.

### Implementation and wiring

- `egp_worker.main.run_worker_job()` now exposes the persisted run summary error in the stdout contract; `main()` prints the machine-readable failed result and exits `1` when a discover run is semantically `failed`.
- `SubprocessDiscoveryDispatcher.dispatch()` now captures stdout separately, appends it to `worker.log`, validates exact `run_id` plus terminal status, and raises retriable `DiscoverySpawnError` for a semantic `failed` result even when the process exit code is zero. `succeeded` and `partial` remain accepted terminal results.
- Persistent profile success remains after the accepted-result boundary, so a semantic failure exits before `source=crawl` or `last_success_at` can be refreshed.
- `FileLockRateLimiter` now maintains independent `consecutive_site_errors` and `site_error_trip_count` state, opening the same host-shared acquisition circuit after two toasts with exponential `300s` to `1800s` cooldowns. Ordinary transport success does not erase the semantic-toast streak; confirmed search success does.
- Search-submit, search-results, restore, and pagination toast paths record `site_error`; confirmed search outcomes record `site_success`.
- Added production example env values and deployment guidance for `EGP_EGP_SITE_ERROR_THRESHOLD`, `EGP_EGP_SITE_ERROR_BASE_SECONDS`, and `EGP_EGP_SITE_ERROR_MAX_SECONDS`.

### Current boundary

- U1 implementation is GREEN locally but not yet reviewed, committed, submitted, or merged.
- No production command, database mutation, deploy, or incident recrawl has been performed.
- Next: run repeated quality gates, explicit wiring checks, self-QCHECK, staged formal `g-check`, then submit and land U1 before starting request/batch correlation.

## QCHECK (2026-07-23 08:10:36 +0700) - PR U1

### Scope and call-path review

- Reviewed the complete U1 diff against root/API/worker/package `AGENTS.md` guidance and root `CLAUDE.md`.
- Traced queue entry through `DiscoveryDispatchProcessor.prepare_for_dispatch()` / claim / `SubprocessDiscoveryDispatcher.dispatch()`, worker `main()`, persisted workflow result, stdout validation, retry exception, persistent-profile state, and the browser rate-limiter call sites.
- Verified the shared-circuit preflight is wired in both runtime compositions: `apps/api/src/egp_api/bootstrap/services.py` and `apps/api/src/egp_api/executors/discovery_dispatch.py` pass the dispatcher as `pre_dispatch_preparer`.
- Verified every new env var is read by `RateLimiterConfig.from_env()`, present in the production env example, documented in the deployment runbook, and asserted in tests.

### Findings fixed during skeptical review

- HIGH: merely skipping a new success timestamp left a previously fresh profile reusable after a semantic crawl failure. Added explicit `crawl_failure` state that removes `last_success_at`, records bounded failure detail, and forces the next eligible dispatch through profile warm-up.
- MEDIUM: capturing a potentially long worker stdout stream directly in a pipe could grow parent memory during multi-hour crawls. Replaced it with a disk-spilling `SpooledTemporaryFile`, bounded the parsed tail to 64 KiB, and preserved stdout in `worker.log`.
- HIGH: the worker-side circuit stopped outbound actions but could still let the queue claim remaining jobs and consume retry attempts while the circuit was open. Added the same host-shared circuit check to `prepare_for_dispatch()` so processing stops before claim.
- MEDIUM: the initial test matrix lacked accepted `partial`, missing/malformed stdout, strict run-ID mismatch, cross-instance shared state, and exponential cap coverage. Added all five cases plus compatibility updates for every subprocess fake that represents a successful worker.

### Final QCHECK result

- CRITICAL: no findings.
- HIGH: no open findings.
- MEDIUM: no open findings.
- LOW: no open findings.
- No schema, tenant-scoped query, frontend contract, production data, or secret-handling surface changed in U1.

### Reliability and quality gates

- Final expanded defect/compatibility suite: `159 passed` on three consecutive runs (`66.70s`, `66.76s`, `67.04s`).
- The suite includes worker entrypoint/result, subprocess dispatch, immediate-dispatch compatibility, persistent profile, queue retry/preclaim, browser toast paths, and cross-process rate-limiter behavior.
- Touched-file `ruff`: passed.
- `compileall` for API, worker, and crawler-core source: passed.
- `git diff --check`: passed.
- Exact base verification: branch HEAD and `origin/main` are both `1de42db659be4ebbd14b7686eef149479b307fc8` before the U1 commit.
- Focused credential-pattern scan of every intended source/test/doc file: no matches.

### Wiring verification table

| Component | Wired | Evidence |
|---|---|---|
| Worker semantic result/exit | YES | `run_worker_job()` supplies run status/error; `main()` prints failed result and exits 1 |
| Dispatcher result parser | YES | `dispatch()` drains bounded stdout tail, validates exact run ID/status, and raises retriable semantic error |
| Queue retry and circuit deferral | YES | processor retries dispatcher exceptions; both runtime constructors register dispatcher preflight before claim |
| Persistent profile failure | YES | semantic failed branch writes `crawl_failure`; accepted branch alone writes `crawl` success |
| Site-error circuit | YES | submit/results/restore/pagination toast paths record `site_error`; confirmed search records `site_success` |
| Circuit configuration | YES | runtime env loader, production example, deployment docs, and env tests use identical names |

### Remaining lifecycle work

- Stage only the intended U1 files plus this Coding Log, run formal `g-check`, fix any findings, then commit/push/open PR/check/merge/exact-main verify.
- `docs/TOR KEYWORDS.md` remains untracked and explicitly excluded.

## Review (2026-07-23 08:11:53 +0700) - working-tree PR U1

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `fix/discovery-result-retry-circuit`
- Scope: staged working tree based on `1de42db659be4ebbd14b7686eef149479b307fc8`
- Commands Run: staged status/name/stat/check inspection; bounded staged source and test diff inspection; exact line-number reads; entrypoint/config/wiring identifier searches; three consecutive 159-test runs; touched-file `ruff`; API/worker/crawler-core `compileall`; focused credential-pattern scan.
- Auggie semantic retrieval exceeded the required two-second review limit; the review continued with the bounded direct inspection and exact-string wiring evidence above.

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

- `partial` is intentionally accepted as a terminal queue outcome, while any pagination toast that caused it remains recorded in the shared semantic circuit.
- The production discovery executor and its child worker share the limiter state path on one host/container; this is the existing host-sharing architecture for `FileLockRateLimiter`.
- With the supported production worker count of one, the pre-claim circuit check stops the batch before another job is claimed. Already-running parallel workers in a future higher-concurrency configuration still rely on acquisition fail-fast.

### Recommended Tests / Validation

- Current validation is sufficient for commit: 159 relevant tests passed three consecutive times, lint/compile/diff checks passed, and transport plus semantic failure boundaries are covered.
- After merge, rerun the focused U1 acceptance suite on the exact merged `main` commit.
- Before incident recovery, deploy and live-verify the executor/worker SHA plus the shared limiter/profile state paths; do not enqueue the ten keywords in U1.

### Rollout Notes

- New optional env vars default safely to threshold `2`, base cooldown `300s`, and maximum cooldown `1800s`; rollback can restore the prior artifact without a schema change.
- Worker stdout remains preserved in `worker.log`; parsing uses a bounded 64 KiB tail from a disk-spilling spool.
- Failed semantic runs now invalidate persistent-profile freshness and retry through the existing queue policy. No migration, API response, or frontend contract changes in this PR.

## Lifecycle Update (2026-07-23 08:44:20 +0700) - U1 landed

- Committed U1 as `999f3cade3ba0e8aa3e8f71435914c786fa768bd` and opened PR #171: `https://github.com/SubhajL/egp/pull/171`.
- All GitHub Actions jobs again failed before executing because the account remained locked for billing; Vercel was the only executable green check.
- Under the user's explicit admin-merge authorization, squash-merged PR #171 as `0d7bf7d1db8089966190d4c88289b866b9e6bbaa`.
- Fast-forwarded local `main`, verified exact equality with `origin/main`, and reran the 159-test U1 acceptance suite on exact merged `main`; all 159 passed in `67.08s`.
- Created `feature/recrawl-request-batches` from exact U1 main. No production deploy, database migration, or recovery mutation was performed.

## Implementation Update (2026-07-23 08:44:20 +0700) - PR U2 durable recrawl batches

### Goal and contract

- Added first-class, tenant-owned manual recrawl requests with stable request IDs.
- POST `/v1/rules/recrawl` now returns `202` plus `request_id`; GET `/v1/rules/recrawl/{request_id}` returns exact batch counts for queued, running, retrying, succeeded, zero-result, partial, and terminal-failed keywords.
- The latest run per discovery job controls its result, so retries do not double-count and unrelated runs cannot enter the request projection.
- The Projects page stores the request ID across reloads, polls only that request while nonterminal, refreshes projects at terminal completion, and no longer uses the latest-ten-run heuristic for the batch summary.

### TDD evidence

- Initial backend RED failed at the intended contract boundary because POST had no `request_id` and no exact status endpoint.
- Focused backend GREEN covered migration upgrade, request creation/status, duplicate click, profile-created job attachment, tenant isolation, latest-attempt recovery, partial/zero/failed taxonomy, and dispatcher-to-run correlation.
- Frontend RED failed because `fetchRecrawlRequestStatus()` did not exist; GREEN added generated-contract wrappers, polling, local-storage restore, and exact-request browser assertions.
- Three consecutive expanded backend runs passed `122` tests each (`6.89s`, `6.67s`, `6.84s`). A subsequent focused manual-recrawl run passed `12` tests after the final mixed-state review fix.
- Frontend unit suite: `50 passed`; Projects browser suite: `8 passed`; full browser suite: `43 passed`; production Next build passed; OpenAPI drift check and TypeScript typecheck passed.

### Implementation and wiring

- Migration `029_recrawl_request_correlation.sql` creates `recrawl_requests`, adds nullable `discovery_jobs.recrawl_request_id`, and adds nullable `crawl_runs.discovery_job_id` plus `crawl_runs.recrawl_request_id` with FK/query indexes.
- `SqlRecrawlRequestRepository.create_request()` creates/attaches request jobs in one transaction and takes a PostgreSQL tenant-row lock so concurrent duplicate clicks serialize. SQLite retains the same transaction without the PostgreSQL-only lock.
- Admission counts only jobs not already covered by a pending request, preventing duplicate clicks from falsely exceeding the queue cap.
- `DiscoveryDispatchProcessor` forwards the durable job/request IDs; `SubprocessDiscoveryDispatcher` reserves every retry run with both correlations.
- Bootstrap registers the repository in app state and injects it into `RulesService`; route auth and tenant resolution remain at the request boundary.
- Generated OpenAPI and TypeScript types are current; the web hook stops its five-second poll when `is_terminal=true`.
- The remote crawler runbook documents the POST request ID and exact GET status flow.

### QCHECK findings fixed

- MEDIUM: a mixed request with one terminal keyword and another pending keyword could add a second discovery job for the already-terminal keyword when POST was repeated. The repository now treats every keyword already owned by the active request as covered, while still attaching genuinely new keywords; a regression test proves the request remains two jobs with one failed and one queued.
- MEDIUM: admission originally added every active keyword to the current pending count, so a duplicate click at the queue cap could be rejected even though it added no work. Admission now subtracts pending/active-request coverage; the duplicate test runs with `max_queued_keywords=1`.
- MEDIUM: the repository-wide suite exposed U1 worker test doubles without `summary_json`. The semantic-result reader now treats an absent summary as empty; all 15 worker-job compatibility tests pass.
- LOW: a PostgreSQL row lock initially assumed every SQLite API fixture seeded a tenant row. The lock is now explicitly PostgreSQL-only; production serialization is preserved and SQLite tests retain transactional behavior.

## Review (2026-07-23 08:44:20 +0700) - working-tree PR U2

### Reviewed

- Complete working-tree diff across migration, SQLAlchemy models/repositories, bootstrap, rules API/service, dispatch/run correlation, generated contracts, Projects UI/hooks, tests, worker compatibility fix, and runbook.
- Traced POST admission and atomic enqueue through claimed job, reserved retry run, exact tenant-scoped status aggregation, React Query polling, reload restoration, and terminal project refresh.
- Verified migration prefix `029` is the next unique prefix and historical rows remain valid through nullable correlations.

### Findings

CRITICAL

- No findings.

HIGH

- No findings.

MEDIUM

- No open findings. Three medium findings found during skeptical review were fixed and regression-tested as recorded above.

LOW

- No open findings. The SQLite fixture compatibility issue was fixed without weakening the PostgreSQL locking path.

### Open questions and residual risk

- Multiple overlapping active request IDs for the same desired keyword set are treated as an invariant violation and fail closed. PostgreSQL tenant-row serialization prevents new overlaps through this API.
- The request ID remains in browser local storage after terminal completion so the truthful terminal summary survives reload; a new request replaces it, and tenant-scoped 404 clears stale cross-tenant state.
- Full repository Python verification is being rerun after the final review fixes; commit is not allowed until it passes.

### Final pre-commit verification

- Repository-wide Python suite passed: `1301 passed, 108 warnings in 168.21s`.
- Final all-Python `ruff`, `compileall`, and `git diff --check` passed.
- The recorded warnings are the existing Python 3.12+ SQLite datetime-adapter deprecations in document, rules, and tenant-storage tests; no test failed or was skipped to obtain the green gate.

## Lifecycle Update (2026-07-23 08:59:49 +0700) - U2 landed

- Committed U2 as `7b72acc1c6748b93100c5d764f301f72887c77c5` and opened PR #172: `https://github.com/SubhajL/egp/pull/172`.
- GitHub Actions again stopped before execution because the account remained billing-locked; the exact annotations were reviewed and no code test ran remotely.
- Under the user's explicit admin-merge authorization, squash-merged PR #172 as `b9b9b2825d2cf9172f05f78085355fd064dcb47e`.
- Fast-forwarded local `main`, verified exact equality with `origin/main`, then passed the exact-main U2 gates: `123` relevant backend tests, `50` frontend unit tests, TypeScript typecheck, and OpenAPI drift.
- Created `fix/bounded-failed-run-recovery` from exact U2 main. Production remained unchanged.

## Implementation Update (2026-07-23 08:59:49 +0700) - PR U3 bounded recovery

### Goal and contract

- Added a dry-run-first command that accepts only one tenant UUID plus explicit source run UUIDs; it never discovers recovery scope from a time window or broad status query.
- Validation fails closed for missing/cross-tenant/nonfailed/nonmanual runs, unresolved or paused profiles, ambiguous discover tasks, duplicate source IDs, count mismatches, and matching pending jobs.
- Recovery jobs are deduplicated by profile plus case-folded keyword. The production CLI requires both the exact source-run count and the exact resulting job count to equal `--expected-count`, which defaults to `10` for this incident.
- Execution creates one `source=operator_recovery` request and `retry` jobs transactionally. A manifest-derived idempotency key returns the same request on an identical rerun without adding jobs.
- Migration `030_operator_recovery_requests.sql` adds the additive request source and tenant-scoped idempotency key needed for the audit trail. Existing U2 request rows migrate to `source=manual`.

### TDD evidence

- Initial RED failed during collection because `requeue_failed_discovery_runs` did not exist.
- GREEN operations suite passed `10` tests covering default dry-run/no writes, unsafe source rejection, tenant isolation, paused/ambiguous source rejection, profile+keyword deduplication, exact-count and pending-job guards, execution-time revalidation, one-request execution, SQLite behavior, and migrated-PostgreSQL idempotent re-execution.
- The complete migration-runner suite passed `4` tests, including an upgrade from pre-`030` data and the tenant/idempotency uniqueness constraint.
- Auggie semantic retrieval was attempted for U3 but returned HTTP `402`; implementation continued with bounded reads of the exact repository, migration, run/task/profile, CLI, test, and runbook seams.

### Production boundary

- No production command, deployment, migration, request creation, or recovery job mutation has been performed in U3 yet.
- The runbook requires the crawler watcher to be stopped, the in-box executor to remain at zero replicas, circuit/profile health to be verified, and the exact ten-run dry-run manifest to be saved and reviewed before `--execute`.
- Stop-only backout remains authoritative: on an unexpected count, pending-job conflict, open circuit, profile pause, or new semantic-failure burst, do not delete request/job audit rows and do not enqueue more work.

### QCHECK findings fixed

- HIGH: a plan could become stale between dry-run construction and execution if an operator paused its profile. Execution now rebuilds and compares the exact manifest immediately before enqueue; a regression test pauses the profile after planning and proves zero writes.
- MEDIUM: the transactional repository initially rejected only exact-case pending keywords, while the dry-run detector used case-folded identity. The recovery transaction now performs the same profile-plus-case-folded conflict check, preventing a case-variant duplicate under a concurrent enqueue.

### Final pre-review verification

- The expanded recovery/recrawl/dispatch/runbook matrix passed `85` tests three consecutive times.
- Repository-wide Python verification passed: `1312 passed, 108 warnings in 175.09s`.
- Full `ruff`, Python `compileall`, staged diff check, migration prefix inspection, and staged credential-pattern scan passed. The warnings remain the existing Python 3.12+ SQLite datetime-adapter deprecations.

## Review (2026-07-23 09:07:53 +0700) - working-tree PR U3

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `fix/bounded-failed-run-recovery`
- Scope: staged working tree based on `b9b9b2825d2cf9172f05f78085355fd064dcb47e`
- Commands Run: staged status/name/stat/check and targeted diff inspection; exact-string wiring and credential scans; three consecutive 85-test recovery/recrawl/dispatch runs; full 1312-test Python suite; all-Python `ruff` and `compileall`; PostgreSQL fresh/upgrade migration and recovery integration tests.
- Auggie returned HTTP `402` during the required semantic review attempt, so review used the bounded direct-inspection fallback.

### Findings

CRITICAL

- No findings.

HIGH

- No open findings. The stale-plan execution issue found during skeptical review was fixed and regression-tested before this formal disposition.

MEDIUM

- No open findings. Transactional case-folded pending-job detection was aligned with the dry-run identity rule and tested.

LOW

- No findings.

### Open Questions / Assumptions

- The exact incident scope remains ten distinct failed manual runs resolving to ten distinct active profile/keyword pairs; production dry-run must prove both counts before mutation.
- Migrations `029` and `030` must be applied before deploying code that selects or writes the new request columns.
- The local Mac remains the sole discovery claimer; the production `discovery-executor` must remain at zero replicas throughout recovery.

### Recommended Tests / Validation

- Current pre-commit coverage is sufficient: three stable relevant runs, migrated PostgreSQL execution/idempotency, full repository tests, lint, compile, and diff checks all passed.
- After merge, rerun the 85-test matrix on exact `main`, deploy/apply migrations in safe order, and capture a read-only ten-run dry-run manifest before `--execute`.

### Rollout Notes

- Additive migration defaults historical/manual requests to `source=manual`; rollback may leave its nullable idempotency column and audit rows in place.
- Recovery has no broad selector and no delete/backout mutation. An identical manifest returns the existing request; any different matching pending work fails closed.
- Stop the watcher before validation and execution, then monitor only the returned request ID. On circuit/profile/count/semantic stop conditions, leave durable rows intact and halt further work.

## Review (2026-07-23 18:04:01 +0700) - system

### Reviewed

- Repo/worktree: `/Users/subhajlimanond/dev/egp-review-crawler-hiccups`
- Branch/base: `review/crawler-hiccup-retro-20260723` at exact `origin/main`
  `6882850cb79930beb7ca14c5c8500a54e0605134`
- Scope: retrospective of apparently unexplained crawl stops, especially stale runs blocking
  new work, accepted recrawls producing no visible run, semantic failures being lost, profile
  pauses, bounded commands exiting after a small number of keywords, and the 2026-07-23
  recovery stopping after two keyword failures.
- Sources: `docs/PRD.md`, `TRACKS.md`, `docs/REMOTE_LOCAL_CRAWLER.md`,
  `docs/OBSERVABILITY.md`, current API/worker/database/web code and tests, the crawl-related
  Coding Logs from 2026-05-21 through 2026-07-23, and the production recovery evidence in
  `/tmp/egp-recovery-20260723-Dy1cL8/{stop-state,final-state}.json`.
- Auggie semantic retrieval was unavailable with HTTP `402`; review used the skill's bounded
  direct-inspection fallback.
- Validation:
  `/Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest
  tests/operations/test_remote_crawl_assets.py
  tests/phase2/test_persistent_browser_profile.py
  tests/phase2/test_discovery_dispatch.py tests/phase2/test_rules_api.py -q`
  passed: `70 passed, 2 warnings in 4.10s`.

### Executive conclusion

There was no single mysterious crawler failure. The incidents came from several independent
state machines being presented as one "crawl" operation:

1. persisted crawl-run state in Postgres;
2. durable queue and retry state in Postgres;
3. the Mac launchd watcher and SSH tunnel;
4. local persistent-profile readiness;
5. a host-local site-error circuit;
6. worker process transport status;
7. worker semantic crawl status; and
8. operator recovery policy.

Before the recent fixes, each seam had at least one place where the wrong signal was treated as
authoritative. Some were implementation defects now fixed; others were fail-closed safeguards
that worked as designed but were invisible to the API/UI; the "two keywords then stop" event was
an operator-policy stop caused by an undefined runbook phrase, not a crawler or circuit stop.

### As-Is pipeline

```text
Projects UI
  | POST recrawl; poll exact request ID
  v
API admission --------------------> crawl_runs
  | count "active" by 3h age           ^
  |                                    | worker writes status/summary
  v                                    |
recrawl_requests -> discovery_jobs ----+
                        |
                        | production queue reached through SSH tunnel
                        v
Mac launchd watcher -- pre-claim gates
  |                      |- shared site-error circuit JSON
  |                      |- persistent-profile lock/state JSON
  |                      `- warm/preflight
  |
  `-> claim pending job (60s stale lease, no heartbeat)
          |
          v
     one-shot worker subprocess -> real Chrome/e-GP
          |
          |- transport: process exit/stdout
          `- semantic: succeeded/partial/failed + reason
                         |
                         v
                dispatched OR pending+backoff OR failed
```

The exact recrawl-request correlation is now durable. The remaining observability problem is
that the API can report queue/run outcomes but not whether the out-of-process Mac runtime is
loaded, the tunnel is usable, the profile requires an operator, or the circuit is cooling down.

### Incident reconstruction

| Symptom | Actual cause | Reasoning/implementation gap | Current disposition |
|---|---|---|---|
| An old run prevented `Crawl ใหม่` | Any `queued`/`running` row counted as active forever | A status label was treated as a live lease; there was no freshness/reconciliation contract | Fixed by the three-hour admission cutoff and stale-run UI, but the duplicated freshness logic still drifts |
| Recrawl accepted but no run appeared | The Mac watcher was not loaded; in another start, it raced the tunnel | Queue acceptance was mistaken for executor health; API/UI had no watcher/tunnel status | Runtime was restored, but health visibility and startup readiness remain open |
| Jobs stayed pending at attempt zero | Profile state had reached two warm failures and required an operator | Intentional fail-closed behavior lived only in local JSON/logs, so it looked like a no-op | Safeguard is correct; control-plane visibility is open |
| A failed keyword looked dispatched | Worker persisted `run_status=failed` while its process contract still appeared successful | OS process success was used as business success; failed crawl also refreshed profile freshness | Fixed in U1 with strict run-correlated stdout, semantic retry, and profile invalidation |
| Batch progress was confusing | UI inferred one action from the latest ten runs | A documented non-authoritative heuristic was used during operations as if it were batch truth | Fixed in U2 with durable requests/job/run correlation; recent activity remains a separate view |
| Manual `crawl 1`, `crawl 2`, or default `crawl 5` exited | `crawl [N]` is explicitly a one-shot bounded command | Normal completion did not prominently report the requested limit and remaining queue | Behavior is correct; terminal operator output remains too weak |
| Recovery stopped after two failed keywords | An operator applied "new semantic-failure burst" as two consecutive heterogeneous failures | The runbook provided neither a threshold nor a failure taxonomy | Open policy defect; resume proved the stop was premature |

### Findings

CRITICAL

- No open critical finding. The production recovery reached a terminal state and no current
  evidence shows silent semantic failures being marked dispatched.

HIGH

1. **[OPEN, reasoning/policy] "Semantic-failure burst" is undefined and caused a false stop.**
   `docs/REMOTE_LOCAL_CRAWLER.md:265-267` says to stop on a new burst but defines neither
   which failure classes count nor how many constitute a burst. The captured stop state says
   `"two consecutive semantic failures after three successful recovery jobs"` while the
   circuit was closed, the profile was active, the tunnel/API were healthy, and the jobs were
   still retryable. The two failures were not equivalent: a pagination site error after page
   13 and `keyword_no_results`; a preceding retry was `no_eligible_rows`. After resume, the
   pagination job succeeded on attempt two, while the two stable anomalies exhausted three
   attempts. Final result: seven succeeded, one explicit zero-result, two failed, 35 projects.
   The pause added operator intervention without protecting a failing shared dependency.

2. **[OPEN, implementation/operability] The control plane cannot explain a blocked queue.**
   `prepare_for_dispatch()` correctly stops before claim for an open circuit, busy profile, or
   failed/paused warm (`discovery_worker_dispatcher.py:646-679`), but those reasons exist only
   in Mac logs and host-local JSON. The exact request endpoint reports counts and failed
   keyword names (`recrawl_request_repo.py:462-508`) but not watcher heartbeat, tunnel health,
   profile action required, circuit reset time, job attempt/retry time, or latest failure
   class. Therefore "queued and not moving" still has no product-visible explanation.

3. **[OPEN, implementation] A 60-second claim lease has no heartbeat although crawls can run
   for minutes or hours.** `DiscoveryDispatchProcessor` defaults
   `claim_stale_after_seconds=60` (`discovery_dispatch.py:67-76`), and the repository reclaims
   pending jobs whose `processing_started_at` crosses that threshold
   (`discovery_job_repo.py:318-439`). The supported single-worker/zero-in-box-executor topology
   reduces the chance of collision but does not make ownership durable. A second dispatcher,
   restart overlap, or future concurrency can duplicate an alive crawl. This risk was already
   recorded in the 2026-05-21 Coding Log and remains unresolved.

MEDIUM

1. **[FIXED ROOT CAUSE, OPEN DRIFT] Stale crawl rows used to block new work indefinitely.**
   The regression and fix are documented in the 2026-06-17 log at lines 391-449. Current API
   admission uses only `started_at`/`created_at` (`run_repo.py:813-847`), while the frontend
   independently hard-codes the same three-hour limit and also considers
   `live_progress.updated_at` (`run-progress.ts:16,57-84`). A legitimate run older than three
   hours with fresh progress can therefore be active in the UI but stale for API admission.
   The original stale rows also remain historically mislabeled unless explicitly reconciled.

2. **[FIXED] Semantic failure was lost across the subprocess boundary.** Before U1, a worker
   could persist a failed run yet be accepted from its process-level result, causing a job to
   become `dispatched` and a bad profile to look fresh. Current code validates the exact run
   ID/status, raises retryable failure for semantic `failed`, and records profile success only
   after accepted completion (`discovery_worker_dispatcher.py:826-926`). The underlying
   reasoning failure was testing process transport and business outcome separately without an
   end-to-end contract test.

3. **[OPEN, operability] One-shot completion is too easy to mistake for a stop.**
   `scripts/run_remote_crawl.sh:17-22,57-63` documents that `crawl [N]` drains at most N jobs
   and exits; the executor logs only `"Processed N pending discovery dispatch jobs"`
   (`executors/discovery_dispatch.py:306-314`). It does not distinguish queue empty, profile
   deferral, circuit deferral, retry scheduling, or limit reached, nor report remaining work.

4. **[OPEN, implementation/operations] launchd reload has no tunnel-readiness gate.**
   `install_launchd.sh:44-78` bootstraps agents in order but does not wait for Postgres to accept
   traffic before loading the watcher. The June recovery log records both a missing watcher
   and a connection-refused startup race. KeepAlive eventually recovered the race, but
   `run_remote_crawl.sh check` validates configuration rather than live runtime dependencies.

5. **[OPEN, reasoning/data contract] Failure classes remain conflated.** Infrastructure
   failure, profile/Cloudflare pause, shared site toast, transient pagination failure,
   `keyword_no_results`, `no_eligible_rows`, a normal zero-result, and a bounded exit have
   different retry and stop implications. Today they collapse into counts plus an untyped
   `last_error`, so operators must interpret prose/logs and can apply the wrong stop rule.

LOW

1. **[OPEN, process] Production completion evidence was not appended to the active Coding Log.**
   The log ended at the pre-production U3 boundary, while the stop and final truth lived only
   in `/tmp`. That fragmented the incident timeline and made the premature pause look like
   crawler behavior until the final artifact was examined.

2. **[OPEN, UX] Exact request progress and general recent-run activity coexist.** U2 correctly
   made the request card authoritative, but operators can still mentally combine it with
   unrelated recent activity unless labels clearly state the scopes.

### Intended-vs-actual drift matrix

| Intended contract | Actual drift that caused or obscured hiccups | Status |
|---|---|---|
| API owns product state; worker emits results (`PRD:443`) | Host-local profile/circuit/runtime state can halt dispatch but is absent from API state | Open |
| Scheduler owns retry/backoff/DLQ (`PRD:467-471`) | Semantic worker failure was formerly reduced to process success | Fixed U1 |
| One recrawl action has truthful progress | Latest-ten inference mixed unrelated attempts/runs | Fixed U2 |
| Active run means live work | Old state labels gated admission forever; current backend/frontend freshness sources differ | Partially fixed |
| A claimed job has one active owner | 60-second stale reclaim has no worker heartbeat | Open |
| Recovery stops protect shared dependencies | Undefined "semantic-failure burst" stopped heterogeneous retryable jobs while all shared health gates were green | Open |
| Isolated crawler worker is operationally distinct (`PRD:455-461`) | Temporary Mac+SSH-tunnel topology has no product-visible agent health or readiness handshake | Open |

### Recommended tactical roadmap

1. **P0 — Replace the fuzzy recovery stop rule with a typed decision table.**
   Hard-stop only on shared dependency failures (circuit open, profile operator action, tunnel
   or watcher unhealthy), manifest/count invariant violation, or an explicitly defined
   same-class threshold. Let job-local retryable anomalies use their existing three attempts.
   Done when the captured two-failure sequence continues automatically to terminal while a
   simulated shared circuit/profile failure stops before the next claim.

2. **P0 — Expose exact request blockers and per-job outcomes.**
   Add per-keyword state, attempt count, next retry time, normalized failure code, latest run
   ID, and blocked reason to the request-status contract/UI. Done when an operator can
   distinguish queued, retry-backoff, profile-paused, circuit-open, worker-offline, and
   terminal failure without querying Postgres or local files.

3. **P0 — Add a Mac crawler-agent heartbeat.**
   Persist agent ID/version, last poll, watcher PID/start time, tunnel probe, profile state,
   circuit open-until, active job/run, and last error through a tenant-safe API/reporting seam.
   Done when an accepted request with no progress displays a single current blocker within two
   polling intervals and alerts when heartbeat age exceeds a bounded threshold.

4. **P1 — Make queue ownership renewable.**
   Add owner/lease token plus heartbeat while the worker subprocess is alive; reclaim only an
   expired token, and reject completion from a superseded owner. Done with a test where a crawl
   exceeds 60 seconds, a second dispatcher polls, and exactly one worker/result exists.

5. **P1 — Centralize run freshness classification in the backend.**
   Compute `last_activity_at` from live progress/start/create and return authoritative
   `is_stale`; have admission and UI use that result/configured threshold. Add an explicit
   reconciliation command for historical orphaned rows. Done when a >3h run with fresh
   heartbeat remains active everywhere and an abandoned run is stale everywhere.

6. **P1 — Make bounded command exit self-explanatory and gate startup readiness.**
   On `crawl N`, print claimed/succeeded/retrying/failed/deferred/remaining and an explicit exit
   reason (`limit_reached`, `queue_empty`, `profile_paused`, `circuit_open`). Probe the tunnel
   before watcher bootstrap/one-shot work. Done with operations tests for unavailable-then-ready
   tunnel and for all bounded exit reasons.

7. **P1 — Preserve incident evidence durably.**
   Append production execution/stop/resume/final outcomes and artifact hashes to the Coding Log
   or an incident record, not only `/tmp`. Done when the timeline can be reconstructed from
   tracked metadata without relying on a live workstation temp directory.

### Recommended strategic architecture

Replace the Mac worker's direct production-DB claim over an SSH tunnel with an authenticated,
outbound crawler-agent protocol:

1. add heartbeat/status reporting while retaining the current DB claimant;
2. add API lease/renew/complete endpoints with typed outcomes and idempotent run correlation;
3. canary one tenant/profile through the API path while dual-reporting status;
4. disable direct DB claiming after parity and failure-injection tests;
5. retain the current guarded runner only as a rollback path, then remove the tunnel dependency.

This keeps the necessary real-Mac Chrome runtime but makes queue ownership, health, stop reasons,
and semantic outcomes part of one control plane. The tradeoff is more authenticated-agent and
lease code, but it removes the largest class of "accepted but apparently nothing happened"
incidents and makes fail-closed behavior visible instead of mysterious.

### Formal disposition

- The recent U1/U2/U3 implementation repaired the two most damaging silent-data issues:
  semantic failure acceptance and non-authoritative batch identity.
- The 2026-07-23 production recovery itself completed correctly after resume:
  `7 succeeded + 1 zero_result + 2 failed = 10`, no pending/processing jobs, no failed latest
  run marked dispatched, profile active, circuit closed, watcher and tunnel running.
- The next highest-value work is not another crawler parsing fix. It is to formalize recovery
  stop semantics and surface agent/dependency health in the request status path.
