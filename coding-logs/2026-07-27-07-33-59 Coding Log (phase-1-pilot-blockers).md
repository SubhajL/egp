# Coding Log: phase-1-pilot-blockers

Started: 2026-07-27 07:33:59 +0700

## Source and current evidence

- Objective: plan and implement Phase 1 from the soft-launch architecture hardening plan,
  delivering U1 through U4 as independently merged PRs and landing the final merged tree on local
  `main`.
- Source specification: the protected, user-owned, untracked primary-checkout file
  `coding-logs/2026-07-27-07-14-32 Coding Log (soft-launch-architecture-hardening).md`.
- Source SHA-256:
  `938015e052ea685820ff343d329013132f1759f6f9eba1173489c57aaea3b35d`.
- Base SHA: `4fe12f85d572d1f3f3f60be35fa793dfe1fbaa68`, equal to freshly fetched
  `origin/main` when planning began.
- Protected primary-checkout changes remain outside this isolated worktree:
  the prior Coding Log modification, the source specification, and `docs/TOR KEYWORDS.md`.
- Auggie semantic search was skipped because its available interface cannot enforce the required
  real two-second deadline. Planning uses direct inspection and exact-string searches of the
  source plan, root and nearest `AGENTS.md`, `CLAUDE.md`, API bootstrap/auth/routes/config,
  repository factories, migration runner, Compose/Docker wiring, environment/runbook contracts,
  and focused tests.
- External prerequisite E0 remains red. CI run `30019936870`, attempt 2, created all six required
  jobs with zero steps. Check-run annotation:
  `The job was not started because your account is locked due to a billing issue.`
- The explicitly requested admin-merge lifecycle may land code after complete local gates, but
  this is not a substitute for E0. Gate S1 and every pilot-readiness claim remain blocked until
  real required jobs execute and pass.

# Plan Draft A - four narrow sequential PRs

## 1. Overview

Land U1 through U4 one at a time from a refreshed `origin/main`. Each PR isolates one confirmed
pilot blocker, uses defect-sensitive RED tests, verifies runtime wiring, receives QCHECK and formal
`g-check`, and is merged and locally landed before the next branch is created.

## 2. Files to change

### U1 - internal worker auth boundary

- `apps/api/src/egp_api/bootstrap/middleware.py`: classify the
  `/internal/worker/` path prefix as one JWT-bypass route class.
- `apps/api/src/egp_api/routes/project_ingest.py`: attach the existing worker-token checker as a
  FastAPI router dependency and remove handler-local duplicate calls.
- `apps/api/src/egp_api/routes/crawler_runtime.py`: split the internal heartbeat router from the
  operator read router; attach the worker-token dependency only to the internal router.
- `apps/api/src/egp_api/bootstrap/middleware.py`: register both crawler-runtime routers.
- `tests/phase1/test_projects_and_runs_api.py` and
  `tests/phase2/test_crawler_runtime.py`: add an auth-on matrix for every internal route.

### U2 - migration-only API bootstrap

- `apps/api/src/egp_api/main.py`: expose an explicit test-only schema-bootstrap injection whose
  default is false.
- `apps/api/src/egp_api/bootstrap/repositories.py`: pass `bootstrap_schema=False` explicitly in
  runtime bootstrap and forward an explicit test opt-in.
- The thirteen repository factory modules currently defaulting
  `bootstrap_schema=True`: change their defaults to false.
- `packages/db/src/egp_db/repositories/document_repo.py`: remove implicit SQLite DDL from the
  factory and require explicit opt-in.
- SQLite API test call sites: opt in explicitly with `bootstrap_schema=True`.
- `tests/phase1/test_high_risk_architecture.py`: prove default app creation emits zero DDL and
  explicit test bootstrap remains available.
- `tests/phase1/test_migration_runner.py`: prove a fully migrated PostgreSQL database supports app
  construction without repository DDL.

### U3 - readiness and explicit runtime topology

- New `apps/api/src/egp_api/services/readiness_service.py`: bounded database connectivity and exact
  migration-ledger checks against checked-in SQL filenames.
- `apps/api/src/egp_api/bootstrap/services.py`: construct and register the readiness service.
- `apps/api/src/egp_api/bootstrap/middleware.py`: add `/live` and `/ready`; retain `/health` as a
  one-release liveness alias and bypass user auth for all three.
- `apps/api/src/egp_api/config.py`: require an explicit background-runtime mode for PostgreSQL;
  retain the embedded default only for SQLite test/dev databases.
- `apps/api/src/egp_api/main.py`: resolve topology after database configuration and reject an
  ambiguous PostgreSQL startup.
- `docker-compose.yml`, `docker-compose-localdev.yml`, and `apps/api/Dockerfile`: probe `/ready`.
- `deploy/.env.production.example`, `scripts/check_launch_gates.sh`, and affected runbooks:
  document and validate the readiness/topology contract.
- Focused API/config/Compose/launch-gate tests: DB-down, missing migration, current migration,
  explicit topology, and compatibility health behavior.

### U4 - bearer authorization claims

- `apps/api/src/egp_api/auth.py`: accept tenant and role only from direct signed claims; remove
  `app_metadata` and `user_metadata` authorization fallbacks.
- `apps/api/src/egp_api/config.py`: remove the `SUPABASE_JWT_SECRET` fallback.
- `apps/api/src/egp_api/bootstrap/repositories.py`: require an explicit EGP JWT secret whenever
  authentication is enabled, while permitting no JWT secret when auth is explicitly disabled.
- `deploy/.env.production.example` and `docs/SECRET_ROTATION.md`: make the no-fallback contract
  explicit.
- `tests/phase4/test_auth_api.py` and `tests/phase1/test_high_risk_architecture.py`: deny metadata
  tenant/role elevation, require explicit secret configuration, and retain direct-claim/session
  compatibility.

## 3. Implementation steps

For every PR, use this TDD order:

1. add the named tests or minimal test scaffold;
2. run them and record RED for the intended defect;
3. implement the smallest complete runtime-wired change;
4. refactor minimally only after GREEN;
5. run focused formatter/lint/typecheck/tests, then affected and full gates;
6. verify all entry points, registrations, environment contracts, and schema names;
7. run tests three consecutive times, QCHECK, and formal `g-check`;
8. commit, push, open the PR, inspect required checks, admin-merge with the CI infrastructure
   limitation stated exactly, land local `main`, and rerun post-merge focused gates.

Key functions/components:

- `_register_auth_middleware()`: bypass JWT for the complete internal-worker route class.
- `require_internal_worker_token()`: remain the single constant-time token dependency.
- `build_repository_bundle()`: make every schema mutation an explicit caller decision.
- `create_*_repository()`: default to no DDL in every runtime factory.
- `ReadinessService.check()`: return safe component status without leaking connection details.
- `get_background_runtime_mode()`: fail closed for unspecified PostgreSQL topology.
- `_extract_claim_tenant_id()` and `extract_request_role()`: trust direct signed claims only.
- `get_jwt_secret()`: read only `EGP_JWT_SECRET` and fail startup when required but absent.

## 4. Test coverage

### U1

- `test_internal_worker_routes_apply_worker_token_matrix`: all routes share one auth contract.
- `test_status_update_valid_worker_token_reaches_handler`: confirmed broken callback becomes
  reachable.
- `test_operator_runtime_route_still_requires_user_auth`: public operator auth remains intact.

### U2

- `test_create_app_default_does_not_create_sqlite_schema`: runtime construction emits zero DDL.
- `test_create_app_explicit_test_bootstrap_creates_schema`: tests retain deliberate local setup.
- `test_migrated_postgres_starts_without_repository_bootstrap`: migration-owned schema remains
  usable.
- `test_repository_factories_default_bootstrap_false`: future factories cannot regress defaults.

### U3

- `test_live_succeeds_without_database`: liveness reports process availability only.
- `test_ready_fails_when_database_unreachable`: dependency failure closes readiness.
- `test_ready_fails_when_migration_is_missing`: schema drift closes readiness.
- `test_ready_succeeds_for_exact_migration_ledger`: current migrated database becomes ready.
- `test_postgres_requires_explicit_background_runtime_mode`: ambiguous topology fails startup.
- `test_sqlite_keeps_embedded_test_default`: isolated tests retain simple topology.
- `test_compose_and_docker_probe_ready`: traffic waits for database and schema.

### U4

- `test_user_metadata_cannot_supply_tenant`: user-controlled tenant elevation is denied.
- `test_user_metadata_cannot_supply_admin_role`: user-controlled role elevation is denied.
- `test_app_metadata_cannot_supply_authorization_claims`: indirect metadata is never trusted.
- `test_direct_bearer_claims_remain_supported`: signed direct claim contract stays compatible.
- `test_cookie_session_login_remains_supported`: database-backed session auth is unchanged.
- `test_auth_enabled_requires_egp_jwt_secret`: missing explicit secret fails closed.
- `test_supabase_jwt_secret_is_not_a_fallback`: legacy fallback cannot silently activate.

## 5. Decision completeness

- Goal: remove the four confirmed code-level blockers to a future supervised single-tenant pilot.
- Non-goals: Gate S1 runtime execution, CI billing remediation, U5+ reproducibility/images,
  crawler-agent cutover, RLS, product features, or microservices.
- Success: U1-U4 are individually merged; their acceptance tests and full affected gates pass on
  each exact merged SHA; final local `main == origin/main`.
- Public surfaces:
  - U1 changes no URLs or header names; `X-EGP-Worker-Token` remains required.
  - U2 changes Python factory defaults only; no migration is added.
  - U3 adds `GET /live` and `GET /ready`, retains `GET /health` temporarily, and makes
    `EGP_BACKGROUND_RUNTIME_MODE=embedded|external` explicit for PostgreSQL.
  - U4 removes `SUPABASE_JWT_SECRET` compatibility and metadata authorization claims;
    `EGP_JWT_SECRET` plus direct `tenant_id`/`role` claims are authoritative.
- Failure policy: worker auth, schema ownership, readiness, topology, and authorization all fail
  closed; `/live` remains open because it proves process liveness only.
- Rollout/backout: each PR is independently revertible. `/health` remains through one release.
  U3 Compose already declares external topology. U4 requires verifying `EGP_JWT_SECRET` before
  deploying. No production deployment is part of this code-only Phase 1 request.
- Monitoring: readiness failures name only safe component codes; auth failures retain 401/403/503
  semantics; no secrets or database URLs are logged.
- Acceptance: code merge does not open Gate S1 while E0 is red.

## 6. Dependencies

- Current Python/Node environments and local PostgreSQL tooling.
- GitHub billing restoration remains external and is not falsified by admin merge.
- U2 must land before U3 so readiness tests exercise migration-only startup.
- U3 must land before U4 only to keep each PR based on exact landed `main`; U4 is otherwise
  behaviorally independent.

## 7. Validation

Focused gates are recorded per PR. The final merged-tree gate is:

```text
./.venv/bin/ruff check apps packages tests scripts
./.venv/bin/python -m compileall apps packages
./.venv/bin/python -m pytest tests apps packages -q
(cd apps/web && npm run check:api-types)
(cd apps/web && npm run test:unit)
(cd apps/web && npm run typecheck && npm run lint && npm run build)
docker compose config
./.venv/bin/python scripts/check_main_sync.py --json
```

Expected: all local gates green, no pending product diff, and exact local/remote SHA equality.
Remote required checks remain separately reported until they execute real steps.

## 8. Wiring verification

| Component | Entry point | Registration/caller | Schema/table |
|---|---|---|---|
| Worker auth dependency | `/internal/worker/*` | internal FastAPI routers plus JWT bypass class | N/A |
| Migration-only bundle | `create_app()` | `build_repository_bundle()` explicit false | all mapped tables |
| Explicit test bootstrap | test `create_app()` calls | explicit `bootstrap_schema=True` | SQLite test schema |
| Liveness | `GET /live`, `GET /health` | API HTTP pipeline | N/A |
| Readiness | `GET /ready` | `ReadinessService` on app state | `schema_migrations` |
| Runtime topology | API startup | config to services/background lifespan | N/A |
| Direct bearer tenant/role | auth middleware | `authenticate_request()` | session path unchanged |
| Explicit JWT secret | API startup | config to repository/service bundle | N/A |

## 9. Cross-language schema verification

- U1, U2, and U4 add no migration or TypeScript DB access.
- U3 reads the existing `schema_migrations.version` ledger written by
  `egp_db.migration_runner.apply_migrations()`.
- Checked-in SQL filenames, not numeric-prefix guesses, are compared to ledger versions because
  historical duplicate prefixes are intentional.
- Route additions require OpenAPI/client drift checks; no handwritten TypeScript schema is added.

## 10. Decision-complete checklist

- [x] Goal, non-goals, success, interfaces, and failure policy are locked.
- [x] Every behavior change has a defect-sensitive test.
- [x] U1-U4 are independent and dependency ordered.
- [x] Runtime entry points and registrations are identified.
- [x] Schema ownership and migration-ledger names are exact.
- [x] Rollback and CI-infrastructure limitations are explicit.
- [x] No implementation architecture decision remains open.

# Plan Draft B - one consolidated Phase 1 PR

## 1. Overview

Implement U1-U4 on one branch, allowing cross-cutting app-fixture and readiness work to settle
together before a single review and merge.

## 2. Files to change

The same files as Draft A, but all auth, factory, readiness, topology, Compose, documentation, and
test changes land in one PR.

## 3. Implementation steps

Use four internal RED/GREEN cycles in U1-U4 order, then one combined wiring review, full gate,
QCHECK, `g-check`, commit, PR, merge, and local landing.

## 4. Test coverage

Use every named test from Draft A plus one combined startup contract covering migrated
PostgreSQL, explicit external topology, readiness success, direct bearer claims, and the internal
worker callback.

## 5. Decision completeness

Goal, non-goals, interfaces, failure policy, rollout, and acceptance are identical to Draft A.
The only decision difference is delivery granularity: one revert unit instead of four.

## 6. Dependencies

All U1-U4 implementation must be complete before review. E0 remains independently blocked.

## 7. Validation

Run the same final gate, but no per-defect merged-SHA evidence exists until the single PR lands.

## 8. Wiring verification

Use the same table as Draft A and trace one combined path from startup through readiness and auth.

## 9. Cross-language schema verification

Identical to Draft A: no migration; U3 reads exact `schema_migrations.version` values.

## 10. Decision-complete checklist

- [x] Interfaces and tests are locked.
- [x] Combined rollback impact is understood.
- [x] Review size and diagnosis costs are acknowledged.

# Comparative analysis

- Draft A matches the source plan, keeps regressions localized, makes every accepted merged SHA
  independently auditable, and minimizes rollback blast radius.
- Draft B reduces PR overhead and may simplify the U2/U3 test-fixture transition, but it combines
  worker authentication, DDL ownership, readiness, topology, and bearer authorization into a
  review surface too broad for the repository's currently unavailable remote CI.
- Choose Draft A. The extra lifecycle cost is justified by security-sensitive changes and the
  requirement to land one PR fully before starting the next.

# Unified Execution Plan

## 1. Overview

Execute Draft A exactly: U1, U2, U3, then U4 as four refreshed, independently landable PRs.
Preserve the source log and dirty primary checkout; carry this implementation log forward and
append RED/GREEN, wiring, review, CI, merge, and post-merge evidence for every PR.

## 2. Files to change

Use Draft A's per-PR file list. Do not opportunistically include U5+ work or protected primary
checkout files.

## 3. Implementation steps

1. U1: path-class middleware plus router dependency and complete internal route matrix.
2. Land U1; refresh exact `main`.
3. U2: factory defaults false, explicit API test bootstrap, zero-DDL and migrated-startup proof.
4. Land U2; refresh exact `main`.
5. U3: safe liveness/readiness, exact ledger check, explicit PostgreSQL topology, Compose/runbook
   wiring.
6. Land U3; refresh exact `main`.
7. U4: direct authorization claims, explicit JWT secret, metadata-elevation and session tests.
8. Land U4; refresh exact `main`.
9. Run the requirement-by-requirement completion audit on the final merged SHA.

Every numbered implementation step uses the full Draft A TDD/lifecycle sequence.

## 4. Test coverage

All Draft A named tests are mandatory. A test is accepted only when its RED is recorded before the
corresponding implementation and the resulting focused suite passes three consecutive runs.

## 5. Decision completeness

- Phase 1 completion means U1-U4 code is merged and locally landed, not that S1 is open.
- E0 remains a named blocker to S1 until six required GitHub jobs execute nonzero steps and pass.
- Admin merge is authorized for delivery under the current infrastructure failure, but every PR
  body and Coding Log must state that remote CI did not pass.
- No deployment or live pilot activation occurs in this phase.

## 6. Dependencies

Draft A dependencies apply. Each next branch must start from the exact prior merged
`origin/main`.

## 7. Validation

Use the focused, three-run reliability, full affected, and post-merge gates from Draft A. Inspect
GitHub check annotations rather than claiming zero-step failures are source failures or passes.

## 8. Wiring verification

Draft A's wiring table is the acceptance table. Every row requires an exact production call site
and a defect-sensitive test before its PR may merge.

## 9. Cross-language schema verification

Draft A's schema verification is authoritative. No new migration is expected; a surprise migration
or hand-written web contract is a review blocker.

## 10. Final decision-complete checklist

- [x] Four-PR sequence selected and branch names fixed by the source plan.
- [x] Exact test names and failure policies recorded.
- [x] Protected dirty files excluded through isolated-worktree delivery.
- [x] E0 and S1 truth remain separate from code landing.
- [x] Final acceptance requires local `main == origin/main` plus exact merged-tree gates.

## Implementation (2026-07-27 07:40:14 +0700) - U1 internal worker auth boundary

### Goal

Make every current `/internal/worker/*` endpoint bypass user JWT authentication as one route class
and enforce the existing constant-time worker token through FastAPI router dependencies.

### What changed

- `apps/api/src/egp_api/bootstrap/middleware.py`: replaced the incomplete path allow-list with the
  internal-worker prefix class and registered the split crawler-runtime internal router.
- `apps/api/src/egp_api/routes/project_ingest.py`: attached
  `require_internal_worker_token()` as a router dependency and removed three handler-local calls.
- `apps/api/src/egp_api/routes/crawler_runtime.py`: split internal heartbeat registration from the
  user-authenticated operator route and attached the worker dependency only to the internal router.
- `tests/phase1/test_internal_worker_auth.py`: added an auth-on missing/wrong/valid matrix and an
  exact current internal-route inventory contract.

### TDD evidence

- Added `test_internal_worker_routes_apply_worker_token_matrix` and
  `test_internal_worker_route_inventory_is_covered`.
- RED command:
  `PYTHONPATH=apps/api/src:packages/observability/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/db/src:apps/worker/src:packages/notification-core/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_internal_worker_auth.py -q`
- RED result: `1 failed, 4 passed`; `/internal/worker/projects/status-update` returned user-auth
  detail `missing authentication` instead of worker-auth detail `missing internal worker token`.
- GREEN command: the same focused command after implementation.
- GREEN result: `5 passed`.

### Tests and gates

- Affected command:
  `python -m pytest tests/phase1/test_internal_worker_auth.py tests/phase1/test_projects_and_runs_api.py tests/phase2/test_crawler_runtime.py -q`
- Result: `30 passed, 1 warning`.
- Reliability: the same 30-test command passed three consecutive runs.
- Ruff check of all touched Python files: passed.
- Ruff format check identified only the new test; it was formatted and will be rechecked.

### Wiring verification

| Component | Production call site | Registration | Schema |
|---|---|---|---|
| Internal worker JWT bypass | middleware request pipeline | `/internal/worker/` prefix class | N/A |
| Project ingest token dependency | discover, close-check, status-update | `project_ingest.router` dependencies | N/A |
| Runtime heartbeat token dependency | crawler heartbeat handler | `crawler_runtime.internal_router` dependencies | `crawler_runtime_heartbeats` unchanged |
| Operator runtime read | `/v1/rules/crawler-runtime` | user-authenticated public router | unchanged |

### Behavior and risk

- Missing, invalid, and valid worker tokens now receive consistent 401, 403, and handler-reached
  outcomes across all four current internal endpoints.
- The internal prefix intentionally fails closed at the router dependency. The exact route
  inventory test forces any future internal route to be added to the auth matrix.
- No URL, header, response schema, database schema, or user-authenticated operator behavior
  changed.

### Follow-ups

- Run full U1 gates, QCHECK, formal `g-check`, PR checks, merge, and exact merged-SHA post-merge
  verification.
- E0 remains blocked by GitHub billing; this code evidence does not open Gate S1.

## Review (2026-07-27 07:48:24 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase1-u1`
- Branch: `fix/internal-worker-auth-boundary`
- Scope: working-tree at base `4fe12f85d572d1f3f3f60be35fa793dfe1fbaa68`
- Commands Run: staged status/name/stat and targeted patch inspection; exact line inspection of
  middleware and both routers; focused 5-test RED/GREEN; affected 30-test suite three times;
  full Python suite; repository Ruff/format/compile; generated API types; web unit/type/lint/build

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

- Assumption: all future routes beneath `/internal/worker/` must use the same worker-token
  dependency. The exact route-inventory test intentionally fails when a route is added without
  extending the behavioral matrix.
- Residual risk: GitHub required jobs still execute zero steps because of the account billing lock;
  local gates cannot certify the remote runner or image-publish environment.

### Recommended Tests / Validation

- Keep the focused internal-route matrix in every affected API gate.
- Preserve the existing operator runtime role test so the split public router cannot accidentally
  inherit worker-token authentication.
- Rerun real required GitHub checks when E0 is restored.

### Rollout Notes

- No migration, environment, header, URL, or response-contract change.
- Safe rollback is a revert of this PR; the prior behavior would reintroduce the confirmed
  status-update authentication defect.
- Formal disposition: no product-code findings require remediation. Proceed to commit and PR after
  restaging this appended review artifact.

## U1 final pre-commit gates (2026-07-27 07:48:24 +0700)

- `./.venv/bin/ruff check apps packages tests scripts`: passed.
- `./.venv/bin/ruff format --check <four touched Python files>`: passed.
- `./.venv/bin/python -m compileall -q apps packages`: passed.
- `./.venv/bin/python -m pytest tests apps packages -q`: `1228 passed, 112 warnings`.
- The first full-suite attempt was `1227 passed, 1 failed`; the failure was isolated-worktree
  infrastructure because `scripts/pg_backup.sh` correctly expected
  `/Users/subhajlimanond/dev/egp-phase1-u1/.venv/bin/python`. After adding an ignored symlink to
  the established repo environment, the exact failed test passed and the unchanged source then
  passed the complete 1228-test rerun.
- `(cd apps/web && npm run check:api-types)`: generated schema/types current.
- `(cd apps/web && npm run test:unit)`: 12 files and 51 tests passed.
- `(cd apps/web && npm run typecheck)`: passed.
- `(cd apps/web && npm run lint)`: passed with no warnings or errors.
- `(cd apps/web && npm run build)`: Next.js production build passed.
- QCHECK and formal `g-check`: no findings; residual risk is the separately documented zero-step
  GitHub billing lock.

## U1 merge and local landing (2026-07-27 07:50:15 +0700)

- PR: `#178`, `https://github.com/SubhajL/egp/pull/178`.
- Reviewed head: `3aaceea8a95ca5032d7cc086a3dbb38470bfa846`.
- Required checks: all six failed with zero steps; exact annotation remained
  `The job was not started because your account is locked due to a billing issue.`
- Admin squash merge: `ae90f374b27a90ddc779848e6eb688151019f388`.
- Primary checkout fast-forwarded without touching its three protected dirty files.
- Verified local `main == origin/main == ae90f374b27a90ddc779848e6eb688151019f388`.
- Exact merged-SHA post-merge gate:
  `python -m pytest tests/phase1/test_internal_worker_auth.py tests/phase1/test_projects_and_runs_api.py tests/phase2/test_crawler_runtime.py -q`
  returned `30 passed, 1 warning`; touched-file Ruff passed.
- Disposition: U1 is landed. E0 and Gate S1 remain blocked independently.

## Implementation (2026-07-27 08:04:58 +0700) - U2 migration-only API bootstrap

### Goal

Make checked-in migrations the only runtime schema authority. Repository factories and default API
construction must emit no DDL, while SQLite tests retain a clearly named explicit bootstrap path.

### What changed

- `apps/api/src/egp_api/main.py`: added `bootstrap_schema: bool = False` and forwarded it into the
  repository bundle.
- `apps/api/src/egp_api/bootstrap/repositories.py`: threaded the explicit flag through every
  DDL-capable API repository factory; runtime default remains false.
- Thirteen repository factory modules: changed `bootstrap_schema` defaults from true to false.
- `packages/db/src/egp_db/repositories/document_repo.py`: added an explicit false-default factory
  parameter and removed automatic SQLite detection/DDL.
- `tests/support/app_factory.py`: added `create_test_app()`, which explicitly opts SQLite API tests
  into `bootstrap_schema=True` and leaves PostgreSQL tests migration-owned.
- API test imports now use the named test adapter. Direct worker/repository tests explicitly create
  their SQLite mapped schema at the test boundary.
- `tests/phase1/test_high_risk_architecture.py`: added blank-database, explicit-test-bootstrap, and
  fourteen-factory-default contracts.
- `tests/phase1/test_migration_runner.py`: added a real temporary-PostgreSQL test that applies every
  migration, constructs the API without repository bootstrap, and serves `/health`.

### TDD evidence

- RED command:
  `python -m pytest tests/phase1/test_high_risk_architecture.py -k 'default_does_not_create_sqlite_schema or explicit_test_bootstrap_creates_sqlite_schema or repository_factories_default_bootstrap_false' -q`
- RED result: `16 failed`; default app creation made 38 mapped tables, explicit bootstrap was not a
  supported argument, thirteen factories defaulted true, and the document factory had no explicit
  bootstrap parameter.
- GREEN result for the same command: `16 passed, 10 deselected`.
- PostgreSQL contract command:
  `python -m pytest tests/phase1/test_high_risk_architecture.py tests/phase1/test_migration_runner.py::test_migrated_postgres_starts_without_repository_bootstrap -q`
- PostgreSQL contract result: `27 passed`.

### Regression discovery and remediation

- First full run after removing implicit DDL: `14 failed, 1231 passed`.
- The failures identified precisely the remaining test-only assumptions:
  four direct worker-document cases, one Phase 1 wiring case, two close-check workflow cases, one
  direct crawler-runtime repository case, and six immediate-discovery API cases whose grouped
  product import had bypassed the test adapter.
- After explicit test setup, `pytest --lf` returned `14 passed`.
- Affected suite:
  `pytest tests/phase1/test_high_risk_architecture.py tests/phase1/test_migration_runner.py tests/phase1/test_document_infrastructure.py tests/phase1/test_phase1_wiring.py tests/phase1/test_worker_workflows.py tests/phase2/test_crawler_runtime.py tests/phase2/test_immediate_discover.py -q`
- Affected result: `93 passed, 36 warnings`, repeated successfully three consecutive times.
- Final full result: `1245 passed, 112 warnings`.

### Additional gates

- `ruff check apps packages tests scripts`: passed.
- `python -m compileall -q apps packages`: passed.
- `apps/web npm run check:api-types`: generated schema/types current.
- `apps/web npm run test:unit`: 12 files and 51 tests passed.
- `apps/web npm run typecheck`: passed.
- `apps/web npm run lint`: passed with no warnings or errors.
- `apps/web npm run build`: production build passed.

### Wiring verification

| Component | Production call site | Registration/caller | Schema |
|---|---|---|---|
| Runtime no-DDL default | `uvicorn egp_api.main:create_app --factory` | `create_app()` to `build_repository_bundle()` | all mapped tables unchanged |
| Repository factory defaults | API, workers, scripts | fourteen explicit `bootstrap_schema=False` defaults | shared `DB_METADATA` |
| Explicit SQLite test setup | pytest API/direct worker tests | `tests.support.app_factory.create_test_app()` or explicit factory true | SQLite mapped schema only |
| Migrated PostgreSQL startup | API construction after runner | `apply_migrations()` then `create_app()` | `schema_migrations` plus current tables |
| Document repository factory | API and worker document ingest | explicit bootstrap argument, default false | documents and related tables |

### Behavior and risk

- Runtime app or repository construction no longer creates or repairs tables implicitly.
- Blank, stale, or unmigrated databases now fail when real repository operations occur; U3 will
  surface that state proactively through `/ready`.
- Test-only SQLite bootstrap remains explicit and cannot be activated by a production environment
  variable.
- No SQL migration, table, column, route, response schema, or TypeScript contract changed.
- Backout is a revert, but that would restore the confirmed out-of-ledger DDL defect.

### Follow-ups

- Perform QCHECK and formal `g-check`, then commit, submit, inspect zero-step CI, admin-merge, and
  verify the exact landed SHA.
- E0 and Gate S1 remain blocked by the billing lock.

## Review (2026-07-27 08:08:42 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase1-u1`
- Branch: `fix/migration-only-api-bootstrap`
- Scope: staged U2 changes at base `ae90f374b27a90ddc779848e6eb688151019f388`
- Commands Run: staged status/name/stat/patch inspection; DDL-capable factory and caller
  inventories; remaining implicit-bootstrap search; focused RED/GREEN and PostgreSQL migration
  contracts; affected suite three times; full Python suite; repository Ruff/compile; generated API
  types; web unit/type/lint/build

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

- Assumption: `FilesystemDocumentRepository` remains an explicitly local compatibility wrapper.
  Its constructor-owned SQLite schema creation is isolated from API/worker repository factories and
  is the sole remaining product `bootstrap_schema=True` call.
- Residual risk: a blank or stale database now fails on first real repository operation until U3
  adds proactive readiness reporting.
- Residual risk: GitHub required jobs still execute zero steps because of the account billing lock;
  local gates cannot certify the remote runner or image-publish environment.

### Recommended Tests / Validation

- Keep both the blank-SQLite no-DDL test and the migrated-PostgreSQL startup test in required Python
  gates.
- Preserve the factory-default inventory so newly added DDL-capable factories must explicitly
  remain migration-only.
- Rerun real required GitHub checks when E0 is restored.

### Rollout Notes

- No migration or database object changed; this changes ownership of schema creation, not schema
  shape.
- API and worker deployments must run the checked-in migration runner before startup.
- Formal disposition: no product-code findings require remediation. Proceed to commit and PR after
  restaging this appended review artifact.

## U2 merge and local landing (2026-07-27 08:11:04 +0700)

- PR: `#179`, `https://github.com/SubhajL/egp/pull/179`.
- Reviewed head: `dd1e7c939bac53cdccc20a9b80be3439d4323a90`.
- Required checks: all six failed with zero steps; exact annotation remained
  `The job was not started because your account is locked due to a billing issue.`
- Admin squash merge: `3fa826a5f0c878167d702c9d345a8e972d8573b1`.
- `gh pr merge` completed the remote merge, then returned nonzero only because it could not check
  out `main` in the isolated worktree while the primary worktree owned that branch.
- Primary checkout fast-forwarded without touching its three protected dirty files.
- Verified local `main == origin/main == 3fa826a5f0c878167d702c9d345a8e972d8573b1`.
- Exact merged-SHA post-merge contract returned `27 passed`; touched-scope Ruff passed.
- Disposition: U2 is landed. E0 and Gate S1 remain blocked independently.

## Implementation (2026-07-27 08:24:12 +0700) - U3 readiness and runtime topology

### Goal

Separate database-independent liveness from admission readiness, require the exact checked-in
migration set before traffic, and reject every PostgreSQL API topology except explicit external
background execution.

### TDD evidence

- RED command:
  `python -m pytest tests/phase1/test_api_readiness.py
  tests/phase2/test_background_runtime_mode.py::test_postgres_requires_explicit_external_mode
  tests/phase2/test_background_runtime_mode.py::test_sqlite_defaults_to_embedded_background_mode
  tests/phase1/test_dev_postgres.py::test_create_phase1_smoke_app_uses_local_callback_secret
  tests/operations/test_api_readiness_assets.py -q`
- RED result: `10 failed, 2 passed`.
- Confirmed causes: `/live` and `/ready` were absent and auth-protected; PostgreSQL still defaulted
  to embedded execution; the PostgreSQL smoke caller did not declare external mode; Compose and
  the image still probed `/health`; the launch checker did not distinguish liveness from readiness.

### What changed

- Added `ReadinessService`, which performs a two-second PostgreSQL connection/statement-bounded
  probe and compares the full `schema_migrations` ledger with the exact checked-in SQL filenames.
- Added public `/live` and `/ready` endpoints. `/health` keeps its prior payload and OpenAPI
  operation ID as a compatibility alias for liveness.
- Readiness returns stable reasons for unreachable databases, absent ledgers, missing migrations,
  unexpected migration history, and unavailable manifests. It logs the reason and pending count
  without exposing driver errors or connection details.
- PostgreSQL API startup now accepts only `EGP_BACKGROUND_RUNTIME_MODE=external`; SQLite retains
  its embedded default. The PostgreSQL smoke app declares external mode explicitly.
- Both Compose API health checks and the image health check now use `/ready`; both env templates
  select external mode.
- The launch gate checker independently probes `/live` and `/ready`. Deployment, rollback,
  incident, secret-rotation, webhook, remote-crawler, frontend-handoff, and local-run guidance now
  use readiness for admission and preserve `/health` only as a documented compatibility alias.
- Regenerated OpenAPI and TypeScript API contracts with typed liveness/readiness responses and an
  explicit HTTP 503 readiness response.

### GREEN and regression evidence

- Focused GREEN after implementation: `13 passed`, expanded to `32 passed` after exact-history,
  absent-ledger, structured-log, explicit-environment, and compatibility-operation-ID coverage.
- Affected matrix: `111 passed` three consecutive times.
- Full repository Python run: `1258 passed, 112 warnings`.
- Repository Ruff, touched-file format check, compileall, both Compose config validations, shell
  syntax checks, and diff whitespace check passed.
- OpenAPI/TypeScript generated contracts are current.
- Web unit tests: 12 files and 51 tests passed; typecheck, lint, and production build passed.

### Wiring verification

| Component | Runtime entry point | Registration/caller | Schema |
|---|---|---|---|
| Liveness | `GET /live`, compatibility `GET /health` | auth bypass plus bootstrap route | none |
| Readiness | `GET /ready` | `app.state.readiness_service` in service bootstrap | `schema_migrations` |
| Migration manifest | readiness service | `packages/db/src/migrations/*.sql` exact filenames | ledger versions |
| Runtime topology | `create_app()` | config validation after resolved database URL | none |
| Container admission | API image and both Compose files | Docker/Compose health checks | readiness response |
| Operator admission | `scripts/check_launch_gates.sh` | separate live/ready curl probes | readiness response |

### Behavior and risk

- Liveness remains database-independent; traffic admission now fails closed until DB and schema are
  exactly ready.
- Readiness performs no DDL and emits no database credentials or raw driver failures.
- PostgreSQL embedded mode is intentionally removed. Rollback keeps the external topology and
  rolls back the release SHA instead.
- The first post-implementation GREEN attempt accidentally imported editable packages from the
  primary checkout. All authoritative test runs explicitly placed the isolated worktree sources
  first on `PYTHONPATH`; generated contracts used the same source path.
- E0 and Gate S1 remain blocked by the GitHub billing lock.

## Review (2026-07-27 08:34:30 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase1-u1`
- Branch: `feat/readiness-topology`
- Scope: staged U3 changes at base `3fa826a5f0c878167d702c9d345a8e972d8573b1`
- Commands Run: staged core/test/operations/generated-contract patch inspection; runtime entry
  point and background-mode caller inventories; stale health/embedded documentation searches;
  focused and affected tests; full Python suite; Ruff/format/compile; Compose and shell validation;
  generated contract check; web unit/type/lint/build

### Findings

CRITICAL

- No findings.

HIGH

- No findings.

MEDIUM

- No findings.

LOW

- No unresolved findings. During QCHECK, the first alias implementation changed the established
  `/health` OpenAPI operation ID. It was split into a dedicated compatibility handler, the original
  `health_health_get` ID was restored, and a regression assertion plus regenerated contract now
  lock it.

### Open Questions / Assumptions

- Assumption: an applied migration version absent from the current checkout means the running
  binary is older than the database and must fail readiness, even if all current filenames are
  present.
- Assumption: SQLite embedded mode is a local/test compatibility path only; every PostgreSQL API
  deployment owns background execution through the external executor services.
- Residual risk: each failed container probe emits one structured warning. This is intentional for
  admission diagnosis but operators should aggregate identical failures during a prolonged outage.
- Residual risk: GitHub required jobs still execute zero steps because of the account billing lock;
  local gates cannot certify the remote runner or image-publish environment.

### Recommended Tests / Validation

- Keep unreachable, absent-ledger, pending, unexpected-history, and exact-migrated readiness states
  in required Python gates.
- Keep both Compose parsing tests and the generated OpenAPI/TypeScript contract check.
- After deployment, verify `/live` remains green while a controlled database denial makes `/ready`
  red, then restore the DB and prove `/ready` green on the exact deployed SHA.
- Rerun real required GitHub checks when E0 is restored.

### Rollout Notes

- Apply all checked-in migrations before starting the API.
- Set `EGP_BACKGROUND_RUNTIME_MODE=external`; PostgreSQL embedded or omitted mode now fails startup.
- Roll back the release SHA without changing the external executor topology.
- Formal disposition: no unresolved product-code findings require remediation. Proceed to final
  exact-tree gates, commit, and PR.

## U3 final pre-commit gates (2026-07-27 08:38:41 +0700)

- Exact reviewed tree full Python suite: `1258 passed, 112 warnings`.
- `ruff check apps packages tests scripts`: passed.
- Touched Python `ruff format --check`: passed.
- `python -m compileall -q apps packages`: passed.
- Production and local-development Compose configurations: passed.
- `bash -n scripts/check_launch_gates.sh scripts/run_local.sh`: passed.
- Staged diff whitespace check: passed.
- Generated OpenAPI/TypeScript contract check: current.
- Web unit tests: 12 files and 51 tests passed.
- Web typecheck, lint, and production build: passed.
- QCHECK/formal `g-check`: no unresolved findings.

## U3 merge and local landing (2026-07-27 08:42:17 +0700)

- PR: `#180`, `https://github.com/SubhajL/egp/pull/180`.
- Reviewed head: `a9972cb8c5af84afa6b57d385c35d79cf3e53d75`.
- Required checks: all six failed with zero steps; exact annotation remained
  `The job was not started because your account is locked due to a billing issue.`
- Admin squash merge: `178fe531903a66d64d2f5b8cdef5a0f388033dfc`.
- The merge command completed the remote merge, then returned nonzero only because the isolated
  worktree could not check out the primary worktree's `main` branch.
- Primary checkout fast-forwarded without touching its three protected dirty files.
- Verified local `main == origin/main == 178fe531903a66d64d2f5b8cdef5a0f388033dfc`.
- Exact merged-SHA post-merge gate returned `32 passed`; touched-scope Ruff passed.
- Disposition: U3 is landed. E0 and Gate S1 remain blocked independently.

## Implementation (2026-07-27 08:45:03 +0700) - U4 bearer authorization trust

### Goal

Accept bearer tenant and role authorization only from direct EGP-controlled claims, require the
dedicated EGP signing secret whenever authentication is enabled, and preserve database-backed
cookie sessions.

### TDD evidence

- RED command:
  `python -m pytest tests/phase4/test_auth_api.py -k
  'metadata_cannot_elevate_role_or_tenant or login_sets_http_only_session_cookie_and_me_reads_session
  or bearer_tokens_remain_supported_for_me' tests/phase1/test_high_risk_architecture.py -k
  'auth_enabled_startup_requires_explicit_egp_jwt_secret or
  auth_disabled_startup_does_not_require_jwt_secret or metadata_cannot_elevate_role_or_tenant or
  login_sets_http_only_session_cookie_and_me_reads_session or
  bearer_tokens_remain_supported_for_me' -q`
- RED result: `3 failed, 3 passed`.
- Confirmed causes: both `user_metadata.role` and `app_metadata.role` elevated a direct-tenant
  bearer to support access; `get_jwt_secret()` silently accepted `SUPABASE_JWT_SECRET`.
- Existing direct bearer and cookie-session compatibility tests remained green in RED.

### What changed

- Added one authorization-claim extractor for bearer tokens. It accepts `tenant_id` and optional
  `role` only as direct claims; nested `user_metadata` and `app_metadata` are never authorization
  sources.
- Role checks now use the normalized role already stored in `AuthContext`. This preserves
  database-backed cookie-session roles while preventing later code from re-reading untrusted
  bearer metadata.
- Removed the `SUPABASE_JWT_SECRET` fallback. Auth-enabled startup now fails closed unless
  `EGP_JWT_SECRET` is explicitly configured; auth-disabled local/test startup remains supported
  without a JWT secret.
- Added the local auth controls to `.env.example` and aligned the frontend handoff and secret
  rotation runbooks with the direct-claim and opaque-session runtime behavior.

### GREEN and regression evidence

- Focused GREEN: `6 passed, 49 deselected`.
- Affected authentication, authorization, registration, webhook, rules, observability, internal
  worker, and high-risk architecture matrix: `171 passed, 5 warnings` three consecutive times.
- Full repository Python run: `1262 passed, 112 warnings`.
- Repository Ruff, touched-file format check, compileall, both Compose config validations, env
  template tests, diff whitespace check, and generated OpenAPI/TypeScript contract check passed.
- Web unit tests: 12 files and 51 tests passed; typecheck, lint, and production build passed.

### Wiring verification

| Component | Runtime entry point | Authorization source | Regression coverage |
|---|---|---|---|
| Machine bearer | auth middleware -> `authenticate_bearer_request()` | direct `sub`, `tenant_id`, optional `role` | nested metadata rejection and direct bearer `/v1/me` |
| Browser session | auth middleware -> `AuthService.authenticate_session()` | database session user and tenant role | login cookie and authenticated `/v1/me` |
| Admin authorization | `request_has_support_role()` | normalized `AuthContext.role` | nested metadata receives 403 |
| JWT configuration | repository bootstrap -> `get_jwt_secret()` | `EGP_JWT_SECRET` only | enabled startup failure and disabled startup compatibility |

### Behavior and risk

- A direct tenant claim always wins because nested tenant values are ignored rather than merged.
  A token with only nested tenant metadata receives 401.
- Rotating `EGP_JWT_SECRET` invalidates old machine bearer tokens but does not invalidate
  database-backed browser sessions.
- The API remains an HS256 verifier; the trusted machine-token issuer must be rotated in lockstep.
- E0 and Gate S1 remain blocked by the GitHub billing lock.

## Review (2026-07-27 08:55:36 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase1-u1`
- Branch: `fix/bearer-authorization-claims`
- Scope: staged U4 changes at base `178fe531903a66d64d2f5b8cdef5a0f388033dfc`
- Commands Run: staged source/test/docs patch inspection; bearer and session authorization-source
  tracing; JWT configuration caller inventory; legacy secret and metadata authority searches;
  focused and affected tests; full Python suite; Ruff/format/compile; Compose and env-template
  validation; generated contract check; web unit/type/lint/build

### Findings

CRITICAL

- No findings.

HIGH

- No findings.

MEDIUM

- No findings.

LOW

- No unresolved findings. During QCHECK, the touched secret-rotation runbook still described
  browser sessions as JWTs signed with `EGP_JWT_SECRET`. It now correctly documents HS256 machine
  bearer verification, zero-overlap bearer rotation, and continuity of opaque database sessions.

### Open Questions / Assumptions

- Assumption: every machine bearer issuer is EGP-controlled and can place `tenant_id` and optional
  `role` at the JWT top level.
- Assumption: auth-disabled startup without a JWT secret is retained solely for explicit local and
  test use; the production template keeps authentication enabled and the secret required.
- Residual risk: HS256 rotation has no dual-key overlap, so issuers and the API require a
  coordinated cutover.
- Residual risk: GitHub required jobs still execute zero steps because of the account billing lock;
  local gates cannot certify the remote runner or image-publish environment.

### Recommended Tests / Validation

- Keep both nested metadata variants in required tests and preserve the direct-claim tenant result,
  absent direct-tenant 401, and support-route 403 assertions.
- Keep direct bearer and database-cookie session compatibility tests together in the auth matrix.
- After deployment, rotate a non-production bearer key and prove new-key success, old-key 401, and
  uninterrupted browser-session access on the exact deployed SHA.
- Rerun real required GitHub checks when E0 is restored.

### Rollout Notes

- Configure `EGP_JWT_SECRET` explicitly before starting any auth-enabled API.
- Update every HS256 machine-token issuer in the same cutover window.
- Do not migrate browser login to bearer tokens; existing sessions remain database-backed.
- Formal disposition: no unresolved product-code findings require remediation. Proceed to final
  exact-tree gates, commit, and PR.

## U4 final pre-commit gates (2026-07-27 08:56:30 +0700)

- Exact reviewed tree full Python suite: `1262 passed, 112 warnings`.
- Focused direct-bearer, nested-metadata, cookie-session, and JWT-startup matrix: `6 passed`.
- Affected matrix: `171 passed, 5 warnings` three consecutive times.
- `ruff check apps packages tests scripts`: passed.
- Touched Python `ruff format --check`: passed.
- `python -m compileall -q apps packages`: passed.
- Production and local-development Compose configurations: passed.
- Env-template test suite: `15 passed`.
- Staged diff whitespace check: passed.
- Generated OpenAPI/TypeScript contract check: current.
- Web unit tests: 12 files and 51 tests passed.
- Web typecheck, lint, and production build: passed.
- QCHECK/formal `g-check`: no unresolved findings.

## U4 merge and local landing (2026-07-27 08:57:48 +0700)

- PR: `#181`, `https://github.com/SubhajL/egp/pull/181`.
- Reviewed head: `1ced1eab5e013f51cc0f4538be3b0536345fdd3c`.
- Required checks and `claude-review` all failed with zero steps; the exact annotation was
  `The job was not started because your account is locked due to a billing issue.`
- Vercel preview completed successfully, but it is not a substitute for the required jobs.
- Admin squash merge: `a356b15d247214359240f2cccd4ceeaa6de78f62`.
- The merge command completed the remote merge, then returned nonzero only because the isolated
  worktree could not check out the primary worktree's `main` branch.
- Primary checkout fast-forwarded without touching its three protected dirty files.
- Verified local `main == origin/main == a356b15d247214359240f2cccd4ceeaa6de78f62`.
- Exact merged-SHA post-merge bearer, metadata, session, and startup matrix returned `6 passed`;
  touched-scope Ruff passed.
- Disposition: U4 is landed. E0 and Gate S1 remain blocked independently.

## Phase 1 exact-main completion audit (2026-07-27 09:03:25 +0700)

### Audited release tree

- Product-code SHA: `a356b15d247214359240f2cccd4ceeaa6de78f62`.
- Primary `main` and `origin/main` are identical with `ahead=0`, `behind=0`, and
  `branch_synced=true`.
- `scripts/check_main_sync.py --json` reports `ok=false` only because the primary checkout retains
  the same three protected pre-existing dirty files. The isolated audit worktree was clean at the
  audited SHA before this evidence-only log update.
- No deployment was attempted: the source plan requires E0 and live Gate S1 evidence first.

### Phase 1 PR disposition

| Unit | PR | Merge SHA | Code gate |
|---|---:|---|---|
| U1 internal worker auth boundary | #178 | `ae90f374b27a90ddc779848e6eb688151019f388` | missing/wrong/valid worker-token route matrix green |
| U2 migration-only API bootstrap | #179 | `3fa826a5f0c878167d702c9d345a8e972d8573b1` | blank DB remains blank; migrated PostgreSQL starts |
| U3 API readiness and runtime topology | #180 | `178fe531903a66d64d2f5b8cdef5a0f388033dfc` | liveness/readiness, exact migration ledger, and external PostgreSQL topology green |
| U4 bearer authorization claims | #181 | `a356b15d247214359240f2cccd4ceeaa6de78f62` | nested metadata elevation denied; direct bearer and cookie session remain compatible |

### Exact-main validation

- Full Python suite: `1262 passed, 112 warnings` in 174.73 seconds.
- Consolidated U1-U4 defect-sensitive matrix: `53 passed`.
  It includes the complete internal-route token inventory, no-DDL/factory defaults, migrated
  PostgreSQL startup, readiness states/assets, explicit PostgreSQL topology, direct/nested bearer
  claims, and cookie-session compatibility.
- `ruff check apps packages tests scripts`: passed.
- `python -m compileall -q apps packages`: passed.
- Production and local-development Compose configurations: passed.
- Env-template tests: `15 passed`.
- Generated OpenAPI and TypeScript API contracts: current.
- Web unit tests: 12 files and 51 tests passed.
- Web typecheck, lint, and production build: passed.

### Acceptance decision

- **Phase 1 code-level pilot blockers U1-U4: COMPLETE.**
- **External prerequisite E0: BLOCKED.** The six required jobs on PR #181 each had zero steps and
  the GitHub billing-lock annotation. Local tests, the admin merge, and Vercel success do not
  satisfy E0.
- **Gate S1: CLOSED.** No real pilot is authorized until E0 is restored and the exact deployed SHA
  passes every live migration/readiness, login/admin/project/rule/recrawl/document/export, worker,
  payment, notification, artifact, backup/restore, Mac doctor, terminal-request, and operator
  rollback/observation requirement without mandatory skips.
- Next lifecycle action is external: restore GitHub billing, rerun required checks with real job
  steps on current `main`, then execute and record Gate S1 against the exact deployed SHA.

## Review (2026-07-27 09:05:29 +0700) - Phase 1 completion audit

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase1-u1`
- Branch: `docs/phase1-completion-audit`
- Scope: evidence-only completion record for product-code SHA
  `a356b15d247214359240f2cccd4ceeaa6de78f62`
- Commands Run: source-plan Phase 1 and Gate S1 reread; U1-U4 Coding Log and merge-SHA audit;
  GitHub PR/check/job/annotation inspection; exact-main full and defect-sensitive Python tests;
  Ruff/compile; Compose/env-template validation; generated-contract check; web unit/type/lint/build;
  primary/main synchronization and protected-dirty-file verification

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

- The completion decision applies only to Phase 1 code-level blockers U1-U4; it does not satisfy
  the external E0 prerequisite or any live Gate S1 item.
- The three primary-checkout dirty files predate and remain outside all Phase 1 commits. Their
  presence makes the sync script's aggregate `ok` false even though local and remote SHAs match.
- Residual risk: GitHub required jobs and `claude-review` did not run any steps, so remote-runner,
  image-build, and independent hosted-review evidence is absent.

### Recommended Tests / Validation

- Restore billing and rerun all six required checks with non-empty job steps on current `main`.
- Deploy only the resulting exact checked SHA, then run every Gate S1 live test without skips.
- Preserve the 53-test U1-U4 matrix as a fast regression gate alongside the full repository suite.

### Rollout Notes

- Phase 1 code can remain landed while E0 is repaired; keep Gate S1 closed.
- Do not reinterpret the audit PR, local evidence, admin merges, or Vercel preview as launch
  approval.
- Formal disposition: no unresolved finding changes the Phase 1 code-complete/E0-blocked/S1-closed
  decision. Proceed to merge this evidence record.

## Partial Gate S1 rehearsal (2026-07-27 09:56:40 +0700)

### Goal and scope

- Perform every non-destructive S1 check that is currently meaningful while GitHub billing keeps
  E0 unavailable.
- Use clean exact-`main` source for local checks and read-only production/Mac diagnostics for live
  state.
- Do not deploy, warm the browser profile, enqueue work, exercise payment/notification providers,
  or open a pilot. This is partial evidence only; it cannot accept Gate S1.

### Release identity and E0

- Clean rehearsal worktree base: `622d2957ac8df31ff3c0f167117eaf12c3b8acbd`, identical to
  freshly fetched `origin/main`.
- Read-only SSH inspection reports the Lightsail checkout at
  `6882850cb79930beb7ca14c5c8500a54e0605134`. The host checkout is not the U1-U4 completion
  tree, and no running-image revision evidence proves an exact U1-U4 deployment.
- Current-`main` Actions runs `30231390350` and `30231390315` contain seven failed jobs:
  six CI/image jobs and the publish-images job. Every check annotation says:
  `The job was not started because your account is locked due to a billing issue.`
- The jobs executed no source steps. E0 remains blocked; local evidence is not a substitute.

### Evidence collected

- `API_URL=https://api.egptracker.com ./scripts/check_launch_gates.sh`:
  `7 passed, 3 failed, 2 skipped`.
  - `/metrics`, conflict counters, e-GP 429 count, inflight count, subprocess count, and the local
    Chrome PID cap passed.
  - `/live` and `/ready` failed against the current production runtime.
  - The checker flagged one first-level profile directory as stale. This is not accepted as
    proof of orphan cleanup because the directory is the intentional persistent profile.
  - Cross-tenant DB attribution and rate-limiter engagement skipped without production DB/traffic
    context.
- `scripts/run_remote_crawl.sh check` passed the production safety guard.
- `scripts/run_remote_crawl.sh doctor` was read-only and sanitized:
  database connected, shared circuit closed, profile lock free, but status `blocked` with
  `queue_unavailable` and `heartbeat_unavailable`; the persistent profile reported
  `warm_required`.
- `./.venv/bin/python scripts/run_phase1_postgres_smoke.py` passed on clean exact `main`:
  fresh migrations, document create/list/download, project/run/task/status-event persistence, and
  alias persistence all completed against throwaway PostgreSQL clusters.
- The focused local S1 behavior matrix passed `271 tests`:
  migration/readiness, backup/restore, restore evidence, login/session/admin, project/run,
  rules/recrawl, export, document/artifact streaming, internal worker auth, discovery dispatch,
  crawler runtime, payment callbacks, email notification, notification dispatch, and LINE
  activation coverage.

### Requirement-by-requirement disposition

| Gate S1 requirement | Current evidence | Disposition |
|---|---|---|
| E0 jobs execute real steps and pass | Seven current-main jobs stopped by billing before steps | BLOCKED |
| U1-U4 deployed at the exact checked SHA | `main=622d2957`; Lightsail checkout `6882850c` | NOT ACHIEVED |
| U5-U6 in progress with dependency/image freeze | Phase 2 not yet implemented | NOT ACHIEVED |
| Fresh/upgrade migrations and `/ready` | Local PostgreSQL matrix green; deployed `/ready` fails | PARTIAL LOCAL ONLY |
| Login/admin/project/rule/recrawl/document/export | Local defect-sensitive matrix green; no live flow run | PARTIAL LOCAL ONLY |
| Worker status-update and one exact terminal request | Local route/dispatch/runtime matrix green; live queue unavailable | PARTIAL LOCAL ONLY |
| Payment sandbox, email/LINE, artifact upload/download | Local provider/notification/artifact contracts green; no live provider exercise | PARTIAL LOCAL ONLY |
| Latest backups and current restore drill | Local restore contract green; last recorded drill is 2026-06-16 with artifact-mirror caveats | INSUFFICIENT LIVE EVIDENCE |
| Mac doctor, worker `1`, profile/circuit/heartbeat healthy | Guard safe and DB/circuit healthy; queue/heartbeat blocked and profile warm required | FAILED |
| Launch checker has no failures or mandatory skips | `7 passed, 3 failed, 2 skipped` | FAILED |
| Named operator, rollback command, observation window | No exact-release live observation was started | NOT ACHIEVED |

### TDD and validation record

- No product behavior changed in this evidence-only rehearsal, so there is no RED implementation
  run.
- Exact commands:
  - `API_URL=https://api.egptracker.com ./scripts/check_launch_gates.sh`
  - `./.venv/bin/python scripts/run_phase1_postgres_smoke.py`
  - `EGP_REMOTECRAWL_ENV_FILE=/Users/subhajlimanond/dev/egp/.env.remotecrawl scripts/run_remote_crawl.sh check`
  - `EGP_REMOTECRAWL_ENV_FILE=/Users/subhajlimanond/dev/egp/.env.remotecrawl scripts/run_remote_crawl.sh doctor`
  - `./.venv/bin/python -m pytest -q tests/phase1/test_migration_runner.py tests/phase1/test_api_readiness.py tests/operations/test_api_readiness_assets.py tests/operations/test_pg_backup_restore.py tests/operations/test_restore_drill_evidence.py tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py tests/phase1/test_projects_and_runs_api.py tests/phase2/test_rules_api.py tests/phase2/test_export_service.py tests/phase1/test_documents_api.py tests/phase1/test_internal_worker_auth.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_crawler_runtime.py tests/phase3/test_payment_links.py tests/phase2/test_notification_service.py tests/phase2/test_notification_dispatch.py tests/phase4/test_line_activation_notify.py tests/phase1/test_artifact_store_streaming.py`
- Result: PostgreSQL smoke passed; focused matrix `271 passed, 21 warnings`.

### Decision and follow-up

- **Partial S1 rehearsal: COMPLETE.**
- **Gate S1: CLOSED.** The evidence directly contradicts acceptance on deployment identity,
  readiness, crawler runtime health, complete launch checks, and operator observation.
- Proceed with Phase 2 U5 then U6 through separate sequential PR lifecycles. Continue to block any
  pilot until billing is restored, checks execute real steps, the exact checked U1-U6 SHA is
  deployed, and every live S1 item passes without a mandatory skip.

## Review (2026-07-27 09:58:27 +0700) - partial S1 evidence

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase2-u5`
- Branch: `docs/partial-s1-rehearsal`
- Scope: staged working-tree evidence append based on
  `622d2957ac8df31ff3c0f167117eaf12c3b8acbd`
- Commands Run: exact S1 source-plan reread; current-main GitHub check/job/annotation inspection;
  read-only production launch checker; read-only Lightsail checkout SHA inspection; remote-crawl
  guard and sanitized doctor; local PostgreSQL smoke; focused 271-test S1 matrix;
  `git diff --check`; staged diff/stat inspection

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

- The running production container has no exact revision evidence in this rehearsal. The older host
  checkout plus missing `/live` and `/ready` are enough to reject exact-release acceptance, not to
  assert an unobserved image SHA.
- Local integration tests verify behavior contracts but do not replace live provider, backup,
  crawler, or observation evidence.
- Auggie was skipped because the available interface cannot enforce the required real two-second
  timeout; review used direct evidence and exact-string inspection.

### Recommended Tests / Validation

- After billing restoration, rerun all required jobs and verify non-empty successful steps on the
  exact release SHA.
- After U5-U6, deploy that checked SHA and run every S1 item live without mandatory skips.
- Capture immutable running-image identity, current backup/restore evidence, healthy doctor output,
  one exact terminal request, provider delivery, and the named operator observation record.

### Rollout Notes

- This evidence PR changes no product behavior and authorizes no deployment or pilot.
- The documented billing override applies only to landing engineering/evidence PRs, not to opening
  Gate S1.
- Formal disposition: no unresolved finding prevents committing the partial-S1 evidence while Gate
  S1 remains closed.

## 2026-07-27 10:34:32 +0700 — Phase 2 U5 reproducible release gates

### Goal and boundary

- Implement U5 from the frozen soft-launch plan on
  `build/reproducible-release-gates`, based on merged partial-S1 SHA
  `0b8b02d142fa503b42a6f6346a398ab9910bf15b`.
- Scope: one frozen Python workspace, immutable SQL migration manifest, real PostgreSQL
  migration/readiness contracts, a critical browser lane, and enforced dependency vulnerability
  policy.
- U6 runtime-image separation/hardening is deliberately deferred to its own sequential PR.
- E0 is still billing-blocked and Gate S1 remains CLOSED.
- Auggie was skipped because the available interface cannot enforce the required real two-second
  timeout; direct exact-string and file inspection was used.

### TDD record

- Initial RED:
  `./.venv/bin/python -m pytest -q tests/operations/test_reproducible_release_gates.py`
  failed all 5 initial tests because `uv.lock`/workspace wiring, the migration-manifest checker,
  enforced CI audits/PostgreSQL contracts, and the critical Playwright lane did not exist.
- Docker validation exposed a second wiring defect: the runtime stage invoked system Python before
  the frozen virtualenv was on `PATH`; the first API build failed with
  `No module named playwright`. Both runtime stages now set `PATH` before dependency-assisted
  install commands.
- The first web image validation transferred a 653.68 MB host context, including local build
  artifacts. A sixth RED test proved `apps/web/.dockerignore` was absent; the added ignore contract
  reduced the verified context to 9.64 kB.
- Current focused GREEN:
  `6 passed` in `tests/operations/test_reproducible_release_gates.py`.

### Implementation and wiring

| Producer | Consumer / enforced path | Evidence |
|---|---|---|
| Root `pyproject.toml`, API/worker workspace members, `uv.lock` | Bootstrap, all Python CI jobs, API and worker Docker builds | uv 0.11.32 and setup action pinned; every sync/export is frozen |
| `packages/db/src/migrations/manifest.sha256` | `scripts/check_migration_manifest.py`, migration CI job | Exact 35-file checksum set verified; drift unit test passes |
| PostgreSQL ledger/readiness contracts | Migration CI job with `EGP_CI_POSTGRES_CONTRACT=1` | Isolated temporary PostgreSQL run passed both opt-in contracts |
| `@critical` launch-path tags | `test:e2e:critical`, dedicated CI job | Login/MFA, worker-backed recrawl, and PromptPay tests each passed 3 consecutive runs |
| Python runtime export | `pip-audit --strict --disable-pip` | No known vulnerabilities |
| Frontend production/all-dependency audits | Frontend build CI job | Runtime high/critical: 0; all dependencies: no critical findings |
| Web `.dockerignore` | Web Docker build context | Host dependencies, generated builds, reports, and env files excluded |

### Security and compatibility changes

- Replaced vulnerable `python-jose`/`ecdsa` with `PyJWT[crypto]`; API exception handling and all JWT
  tests now use PyJWT. The frozen runtime audit is clean.
- Test-only HMAC keys were lengthened to at least 32 bytes so PyJWT's key-strength warnings identify
  real configuration problems rather than fixtures.
- Upgraded the frontend to patched Next.js 16.2.12 and nodemailer 9.0.3, migrated to Next's flat
  ESLint configuration, and retained only a documented compatibility exception for existing
  controlled-form hydration.
- The production npm audit is clean. Eleven high-severity findings remain in development-only
  ESLint/OpenAPI transitive packages; CI fails on critical findings across all dependencies without
  an allowlist or `continue-on-error`.

### Validation evidence so far

- Frozen lock, migration manifest, Ruff lint, and Ruff format: green. The newly executable format
  gate found latent billing-hidden drift; 79 Python files were normalized mechanically and the
  final declared scope reports `310 files already formatted`.
- Three consecutive full Python suites before the final fixture/dockerignore additions:
  `1424 passed, 2 skipped` each, in 180.04 s, 179.69 s, and 176.27 s. A final post-review triple run
  is still required before commit.
- Frontend unit tests: 3 consecutive runs, each `51 passed`; critical Playwright: 3 consecutive
  runs, each `3 passed`; full Playwright: `43 passed`.
- OpenAPI generated types current; TypeScript, ESLint, Next production build, compileall, and both
  Compose config validations passed.
- API, worker, and web images build. API/worker frozen-runtime import smokes passed.
- Shared local PostgreSQL was inspected but not modified after revealing pre-existing drift
  (`crawler_runtime_heartbeats` present while migration `033` was absent from the ledger).
  An isolated `TempPostgresCluster` applied the complete migration set and passed both CI contracts.

### Remaining lifecycle work

- Inspect the complete semantic and mechanical diff, run Claude read-only review, QCHECK, and formal
  `g-check`; remediate any findings.
- Run final post-remediation gates and three consecutive full suites.
- Commit, push, open U5 PR, record the expected billing-blocked GitHub checks, use the user's
  engineering-PR admin-merge authorization, and land exact merged `origin/main` locally.
- Start U6 only from that landed U5 main SHA.

## Review (2026-07-27 10:49:17 +0700) - Phase 2 U5 staged working tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase2-u5`
- Branch: `build/reproducible-release-gates`
- Scope: staged working tree based on
  `0b8b02d142fa503b42a6f6346a398ab9910bf15b`
- Commands Run: bounded staged diff/status/stat inspection; exact-string dependency and wiring
  searches; lock and manifest checks; Ruff lint/format; focused and full pytest; isolated
  PostgreSQL contracts; OpenAPI type check; TypeScript; ESLint; Vitest; critical and full
  Playwright; npm and pip audits; Compose config; API/worker/web image builds and runtime imports;
  Claude Code 2.1.220 read-only semantic review

### Findings

CRITICAL

- No unresolved findings. Claude identified that `apps/web/next-env.d.ts` had captured the local
  `.next-playwright` dist directory, which could couple clean type generation to a local
  Playwright artifact. The declaration is now the build-generated `.next/types/routes.d.ts` form
  at `apps/web/next-env.d.ts:3`, and
  `tests/operations/test_reproducible_release_gates.py:194` prevents regression. Clean-directory
  typecheck and production build both pass.

HIGH

- No findings.

MEDIUM

- No findings.

LOW

- No findings.

### Open Questions / Assumptions

- GitHub billing still prevents hosted jobs from starting, so the new
  `Critical Playwright Smoke` job cannot yet provide hosted runtime evidence. Admin-merging this
  engineering PR under the user's explicit billing override does not open Gate S1.
- The branch-protection required-check set is external configuration. After billing restoration,
  confirm the new job is required before treating it as a release gate.
- The 79-file Ruff normalization was reviewed as mechanical-only and is covered by the full suite;
  semantic review focused on the release-gate files.

### Recommended Tests / Validation

- Complete the final post-review triple full-suite run after all review remediation.
- Re-run the frozen lock, manifest, lint/format, audits, frontend matrix, exact PostgreSQL
  contracts, and all three image builds on the final staged state.
- On the PR, inspect every hosted job annotation and do not describe zero-step billing failures as
  passing checks.

### Rollout Notes

- U5 changes build/test/release contracts and dependency implementations but performs no
  deployment or production mutation.
- The PyJWT replacement preserves HS256 bearer behavior and rejects invalid tokens through
  `jwt.PyJWTError`; runtime dependency auditing is clean.
- U6 remains a separate sequential PR for lean non-root images, executor isolation, resource/log
  limits, and formal image smoke gates.
- Gate S1 remains CLOSED until exact deployed U1-U6 evidence and every live requirement pass.

### Final post-review validation closure

- Three consecutive full final-tree Python suites passed identically:
  `1426 passed, 2 skipped`, in 184.42 s, 184.51 s, and 177.84 s.
- The warning count fell to 113 after strengthening test-only HMAC fixtures; remaining warnings are
  the known Starlette/httpx and SQLite datetime deprecations.
- Final frozen lock, 35-file migration manifest, Ruff lint/format over 310 files, compileall,
  OpenAPI types, TypeScript, ESLint, Vitest, critical Playwright, Next production build, npm
  policy audits, Python runtime audit, and both Compose configurations passed.
- Final images built from the staged tree:
  API `sha256:4b30acdbd2107b27fcd678b4952af8e62a841dc4ba22a9148df06099dc97055f`,
  worker `sha256:f80c9d1fdb6081200685d0feb9dce019f7061417e269758641992198d3457672`,
  web `sha256:4da61432f0cd02a0782c18cc401109a14e51825892624a1ad091da9055b34295`.
  API and worker frozen-runtime import smokes passed.
- Final formal disposition: no unresolved QCHECK or g-check finding blocks the U5 commit.

## 2026-07-27 11:06:35 +0700 — U5 Vercel preview remediation

- PR #184 opened at exact head
  `fc140ee1119b4309b2748e24c397c405862e1a06`.
- All eight GitHub-hosted checks created zero source steps and returned the exact annotation:
  `The job was not started because your account is locked due to a billing issue.`
- Vercel was a separate real failure. Deployment
  `dpl_DuQn1cMEzm7oRkzUx5St8NbmAHJj` cloned exact `fc140ee`, installed successfully, and completed
  Next 16.2.12 Turbopack compilation/type/static generation, but Vercel's post-build adapter emitted
  no deployable output and the deployment ended `ERROR` without an error code/message. The last
  exact-main Next 15/webpack deployment emitted its expected lambdas and completed.
- TDD RED:
  `test_next_16_release_build_uses_vercel_compatible_webpack` first failed on the package build
  command, then on the explicit `vercel.json` command.
- Remediation: both local/Docker and Vercel release builds now use Next 16's supported
  `next build --webpack` path while retaining the patched Next 16.2.12 dependency.
- Focused GREEN: release-gate suite `8 passed`; webpack production build, TypeScript, ESLint, and
  `51` Vitest tests passed locally.
- A replacement Vercel preview must emit real deployable outputs and pass before merge.

## Review (2026-07-27 11:08:00 +0700) - U5 Vercel remediation

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase2-u5`
- Branch: `build/reproducible-release-gates`
- Scope: staged follow-up against committed U5 SHA
  `fc140ee1119b4309b2748e24c397c405862e1a06`
- Commands Run: failed/exact-main Vercel deployment metadata and bounded logs; targeted staged
  diff; focused release-gate pytest; Next 16.2.12 webpack build; TypeScript; ESLint; Vitest;
  Claude Code read-only focused review

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

- The static contract proves both release entry points select webpack; the replacement Vercel
  deployment is the required behavioral proof that deployable outputs are restored.
- Development remains on Turbopack through `next dev`; only production release builds use webpack.
  This is intentional because the observed failure was in Vercel post-build packaging, not local
  development.

### Recommended Tests / Validation

- Require the replacement Vercel preview to complete `READY` with non-empty lambda/static outputs.
- Re-run final lint, focused Python tests, unit/browser tests, production audit, and web Docker build
  on the follow-up commit.

### Rollout Notes

- The fix changes only the Next production bundler and does not alter routes, API contracts, or
  production environment values.
- Formal disposition: no unresolved finding blocks the follow-up commit; merge remains blocked on
  replacement preview evidence.
- Final local follow-up gates passed: focused release contracts `8 passed` three consecutive times;
  Ruff lint/format; TypeScript; ESLint; `51` Vitest tests; clean production npm audit; no
  all-dependency critical finding; and webpack web image
  `sha256:e2aa179525163676c194c39989761b2e947847c5ee018b878025ba3e6021509d`.

## 2026-07-27 11:13:23 +0700 — U5 Vercel output-mode correction

- Replacement deployment `dpl_5m4jFtxHqumHAnyiAkD8dxkHBwwf` at exact
  `6e8789ec6970c4c2784c387d83149df4fbad684c` disproved the bundler hypothesis: Next 16.2.12
  webpack also compiled, typechecked, prerendered, traced, and ran Vercel `onBuildComplete`, then
  produced zero deployment outputs and ended `ERROR` without an error code/message.
- The distinguishing boundary is deployment mode. The repo forced `output: "standalone"` for the
  Docker image even when Vercel's Next 16 adapter owned serverless output packaging. Vercel does
  not require standalone output; the self-hosted image does.
- Corrected implementation:
  `output: process.env.VERCEL ? undefined : "standalone"`. The ineffective webpack changes in
  `package.json` and `vercel.json` are reverted.
- TDD RED/GREEN: the release contract failed while the two build commands still selected webpack
  and the config forced standalone. It now passes and asserts standard release commands plus the
  Vercel/self-hosted output boundary.
- Behavioral local proof:
  a normal Next 16.2.12 build produced `.next/standalone/server.js`; a `VERCEL=1` build succeeded
  without `.next/standalone`; TypeScript, ESLint, and `51` Vitest tests passed.
- A third replacement preview remains mandatory before merge.
- Focused Claude review found that implicit `VERCEL` detection could make a local Vercel CLI build
  incompatible with the generic standalone `start` command. The final boundary is therefore
  explicit: `npm run build` sets `EGP_BUILD_STANDALONE=true`, `npm run build:vercel` does not, and
  `vercel.json` calls the latter. Local behavioral proof confirms the first build creates
  `.next/standalone/server.js` and the Vercel build does not.

## Review (2026-07-27 11:17:00 +0700) - final U5 Vercel output-mode fix

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-phase2-u5`
- Branch: `build/reproducible-release-gates`
- Scope: staged follow-up against
  `6e8789ec6970c4c2784c387d83149df4fbad684c`
- Commands Run: exact metadata and bounded logs for Vercel deployments
  `dpl_DuQn1cMEzm7oRkzUx5St8NbmAHJj` and
  `dpl_5m4jFtxHqumHAnyiAkD8dxkHBwwf`; targeted staged diff; focused pytest;
  explicit self-hosted and Vercel-mode Next builds; TypeScript; ESLint; Vitest; two focused Claude
  read-only reviews

### Findings

CRITICAL

- No findings.

HIGH

- No findings.

MEDIUM

- No unresolved findings. Claude's first review correctly found that implicit `VERCEL` detection
  made local Vercel CLI output ambiguous; the explicit `EGP_BUILD_STANDALONE` build split resolves
  it. Claude's final suggestion to retain webpack is rejected by exact runtime evidence: deployment
  `dpl_5m4jFtxHqumHAnyiAkD8dxkHBwwf` used `next build --webpack`, reached
  `onBuildComplete`, emitted zero outputs, and failed identically. Webpack is not the fix and should
  not remain as an unexplained divergence.

LOW

- No findings.

### Open Questions / Assumptions

- Only the third Vercel preview can prove the adapter emits deployable output with standalone
  disabled. Merge remains blocked until that preview passes.
- `npm run build` is the self-hosted contract and must keep producing the server consumed by
  `npm start` and the web Dockerfile. `npm run build:vercel` deliberately delegates output
  packaging to Vercel.

### Recommended Tests / Validation

- Re-run focused contracts three times, frontend/browser checks, audits, and the Docker build on
  the final explicit-mode tree.
- Inspect the third preview's output count and require Vercel `READY`.

### Rollout Notes

- No production deployment is initiated by this preview fix.
- Formal disposition: no unresolved local finding; external preview proof is the remaining merge
  condition.
- Final explicit-mode gates passed: release contracts `8 passed` three consecutive times; Ruff;
  TypeScript; ESLint; `51` Vitest tests; critical Playwright `3 passed`; clean production npm
  audit; no all-dependency critical finding; self-hosted and Vercel-mode Next builds; and web image
  `sha256:87a2b764bb737dc66f8f88f6cb283694a07ff6d2d19a57f5844b416776a90b3a`.
