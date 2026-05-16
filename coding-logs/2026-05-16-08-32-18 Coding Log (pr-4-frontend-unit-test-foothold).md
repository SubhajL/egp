# Coding Log — PR 4 Frontend Unit Test Foothold

Created: 2026-05-16 08:32:18 +07

## Plan Draft A — Minimal additive foothold

### Overview
Add a small dedicated unit-test layer beside the existing Playwright smoke suite, keeping the production app behavior unchanged while giving fast coverage to brittle frontend contracts. The smallest useful slice is a `vitest` setup, API error parsing coverage through exported fetch functions, a testable current-session fetch helper for the existing `useMe()` invalidation behavior, and pure helper coverage for auth/rules view models.

### Files to Change
- `apps/web/package.json`, `apps/web/package-lock.json` — add unit-test tooling and scripts.
- `apps/web/vitest.config.ts` — deterministic unit-test discovery.
- `apps/web/tests/unit/api.test.ts` — API error contract coverage.
- `apps/web/tests/unit/hooks.test.ts` — current-session success / `401` invalidation coverage.
- `apps/web/tests/unit/auth.test.ts` — auth display helper coverage.
- `apps/web/tests/unit/rules-view-model.test.tsx` — pure rules view-model coverage.
- `apps/web/src/lib/hooks.ts` — extract the existing `useMe()` query function into a named helper used by the hook.
- `apps/web/AGENTS.md`, `package.json`, `.github/workflows/ci.yml` — document and wire the new fast frontend gate.

### Implementation Steps
1. Add failing unit tests and the `test:unit` script target.
2. Run `cd apps/web && npm run test:unit -- --runInBand` equivalent via `vitest run` and confirm failure because the unit-test layer/helper does not exist yet.
3. Add the smallest implementation: Vitest dependency/config, exported `fetchCurrentSession()` helper, and CI/dev workflow wiring.
4. Refactor only if needed to keep `useMe()` behavior unchanged.
5. Run focused gates: unit tests, typecheck, lint, build, and the existing Playwright smoke suite.

Functions
- `fetchCurrentSession()` in `apps/web/src/lib/hooks.ts`: own the current-session fetch/write/clear behavior currently embedded inside `useMe()` so the contract can be tested without rendering React hooks.
- Existing helpers under test only: `fetchMe()`, `getUserDisplayName()`, `getUserInitials()`, `resolvePlanTier()`, `headerSubtitleForPlan()`.

### Test Coverage
- `fetchMe parses structured validation errors` — preserves readable 422 API detail text.
- `fetchMe falls back when response body is unreadable` — keeps robust generic API failures.
- `fetchCurrentSession writes storage after success` — successful refresh persists latest session.
- `fetchCurrentSession clears storage on unauthorized response` — `401` fails closed for stale sessions.
- `fetchCurrentSession preserves storage on server error` — transient failures do not log users out.
- `getUserDisplayName prefers full name/email/subject` — user labels stay stable.
- `getUserInitials derives one- and two-part initials` — header avatars remain predictable.
- `resolvePlanTier maps known and unknown plans` — rules page branching stays explicit.
- `headerSubtitleForPlan matches tier copy` — view-model lookup remains correct.

### Decision Completeness
- Goal: establish a fast frontend unit/contract test layer below E2E.
- Non-goals: no broad component-test framework, no contract codegen, no rewrite of existing Playwright smoke tests.
- Success criteria: `npm run test:unit` exists, runs quickly, covers API parsing + session invalidation + pure helpers, and is enforced in CI.
- Public interfaces: new developer commands only (`test:unit` root/web scripts); no API/env/schema changes.
- Edge cases / failure modes: malformed error payloads fall back to generic text; `401` clears cached session fail-closed; `500` preserves session fail-open for transient server faults.
- Rollout & monitoring: no runtime rollout; CI should surface regressions immediately.
- Acceptance checks: `npm run test:unit`, `npm run typecheck`, `npm run lint`, `npm run build`, `npm test` all pass under `apps/web`.

### Dependencies
- Existing Node/npm frontend setup and `package-lock.json`.
- Existing `fetchMe()` and `useMe()` contract.

### Validation
Run focused unit tests first, then the standard frontend gates from `apps/web/AGENTS.md`.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `vitest` unit suite | `npm run test:unit` | `apps/web/package.json`, `.github/workflows/ci.yml` | N/A |
| `fetchCurrentSession()` | `useMe()` query function | `apps/web/src/lib/hooks.ts` | N/A |
| root unit-test proxy | `npm run test:unit` from repo root | root `package.json` | N/A |

### Cross-Language Schema Verification
No schema or migration changes.

## Plan Draft B — Broader component-test foothold

### Overview
Stand up a fuller frontend test stack immediately with Vitest, jsdom, React Testing Library, and hook/component tests around `useMe()` plus one protected layout flow. This better mirrors user behavior, but it introduces more dependencies and broader surface area than the first PR needs.

### Files to Change
- Same config/package files as Draft A.
- Additional test utilities and React Testing Library dependencies.
- Hook/component tests for `useMe()` and possibly `AppLayout`.

### Implementation Steps
1. Add failing hook/component tests first.
2. Configure jsdom + RTL test utilities.
3. Render `useMe()` within `QueryClientProvider` and assert storage invalidation.
4. Add pure helper tests.
5. Run full frontend gates.

### Test Coverage
- `useMe clears session after 401` — integration-style hook behavior.
- `AppLayout redirects unauthorized users` — protected route UX.
- Plus the pure helper/API tests from Draft A.

### Decision Completeness
- Goal: create a richer browser-adjacent frontend test layer.
- Non-goals: no full visual regression suite.
- Success criteria: hook/component contracts are exercised without a browser.
- Public interfaces: new test commands only.
- Edge cases / failure modes: same auth/error behaviors as Draft A.
- Rollout & monitoring: same CI-only rollout.
- Acceptance checks: same commands plus component-test coverage.

### Dependencies
- Adds `@testing-library/react`, `jsdom`, and related typings/utilities.

### Validation
Use component tests to validate routing/auth behavior before Playwright.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| RTL/jsdom suite | `npm run test:unit` | `apps/web/package.json`, `vitest.config.ts` | N/A |
| `useMe()` integration tests | test renderer | test utility/provider setup | N/A |

### Cross-Language Schema Verification
No schema or migration changes.

## Comparative Analysis
- Draft A is the better first PR: materially improves confidence with very little framework weight, keeps the diff reviewable, and tests the exact risky seams already present in the code.
- Draft B buys more realism, but it front-loads dependencies and testing infrastructure before the repo has proven it needs component-level unit tests.
- Both comply with the repo guidance; Draft A better matches the phase-plan phrase “smallest viable frontend unit-test setup.”

## Unified Execution Plan

### Overview
Land the minimal additive foothold from Draft A now, while shaping the code so Draft B remains easy later. The PR will add Vitest as the fast layer, cover exported API/auth/view-model contracts, extract only the currently anonymous `useMe()` query function into `fetchCurrentSession()`, wire unit tests into CI, and update frontend docs to make the new layer discoverable.

### Files to Change
- `apps/web/package.json`, `apps/web/package-lock.json`
- `apps/web/vitest.config.ts`
- `apps/web/tests/unit/api.test.ts`
- `apps/web/tests/unit/hooks.test.ts`
- `apps/web/tests/unit/auth.test.ts`
- `apps/web/tests/unit/rules-view-model.test.tsx`
- `apps/web/src/lib/hooks.ts`
- `apps/web/AGENTS.md`
- root `package.json`
- `.github/workflows/ci.yml`

### Implementation Steps
1. Add the new unit test files plus script/config references so the first run fails for the expected missing-tool/helper reasons.
2. Run the focused RED command and capture the failure.
3. Install/configure Vitest, add `fetchCurrentSession()`, and point `useMe()` at it without changing behavior.
4. Run the focused GREEN command; then make only the small documentation/CI wiring changes.
5. Run frontend validation gates and perform skeptical review before commit/submission.

Functions
- `fetchCurrentSession()` — fetch `/v1/me`, persist fresh sessions, clear stale cached sessions only on `401`, and rethrow all failures for existing React Query behavior.

### Test Coverage
- `api.test.ts`
  - `fetchMe parses structured validation errors` — readable 422 detail extraction.
  - `fetchMe falls back when payload is unreadable` — safe generic API message.
- `hooks.test.ts`
  - `fetchCurrentSession stores successful refreshes` — writes latest session.
  - `fetchCurrentSession clears only unauthorized sessions` — fail-closed `401` handling.
  - `fetchCurrentSession preserves session on transient failures` — avoids false logout.
- `auth.test.ts`
  - display-name and initials priority cases.
- `rules-view-model.test.tsx`
  - known/unknown plan mapping and subtitle lookup.

### Decision Completeness
- Goal: add a real fast frontend test layer with first useful contracts.
- Non-goals: no React Testing Library yet; no broad page/component coverage; no Playwright replacement.
- Success criteria: unit tests exist, pass, run in CI, and target the three requested seams.
- Public interfaces: `test:unit` command in web/root package scripts; no runtime/API/env/schema changes.
- Edge cases / failure modes:
  - unreadable API response body → generic `ApiError` detail, fail-safe.
  - `401` current-session refresh → clear cached session, fail-closed.
  - `5xx` current-session refresh → preserve cache, fail-open for transient backend issues.
- Rollout & monitoring: CI-only change; watch the new frontend unit-test step and existing frontend gates.
- Acceptance checks:
  - `cd apps/web && npm run test:unit`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run lint`
  - `cd apps/web && npm run build`
  - `cd apps/web && npm test`

### Dependencies
- `vitest` as the only new test dependency unless implementation proves otherwise.

### Validation
Run the new fast suite first, then all existing frontend gates to ensure the new layer coexists with the smoke suite.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| unit-test runner | `apps/web/package.json:test:unit` | CI step in `.github/workflows/ci.yml` and root proxy script | N/A |
| current-session fetch contract | `useMe()` | direct call in `apps/web/src/lib/hooks.ts` | N/A |
| pure helper tests | `vitest` discovery | `apps/web/vitest.config.ts` | N/A |

### Cross-Language Schema Verification
No schema or migration changes.

### Decision-Complete Checklist
- No open implementation decisions remain.
- New public surface is limited to named test commands.
- Each behavior change or contract seam has a targeted test.
- Validation commands are scoped and explicit.
- Wiring table covers every new component.
- No deployment-visible rollout/backout work is required.


## Implementation Summary (2026-05-16 08:36:03 +07)

### Goal
Add the first real fast frontend unit/contract test layer for PR 4 without broadening the runtime surface or replacing the existing Playwright smoke suite.

### What Changed
- `apps/web/package.json`, `apps/web/package-lock.json`, `apps/web/vitest.config.ts`
  - Added `vitest` and a dedicated `test:unit` command with deterministic unit-test discovery.
- `apps/web/tests/unit/api.test.ts`
  - Added contract coverage for structured API validation failures and unreadable response bodies via `fetchMe()`.
- `apps/web/tests/unit/hooks.test.ts`
  - Added current-session coverage for successful refreshes, fail-closed `401` invalidation, and non-logout behavior on transient server failures.
- `apps/web/tests/unit/auth.test.ts`
  - Added fast view-model/helper coverage for display-name and initials derivation.
- `apps/web/src/lib/hooks.ts`
  - Extracted `fetchCurrentSession()` from the anonymous `useMe()` query function so the existing behavior is directly testable while preserving runtime wiring.
- `apps/web/AGENTS.md`, root `package.json`, `.github/workflows/ci.yml`
  - Documented and wired the new fast test layer into developer workflow and CI.

### TDD Evidence
- RED command:
  - `cd apps/web && npm run test:unit`
  - failed because `vitest` did not yet exist: `sh: vitest: command not found`.
- Intermediate RED after installing the runner:
  - `cd apps/web && npm run test:unit`
  - surfaced the intended missing helper/mock issues before the implementation was finalized (`fetchCurrentSession` path plus Vitest mock hoisting); this also showed that testing the JSX-bearing rules view-model would unnecessarily expand the first PR's infrastructure needs.
- GREEN command:
  - `cd apps/web && npm run test:unit`
  - passed: `3 passed`, `7 passed`.

### Tests Run And Results
- `cd apps/web && npm run test:unit` — passed.
- `cd apps/web && npm run typecheck` — passed.
- `cd apps/web && npm run lint` — passed.
- `cd apps/web && npm run build` — passed.
- `cd apps/web && npm test` — passed (`28 passed`).

### Wiring Verification Evidence
- `apps/web/src/lib/hooks.ts` now routes `useMe()` through `fetchCurrentSession()` directly.
- `apps/web/package.json:test:unit` is exposed at repo root via `package.json:test:unit`.
- `.github/workflows/ci.yml` runs `npm run test:unit` inside the frontend lint/typecheck job before ESLint.

### Behavior Changes And Risk Notes
- Runtime behavior is intentionally unchanged; only the anonymous `useMe()` query function became a named helper.
- `401` session refresh still fails closed by clearing cached session data.
- `5xx` refresh failures still fail open with respect to cached session retention, matching the existing transient-failure behavior.
- I deliberately kept the first foothold narrow: pure auth helper tests replace an initial idea to test the JSX-based rules view-model so the PR does not pull in component-test tooling prematurely.

### Follow-ups / Known Gaps
- Future frontend testing PRs can add React Testing Library/jsdom if component-level coverage becomes valuable.
- The legacy `scripts/api-helpers-check.mts` script remains separate; this PR establishes the real test framework rather than migrating every ad-hoc assertion immediately.


## Review (2026-05-16 08:36:03 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: `working-tree`
- Commands Run:
  - `git status --short --branch`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - targeted diff inspection for `.github/workflows/ci.yml`, `apps/web/AGENTS.md`, `apps/web/package.json`, `apps/web/src/lib/hooks.ts`, root `package.json`
  - targeted reads for `apps/web/tests/unit/*.ts` and `apps/web/vitest.config.ts`
  - `cd apps/web && npm run test:unit`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run lint`
  - `cd apps/web && npm run build`
  - `cd apps/web && npm test`

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
- Assumed the first foothold should stay minimal and avoid React Testing Library until there is a concrete component-level target worth testing.

### Recommended Tests / Validation
- Already run: unit tests, typecheck, lint, build, and Playwright smoke suite.

### Rollout Notes
- CI-only workflow expansion; no runtime rollout, env-var, schema, or backward-compatibility concerns.

## Merge train update - 2026-05-16 09:28:29 +07

- Merged PR #76 (`test(web): add frontend unit test foothold`) into `main` using GitHub admin bypass because GitHub Actions are currently considered non-operational per user instruction.
- Normal merge attempt was blocked by branch policy; PR was Git-mergeable but check-gated (`Python Lint & Format`, `Frontend Lint & Typecheck`, `Database Migrations`, `Python Tests`, `Frontend Build`, `Build Docker Images`, and `claude-review` all reported failure immediately).
- Synced local `main` with `origin/main`; no open PRs remain. After this required log append, the only local working-tree change is this Coding Log file.
- Merge commit: `1354fdaba14af62b49d12ac18bc90c829f844289`.
