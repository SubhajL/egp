# create_app Bootstrap Builders — PR 3 Plan

## Plan Draft A — Extract four focused builder modules

### Overview
Split `create_app()` by responsibility into repositories, services, middleware, and background builders while keeping `create_app()` as the only public factory. Freeze the current app-state contract first, then move existing wiring with minimal logic changes.

### Files to Change
- `apps/api/src/egp_api/main.py` — keep the façade, reduce orchestration volume, delegate to builders.
- `apps/api/src/egp_api/bootstrap/repositories.py` — construct shared engine, stores, and repositories.
- `apps/api/src/egp_api/bootstrap/services.py` — construct services and bind app-state service objects.
- `apps/api/src/egp_api/bootstrap/middleware.py` — register validation, CORS, auth middleware, and health/router wiring if appropriate.
- `apps/api/src/egp_api/bootstrap/background.py` — build lifespan and background dispatch state.
- `tests/phase1/test_high_risk_architecture.py` or a focused new API bootstrap test file — freeze app-state wiring and middleware/background flags.

### Implementation Steps
1. Add RED tests that assert the representative app-state contract and startup flags exist after `create_app()`.
2. Run the focused tests and confirm failure on the newly expected explicit contract assertions.
3. Introduce internal bootstrap dataclasses to carry repository/service dependencies between builder layers.
4. Extract repository/storage construction first.
5. Extract service/app-state binding second.
6. Extract middleware registration and lifespan/background setup last.
7. Leave `create_app()` as the public façade and keep all route contracts unchanged.
8. Run focused API tests, ruff, and compileall.

### Test Coverage
- `test_create_app_exposes_expected_bootstrap_state` — representative app.state wiring remains present.
- `test_create_app_preserves_background_processor_flags` — sqlite defaults stay disabled for embedded processors.
- existing engine-sharing and auth/payment tests — startup behavior unchanged.

### Decision Completeness
- **Goal:** shrink `main.py` and make startup wiring legible without changing behavior.
- **Non-goals:** no runtime-mode redesign, no route/service behavior change, no repository API change.
- **Success criteria:** `main.py` is materially smaller; builders own cohesive responsibilities; existing startup tests remain green.
- **Public interfaces:** unchanged `create_app()` signature, routes, env vars, and schema.
- **Failure modes:** missing app.state bindings, changed middleware order, or altered lifespan startup; tests should fail closed on representative drift.
- **Rollout & monitoring:** refactor-only; deploy normally and watch startup logs / health checks.
- **Acceptance checks:** focused bootstrap tests, API ruff, compileall, selected API regression tests.

### Dependencies
Current API main module, repository factories, and services only.

### Validation
Run focused startup tests and a representative route regression subset after extraction.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| repository builder | `create_app()` | import/use in `egp_api.main` | existing tables only |
| service builder | `create_app()` | import/use in `egp_api.main` | existing tables only |
| middleware builder | FastAPI request pipeline | call from `create_app()` | N/A |
| background builder | FastAPI lifespan | `lifespan=` in `create_app()` | N/A |

## Plan Draft B — Extract helper functions but keep one module

### Overview
Keep all code in `main.py`, but split it into `_build_repositories()`, `_build_services()`, `_register_middleware()`, and `_build_lifespan()` functions. This minimizes import churn and is the lowest-risk refactor, but it leaves the entrypoint file large and does less to establish future module boundaries.

### Files to Change
- `apps/api/src/egp_api/main.py` — internal helper extraction only.
- targeted tests — same freeze tests as Draft A.

### Implementation Steps
1. Add RED startup-contract tests.
2. Extract helpers inside `main.py` in the order repositories → services → middleware → lifespan.
3. Re-run regression suite.

### Test Coverage
Same as Draft A.

### Decision Completeness
- **Goal:** improve readability with minimal file movement.
- **Non-goals:** no package reorganization.
- **Success criteria:** helper functions exist and tests stay green.
- **Public interfaces:** unchanged.
- **Failure modes:** lower import risk, but weaker decomposition payoff.
- **Rollout & monitoring:** same as Draft A.
- **Acceptance checks:** same as Draft A.

### Dependencies
Same as Draft A.

### Validation
Same as Draft A.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| helper functions | `create_app()` | same module | existing tables only |

## Comparative Analysis
Draft B is safer in the smallest possible sense, but PR 3 exists specifically to make future runtime-separation work easier. Keeping all helper functions inside the already-large `main.py` buys less than the planned PR should. Draft A is the better fit if it remains conservative: internal bootstrap modules, no public API changes, no service redesign.

## Unified Execution Plan

### Overview
Use the modular extraction from Draft A, but keep the first PR intentionally conservative: repositories, services, middleware, and background builders move out; `create_app()` remains the only public entry point and continues to decide the sequence. The job is to change ownership of wiring code, not startup behavior.

### Files to Change
- `apps/api/src/egp_api/main.py`
- `apps/api/src/egp_api/bootstrap/__init__.py`
- `apps/api/src/egp_api/bootstrap/repositories.py`
- `apps/api/src/egp_api/bootstrap/services.py`
- `apps/api/src/egp_api/bootstrap/middleware.py`
- `apps/api/src/egp_api/bootstrap/background.py`
- `tests/phase1/test_high_risk_architecture.py`

### Implementation Steps
1. **RED:** add a representative state-contract test and a background-flag test in `tests/phase1/test_high_risk_architecture.py`.
2. Run the focused tests and confirm the new tests fail before the contract helper/shape exists.
3. Add `bootstrap/repositories.py` with a typed bundle carrying resolved config plus repositories/stores.
4. Add `bootstrap/services.py` with service construction and app-state assignment for current service/repository objects.
5. Add `bootstrap/background.py` with the lifespan factory and dispatch-processor setup.
6. Add `bootstrap/middleware.py` with validation/CORS/auth middleware registration and health/router registration helpers.
7. Rewire `create_app()` to orchestrate those builders in the same order as today.
8. Run focused bootstrap tests, representative API regressions, ruff, and compileall.
9. Verify every existing `app.state.*` contract used by routes/tests is still bound from the new builder path.

### Test Coverage
- `test_create_app_exposes_expected_bootstrap_state` — representative repos/services/auth/session bindings exist.
- `test_create_app_preserves_background_processor_flags` — sqlite startup keeps background processors disabled.
- existing `test_create_app_shares_one_engine_across_repositories` — shared engine preserved.
- existing payment/auth/document route tests — façade behavior unchanged.

### Decision Completeness
- **Goal:** decompose startup wiring so future background/runtime work has clear seams.
- **Non-goals:** no behavior change, no config redesign, no background extraction yet, no route split.
- **Success criteria:** `create_app()` is materially shorter; new bootstrap modules each have one dominant responsibility; focused and representative API tests pass unchanged.
- **Public interfaces:** unchanged FastAPI factory signature, routes, middleware-visible behavior, env vars, and migrations.
- **Edge cases / failure modes:**
  - app.state omission → representative state test fails;
  - middleware order/CORS drift → auth/CORS tests fail;
  - sqlite background defaults change → background flag test fails;
  - payment callback secret / DATABASE_URL requirements regress → existing tests fail.
- **Rollout & monitoring:** refactor-only. Use normal deploy; watch startup failures, `/health`, and auth/payment smoke paths.
- **Acceptance checks:**
  - `/Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py -q`
  - selected API regression tests covering auth, payments, documents, rules
  - `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check apps/api packages tests/phase1/test_high_risk_architecture.py`
  - `/Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps/api/src`

### Dependencies
PR 1 is already landed; no other PR dependency is required.

### Validation
Run focused startup tests first, then representative API route suites after extraction.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `bootstrap.repositories` | `create_app()` | imported and called by `egp_api.main` | existing repo tables only |
| `bootstrap.services` | `create_app()` | imported and called by `egp_api.main` | existing repo tables only |
| `bootstrap.middleware` | FastAPI request pipeline | called by `create_app()` | N/A |
| `bootstrap.background` | FastAPI lifespan | lifespan factory passed to `FastAPI(...)` | N/A |

### Cross-Language Schema Verification
No schema or migration changes are planned for this PR.


## Review (2026-05-16 06:58:51 ) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-pr3-bootstrap-builders`
- Branch: `refactor/create-app-bootstrap-builders`
- Scope: working tree
- Commands Run: `git status --porcelain=v1`, targeted `git diff`, focused `pytest`, representative API `pytest`, `ruff`, `compileall`

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
- This PR intentionally keeps the public helpers imported by tests from `egp_api.main` stable where needed (`_logger`, discovery flag helpers, discover spawner helpers) while moving only bootstrap ownership.
- The new bootstrap modules are internal decomposition seams; they are not yet a public extension point.

### Recommended Tests / Validation
- Keep the representative startup-state tests plus the existing auth/payment/document regressions in the pre-merge check set.
- Re-run the focused startup suite after any follow-up bootstrap changes.

### Rollout Notes
- Refactor-only; no flags, migrations, or public contract changes. Watch startup logs and `/health` after deploy.


## Implementation (2026-05-16 06:59:15 ) - create_app bootstrap builders

### Goal
Split the API startup monolith into focused bootstrap builders while preserving `create_app()` as the only public façade and keeping startup behavior unchanged.

### What Changed
- `apps/api/src/egp_api/bootstrap/repositories.py`
  - Added `RepositoryBundle` and `build_repository_bundle(...)` for config resolution, shared-engine creation, storage wiring, and repository construction.
- `apps/api/src/egp_api/bootstrap/services.py`
  - Added `configure_services(...)` for service construction and app-state binding.
- `apps/api/src/egp_api/bootstrap/background.py`
  - Moved background-loop helpers and lifespan creation into a dedicated builder module.
- `apps/api/src/egp_api/bootstrap/middleware.py`
  - Moved validation handling, CORS/auth middleware, health route, and router registration into one request-pipeline module.
- `apps/api/src/egp_api/main.py`
  - Reduced `create_app()` to orchestration only and preserved compatibility exports for the discovery flag helpers used by tests.
- `tests/phase1/test_high_risk_architecture.py`
  - Added representative startup-state and sqlite background-flag coverage.

### TDD Evidence
- Added tests:
  - `test_create_app_exposes_expected_bootstrap_state`
  - `test_create_app_preserves_background_processor_flags_for_sqlite`
- RED:
  - Not applicable: this PR is a pure behavior-preserving refactor, and the new tests intentionally froze existing behavior before code movement. Their initial run passed because they capture the pre-existing contract rather than a new feature.
- GREEN:
  - `PYTHONPATH='apps/api/src:packages/db/src:packages/crawler-core/src:packages/shared-types/src:packages/document-classifier/src:packages/notification-core/src' /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py -q`
  - Passed: `9 passed`.

### Tests Run
- `PYTHONPATH='apps/api/src:packages/db/src:packages/crawler-core/src:packages/shared-types/src:packages/document-classifier/src:packages/notification-core/src' /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py -q` → `9 passed`
- `PYTHONPATH='apps/api/src:packages/db/src:packages/crawler-core/src:packages/shared-types/src:packages/document-classifier/src:packages/notification-core/src' /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase3/test_payment_links.py tests/phase1/test_documents_api.py -q` → `59 passed`
- `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check apps/api packages tests/phase1/test_high_risk_architecture.py` → passed
- `/Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps/api/src` → passed

### Wiring Verification
- `create_app()` now calls `build_repository_bundle(...)`, `configure_services(...)`, `build_lifespan(...)`, and `configure_http_pipeline(...)` in order.
- Route modules still resolve the same `app.state.*` services; representative bindings are covered by the new startup contract test.
- FastAPI lifespan still owns webhook/discovery loop startup and teardown through `bootstrap.background.build_lifespan(...)`.

### Behavior Changes and Risk Notes
- No intended user-visible behavior changes.
- The decomposition creates cleaner seams for later PRs 5–8, especially external background execution work.
- Public helper compatibility was preserved for the tests that intentionally import `_logger` and discovery flag helpers from `egp_api.main`.

### Follow-Ups / Known Gaps
- The modules currently use broad internal bundle fields rather than narrowly typed repository protocols; that is acceptable for this refactor and can be tightened later if the bootstrap layer becomes more independently testable.
