# Coding Log: crawler-runtime-reliability

Started: 2026-07-23 19:06:18 +0700

## Source request and scope

Implement every priority from
`/Users/subhajlimanond/.codex/attachments/8e4f9794-9de6-4b82-b9d7-444fdf6e7d71/pasted-text-1.txt`
through tests, QCHECK, formal `g-check`, standard GitHub PR creation, authorized admin merge to
`origin/main`, and exact local-main landing:

1. define typed recovery stop rules;
2. expose crawler/profile/circuit/watcher/tunnel blockers to API/UI;
3. add renewable discovery-job leases;
4. centralize crawl-run freshness; and
5. make bounded crawl completion and launchd/tunnel startup diagnostic.

The preceding system review is in
`coding-logs/2026-07-22-13-39-00 Coding Log (crawl-result-retry-and-recrawl-batches).md`
under `Review (2026-07-23 18:04:01 +0700) - system`.

## Exploration evidence

- Base: exact `origin/main` `6882850cb79930beb7ca14c5c8500a54e0605134`.
- Worktree: `/Users/subhajlimanond/dev/egp-review-crawler-hiccups`.
- Branch: `feature/crawler-runtime-reliability`.
- The primary checkout's unrelated untracked `docs/TOR KEYWORDS.md` remains untouched.
- Auggie semantic retrieval was attempted with one detailed cross-layer query and returned HTTP
  `402`. Planning therefore used bounded direct inspection plus exact-identifier searches.
- Governing files read: root `AGENTS.md`, root `CLAUDE.md`, `apps/api/AGENTS.md`,
  `apps/worker/AGENTS.md`, `apps/web/AGENTS.md`, `packages/AGENTS.md`,
  `packages/db/AGENTS.md`, `packages/shared-types/AGENTS.md`, and
  `docs/MIGRATION_POLICY.md`.
- Principal implementation paths inspected:
  - `packages/db/src/egp_db/repositories/{run_repo,discovery_job_repo,recrawl_request_repo}.py`
  - `apps/api/src/egp_api/services/{discovery_dispatch,discovery_worker_dispatcher,rules_service,run_service}.py`
  - `apps/api/src/egp_api/executors/discovery_dispatch.py`
  - `apps/api/src/egp_api/routes/{rules,runs,project_ingest}.py`
  - `apps/api/src/egp_api/bootstrap/{repositories,services,middleware}.py`
  - `apps/worker/src/egp_worker/{main,browser_discovery,workflows/discover}.py`
  - `packages/crawler-core/src/egp_crawler_core/rate_limiter.py`
  - `packages/shared-types/src/egp_shared_types/enums.py`
  - `apps/web/src/lib/{api,hooks,run-progress}.ts`
  - `apps/web/src/app/(app)/projects/page.tsx`
  - `scripts/{run_remote_crawl,install_launchd,remote_crawl_guard}.sh/.py`
  - migrations `029` and `030`, OpenAPI generation scripts, and the relevant Python,
    migration, unit, Playwright, concurrency, and operations tests.

## Current As-Is wiring

```text
Projects UI
  -> POST /v1/rules/recrawl
  -> recrawl_requests + discovery_jobs
  -> GET /v1/rules/recrawl/{request_id} every 5s
       currently: aggregate counts + failed keyword names only

Mac launchd watcher
  -> direct production Postgres through SSH tunnel
  -> pre-claim bool gate (circuit/profile lock/warm/pause reason is discarded)
  -> claim pending job by processing_started_at with fixed 60s stale window
  -> blocking worker subprocess may run up to 3h
  -> free-text failure, pending retry, dispatched, or failed

crawl_runs
  -> backend admission: started_at/created_at within 3h
  -> frontend activity: max(live_progress.updated_at, started_at, created_at) within 3h
```

No current route, table, or heartbeat reports Mac watcher/tunnel/profile/circuit state. The
runbook phrase `semantic-failure burst` is documentation-only and has no threshold, taxonomy,
window, or executable decision function.

---

## Plan Draft A - four independently landable reliability PRs

### 1. Overview

Land four narrow PRs in dependency order: authoritative run activity, renewable typed dispatch
leases, crawler runtime/recovery visibility, then operator diagnostics. Each PR starts from the
new exact `main`, uses its own migration prefix if needed, and is merged and post-merge verified
before the next branch begins.

### 2. Files to change

PR U1, authoritative run activity:

- `packages/db/src/migrations/031_crawl_run_last_activity.sql` - add/backfill indexed
  `crawl_runs.last_activity_at`.
- `packages/db/src/egp_db/repositories/run_repo.py` - write activity on create/start/progress/
  finish, count active runs from the canonical column, and expose the shared stale classifier.
- `apps/api/src/egp_api/routes/runs.py` - return `last_activity_at` and authoritative `is_stale`.
- `apps/web/src/lib/run-progress.ts` - consume server classification; remove the local three-hour
  policy.
- Generated OpenAPI files and run/admission/frontend/migration tests.

PR U2, renewable typed dispatch:

- `packages/db/src/migrations/032_discovery_job_leases.sql` - add `claim_token`,
  `lease_expires_at`, `lease_heartbeat_at`, and `last_error_code`.
- `packages/shared-types/src/egp_shared_types/enums.py` - add stable discovery failure and crawler
  blocker vocabularies.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py` - tokenized claims, renewals, and
  token-guarded completion.
- `apps/worker/src/egp_worker/workflows/discover.py` and `apps/worker/src/egp_worker/main.py` -
  persist and emit structured semantic failure codes.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` - validate structured worker
  results and return typed pre-dispatch blockers.
- `apps/api/src/egp_api/services/discovery_dispatch.py` - keep leases alive, reject stale-owner
  completion, and return a typed batch result.
- `packages/crawler-core/src/egp_crawler_core/rate_limiter.py` - expose a sanitized circuit
  snapshot including reset time.
- Config/env docs and dispatch/worker/concurrency/migration tests.

PR U3, runtime and recovery visibility:

- `packages/db/src/migrations/033_crawler_runtime_heartbeats.sql` - add global operational
  heartbeat state for the out-of-process Track C agent.
- New `packages/db/src/egp_db/repositories/crawler_runtime_repo.py` - sanitized upsert/freshest
  snapshot/offline derivation.
- New `apps/api/src/egp_api/routes/crawler_runtime.py` - internal worker-token heartbeat POST and
  operator-readable status GET.
- New `apps/api/src/egp_api/services/crawler_runtime_reporter.py` - fail-open HTTPS heartbeat
  reporter used by the Mac executor even when its DB tunnel fails.
- New `packages/crawler-core/src/egp_crawler_core/recovery_policy.py` - executable typed
  continue/stop/complete decision table.
- API bootstrap files - repository/service/route/runtime-mode wiring.
- `recrawl_request_repo.py`, `rules_service.py`, and `routes/rules.py` - per-keyword attempts,
  lease/retry/error/run details, current runtime blocker, correlation mismatch, and recovery
  decision.
- Web API/hooks/Projects page/generated contracts - display the exact blocker and stop polling on
  terminal or explicit hard stop.
- API/repository/reporter/policy/web/migration tests.

PR U4, operator diagnostics:

- `apps/api/src/egp_api/executors/discovery_dispatch.py` - stable one-shot summary with requested
  limit, dispositions, remaining work, blocker, and explicit exit reason.
- New `apps/api/src/egp_api/executors/discovery_doctor.py` - read-only sanitized DB/profile/
  circuit/heartbeat/queue diagnosis.
- `scripts/remote_crawl_guard.py` - bounded live database readiness probe.
- `scripts/run_remote_crawl.sh` - `doctor` and `wait-database` commands.
- `scripts/install_launchd.sh` - wait for the tunnel/database before watcher bootstrap.
- `docs/REMOTE_LOCAL_CRAWLER.md` - replace the fuzzy burst rule with the executable decision
  matrix and document output/doctor/recovery.
- Operations/executor/runbook tests.

### 3. Implementation steps

For every PR:

1. add/stub the named tests first;
2. run them and record the expected RED reason;
3. implement the smallest complete production wiring;
4. refactor only where necessary to keep focused functions;
5. run format/lint/typecheck/tests, wiring searches, and three consecutive relevant suites;
6. run skeptical QCHECK, stage the exact intended set, and run formal `g-check`;
7. fix/disposition every finding, commit, push, create PR, verify checks, admin merge, refresh
   local `main`, and post-merge test the exact merge commit.

Key functions/classes:

- U1 `touch_run_activity()`, `is_run_stale()`, and
  `SqlRunRepository.count_active_runs()` use one activity source.
- U2 `claim_pending_discovery_jobs()` creates a claim token and expiry;
  `renew_discovery_job_lease()` is tenant/job/token scoped;
  `record_discovery_job_attempt()` rejects stale owners; `DiscoveryJobLeaseKeeper` renews during
  blocking worker execution; `DiscoveryDispatchBatchResult` records dispositions and blocker.
- U3 `SqlCrawlerRuntimeRepository.record_heartbeat()` and `get_freshest_status()` own durable
  runtime truth; `CrawlerRuntimeReporter` posts independently of the DB tunnel;
  `evaluate_recovery_decision()` stops only for typed shared-dependency/invariant failures.
- U4 `probe_database_until_ready()` is bounded and credential-safe;
  `build_discovery_doctor_snapshot()` is read-only; installer ordering is tunnel -> readiness ->
  watcher.

### 4. Test coverage

U1:

- `test_live_progress_heartbeat_keeps_old_run_active` - recent activity preserves admission.
- `test_abandoned_run_activity_expires_everywhere` - stale activity releases admission.
- `test_run_api_returns_authoritative_freshness` - API exposes server classification.
- `run-progress.test.ts` server-state cases - frontend no longer recomputes freshness.
- `test_crawl_run_activity_migration_backfills_existing_rows` - safe additive upgrade.

U2:

- `test_renewed_lease_cannot_be_reclaimed` - live ownership survives 60 seconds.
- `test_expired_lease_can_be_reclaimed` - abandoned ownership recovers safely.
- `test_stale_claim_token_cannot_finish_job` - old owner cannot overwrite result.
- `test_dispatch_renews_lease_during_blocking_worker` - subprocess keeps ownership alive.
- `test_worker_result_carries_failure_code` - semantic code survives stdout boundary.
- `test_pre_dispatch_returns_exact_blocker` - circuit/profile reasons remain typed.
- Existing fair-claim/retry tests - tenant fairness and three attempts remain.

U3:

- `test_internal_heartbeat_requires_worker_token` - endpoint rejects unauthenticated agents.
- `test_heartbeat_status_becomes_offline_when_stale` - absent agent is explicit.
- `test_reporter_posts_database_unreachable_without_tunnel` - HTTPS health survives DB failure.
- `test_two_heterogeneous_keyword_failures_continue` - no false global stop.
- `test_circuit_or_profile_pause_stops_before_next_claim` - shared failures hard-stop.
- `test_recrawl_status_returns_per_job_diagnostics` - attempts/retry/error/run are exact.
- `test_correlation_mismatch_returns_typed_stop` - deleted/missing jobs cannot poll forever.
- Projects UI tests - Thai blocked/retrying/error copy and finite polling.

U4:

- `test_once_summary_distinguishes_limit_queue_and_blocker` - bounded exits are explicit.
- `test_database_probe_waits_then_succeeds` - startup handles tunnel delay.
- `test_database_probe_times_out_actionably` - install fails closed when unavailable.
- `test_install_orders_tunnel_readiness_before_watcher` - launchd race is prevented.
- `test_doctor_reports_profile_circuit_queue_and_heartbeat` - read-only diagnosis is complete.

### 5. Decision completeness

- Goal: make every crawl stop or delay attributable, ownership-safe, and visible.
- Non-goals: no legacy crawler fallback, no direct production mutation in implementation PRs, no
  new browser automation algorithm, no Graphite/stacked PRs, and no removal of existing audit
  rows.
- Success criteria:
  - backend and frontend agree on active/stale runs;
  - a renewed live claim cannot be reclaimed and an expired claim can;
  - stale owners cannot write terminal state;
  - worker semantic codes reach per-job status;
  - Track C heartbeat/profile/circuit/tunnel-equivalent health is visible to operators;
  - two unrelated retryable semantic failures do not globally stop recovery;
  - hard shared blockers produce a typed stop;
  - `crawl N` explains exactly why it exited and how much work remains;
  - launchd never intentionally starts the watcher before bounded DB readiness.
- Public interfaces:
  - migrations `031`, `032`, `033`;
  - `RunResponse.last_activity_at` and `RunResponse.is_stale`;
  - structured fields on exact recrawl status, including `jobs`, `runtime`, and
    `recovery_decision`;
  - `POST /internal/worker/crawler-runtime/heartbeat`;
  - `GET /v1/rules/crawler-runtime`;
  - envs `EGP_DISCOVERY_LEASE_SECONDS`, `EGP_DISCOVERY_LEASE_HEARTBEAT_SECONDS`,
    `EGP_CRAWLER_AGENT_ID`, `EGP_CRAWLER_HEARTBEAT_INTERVAL_SECONDS`, and
    `EGP_CRAWLER_HEARTBEAT_STALE_AFTER_SECONDS`;
  - `run_remote_crawl.sh doctor|wait-database` and stable one-shot summary output.
- Failure behavior:
  - observability reporting is fail-open for crawling but recorded/logged;
  - lease acquisition/completion is fail-closed on token mismatch;
  - stale heartbeat in external mode is a typed hard stop; embedded mode reports embedded-ready;
  - one warm failure defers/continues, operator-required profile pause hard-stops;
  - per-keyword retryable anomalies never global-stop; retry exhaustion is terminal for that job;
  - manifest/correlation mismatch hard-stops and finite-polling UI explains it.
- Rollout/backout:
  - apply additive migration before each matching code deploy;
  - deploy API before restarting the Mac reporter for U3;
  - old nullable rows remain readable during rollout;
  - backout code may leave additive columns/table and audit heartbeats in place;
  - U4 installer fails before watcher bootstrap if readiness does not arrive.
- Monitoring:
  - watch heartbeat age, blocker code, lease renew failures, stale-token write rejects, queue due
    counts, retry exhaustion, and activity-age classification.
- Acceptance:
  - relevant suites pass three consecutive times;
  - full Python, ruff, compileall, web unit/e2e/typecheck/lint/build, OpenAPI drift, migration
    fresh/upgrade, credential scan, and wiring checks pass as applicable;
  - exact merged `origin/main` SHA equals local `main` after every PR.

### 6. Dependencies

- Existing internal worker token and API base URL already present in Track C env.
- PostgreSQL/Supabase remains source of truth.
- Real Mac Chrome/profile is not needed for deterministic unit/integration gates.
- Production deployment/runtime activation is not implied by merging; implementation will
  document deploy order but will not mutate production without separate authorization.

### 7. Validation

Use targeted RED/GREEN commands recorded per PR, then:

```bash
./.venv/bin/python -m ruff check apps packages scripts tests
./.venv/bin/python -m compileall apps packages scripts
./.venv/bin/python -m pytest tests/phase1 tests/phase2 tests/concurrency tests/operations -q
(cd apps/web && npm run check:api-types && npm run test:unit && npm run typecheck && npm run lint && npm run build)
```

Playwright is required where Projects-page behavior changes. Migration tests use the repository's
temporary PostgreSQL harness when binaries are available.

### 8. Wiring verification

| Component | Entry point | Registration | Schema/table |
|---|---|---|---|
| Canonical activity | run create/start/progress/finish and admission | `run_repo.py` callers + runs route | `crawl_runs.last_activity_at` |
| Tokenized lease | dispatcher claim/process/complete | standalone and embedded processor factories | `discovery_jobs.claim_token/lease_*` |
| Typed worker failure | discover workflow result | worker stdout -> subprocess dispatcher -> queue attempt | `discovery_jobs.last_error_code` |
| Runtime heartbeat POST | Mac executor heartbeat loop | API middleware/router + repository bundle | `crawler_runtime_heartbeats` |
| Runtime/recovery status | exact request polling | RulesService and `/v1/rules` route | heartbeat + jobs + runs |
| Projects diagnostics | React Query exact request hook | Projects page | generated API contract |
| DB readiness | launchd install and manual runner | `install_launchd.sh` / `run_remote_crawl.sh` | read-only `SELECT 1` |
| Doctor | `run_remote_crawl.sh doctor` | packaged executor module | read-only runtime tables/files |

### 9. Cross-language schema verification

- Python uses exact tables `crawl_runs`, `discovery_jobs`, `recrawl_requests`, and the new
  `crawler_runtime_heartbeats`.
- TypeScript receives API field names only from regenerated OpenAPI types; it does not issue SQL.
- Before each migration, exact searches must confirm all SQLAlchemy columns, SQL migrations,
  Pydantic contracts, generated types, and frontend consumers use the same names.

### 10. Decision-complete checklist

- [x] No open implementation decisions.
- [x] Every public route/schema/env/CLI change is named.
- [x] Every behavior has a defect-sensitive test.
- [x] Validation commands and three-run reliability gates are specified.
- [x] Every component has a production entry point and registration location.
- [x] Migration order, rollout, backout, and fail-open/fail-closed behavior are specified.

---

## Plan Draft B - two broad vertical PRs

### 1. Overview

Combine all database state changes into one control-plane PR, then land one operator-runtime PR.
This minimizes migrations and exposes the whole feature sooner, at the cost of a much larger
review and rollback surface.

### 2. Files to change

- PR B1: one migration containing run activity, job leases/failure code, and runtime heartbeat;
  all repositories, worker/dispatcher, API routes/services/bootstrap, OpenAPI, frontend, and
  tests.
- PR B2: reporter loop, CLI summary/doctor, guard readiness, launchd ordering, runbook, and
  operations tests.

### 3. Implementation steps

Follow the same RED -> implementation -> GREEN -> three-run gates -> QCHECK -> g-check -> merge
sequence, but implement B1 in vertical slices behind one staged migration: activity, lease,
runtime heartbeat, recovery policy, then frontend.

### 4. Test coverage

Use every test named in Draft A. Additionally run the full cross-layer matrix after each slice
because all changes share one branch and migration.

### 5. Decision completeness

- Goal/non-goals and public interfaces are identical to Draft A.
- Success is all-or-nothing for B1: no partial landing of activity, ownership, or status.
- Failure modes retain the same fail-closed lease and hard-stop rules.
- Rollout applies one larger migration before the B1 API/worker deploy.
- Backout leaves all additive columns/table in place.

### 6. Dependencies

Same as Draft A, but B1 requires all Python/web/generated-contract changes to be deployable at
once.

### 7. Validation

Same full commands as Draft A, with all relevant suites run three times before B1 review.

### 8. Wiring verification

| Component | Entry point | Registration | Schema/table |
|---|---|---|---|
| Activity + lease + runtime state | API/worker/dispatcher | one repository/service/bootstrap change set | one combined migration |
| Recovery UI | exact request hook | Rules route/OpenAPI/Projects page | combined state |
| Operator runtime | Mac runner/install | shell + executor modules | read-only combined state |

### 9. Cross-language schema verification

Generate OpenAPI after all B1 Python contracts settle and require the single schema/type drift
gate to cover every new field.

### 10. Decision-complete checklist

- [x] No open decisions.
- [x] Same interfaces/tests/failure behavior as Draft A.
- [x] Wiring is vertical, but review size is materially larger.
- [x] Rollout/backout is specified.

---

## Comparative analysis

Draft A isolates four production invariants, gives every migration and behavior a focused RED,
and makes rollback/incident attribution straightforward. Its cost is four PR/check/merge cycles.

Draft B reduces lifecycle overhead and migration count, but a defect in lease ownership, runtime
status, or frontend polling can delay all other fixes. Its combined diff is harder to review
skeptically and makes post-merge failure attribution less precise.

Both obey tenant isolation, API-owned product state, strict TDD, generated-contract discipline,
and standard non-Graphite GitHub flow. Draft A is safer for this operationally sensitive system.
Draft B contributes one useful idea: define the shared enums/status envelope before individual
layers so vocabulary cannot drift.

---

## Unified Execution Plan

### 1. Overview

Use Draft A's four sequential PR boundaries and Draft B's shared-vocabulary-first discipline.
Land U1 through U4 one at a time, refreshing exact `main` after each merge. This is the selected
implementation plan.

### 2. Files to change

- U1: migration `031`, run repository/routes, frontend run-progress, generated contracts, run/
  admission/migration/web tests.
- U2: migration `032`, shared enums, job repository, worker workflow/result, dispatcher,
  rate-limiter snapshot, config/env, dispatch/worker/concurrency/migration tests.
- U3: migration `033`, runtime repository/route/reporter/policy, bootstrap/rules status,
  frontend/generated contracts, API/policy/reporter/UI/migration tests.
- U4: executor summary/doctor, remote guard/runner/launchd installer, runbook, operations tests.

### 3. Implementation steps

1. U1 RED/GREEN: prove a run older than three hours with fresh progress is active in both
   admission and UI; add/backfill/update canonical activity; expose server classification;
   remove frontend timing policy.
2. U1 gates/QCHECK/g-check/PR/admin merge/local-main verification.
3. U2 RED/GREEN: prove a live long-running claim is currently reclaimable; add tokens/expiry/
   renewal/stale-owner rejection; propagate structured failure/blocker codes and batch result.
4. U2 gates/QCHECK/g-check/PR/admin merge/local-main verification.
5. U3 RED/GREEN: prove external queued work has no visible blocker and two heterogeneous
   failures have no executable policy; add heartbeat, exact job diagnostics, finite polling, and
   typed recovery decision.
6. U3 gates/QCHECK/g-check/PR/admin merge/local-main verification.
7. U4 RED/GREEN: prove one-shot/launchd startup ambiguity; add stable summary, doctor, bounded DB
   readiness, and readiness-before-watcher ordering; replace fuzzy runbook text.
8. U4 gates/QCHECK/g-check/PR/admin merge/local-main verification.
9. Final audit every source requirement against exact current `origin/main` and local `main`.

### 4. Test coverage

All Draft A tests are mandatory. Each PR's focused suite runs three times; the final merged U4
commit runs the union of affected suites plus repository-wide quality gates.

### 5. Decision completeness

- Goal/non-goals, interfaces, failure decisions, rollout, monitoring, and acceptance are exactly
  those locked in Draft A.
- Migration names are locked to `031`, `032`, and `033` because current maximum is `030` and PRs
  land sequentially. Recheck immediately before each branch; any unexpected upstream migration
  is a real collision to resolve, not a reason to reuse a prefix.
- Runtime heartbeat is global operational state, not tenant data. Public reads still require a
  run-operator role; heartbeat writes require the existing internal worker token; per-request
  job/run data remains tenant-scoped.
- Observability failures never stop crawling. Ownership and invariant failures fail closed.
- No production deploy/migration/recovery execution is included; merge and source landing only.

### 6. Dependencies

Exact merged predecessor `main`, local Python/web dependencies, temporary PostgreSQL binaries
when available, internal worker token/API URL already used by Track C, and GitHub admin merge
authorization supplied in the objective.

### 7. Validation

Record exact RED and GREEN commands in each implementation update. Before each merge require:

1. targeted tests three consecutive times;
2. relevant full Python/web/operations/concurrency suites;
3. ruff, compileall, typecheck, lint, build, OpenAPI drift, migration fresh/upgrade;
4. exact wiring/schema/env searches;
5. QCHECK and formal staged working-tree `g-check`;
6. GitHub checks/review state or exact documented infrastructure blocker;
7. post-merge tests on local `main` at the same SHA as `origin/main`.

### 8. Wiring verification

Use Draft A's table as the authoritative checklist and append exact file:line evidence after each
PR implementation. No row may remain `NOT FOUND`.

### 9. Cross-language schema verification

Before migrations and generated types, run exact searches across SQL, SQLAlchemy, Pydantic,
OpenAPI JSON/TypeScript, and frontend consumers. Confirm `tenant_id` on every tenant-scoped
query and confirm the global heartbeat table contains no tenant/customer payload or secrets.

### 10. Decision-complete checklist

- [x] Full source scope preserved across four PRs.
- [x] Every named priority maps to an implementation unit and acceptance proof.
- [x] No legacy fallback or unrelated production action.
- [x] Tests-first order, public contracts, wiring, migration, rollout, and backout are locked.
- [x] Final success requires all four PRs merged and exact local-main landing, not planning alone.

---

## Implementation Update - U1 authoritative run activity

### Scope implemented

- Added additive migration `031_crawl_run_last_activity.sql`.
  - Existing rows backfill from `finished_at`, then `started_at`, then `created_at`.
  - The default is installed only after the backfill so migration time cannot overwrite historical
    activity.
  - The final column is non-null and indexed with tenant/status for admission queries.
- Added `CrawlRunRecord.last_activity_at` and writes on run create, start, summary/progress,
  finish, and all repository-owned failure transitions.
- Changed active-run admission from `started_at`/`created_at` inference to the canonical activity
  column.
- Added the shared server-side stale classifier and exposed `last_activity_at` plus `is_stale` in
  `RunResponse`.
- Regenerated OpenAPI JSON and TypeScript contracts.
- Removed the frontend three-hour clock policy. The UI consumes `run.is_stale` and uses
  `last_activity_at` only for ordering stale entries.

### RED evidence

Backend/API/admission/migration RED:

```text
PYTHONPATH=<worktree API and DB sources> python -m pytest \
  tests/phase1/test_project_and_run_persistence.py::test_run_repository_tracks_canonical_activity_across_lifecycle \
  tests/phase1/test_projects_and_runs_api.py::test_runs_endpoints_create_list_and_return_tasks \
  tests/phase2/test_rules_api.py::test_manual_recrawl_counts_old_run_with_fresh_progress_as_active \
  tests/phase1/test_migration_runner.py::test_crawl_run_activity_migration_uses_next_unique_prefix -q
```

Expected result before implementation: four failures because the record/API fields and migration
did not exist and admission returned `202` instead of `429`.

Frontend RED:

```text
npm run test:unit -- tests/unit/run-progress.test.ts
```

Expected result before implementation: two failures because the client still recomputed
freshness from its own clock and `live_progress` timestamps.

The first attempted GREEN invocation accidentally loaded the primary checkout's editable Python
packages. Its repeated RED was discarded as implementation evidence. All recorded GREEN commands
explicitly put the isolated worktree API and DB sources first on `PYTHONPATH`.

### GREEN and regression evidence

- Focused RED set: `4 passed`.
- Authoritative stale API plus stale/fresh admission cases: `3 passed`.
- Real temporary-PostgreSQL migration upgrade/backfill test: `1 passed`.
- Relevant Python suite before QCHECK, three consecutive executions:
  `74 passed, 6 SQLite adapter deprecation warnings` each time.
- Web focused unit test: `2 passed`.
- Web full unit suite, three consecutive executions: `50 passed` each time.
- OpenAPI drift: current.
- Web typecheck: passed.
- Web lint: passed with only Next.js's existing `next lint` deprecation notice.
- Production web build: passed, 22 pages generated.
- Ruff on all changed Python files: passed.
- Python compileall for changed API/DB packages: passed.
- `git diff --check`: passed.
- Repo-wide Python collection: `1316 passed`, with one worktree-environment failure because the
  backup CLI expects `<repo>/.venv/bin/python`. After adding an ignored `.venv` link to the
  primary checkout's existing environment, the exact failed backup test passed (`1 passed`).
  No product file changed for that environment correction.

### Wiring verification

| Contract | Definition/write | Runtime read/consumer | Verification |
|---|---|---|---|
| `crawl_runs.last_activity_at` | migration `031`; SQLAlchemy table at `run_repo.py:151-156`; run transitions at `run_repo.py:430-554`, failure transitions below, and task touches at `run_repo.py:762-849` | admission at `run_repo.py:897-925` | migration upgrade plus stale/fresh admission tests |
| `is_run_stale()` | `run_repo.py:216-239` | API serializer at `runs.py:89-103` | stale API response test |
| `RunResponse.last_activity_at/is_stale` | Pydantic fields at `runs.py:43-55` | generated OpenAPI/TypeScript and `run-progress.ts:50-57` | schema drift, typecheck, web unit tests |
| frontend stale ordering | `run-progress.ts:145-153` | runs page helpers | full web unit suite and production build |

No wiring row is `NOT FOUND`. Tenant scoping remains in the admission predicate alongside the new
activity predicate. Migration `031` is additive; rollback is application rollback without
dropping the new column.

### U1 review state

The independent QCHECK reported one HIGH finding: task-only workflows updated `crawl_tasks` but
did not refresh their parent run, so a long close-check task could be live while admission and the
API classified its run as stale. The finding was accepted.

Fix RED:

```text
pytest tests/phase1/test_project_and_run_persistence.py::test_task_lifecycle_refreshes_parent_run_activity -q
```

The test failed because task creation left the parent at its old activity timestamp. The fix added
`touch_run_activity()` and invoked it inside the same transaction as task create/start/finish.
The focused test passed, Ruff passed, and the relevant Python suite then passed three consecutive
times at `75 passed, 6 SQLite adapter deprecation warnings` per execution. QCHECK re-reviewed the
fix and confirmed the HIGH finding resolved with no new findings.

Implementation, gates, and QCHECK are complete. Formal staged `g-check` remains before commit,
PR, admin merge, local-main refresh, and post-merge verification.

## Review (2026-07-23 19:31:01 +07) - staged working tree U1 authoritative activity

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-review-crawler-hiccups`
- Branch: `fix/crawl-run-activity`
- Scope: staged working tree against `6882850cb79930beb7ca14c5c8500a54e0605134`
- Commands Run: `git status --porcelain=v1`; staged/unstaged `git diff --name-only`,
  `--stat`, targeted staged diff inspection, and `git diff --cached --check`; exact-string
  wiring searches; focused pytest RED/GREEN; relevant pytest suite three times; repo-wide
  pytest; Ruff; compileall; OpenAPI drift; Vitest three times; TypeScript typecheck; Next lint;
  Next production build

### Findings
CRITICAL
- No findings.

HIGH
- No findings. The independent QCHECK's task-only activity finding was remediated before this
  formal review and its regression test is staged.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Assumption: deployment applies migration `031` before starting application code that selects
  `last_activity_at`; this is the repository's existing migration-first deployment contract.
- Assumption: run-summary and task lifecycle events are the authoritative liveness signals.
  Renewable ownership for blocking discovery jobs remains deliberately assigned to U2.

### Recommended Tests / Validation
- Required validation is complete: temporary-PostgreSQL upgrade/backfill, active/stale admission,
  authoritative API and frontend classification, task lifecycle activity, generated-contract
  drift, full relevant Python/web suites, and production web build.
- Post-merge, rerun the focused U1 Python set, web freshness unit test, and migration-prefix
  check on exact local `main`.

### Rollout Notes
- Apply migration `031` before the application rollout. Older application code safely ignores the
  additive column, allowing migration-first deployment and application rollback.
- Backfill deliberately precedes the default so existing rows retain historical activity rather
  than migration time.
- Creating the new index can briefly contend with writes on a large `crawl_runs` table; schedule
  the normal migration window and observe migration duration. No feature flag or environment
  variable is required.

### U1 landing

- PR: `https://github.com/SubhajL/egp/pull/174`
- GitHub Actions and Claude jobs all stopped before execution because the GitHub account was
  locked for billing. Direct check annotations confirmed this was infrastructure, not a test
  failure.
- The user-authorized admin squash merge completed at
  `2511879981e824be774c8a0ab7f63c5137dac2df`.
- `origin/main` and the primary local `main` were verified at that exact SHA. The user-owned
  untracked `docs/TOR KEYWORDS.md` remained untouched.
- Post-merge verification: 75 relevant Python tests, Ruff, two focused web unit tests, and
  OpenAPI drift all passed on exact local `main`.

---

## Implementation Update - U2 renewable claims and typed failure state

### Scope implemented

- Added migration `032_discovery_job_leases.sql` with `claim_token`, `lease_expires_at`,
  `lease_heartbeat_at`, and `last_error_code`, plus a pending-lease index.
- Replaced permanent `processing_started_at` ownership with tokenized renewable leases:
  unclaimed or expired jobs are claimable; active leases are not; renewals require the current
  tenant/job/token and an unexpired lease; completion clears lease state.
- Added a fail-closed `DiscoveryJobLeaseKeeper` around the blocking worker subprocess. Transient
  renew errors retry within the last confirmed lease; a superseded/expired claim emits
  cancellation, kills the worker/Chrome process group, returns `lease_lost`, and cannot overwrite
  the newer owner.
- Added shared stable `DiscoveryFailureCode` and `CrawlerBlockerCode` vocabularies.
- Worker semantic anomalies now cross the stdout JSON boundary with a failure code. The dispatcher
  validates the result and distinguishes semantic failure, malformed/missing result, nonzero exit,
  timeout, termination, entitlement failure, generic dispatch failure, and lost ownership.
- Added typed `DiscoveryPreDispatchResult`, per-job disposition, and
  `DiscoveryDispatchBatchResult`. Pre-dispatch checks report exact circuit/profile blockers and
  leave jobs pending and unclaimed.
- Added an operator-safe rate-limiter circuit snapshot with reset timestamp/duration and aggregate
  counters only.
- Wired lease duration/heartbeat through embedded and standalone executors, both Compose files,
  all relevant environment templates, and deployment/remote-crawler runbooks.

### RED evidence

The focused tests were written before implementation:

```text
PYTHONPATH=<worktree API/worker/DB/shared/crawler sources> python -m pytest \
  tests/concurrency/test_fair_claim.py \
  tests/phase2/test_discovery_dispatch.py \
  tests/phase1/test_worker_entrypoint.py \
  tests/phase1/test_worker_live_discovery.py \
  tests/phase1/test_api_discovery_spawn.py \
  tests/phase2/test_persistent_browser_profile.py \
  tests/concurrency/test_rate_limiter.py \
  tests/phase1/test_migration_runner.py \
  tests/phase2/test_background_runtime_mode.py \
  tests/phase2/test_discovery_executor.py \
  apps/api/tests/test_dispatch_trigger_metadata.py -q
```

Expected collection failed with six import/config errors because
`DiscoveryDispatchBatchResult`, `DiscoveryFailureCode`, `CrawlerBlockerCode`, and the lease
configuration helpers did not exist.

The first GREEN attempt found SQLite's expected naive-datetime adapter behavior in the stale-token
comparison. Normalizing repository timestamps to UTC fixed the adapter-specific failure without
weakening the Postgres predicate. The focused lease/typed-result set then passed (`12 passed`).

### GREEN and regression evidence

- Broad compatibility split:
  - dispatch/repository/executor/API: `25 passed`;
  - worker/spawner/persistent profile after updating five intended summary contracts:
    `94 passed`;
  - migration/config/rate limiter: `25 passed`.
- Environment-template, remote-crawl asset, and migration tests: `34 passed`.
- Final affected suite, including full rules API and architecture checks, passed three consecutive
  times before QCHECK: `229 passed, 5 existing SQLite deprecation warnings` each run.
- Repository-wide Python suite: `1327 passed, 112 existing SQLite deprecation warnings`.
  The isolated worktree temporarily linked `.venv` to the primary checkout's existing environment
  because one backup CLI test deliberately invokes `<repo>/.venv/bin/python`; the link was removed
  immediately after the gate and never staged.
- Ruff across API, worker, packages, and affected tests: passed.
- Compileall across API, worker, and packages: passed.
- `git diff --check`: passed.

### Wiring verification

| Contract | Definition/write | Runtime read/consumer | Verification |
|---|---|---|---|
| discovery lease columns | migration `032`; SQLAlchemy discovery-job table and record | claim, renew, and finish predicates in `discovery_job_repo.py` | migration upgrade/preservation and repository concurrency tests |
| lease config | `get_discovery_lease_seconds()` and heartbeat validation | embedded bootstrap and standalone executor | config and runtime-mode tests; Compose/env drift tests |
| claim token ownership | UUID generated on atomic pending claim | lease keeper renewal and token-scoped completion | renewed/expired/stale-token/blocking-worker tests |
| `DiscoveryFailureCode` | shared `StrEnum` and worker summary writer | stdout validator, dispatch disposition, `last_error_code` persistence | worker-entrypoint, spawner, workflow, and retry/final-state tests |
| `CrawlerBlockerCode` | shared `StrEnum` | circuit/profile preflight and typed batch result | circuit/profile and no-claim tests |
| circuit snapshot | `RateLimiterCircuitSnapshot` | pre-dispatch circuit gate and safe operator logging | exact snapshot/reset-time test |

No wiring row is `NOT FOUND`. Tenant predicates remain explicit on renew, finish, get/list, and
all job mutation queries. Migration `032` is additive: unstarted pending jobs keep null lease
fields and remain claimable, while legacy in-flight jobs receive a sentinel lease through the
remainder of the old three-hour worker timeout.

### U2 review state

Independent QCHECK found:

1. HIGH: the embedded app adapter converted typed preparation back to `bool`, causing an
   `AttributeError` on a real pending job;
2. HIGH: one transient renew exception abandoned the lease without retrying or cancelling Chrome;
3. MEDIUM: migration could reclaim a legacy in-flight job immediately;
4. MEDIUM: the advertised stable failure-code vocabulary was unconstrained in DB/repository;
5. LOW: missing-worker reconciliation returned `int` but was annotated as a batch result.

All findings were accepted. Seven RED tests reproduced them. The fixes preserve the typed result
in embedded mode, retry transient renew failures until the confirmed deadline, propagate a
cancellation event into a polled subprocess `communicate`, kill the whole worker process group on
confirmed loss, protect legacy in-flight rows with a three-hour sentinel lease, constrain codes in
SQLAlchemy/Postgres and repository input, and correct the annotation.

The seven QCHECK regressions pass. The expanded affected suite passes three consecutive times at
`235 passed, 5 existing SQLite deprecation warnings` each run. Independent re-review also ran the
seven focused tests (`7 passed`) and reported no remaining findings. The final post-remediation
repository-wide suite passed with confirmed exit code: `1333 passed, 112 existing SQLite
deprecation warnings`.

Implementation, local gates, and QCHECK are complete. Formal staged `g-check`, commit, PR,
user-authorized admin merge, exact local-main landing, and post-merge verification remain.

## Review (2026-07-23 20:24:39 +07) - staged working tree U2 renewable claims

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-review-crawler-hiccups`
- Branch: `fix/discovery-job-leases`
- Scope: staged working tree against U1 merge
  `2511879981e824be774c8a0ab7f63c5137dac2df`
- Commands Run: staged/unstaged status, name and stat inspection, staged diff/check, production
  diff inspection, exact schema/config/worker/consumer wiring searches, migration upgrade,
  affected suite three times, repository-wide pytest, Ruff, compileall, environment-template
  drift, and independent QCHECK/re-review

### Findings

CRITICAL

- No findings.

HIGH

- No outstanding findings. Both QCHECK HIGH findings were reproduced, fixed, and independently
  re-reviewed before this formal review.

MEDIUM

- No outstanding findings. During formal staged inspection, a cancellation race remained: if
  `communicate()` returned during the 500 ms poll in which lease loss was signalled, the late
  worker result could be treated as success before the next event check. The regression was
  tightened to signal cancellation inside `communicate()` and failed as expected. The helper now
  rechecks cancellation after every successful `communicate()` return, kills/drains the process
  group, and reports `lease_lost`. The focused test passes, and the 235-test affected suite passed
  three more consecutive times after the fix.

LOW

- No findings.

### Open Questions / Assumptions

- Deployment must stop and drain old embedded/standalone discovery executors before migration
  `032`, then start only lease-aware code. The migration sentinel protects already in-flight old
  jobs but does not make deliberately mixed versions a supported steady state.
- Host and database clocks remain normally synchronized. The renewal loop additionally uses a
  monotonic local deadline after translating the DB lease timestamp.
- Semantic `partial` runs remain accepted dispatches by existing policy; zero-project semantic
  anomalies are `failed` and retry with their stable failure code.

### Recommended Tests / Validation

- Complete: seven QCHECK regressions; temporary-PostgreSQL upgrade, sentinel, and check-constraint
  proof; renewal/reclaim/stale-token/cancellation tests; embedded and standalone wiring; stdout
  semantic-failure validation; exact blocker/circuit snapshot tests; affected suite three times;
  post-remediation repository-wide suite (`1333 passed`); Ruff; compileall; diff check.
- Post-merge: rerun the seven regression tests, migration prefix/upgrade test, and the compact
  discovery dispatch/worker suite on exact local `main`.

### Rollout Notes

- Stop/drain all old discovery executors; apply migration `032`; deploy/start the new executor.
- Keep lease/heartbeat at `60/20` initially and worker count at `1`.
- Observe `lease_lost`, renewal errors, typed blocker counts, worker termination, and pending-job
  age before any concurrency increase.
- Application rollback is safe with additive columns, but do not restart old executors against
  newly queued work after migration without first stopping the new executor.

## U2 landed

- PR: `https://github.com/SubhajL/egp/pull/175`
- Admin squash merge: `54fc96c6cf96c24bacd3b23759a8ce6ff3232c49`
- GitHub checks could not start because the account was locked for billing; every check carried
  the same immediate GitHub annotation. Local gates and the staged formal review above were green.
- Primary local `main` was fast-forwarded to the exact merge SHA; user-owned untracked
  `docs/TOR KEYWORDS.md` remained untouched.
- Post-merge verification: the 235-test affected suite and Ruff passed on exact merged source.

## Implementation Update (2026-07-23): U3 runtime and recovery visibility

### Semantic exploration and fallback

The required Auggie retrieval requested the heartbeat table/repository, worker-token route,
bootstrap, exact recrawl aggregation, executor/reporting path, generated contracts, hooks, and
Projects UI. Auggie again returned HTTP 402. Direct bounded `rg`/`sed` inspection established:

- exact-request polling previously exposed counts and failed keyword names only;
- no API/database contract represented the external Mac watcher, database tunnel, browser
  profile, or circuit state;
- the standalone executor could fail before database runtime construction and therefore had no
  independent visibility channel;
- React Query polled every five seconds until terminal, with no typed hard-stop boundary.

### RED evidence

Backend RED:

```text
PYTHONPATH=<worktree sources> <primary .venv>/bin/python -m pytest \
  tests/phase2/test_crawler_runtime.py tests/phase1/test_migration_runner.py -q
```

Collection failed because `crawler_runtime_reporter`, `crawler_runtime_repo`, and
`recovery_policy` did not exist. Frontend RED ran the focused hooks unit test and failed because
`shouldPollRecrawlRequest` did not exist.

### Implementation

- Added migration `033` and `SqlCrawlerRuntimeRepository`. Heartbeats are global sanitized
  operational state: no tenant/customer identifier, credential, URL, path, or free-form runtime
  exception. Atomic Postgres/SQLite upsert prevents duplicate-agent races.
- Added internal worker-token `POST /internal/worker/crawler-runtime/heartbeat` and run-operator
  `GET /v1/rules/crawler-runtime`. External heartbeat age derives explicit `online`/`offline`;
  embedded mode synthesizes `embedded_ready`.
- Added a fail-open HTTPS `CrawlerRuntimeReporter`. The external executor constructs it before
  database runtime state, so a real SQLAlchemy `OperationalError` reports
  `database_unreachable` even when the SSH tunnel is down. Non-database exceptions are not
  mislabeled as tunnel failures.
- Added executable `evaluate_recovery_decision()`. Correlation mismatch, stale agent,
  unreachable database, open circuit, and operator-required profile state are typed hard stops.
  Busy/warm-retry and heterogeneous per-keyword failures continue/defer. Terminal request state
  completes independently of keyword outcome mix.
- Extended exact recrawl status with every correlated job's state, attempts, typed/latest error,
  retry timestamp, latest run id/status/timestamps, correlation invariant, runtime snapshot, and
  recovery decision. Per-request reads remain tenant-scoped.
- Generated OpenAPI/TypeScript contracts now include both runtime routes and structured status.
  Projects renders Thai hard-stop, retrying, and exact error diagnostics. Polling stops on either
  terminal completion or a typed hard stop instead of running forever.
- Added heartbeat interval/staleness configuration to templates/Compose and documented deploy
  ordering: apply migration/API before restarting the Mac reporter.

### Initial GREEN evidence

- Backend focused set: `22 passed`.
- Expanded affected Python run: `110 passed, 1 contract expectation failed`; the single failure
  was an older exact-dictionary assertion that correctly detected the additive structured status.
  The assertion was updated to verify the new fields explicitly.
- Web unit suite: `51 passed`.
- Projects Playwright suite: `8 passed`, including rendered Thai blocked/retrying/error states.
- Generated OpenAPI drift check and TypeScript typecheck: passed.
- Ruff across every touched Python file: passed.

Final affected-suite repetition, repository-wide gates, wiring table, independent QCHECK,
formal staged g-check, PR, merge, and exact local-main landing remain.

### U3 QCHECK findings and remediation

Independent read-only QCHECK passed 69 focused Python tests, six web unit tests, and web
typecheck, then found two HIGH and three MEDIUM gaps:

1. HIGH: heartbeats were emitted only after `process_pending()`, so a healthy three-hour worker
   would be declared offline after 90 seconds;
2. HIGH: both default Compose `discovery-executor` services omitted the internal API URL/token,
   so the reporter could never start;
3. MEDIUM: stopping React Query on a typed hard stop offered no in-page way to observe recovery;
4. MEDIUM: terminal requests were overridden by later stale/offline runtime state;
5. MEDIUM: circuit reset time was dropped between preflight and heartbeat, and transient
   profile busy/warm-retry blockers were not rendered.

All findings were accepted and reproduced with RED tests. Remediation:

- the long-running executor owns an independent periodic heartbeat task whose state is updated by
  batch results/errors; heartbeat HTTP runs off the event loop, unchanged failed deliveries are
  also rate-limited, and `--once` reports its final batch;
- both Compose executor services receive `http://api:8000`, the internal worker token, a distinct
  in-box agent id, and heartbeat cadence;
- terminal completion now wins after correlation validation and before runtime blockers;
- finite polling remains stopped on a hard stop, but Projects exposes
  `ตรวจสอบสถานะอีกครั้ง`; the browser test proves stop -> continue recovery without reload;
- `circuit_reset_at` now flows from the sanitized limiter snapshot through preflight, batch,
  reporter, table, API, and Thai UI; profile busy/warm-retry blockers render as amber defer states;
- exact-request correlation now also rejects request-tagged runs whose discovery job is null or
  belongs outside the request, not only job-count mismatch;
- stale age comparison uses sub-second truth while the displayed age remains an integer.

Post-remediation focused evidence:

- `146 passed, 5 existing SQLite deprecation warnings`;
- web unit `51 passed`;
- Projects Playwright `8 passed`;
- Ruff, compileall, TypeScript typecheck, and `git diff --check`: passed.

Independent re-review, restarted three-consecutive affected runs, final repository-wide gates,
wiring table, staged g-check, PR, merge, and exact local-main landing remain.

### U3 final QCHECK remediation

The first re-review found three remaining MEDIUM gaps and reproduced each one:

1. every blocked poll briefly cleared the last-known circuit/profile blocker, producing
   ready/open oscillation and bypassing failed-delivery throttling when the control plane was
   unavailable;
2. `--once` published a healthy heartbeat only after its batch completed, then exited while the
   fresh heartbeat continued to imply a live agent;
3. correlation validation queried runs only by `recrawl_request_id`, so a run linked through a
   request job but missing/wrong on the reverse request axis was invisible.

The processor now exposes a readiness observer that fires only after pre-dispatch has positively
confirmed readiness and before a job is claimed. Until then the heartbeat retains the last-known
blocker. Failed heartbeat delivery globally throttles all changing non-forced payloads for the
configured interval. One-shot execution owns an independent serialized heartbeat thread while
the blocking batch runs and force-publishes `stopping` + `agent_offline` at exit.

Exact-request status now queries runs linked through either correlation axis and requires every
visible run to agree on both `recrawl_request_id` and `discovery_job_id`; malformed inverse links
cannot silently disappear or contribute a latest run.

The next re-review found one HIGH shutdown ordering race and one MEDIUM terminal-label gap:

- a delayed periodic HTTP request could outlive the one-second join and arrive after the forced
  terminal heartbeat;
- a one-shot exit retained circuit/profile/database blocker codes rather than becoming
  `agent_offline`.

Heartbeat delivery and terminal publication now share a lock. Shutdown sets the stop event,
waits behind any in-flight periodic delivery, publishes the forced terminal state under the same
lock, then joins the now-drained thread. `mark_stopping()` always selects `agent_offline`, while
the separate database/profile/circuit diagnostic fields remain intact. The delayed-delivery
regression proves the last report cannot revert from stopping to running. Final independent
QCHECK reported no severity findings.

Pre-formal staged inspection then found the analogous ordering risk in continuous mode: its
periodic and post-batch async tasks could overlap and let an older delayed heartbeat arrive after
new blocker state. Both paths now share an `asyncio.Lock` and capture state only after acquiring
it. A delayed-first continuous-mode regression proves `circuit_open` remains the last report.
The final bounded independent re-review again reported no severity findings.

### U3 final verification

| Producer | Contract seam | Consumer | Proof |
| --- | --- | --- | --- |
| external executor | sanitized worker-token heartbeat | runtime repository/API | heartbeat auth, stale/offline, failure-throttle, delayed-order tests |
| pre-dispatch preparer | blocker/reset/readiness observer | periodic runtime state | persistent-blocker and confirmed-readiness tests |
| recrawl jobs + crawl runs | both correlation axes | exact-request status/recovery policy | forward/null/inverse mismatch tests |
| runtime + exact jobs | generated OpenAPI/types | Projects hook/UI | generated drift check, unit tests, 43 browser tests |
| environment templates | API URL/token/agent/cadence | both Compose executors | configuration/wiring assertions and bounded diff inspection |

Final gates after all remediation:

- affected Python suite: `102 passed` on each of three consecutive runs;
- repository-wide Python suite: `1356 passed, 112 existing SQLite deprecation warnings`;
- web unit: `51 passed`; Playwright: `43 passed`; production build: passed;
- generated OpenAPI/TypeScript drift check: passed using the isolated worktree source path;
- TypeScript typecheck and Next lint: passed;
- repository-wide Ruff and Python compileall: passed;
- final independent QCHECK: no severity findings.

The first repository-wide attempt had one environment-only failure because the isolated worktree
did not contain its own `.venv`, which `scripts/pg_backup.sh` resolves relative to the repo root.
An untracked worktree-local symlink to the primary environment allowed the exact backup test and
full suite to run; it was removed immediately afterward and is not part of the change.

## Review (2026-07-23 21:38:49 +0700) - U3 staged working tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-review-crawler-hiccups`
- Branch: `fix/crawler-runtime-status`
- Scope: staged working tree against
  `54fc96c6cf96c24bacd3b23759a8ce6ff3232c49`
- Commands Run: staged status/name/stat/check and targeted production diffs; exact
  route/auth/repository/recovery/executor/Compose/UI wiring inspection; independent QCHECK and
  bounded re-reviews; RED regressions; affected suite three times; repository-wide pytest;
  OpenAPI drift; TypeScript typecheck; unit/browser tests; build; lint; Ruff; compileall

### Findings

CRITICAL

- No findings.

HIGH

- No outstanding findings. QCHECK's long-batch heartbeat, missing Compose credentials, bounded
  shutdown ordering, and continuous-mode delivery ordering risks were reproduced and fixed.

MEDIUM

- No outstanding findings. QCHECK's recovery refresh, terminal precedence, circuit/profile
  diagnostics, blocker oscillation/throttling, one-shot liveness, and bidirectional correlation
  gaps were reproduced and fixed.

LOW

- No findings.

### Open Questions / Assumptions

- Migration `033` and the API route are deployed before any external executor begins heartbeat
  delivery.
- `EGP_INTERNAL_API_BASE_URL`, `EGP_INTERNAL_WORKER_TOKEN`, and the agent id are supplied outside
  git on the Mac; example values are placeholders only.
- The initial 30-second heartbeat and 90-second stale threshold remain the rollout defaults.
- Freshest-agent global state is intentional for the current single authoritative external
  crawler; multi-agent aggregation is outside this PR.
- A completed bounded `--once` process intentionally becomes `agent_offline`; the retained
  database/profile/circuit fields remain diagnostic context rather than the stop reason.

### Recommended Tests / Validation

- Complete: `102 passed` three consecutive times for the affected Python suite.
- Complete: repository-wide `1356 passed` with 112 existing SQLite deprecation warnings.
- Complete: web unit `51 passed`, Playwright `43 passed`, production build, TypeScript typecheck,
  Next lint, generated OpenAPI/type drift, Ruff, compileall, and staged diff check.
- Post-merge: rerun the runtime/executor/correlation regressions and Ruff on exact merged
  `main`.

### Rollout Notes

- Apply migration `033`, deploy the API/runtime status route, then restart the Mac executor.
- Keep the worker token secret and rotate it if heartbeat authentication fails unexpectedly.
- Observe heartbeat age, delivery warnings, `agent_offline`, `database_unreachable`,
  `circuit_open`, profile blockers, and correlation mismatch before changing cadence.
- Code rollback can leave the additive heartbeat table in place. Stop the new reporter before
  rolling the API back so it does not repeatedly hit a missing endpoint.

## U3 landed (2026-07-23)

- PR `#176` was admin squash-merged to `origin/main`.
- Exact merge commit: `57c9bb048ef3f3e34a99f96dc3e0181cca6d1843`.
- GitHub-hosted checks did not start because the account was locked for billing; all equivalent
  local gates listed above were green before merge.
- Primary local `main` was fast-forwarded to the exact merge commit.
- Post-merge verification: affected Python suite `102 passed`; Ruff passed.
- The user-owned untracked `docs/TOR KEYWORDS.md` remained untouched.

## Implementation update (2026-07-23) - U4 operator diagnostics

### Exploration and RED

- Inspected the remote crawl guard/runner/launchd assets, discovery dispatch executor and
  repository seams, persistent-profile lock/state helpers, shared circuit state, runtime
  heartbeat repository, and the operator runbook.
- Auggie could not be invoked with the skill-mandated two-second timeout, so exploration used
  bounded direct `rg`/source inspection as the documented fallback.
- Initial named regressions failed at collection because the doctor module, queue snapshot,
  database-readiness result, and read-only profile-lock probe did not yet exist.

### Implementation

- Added a stable terminal JSON contract for bounded crawling: requested limit, processed
  dispositions, aggregate remaining queue state, blocker/reset context, and an explicit exit
  reason. Typed blockers return status 3; completed/deferred summaries return 0.
- Added a read-only, sanitized `doctor` command covering database reachability, aggregate queue
  state, external-agent heartbeat, persistent-profile lock/warm state, and the shared circuit.
- Added non-mutating circuit and profile-lock inspection helpers so diagnosis does not create,
  refresh, or overwrite runtime state.
- Added a bounded `wait-database` guard command. Launchd installation now orders tunnel startup,
  database readiness, then watcher bootstrap and aborts before the watcher if readiness fails.
- Expanded the operator runbook with exact daily commands, summary-field semantics, typed
  decision responses, and explicit stop rules based on correlation and hard-stop blockers.

### Focused verification

- First focused implementation run: `111 passed, 1 failed`; the only failure was the still-missing
  runbook contract.
- After the runbook update: `112 passed`.
- After explicit blocked-crawl and sanitized-doctor CLI exit-code coverage: `114 passed`.
- Ruff over every changed Python file and `bash -n` over both changed shell scripts passed.

### Independent QCHECK and remediation

QCHECK reported three medium findings and no critical/high findings:

1. exceptional bounded runs returned before emitting the promised JSON contract;
2. a direct SQLite doctor target could create a local database artifact;
3. database readiness accepted non-finite waits and could start a retry at the deadline.

All three were reproduced with regressions and fixed:

- bounded runtime-build and dispatch exceptions now emit a sanitized `error` summary with unknown
  queue counts represented as `null`, then exit 1;
- doctor rejects non-PostgreSQL targets before engine construction, sanitizes initialization
  failures, and guarantees disposal of any constructed engine;
- database readiness requires positive finite timeout/poll values and checks the deadline before
  every probe.

The remediated affected suite passed `155 tests` on each of three consecutive runs. Focused Ruff
and `git diff --check` also passed.

The first re-review identified two remaining medium precision gaps: exceptional processing could
have completed partial work before raising, and a slow successful readiness call could return
after its deadline. Error summaries now use `null` for both processed count and dispositions
instead of asserting zero, with a partial-work regression. Database readiness now rechecks the
clock after a successful probe and rejects deadline overruns. The final affected suite passed
`156 tests` on each of three consecutive runs.

Final independent QCHECK reported no severity findings. Final repository-wide gates on the
remediated source:

- Python: `1380 passed`, with 112 existing SQLite deprecation warnings;
- affected Python: `156 passed` on each of three consecutive runs;
- web unit: `51 passed`; Playwright: `43 passed`;
- generated OpenAPI/TypeScript drift, TypeScript typecheck, Next lint, and production build:
  passed;
- repository-wide Ruff, Python compileall, shell syntax, and `git diff --check`: passed.

As in U3, an untracked worktree-local `.venv` symlink was used only for the repository backup
test and removed automatically after pytest.

## Review (2026-07-23 22:16:48 +0700) - U4 staged working tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-review-crawler-hiccups`
- Branch: `fix/crawler-operator-diagnostics`
- Scope: staged working tree against
  `57c9bb048ef3f3e34a99f96dc3e0181cca6d1843`
- Commands Run: staged status/name/stat/check; bounded production source, shell, runbook, and
  test inspection; independent QCHECK with two remediation rounds; affected suite three times;
  repository-wide pytest; OpenAPI drift; TypeScript typecheck; unit/browser tests; build; lint;
  Ruff; compileall; shell syntax

### Findings

CRITICAL

- No findings.

HIGH

- No findings.

MEDIUM

- No outstanding findings. QCHECK's exceptional-summary accuracy, non-PostgreSQL doctor
  side-effect, initialization sanitization/disposal, non-finite database wait, deadline retry,
  partial-progress reporting, and successful-probe overrun findings were reproduced and fixed.

LOW

- No findings.

### Open Questions / Assumptions

- Doctor intentionally reports global aggregate queue counts because the single external Mac
  executor owns the global discovery queue; it never returns tenant, keyword, URL, path, or raw
  exception data.
- Doctor is diagnostic only and returns nonzero for deferred as well as blocked state so operator
  automation does not mistake “not ready now” for safe dispatch.
- A bounded error summary uses `null` progress and remaining counts because work may have completed
  before an exception and the final queue query may itself be the failing operation.
- PostgreSQL driver connection timeout granularity may let a probe process return after its
  logical deadline; the command rejects that late success and never starts another probe after
  the deadline.

### Recommended Tests / Validation

- Complete: affected suite `156 passed` on each of three consecutive runs.
- Complete: repository-wide `1380 passed` with 112 existing SQLite deprecation warnings.
- Complete: web unit `51 passed`, Playwright `43 passed`, production build, TypeScript typecheck,
  Next lint, generated OpenAPI/type drift, Ruff, compileall, shell syntax, and staged diff check.
- Post-merge: rerun the focused doctor/executor/guard/asset suites and Ruff on exact merged `main`.

### Rollout Notes

- Deploy code and the existing migration/runtime route sequence from U3 before enabling the Mac
  watcher.
- `scripts/install_launchd.sh install` now starts the tunnel, waits for a bounded database-ready
  result, and only then bootstraps the watcher.
- Use `scripts/run_remote_crawl.sh doctor` before changing queue rows; use the bounded crawl JSON
  exit reason to distinguish queue drain, cap reached, deferred work, blocker, and execution
  error.
- Code rollback does not require a schema rollback for U4; stop the watcher first and leave queue
  rows intact.
