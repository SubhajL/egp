# Coding Log: fair-discovery-claim

## Plan Draft A

### Overview
Make discovery job claiming tenant-fair by ranking due pending jobs within each
tenant before applying the global claim limit. The dispatch loop and outbox schema stay
unchanged; only repository claim ordering changes.

### Files To Change
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: update
  `claim_pending_discovery_jobs()` to select due candidates using
  `ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY next_attempt_at, created_at, id)`.
- `tests/concurrency/test_fair_claim.py`: add a regression test proving a tenant with
  one later due job is claimed within worker-capacity cycles despite another tenant's
  large backlog.

### Implementation Steps
1. Add `test_fair_claim_reaches_later_tenant_within_worker_capacity_cycles`.
2. Run it and confirm RED: tenant B is not claimed with the current global FIFO query.
3. Build a ranked subquery in `claim_pending_discovery_jobs()`.
4. Order candidates by tenant-local rank, `next_attempt_at`, `created_at`, and id.
5. Keep stale lease filtering and `exclude_job_ids` behavior intact.
6. Run focused tests, compile, Ruff, and review.

### Test Coverage
- `test_fair_claim_reaches_later_tenant_within_worker_capacity_cycles`: later tenant
  cannot starve behind large tenant backlog.
- Existing dispatch tests: worker pool and retry behavior unchanged.

### Decision Completeness
- Goal: prevent one tenant's large queue from monopolizing discovery dispatch claims.
- Non-goals: no schema changes, no new metrics, no entitlement/admission control.
- Success criteria: tenant B's single job appears within `worker_count + 1` claim cycles
  when tenant A has 50 earlier due jobs and tenant B is due one second later.
- Public interfaces: no API, env, migration, or schema changes.
- Edge cases/failure modes: excluded IDs remain excluded; non-stale in-progress rows
  remain unclaimable; claim order is deterministic for equal timestamps via id.
- Rollout & monitoring: query-only behavior change; watch per-tenant queue depth and
  dispatch distribution.
- Acceptance checks: focused fairness test, discovery dispatch tests, Ruff, compileall.

### Dependencies
Uses SQL window functions through SQLAlchemy; SQLite and PostgreSQL both support
`ROW_NUMBER() OVER (...)`.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Fair claim query | `SqlDiscoveryJobRepository.claim_pending_discovery_jobs()` | Called by `DiscoveryDispatchProcessor.process_pending()` | `discovery_jobs` |

### Cross-Language Schema Verification
No schema changes. Existing table/columns verified in
`packages/db/src/migrations/015_discovery_jobs_outbox.sql`.

## Plan Draft B

### Overview
Keep the current query but over-fetch a larger candidate pool, then round-robin tenants
in Python before updating rows. This avoids SQL window functions but moves fairness
policy into application code.

### Files To Change
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: over-fetch due rows and
  group by tenant in Python.
- `tests/concurrency/test_fair_claim.py`: same regression coverage.

### Implementation Steps
1. Add the same failing fairness test.
2. Fetch `limit * tenant_factor` due candidates globally.
3. Group rows by tenant and interleave one row per tenant.
4. Update selected rows with existing stale filtering.
5. Run focused tests and gates.

### Test Coverage
- Same fairness regression test.
- Existing dispatch tests to cover worker behavior.

### Decision Completeness
- Goal: reduce tenant starvation without SQL window functions.
- Non-goals: no schema or dispatcher changes.
- Success criteria: same `worker_count + 1` fairness gate.
- Public interfaces: no external contract changes.
- Edge cases/failure modes: over-fetch size could still miss a later tenant when one
  tenant's backlog is much larger than the fetch multiplier.
- Rollout & monitoring: query-only, but fairness is probabilistic with bounded over-fetch.
- Acceptance checks: focused pytest, Ruff, compileall.

### Dependencies
No new dependencies.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Python interleaver | `SqlDiscoveryJobRepository.claim_pending_discovery_jobs()` | Called by `DiscoveryDispatchProcessor.process_pending()` | `discovery_jobs` |

### Cross-Language Schema Verification
No schema changes.

## Comparative Analysis
Draft A directly matches the rollout requirement to use `ROW_NUMBER() OVER
(PARTITION BY tenant_id ORDER BY next_attempt_at)` and gives deterministic fairness at
the database-selection layer. Draft B is simpler SQL but cannot guarantee the later
tenant is visible unless the over-fetch window is unbounded, which undermines the
purpose of the PR.

## Unified Execution Plan

### Overview
Implement Draft A. Keep the repository API unchanged and make the due-candidate
selection tenant-fair before existing claim updates run.

### Files To Change
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: import SQLAlchemy window
  helpers and replace the global FIFO candidate select with a ranked subquery.
- `tests/concurrency/test_fair_claim.py`: seed two tenants and assert tenant B is claimed
  within `worker_count + 1` cycles.

### TDD Sequence
1. Add `tests/concurrency/test_fair_claim.py`.
2. Run the new test and confirm RED because current query returns tenant A jobs only.
3. Implement the ranked SQLAlchemy subquery.
4. Run the new test until GREEN.
5. Run existing dispatch tests, Ruff, compileall, and formal review.

### Function Details
- `claim_pending_discovery_jobs()`: compute `tenant_rank = row_number().over(...)` for
  due rows, then order by `tenant_rank`, `next_attempt_at`, `created_at`, and `id`.
  Preserve stale lease checks and optimistic update semantics.

### Test Coverage
- `test_fair_claim_reaches_later_tenant_within_worker_capacity_cycles`: verifies
  round-robin tenant progress under a skewed queue.

### Decision Completeness
- Goal: tenant-fair discovery dispatch claims.
- Non-goals: no dispatcher worker-pool changes, no new database migration, no UI work.
- Success criteria: deterministic fairness test passes and existing dispatch behavior
  remains green.
- Public interfaces: none.
- Edge cases/failure modes: due-only rows are ranked; excluded IDs are filtered before
  rank; stale processing rows remain protected by the existing update predicate.
- Rollout & monitoring: query-only change; watch `egp_discovery_queue_depth` by tenant
  and per-tenant dispatch distribution.
- Acceptance checks: focused pytest, dispatch pytest, Ruff, compileall.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Tenant-fair candidate ranking | `claim_pending_discovery_jobs()` | Existing repository injected into `DiscoveryDispatchProcessor` | `discovery_jobs.tenant_id`, `next_attempt_at`, `created_at`, `processing_started_at` |

### Cross-Language Schema Verification
No schema changes. The relevant table and columns exist in migration 015 and the
SQLAlchemy table definition in `discovery_job_repo.py`.

## Implementation Summary (2026-05-24 07:11:06 +07)

### Goal
Implement PR-07 tenant-fair discovery job claiming and carry the branch through local
quality gates before PR submission.

### Context Gathering
- Auggie semantic search was attempted twice and returned HTTP 429 both times.
- Fallback inspection used direct reads of `packages/AGENTS.md`, `packages/db/AGENTS.md`,
  `CLAUDE.md`, `packages/db/src/egp_db/repositories/discovery_job_repo.py`,
  `apps/api/src/egp_api/services/discovery_dispatch.py`, and adjacent discovery tests.

### What Changed
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: replaced the global FIFO
  due-job candidate select with a `ROW_NUMBER() OVER (PARTITION BY tenant_id ...)`
  subquery ordered by tenant-local rank, then due time, creation time, and id. The query
  filters non-stale in-progress jobs before ranking while preserving the update predicate
  as the concurrency guard.
- `tests/concurrency/test_fair_claim.py`: added a SQLite-backed regression test that
  seeds tenant A with 50 earlier due jobs and tenant B with one later due job, then proves
  tenant B is dispatched within `worker_count + 1` worker-capacity cycles.

### TDD Evidence
- RED: `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/concurrency/test_fair_claim.py -q`
  - Result: failed because all six claimed jobs belonged to tenant A and tenant B was absent.
- GREEN: same focused command after implementation.
  - Result: `1 passed in 0.17s`.

### Tests Run
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/concurrency/test_fair_claim.py tests/phase2/test_discovery_dispatch.py -q`
  - Result: `8 passed in 0.38s`.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall packages/db/src tests/concurrency/test_fair_claim.py`
  - Result: passed.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m ruff check packages/db/src/egp_db/repositories/discovery_job_repo.py tests/concurrency/test_fair_claim.py`
  - Result: passed.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m ruff format --check packages/db/src/egp_db/repositories/discovery_job_repo.py tests/concurrency/test_fair_claim.py`
  - Result: passed after formatting the new test.

### Wiring Verification Evidence
- Runtime entry point remains `DiscoveryDispatchProcessor.process_pending()`, which calls
  `repository.claim_pending_discovery_jobs(...)`.
- Repository implementation remains `SqlDiscoveryJobRepository.claim_pending_discovery_jobs()`.
- Schema/table remains `discovery_jobs`; no migration or public interface change.

### Behavior And Risk Notes
- Behavior changes from global due-time FIFO to tenant-fair due-candidate ranking.
- Fail-open/fail-closed: claim filtering remains conservative; non-stale in-progress rows
  are not claimable, and the update predicate still rejects races after candidate selection.
- Rollout watch remains per-tenant queue depth and dispatch distribution per PR-07 plan.

### Follow-ups / Known Gaps
- No Postgres integration test was added in this PR; SQLAlchemy emits standard window
  function SQL and the SQLite-backed regression covers the behavioral contract.

## Review (2026-05-24 07:11:06 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-pr07`
- Branch: `feat/fair-discovery-claim`
- Scope: working tree
- Commands Run: `git status -sb`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`,
  targeted `git diff`, `nl -ba` on touched files, focused pytest, compileall, Ruff check,
  Ruff format check.

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
- Assumes SQLite and PostgreSQL window-function behavior are sufficient for the tested
  `ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY ...)` query shape.

### Recommended Tests / Validation
- Completed focused fairness regression plus adjacent discovery dispatch tests.
- Completed compileall and Ruff gates for touched Python files.

### Rollout Notes
- Query-only change; no flags or migrations.
- Observe `egp_discovery_queue_depth` by tenant and per-tenant dispatch distribution after deploy.
