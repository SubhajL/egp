# Coding Log: Generated API Types Adoption

Created: 2026-05-16 11:50:40 +07

Auggie semantic search unavailable: `mcp__auggie_mcp__.codebase_retrieval` returned HTTP 429.
This plan is based on direct file inspection plus exact-string searches.

Inspected files:
- `AGENTS.md`
- `apps/web/AGENTS.md`
- `apps/web/package.json`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/lib/generated/api-types.ts`
- `apps/web/tests/unit/api.test.ts`
- `apps/web/tests/unit/generated-api-types.test.ts`
- `docs/OPENAPI_CONTRACTS.md`

## Plan Draft A - Endpoint Type Aliases In Existing API Facade

### Overview

Migrate the first frontend domains to generated OpenAPI types while preserving the current
`src/lib/api.ts` wrapper surface. Projects, documents, and rules will keep their exported names,
but the source of truth for response, request, and query parameter types will be
`src/lib/generated/api-types.ts`.

### Files to Change

- `apps/web/src/lib/api.ts` - import generated `components` and `paths`, replace manual project,
  document, and rules response/request type declarations with generated type aliases, and keep
  wrapper functions unchanged at call sites.
- `apps/web/tests/unit/api.test.ts` - add focused wrapper tests that prove project/rule requests
  build the same URLs/payloads while returning generated response-shaped data.
- `apps/web/tests/unit/generated-api-types.test.ts` - expand the contract test to assert the first
  migrated domains are type-backed by generated endpoint responses and schemas.
- `docs/OPENAPI_CONTRACTS.md` - document that projects, documents, and rules are the first adopted
  generated-type domains.

### Implementation Steps

TDD sequence:
1. Add type/import and wrapper tests that reference generated project, document, and rules endpoint
   types from the public `api.ts` facade.
2. Run `cd apps/web && npm run test:unit` and confirm failure because the facade still exposes
   manual declarations rather than generated-compatible aliases tested by the new assertions.
3. Replace the manual project/document/rules declarations with generated aliases:
   - `ProjectSummary`, `ProjectAlias`, `ProjectStatusEvent`, `ProjectDetailResponse`,
     `ProjectListResponse`, `ProjectCrawlEvidence`, `ProjectCrawlEvidenceListResponse`
   - `DocumentSummary`, `DocumentListResponse`, `DocumentDownloadLinkResponse`
   - `RuleProfile`, `ClosureRulesSummary`, `NotificationRulesSummary`, `ScheduleRulesSummary`,
     `EntitlementSummary`, `RulesResponse`, `CreateRuleProfileInput`,
     `TriggerManualRecrawlInput`, `TriggerManualRecrawlResponse`
4. Keep `FetchProjectsParams` compatible with existing callers but derive its field types from the
   generated `/v1/projects` query parameters.
5. Run unit tests, typecheck, lint, build, and `npm run check:api-types`.

Function notes:
- `fetchProjects(params)` continues to build `/v1/projects` with current defaults and returns the
  generated project-list response shape.
- `fetchProjectDetail(projectId)` continues to return the generated project-detail response.
- `fetchDocuments(projectId)` and `fetchDocumentDownloadLink(documentId)` return generated document
  response shapes.
- `fetchRules()` and `createRuleProfile(payload)` return generated rules/profile schemas while the
  wrapper keeps caller-friendly optional defaults.

### Test Coverage

- `fetchProjects builds generated contract query` - URL defaults and arrays preserved.
- `fetchProjectDetail returns generated response shape` - detail wrapper typed response.
- `fetchDocuments returns generated document list` - document list wrapper typed response.
- `fetchRules returns generated rules response` - rules wrapper typed response.
- `createRuleProfile sends generated request payload` - wrapper default payload stable.
- `generated API contract exposes migrated domains` - generated schemas cover adopted domains.

### Decision Completeness

- Goal: adopt generated OpenAPI types in real frontend wrapper code for projects, documents, and
  rules without changing UI pages.
- Non-goals: migrate every frontend domain, replace the fetch implementation, introduce a runtime
  OpenAPI client, change backend API schemas, or regenerate artifacts.
- Success criteria: the migrated `api.ts` exports are derived from `components`/`paths`; existing
  hooks/pages compile unchanged; focused wrapper tests and frontend gates pass.
- Public interfaces: no API endpoint, env var, CLI flag, migration, or UI route changes. Public
  TypeScript exports keep their existing names.
- Edge cases / failure modes: generated schemas may mark defaulted request fields as required, so
  wrapper input keeps optional caller fields and fills defaults before sending; drift fails closed
  through `npm run check:api-types`; runtime API failures continue through `ApiError`.
- Rollout & monitoring: frontend-only compile-time hardening. Backout is reverting the type alias
  migration; watch CI typecheck/unit failures and generated-type drift.
- Acceptance checks: `cd apps/web && npm run test:unit`, `npm run typecheck`, `npm run lint`,
  `npm run build`, and `npm run check:api-types` all pass.

### Dependencies

- PR12 generated artifacts must be present on `main`.
- Existing Vitest unit-test layer from PR4.

### Validation

Run the frontend unit tests first, then typecheck/lint/build and API type drift check. Inspect the
facade exports to verify the first migrated domains use generated endpoint/schema aliases.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Generated project aliases | `apps/web/src/lib/api.ts` exported wrapper return types | `api.ts` imports `components`/`paths` from generated file | N/A |
| Generated document aliases | `fetchDocuments`, `fetchDocumentDownloadLink` | existing hooks/pages import from `api.ts` | N/A |
| Generated rules aliases | `fetchRules`, `createRuleProfile`, `triggerManualRecrawl` | existing hooks/pages import from `api.ts` | N/A |
| Contract tests | `npm run test:unit` | `apps/web/vitest.config.ts` discovers `tests/unit/**/*.test.ts` | N/A |

## Plan Draft B - New Contract Types Module

### Overview

Create a dedicated `src/lib/api-contracts.ts` module that owns generated alias names and have
`src/lib/api.ts` import from that module. This keeps the large API facade cleaner, but adds a new
layer that can hide whether wrappers are actually using generated types.

### Files to Change

- `apps/web/src/lib/api-contracts.ts` - new generated alias module for adopted domains.
- `apps/web/src/lib/api.ts` - import adopted aliases from the new module and remove manual
  declarations for migrated domains.
- `apps/web/tests/unit/api.test.ts` - wrapper tests as in Draft A.
- `apps/web/tests/unit/generated-api-types.test.ts` - contract module import assertions.
- `docs/OPENAPI_CONTRACTS.md` - document the adopted contract module.

### Implementation Steps

TDD sequence:
1. Add tests importing the future contract aliases from `api-contracts.ts`.
2. Run unit tests and confirm import failure.
3. Create `api-contracts.ts` with generated alias exports.
4. Replace migrated `api.ts` manual declarations with imports/re-exports from the contract module.
5. Run frontend gates and generated drift check.

Function notes:
- `api-contracts.ts` would expose `OkResponse<Path, Method>` style helpers or explicit aliases.
- `api.ts` remains the only runtime fetch facade.

### Test Coverage

- Same wrapper behavior tests as Draft A.
- `api-contracts exports generated aliases` - module-level contract adoption.

### Decision Completeness

- Goal: centralize generated aliases outside the runtime API facade.
- Non-goals: runtime client generation, all-domain migration, backend schema changes.
- Success criteria: migrated domain aliases are generated and imported by `api.ts`.
- Public interfaces: adds an internal module; existing `api.ts` exports remain.
- Edge cases / failure modes: extra indirection can drift if wrappers import the wrong alias;
  tests must import public `api.ts` exports and generated aliases to catch that.
- Rollout & monitoring: same as Draft A.
- Acceptance checks: same frontend gates as Draft A.

### Dependencies

- Generated OpenAPI artifacts from PR12.

### Validation

Run unit tests and TypeScript checks; inspect import graph to confirm pages still consume `api.ts`.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `api-contracts.ts` | Type imports from `api.ts` and tests | direct TypeScript imports | N/A |
| Contract tests | `npm run test:unit` | Vitest discovery | N/A |

## Comparative Analysis

Draft A is the smaller, clearer PR13 slice because the existing `api.ts` facade is already the
documented extension point in `apps/web/AGENTS.md`. It proves adoption in real wrappers without
introducing a second contract module or changing import paths across pages.

Draft B may become useful if many more domains migrate and `api.ts` becomes harder to scan, but it
adds indirection before there is enough adopted surface to justify it.

Both drafts follow the repo guidance: keep fetch logic centralized, preserve strict TypeScript,
write tests first, and run the nearest frontend gates. Draft A has less wiring risk and better
matches PR13's goal of first-domain adoption.

## Unified Execution Plan

### Overview

Use Draft A. Migrate projects, documents, and rules in `apps/web/src/lib/api.ts` by replacing
manual response/request/domain types with generated aliases while preserving existing wrapper
function names and page imports.

### Files to Change

- `apps/web/src/lib/api.ts` - generated type aliases for adopted domains, no runtime behavior
  changes except typed wrapper payloads.
- `apps/web/tests/unit/api.test.ts` - tests-first coverage for wrapper URL/payload behavior and
  generated-shaped responses.
- `apps/web/tests/unit/generated-api-types.test.ts` - generated contract coverage for the migrated
  domains.
- `docs/OPENAPI_CONTRACTS.md` - update adoption notes.

### Implementation Steps

TDD sequence:
1. Add tests in `api.test.ts` and `generated-api-types.test.ts` for generated domain adoption and
   wrapper behavior.
2. Run `cd apps/web && npm run test:unit` and capture RED.
3. Edit `api.ts` to import `components`/`paths` and alias the adopted domain types from generated
   contracts.
4. Keep caller-friendly request types where generated defaults are too strict, but derive their
   field types from generated query/request schemas.
5. Run GREEN unit tests.
6. Run `npm run typecheck`, `npm run lint`, `npm run build`, and `npm run check:api-types`.
7. Perform `g-check` working-tree review, fix any findings, then package and submit through
   Graphite.

Function names:
- `fetchProjects` - list projects using generated response and query parameter types.
- `fetchProjectDetail` - return generated project detail contract.
- `fetchDocuments` - return generated document list contract.
- `fetchDocumentDownloadLink` - return generated signed/proxy download-link contract.
- `fetchRules` - return generated rules contract.
- `createRuleProfile` - accept a caller-friendly payload derived from generated request fields and
  send a generated-compatible request body.
- `triggerManualRecrawl` - return generated manual recrawl response.

### Test Coverage

- `fetchProjects builds generated contract query` - query defaults and arrays.
- `fetchProjectDetail returns generated response shape` - project detail wrapper.
- `fetchDocuments returns generated document list` - documents wrapper.
- `fetchRules returns generated rules response` - rules wrapper.
- `createRuleProfile sends generated request payload` - request defaults preserved.
- `generated API contract exposes migrated domains` - schema/endpoint aliases compile.

### Decision Completeness

- Goal: make generated OpenAPI types actively used by the first frontend domains.
- Non-goals: full frontend migration, runtime OpenAPI client, generated artifact changes, backend
  route/schema changes, UI redesign.
- Success criteria: `api.ts` adopted domain exports derive from generated types; pages/hooks compile
  unchanged; tests and frontend gates pass.
- Public interfaces: existing public TypeScript export names remain; no route/API/env/schema/CLI
  changes.
- Edge cases / failure modes: optional wrapper inputs still fill generated-required default fields;
  array query serialization stays unchanged; binary download helper remains manually typed because
  OpenAPI JSON response types do not model the returned `Blob` wrapper.
- Rollout & monitoring: compile-time-only hardening. CI should catch generated drift, wrapper
  behavior regressions, and type mismatches.
- Acceptance checks: `cd apps/web && npm run test:unit`; `npm run typecheck`; `npm run lint`;
  `npm run build`; `npm run check:api-types`.

### Dependencies

- Clean `main` containing PR12 generated artifacts.
- Graphite CLI and GitHub CLI available for submit/landing.

### Validation

Use the focused unit suite as RED/GREEN, then run full frontend gates. Use targeted `rg`/diff
inspection to verify the adopted manual types are gone and generated imports are wired.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Project generated aliases | `fetchProjects`, `fetchProjectDetail`, `useProjects`, `useProjectDetail` | `api.ts` exports consumed by `hooks.ts` and pages | N/A |
| Document generated aliases | `fetchDocuments`, `fetchDocumentDownloadLink`, `useDocuments` | `api.ts` exports consumed by project detail page | N/A |
| Rules generated aliases | `fetchRules`, `createRuleProfile`, `triggerManualRecrawl`, `useRules` | `api.ts` exports consumed by rules/projects pages | N/A |
| Wrapper tests | `npm run test:unit` | Vitest config discovers unit tests | N/A |
| Drift gate | `npm run check:api-types` | package script invokes committed generation check | N/A |

## Implementation Summary (2026-05-16 11:58:03 +07)

### Goal

Implement PR 13: migrate the first frontend domains to generated OpenAPI types while keeping the
existing `apps/web/src/lib/api.ts` wrapper functions stable for pages and hooks.

### What Changed

- `apps/web/src/lib/api.ts`
  - Imported generated `components` and `paths`.
  - Replaced manual project, document, crawl-evidence, rules, entitlement, rule-profile, rule
    request, and manual-recrawl response types with generated aliases.
  - Derived `FetchProjectsParams` from the generated `/v1/projects` query parameters while keeping
    caller-friendly optional fields.
  - Kept binary `DocumentDownloadFileResponse` manual because it is a frontend `Blob` wrapper, not
    the OpenAPI JSON download-link response.
- `apps/web/tests/unit/api.test.ts`
  - Added adoption and wrapper coverage for project list/detail, documents, rules, and rule-profile
    creation payloads.
- `apps/web/tests/unit/generated-api-types.test.ts`
  - Added type-backed generated endpoint coverage for projects, documents, and rules.
- `docs/OPENAPI_CONTRACTS.md`
  - Documented the first adopted generated-type domains and the migration pattern for future
    domains.

### TDD Evidence

- RED: `npm run test:unit`
  - Result: failed in `generated API type adoption` because `apps/web/src/lib/api.ts` did not yet
    import `./generated/api-types` and still contained manual `ProjectSummary`, `DocumentSummary`,
    and `RulesResponse` object declarations.
- GREEN: `npm run test:unit`
  - Result: `4 passed`, `14 passed`.

### Tests Run

- `npm run test:unit` - passed (`4 passed`, `14 passed`).
- `npm run typecheck` - passed.
- `npm run lint` - passed.
- `npm run check:api-types` - passed (`OpenAPI schema and generated API types are current.`).
- `npm run build` - passed.
- `npm test` - passed (`28 passed`).

### Wiring Verification

- Project wrappers: `fetchProjects`, `fetchProjectDetail`, and `fetchProjectCrawlEvidence` now
  return aliases derived from generated `paths`/`components`; hooks/pages continue importing from
  `api.ts`.
- Document wrappers: `fetchDocuments` and `fetchDocumentDownloadLink` use generated response
  aliases; `fetchDocumentDownloadFile` keeps the browser `Blob` wrapper type.
- Rules wrappers: `fetchRules`, `createRuleProfile`, and `triggerManualRecrawl` use generated
  response/request aliases with optional caller defaults preserved.
- Tests are registered through the existing Vitest discovery pattern.

### Behavior Changes And Risk Notes

- No runtime API behavior changes intended; fetch URLs, query serialization, request defaults, and
  wrapper names are preserved.
- Compile-time behavior is stricter: project budget filters now accept the generated
  `number | string` query shape instead of the old string-only manual type.
- Generated OpenAPI drift continues to fail closed through `npm run check:api-types`.

### Follow-Ups / Known Gaps

- Remaining frontend domains still use manual facade types and should be migrated in later focused
  PRs.

## Review (2026-05-16 11:58:03 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree
- Commands Run: `git status --porcelain=v1`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`,
  targeted `git diff` and `nl -ba` inspection for `api.ts`, unit tests, and docs, `npm run
  test:unit`, `npm run typecheck`, `npm run lint`, `npm run check:api-types`, `npm run build`,
  `npm test`.

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
- Assumes PR13 should keep the existing `api.ts` facade rather than introducing a runtime generated
  OpenAPI client.
- Assumes binary download helper output should stay manually typed as a browser `Blob` wrapper.

### Recommended Tests / Validation
- Already run: frontend unit tests, typecheck, lint, build, Playwright smoke suite, and OpenAPI
  drift check.

### Rollout Notes
- Frontend compile-time hardening only. No backend, schema, environment, or runtime deployment
  changes.

## Submission / Landing Status (2026-05-16 12:01:00 +07)

- Created Graphite branch: `05-16-feat_web_adopt_generated_api_types`.
- Submitted PR: https://github.com/SubhajL/egp/pull/85
- Remote CI did not execute because GitHub reported the same repository/account billing blocker
  seen on PR12.
- Evidence: the `Frontend Lint & Typecheck` check-run annotation reported:
  `The job was not started because your account is locked due to a billing issue.`
- All CI jobs failed immediately in roughly two seconds with the same non-execution pattern.
- Added PR comment documenting the blocker and local validation:
  https://github.com/SubhajL/egp/pull/85#issuecomment-4465695641
- Landing to `remote/main` and local `main` is blocked until GitHub Actions/check execution is
  restored, unless an explicit admin bypass is approved. I did not bypass branch protection or push
  directly to `main`.
