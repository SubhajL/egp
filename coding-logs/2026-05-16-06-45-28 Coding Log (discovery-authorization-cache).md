# Discovery Authorization Cache — PR 2 Plan

## Plan Draft A — Minimal worker-local caching

### Overview
Cache discovery authorization data at the narrowest hot spots: once per worker run in `run_discover_workflow()` and once per tenant in the scheduled keyword batch. Reuse the existing shared snapshot evaluator so user-visible authorization behavior remains unchanged while eliminating repeated repository reads.

### Files to Change
- `apps/worker/src/egp_worker/workflows/discover.py` — build one run-scoped snapshot and reuse it for the run keyword plus per-project keyword checks.
- `apps/worker/src/egp_worker/scheduler.py` — build one tenant snapshot for a scheduled batch and reuse it across that tenant’s jobs.
- `tests/phase1/test_worker_live_discovery.py` — add regression tests proving repository calls collapse while denial behavior stays fail-closed.

### Implementation Steps
1. Add failing tests that count authorization repository calls for multiple discovered projects and multiple scheduled keywords.
2. Run the focused test file and confirm the new tests fail because the current code reloads billing/profile state repeatedly.
3. Add a small helper in each worker module to construct the existing `DiscoveryAuthorizationSnapshot` once per scope.
4. Make `run_discover_workflow()` authorize every keyword against the cached snapshot rather than reloading repositories per project.
5. Make `run_scheduled_discovery()` cache snapshots by tenant for the current due-job batch.
6. Refactor names only if needed, then run focused tests, ruff, and compile checks.

### Test Coverage
- `test_run_discover_workflow_reuses_authorization_snapshot_for_discovered_projects` — one load across same-run project persistence.
- `test_run_discover_workflow_denies_per_project_keyword_outside_entitlement` — cached snapshot still rejects unentitled keyword.
- `test_run_scheduled_discovery_reuses_authorization_snapshot_per_tenant_batch` — one load across tenant keyword batch.
- existing scheduled-denial tests — expired/pending/out-of-plan jobs still skipped.

### Decision Completeness
- **Goal:** avoid rebuilding the same entitlement/profile snapshot for every discovered project or every scheduled keyword in one batch.
- **Non-goals:** no API contract changes, no schema changes, no long-lived cross-process cache, no behavior change to entitlement rules.
- **Success criteria:** multi-project discover performs one subscription read and one active-keyword read for the run; scheduled batch performs one of each per tenant; denial tests remain green.
- **Public interfaces:** unchanged.
- **Failure modes:** snapshot construction still fails closed if subscription/keyword data is invalid or absent; keyword checks continue to fail closed for unauthorized keywords. A snapshot is intentionally scoped only to the in-flight run/batch, not persisted beyond it.
- **Rollout & monitoring:** no rollout flag needed; inspect worker logs and task counts if authorization denials unexpectedly change.
- **Acceptance checks:** focused pytest, worker/package ruff, compileall.

### Dependencies
Existing shared `egp_crawler_core.discovery_authorization` helpers and worker repositories only.

### Validation
Run the focused worker discovery tests plus lint/compile gates; verify no new public wiring is required.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Run-scoped discovery snapshot use | `run_discover_workflow()` | local calls in `workflows/discover.py` | N/A |
| Scheduled tenant snapshot cache | `run_scheduled_discovery()` | local calls in `scheduler.py` | N/A |

## Plan Draft B — Shared authorization loader abstraction

### Overview
Introduce a reusable worker-side authorization loader object that owns repository creation and memoization, then inject it into both discovery workflow and scheduler code. This centralizes cache behavior and makes later executor work easier, but adds a new abstraction before there is a third call site.

### Files to Change
- `apps/worker/src/egp_worker/discovery_authorization.py` — new loader/cache abstraction.
- `apps/worker/src/egp_worker/workflows/discover.py` — consume the loader.
- `apps/worker/src/egp_worker/scheduler.py` — consume the loader.
- `tests/phase1/test_worker_live_discovery.py` — add loader usage/call-count tests.

### Implementation Steps
1. Add failing tests around the loader’s tenant memoization and workflow call counts.
2. Implement `DiscoveryAuthorizationLoader.get_snapshot(tenant_id)` using current repositories.
3. Pass or construct the loader in the two current worker paths.
4. Reuse `require_discovery_authorization()` at each keyword decision point.
5. Run focused gates and verify the abstraction is actually wired.

### Test Coverage
- loader memoization test — one repository read per tenant.
- discover workflow reuse test — no per-project repository reload.
- scheduler reuse test — no per-keyword repository reload.
- existing denial tests — fail-closed semantics preserved.

### Decision Completeness
- **Goal:** centralize repeated authorization snapshot loading and future-proof later executors.
- **Non-goals:** no cross-process cache, no API/schema change.
- **Success criteria:** same as Draft A plus reusable loader coverage.
- **Public interfaces:** new internal worker module only.
- **Failure modes:** same authorization denials; extra abstraction increases surface area and injection complexity.
- **Rollout & monitoring:** no flags; monitor as in Draft A.
- **Acceptance checks:** same as Draft A.

### Dependencies
Same as Draft A.

### Validation
Focused tests plus proof that both runtime paths call the new loader.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `DiscoveryAuthorizationLoader` | `run_discover_workflow()`, `run_scheduled_discovery()` | imported by both worker modules | N/A |

## Comparative Analysis
Draft A is the smallest safe change and directly addresses the two measured hot spots. Draft B is cleaner if several more worker executors soon need the same memoization, but today it introduces an abstraction with only two consumers and more injection decisions than PR 2 needs. Both preserve the shared entitlement evaluator and fail-closed keyword checks; Draft A better matches the PR’s tactical-cleanup intent.

## Unified Execution Plan

### Overview
Implement the narrow, explicit version from Draft A: reuse a run-scoped snapshot inside worker discovery and memoize scheduled authorization snapshots per tenant for the current keyword batch. Keep all authorization decisions delegated to the existing shared evaluator so the optimization changes cost, not policy.

### Files to Change
- `apps/worker/src/egp_worker/workflows/discover.py` — add a snapshot builder and reuse the run snapshot for initial and per-project checks.
- `apps/worker/src/egp_worker/scheduler.py` — add tenant-level batch memoization while filtering scheduled jobs.
- `tests/phase1/test_worker_live_discovery.py` — add call-count regressions and keep denial coverage explicit.

### Implementation Steps
1. **RED:** add the two call-count regression tests in `tests/phase1/test_worker_live_discovery.py`.
2. Run only those tests and confirm they fail because current code loads subscriptions/active keywords repeatedly.
3. Add `_load_discovery_authorization_snapshot(...)` in `workflows/discover.py` that returns the existing shared snapshot type.
4. In `run_discover_workflow()`, load once when `database_url` is present and pass the cached snapshot through both the top-level keyword check and `_persist_discovered_project()` keyword checks.
5. In `run_scheduled_discovery()`, memoize snapshots in a local `dict[str, DiscoveryAuthorizationSnapshot]` keyed by tenant id for the current due-job filtering pass.
6. Re-run the focused tests to green; preserve and re-run existing denial-path tests.
7. Run worker/package ruff, compileall, and the focused worker test file.
8. Verify wiring by checking both entry points still call `require_discovery_authorization()` using the reused snapshot.

### Test Coverage
- `test_run_discover_workflow_reuses_authorization_snapshot_for_discovered_projects` — one DB-backed snapshot build per run.
- `test_run_scheduled_discovery_reuses_authorization_snapshot_per_tenant_batch` — one snapshot build per tenant batch.
- `test_run_discover_workflow_denies_per_project_keyword_outside_entitlement` — cached snapshot rejects wrong keyword.
- `test_run_scheduled_discovery_skips_keywords_outside_entitlement` — scheduled filter still fails closed.

### Decision Completeness
- **Goal:** reduce repeated entitlement/profile reads in discovery authorization without changing authorization rules.
- **Non-goals:** no API changes, no migrations, no cache persistence, no attempt to merge scheduler and workflow code paths.
- **Success criteria:** repeated same-scope reads are eliminated; all existing authorization denials behave exactly as before; focused worker tests pass.
- **Public interfaces:** unchanged APIs, CLI commands, env vars, and schema.
- **Edge cases / failure modes:**
  - missing or inactive subscription → fail closed with the existing permission error;
  - keyword absent from the cached active-keyword set → fail closed;
  - scheduled tenant with multiple jobs → one snapshot reused only within that batch;
  - no database URL in injected-test mode → existing repository-injected behavior remains unchanged.
- **Rollout & monitoring:** deploy normally; no data migration. Watch worker authorization-denial counts and scheduled due/executed-job counts for regressions.
- **Acceptance checks:**
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q`
  - `./.venv/bin/ruff check apps/worker packages`
  - `./.venv/bin/python -m compileall apps/worker/src packages/crawler-core/src`

### Dependencies
Only current worker modules and shared crawler-core authorization helper.

### Validation
Run the focused worker suite, lint, compileall, then review the branch before PR submission.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `_load_discovery_authorization_snapshot()` | `run_discover_workflow()` | local call in `apps/worker/src/egp_worker/workflows/discover.py` | N/A |
| scheduled snapshot memoization | `run_scheduled_discovery()` | local call in `apps/worker/src/egp_worker/scheduler.py` | N/A |

### Cross-Language Schema Verification
No schema or migration changes are planned for this PR.


## Review (2026-05-16 06:47:41 ) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-pr2-discovery-auth-cache`
- Branch: `feat/discovery-authorization-cache`
- Scope: working tree
- Commands Run: `git status --porcelain=v1`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff`, focused `pytest`, `ruff`, `compileall`

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
- The optimization intentionally treats authorization as a run-scoped / batch-scoped snapshot. A subscription change after a run has already started is therefore observed on the next run or batch, while unentitled per-project keywords still fail closed against the cached snapshot.

### Recommended Tests / Validation
- Keep the new call-count tests plus the existing per-project keyword denial and scheduled entitlement-denial tests in the focused worker suite.
- Re-run the full focused worker file before submission.

### Rollout Notes
- No flags or schema changes. Watch worker authorization-denial counts and scheduled due/executed-job counts after rollout for unexpected drift.


## Implementation (2026-05-16 06:48:03 ) - discovery authorization cache

### Goal
Reduce repeated discovery authorization repository reads within one worker run / scheduled keyword batch without changing entitlement policy.

### What Changed
- `apps/worker/src/egp_worker/workflows/discover.py`
  - Replaced repeated repository-backed authorization loading with `_load_discovery_authorization_snapshot(...)`.
  - Reused one snapshot for the run keyword and each persisted project keyword check.
- `apps/worker/src/egp_worker/scheduler.py`
  - Added tenant-keyed memoization for the current scheduled filtering batch.
- `tests/phase1/test_worker_live_discovery.py`
  - Added repository call counters to the test fakes.
  - Added regression tests proving discover runs and scheduled batches reuse one snapshot.
- `coding-logs/2026-05-16-06-45-28 Coding Log (discovery-authorization-cache).md`
  - Added the plan and review trail for PR 2.

### TDD Evidence
- Added tests:
  - `test_run_discover_workflow_reuses_authorization_snapshot_for_discovered_projects`
  - `test_run_scheduled_discovery_reuses_authorization_snapshot_per_tenant_batch`
- RED:
  - `PYTHONPATH='apps/worker/src:packages/db/src:packages/crawler-core/src:packages/shared-types/src:packages/notification-core/src' /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q -k 'reuses_authorization_snapshot'`
  - Failed because the current code performed 3 subscription reads for one discover run and 2 reads for one scheduled tenant batch.
- GREEN:
  - `PYTHONPATH='apps/worker/src:packages/db/src:packages/crawler-core/src:packages/shared-types/src:packages/notification-core/src' /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q -k 'reuses_authorization_snapshot or denies_per_project_keyword_outside_entitlement or skips_keywords_outside_entitlement'`
  - Passed: `4 passed`.

### Tests Run
- `PYTHONPATH='apps/worker/src:packages/db/src:packages/crawler-core/src:packages/shared-types/src:packages/notification-core/src' /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q` → `44 passed`
- `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check apps/worker packages tests/phase1/test_worker_live_discovery.py` → passed
- `/Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps/worker/src packages/crawler-core/src` → passed

### Wiring Verification
- `run_discover_workflow()` now loads and reuses the snapshot at the worker workflow entry point.
- `_persist_discovered_project()` still calls `require_discovery_authorization(...)` for every project keyword.
- `run_scheduled_discovery()` still calls `require_discovery_authorization(...)` for every due job while reusing one tenant snapshot for the batch.

### Behavior Changes and Risk Notes
- User-visible authorization behavior is unchanged for missing subscriptions, over-limit configurations, and unentitled keywords: those still fail closed.
- The cache is intentionally scoped only to the in-flight run or scheduled batch; it is not persisted across jobs or processes.
- Assumption retained from the plan: an already-started run uses its start-of-run entitlement snapshot; later subscription changes are picked up on the next run/batch.

### Follow-Ups / Known Gaps
- If the product later requires mid-run revocation to interrupt an already-started discovery run, that would need an explicit policy decision and a separate refresh/invalidation mechanism rather than this tactical cache.
