# Task 4.7 Plan

## Planning Context

- Task: `4.7 Add cost observability and support tooling`
- Auggie semantic search used first. Direct inspection supplemented the plan.
- Inspected files:
  - `AGENTS.md`
  - `apps/api/AGENTS.md`
  - `apps/web/AGENTS.md`
  - `packages/AGENTS.md`
  - `packages/db/AGENTS.md`
  - `apps/api/src/egp_api/auth.py`
  - `apps/api/src/egp_api/main.py`
  - `apps/api/src/egp_api/routes/admin.py`
  - `apps/api/src/egp_api/routes/billing.py`
  - `apps/api/src/egp_api/routes/dashboard.py`
  - `apps/api/src/egp_api/services/admin_service.py`
  - `apps/api/src/egp_api/services/audit_service.py`
  - `apps/api/src/egp_api/services/billing_service.py`
  - `apps/api/src/egp_api/services/dashboard_service.py`
  - `packages/db/src/egp_db/repositories/admin_repo.py`
  - `packages/db/src/egp_db/repositories/billing_repo.py`
  - `packages/db/src/egp_db/repositories/document_repo.py`
  - `packages/db/src/egp_db/repositories/notification_repo.py`
  - `packages/db/src/egp_db/repositories/run_repo.py`
  - `apps/web/src/lib/api.ts`
  - `apps/web/src/lib/hooks.ts`
  - `apps/web/src/app/(app)/dashboard/page.tsx`
  - `apps/web/src/app/(app)/admin/page.tsx`
  - `tests/phase2/test_dashboard_api.py`
  - `tests/phase4/test_admin_api.py`

## Plan Draft A

### Overview

Implement task 4.7 as two connected operator surfaces. First, extend the tenant dashboard with cost observability signals for crawl, storage, notifications, and payments. Second, add a support tooling layer that lets internal `support` operators search tenants, inspect a tenant-scoped triage summary, and then reuse the existing admin/billing/webhook tooling with explicit tenant context instead of introducing new unsafe mutation APIs.

This draft keeps the database schema unchanged. The implementation stays in the control plane and repository layer, reusing existing tables for cost drivers and triage indicators.

### Files to Change

- `packages/db/src/egp_db/repositories/support_repo.py`: new cross-domain support/cost queries.
- `apps/api/src/egp_api/services/support_service.py`: orchestration for tenant search and support summary.
- `apps/api/src/egp_api/auth.py`: add `support` role helpers and controlled cross-tenant access.
- `apps/api/src/egp_api/routes/admin.py`: add support search/summary endpoints.
- `apps/api/src/egp_api/services/dashboard_service.py`: add cost summary into dashboard response.
- `apps/api/src/egp_api/routes/dashboard.py`: serialize new dashboard cost payload.
- `apps/api/src/egp_api/main.py`: instantiate and register `SupportService`, wire updated `DashboardService`.
- `apps/web/src/lib/api.ts`: add support search/summary types and tenant-aware admin/dashboard fetch helpers.
- `apps/web/src/lib/hooks.ts`: add support hooks.
- `apps/web/src/app/(app)/dashboard/page.tsx`: render cost observability cards/report rows.
- `apps/web/src/app/(app)/admin/page.tsx`: add support lookup tab and selected-tenant support summary.
- `tests/phase2/test_dashboard_api.py`: verify cost observability response.
- `tests/phase4/test_admin_api.py`: verify support search, support summary, and support-role cross-tenant access.

### Implementation Steps

TDD sequence:
1. Add/stub API tests for dashboard cost summary and admin support lookup/summary.
2. Run focused pytest commands and confirm failures for missing response fields/routes/auth behavior.
3. Implement the smallest repository + service + route changes to satisfy the tests.
4. Add the web API/hook/page changes against the stabilized contracts.
5. Run relevant fast gates: targeted pytest, `ruff`, `compileall`, `apps/web` typecheck/build.

Functions and behavior:
- `SqlSupportRepository.search_tenants(query, limit)`: search tenants by name, slug, support/billing email, and user email; always bounded.
- `SqlSupportRepository.get_support_summary(tenant_id)`: aggregate cost signals and triage indicators from existing tables.
- `SupportService.search_tenants(...)`: validate support query inputs and return sanitized matches.
- `SupportService.get_summary(tenant_id)`: compose tenant record plus triage and cost report.
- `request_has_support_role(request)`: identify internal support JWTs.
- `resolve_request_tenant_id(...)`: allow cross-tenant resolution only for support role and only when an explicit `tenant_id` is supplied.
- `DashboardService.get_summary(...)`: include a cost summary built from support repository data.

Expected behavior and edge cases:
- Empty support search returns an empty list, not all tenants.
- Support summary fails closed with `404` for unknown tenant IDs.
- Tenant admins remain tenant-scoped; only `support` can cross tenant boundaries.
- Cost signals use existing counts/bytes/amounts; no writes or backfills are required.
- Missing activity in any category returns zeroed metrics.

### Test Coverage

- `tests/phase2/test_dashboard_api.py::test_dashboard_summary_includes_cost_observability`
  - Returns crawl/storage/notification/payment cost signals.
- `tests/phase4/test_admin_api.py::test_admin_support_search_matches_name_slug_and_contact_email`
  - Finds tenants through supported lookup fields.
- `tests/phase4/test_admin_api.py::test_admin_support_summary_returns_triage_and_cost_report`
  - Exposes tenant-safe support summary payload.
- `tests/phase4/test_admin_api.py::test_support_role_can_access_selected_tenant_context`
  - Support role may cross tenant with explicit target.
- `tests/phase4/test_admin_api.py::test_non_support_roles_cannot_use_support_lookup`
  - Tenant admins cannot use global support endpoints.

### Decision Completeness

- Goal:
  - Expose usable cost observability and support tooling without breaking tenant isolation.
- Non-goals:
  - No new billing engine.
  - No manual data repair endpoints.
  - No new database tables or background jobs.
- Success criteria:
  - Dashboard response includes cost report categories for a tenant.
  - Support operators can search tenants and open a triage summary.
  - Existing admin-style actions can target the selected tenant when performed by support role.
  - Tests cover cross-tenant safety boundaries.
- Public interfaces:
  - `GET /v1/dashboard/summary` adds `cost_summary`.
  - `GET /v1/admin/support/tenants`
  - `GET /v1/admin/support/tenants/{tenant_id}/summary`
  - Auth support for JWT `role=support`.
- Edge cases / failure modes:
  - Unknown tenant -> `404`.
  - Blank query -> empty result set.
  - Non-support cross-tenant request -> `403`.
  - Sparse operational data -> zero-value summaries, not errors.
  - Fail closed for auth; fail open only on zero-activity reporting.
- Rollout & monitoring:
  - No flag required; additive read APIs only.
  - Watch for `403 tenant mismatch` regressions and any dashboard serialization errors.
  - Backout is route/UI removal because schema is unchanged.
- Acceptance checks:
  - `pytest` targeted dashboard/admin tests pass.
  - Dashboard UI builds with new cost cards.
  - Admin UI typechecks/builds with support tab.

### Dependencies

- Existing tables in `tenants`, `tenant_settings`, `users`, `crawl_runs`, `crawl_tasks`, `documents`, `notifications`, `webhook_deliveries`, `billing_records`, `billing_payment_requests`, `document_diff_reviews`, `audit_log_events`.
- Existing admin, billing, webhook, and dashboard surfaces.

### Validation

- Run focused tests first, then Python lint/compile, then frontend typecheck/build.
- Manually verify the support lookup drives a selected tenant context through the admin page.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `support_repo.py` | `SupportService`, `DashboardService` | imported into `apps/api/src/egp_api/main.py` | `tenants`, `tenant_settings`, `users`, `crawl_runs`, `crawl_tasks`, `documents`, `notifications`, `webhook_deliveries`, `billing_records`, `billing_payment_requests`, `document_diff_reviews`, `audit_log_events` |
| `SupportService` | `/v1/admin/support/*` route handlers | `app.state.support_service` in `apps/api/src/egp_api/main.py` | read-only tables above |
| Dashboard `cost_summary` | `GET /v1/dashboard/summary` | `DashboardService` injected in `apps/api/src/egp_api/main.py`; serialized in `routes/dashboard.py` | same read-only tables above |
| Admin support routes | FastAPI `/v1/admin/support/tenants` and `/v1/admin/support/tenants/{tenant_id}/summary` | `admin_router` already included by `apps/api/src/egp_api/main.py` | N/A |
| Admin support tab | `apps/web/src/app/(app)/admin/page.tsx` | existing app route tree + `src/lib/api.ts` + `src/lib/hooks.ts` | N/A |

### Cross-Language Schema Verification

- Python-only repo paths are authoritative here.
- Verify exact table names before query code:
  - `tenants`
  - `tenant_settings`
  - `users`
  - `crawl_runs`
  - `crawl_tasks`
  - `documents`
  - `notifications`
  - `webhook_deliveries`
  - `billing_records`
  - `billing_payment_requests`
  - `document_diff_reviews`
  - `audit_log_events`

## Plan Draft B

### Overview

Implement task 4.7 by extending the existing `AdminService` and `DashboardService` directly, without introducing a dedicated support repository. This keeps the change set smaller in file count, but it pushes cross-domain SQL into already-broad services and repositories.

The dashboard would gain cost signals, while the admin page would gain a support tab backed by new methods on `AdminService` and `SqlAdminRepository`.

### Files to Change

- `packages/db/src/egp_db/repositories/admin_repo.py`: add tenant search and support summary SQL.
- `apps/api/src/egp_api/services/admin_service.py`: add support lookup/summary orchestration.
- `apps/api/src/egp_api/auth.py`: add `support` role helpers and cross-tenant access.
- `apps/api/src/egp_api/routes/admin.py`: add support endpoints.
- `apps/api/src/egp_api/services/dashboard_service.py`: add cost summary.
- `apps/api/src/egp_api/routes/dashboard.py`: serialize cost summary.
- `apps/api/src/egp_api/main.py`: wire widened `AdminService` constructor if needed.
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/app/(app)/dashboard/page.tsx`
- `apps/web/src/app/(app)/admin/page.tsx`
- `tests/phase2/test_dashboard_api.py`
- `tests/phase4/test_admin_api.py`

### Implementation Steps

TDD sequence:
1. Add dashboard/admin tests for the desired payloads and cross-tenant support role.
2. Run failing tests.
3. Extend `SqlAdminRepository` with joins into billing/run/document/notification tables.
4. Extend `AdminService` and `DashboardService` to expose the new data.
5. Update web contracts and pages, then run focused gates.

Functions and behavior:
- `SqlAdminRepository.search_support_tenants(...)`
- `SqlAdminRepository.get_support_summary(...)`
- `AdminService.search_support_tenants(...)`
- `AdminService.get_support_summary(...)`
- `DashboardService.get_summary(...)` adds cost payload.

Expected behavior and edge cases:
- Same as Draft A, but with more logic embedded in the existing admin module.

### Test Coverage

- Same tests as Draft A.

### Decision Completeness

- Goal:
  - Deliver the same user-facing outcome with fewer new modules.
- Non-goals:
  - Same as Draft A.
- Success criteria:
  - Same as Draft A.
- Public interfaces:
  - Same as Draft A.
- Edge cases / failure modes:
  - Same as Draft A.
- Rollout & monitoring:
  - Same as Draft A.
- Acceptance checks:
  - Same as Draft A.

### Dependencies

- Same existing tables and routes as Draft A.

### Validation

- Same validation commands as Draft A.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Extended `SqlAdminRepository` | `AdminService`, `DashboardService` | `main.py` existing admin repository wiring | cross-domain operational tables |
| Extended `AdminService` | `/v1/admin/support/*` | `app.state.admin_service` | N/A |
| Dashboard `cost_summary` | `GET /v1/dashboard/summary` | existing dashboard wiring | cross-domain operational tables |
| Admin support tab | admin page | existing app route tree | N/A |

### Cross-Language Schema Verification

- Same table verification list as Draft A.

## Comparative Analysis & Synthesis

### Strengths

- Draft A keeps support/cost aggregation in a focused layer. That matches the cross-domain nature of task 4.7 and avoids turning `AdminService` into another monolith.
- Draft B changes fewer top-level concepts and might be slightly faster to wire initially.

### Gaps

- Draft A needs one new repository module and one new service module, so the implementation has slightly more scaffolding.
- Draft B couples tenant search, cost reporting, and support triage to the admin repository, which is already responsible for tenant settings and would become an awkward multi-domain owner.

### Trade-offs

- Draft A optimizes maintainability and future extension for support tooling.
- Draft B optimizes short-term file count, but the cohesion is worse and the review risk is higher.

### Compliance Check

- Both drafts follow repo rules: thin route layer, tenant-scoped queries, no legacy fallback, bounded list endpoints, and additive public interfaces.
- Draft A better follows the “focused module” rule from `packages/AGENTS.md`.

## Unified Execution Plan

### Overview

Implement task 4.7 with a dedicated support/cost reporting layer and no schema migration. The API will gain additive support lookup/summary endpoints and an additive dashboard cost report, while the web app will surface cost observability on the dashboard and a support lookup/triage workflow on the admin page. Existing tenant-scoped admin, billing, webhook, and audit actions will remain the intervention path, with a controlled `support` role permitted to target an explicit tenant.

### Files to Change

- `packages/db/src/egp_db/repositories/support_repo.py`: new bounded tenant search and tenant support summary queries.
- `apps/api/src/egp_api/services/support_service.py`: support lookup/summary orchestration.
- `apps/api/src/egp_api/auth.py`: add `request_has_support_role()` and explicit support-only cross-tenant resolution behavior.
- `apps/api/src/egp_api/routes/admin.py`: add support response models and `GET /v1/admin/support/tenants`, `GET /v1/admin/support/tenants/{tenant_id}/summary`.
- `apps/api/src/egp_api/services/dashboard_service.py`: accept support repository/service dependency and include `cost_summary`.
- `apps/api/src/egp_api/routes/dashboard.py`: serialize `cost_summary`.
- `apps/api/src/egp_api/main.py`: instantiate `SqlSupportRepository`, `SupportService`, and updated `DashboardService`.
- `apps/web/src/lib/api.ts`: new support types/fetchers plus optional `tenant_id` on admin/dashboard fetchers used by support tooling.
- `apps/web/src/lib/hooks.ts`: new support hooks and tenant-aware query keys.
- `apps/web/src/app/(app)/dashboard/page.tsx`: add cost observability cards and top cost-driver section.
- `apps/web/src/app/(app)/admin/page.tsx`: add `Support` tab with search, tenant picker, support summary, and selected-tenant context reuse.
- `tests/phase2/test_dashboard_api.py`: RED/GREEN for cost summary.
- `tests/phase4/test_admin_api.py`: RED/GREEN for support lookup, support summary, and support-only cross-tenant access.

### Implementation Steps

TDD sequence:
1. Add/stub `tests/phase2/test_dashboard_api.py::test_dashboard_summary_includes_cost_observability`.
2. Add/stub `tests/phase4/test_admin_api.py` coverage for support tenant search, support summary, support-role access, and non-support denial.
3. Run:
   - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`
   - Confirm failures are missing fields/routes/auth logic.
4. Implement repository/service/route/auth changes until the focused suite passes.
5. Implement frontend API/hook/page changes against the now-stable response contracts.
6. Run:
   - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`
   - `./.venv/bin/ruff check apps/api packages tests`
   - `./.venv/bin/python -m compileall apps packages`
   - `(cd apps/web && npm run typecheck)`
   - `(cd apps/web && npm run build)`

Functions and 1-3 sentence descriptions:
- `SqlSupportRepository.search_tenants(query: str, limit: int = 20) -> list[...]`
  - Performs bounded support lookup by tenant name, slug, support/billing contact email, and tenant user email. It returns only the minimal identity fields needed to choose a tenant safely.
- `SqlSupportRepository.get_support_summary(tenant_id: str) -> SupportSummary`
  - Aggregates operational triage signals and cost drivers from existing tables. The method remains read-only and tenant-scoped.
- `SupportService.search_tenants(...)`
  - Normalizes queries, rejects unbounded empty search requests, and delegates to the repository.
- `SupportService.get_summary(...)`
  - Loads tenant identity and support snapshot, returning a stable API contract for the admin support tab.
- `request_has_support_role(request: Request) -> bool`
  - Identifies internal support JWTs without widening normal tenant-admin permissions.
- `resolve_request_tenant_id(...)`
  - Continues to enforce tenant match by default, but allows an explicitly supplied target tenant only for support role.
- `DashboardService.get_summary(...)`
  - Adds a cost summary to the existing dashboard payload without changing the route shape beyond additive fields.

Expected behavior and edge cases:
- Search requests with blank or whitespace-only query return `[]`.
- Search results remain bounded to prevent large tenant enumeration.
- Support summary zeros out cost categories when the tenant has no recent activity.
- Cross-tenant access still fails closed for `owner`/`admin`/`viewer`; only `support` can select another tenant.
- Existing admin/billing/webhook routes continue using `resolve_request_tenant_id`, so the new support role automatically reuses those safe intervention paths.

### Test Coverage

- `tests/phase2/test_dashboard_api.py::test_dashboard_summary_includes_cost_observability`
  - Dashboard includes additive cost report fields.
- `tests/phase4/test_admin_api.py::test_admin_support_search_matches_name_slug_and_contact_email`
  - Search matches intended support lookup dimensions.
- `tests/phase4/test_admin_api.py::test_admin_support_summary_returns_triage_and_cost_report`
  - Support summary exposes triage counts and recent issue lists.
- `tests/phase4/test_admin_api.py::test_support_role_can_access_selected_tenant_context`
  - `support` JWT can target another tenant explicitly.
- `tests/phase4/test_admin_api.py::test_non_support_roles_cannot_cross_tenant_or_use_support_lookup`
  - Non-support roles remain isolated.

### Decision Completeness

- Goal:
  - Give operators visibility into cost drivers and enough support tooling to diagnose tenant issues and act through existing safe admin surfaces.
- Non-goals:
  - No migration or backfill.
  - No direct data-edit “break glass” endpoints.
  - No new background jobs, schedulers, or external cost providers.
- Success criteria:
  - Dashboard exposes additive cost summary for crawl/storage/notifications/payments.
  - Support lookup returns targeted tenants through operational identifiers.
  - Support summary shows triage indicators for failed runs, pending reviews, failed webhooks, and billing trouble.
  - Support role can pivot into the selected tenant using existing admin/billing routes.
  - Focused tests and build gates pass.
- Public interfaces:
  - `GET /v1/dashboard/summary` adds `cost_summary`.
  - `GET /v1/admin/support/tenants?query=...&limit=...`
  - `GET /v1/admin/support/tenants/{tenant_id}/summary`
  - Auth contract recognizes JWT `role=support`.
  - `apps/web` admin/dashboard clients accept optional `tenant_id`.
- Edge cases / failure modes:
  - Unknown tenant: `404`.
  - Unauthorized cross-tenant selection: `403`.
  - Missing cost inputs: zero-value category output.
  - Empty search query: no enumeration, returns `[]`.
  - Fail closed on auth and tenant resolution.
- Rollout & monitoring:
  - Additive API/UI only; no migration sequencing.
  - Watch dashboard response serialization, support lookup latency, and any unexpected cross-tenant access attempts.
  - Backout path is code-only revert because persistence is unchanged.
- Acceptance checks:
  - Focused pytest suite passes.
  - `ruff` and `compileall` pass.
  - `apps/web` typecheck/build pass.
  - Manual sanity: support search selects a tenant and the admin page refreshes that tenant’s snapshot/audit/webhook state.

### Dependencies

- Existing repository table definitions in `admin_repo.py`, `billing_repo.py`, `document_repo.py`, `notification_repo.py`, and `run_repo.py`.
- Existing admin/dashboard/webhook/billing pages and React Query helpers.

### Validation

- Backend:
  - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/ruff check apps/api packages tests`
  - `./.venv/bin/python -m compileall apps packages`
- Frontend:
  - `(cd apps/web && npm run typecheck)`
  - `(cd apps/web && npm run build)`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `packages/db/src/egp_db/repositories/support_repo.py` | `SupportService.get_summary()`, `SupportService.search_tenants()`, `DashboardService.get_summary()` | instantiated in `apps/api/src/egp_api/main.py` and passed into services | `tenants`, `tenant_settings`, `users`, `crawl_runs`, `crawl_tasks`, `documents`, `notifications`, `webhook_deliveries`, `billing_records`, `billing_payment_requests`, `document_diff_reviews`, `audit_log_events` |
| `apps/api/src/egp_api/services/support_service.py` | admin support route handlers | `app.state.support_service` in `apps/api/src/egp_api/main.py` | read-only aggregate queries |
| Dashboard `cost_summary` | `GET /v1/dashboard/summary` | `DashboardService` constructed in `apps/api/src/egp_api/main.py`, serialized in `apps/api/src/egp_api/routes/dashboard.py` | same aggregate queries |
| Support search route | `GET /v1/admin/support/tenants` | added to existing `admin_router`; router already included in `apps/api/src/egp_api/main.py` | N/A |
| Support summary route | `GET /v1/admin/support/tenants/{tenant_id}/summary` | added to existing `admin_router`; router already included in `apps/api/src/egp_api/main.py` | N/A |
| Dashboard cost UI | `apps/web/src/app/(app)/dashboard/page.tsx` | existing dashboard route + `useDashboardSummary` + `fetchDashboardSummary` | N/A |
| Admin support UI | `apps/web/src/app/(app)/admin/page.tsx` | existing admin route + new support hooks/fetchers | N/A |

### Cross-Language Schema Verification

- Multi-language verification is not needed here because the operational tables are all Python-defined in this repo.
- Verify exact table names and key columns before implementing queries:
  - `tenants.id`, `tenants.name`, `tenants.slug`
  - `tenant_settings.tenant_id`, `support_email`, `billing_contact_email`
  - `users.tenant_id`, `email`, `role`, `status`
  - `crawl_runs.tenant_id`, `status`, `created_at`, `error_count`
  - `crawl_tasks.run_id`, `status`, `task_type`, `created_at`
  - `documents.tenant_id`, `size_bytes`, `created_at`
  - `notifications.tenant_id`, `channel`, `status`, `created_at`
  - `webhook_deliveries.tenant_id`, `delivery_status`, `last_attempted_at`
  - `billing_records.tenant_id`, `status`, `amount_due`, `created_at`
  - `billing_payment_requests.tenant_id`, `status`, `amount`, `created_at`
  - `document_diff_reviews.tenant_id`, `status`, `created_at`
  - `audit_log_events.tenant_id`, `source`, `occurred_at`


## Implementation Summary (2026-04-05 17:58:43) - task-4-7-cost-observability-support-tooling

### Goal
Add task 4.7 cost observability plus internal support tooling without breaking tenant isolation.

### What Changed
- `packages/db/src/egp_db/repositories/support_repo.py`
  - Added read-only tenant search, cost summary, triage counters, and recent support-issue queries across existing operational tables.
- `apps/api/src/egp_api/services/support_service.py`
  - Added a thin service wrapper for support lookup and summary retrieval.
- `apps/api/src/egp_api/auth.py`
  - Added `support` role helpers and made support cross-tenant resolution opt-in per route instead of global.
- `apps/api/src/egp_api/routes/admin.py`
  - Added `GET /v1/admin/support/tenants` and `GET /v1/admin/support/tenants/{tenant_id}/summary` plus response serializers.
- `apps/api/src/egp_api/routes/billing.py`
  - Enabled support-role tenant override only on billing intervention routes.
- `apps/api/src/egp_api/routes/webhooks.py`
  - Enabled support-role tenant override only on webhook intervention routes.
- `apps/api/src/egp_api/services/dashboard_service.py`
  - Extended dashboard summaries with additive `cost_summary` data.
- `apps/api/src/egp_api/routes/dashboard.py`
  - Serialized dashboard cost observability payloads.
- `apps/api/src/egp_api/main.py`
  - Wired `support_repository`, `support_service`, and the updated `DashboardService` into app state.
- `apps/web/src/lib/api.ts`
  - Added dashboard cost/support DTOs plus tenant-aware admin/dashboard fetch helpers and support fetchers.
- `apps/web/src/lib/hooks.ts`
  - Added tenant-aware query hooks and support lookup/summary hooks.
- `apps/web/src/app/(app)/dashboard/page.tsx`
  - Added a cost observability section with per-category operational drivers.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Added a support tab with tenant search, triage summary, cost report, and selected-tenant context reuse across existing admin tabs.
- `tests/phase2/test_dashboard_api.py`
  - Added dashboard `cost_summary` RED/GREEN coverage.
- `tests/phase4/test_admin_api.py`
  - Added support lookup, support summary, support-role context switching, and non-support boundary coverage.

### TDD Evidence
- Added/changed tests:
  - `tests/phase2/test_dashboard_api.py::test_dashboard_summary_endpoint_returns_repository_backed_metrics`
  - `tests/phase2/test_dashboard_api.py::test_dashboard_summary_endpoint_returns_zero_safe_defaults_for_empty_tenant`
  - `tests/phase4/test_admin_api.py::test_admin_support_search_matches_name_slug_and_contact_email`
  - `tests/phase4/test_admin_api.py::test_admin_support_summary_returns_triage_and_cost_report`
  - `tests/phase4/test_admin_api.py::test_support_role_can_access_selected_tenant_context`
  - `tests/phase4/test_admin_api.py::test_non_support_roles_cannot_cross_tenant_or_use_support_lookup`
  - `tests/phase4/test_admin_api.py::test_support_role_remains_tenant_scoped_on_non_support_routes`
- RED command:
  - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`
- RED failure reason:
  - Missing `cost_summary` in dashboard responses, missing support routes (`404`), and missing support-role access behavior.
- GREEN command:
  - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`
- GREEN result:
  - `13 passed`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`
- `./.venv/bin/ruff check apps/api packages tests`
- `./.venv/bin/python -m compileall apps packages`
- `(cd apps/web && npm run typecheck)`
- `(cd apps/web && npm run build)`

### Wiring Verification Evidence
- `apps/api/src/egp_api/main.py`
  - Instantiates `support_repository` and `support_service` and passes `support_repository` into `DashboardService`.
- `apps/api/src/egp_api/routes/admin.py`
  - Registers support endpoints under the existing `admin_router` already included by the FastAPI app.
- `apps/api/src/egp_api/routes/dashboard.py`
  - Adds additive `cost_summary` serialization for `GET /v1/dashboard/summary`.
- `apps/web/src/lib/api.ts` + `apps/web/src/lib/hooks.ts`
  - Route the new support/admin/dashboard contracts into the web app.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Reuses existing admin/billing/webhook mutation paths by passing the selected tenant ID.

### Behavior Changes And Risk Notes
- Dashboard responses now expose additive cost observability fields for crawl, storage, notifications, and payments.
- Internal `support` role can search tenants and operate cross-tenant only on admin, billing, and webhook routes.
- Non-support routes still fail closed on tenant mismatch, including project reads.
- No schema migration was required; all summaries read from existing tables only.

### Follow-Ups / Known Gaps
- The cost rate card is currently code-defined and heuristic. If the business wants real provider pricing, move those rates to explicit configuration.

## Review (2026-04-05 17:58:43) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: feat/task-4-7-cost-observability-support-tooling
- Scope: working-tree
- Commands Run: `git status --short`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff`, `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`, `./.venv/bin/ruff check apps/api packages tests`, `./.venv/bin/python -m compileall apps packages`, `(cd apps/web && npm run typecheck)`, `(cd apps/web && npm run build)`

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
- Assumed the internal cost model is intentionally heuristic rather than externally billed pricing.
- Assumed support-role cross-tenant access should be limited to admin, billing, and webhook intervention surfaces.

### Recommended Tests / Validation
- Keep the targeted dashboard/admin pytest suite in CI for future auth or response-contract changes.
- If support-role usage expands, add route-level regression tests before widening any additional tenant override surfaces.

### Rollout Notes
- No migration or backfill is required.
- Rollout is additive and fail-closed for tenant resolution outside the explicitly opted-in support surfaces.
