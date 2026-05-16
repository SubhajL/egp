# Coding Log: discovery-lease-worker-pool

## Planning Context

Auggie semantic search was attempted first and failed with HTTP 429. This plan is based on direct file inspection and exact-string searches across the runtime dispatch, executor, repository, compose, and existing tests.

Inspected files:
- `AGENTS.md`, `CLAUDE.md`, `apps/api/AGENTS.md`, `apps/worker/AGENTS.md`, `packages/AGENTS.md`
- `apps/api/src/egp_api/services/discovery_dispatch.py`
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
- `apps/api/src/egp_api/executors/discovery_dispatch.py`
- `apps/api/src/egp_api/bootstrap/background.py`
- `apps/api/src/egp_api/bootstrap/services.py`
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`
- `tests/phase2/test_discovery_dispatch.py`
- `tests/phase2/test_discovery_executor.py`
- `tests/phase2/test_background_runtime_mode.py`
- `docker-compose.yml`, `docker-compose-localdev.yml`

## Plan Draft A - Processor-Level Thread Pool

### Overview

Convert `DiscoveryDispatchProcessor.process_pending()` from serial dispatch to a lease-backed worker pool using the existing `discovery_jobs.processing_started_at` lease. Keep the public dispatcher abstraction unchanged and add bounded concurrency through a processor constructor setting plus executor CLI/env configuration.

### Files to Change

- `apps/api/src/egp_api/services/discovery_dispatch.py`: add `worker_count`, concurrent claimed-job processing, and input normalization.
- `apps/api/src/egp_api/executors/discovery_dispatch.py`: read worker count from CLI/env and pass it into the processor.
- `apps/api/src/egp_api/config.py`: add `get_discovery_worker_count()` helper.
- `apps/api/src/egp_api/bootstrap/services.py`: use worker count for embedded mode processor wiring.
- `apps/api/src/egp_api/bootstrap/background.py`: no behavioral change expected, but verify it calls the same processor path.
- `docker-compose.yml`, `docker-compose-localdev.yml`: remove unused Redis service/dependency and set worker count for the discovery executor.
- `AGENTS.md`, `CLAUDE.md`, possibly `packages/db/AGENTS.md`: update local setup commands so Redis is not described as required infrastructure.
- `tests/phase2/test_discovery_dispatch.py`: add worker-pool concurrency and retry tests.
- `tests/phase2/test_discovery_executor.py`: add CLI/env worker-count wiring tests.
- `tests/phase2/test_background_runtime_mode.py`: add/create-app wiring assertion for worker count.

### Implementation Steps

TDD sequence:
1. Add tests proving two claimed jobs can dispatch concurrently when worker_count=2.
2. Run the targeted tests and confirm the concurrency test fails because dispatch is serial.
3. Add worker-count config/CLI tests and confirm they fail for missing interfaces.
4. Implement processor-level bounded concurrency with `ThreadPoolExecutor` and existing DB leases.
5. Wire worker count through config, executor runtime factory, and embedded app service construction.
6. Remove Redis from compose/docs because the implementation is DB lease-backed, not Redis-backed.
7. Run focused tests, ruff, compileall, and flakiness repeats for touched tests.

Functions:
- `normalize_discovery_worker_count(value)`: clamps worker count to at least one and raises for invalid config.
- `get_discovery_worker_count(override=None)`: reads `EGP_DISCOVERY_WORKER_COUNT` with safe defaults.
- `DiscoveryDispatchProcessor.process_pending()`: claims up to `limit` jobs and dispatches them through a bounded worker pool.
- `DiscoveryDispatchProcessor._process_jobs_concurrently()`: private helper to submit claimed jobs and surface impossible failures.
- `build_discovery_dispatch_runtime(..., worker_count=None)`: creates a processor with configured concurrency.

Expected behavior and edge cases:
- `worker_count=1` preserves current serial behavior.
- `worker_count>1` runs claimed jobs concurrently while still using DB leases to avoid duplicate claims across executor instances.
- Dispatcher exceptions remain handled by `process_job`; jobs retry/fail exactly as before.
- Invalid worker count fails closed at startup with a clear config error.

### Test Coverage

- `test_discovery_dispatch_processor_runs_claimed_jobs_with_worker_pool`: proves concurrent dispatch.
- `test_discovery_dispatch_processor_preserves_serial_mode_with_one_worker`: proves default compatibility.
- `test_get_discovery_worker_count_reads_environment`: validates env parsing.
- `test_get_discovery_worker_count_rejects_invalid_value`: validates fail-closed config.
- `test_main_once_passes_worker_count_to_runtime_factory`: validates CLI wiring.
- `test_create_app_wires_configured_discovery_worker_count`: validates embedded app-state wiring.

### Decision Completeness

Goal: replace the serial discovery dispatcher loop with a DB lease-backed bounded worker pool.

Non-goals:
- Do not introduce Redis/Celery/RQ yet.
- Do not change the worker payload contract.
- Do not change `discovery_jobs` schema unless tests prove the existing lease is insufficient.
- Do not rewrite crawler worker internals.

Success criteria:
- Multiple claimed discovery jobs dispatch concurrently with `worker_count>1`.
- Existing retry, non-retriable, and dispatched status semantics stay green.
- External executor exposes worker count through CLI/env.
- Redis is no longer represented as active infrastructure.

Public interfaces:
- New env var: `EGP_DISCOVERY_WORKER_COUNT`, default `1`.
- New CLI flag: `--worker-count`, default from env.
- No API endpoint changes.
- No DB migrations.

Failure modes:
- Invalid worker count: fail closed at startup.
- Worker subprocess failure: existing retry/fail behavior remains.
- Executor crash with leased jobs: existing stale lease reclaim remains.
- Stop event during in-flight subprocess: existing behavior remains; in-flight subprocess completes or times out.

Rollout & monitoring:
- Deploy with `EGP_DISCOVERY_WORKER_COUNT=1` first for behavior parity.
- Raise to 2-4 after observing run durations, database load, and worker failure rate.
- Backout by setting worker count back to 1.

Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py -q`
- `./.venv/bin/ruff check apps/api packages tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py`
- `./.venv/bin/python -m compileall apps/api/src packages/db/src`

### Dependencies

No new external dependency. Uses Python stdlib `concurrent.futures` and existing DB lease semantics.

### Validation

Run focused tests three times after green to catch concurrency flakiness. Verify compose no longer depends on Redis.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `DiscoveryDispatchProcessor.worker_count` | `processor.process_pending()` | `configure_services()` and `build_discovery_dispatch_runtime()` | `discovery_jobs` existing lease columns |
| `get_discovery_worker_count()` | API service bootstrap and executor runtime factory | `config.py` imports in bootstrap/executor | N/A |
| `--worker-count` | `python -m egp_api.executors.discovery_dispatch` | `_build_parser()` and `main()` | N/A |
| Compose worker count | `discovery-executor` container env | `docker-compose*.yml` | N/A |

### Cross-Language Schema Verification

No DB migration. Existing table verified by exact search: Python uses `discovery_jobs` in repository/tests/rules service. No TypeScript table access.

### Decision-Complete Checklist

- No open decisions remain for the implementer.
- Public env/CLI interfaces are listed.
- Behavior change has concurrency and serial-compatibility tests.
- Validation commands are scoped.
- Wiring table covers all new components.
- Rollout/backout is via worker count.

## Plan Draft B - Executor-Level Async Worker Pool

### Overview

Leave `DiscoveryDispatchProcessor` serial and build an async worker pool in `egp_api.executors.discovery_dispatch`. Each async worker repeatedly calls `processor.process_pending(limit=1)` via `asyncio.to_thread`, relying on existing leases to partition jobs across workers.

### Files to Change

- `apps/api/src/egp_api/executors/discovery_dispatch.py`: introduce `run_discovery_worker_pool_loop()` with N async workers.
- `apps/api/src/egp_api/bootstrap/background.py`: call pool loop instead of old loop.
- `apps/api/src/egp_api/config.py`: worker count helper.
- `docker-compose*.yml` and docs: same Redis cleanup.
- `tests/phase2/test_discovery_executor.py`: async worker-pool behavior.

### Implementation Steps

TDD sequence:
1. Add tests for multiple async workers calling `process_pending(limit=1)` concurrently.
2. Add config/CLI tests for worker count.
3. Implement async worker pool using `asyncio.to_thread`.
4. Wire bootstrap/executor to use the new pool loop.
5. Keep processor tests unchanged except for maybe compatibility coverage.

Functions:
- `run_discovery_worker_pool_loop()`: starts worker tasks until stop event.
- `_run_discovery_worker()`: per-worker loop that processes one leased job at a time.
- `get_discovery_worker_count()`: same config helper.

Expected behavior and edge cases:
- In-flight jobs are still blocking subprocesses, but they no longer block the event loop.
- Each worker claims one job at a time, improving fairness.
- Stop event stops new claims, not already-running subprocesses.

### Test Coverage

- `test_run_discovery_worker_pool_loop_runs_workers_concurrently`: proves worker tasks overlap.
- `test_main_once_builds_runtime_with_worker_count`: CLI wiring.
- `test_background_lifespan_uses_worker_pool_loop`: bootstrap wiring.

### Decision Completeness

Goal: concurrency in the executor layer without changing processor semantics.

Non-goals: same as Draft A.

Success criteria:
- Long-running executor can have N independent claim/dispatch workers.
- Existing processor unit tests remain mostly untouched.

Public interfaces:
- New env var: `EGP_DISCOVERY_WORKER_COUNT`.
- New CLI flag: `--worker-count`.

Failure modes:
- Worker task crash: parent logs and restarts on next loop only if implemented; otherwise task dies.
- Shared processor object must be thread-safe enough for repeated calls. Existing processor is immutable and repository uses engine connections, so acceptable.

Rollout & monitoring: same as Draft A.

Acceptance checks: same focused tests plus background runtime tests.

### Dependencies

No new external dependency.

### Validation

Focused pytest and compile checks.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `run_discovery_worker_pool_loop()` | executor main and API lifespan | `discovery_dispatch.py`, `background.py` | `discovery_jobs` existing leases |
| `get_discovery_worker_count()` | executor CLI/config | `config.py` import | N/A |

### Cross-Language Schema Verification

No DB migration.

### Decision-Complete Checklist

- Public interfaces listed.
- Behavior tests listed.
- Rollout/backout listed.

## Comparative Analysis & Synthesis

Draft A is simpler to wire because existing call sites keep calling `process_pending()`, including route-kick background tasks and embedded runtime. It makes concurrency part of the dispatch processor itself, so every runtime mode benefits consistently. The downside is creating a short-lived thread pool per batch.

Draft B has a purer long-running worker-pool shape and better one-job-per-worker fairness. Its downside is more runtime-loop code and more careful task lifecycle handling, while route-kick paths would still be serial unless separately changed.

Both plans follow repo constraints: no new dependency, no schema churn, tenant scoping unchanged, and worker subprocess payload unchanged. Because the immediate problem is the serial dispatch bottleneck across all call sites, Draft A is the better first implementation. A future PR can promote this to a persistent executor-level pool if needed.

## Unified Execution Plan

### Overview

Implement a database lease-backed bounded worker pool inside `DiscoveryDispatchProcessor`, with worker count wired through config, API bootstrap, and the standalone discovery executor. Since the chosen design uses PostgreSQL leases rather than Redis, remove Redis from compose/docs so infrastructure accurately reflects runtime behavior.

### Files to Change

- `apps/api/src/egp_api/services/discovery_dispatch.py`: add worker-count field and concurrent job processing.
- `apps/api/src/egp_api/config.py`: add worker-count config parser.
- `apps/api/src/egp_api/executors/discovery_dispatch.py`: add CLI flag/env wiring into runtime builder.
- `apps/api/src/egp_api/bootstrap/services.py`: pass configured worker count to embedded processor.
- `tests/phase2/test_discovery_dispatch.py`: processor concurrency and serial compatibility tests.
- `tests/phase2/test_discovery_executor.py`: worker-count CLI/runtime wiring tests.
- `tests/phase2/test_background_runtime_mode.py`: app-state worker-count wiring test.
- `docker-compose.yml`, `docker-compose-localdev.yml`: remove Redis and set discovery worker count env.
- `AGENTS.md`, `CLAUDE.md`, `packages/db/AGENTS.md`: remove Redis from required local setup references.

### Implementation Steps

TDD sequence:
1. Add failing tests for processor concurrency, config parsing, executor CLI wiring, and app bootstrap wiring.
2. Run the focused tests and record RED failures.
3. Implement `get_discovery_worker_count()` and processor-level concurrency.
4. Wire worker count through executor and API bootstrap.
5. Update compose/docs to remove Redis and add `EGP_DISCOVERY_WORKER_COUNT` for discovery executor.
6. Run focused tests; fix defects.
7. Run ruff and compileall for touched Python surfaces.
8. Repeat focused tests three times.
9. Perform QCHECK and append implementation summary.

Functions:
- `get_discovery_worker_count(override: int | str | None = None) -> int`: parse env/override, default 1, reject invalid values.
- `DiscoveryDispatchProcessor.process_pending(limit=None) -> int`: claim pending jobs and process with bounded worker count.
- `DiscoveryDispatchProcessor._process_jobs_concurrently(jobs) -> None`: submit jobs to a thread pool when `worker_count > 1`.
- `build_discovery_dispatch_runtime(..., worker_count=None)`: construct processor with configured worker count.

Expected behavior and edge cases:
- `worker_count=1`: serial, current semantics.
- `worker_count=2+`: claimed jobs are dispatched concurrently; status updates and retries remain per job.
- Empty queue: no worker pool created.
- Invalid env/CLI: startup fails closed with `RuntimeError`/parser error.
- Dispatcher exception escaping unexpectedly from `process_job`: future result is consumed and logged/handled by existing processor boundaries if needed.

### Test Coverage

- `tests/phase2/test_discovery_dispatch.py::test_discovery_dispatch_processor_runs_claimed_jobs_with_worker_pool`: concurrent claimed jobs overlap.
- `tests/phase2/test_discovery_dispatch.py::test_discovery_dispatch_processor_preserves_serial_mode_with_one_worker`: default serial behavior remains.
- `tests/phase2/test_discovery_executor.py::test_main_once_passes_worker_count_to_runtime_factory`: CLI passes worker count to runtime factory.
- `tests/phase2/test_background_runtime_mode.py::test_get_discovery_worker_count_reads_environment`: env parsing works.
- `tests/phase2/test_background_runtime_mode.py::test_get_discovery_worker_count_rejects_invalid_value`: invalid config fails closed.
- `tests/phase2/test_background_runtime_mode.py::test_create_app_wires_configured_discovery_worker_count`: embedded processor gets worker count.

### Decision Completeness

Goal: remove the serial dispatch bottleneck by making discovery dispatch a bounded DB lease-backed worker pool.

Non-goals:
- Redis queue adoption.
- DB schema migration.
- Worker payload/protocol rewrite.
- Internal API transport rewrite.

Success criteria:
- Concurrency test fails before implementation and passes after.
- Existing retry/failure dispatch tests remain green.
- Worker count is configurable in standalone executor and embedded API mode.
- Compose no longer advertises unused Redis infrastructure.

Public interfaces:
- New env var: `EGP_DISCOVERY_WORKER_COUNT`.
- New CLI flag: `--worker-count`.
- No endpoint/schema changes.

Edge cases / failure modes:
- Invalid worker count: fail closed at startup.
- More workers than claimed jobs: pool size clamps to claimed job count.
- Executor crash: leased pending jobs remain reclaimable after stale lease window.
- Worker failure: existing retry and non-retriable logic remains authoritative.

Rollout & monitoring:
- Default remains `1`, so deploying code alone preserves behavior.
- Compose uses `${EGP_DISCOVERY_WORKER_COUNT:-2}` for local/prod-like concurrency.
- Backout by setting `EGP_DISCOVERY_WORKER_COUNT=1`.
- Watch discovery backlog, run duration, failure rate, DB connection count, and worker log paths.

Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py -q`
- repeat focused tests 3x
- `./.venv/bin/ruff check apps/api packages tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py`
- `./.venv/bin/python -m compileall apps/api/src packages/db/src`

### Dependencies

Python stdlib only. Existing DB leases are the queue/lease primitive.

### Validation

Use unit tests for concurrency and config, then inspect compose/docs for Redis removal and worker count exposure.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `DiscoveryDispatchProcessor.worker_count` | `process_pending()` | `configure_services()` and `build_discovery_dispatch_runtime()` | `discovery_jobs.processing_started_at` existing lease |
| `get_discovery_worker_count()` | API bootstrap and executor builder | imports in `bootstrap/services.py` and `executors/discovery_dispatch.py` | N/A |
| `--worker-count` | `python -m egp_api.executors.discovery_dispatch` | `_build_parser()` and `main()` | N/A |
| Compose worker count env | `discovery-executor` | `docker-compose.yml`, `docker-compose-localdev.yml` | N/A |

### Cross-Language Schema Verification

No DB migration. Exact search showed `discovery_jobs` is only used in Python repositories/services/tests; frontend does not access this table.

### Decision-Complete Checklist

- No open decisions remain.
- Public env/CLI changes listed.
- Behavior has failing-first tests.
- Acceptance commands are specific.
- Wiring table covers new code.
- Rollout/backout is explicit.


## Review (2026-05-16 14:42:32 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: feature/discovery-lease-worker-pool
- Scope: working tree based on 905e8d3a
- Commands Run: Auggie semantic search attempted and failed with HTTP 429; `git status --porcelain=v1`; `git diff --name-only`; `git diff --stat`; targeted diffs for discovery dispatch/config/repository; focused pytest; ruff; compileall; Docker Compose config validation.

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
- This implements the first lease-backed pool step using PostgreSQL `discovery_jobs` leases, not Redis. That is intentional; Redis was removed from compose so active infrastructure matches the runtime design.
- The worker subprocess remains the underlying crawler execution unit. This change replaces serial dispatch with bounded concurrent dispatch and safer lease batching; a later PR could replace subprocess execution itself with a dedicated worker transport.

### Recommended Tests / Validation
- Already run: `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py -q` three times after the final implementation; all passed.
- Already run: `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase2/test_rules_api.py -q`; passed.
- Already run: `./.venv/bin/ruff check apps/api packages tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py`; passed.
- Already run: `./.venv/bin/python -m compileall apps/api/src packages/db/src`; passed.
- Already run: `docker compose -f docker-compose-localdev.yml config --quiet`; passed.
- Already run: production `docker compose -f docker-compose.yml config --quiet` with required env placeholders; passed.

### Rollout Notes
- Default `EGP_DISCOVERY_WORKER_COUNT` remains `1`, so code deploys preserve current behavior unless configured otherwise.
- Compose defaults discovery executor concurrency to `2`; backout is setting `EGP_DISCOVERY_WORKER_COUNT=1`.
- Watch discovery backlog, crawl-run duration, failed-worker reconciliation, DB connection pressure, and worker log paths after increasing concurrency.


## Implementation Summary (2026-05-16 14:42:58 +0700)

### Goal
Replace serial discovery dispatch with a PostgreSQL lease-backed bounded worker pool, and remove Redis from active compose infrastructure because dispatch now uses existing `discovery_jobs` leases rather than a Redis queue.

### What Changed
- `apps/api/src/egp_api/services/discovery_dispatch.py`: added `worker_count`, worker-sized claim waves, concurrent claimed-job processing with `ThreadPoolExecutor`, and same-invocation retry exclusion so failed jobs are not retried repeatedly in one `process_pending()` call.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: added optional `exclude_job_ids` support to `claim_pending_discovery_jobs()` for per-invocation retry exclusion.
- `apps/api/src/egp_api/config.py`: added `get_discovery_worker_count()` for `EGP_DISCOVERY_WORKER_COUNT` parsing and fail-closed validation.
- `apps/api/src/egp_api/executors/discovery_dispatch.py`: added `--worker-count` and runtime-factory wiring.
- `apps/api/src/egp_api/bootstrap/services.py`: embedded-mode dispatch processor now uses configured worker count.
- `docker-compose.yml` and `docker-compose-localdev.yml`: removed unused Redis service/dependencies/volume and set `EGP_DISCOVERY_WORKER_COUNT` on the discovery executor.
- `AGENTS.md`, `CLAUDE.md`, `packages/db/AGENTS.md`, `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`: removed Redis from active local/compose setup references.
- `tests/phase2/test_discovery_dispatch.py`: added concurrency, serial compatibility, and worker-capacity claim batching tests.
- `tests/phase2/test_background_runtime_mode.py`: added worker-count config and app bootstrap wiring tests.
- `tests/phase2/test_discovery_executor.py`: added CLI/runtime worker-count wiring coverage.

### TDD Evidence
- RED 1: `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py -q` failed during collection because `get_discovery_worker_count` did not exist.
- RED 2: after self-review added claim-capacity coverage, `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py::test_discovery_dispatch_processor_claims_only_worker_capacity_per_batch -q` failed because the processor claimed `[5]` instead of `[2, 2, 1]`.
- GREEN: `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py -q` passed with 18 tests after implementation.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py -q` passed three consecutive final runs.
- `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase2/test_rules_api.py -q` passed.
- `./.venv/bin/ruff check apps/api packages tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_background_runtime_mode.py` passed.
- `./.venv/bin/python -m compileall apps/api/src packages/db/src` passed.
- `docker compose -f docker-compose-localdev.yml config --quiet` passed.
- `docker compose -f docker-compose.yml config --quiet` with required placeholder env passed.

### Wiring Verification
- `DiscoveryDispatchProcessor.worker_count` is used by `process_pending()` and wired from `configure_services()` for embedded mode.
- Standalone executor wires `--worker-count` through `main()` into `build_discovery_dispatch_runtime()`.
- Runtime config reads `EGP_DISCOVERY_WORKER_COUNT` through `get_discovery_worker_count()`.
- Compose discovery executor sets `EGP_DISCOVERY_WORKER_COUNT` and no longer depends on Redis.
- Existing schema remains `discovery_jobs`; no migration was added.

### Behavior / Risk Notes
- Default worker count remains `1`, so plain deploys preserve serial behavior.
- Compose defaults to `2`, giving local/prod-like executors visible pool behavior.
- Processor claims no more than active worker capacity per wave, preventing idle leased jobs from becoming stale before they start.
- Retriable failures are still retried on later `process_pending()` calls, not in a tight loop inside one call.

### Follow-Ups / Known Gaps
- The crawler execution unit is still the existing subprocess worker. This PR makes dispatch lease-backed and bounded-concurrent; a later worker-transport refactor can remove subprocess execution entirely if production scale requires it.


## Review (2026-05-16 14:46:31 +0700) - last-commit

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: feature/discovery-lease-worker-pool
- Scope: last commit `45b1c2ba` / branch diff against `main`
- Commands Run: Auggie semantic search attempted and failed with HTTP 429; `git status -sb`; `gt ls`; `gt status`; `git diff --name-status main...HEAD`; `git diff --stat main...HEAD`; targeted reads of discovery dispatch processor and discovery job repository; reused recorded validation from this coding log.

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
- This review treats PostgreSQL `discovery_jobs` leases as the intended queue primitive for this PR. Redis removal is therefore consistent with the implementation.
- The subprocess crawler remains the actual work executor; this branch only changes dispatch scheduling and lease batching.

### Recommended Tests / Validation
- Already run during implementation: focused dispatch/runtime tests passed three final runs.
- Already run during implementation: immediate-discover and rules API tests passed.
- Already run during implementation: ruff, compileall, and Docker Compose config validation passed.

### Rollout Notes
- Default `EGP_DISCOVERY_WORKER_COUNT=1` preserves current serial behavior unless explicitly configured.
- Compose defaults the standalone discovery executor to `2`; backout is setting `EGP_DISCOVERY_WORKER_COUNT=1`.
- Watch discovery backlog, run duration, failed-worker reconciliation, DB connection pressure, and worker log paths after raising concurrency.
