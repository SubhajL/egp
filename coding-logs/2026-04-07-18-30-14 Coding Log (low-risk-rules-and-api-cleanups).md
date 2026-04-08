## Goal

- Address the remaining low-risk cleanup items and nitty-gritty follow-ups from review:
  - reduce the amount of mixed product/view/mutation logic still living in `apps/web/src/app/(app)/rules/page.tsx`
  - stop silently treating unknown rules plan codes as `free_trial`
  - forward `profile_id` through the immediate-discovery worker payload for cleaner wiring
  - move signup-specific 422 normalization out of `signup/page.tsx` into shared API error helpers
  - add direct coverage for shared API error normalization and loopback API base-url behavior

## Exploration

- Auggie semantic retrieval was available and used for the initial code map.
- Exact file inspection confirmed:
  - `apps/web/src/app/(app)/rules/page.tsx` is still large because it keeps several presentational subcomponents plus page-level mutation orchestration and tab rendering in one file.
  - `apps/web/src/app/(app)/rules/view-model.tsx` currently owns plan tier mapping, but `resolvePlanTier()` still defaults unknown plans to `free_trial`.
  - `apps/web/src/lib/api.ts` now owns code-first localization, but signup-specific 422-to-Thai mapping still lives in `apps/web/src/app/signup/page.tsx`.
  - `apps/api/src/egp_api/main.py` accepts `profile_id` into `_make_discover_spawner()` but does not pass it to the worker JSON payload.
  - `apps/worker/src/egp_worker/main.py` currently ignores `profile_id` because the `discover` payload does not include it.
  - There is no dedicated frontend unit-test runner beyond Playwright, so low-level API helper checks should use a minimal Node/TypeScript-safe script or focused e2e coverage rather than introducing a new framework.

## Plan Draft A

### Overview

- Keep the cleanup slice small and local:
  - introduce shared frontend helper functions/types in `apps/web/src/lib/api.ts` for normalized auth/signup error presentation
  - extract a small rules page-state/helper module from `page.tsx` for tab validity, keyword parsing, crawl interval formatting, and unknown-plan handling
  - make unknown plans explicit via a safe fallback state that is visible in copy/logical branching rather than silently masquerading as `free_trial`
  - add `profile_id` to the worker discover payload and add a worker-level assertion test

### Files To Change

- `apps/web/src/lib/api.ts`
- `apps/web/src/app/signup/page.tsx`
- `apps/web/src/app/(app)/rules/page.tsx`
- `apps/web/src/app/(app)/rules/view-model.tsx`
- `apps/web/src/app/(app)/rules/` new helper module(s)
- `apps/web/tests/e2e/auth-pages.spec.ts`
- `apps/web/tests/e2e/rules-page.spec.ts`
- `apps/api/src/egp_api/main.py`
- `apps/worker/src/egp_worker/main.py`
- `tests/phase2/test_immediate_discover.py`
- `tests/phase1/test_worker_workflows.py` or the smallest existing worker-entry test seam
- new small web helper test script under `apps/web/src/lib/` or `apps/web/scripts/` if needed
- `.opencode/coding-log.current`
- `.codex/coding-log.current`

### Implementation Steps

1. Add RED tests for worker payload forwarding of `profile_id` and for shared web API normalization behavior.
2. Add RED coverage for unknown plan handling and any rules helper extraction behavior that should remain stable.
3. Implement the smallest shared helper extraction in `apps/web/src/lib/api.ts` so signup can consume normalized error metadata instead of page-local code branches.
4. Refactor `signup/page.tsx` to use the shared helper while preserving existing UX and login-link behavior.
5. Extract remaining page-state/view helpers from `rules/page.tsx` into a typed module local to the rules route.
6. Change plan resolution so unknown/non-null plan codes map to an explicit safe tier or display state, not silently to `free_trial`.
7. Forward `profile_id` into the worker discover payload and keep worker command handling compatible.
8. Run focused validation gates.

### Test Coverage

- Backend / worker:
  - `tests/phase2/test_immediate_discover.py`
  - smallest relevant worker-entry test file (likely `tests/phase1/test_worker_workflows.py`)
- Frontend:
  - `apps/web/tests/e2e/auth-pages.spec.ts`
  - `apps/web/tests/e2e/rules-page.spec.ts`
  - minimal direct helper test command if added

### Decision Completeness

- Goal:
  - improve clarity and maintainability without changing product behavior beyond making unknown plan drift more explicit
- Non-goals:
  - no backend capability-contract redesign for rules
  - no new frontend test framework
  - no change to discovery job semantics or worker workflow behavior beyond payload clarity
- Success criteria:
  - signup no longer owns special-case validation normalization logic
  - rules page sheds more helper logic into typed local modules
  - unknown plans do not silently render as free trial
  - worker discover payload includes `profile_id`
  - focused tests pass
- Changed public interfaces:
  - internal worker payload for `discover` gains `profile_id`
  - frontend shared helper API may gain exported normalization helpers
- Edge cases:
  - unknown plan codes still render safely without crashing and without offering incorrect free-trial-specific messaging
  - existing worker behavior must remain compatible if `profile_id` is absent in older payloads
  - signup still shows the login shortcut only for duplicate-account cases
- Rollout/backout:
  - low-risk internal refactor plus additive worker payload field

### Dependencies

- Existing rules page query contract from `/v1/rules`
- Existing `ApiError` and `localizeApiError()` usage in `apps/web/src/lib/api.ts`
- Existing worker command parser in `apps/worker/src/egp_worker/main.py`

### Validation

- `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py <worker-test-file> -q`
- `./.venv/bin/ruff check apps/api apps/worker packages tests`
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages`
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run build`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| shared signup error normalization | signup submit flow and any future auth pages | `apps/web/src/lib/api.ts`, imported by `apps/web/src/app/signup/page.tsx` | none |
| extra rules helper extraction | `/rules` page render path | `apps/web/src/app/(app)/rules/page.tsx` plus new local helper module(s) | none |
| explicit unknown plan handling | rules page view model | `apps/web/src/app/(app)/rules/view-model.tsx` | none |
| discover payload `profile_id` forwarding | durable dispatch -> app spawner -> worker command parser | `apps/api/src/egp_api/main.py`, `apps/worker/src/egp_worker/main.py` | `discovery_jobs` |

## Plan Draft B

### Overview

- Keep the frontend even tighter by avoiding new modules beyond one additional shared helper in `api.ts` and one extra rules local helper file.
- Treat unknown plan codes as a dedicated computed display state that reuses the safest existing tabs while changing only the badge/subtitle copy to avoid claiming free-trial semantics.
- Verify shared API helper behavior through a tiny `node --import tsx`-style script only if already available; otherwise rely on Playwright and TypeScript compilation.

### Files To Change

- Same core files as Draft A, but no broader helper split than strictly necessary.

### Implementation Steps

1. RED backend worker payload tests.
2. RED Playwright coverage for unknown plan display and signup duplicate/validation behavior still rendering correctly after helper extraction.
3. Add shared `normalizeAuthPageError` helper(s) in `api.ts` and consume them from signup.
4. Extract only keyword/schedule/tab helper logic from `rules/page.tsx` into one local helper module.
5. Update `resolvePlanTier()` to return an explicit `unknown_plan` tier and keep rendering conservative.
6. Forward `profile_id` in worker payload and add the smallest worker parse/assertion coverage.
7. Run focused validation.

### Test Coverage

- Same focused backend and Playwright coverage.
- No new standalone web script unless necessary.

### Decision Completeness

- Goal: fix the review nits with minimum new surface area.
- Non-goals: large component split or new testing harness.
- Success criteria: same as Draft A, with smaller refactor footprint.
- Changed public interfaces: additive worker payload field only.

### Dependencies

- Same as Draft A.

### Validation

- Same as Draft A.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| shared signup normalization helper | `/signup` submit path | `apps/web/src/lib/api.ts` + `apps/web/src/app/signup/page.tsx` | none |
| explicit unknown plan view state | `/rules` page render path | `apps/web/src/app/(app)/rules/view-model.tsx` | none |
| discover payload `profile_id` | app spawner -> worker parser | `apps/api/src/egp_api/main.py`, `apps/worker/src/egp_worker/main.py` | `discovery_jobs` |

## Comparative Analysis

- Draft A is cleaner if the rules page can afford one more extraction step, but it risks turning a low-risk cleanup into a broader component refactor.
- Draft B better matches the user’s request: fix the remaining low-risk issues and nitty-gritty items with the smallest possible diff.
- Both drafts handle `profile_id` forwarding and shared signup normalization; the main difference is how aggressively to split `rules/page.tsx`.

## Unified Execution Plan

### Overview

- Follow Draft B.
- Keep the changes narrow and explicit:
  - shared error normalization helper in `apps/web/src/lib/api.ts`
  - one additional local rules helper module for page-state/helper logic that still clutters `page.tsx`
  - explicit `unknown_plan` view-model handling
  - additive `profile_id` worker payload forwarding

### Files To Change

- `apps/web/src/lib/api.ts`
- `apps/web/src/app/signup/page.tsx`
- `apps/web/src/app/(app)/rules/page.tsx`
- `apps/web/src/app/(app)/rules/view-model.tsx`
- `apps/web/src/app/(app)/rules/` one new local helper module
- `apps/web/tests/e2e/auth-pages.spec.ts`
- `apps/web/tests/e2e/rules-page.spec.ts`
- `apps/api/src/egp_api/main.py`
- `apps/worker/src/egp_worker/main.py`
- `tests/phase2/test_immediate_discover.py`
- smallest worker-entry test file for payload parsing/wiring

### Implementation Steps

1. RED tests:
   - add worker/discovery tests that fail because `profile_id` is not forwarded today
   - add or extend focused frontend coverage for signup/rules behavior that should survive helper extraction and explicit unknown-plan handling
   - add the smallest direct helper assertions possible for `localizeApiError()` / shared auth error normalization if the existing toolchain allows it without adding dependencies
2. Implement shared API error normalization:
   - add exported helper(s) in `apps/web/src/lib/api.ts` for auth/signup page error display and duplicate-account detection
   - move signup-specific code-based normalization out of `signup/page.tsx`
3. Reduce rules page responsibility:
   - move `parseKeywordDraft`, crawl interval formatting, active-tab validation, and any derived page-model state into one local helper module
   - keep render subcomponents in `page.tsx` unless extraction clearly reduces complexity without spreading concerns
4. Handle unknown plans explicitly:
   - change `resolvePlanTier()` to return `unknown_plan` for non-null unsupported codes
   - add conservative labels/copy/tabs so the page stays safe but no longer claims free-trial semantics
5. Forward worker payload context:
   - add `profile_id` to the JSON payload in `_make_discover_spawner()`
   - let worker command handling accept and preserve that value where relevant without changing current workflow outputs unless needed for tests
6. Run focused validation and update the coding log.

### Test Coverage

- Backend / worker:
  - `tests/phase2/test_immediate_discover.py`
  - relevant worker entry/workflow test file for discover payload parsing
- Frontend:
  - `apps/web/tests/e2e/auth-pages.spec.ts`
  - `apps/web/tests/e2e/rules-page.spec.ts`
  - optional tiny direct helper test if it can run with existing dependencies only

### Decision Completeness

- Goal:
  - clean up the known low-risk maintainability issues without redesigning architecture
- Non-goals:
  - no new backend rules capability contract
  - no full component tree rewrite of the rules page
  - no new frontend testing framework or package additions
- Measurable success criteria:
  - signup page no longer contains bespoke validation normalization logic
  - rules page shrinks and delegates more pure helper logic out of `page.tsx`
  - unknown plans render safely with explicit non-free-trial handling
  - `profile_id` is present in the discover payload path and covered by tests
  - focused validation passes
- Changed public interfaces:
  - additive `profile_id` field in internal worker discover payload
  - exported shared frontend normalization helper(s)
- Edge cases and failure modes:
  - unsupported plan codes must not crash or accidentally unlock/edit features
  - old payloads without `profile_id` must remain acceptable in the worker parser
  - duplicate-account login shortcut must still appear only when intended
- Rollout/backout expectations:
  - internal cleanup and additive payload field; low-risk to revert if needed
- Concrete acceptance checks:
  - targeted backend/worker/frontend tests pass
  - `typecheck`, `build`, `ruff`, and `compileall` pass for touched code

### Dependencies

- Existing rules snapshot and entitlement response shape
- Existing `ApiError` / `localizeApiError()` client plumbing
- Existing worker `discover` command handling

### Validation

- `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase1/test_worker_workflows.py -q`
- `./.venv/bin/ruff check apps/api apps/worker packages tests`
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages`
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run build`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| shared signup/auth error normalization | auth page submit handlers | `apps/web/src/lib/api.ts`, consumed by `apps/web/src/app/signup/page.tsx` | none |
| local rules page helpers | `/rules` page render and mutations | new helper imported by `apps/web/src/app/(app)/rules/page.tsx` | none |
| explicit unknown plan handling | rules plan view model | `apps/web/src/app/(app)/rules/view-model.tsx` | none |
| discover payload `profile_id` | dispatch processor -> spawner -> worker parser | `apps/api/src/egp_api/main.py`, `apps/worker/src/egp_worker/main.py` | `discovery_jobs` |

## Implementation (2026-04-07 18:35:29 +07)

### Goal

- Close the remaining low-risk review items around rules-page maintainability, explicit unknown-plan handling, shared signup error normalization, and immediate-discovery payload clarity.

### What Changed By File

- `apps/web/src/lib/api.ts`
  - Added shared `normalizeSignupApiError()` and `shouldShowSignupLoginLink()` helpers so signup-specific error normalization no longer lives inside the page component.
  - Kept `localizeApiError()` as the shared fallback path.
- `apps/web/src/app/signup/page.tsx`
  - Switched the page to shared API error normalization helpers.
  - Replaced login-link detection by string inclusion with explicit helper-driven state.
- `apps/web/src/app/(app)/rules/page-helpers.ts`
  - New local helper module for keyword parsing, crawl interval formatting, interval options, and active-tab fallback logic.
- `apps/web/src/app/(app)/rules/view-model.tsx`
  - Introduced explicit `unknown_plan` handling instead of silently mapping unsupported plan codes to `free_trial`.
  - Added conservative badge/copy/tab definitions for the unknown-plan state.
- `apps/web/src/app/(app)/rules/page.tsx`
  - Switched to the new local helper module for pure page-state helpers.
  - Kept render behavior stable while shrinking inline helper logic.
- `apps/api/src/egp_api/main.py`
  - `_make_discover_spawner()` now forwards `profile_id` in the discover worker payload.
- `apps/worker/src/egp_worker/main.py`
  - `run_worker_job()` now preserves `profile_id` in the discover result payload when provided.
- `tests/phase2/test_immediate_discover.py`
  - Added coverage that the app spawner forwards `profile_id` into the worker JSON payload.
- `tests/phase1/test_worker_workflows.py`
  - Added coverage that the worker preserves `profile_id` in the discover result.
- `apps/web/tests/e2e/rules-page.spec.ts`
  - Added unknown-plan UI coverage to ensure unsupported plans do not silently render as free trial.
- `apps/web/scripts/api-helpers-check.mts`
  - Added a small direct assertion script for shared API helpers and loopback API base-url normalization using only existing Node support.

### TDD Evidence

- Tests added/changed:
  - `tests/phase2/test_immediate_discover.py`
  - `tests/phase1/test_worker_workflows.py`
  - `apps/web/tests/e2e/rules-page.spec.ts`
  - `apps/web/scripts/api-helpers-check.mts`
- RED commands:
  - `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase1/test_worker_workflows.py -q`
  - `cd apps/web && node --experimental-strip-types src/lib/api.test.ts`
- RED failure reasons:
  - `profile_id` was not included in the spawner payload
  - worker discover results did not preserve `profile_id`
  - shared signup helper exports did not exist yet
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase1/test_worker_workflows.py -q`
  - `cd apps/web && node --experimental-strip-types scripts/api-helpers-check.mts`
  - `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts`

### Tests Run And Results

- `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase1/test_worker_workflows.py -q`
  - passed (`19 passed`)
- `cd apps/web && node --experimental-strip-types scripts/api-helpers-check.mts`
  - passed (`api helpers ok`)
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts`
  - passed (`14 passed`)
- `./.venv/bin/ruff check apps/api apps/worker packages tests`
  - passed
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages`
  - passed
- `cd apps/web && npm run typecheck`
  - passed
- `cd apps/web && npm run build`
  - passed

### Wiring Verification Evidence

| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| shared signup error normalization | YES | Verified by `apps/web/src/app/signup/page.tsx` imports/call sites and existing signup Playwright coverage still passing |
| local rules helper module | YES | Verified by imports in `apps/web/src/app/(app)/rules/page.tsx` and passing rules Playwright suite |
| explicit unknown-plan handling | YES | Verified by `apps/web/src/app/(app)/rules/view-model.tsx` usage in `page.tsx` and new unknown-plan Playwright scenario |
| discover payload `profile_id` forwarding | YES | Verified by `_make_discover_spawner()` payload construction in `apps/api/src/egp_api/main.py`, worker handling in `apps/worker/src/egp_worker/main.py`, and passing focused pytest coverage |

### Behavior Changes And Risk Notes

- Unsupported plan codes now render as an explicit safe fallback state instead of pretending to be `free_trial`; this makes contract drift more visible without breaking the page.
- Signup login-link behavior is now explicit and code-driven rather than inferred from localized text.
- The direct Node helper-check script emits a module-type warning because the web package is not declared as ESM; the assertions still run correctly, and this slice intentionally does not change package module policy.

### Follow-Ups And Known Gaps

- If we want quieter direct helper checks, we could later add an officially supported script runner or package-level ESM declaration after evaluating repo-wide impact.
- The rules page is smaller in pure-helper responsibility now, but render subcomponents still live in one file; further splitting should wait until there is a concrete product change that benefits from it.

## Review (2026-04-08 07:06:36 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main` working tree before branch cut
- Scope: current low-risk cleanup slice
- Commands Run:
  - `git status --short`
  - `git diff --stat`
  - targeted reads/diff for `apps/web/src/lib/api.ts`, `apps/web/src/app/signup/page.tsx`, `apps/web/src/app/(app)/rules/{page.tsx,view-model.tsx,page-helpers.ts}`, `apps/api/src/egp_api/main.py`, `apps/worker/src/egp_worker/main.py`, `tests/phase1/test_worker_workflows.py`, `tests/phase2/test_immediate_discover.py`, `apps/web/tests/e2e/rules-page.spec.ts`, `apps/web/scripts/api-helpers-check.mts`

### Findings
- No findings.

### Open Questions / Assumptions
- The direct helper check script remains a local validation aid, not a formal npm test target.
- Unknown-plan handling is intentionally conservative until a backend capability contract exists.

### Recommended Tests / Validation
- Reuse the focused backend/worker/frontend validations already recorded for this slice.
- No extra coverage appears necessary before merge.

### Rollout Notes
- Changes are low-risk and mostly internal refactors plus one additive internal worker payload field.
