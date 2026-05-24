# Coding Log: Tenant Admission Control

## Planning (2026-05-24 08:45:58)

Auggie semantic search was attempted first and returned HTTP 429, so this plan is based on direct file inspection plus exact-string searches. Inspected files included `AGENTS.md`, `apps/api/AGENTS.md`, `apps/web/AGENTS.md`, `packages/db/AGENTS.md`, `apps/api/src/egp_api/services/rules_service.py`, `apps/api/src/egp_api/services/entitlement_service.py`, `apps/api/src/egp_api/routes/rules.py`, `apps/api/src/egp_api/bootstrap/services.py`, `packages/db/src/egp_db/repositories/run_repo.py`, `packages/db/src/egp_db/repositories/discovery_job_repo.py`, `packages/db/src/egp_db/repositories/billing_schema.py`, `packages/db/src/migrations`, `tests/phase2/test_rules_api.py`, `apps/web/src/lib/api.ts`, and `apps/web/src/app/(app)/projects/page.tsx`.

### Plan Draft A

Overview: Add a dedicated tenant entitlement caps table and repository, then make `TenantEntitlementService.check_runs_admission()` enforce tenant-scoped concurrent run and queued keyword limits before `RulesService.queue_active_discovery_jobs()` inserts outbox rows. The API returns a structured 429 for denied manual recrawls, and the projects page treats that state as queued rather than as a generic failure.

Files to change:
- `packages/db/src/migrations/022_tenant_concurrent_caps.sql`: create `tenant_entitlements` with `max_concurrent_runs` default 1 and `max_queued_keywords` default 20.
- `packages/db/src/egp_db/repositories/tenant_entitlement_repo.py`: read override caps, returning safe defaults when no row exists.
- `packages/db/src/egp_db/repositories/run_repo.py`: count tenant-scoped queued/running runs.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: count tenant-scoped pending discovery jobs.
- `apps/api/src/egp_api/services/entitlement_service.py`: define admission result/error and `check_runs_admission()`.
- `apps/api/src/egp_api/services/rules_service.py`: call admission before outbox insert.
- `apps/api/src/egp_api/bootstrap/repositories.py` and `apps/api/src/egp_api/bootstrap/services.py`: wire repository dependencies.
- `apps/api/src/egp_api/routes/rules.py`: map admission denial to structured HTTP 429.
- `apps/web/src/lib/api.ts` and `apps/web/src/app/(app)/projects/page.tsx`: localize the admission code and show a queued badge.
- `tests/phase2/test_rules_api.py`: API coverage for running-run denial and success after completion.

Implementation steps:
1. Add failing API tests for manual recrawl admission: running run returns 429, finished run allows 202, denial inserts no outbox rows.
2. Add optional queued-keyword cap coverage with a low tenant override.
3. Implement DB table/repository and repository count helpers.
4. Wire `TenantEntitlementService` to run, outbox, and cap repositories.
5. Update API route error serialization and web recrawl UI handling.
6. Regenerate OpenAPI/types if the route schema changes.
7. Run focused pytest, compileall/ruff for touched Python, and web typecheck/unit checks.

Test coverage:
- `test_manual_recrawl_returns_429_when_tenant_run_cap_is_full`: denies while a run is queued/running.
- `test_manual_recrawl_succeeds_after_inflight_run_completes`: same tenant succeeds once run finishes.
- `test_manual_recrawl_respects_queued_keyword_cap`: prevents outbox insertion over cap.

Decision completeness:
- Goal: enforce tenant admission control for manual discovery recrawls.
- Non-goals: no worker concurrency changes, no customer-facing cap management UI, no Graphite stack.
- Success criteria: 429 denial with `queued -- previous run still in progress`, no outbox insert on denial, 202 after completion, generated API types current.
- Public interfaces: new `tenant_entitlements` table; `POST /v1/rules/recrawl` can return 429 with `code`, `detail`, and cap counters.
- Edge cases: missing entitlement row uses defaults; missing repository wiring fails closed; queued keyword overflow denies before insert; tenant scoping remains explicit.
- Rollout: migration is additive and defaults existing tenants to 1 concurrent run / 20 queued keywords. Backout is to stop API deploy or raise caps manually.
- Acceptance checks: focused pytest for rules, compileall for touched Python, ruff for touched packages/apps, web unit/typecheck.

Dependencies: existing SQLAlchemy shared metadata and FastAPI route patterns; frontend generated OpenAPI pipeline.

Validation: API tests confirm behavior; generated type checks catch contract drift; UI tests/typecheck validate the badge flow.

Wiring verification:

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `tenant_entitlement_repo.py` | `TenantEntitlementService.check_runs_admission()` | `build_repository_bundle()` creates repository | `tenant_entitlements` |
| `check_runs_admission()` | `RulesService.queue_active_discovery_jobs()` | `configure_services()` injects repositories | `crawl_runs`, `discovery_jobs`, `tenant_entitlements` |
| 429 response model | `POST /v1/rules/recrawl` | `apps/api/src/egp_api/routes/rules.py` router included by middleware | N/A |
| queued UI badge | projects recrawl catch path | `apps/web/src/app/(app)/projects/page.tsx` | N/A |

### Plan Draft B

Overview: Avoid a new repository and store caps as nullable columns on `tenants` or `tenant_settings`, then query them through `SqlAdminRepository`. This minimizes new repository files but mixes operational admission limits with admin tenant settings.

Files to change:
- `packages/db/src/migrations/022_tenant_concurrent_caps.sql`: alter `tenant_settings` or `tenants` with cap columns.
- `packages/db/src/egp_db/repositories/admin_repo.py`: expose cap fields.
- Same API route, rules service, entitlement service, run/outbox count helpers, web UI, and tests as Draft A.

Implementation steps:
1. Add failing API tests around manual recrawl denial and post-completion success.
2. Extend existing admin repository record and schema to expose cap values.
3. Add `check_runs_admission()` and route/UI wiring.
4. Run same focused gates.

Test coverage:
- Same tests as Draft A, plus an admin repository default/override test if cap columns live in settings.

Decision completeness:
- Goal and public API behavior match Draft A.
- Non-goals match Draft A.
- Public interfaces differ: columns are added to an existing table instead of a dedicated cap table.
- Edge cases: missing `tenant_settings` would need synthetic defaults.
- Rollout/backout: additive columns are easy, but cap ownership is less clear.

Dependencies: existing `SqlAdminRepository` settings path.

Validation and wiring verification are otherwise equivalent.

### Comparative Analysis

Draft A better matches the requested `tenant_entitlements` surface, keeps operational caps separate from profile and admin settings, and makes future support overrides straightforward. Draft B is smaller, but it conflicts with the requested table name and would broaden the admin repository with unrelated runtime admission logic.

Both plans preserve tenant scoping and use additive migration semantics. Draft A has a few more moving parts, but those parts map directly to the rollout requirement and keep runtime admission checks explicit.

### Unified Execution Plan

Use Draft A. Implement a small DB repository for `tenant_entitlements`, add run/outbox count helpers, and wire them into `TenantEntitlementService.check_runs_admission()`. `RulesService.queue_active_discovery_jobs()` will perform normal active subscription and keyword checks, build the pending active job list, call admission before any outbox insert, then proceed with current idempotent enqueue behavior.

TDD sequence:
1. Add RED API tests in `tests/phase2/test_rules_api.py`.
2. Run the specific tests and confirm failures are missing admission behavior/schema.
3. Implement migration, repository, service, and route changes.
4. Add web queued-badge handling and regenerate API types if needed.
5. Run the focused tests and quality gates.
6. Perform QCHECK/g-check review, fix findings, then submit and land the PR.

Function outline:
- `SqlTenantEntitlementRepository.get_run_admission_caps()`: return override caps or defaults for a tenant.
- `SqlRunRepository.count_active_runs()`: count queued/running runs scoped by tenant.
- `SqlDiscoveryJobRepository.count_pending_discovery_jobs()`: count pending outbox rows scoped by tenant.
- `TenantEntitlementService.check_runs_admission()`: deny when active runs meet cap or queued keyword demand exceeds cap.
- `RulesService.queue_active_discovery_jobs()`: call admission after active keywords are resolved and before outbox insertion.
- `recrawl_active_keywords()`: translate admission denial into HTTP 429.

Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py -q`
- `./.venv/bin/python -m compileall apps/api/src packages/db/src`
- `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase2/test_rules_api.py`
- `(cd apps/web && npm run generate:api-types && npm run test:unit && npm run typecheck)`

Wiring table:

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Migration `022_tenant_concurrent_caps.sql` | migration runner | filename-sorted migration directory | `tenant_entitlements` |
| `SqlTenantEntitlementRepository` | `TenantEntitlementService.check_runs_admission()` | `RepositoryBundle.tenant_entitlement_repository` | `tenant_entitlements` |
| `count_active_runs()` | admission service | `SqlRunRepository` already in bundle | `crawl_runs.status IN ('queued','running')` |
| `count_pending_discovery_jobs()` | admission service | `SqlDiscoveryJobRepository` already in bundle | `discovery_jobs.job_status='pending'` |
| 429 schema | `POST /v1/rules/recrawl` | rules router included in HTTP pipeline | N/A |
| queued badge | projects manual recrawl catch path | Next.js route component import | N/A |

## Implementation Summary (2026-05-24 08:59:16 +07)

Goal: implement PR-08 tenant admission control through local validation.

What changed:
- `packages/db/src/migrations/022_tenant_concurrent_caps.sql`: added the additive `tenant_entitlements` table with `max_concurrent_runs` and `max_queued_keywords` defaults.
- `packages/db/src/egp_db/repositories/tenant_entitlement_repo.py`: added tenant cap defaults, lookup, and override upsert support.
- `packages/db/src/egp_db/repositories/run_repo.py`: added tenant-scoped active run counting for queued/running runs.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: added tenant-scoped pending outbox counting.
- `apps/api/src/egp_api/services/entitlement_service.py`: added run admission snapshots/errors and cap enforcement.
- `apps/api/src/egp_api/services/rules_service.py`: checks admission after resolving active keywords and before outbox insertion.
- `apps/api/src/egp_api/routes/rules.py`: returns structured HTTP 429 admission payloads.
- `apps/api/src/egp_api/bootstrap/repositories.py` and `apps/api/src/egp_api/bootstrap/services.py`: wire the new repository and dependencies.
- `apps/web/src/lib/api.ts`, generated OpenAPI/types, and `apps/web/src/app/(app)/projects/page.tsx`: localize admission denials and render them with the queued run badge.
- `tests/phase2/test_rules_api.py`: added manual recrawl admission tests for concurrent run denial, post-finish success, and queued keyword cap denial before insert.

TDD evidence:
- RED: `/Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase2/test_rules_api.py -q` failed with the second manual recrawl returning `202` instead of `429`, and `tenant_entitlements` missing.
- GREEN: `PYTHONPATH=/Users/subhajlimanond/dev/egp-pr08/apps/api/src:/Users/subhajlimanond/dev/egp-pr08/apps/worker/src:/Users/subhajlimanond/dev/egp-pr08/packages/db/src:/Users/subhajlimanond/dev/egp-pr08/packages/crawler-core/src:/Users/subhajlimanond/dev/egp-pr08/packages/domain-core/src:/Users/subhajlimanond/dev/egp-pr08/packages/shared-types/src:/Users/subhajlimanond/dev/egp-pr08/packages/notification-core/src:/Users/subhajlimanond/dev/egp-pr08/packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase2/test_rules_api.py -q` passed with 14 tests.

Tests and checks run:
- `PYTHONPATH=... /Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps/api/src packages/db/src` passed.
- `PYTHONPATH=... /Users/subhajlimanond/dev/egp/.venv/bin/ruff check apps/api/src packages/db/src tests/phase2/test_rules_api.py` passed.
- `PYTHONPATH=... /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase2/test_rules_api.py -q` passed.
- `PYTHONPATH=... PYTHON=/Users/subhajlimanond/dev/egp/.venv/bin/python npm run generate:api-types` passed.
- `PYTHONPATH=... PYTHON=/Users/subhajlimanond/dev/egp/.venv/bin/python npm run check:api-types` passed.
- `npm run test:unit` passed.
- `npm run typecheck` passed.
- `npm run lint` passed.
- `npm run build` passed.
- `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --check` passed.

Migration validation gap:
- `docker compose -f docker-compose-localdev.yml up -d postgres` could not run because the Docker daemon was unavailable at `/Users/subhajlimanond/.orbstack/run/docker.sock`.

Wiring verification:
- Runtime API dependency path is `build_repository_bundle()` -> `RepositoryBundle.tenant_entitlement_repository` -> `configure_services()` -> `TenantEntitlementService`.
- Admission entry point is `RulesService.queue_active_discovery_jobs()` before any manual recrawl outbox insert.
- Route mapping is `POST /v1/rules/recrawl`, returning 429 via `ManualRecrawlQueuedResponse`.
- Frontend display path is `ProjectsPage.handleRecrawl()` catch branch with `StatusBadge state="queued" variant="run"`.

Risk notes:
- Admission is tenant-scoped through tenant IDs on all repository counts.
- Missing cap rows default to 1 concurrent run and 20 queued keywords.
- Missing run repository wiring fails closed by treating the tenant as at cap.

## Review (2026-05-24 08:59:16 +07) - Working Tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-pr08`
- Branch: `feat/tenant-admission-control`
- Scope: working tree
- Commands Run: `git status --porcelain=v1`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `nl -ba` reads, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --check`, focused pytest/ruff/compileall/web checks listed above. Auggie review retrieval was attempted and returned HTTP 429, so review used direct file inspection.

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
- Assumption: support/admin override of `tenant_entitlements` can be done manually in DB for this PR; no cap-management UI was requested.
- Local Postgres DDL execution remains unverified because Docker is not running in this environment.

### Recommended Tests / Validation
- Run the migration runner against local or staging Postgres before deploy.
- Re-run the API and web checks in CI after PR creation.

### Rollout Notes
- Migration is additive. Default behavior is conservative: tenants without rows get one concurrent run and twenty queued keywords.
- Watch 429 rate on manual recrawl and `egp_discovery_inflight_runs` during the 72h observation window.
