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
