# OpenAPI Migration Domains

## Planning (2026-05-16 15:13:01)

Auggie semantic search was attempted first and returned HTTP 429. This plan is based on direct file inspection and exact-string searches of `AGENTS.md`, `apps/web/AGENTS.md`, `docs/OPENAPI_CONTRACTS.md`, `apps/web/src/lib/api.ts`, `apps/web/src/lib/hooks.ts`, `apps/web/tests/unit/api.test.ts`, `apps/web/tests/unit/generated-api-types.test.ts`, and `apps/web/src/lib/generated/api-types.ts`.

### Plan Draft A - Domain Alias Migration

Overview: Replace remaining manual frontend facade types in `apps/web/src/lib/api.ts` with generated `components`/`paths` aliases, following the requested domain order. Keep all wrapper function names and call signatures stable so hooks/pages do not change.

Files to change:
- `apps/web/src/lib/api.ts`: Replace manual response/request type literals for runs/dashboard, billing/payment, admin/support, storage/webhooks, and auth/session.
- `apps/web/tests/unit/api.test.ts`: Add wrapper tests for migrated domains and assert manual type literals are gone.
- `apps/web/tests/unit/generated-api-types.test.ts`: Add compile-time assignments covering all newly migrated domains.
- `docs/OPENAPI_CONTRACTS.md`: Update adopted domain list.

Implementation steps:
1. Add/stub unit/type tests for the migrated domains.
2. Run `cd apps/web && npm run test:unit -- api.test.ts generated-api-types.test.ts` and confirm RED from missing aliases/coverage expectations.
3. Replace manual exported type literals with generated aliases and endpoint request/response helper types.
4. Refactor minimally if TypeScript exposes exact optional/default differences.
5. Run `npm run test:unit`, `npm run typecheck`, and focused OpenAPI contract checks.

Functions/types:
- `fetchRuns`, `fetchDashboardSummary`: Return generated run/dashboard response types while preserving URLs and defaults.
- `fetchBillingRecords`, `fetchBillingPlans`, billing mutation wrappers: Use generated request/response contracts with existing wrapper defaults.
- `fetchAdminSnapshot`, `fetchAuditLog`, `fetchSupportTenants`, `fetchSupportSummary`: Use generated admin/support contracts without changing query parameter behavior.
- `fetchTenantStorageSettings`, storage mutation wrappers, OAuth/folder wrappers: Use generated storage contracts and keep wrapper inputs stable.
- `register`, `login`, `acceptInvite`, password/email/MFA/session wrappers: Use generated auth/session contracts and keep public helper signatures stable.
- `fetchWebhooks`, `createWebhook`, `deleteWebhook`: Use generated webhook contracts and preserve delete void behavior.

Test coverage:
- `api.test.ts::uses generated OpenAPI types for every migrated frontend domain`: detects leftover manual type declarations.
- `api.test.ts::builds run and dashboard requests with generated response shapes`: wrapper behavior.
- `api.test.ts::builds billing requests with generated payload defaults`: billing wrapper stability.
- `api.test.ts::builds admin support storage and webhook requests`: admin/storage wrapper URLs and payloads.
- `api.test.ts::builds auth session requests`: auth/session wrapper URLs and payloads.
- `generated-api-types.test.ts::covers all migrated frontend domains`: compile-time assignability.

Decision completeness:
- Goal: Finish generated OpenAPI type adoption for the requested frontend domains.
- Non-goals: No generated artifact edits, backend schema changes, endpoint behavior changes, route renames, or page redesigns.
- Success criteria: No manual facade type literals remain for the requested domains; wrappers keep their existing names/signatures; unit/type gates pass.
- Public interfaces: TypeScript exported wrapper types in `apps/web/src/lib/api.ts` are preserved by name; runtime API endpoints are unchanged.
- Edge cases/failure modes: Generated schema may model some nested cost objects as `Record<string, unknown>`; fail closed at typecheck by aliasing the generated contract instead of hand-narrowing. Wrapper defaults remain local where callers depend on them.
- Rollout/monitoring: Frontend type-only migration; backout is reverting this branch. Watch typecheck and unit tests in CI.
- Acceptance checks: `cd apps/web && npm run test:unit -- api.test.ts generated-api-types.test.ts`, `cd apps/web && npm run typecheck`, `cd apps/web && npm run check:api-types`.

Dependencies: Existing generated OpenAPI files and installed web dependencies.

Validation: Focused unit tests, full unit test suite if needed, typecheck, and OpenAPI drift check.

Wiring verification:

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `api.ts` exported wrapper types | Existing pages/hooks import from `@/lib/api` | `apps/web/src/lib/hooks.ts` and page imports | OpenAPI `components`/`paths`, no DB |
| Unit contract tests | Vitest | `apps/web/vitest.config.ts` | OpenAPI generated types, no DB |

Cross-language schema verification: No DB migration or table/column references are changed.

Checklist:
- No open decisions remain.
- Public TypeScript wrappers remain named consistently.
- Every domain behavior change has at least one focused test.
- Validation commands are specific to frontend contract migration.
- Wiring table covers touched frontend type and test components.
- Rollout/backout is branch revert; no deployment flags required.

### Plan Draft B - Helper Type Layer

Overview: Introduce local generic helper aliases such as `JsonResponse<Path, Method, Status>` and `JsonRequest<Path, Method>` first, then migrate each domain through those helpers. Keep wrapper names stable and centralize generated path lookups.

Files to change:
- `apps/web/src/lib/api.ts`: Add generic helper aliases and migrate domain types through helpers.
- `apps/web/tests/unit/api.test.ts`: Same behavior-focused wrapper tests.
- `apps/web/tests/unit/generated-api-types.test.ts`: Same generated assignability tests.
- `docs/OPENAPI_CONTRACTS.md`: Same adopted domain update.

Implementation steps:
1. Add tests that require full-domain migration.
2. Add generic OpenAPI helper type aliases.
3. Convert domain response/request exports to helper aliases.
4. Keep wrapper bodies unchanged except type parameters where required.
5. Run focused unit tests, typecheck, and contract drift check.

Test coverage: Same test names and behaviors as Draft A.

Decision completeness:
- Goal/non-goals/success criteria/public interfaces match Draft A.
- Edge cases/failure modes: Helper aliases can obscure exact generated path names when errors occur; fail closed via typecheck.
- Rollout/monitoring: Same type-only branch rollout.
- Acceptance checks: Same commands as Draft A.

Dependencies: Same as Draft A.

Validation: Same as Draft A.

Wiring verification:

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| OpenAPI helper aliases | Type exports consumed by `api.ts` wrappers | Inline in `apps/web/src/lib/api.ts` | OpenAPI `components`/`paths`, no DB |
| Unit contract tests | Vitest | `apps/web/vitest.config.ts` | OpenAPI generated types, no DB |

Cross-language schema verification: No DB migration or table/column references are changed.

Checklist: Same as Draft A.

### Comparative Analysis

Draft A is more direct and matches the existing project/docs pattern, where early migrated domains use explicit `components["schemas"]` and `paths[...]` aliases. It produces clearer type errors at the exact endpoint/schema being migrated.

Draft B reduces repeated syntax, but it adds a generic abstraction for a one-file migration and can make failures harder to trace. It is useful only if many future files will consume raw generated path helpers.

Both plans keep wrappers stable, avoid backend/schema edits, and use tests-first coverage. Draft A has fewer moving parts and better matches the existing code.

### Unified Execution Plan

Use Draft A. Add failing tests first, migrate explicit exported aliases domain by domain in the requested order, update OpenAPI contract docs, then run focused and broader frontend validation.

Execution order:
1. Tests RED: update `api.test.ts` and `generated-api-types.test.ts` for runs/dashboard, billing/payment, admin/support, storage/webhooks, auth/session.
2. Implementation GREEN: replace manual type literals in `api.ts` with generated `components`/`paths` aliases while preserving wrapper function names, parameters, defaults, URLs, and return types.
3. Docs: update `docs/OPENAPI_CONTRACTS.md` adopted frontend domains.
4. Gates: run focused unit tests, `npm run typecheck`, `npm run check:api-types`; then run `g-check`.
5. Submission: package with Graphite, submit PR, verify checks, merge, and sync local.

Acceptance checks:
- `cd apps/web && npm run test:unit -- api.test.ts generated-api-types.test.ts`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run check:api-types`

## Implementation Summary (2026-05-16 15:28:00)

Goal: Finish OpenAPI type adoption for runs/dashboard, billing/payment, admin/support, storage/webhooks, and auth/session while preserving frontend wrapper functions.

What changed:
- `apps/api/src/egp_api/routes/admin/schemas.py`: Added typed nested support cost summary response models.
- `apps/api/src/egp_api/routes/dashboard.py`: Reused typed support cost summary schema for dashboard `cost_summary`.
- `apps/web/src/lib/generated/openapi.json` and `apps/web/src/lib/generated/api-types.ts`: Regenerated from FastAPI OpenAPI output.
- `apps/web/src/lib/api.ts`: Replaced remaining manual response/request facade types for the requested domains with generated `components`/`paths` aliases, keeping wrapper function names and runtime payload defaults stable.
- `apps/web/tests/unit/api.test.ts`: Added wrapper stability tests and migration source guard.
- `apps/web/tests/unit/generated-api-types.test.ts`: Added compile-time endpoint assignability coverage for all migrated domains.
- `docs/OPENAPI_CONTRACTS.md`: Updated adopted frontend domain list.

TDD evidence:
- RED: `cd apps/web && npm run test:unit -- api.test.ts generated-api-types.test.ts` failed because `src/lib/api.ts` still contained manual declarations such as `export type AuthenticatedUser = {`.
- GREEN: `cd apps/web && npm run test:unit -- api.test.ts generated-api-types.test.ts` passed with 14 tests after generated aliases and schema tightening.

Tests run:
- `cd apps/web && npm run test:unit -- api.test.ts generated-api-types.test.ts` - pass.
- `cd apps/web && npm run typecheck` - pass.
- `cd apps/web && npm run check:api-types` - pass.
- `cd apps/web && npm run test:unit` - pass, 19 tests.
- `cd apps/web && npm run lint` - pass.
- `cd apps/web && npm run build` - pass.
- `./.venv/bin/ruff check apps/api/src/egp_api/routes/dashboard.py apps/api/src/egp_api/routes/admin/schemas.py apps/api/src/egp_api/routes/admin/serializers.py` - pass.
- `./.venv/bin/python -m compileall apps/api/src` - pass.
- `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q` - pass, 46 tests.

Wiring verification:
- `DashboardSummaryResponse.cost_summary` now emits a generated `SupportCostSummaryResponse` schema from `apps/api/src/egp_api/routes/dashboard.py`.
- Admin support summary still serializes through `serialize_support_cost_summary()` into the same typed schema.
- Frontend pages/hooks remain wired through existing `apps/web/src/lib/api.ts` wrappers and `apps/web/src/lib/hooks.ts`; no import or function name changes were required.

Behavior changes and risk notes:
- Runtime JSON is unchanged; this is schema/type precision plus frontend facade migration.
- Wrapper input types intentionally keep caller-compatible widenings for string-valued UI state, including admin roles/statuses, billing transitions, and webhook notification types.
- Fail closed at typecheck and OpenAPI drift checks; no DB or tenant-scoping behavior changed.

Follow-ups / known gaps:
- None identified for this migration slice.

## Review (2026-05-16 15:27:35 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `git diff` for API schema/dashboard/docs, `apps/web/src/lib/api.ts`, and frontend unit tests; `cd apps/web && npm run test:unit -- api.test.ts generated-api-types.test.ts`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run check:api-types`; `cd apps/web && npm run test:unit`; `cd apps/web && npm run lint`; `cd apps/web && npm run build`; `./.venv/bin/ruff check apps/api/src/egp_api/routes/dashboard.py apps/api/src/egp_api/routes/admin/schemas.py apps/api/src/egp_api/routes/admin/serializers.py`; `./.venv/bin/python -m compileall apps/api/src`; `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py tests/phase4/test_admin_api.py -q`

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
- Assumption: The dashboard route importing `SupportCostSummaryResponse` from admin schemas is acceptable because it only shares response model definitions and does not introduce route registration side effects.
- Assumption: Wrapper input types should remain permissive for existing string-backed UI state even where generated schemas expose enum unions.

### Recommended Tests / Validation
- Already run: focused frontend unit tests, full frontend unit tests, frontend typecheck, OpenAPI drift check, lint, production build, API ruff/compileall, and targeted dashboard/admin API pytest coverage.

### Rollout Notes
- Runtime JSON shape is unchanged; the deployment-visible change is a more precise OpenAPI schema for cost summary objects.
- Backout is reverting this branch if downstream generated-type consumers expose an unexpected contract mismatch.

## Submission / Merge Status (2026-05-16 15:31:44 +07)

- Created Graphite branch: `05-16-feat_web_finish_openapi_domain_migration`.
- Created PR: https://github.com/SubhajL/egp/pull/92.
- PR target: `main`.
- Merge attempt with `gh pr merge 92 --merge --delete-branch=false` was blocked by base branch policy because required GitHub checks are failing.
- Reran failed CI workflows once. The rerun failed the same way: every job completed in 2-3 seconds with no recorded job steps and `runner_id: 0`, so no actionable code/test log was available.
- Enabled GitHub auto-merge with merge method `MERGE`; PR remains open and blocked until GitHub checks can pass or an administrator resolves the CI infrastructure failure.
- Local sync to merged `main` could not be completed because PR #92 is not merged.
