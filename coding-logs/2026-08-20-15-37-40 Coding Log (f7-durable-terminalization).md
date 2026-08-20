# Coding Log: F7 Durable Terminalization

- Started: 2026-08-20 15:37:40 +07
- Branch: `fix/f7-durable-terminalization`
- Base: `origin/main` at `54dc285d58bf07cc0c241dd84256ee79dbbddf4b`
- Worktree: `/Users/subhajlimanond/dev/egp-f7-terminalization`
- Requested lifecycle: g-planning -> g-coding -> QCHECK -> g-check -> PR -> authorized admin merge -> exact-SHA local-main landing -> worktree removal

## Planning Evidence

- RepoPromptCE was bound to the isolated worktree and used for a focused context build covering dispatcher cleanup, queue/run consistency, reconciliation, PostgreSQL test patterns, CI wiring, consumers, and schemas.
- Nearest instructions read: `AGENTS.md`, `CLAUDE.md`, `apps/api/AGENTS.md`, `packages/AGENTS.md`, and `packages/db/AGENTS.md`.
- Runtime wiring traced through `apps/api/src/egp_api/executors/discovery_dispatch.py:build_discovery_dispatch_runtime()` and `run_discovery_dispatch_once()`, plus `apps/api/src/egp_api/main.py:_make_discover_spawner()`.
- Existing schema already provides tenant-scoped `crawl_runs.discovery_job_id`; no migration is required. Internal reservation ownership can use additive `summary_json` keys.
- Independent read-only Terra exploration confirmed that `start_new_session=True` makes the child PID the process-group ID, while the current finalizer skips group cleanup after leader exit and `_kill_process_group()` cannot rediscover a dead leader's group.
- Independent read-only Terra analysis confirmed the queue/run transaction split, the pre-spawn reconciliation blind spot, the absence of real-PostgreSQL F7 coverage, and the missing explicit `uv lock --check` CI step.

## Locked Requirements

1. A signal-crashed worker must not leave a same-process-group descendant alive.
2. A discovery job must not become terminal while its correlated active run cannot be durably terminalized.
3. Pre-spawn reservations and legacy failed-job/active-run divergence must be durably recoverable without cross-tenant mutation or duplicate dispatch.
4. The repaired contracts must run against migrated real PostgreSQL and a real child-process path; SQLite/fakes remain fast feedback only.
5. `uv lock --check` must be an explicit required CI and local gate, without changing dependencies or `uv.lock`.

# Plan Draft A: Consistency Guard and Reconciliation Metadata

## Overview

Keep the existing repository and dispatcher boundaries, but add an explicit internal failure for unconfirmed run terminalization. Keep the queue job pending and unclaimable while an active correlated run exists, then let the existing pre/post-dispatch reconciliation loop repair the run before retry. Capture the worker process-group ID at spawn so final cleanup can kill descendants after the leader has exited.

## Files to Change

- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` — capture PGID, seed reservation metadata, and propagate incomplete terminalization.
- `apps/api/src/egp_api/services/discovery_dispatch.py` — define and handle the internal incomplete-terminalization exception.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py` — exclude jobs with active tenant-matched correlated runs from claimability and claim CAS.
- `packages/db/src/egp_db/repositories/run_repo.py` — reconcile reserved/no-worker and legacy divergent runs safely.
- `tests/phase3/test_discovery_cancellation_poll.py` — behavioral dead-leader process-group regression.
- `tests/phase1/test_api_discovery_spawn.py` — reservation/spawn metadata expectations.
- `tests/phase1/test_truthful_fault_injection.py` — truthful incomplete-terminalization and real descendant cleanup expectations.
- `tests/phase1/test_project_and_run_persistence.py` — fast repository reconciliation and tenant-isolation contracts.
- `tests/phase2/test_discovery_dispatch.py` — processor pending semantics and active-run claim barrier.
- `tests/operations/test_f7_terminalization_postgres.py` — new real-PostgreSQL and real-child F7 contracts.
- `.github/workflows/ci.yml` — explicit lock check and F7 PostgreSQL selector.
- `tests/operations/test_reproducible_release_gates.py` — static CI wiring assertions.

## Implementation Steps

### TDD sequence

1. Add the focused unit/repository/PostgreSQL tests and confirm each fails for the expected missing behavior.
2. Implement captured-PGID cleanup and rerun the process regression GREEN.
3. Implement the internal incomplete-terminalization exception and processor pending behavior; rerun processor/fault tests GREEN.
4. Add reservation metadata, active-run claim exclusion, and reconciliation recovery; rerun SQLite and PostgreSQL contracts GREEN.
5. Add the CI lock step and selector; run static CI tests and `uv lock --check` GREEN.
6. Refactor minimally, verify wiring, then run Ruff, format check, compileall, relevant suites, real PostgreSQL contracts, full Python tests, and the affected scope three consecutive times.

### Functions and behavior

- `_kill_process_group(proc, *, process_group_id: int | None = None)` — prefer the captured group ID, tolerate a missing group, and avoid masking the original dispatch outcome.
- `SubprocessDiscoveryDispatcher.dispatch_cancellable()` — persist `worker_owner_pid` and `worker_dispatch_phase="reserved"` at reservation; capture `process_group_id=proc.pid` after `Popen(start_new_session=True)`; update phase to `spawned`; always kill the captured group during finalization; convert unconfirmed abnormal completion into the internal consistency exception.
- `DiscoveryRunTerminalizationIncompleteError.__init__()` — carry bounded `run_id`, `failure_code`, and original error type without child payloads or secrets.
- `DiscoveryDispatchProcessor.process_job()` — handle incomplete terminalization before max-attempt, non-retriable, and force-terminal branches; record `pending`/`retrying` with a delayed retry.
- `_no_active_correlated_run_predicate()` — tenant-scoped `NOT EXISTS` predicate for queued/running correlated runs, applied to snapshots, probes, selection, and claim CAS.
- `SqlRunRepository.fail_runs_with_missing_workers()` — repair current/dead-owner reserved runs, missing spawned workers, and legacy active runs whose tenant-matched job is already failed; preserve active-status CAS.

## Test Coverage

### `tests/phase3/test_discovery_cancellation_poll.py`

- `test_finalizer_kills_captured_group_after_signal_exit` — kills descendants after worker leader already exited.

### `tests/phase1/test_truthful_fault_injection.py`

- `test_signal_crash_cleanup_terminates_real_descendant_group` — real child crash leaves no descendant alive.
- `test_terminalization_write_failure_is_reported_incomplete` — failed run write cannot verify fault evidence.

### `tests/phase2/test_discovery_dispatch.py`

- `test_incomplete_terminalization_overrides_terminal_attempt_limit` — exhausted attempt remains pending for reconciliation.
- `test_incomplete_terminalization_overrides_forced_fault_failure` — fault canary cannot falsely reach failed.
- `test_active_correlated_run_blocks_claim_until_terminal` — duplicate reservation blocked until run cleanup.

### `tests/phase1/test_project_and_run_persistence.py`

- `test_reconcile_reserved_run_without_worker_pid` — current-owner reservation becomes worker-lost failure.
- `test_reconcile_skips_live_foreign_owner_reservation` — live alternate owner remains untouched.
- `test_reconcile_legacy_run_for_failed_correlated_job` — old divergent row becomes durably failed.
- `test_reconcile_legacy_run_is_tenant_scoped` — sibling tenant cannot be mutated.

### `tests/operations/test_f7_terminalization_postgres.py`

- `test_f7_postgres_terminalization_write_failure_recovers` — trigger outage preserves invariant then reconciles.
- `test_f7_postgres_repairs_legacy_divergent_run_tenant_safely` — real PostgreSQL repairs only correlated tenant.
- `test_f7_postgres_signal_crash_reaps_descendant_group` — real child and persistence finish consistently.
- `test_f7_ci_postgres_contract` — explicit CI database URL runs contracts.

### `tests/operations/test_reproducible_release_gates.py`

- `test_ci_verifies_uv_lock_before_frozen_sync` — exact fatal lock command is ordered first.
- `test_ci_runs_f7_postgres_contract` — database lane selects real F7 contract.

## Decision Completeness

- Goal: make F7 terminalization durable, recoverable, process-clean, and honestly tested.
- Non-goals: deployment, activation, schema migration, status vocabulary changes, dependency upgrades, `uv.lock` regeneration, browser behavior redesign, or global cross-repository transactions.
- Success criteria: signal-crash descendant disappears; queue never becomes failed while correlated run is active due to unconfirmed cleanup; pre-spawn/legacy orphans reconcile; tenant isolation holds; real PostgreSQL tests and explicit lock check pass.
- Public interfaces: no API, CLI, env-var, enum, or schema changes. Existing queue outcome `retrying` is reused. Internal additions are one exception and `summary_json` keys `worker_owner_pid` and `worker_dispatch_phase` (`reserved|spawned`).
- Failure modes: run-write outage fails closed by leaving the job pending and unclaimable; missing process group is best-effort cleanup and does not mask the original error; live/permission-inaccessible foreign owners are skipped; reconciliation CAS cannot overwrite terminal runs; candidate-only reconciliation failure does not block queue terminalization once the run is confirmed terminal.
- Rollout/backout: additive code-only rollout with no data migration. Before rollback, reconcile active runs correlated to pending/failed jobs so removing the claim barrier cannot duplicate dispatch. Monitor incomplete-terminalization logs, pending-unclaimable counts, worker-lost reconciliations, and process cleanup warnings.
- Acceptance checks: focused RED/GREEN commands; migrated temp-PostgreSQL contract; `EGP_CI_POSTGRES_CONTRACT=1` selector against service PostgreSQL; `uv lock --check`; Ruff/format/compileall; full pytest; three repeated affected-suite passes.

## Dependencies

- Existing SQLAlchemy repositories and migrations through 039.
- Existing `TempPostgresCluster`, local PostgreSQL binaries or CI `DATABASE_URL`.
- POSIX `start_new_session=True`, `os.killpg`, and signals.
- Pinned uv 0.11.32 already used by CI.

## Validation

- Trace API/standalone entry point -> processor -> subprocess dispatcher -> run repository -> queue disposition -> pre/post-batch reconciliation.
- Query correlated `discovery_jobs`/`crawl_runs` by both `tenant_id` and `discovery_job_id` after each injected failure.
- Poll both leader and descendant PIDs/process group within bounded deadlines and perform emergency test cleanup.
- Confirm no diffs to `pyproject.toml`, `uv.lock`, migrations, or migration manifest.

## Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Captured process-group cleanup | `SubprocessDiscoveryDispatcher.dispatch_cancellable()` | `build_discovery_dispatch_runtime()` and `_make_discover_spawner()` construct dispatcher | N/A |
| Incomplete-terminalization disposition | `DiscoveryDispatchProcessor.process_job()` | Processor constructed in `build_discovery_dispatch_runtime()` | `discovery_jobs.job_status`, retry/error fields |
| Active correlated-run claim barrier | queue snapshot/probe/claim repository methods | Existing `SqlDiscoveryJobRepository` factory | `discovery_jobs.id/tenant_id`; `crawl_runs.discovery_job_id/tenant_id/status` |
| Reserved-run reconciliation | `RunService.reconcile_missing_workers()` | called before/after batch by `run_discovery_dispatch_once()` | `crawl_runs.summary_json/status`; correlated `discovery_jobs` |
| Real F7 PostgreSQL contract | Pytest operations selector | `.github/workflows/ci.yml` PostgreSQL contract step | migrated `discovery_jobs`, `crawl_runs`, candidate ledger |
| uv lock check | `lint-python` job | `.github/workflows/ci.yml` after pinned uv setup | `uv.lock` |

## Cross-Language Schema Verification

- Python repository definitions and migrations agree on `discovery_jobs.id`, `discovery_jobs.tenant_id`, `crawl_runs.discovery_job_id`, `crawl_runs.tenant_id`, `crawl_runs.status`, and `crawl_runs.summary_json`.
- No TypeScript or other-language consumer writes these internal dispatch/reconciliation fields.
- Migration 029 already adds the correlation; no new SQL or manifest change is planned.

## Decision-Complete Checklist

- [x] No open implementation decisions.
- [x] Internal/public interface changes named consistently.
- [x] Every behavior change has a defect-sensitive test.
- [x] Validation commands are specific and scoped.
- [x] Wiring table covers every new behavior and CI component.
- [x] Rollout, monitoring, and backout are specified.

# Plan Draft B: Atomic Terminal Disposition Coordinator

## Overview

Move queue/run terminal disposition into a DB-package coordinator that writes the correlated run and job within one transaction, while retaining captured-PGID cleanup and a reconciliation path for crashes before the coordinator runs. This gives the strongest atomic final-state invariant but increases coupling between queue and run repositories and still needs reservation ownership for process death before terminal disposition.

## Files to Change

- All Draft A process/test/CI files.
- New `packages/db/src/egp_db/discovery_terminalization.py` — transactional correlated run/job disposition coordinator.
- `apps/api/src/egp_api/services/discovery_dispatch.py` — delegate terminal disposition decisions to coordinator rather than recording them independently.
- `apps/api/src/egp_api/executors/discovery_dispatch.py` — wire the coordinator from the shared engine.

## Implementation Steps

### TDD sequence

1. Add a PostgreSQL test proving the coordinator rolls back both run and job when either write fails; confirm RED because no atomic coordinator exists.
2. Add signal-crash descendant RED and reservation-reconciliation RED tests.
3. Implement captured-PGID cleanup.
4. Implement `complete_correlated_dispatch_failure()` with tenant/job/run correlation and one engine transaction.
5. Route post-reservation queue disposition through the coordinator; retain reconciliation for process crashes before handoff.
6. Add real PostgreSQL, CI lock, lint, format, compile, full tests, and three repeated affected runs.

### Functions and behavior

- `_kill_process_group(..., process_group_id=...)` and dispatcher capture behave as in Draft A.
- `complete_correlated_dispatch_failure()` locks the queue/run pair, terminalizes the run, reconciles candidate status if transactionally feasible, and records either pending or failed job status atomically.
- `DiscoveryDispatchProcessor.process_job()` receives a structured correlated completion result and avoids direct queue writes for post-reservation failures.
- `fail_runs_with_missing_workers()` still handles dead pre-spawn owners and historical divergence.

## Test Coverage

- `test_atomic_terminalization_rolls_back_queue_when_run_write_fails` — neither side commits on run failure.
- `test_atomic_terminalization_rolls_back_run_when_queue_write_fails` — transaction preserves paired state.
- `test_atomic_terminalization_is_tenant_scoped` — correlation cannot cross tenant boundary.
- The process cleanup, legacy recovery, PostgreSQL child, CI selector, and uv tests from Draft A remain.

## Decision Completeness

- Goal: enforce run/job terminal state atomically and close process leaks.
- Non-goals: schema migration, dependency changes, public status changes, deployment, or activation.
- Success criteria: transactional tests prove all-or-nothing terminal writes; descendant cleanup and orphan recovery pass; real PostgreSQL and lock gates pass.
- Public interfaces: no external changes; new internal coordinator result type and repository transaction boundary.
- Failure modes: either terminal write failure rolls back both and leaves the job leased/pending for recovery; database unavailability fails closed; stale claim tokens abort the transaction; process cleanup remains best effort.
- Rollout/backout: code-only but high coupling. Backout must ensure no coordinator-owned partial lease remains and run reconciliation is healthy.
- Acceptance checks: coordinator fault triggers, real child, full relevant suite, lock/lint/format/compile/full tests, and repeated affected scope.

## Dependencies

- A single shared SQLAlchemy engine/connection must be threaded through the coordinator.
- Existing repositories need connection-aware methods or duplicated SQL statements.
- Candidate reconciliation may require expansion of the transaction boundary.

## Validation

- PostgreSQL triggers independently fail run and job writes and prove rollback.
- Verify runtime factory supplies exactly one engine/transaction boundary.
- Verify existing API/in-memory test doubles still satisfy processor contracts or are adapted explicitly.

## Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Atomic terminal coordinator | `DiscoveryDispatchProcessor.process_job()` post-reservation failure | constructed in `build_discovery_dispatch_runtime()` from shared engine | `discovery_jobs`, `crawl_runs`, candidate ledger |
| Captured PGID cleanup | dispatcher finalization | existing dispatcher factories | N/A |
| Orphan reconciliation | pre/post batch | `run_discovery_dispatch_once()` | active `crawl_runs` and correlated job |
| PostgreSQL/uv gates | Pytest and lint CI jobs | `.github/workflows/ci.yml` | migrated DB and `uv.lock` |

## Cross-Language Schema Verification

- Same verified Python/migration fields as Draft A; no frontend contract changes.
- Coordinator must use migration-defined table names, not create parallel schema models.

## Decision-Complete Checklist

- [x] Alternative is implementable and testable.
- [x] Public/internal surfaces are named.
- [x] Transaction failure behavior is explicit.
- [x] Runtime wiring and validation are identified.
- [x] Rollout/backout risks are explicit.

# Comparative Analysis and Synthesis

## Strengths

- Draft A fits the current architecture, reuses the existing retry disposition and reconciliation loop, avoids a migration, and directly prevents duplicate reservation while cleanup is unavailable.
- Draft B gives the strongest atomic write guarantee and a simple database invariant when both records are available in one transaction.

## Gaps and Trade-offs

- Draft A intentionally allows a temporary pending-job/active-run state, so correctness depends on a claim barrier plus reconciliation; its tests must prove both pieces.
- Draft B requires connection-aware repository APIs or duplicated SQL, couples the app processor to DB transaction mechanics, complicates candidate reconciliation, and does not remove the need for orphan metadata when the process dies before transaction coordination.
- Both need captured-PGID cleanup, pre-spawn ownership evidence, legacy recovery, real PostgreSQL coverage, and the lock gate.

## Compliance Check

- Both preserve tenant scoping, PostgreSQL as source of truth, explicit lifecycle states, TDD, and standard non-main PR workflow.
- Draft A better preserves the current control-plane service/repository separation and makes the smallest maintainable change.
- Draft B's broader transaction refactor adds risk beyond the four verified gaps.

# Unified Execution Plan

## Overview

Adopt Draft A's explicit incomplete-terminalization state, active correlated-run claim barrier, and reconciliation metadata. Borrow Draft B's invariant-driven PostgreSQL fault testing: use real triggers and durable queries to prove no terminal queue state is committed while a correlated run remains active, without introducing a new transaction coordinator.

## Files to Change

- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
- `apps/api/src/egp_api/services/discovery_dispatch.py`
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`
- `packages/db/src/egp_db/repositories/run_repo.py`
- `tests/phase3/test_discovery_cancellation_poll.py`
- `tests/phase1/test_api_discovery_spawn.py`
- `tests/phase1/test_truthful_fault_injection.py`
- `tests/phase1/test_project_and_run_persistence.py`
- `tests/phase2/test_discovery_dispatch.py`
- `tests/operations/test_f7_terminalization_postgres.py` (new)
- `tests/operations/test_reproducible_release_gates.py`
- `.github/workflows/ci.yml`
- This Coding Log and `.codex/coding-log.current`

## Implementation Steps

### Slice 1: dead-leader process-group cleanup

1. Add `test_finalizer_kills_captured_group_after_signal_exit` and the real descendant crash regression.
2. Run scoped tests and confirm RED because final cleanup is skipped or PGID lookup fails after leader death.
3. Extend `_kill_process_group()` with captured PGID and make dispatcher finalization signal it regardless of `poll()`.
4. Run scoped tests GREEN, minimally refactor, and verify `start_new_session=True` remains the registration invariant.

### Slice 2: truthful queue behavior on terminalization failure

1. Add processor and fault tests for max-attempt and forced-terminal cases.
2. Confirm RED because the queue becomes failed while the run remains queued.
3. Add `DiscoveryRunTerminalizationIncompleteError`; raise it whenever post-reservation abnormal completion cannot confirm run terminality.
4. Handle it before ordinary terminal/retry branches and record `pending`/`retrying`.
5. Run scoped tests GREEN and verify bounded/redacted diagnostics.

### Slice 3: claim barrier and durable reconciliation

1. Add SQLite and real-PostgreSQL tests for active-run claim exclusion, reserved/no-PID recovery, foreign live-owner safety, legacy failed-job recovery, active-status CAS, and tenant isolation.
2. Confirm RED for missing reservation metadata/reconciliation and claim predicate.
3. Persist reservation phase/owner in `create_run()`, transition to `spawned`, add the tenant-scoped claim predicate, and expand missing-worker reconciliation.
4. Run SQLite and PostgreSQL tests GREEN and trace pre/post-batch runtime wiring.

### Slice 4: honest PostgreSQL and lock gates

1. Add the operations contract file and CI selector assertions; confirm RED because the selector/step are absent.
2. Add explicit `Verify uv lockfile: uv lock --check` before frozen sync and the F7 PostgreSQL selector.
3. Run `uv lock --check`, static CI tests, and real PostgreSQL contracts GREEN without modifying dependency or migration sources.

### Final verification and delivery

1. Run focused unit/integration suites, Ruff, format check, compileall, migration/manifest checks, full Python tests, and affected tests three consecutive times.
2. Perform independent QCHECK, remediate findings, stage only intended files, and run formal `g-check`; rerun when remediation materially changes the surface.
3. Commit with Conventional Commit, push, create one PR to `main`, verify exact head and mergeability, and apply the standing billing-lock policy only to known zero-step unavailable hosted jobs.
4. Admin-merge the accepted candidate, synchronize dirty-preserving local `main` exactly to `origin/main`, verify the merge SHA, rerun relevant post-merge checks, preserve evidence, and follow worktree closeout protocol before removing the isolated worktree and merged branch.

## Test Coverage

- All named tests from Draft A are required.
- PostgreSQL trigger failure is the strong oracle for durable terminalization write failure.
- Real child signal crash is the strong oracle for descendant cleanup.
- Tenant-sibling rows and active-status CAS are negative safety cases.
- Static workflow tests prove the explicit lock and PostgreSQL CI wiring.

## Decision Completeness

- Goal: close all four supplied gaps and land the exact reviewed candidate on `origin/main` and local `main`.
- Non-goals: deployment, runtime activation/restart, schema migration, new external API/status/env/CLI vocabulary, dependency updates, or Graphite.
- Success criteria: every locked requirement has direct behavioral evidence; all gates and three repeated affected runs pass; QCHECK/g-check findings are resolved; PR is merged; local `main` equals the exact merged `origin/main`; primary dirty state is preserved; session worktree is removed.
- Public interfaces: unchanged. Internal exception and additive JSON summary keys only.
- Edge/failure behavior: fail closed to pending/unclaimable on uncertain run terminality; best-effort process cleanup never masks original errors; skip live/inaccessible foreign owners; active-status CAS protects concurrent completion; no cross-tenant correlation; trigger cleanup uses `try/finally`.
- Rollout/monitoring: additive code-only rollout, no activation in this task. Watch incomplete-terminalization errors, claimable vs pending deltas, worker-lost recovery counts, queue/run divergence, and process-group cleanup warnings. Reconcile active correlated runs before rollback.
- Acceptance checks: exact RED/GREEN commands recorded per slice; `uv lock --check`; real PostgreSQL operations contracts; Ruff and format check; compileall; migration manifest; full pytest; three consecutive affected-suite passes; exact-SHA post-merge rerun.

## Dependencies

- Existing migrations and schema correlation.
- Local or CI PostgreSQL 15+ test infrastructure.
- Existing CI-pinned uv 0.11.32.
- POSIX process-group semantics.
- GitHub CLI authorization already implied by the requested full lifecycle.

## Validation

- Required focused suites: phase 1 fault/persistence/spawn, phase 2 dispatch/profile, phase 3 cancellation, operations F7 PostgreSQL and reproducible gates.
- Final relevant gates: `uv lock --check`; Ruff check; Ruff format check; compileall; migration manifest verification; full Python pytest; repeat affected scope three times.
- Git/PR: no unintended files, exact PR head, no non-billing failures, mergeable state, merged SHA equality across `origin/main` and local `main`.
- Closeout: compare original seven dirty primary paths and pre-existing worktree ledger; no session-created path or branch remains.

## Wiring Verification

| Component | Non-test Call Site / Entry Point | Registration / Config Load | Schema / Contract Match |
|---|---|---|---|
| Captured process-group cleanup | `SubprocessDiscoveryDispatcher.dispatch_cancellable()` | dispatcher factories in executor and API main | `start_new_session=True` proves `pgid == child pid` |
| Incomplete-terminalization handling | `DiscoveryDispatchProcessor.process_job()` | runtime processor in `build_discovery_dispatch_runtime()` | existing `pending`/`retrying`, error code fields |
| Active-run claim barrier | queue snapshot/probe/claim methods | existing SQL repository factory | tenant + job correlation, active run statuses |
| Reservation metadata | run creation/update in dispatcher | same runtime dispatcher | `crawl_runs.summary_json` additive keys |
| Reserved/legacy reconciliation | `RunService.reconcile_missing_workers()` | pre/post batch in `run_discovery_dispatch_once()` | active-status CAS; correlated job/run tenant fields |
| Real F7 PostgreSQL contract | operations pytest selector | PostgreSQL CI contract step | fully migrated service DB |
| uv lock verification | lint-python CI job | after setup-uv, before frozen sync | committed `uv.lock` and workspace manifests |

## Cross-Language Schema Verification

- Verified actual Python/migration table names: `discovery_jobs` and `crawl_runs`.
- Verified actual correlation/status fields: `id`, `tenant_id`, `discovery_job_id`, `job_status`, `status`, `summary_json`, `last_error`, and `last_error_code`.
- No web/TypeScript change consumes the internal summary keys or exception.
- No migration or manifest edit is required or permitted by this plan.

## Decision-Complete Checklist

- [x] No open decisions remain for implementation.
- [x] Every internal/public interface is listed and consistently named.
- [x] Every behavior change has a test designed to fail on the known defect.
- [x] Validation commands and strong oracles are explicit.
- [x] Wiring table covers runtime entry points, registration, and schema.
- [x] Rollout, monitoring, backout, merge, landing, and cleanup are specified.

## Work Unit (2026-08-20 15:45 +07) - Dead-leader process-group cleanup

- Goal: preserve the worker's known process-group ID and kill descendants even after the leader has exited by signal.
- Files changed: `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`, `tests/phase3/test_discovery_cancellation_poll.py`, and `tests/phase1/test_truthful_fault_injection.py`.
- Tests added: `test_cleanup_uses_captured_process_group_after_leader_exit` and `test_signal_crash_cleanup_terminates_real_descendant_process_group`.
- RED command: `PYTHONPATH=apps/api/src:apps/worker/src:packages/crawler-core/src:packages/db/src:packages/document-classifier/src:packages/domain/src:packages/notification-core/src:packages/observability/src:packages/shared-types/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase3/test_discovery_cancellation_poll.py::test_cleanup_uses_captured_process_group_after_leader_exit tests/phase1/test_truthful_fault_injection.py::test_signal_crash_cleanup_terminates_real_descendant_process_group -q`
- Expected RED: helper rejected the captured `process_group_id`, and the real signal-crash descendant remained alive.
- GREEN command: same scoped command with worktree-local `PYTHONPATH`.
- GREEN result: `2 passed`.
- Implementation: `_kill_process_group()` accepts a captured group ID; `dispatch_cancellable()` captures the real Popen PID only when the process exposes `poll`, kills the group immediately on negative return code, reuses it for timeout cleanup, and always signals it in the finalizer before releasing the profile lock.
- Wiring evidence: the dispatcher is constructed by both `build_discovery_dispatch_runtime()` and `_make_discover_spawner()`; `start_new_session=True` remains the invariant making child PID equal process-group ID.
- Risk behavior: `ProcessLookupError` means cleanup is already complete; permission/other OS errors fall back to leader kill; cleanup never masks the original dispatch error.
- Environment note: the shared primary `.venv` is usable for dependencies but its editable imports point to the primary checkout, so all worktree tests explicitly set `PYTHONPATH` to the isolated sources.

## Work Unit (2026-08-20 16:00 +07) - Truthful incomplete-terminalization disposition

- Goal: prevent max-attempt and forced-fault logic from terminally failing a queue job when its reserved run could not be confirmed terminal.
- Files changed: `apps/api/src/egp_api/services/discovery_dispatch.py`, `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`, `tests/phase2/test_discovery_dispatch.py`, and `tests/phase1/test_truthful_fault_injection.py`.
- Test contract: `test_incomplete_terminalization_overrides_terminal_attempt_rules[False|True]` and the updated `test_terminalization_audit_reports_failed_durable_transition`.
- RED commands: the focused processor test failed with `outcome='failed'` for both exhausted and forced-terminal modes; the focused fault audit raised the old `NonRetriableDiscoveryDispatchError` while leaving the run queued.
- GREEN commands: the two focused commands plus `... python -m pytest tests/phase1/test_truthful_fault_injection.py tests/phase2/test_discovery_dispatch.py -q` using the worktree `PYTHONPATH`.
- GREEN result: `37 passed` across the complete fault and dispatch modules.
- Implementation: added bounded `DiscoveryRunTerminalizationIncompleteError`; dispatcher abnormal paths raise it when neither terminalized nor already-terminal run state is confirmed; signal termination carries an internal confirmation marker to avoid duplicate uncertain cleanup; processor handles the exception before non-retriable, max-attempt, and force-terminal branches and records `pending`/`retrying`.
- Fail-closed behavior: the attempt is counted and retry time recorded, but the queue job cannot claim terminal success/failure from an unconfirmed run write. Candidate-only reconciliation failure does not trigger this queue hold when run terminality is confirmed.
- Wiring evidence: the exception crosses the existing dispatcher-to-processor boundary only; no public API, enum, schema, CLI, or environment contract changed.

## Work Unit (2026-08-20 16:20 +07) - Reservation recovery and active-run claim barrier

- Goal: make pre-spawn reservations identifiable/recoverable and prevent duplicate claims while any tenant-matched correlated run remains active.
- Files changed: dispatcher reservation metadata, `discovery_job_repo.py`, `run_repo.py`, and their phase 1/2 tests.
- RED command: focused parameterized fault metadata, reserved-run reconciliation, active-run claim, and legacy repair tests using worktree `PYTHONPATH`.
- Expected RED: spawned phase key absent; current-owner reserved/no-PID run skipped; active correlated job still claimable; legacy failed-job/queued-run divergence unrepaired.
- GREEN command: `... python -m pytest tests/phase1/test_truthful_fault_injection.py tests/phase1/test_project_and_run_persistence.py tests/phase2/test_discovery_dispatch.py -q`.
- GREEN result: `63 passed`.
- Additional negative tests: dead foreign owner reservation is recovered; live foreign owner reservation is skipped; tenant-mismatched sibling run correlated to the same job ID remains queued.
- Implementation: dispatcher seeds `worker_owner_pid` and `worker_dispatch_phase='reserved'` atomically with run creation, then merges `worker_dispatch_phase='spawned'` with child PID. Queue snapshot/probe/candidate selection/claim CAS all use the same tenant-scoped `NOT EXISTS` active-run predicate. Missing-worker reconciliation now handles current/dead-owner reservations, missing spawned workers, and legacy active runs correlated to failed jobs, with tenant+run+active-status CAS.
- Fast gates: focused Ruff check passed; Ruff format check identified three touched production files, which were formatted with Ruff before continuing.
- Wiring evidence: existing `run_discovery_dispatch_once()` invokes `RunService.reconcile_missing_workers()` before and after joined batch processing, so current-owner pre-spawn reservations are not reconciled during a live reservation window.
- Fail-closed behavior: live or permission-inaccessible foreign owners are skipped; malformed/no-owner legacy rows are changed only when a tenant-matched correlated job is already terminal failed; pending count remains truthful while claimable count excludes the blocked job.

## Work Unit (2026-08-20 16:55 +07) - Real PostgreSQL and explicit uv lock gates

- Goal: replace overstated persistence evidence with migrated real-PostgreSQL contracts and execute the previously omitted lockfile check.
- Files changed: new `tests/operations/test_f7_terminalization_postgres.py`, `.github/workflows/ci.yml`, and `tests/operations/test_reproducible_release_gates.py`.
- PostgreSQL contract: a real trigger rejects `crawl_runs.status -> failed`; the processor records `pending/retrying`; the active run blocks claim; trigger removal plus `RunService` reconciliation fails the run and reconciles an accepted candidate to unknown; a retry then produces a terminal run/job pair. Separate scenarios prove legacy tenant-safe repair and real signal-crash descendant cleanup.
- PostgreSQL command: `.venv/bin/python -m pytest tests/operations/test_f7_terminalization_postgres.py -q` (first run used the shared dependency environment with worktree `PYTHONPATH`; later gates use the worktree-local `.venv`).
- PostgreSQL result: `3 passed, 1 skipped`; the skip is only the explicitly CI-gated `DATABASE_URL` duplicate of the same helpers.
- CI RED command: focused static workflow tests; expected failures were missing `Verify uv lockfile` and missing F7 PostgreSQL selector.
- CI GREEN result: `2 passed` after adding exact `uv lock --check` before frozen sync and the explicit `test_f7_ci_postgres_contract` selector.
- Bootstrap: `./scripts/bootstrap_python_env.sh` installed repository-pinned uv 0.11.32 under the disposable worktree and created a worktree-local frozen environment.
- Lock command: `.tools/uv-0.11.32/bin/uv lock --check`.
- Lock result: exit 0, `Resolved 92 packages`; no dependency declarations or lockfile were modified.
- Fast gates: Ruff check passed; the new PostgreSQL module was formatted with Ruff and rechecked.
- Wiring evidence: `db-migrations` already provides PostgreSQL 15, migrations, `DATABASE_URL`, and `EGP_CI_POSTGRES_CONTRACT=1`; the new selector exercises the same contract helpers on that service database.

## Work Unit (2026-08-20 17:35 +07) - Full-suite compatibility

- Goal: prove the stricter terminalization contract across the complete Python suite and repair only test seams that previously treated a no-op repository as durable persistence.
- First full-suite diagnostics found structured-logging, immediate-dispatch, and browser-isolation tests expecting the original dispatch exception while their fake repositories returned no terminalized run.
- Resolution: those logging/browser tests now inject explicit confirming run repositories. Production code remains fail-closed: an unconfirmed run write raises `DiscoveryRunTerminalizationIncompleteError` and keeps the queue job retryable.
- Focused results: structured logging `15 passed`; immediate discovery `13 passed`; browser isolation `3 passed`.
- Full command: `.venv/bin/python -m pytest tests apps packages -q`.
- Full result: `1788 passed, 4 skipped, 114 warnings` in 234.03 seconds.
- Cleanup: removed the test-created disposable worktree `test.sqlite3`; the unrelated untracked `test.sqlite3` in the user's primary checkout was not touched.

## Work Unit (2026-08-20 18:05 +07) - Independent QCHECK remediation

- Independent reviewers found: a missing active-status CAS in `fail_run_if_active`; same-process reconciliation could fail a legitimately live reservation; signal-path incomplete terminalization was caught by the generic handler and attempted twice; fault/signal helpers did not accept an already-terminal run; pre-spawn terminalization failure could bypass evidence-writer cleanup; and the real PostgreSQL outage scenario covered spawned rather than reserved state.
- RED contracts: same-process live reservation, signal single-attempt terminalization, already-terminal failed/cancelled/succeeded/partial readback, evidence close under spool plus run-write failure, and a real-PostgreSQL interleaving where success commits between the read and failure update. The focused RED run failed all three fast contracts, the evidence-close contract, and the PostgreSQL CAS contract for the expected reasons.
- Implementation: `fail_run_if_active` now repeats active status in its update CAS; reconciliation joins correlated lease evidence and skips live same-process reservations while the job claim is active; uncorrelated same-process reservations remain untouched; the dispatcher propagates `DiscoveryRunTerminalizationIncompleteError` before the generic handler; fault/signal paths tenant-safely accept every non-active status; and pre-spawn cleanup is in `finally` blocks.
- PostgreSQL contract now injects failure after run reservation but before `Popen`, proves `worker_dispatch_phase='reserved'` with no worker PID, keeps the job pending/unclaimable during the trigger outage, then reconciles and retries after trigger removal. A second real-PostgreSQL contract proves a concurrently succeeded run cannot be overwritten to failed.
- Test-stability note: the existing lease heartbeat test twice exposed host-scheduler flakiness with a 120 ms lease. Its contract was preserved while widening the lease/heartbeat window to 500/50 ms; five concurrent isolated repetitions passed.
- GREEN result after remediation: focused persistence/dispatcher/PostgreSQL modules `79 passed, 1 skipped`, followed by the expanded affected scope three consecutive times at `163 passed, 1 skipped` each.

## Final Quality Gates (2026-08-20 18:20 +07)

- Full Python suite: `.venv/bin/python -m pytest tests apps packages -q` -> `1799 passed, 4 skipped, 114 warnings` in 238.05 seconds.
- Legacy crawler suite: `.venv/bin/python -m pytest test_egp_crawler.py -q` -> `157 passed`.
- Affected scope stabilization: three consecutive final passes of `163 passed, 1 skipped`; the skip is the explicit `DATABASE_URL` CI wrapper while the same helpers ran on temporary migrated PostgreSQL.
- Ruff: `.venv/bin/ruff check apps packages tests scripts` -> all checks passed.
- Touched-file format: 17 files already formatted. Repository-wide format remains the pre-existing unrelated 42-file baseline drift and was not rewritten.
- Compile: `.venv/bin/python -m compileall -q apps packages` -> exit 0.
- Dependency lock: `.tools/uv-0.11.32/bin/uv lock --check` -> resolved 92 packages, exit 0, no lock diff.
- Migration manifest: 41 SQL files verified, no migration or manifest diff.
- Web gates: `npm ci`, `npm run build`, and `npm run typecheck` all passed; install reported the existing four high-severity audit advisories without changing the lockfile.

## Work Unit (2026-08-20 19:05 +07) - Formal review race and durability remediation

- Review findings accepted: run reservation was not atomically tied to the queue claim; a swallowed post-spawn summary write could leave a live child indistinguishable from a pre-spawn reservation; legacy metadata-less reservations had no conservative recovery path; and already-terminal succeeded/partial runs could have accepted candidates destructively reconciled after a parent-side failure.
- RED contracts: real-PostgreSQL stale-claim reservation, stale metadata-less legacy reservation, and real-child spawned-summary failure tests; plus status-parameterized candidate preservation. Expected REDs were a missing claim-token interface, no legacy recovery, a payload sentinel written by the unreaped child, and candidate reconciliation for durable success/partial states.
- Implementation: `SqlRunRepository.create_run()` now locks and validates the exact tenant/job/claim-token lease in the same transaction as run insertion; the dispatcher passes the claim token and the processor records claim loss as `LEASE_LOST`. The first post-`Popen` spawned evidence write is mandatory, so failure enters abnormal terminalization and unconditional captured-process-group cleanup before any payload is sent.
- Legacy compatibility: reconciliation recovers only tenant-correlated, metadata-less active runs older than five minutes with no active queue lease. Tenant/run/status CAS remains authoritative.
- Durable terminal semantics: run terminalization/readback now precedes candidate repair. Succeeded/partial runs preserve accepted candidates; failed/cancelled runs retain the existing reconciliation behavior. Dispatcher-side abnormal helpers use the same terminal-status rule.
- GREEN evidence: the targeted production/test slice passed `80 passed, 1 skipped`, the complete real-PostgreSQL F7 module passed `8 passed, 1 skipped`, and the strengthened terminal-status unit contract passed all four statuses.

## Final Quality Gates (2026-08-20 19:30 +07)

- Full Python suite: `.venv/bin/python -m pytest -q` -> `1960 passed, 4 skipped, 114 warnings` in 238.57 seconds.
- Affected scope stabilization after the final review changes: three consecutive passes of `167 passed, 1 skipped`.
- Legacy crawler: `157 passed`.
- Ruff: repository check passed; all 17 touched Python files are formatted.
- Compile: `.venv/bin/python -m compileall -q apps packages` -> exit 0.
- Dependency lock: `.tools/uv-0.11.32/bin/uv lock --check` -> uv 0.11.32 resolved 92 packages with no lock change.
- Migration manifest: 41 migration files verified with `--check`; no schema change.
- Web: `npm ci`, `npm run build`, and `npm run typecheck` passed. The existing four high-severity npm audit advisories remain outside this Python terminalization change and the lockfile is unchanged.

## Work Unit (2026-08-20 20:05 +07) - Formal g-check remediation

- Formal review found five remaining races: candidate cleanup could run without confirmed terminality; terminal candidate cleanup had no later durable retry; unexpected post-spawn exceptions terminalized before reaping; claim expiry was checked against a pre-lock clock; and PID reuse could suppress orphan recovery indefinitely.
- Independent QCHECK additionally found two exception-path defects: evidence-writer close could replace the retry-safe terminalization exception, and fault signal verification could lose its already-terminal marker and execute terminalization twice.
- RED evidence: seven initial contracts failed for success/partial readback, unknown-status cleanup suppression, child-reap ordering, stale live PID recovery, retrying accepted candidates on a terminal run, and post-lock lease expiry. Three additional contracts failed for active-lease authority, close-error preservation, and single-pass signal cleanup.
- Implementation: abnormal completion always reads back after a failed write and reconciles candidates only for confirmed failed/cancelled runs. `SqlCandidateAttemptRepository.list_open_candidate_runs()` exposes the durable accepted-candidate backlog; `RunService.reconcile_missing_workers()` now sweeps that backlog for failed/cancelled runs on later dispatch-loop passes.
- Process/claim ordering: unexpected post-spawn failures kill and reap the captured process group before database terminalization; `create_run()` locks the exact claimed job, then samples a fresh clock to validate lease expiry; active database leases override local PID visibility; inactive stale reservations recover even if an unrelated process reused the recorded PID.
- Exception integrity: pre-spawn evidence close failures are logged without replacing the primary exception. Fault-verification replacement exceptions retain `run_terminalization_confirmed`, and the non-retriable handler checks that marker before any fault cleanup.
- GREEN evidence: all ten new contracts passed; the combined PostgreSQL/abnormal/persistence/fault/dispatch slice passed `90 passed, 1 skipped`.

## Work Unit (2026-08-20 20:40 +07) - Second formal review remediation

- Remaining formal findings: fault/signal helpers still bypassed shared candidate gating; a waiting replacement claim could use a pre-reservation statement snapshot; late worker writes could revive terminal runs; preserved successful candidates could starve the bounded cleanup backlog; and replay used a generic terminal reason.
- Implementation: every fault/signal helper now reconciles only after a successful failure transition or explicit failed/cancelled readback. Claim updates lock the job row before a fresh CAS statement, while run reservation rejects any existing tenant-correlated active run under that same job-row lock.
- State machine: `mark_run_started()` is a queued-to-running CAS and `mark_run_finished()` changes only queued/running rows. Terminal states are immutable, including against late successful worker commits.
- Cleanup backlog: accepted-candidate enumeration joins `crawl_runs` and selects failed/cancelled rows before applying its limit, so intentionally preserved success/partial candidates cannot starve repair. Replay derives timeout, termination, and lease-loss reasons from durable run failure evidence.
- New contracts: no candidate reconciliation with unconfirmed fault terminality; one claim token cannot create a second active run; late start/success writes cannot revive failed state; and 101 older successful accepted-candidate runs cannot hide a failed cleanup row behind the 100-row limit.
- GREEN evidence: the combined PostgreSQL/abnormal/persistence/fault/dispatch slice passed `93 passed, 1 skipped`.

## Work Unit (2026-08-20 21:10 +07) - Final lifecycle race remediation

- Final review/QCHECK findings accepted: per-row batch claims used a pre-lock lease clock; durable success/partial could still requeue the parent job; failed reap was not a terminalization gate; expired cross-host leases lacked a staleness grace; concurrent summary writes could be overwritten; and job-only correlation lacked tenant validation.
- Claim/run serialization: each claimed row gets a fresh post-lock clock and full lease interval. Run reservation validates tenant ownership for every correlated job, locks claim state, rejects existing active correlated runs, and late claim CAS executes with a fresh statement snapshot.
- Durable success: abnormal completion reports the observed status. A succeeded/partial readback raises a typed already-completed outcome that records the queue job as dispatched instead of retrying.
- Reap/fencing: an unexpected post-spawn cleanup failure now raises the retry-safe incomplete exception before any run/candidate terminalization, leaving the active-run barrier in place. Correlated foreign reservations also receive the five-minute stale-activity grace after lease expiry before local PID absence can recover them.
- Write integrity: `fail_run_if_active()` locks the run row before merging summary evidence; production `create_run()` rejects cross-tenant job correlation. Legacy divergent-row fixtures now use direct database setup to keep the production API safe.
- Additional contracts cover fresh post-lock lease timestamps, durable completed-run queue disposition, failed-reap retryability, duplicate reservation rejection, terminal immutability, cleanup-starvation prevention, and the existing real-PostgreSQL CAS under the new row-lock protocol.
- GREEN evidence: the combined PostgreSQL/abnormal/persistence/fault/dispatch slice passed `97 passed, 1 skipped`.

## Formal g-check Disposition (2026-08-20 21:45 +07)

- Review inputs: four formal staged-diff passes plus two independent Terra QCHECK passes. All reported P1/P2 findings were reproduced or accepted from concrete race traces and remediated; no finding was waived as a known defect.
- Final remediations after the last pass: specialized fault/signal success readback now uses the already-completed queue disposition; completed-run recovery locks the job and atomically records dispatched even across claim loss; every summary read/merge/write is row-locked; fresh foreign-owner observations require staleness before recovery; and per-row claim lease timestamps are sampled after locking.
- Compatibility: established confirming test repositories that omit a status field are interpreted as the failed transition they confirmed; the complete affected suite verifies those seams.
- Final severity disposition: no remaining P0, P1, P2, or P3 findings in the accepted candidate.

## Final Candidate Gates (2026-08-20 22:00 +07)

- Full Python suite: `1974 passed, 4 skipped, 114 warnings` in 238.75 seconds.
- Expanded affected suite: three consecutive passes of `181 passed, 1 skipped` after all formal-review remediations.
- Real PostgreSQL F7 module is included in both suites; only the explicit CI `DATABASE_URL` duplicate wrapper is skipped locally.
- Legacy crawler: `157 passed`.
- Ruff repository check: passed. Touched-file format: 19 files already formatted.
- Compileall: passed. uv 0.11.32 lock check: 92 packages resolved with no lock change. Migration manifest: 41 files verified.
- Web gates remained green from the same candidate worktree: `npm ci`, production build, and TypeScript typecheck passed; no web or lockfile file changed after those gates.
