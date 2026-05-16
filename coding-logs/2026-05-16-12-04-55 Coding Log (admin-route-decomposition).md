# Admin Route Decomposition

## Plan Draft A

### Overview
Split the monolithic `egp_api.routes.admin` module into a package with subdomain routers while preserving the existing `/v1/admin` public API. Auggie semantic search returned HTTP 429, so this plan is based on direct inspection of `AGENTS.md`, `apps/api/AGENTS.md`, `apps/api/src/egp_api/routes/admin.py`, `apps/api/src/egp_api/bootstrap/middleware.py`, and `tests/phase4/test_admin_api.py`.

### Files To Change
- `apps/api/src/egp_api/routes/admin.py`: replace the monolith with a package entrypoint, or move content into package modules.
- `apps/api/src/egp_api/routes/admin/__init__.py`: aggregate subdomain routers under the same `router` import used by bootstrap.
- `apps/api/src/egp_api/routes/admin/schemas.py`: shared Pydantic request/response models.
- `apps/api/src/egp_api/routes/admin/dependencies.py`: request-to-service helpers, tenant actor helpers, and storage redirect helpers.
- `apps/api/src/egp_api/routes/admin/serializers.py`: response serialization helpers.
- `apps/api/src/egp_api/routes/admin/overview.py`: `GET /v1/admin`.
- `apps/api/src/egp_api/routes/admin/audit.py`: `GET /v1/admin/audit-log`.
- `apps/api/src/egp_api/routes/admin/settings.py`: users, invites, notification preferences, and tenant settings.
- `apps/api/src/egp_api/routes/admin/storage.py`: storage settings, connect/disconnect, OAuth, folders, and test-write.
- `apps/api/src/egp_api/routes/admin/support.py`: support tenant search and support summary.
- `tests/phase4/test_admin_route_registration.py`: structural regression tests for package modules and path preservation.

### Implementation Steps
1. Add failing route decomposition tests that import the new admin submodules and assert key route paths remain registered once.
2. Run the focused test and confirm it fails because `egp_api.routes.admin` is still a single module.
3. Convert `admin.py` into a package entrypoint and move models/helpers/routes into subdomain modules.
4. Keep `egp_api.routes.admin.router` as the single public facade imported by `bootstrap/middleware.py`.
5. Run focused registration tests and representative existing admin behavior tests.
6. Run API lint/compile checks.

### Test Coverage
- `test_admin_route_package_exposes_subdomain_modules`: importable domain modules.
- `test_admin_router_preserves_public_admin_paths_once`: paths unchanged and unique.
- Existing `tests/phase4/test_admin_api.py`: behavioral endpoint coverage remains green.

### Decision Completeness
- Goal: reduce future admin-route change cost by splitting route code by subdomain.
- Non-goals: no API contract changes, no DB/schema changes, no service/repository decomposition.
- Success criteria: `egp_api.routes.admin.router` still registers all previous paths; focused admin tests pass; `admin.py` no longer contains all endpoint code.
- Public interfaces: existing `/v1/admin`, `/v1/admin/users`, `/v1/admin/settings`, `/v1/admin/storage*`, `/v1/admin/support*`, and `/v1/admin/audit-log` are unchanged.
- Edge cases/failure modes: missing subrouter registration would drop endpoints; duplicate inclusion would duplicate paths; response model imports could drift. Fail closed through tests and FastAPI import failures.
- Rollout/monitoring: refactor-only, no flags or migrations. Watch API startup and admin route smoke tests.
- Acceptance checks: focused registration test, existing phase4 admin tests, `ruff check apps/api packages`, `compileall apps/api/src`.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `admin.__init__.router` | `configure_http_pipeline()` | `apps/api/src/egp_api/bootstrap/middleware.py` imports `egp_api.routes.admin.router` | N/A |
| `overview.router` | `GET /v1/admin` | included by `admin.__init__` | N/A |
| `audit.router` | `GET /v1/admin/audit-log` | included by `admin.__init__` | N/A |
| `settings.router` | `/users`, `/settings` | included by `admin.__init__` | N/A |
| `storage.router` | `/storage*` | included by `admin.__init__` | N/A |
| `support.router` | `/support*` | included by `admin.__init__` | N/A |

## Plan Draft B

### Overview
Perform a smaller split that keeps all Pydantic models and helper functions in `admin.py`, while extracting only endpoint functions into sibling modules. The current bootstrap import would continue to target `egp_api.routes.admin.router`.

### Files To Change
- `apps/api/src/egp_api/routes/admin.py`: keep schemas/helpers plus aggregate subrouters.
- `apps/api/src/egp_api/routes/admin_*.py`: new endpoint modules using imports from `admin.py`.
- `tests/phase4/test_admin_route_registration.py`: assert route preservation.

### Implementation Steps
1. Add failing tests for importable endpoint modules.
2. Move endpoint functions into five modules.
3. Import shared schemas/helpers from the remaining `admin.py`.
4. Include subrouters into the existing public router.
5. Run focused tests.

### Test Coverage
- Same route registration tests as Draft A.
- Existing phase4 admin behavior tests.

### Decision Completeness
- Goal: lower risk by moving less code.
- Non-goals: no API changes, no service changes.
- Success criteria: endpoint code is smaller, behavior remains green.
- Public interfaces: unchanged.
- Edge cases/failure modes: circular imports are likely because modules import helpers from `admin.py` while `admin.py` imports modules.
- Rollout/monitoring: same refactor-only posture.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `admin.router` | FastAPI route registration | `bootstrap/middleware.py` | N/A |
| endpoint modules | included by `admin.router` | `admin.py` | N/A |

## Comparative Analysis

Draft A creates a clean package boundary and avoids circular imports by placing shared schemas, dependencies, and serializers in neutral modules. It moves more files but leaves a better long-term shape.

Draft B is a smaller diff, but it leaves `admin.py` as an awkward shared module and makes circular imports more likely. It also does less to make ownership boundaries obvious.

Both preserve the existing public API and rely on route-registration tests plus existing behavior tests. Draft A better matches the PR 14 goal.

## Unified Execution Plan

### Overview
Implement Draft A: convert admin routing into a package with five subdomain endpoint modules plus shared schemas, dependencies, and serializers. Preserve `egp_api.routes.admin.router` as the only public registration surface so `bootstrap/middleware.py` does not need a behavior change.

### Files To Change
- `apps/api/src/egp_api/routes/admin.py`: delete after moving to package form.
- `apps/api/src/egp_api/routes/admin/__init__.py`: aggregate subdomain routers under `APIRouter(prefix="/v1/admin", tags=["admin"])`.
- `apps/api/src/egp_api/routes/admin/schemas.py`: Pydantic models.
- `apps/api/src/egp_api/routes/admin/dependencies.py`: request helpers.
- `apps/api/src/egp_api/routes/admin/serializers.py`: serializers.
- `apps/api/src/egp_api/routes/admin/overview.py`: overview endpoint.
- `apps/api/src/egp_api/routes/admin/audit.py`: audit-log endpoint.
- `apps/api/src/egp_api/routes/admin/settings.py`: users, invites, preferences, tenant settings.
- `apps/api/src/egp_api/routes/admin/storage.py`: storage endpoints.
- `apps/api/src/egp_api/routes/admin/support.py`: support endpoints.
- `tests/phase4/test_admin_route_registration.py`: structural route tests.

### TDD Sequence
1. Add/stub `test_admin_route_package_exposes_subdomain_modules` and `test_admin_router_preserves_public_admin_paths_once`.
2. Run `./.venv/bin/python -m pytest tests/phase4/test_admin_route_registration.py -q` and confirm import/path failure.
3. Move code into package modules with no endpoint contract changes.
4. Run the focused registration test to green.
5. Run representative admin behavior tests and API lint/compile gates.

### Functions
- `admin.__init__.router`: aggregate subrouters and preserve the existing external import.
- `overview.get_admin_snapshot()`: same tenant snapshot behavior.
- `audit.get_admin_audit_log()`: same paginated audit behavior.
- `settings.*`: same user/settings mutation behavior.
- `storage.*`: same storage settings and OAuth behavior.
- `support.*`: same support lookup and summary behavior.

### Test Coverage
- `test_admin_route_package_exposes_subdomain_modules`: verifies decomposition exists.
- `test_admin_router_preserves_public_admin_paths_once`: verifies no dropped/duplicated public paths.
- Existing admin tests: verify route behavior, auth, tenant scoping, storage OAuth, audit, and support.

### Decision Completeness
- Goal: decompose admin route module by subdomain.
- Non-goals: no endpoint renames, no response changes, no schema/migration changes, no service/repository refactor.
- Success criteria: all existing admin public paths still present exactly once; existing admin tests pass; bootstrap import remains unchanged.
- Public interfaces: unchanged `/v1/admin*` HTTP API.
- Edge cases/failure modes: router omitted, duplicate subrouter include, circular imports, auth/tenant helper drift. Tests catch route omissions/duplicates; imports catch circulars.
- Rollout & monitoring: refactor-only; rollback by reverting PR; monitor API startup/import and existing admin smoke tests.
- Acceptance checks: registration pytest, representative `test_admin_api.py`, `compileall apps/api/src`, `ruff check apps/api packages`.

### Dependencies
No new runtime or test dependencies.

### Validation
Run focused pytest first, then the existing phase4 admin API file, then compile and ruff.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `egp_api.routes.admin.router` | `configure_http_pipeline()` | imported in `apps/api/src/egp_api/bootstrap/middleware.py` | N/A |
| `overview.router` | `GET /v1/admin` | `admin/__init__.py:router.include_router()` | N/A |
| `audit.router` | `GET /v1/admin/audit-log` | `admin/__init__.py:router.include_router()` | N/A |
| `settings.router` | `/users`, `/settings` | `admin/__init__.py:router.include_router()` | N/A |
| `storage.router` | `/storage*` | `admin/__init__.py:router.include_router()` | N/A |
| `support.router` | `/support*` | `admin/__init__.py:router.include_router()` | N/A |

### Cross-Language Schema Verification
No DB migration or schema change is planned.

## Implementation Summary (2026-05-16 12:10:56 +07)

### Goal
Decompose the monolithic admin route module into subdomain modules while preserving the existing `/v1/admin*` API contract and bootstrap import.

### What Changed
- `apps/api/src/egp_api/routes/admin.py`: replaced the 1050-line monolith with a package.
- `apps/api/src/egp_api/routes/admin/__init__.py`: added the public `router` facade and included all subdomain routers under `/v1/admin`.
- `apps/api/src/egp_api/routes/admin/schemas.py`: moved admin request/response Pydantic models.
- `apps/api/src/egp_api/routes/admin/dependencies.py`: moved request-to-service, actor, HTML accept, and storage redirect helpers.
- `apps/api/src/egp_api/routes/admin/serializers.py`: moved response serialization helpers.
- `apps/api/src/egp_api/routes/admin/overview.py`: moved `GET /v1/admin`.
- `apps/api/src/egp_api/routes/admin/audit.py`: moved `GET /v1/admin/audit-log`.
- `apps/api/src/egp_api/routes/admin/settings.py`: moved user, invite, preferences, and tenant settings routes.
- `apps/api/src/egp_api/routes/admin/storage.py`: moved storage settings, OAuth, folders, connect, disconnect, and test-write routes.
- `apps/api/src/egp_api/routes/admin/support.py`: moved support lookup and summary routes.
- `tests/phase4/test_admin_route_registration.py`: added structural tests for importable subdomain modules and preserved route method/path keys.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase4/test_admin_route_registration.py -q`
  - Failed because `egp_api.routes.admin` was not yet a package.
  - The first draft also caught that path-only uniqueness was too strict for valid multi-method paths.
- GREEN: `./.venv/bin/python -m pytest tests/phase4/test_admin_route_registration.py -q`
  - `2 passed in 0.25s`.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase4/test_admin_route_registration.py -q` - passed.
- `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q` - `43 passed in 3.72s`.
- `./.venv/bin/python -m compileall apps/api/src` - passed.
- `./.venv/bin/ruff check apps/api packages` - passed.

### Wiring Verification Evidence
- `apps/api/src/egp_api/bootstrap/middleware.py` still imports `router` from `egp_api.routes.admin`.
- `apps/api/src/egp_api/routes/admin/__init__.py` includes `overview`, `audit`, `support`, `settings`, and `storage` routers with prefix `/v1/admin`.
- `tests/phase4/test_admin_route_registration.py` asserts every public admin method/path key remains present exactly once.

### Behavior Changes And Risk Notes
No intended behavior changes. The main risk was dropping or duplicating routes during router aggregation; the route-registration test plus existing admin behavior tests cover that.

### Follow-Ups / Known Gaps
No schema, migration, or service-layer changes were included in this PR.

## Review (2026-05-16 12:11:38 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at `85028c27`
- Commands Run:
  - `mcp__auggie_mcp__codebase_retrieval(...)` - failed with HTTP 429
  - `git status --porcelain=v1`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - `find apps/api/src/egp_api/routes/admin -maxdepth 1 -type f -print | sort`
  - `rg -n "@router\\.|require_admin_role|require_support_role|resolve_request_tenant_id|response_model|status_code" apps/api/src/egp_api/routes/admin -g '*.py'`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_route_registration.py -q`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/python -m compileall apps/api/src`
  - `./.venv/bin/ruff check apps/api packages`

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
- Assumes the intended PR 14 scope is route-module decomposition only, not service or repository decomposition.
- Auggie semantic review was unavailable due to HTTP 429; review used direct file inspection and focused tests.

### Recommended Tests / Validation
- Already run: route-registration pytest, full phase4 admin API pytest, compileall, and ruff.
- Remote CI should rerun the same API test/lint gates after submission.

### Rollout Notes
- Refactor-only change. No flags, migrations, or runtime configuration changes.
- Bootstrap still imports `egp_api.routes.admin.router`, so API startup wiring remains unchanged.

## Submission / Landing Status (2026-05-16 12:14:36 +07)

### Branch And PR
- Created Graphite branch: `refactor/admin-route-decomposition`.
- Commit: Graphite branch head for `refactor(api): split admin routes by subdomain`.
- Submitted PR: https://github.com/SubhajL/egp/pull/86.
- Base: `main`; head: `refactor/admin-route-decomposition`.

### Remote Checks
- `gh pr checks 86` reported all CI and `claude-review` jobs failed immediately.
- The check annotation from GitHub was: `The job was not started because your account is locked due to a billing issue.`
- Reran failed CI jobs once with `gh run rerun 25953584808 --failed`; the same billing-lock failure recurred.

### Landing Blocker
The PR is mergeable by Git but `mergeStateStatus` is `BLOCKED` because required checks cannot start while the GitHub Actions account is billing-locked. I did not bypass the failed required checks or merge locally into `main`.

### Auto-Merge
- Enabled GitHub auto-merge with `gh pr merge 86 --merge --auto --delete-branch=false`.
- Current PR state remains `OPEN` and `BLOCKED`; auto-merge can complete only after required checks are rerun and pass.
