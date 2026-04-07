## Goal

- Implement the medium-risk hardening slice that remains after the auth ambiguity and durable discovery work:
  - replace brittle frontend English-substring localization with stable backend error codes where the touched flows need them
  - extract rules page plan-tier and tab/copy logic out of `page.tsx` into typed frontend helpers
  - improve observability when the immediate discovery subprocess fails
  - add focused frontend coverage for the changed login/signup/rules UX

## Exploration

- Auggie semantic retrieval was available and used for the initial map.
- Exact file inspection confirmed these current hotspots:
  - `apps/api/src/egp_api/routes/auth.py` returns mostly plain `detail` strings and only one structured code today (`workspace_slug_required`).
  - `apps/api/src/egp_api/routes/rules.py` still returns plain `detail` strings for entitlement and validation failures.
  - `apps/web/src/lib/api.ts` parses `code`, but `localizeApiError()` still primarily matches English `detail` substrings.
  - `apps/web/src/app/signup/page.tsx` still normalizes errors by checking English fragments like `password`, `short`, `email`, and `company_name`.
  - `apps/web/src/app/(app)/rules/page.tsx` still owns `resolvePlanTier()`, `tabsForPlan()`, `PLAN_DISPLAY`, and several plan-specific copy/behavior branches.
  - `apps/api/src/egp_api/main.py` still spawns the discover worker with `stdout` and `stderr` sent to `DEVNULL`, so subprocess failures are mostly invisible.

## Plan Draft A

### Overview

- Add small structured API error codes at the route layer for the affected auth and rules flows.
- Add a focused FastAPI validation-error handler that emits field-oriented codes for the auth and rules payloads we actually surface in the web app.
- Update frontend localization to prefer `ApiError.code` first, with English-detail substring matching as fallback only.
- Extract rules page plan/view logic into a typed helper module used by `page.tsx`.
- Improve discover spawner logging by capturing subprocess stderr and logging non-zero exits.

### Files To Change

- `apps/api/src/egp_api/routes/auth.py`
- `apps/api/src/egp_api/routes/rules.py`
- `apps/api/src/egp_api/main.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/signup/page.tsx`
- `apps/web/src/app/(app)/rules/page.tsx`
- `apps/web/src/app/(app)/rules/` helper module(s), likely new
- `tests/phase4/test_auth_api.py`
- `tests/phase2/test_rules_api.py`
- `tests/phase2/test_immediate_discover.py`
- `apps/web/tests/e2e/auth-pages.spec.ts`
- `apps/web/tests/e2e/` new rules-focused spec
- `.opencode/coding-log.current`
- `.codex/coding-log.current`

### Implementation Steps

1. Add backend RED tests for structured auth and rules error codes.
2. Add backend RED tests for the immediate discovery subprocess logging contract if practical at the helper level, otherwise extend current immediate-discover tests around logged failures.
3. Add frontend RED e2e coverage for signup Thai validation/account-exists messaging and rules-page plan/tab behavior.
4. Implement the smallest backend route changes to emit stable `code` values for the touched auth/rules failures.
5. Implement the smallest app-level validation error handler needed to convert selected 422 payloads into predictable field codes while preserving useful `detail` text.
6. Update `ApiError` localization to prefer code-based Thai mapping first and fallback to legacy detail matching only when no code exists.
7. Simplify signup error handling to consume stable codes instead of English string parsing.
8. Extract rules view logic into a typed helper and update `page.tsx` to consume it without changing visible UX beyond the intended cleanup.
9. Improve discover subprocess observability in `_make_discover_spawner()` and keep the route/processor wiring unchanged.
10. Run focused validation gates, then broader typecheck/build as needed.

### Test Coverage

- Backend:
  - `tests/phase4/test_auth_api.py`
  - `tests/phase2/test_rules_api.py`
  - `tests/phase2/test_immediate_discover.py`
- Frontend:
  - `apps/web/tests/e2e/auth-pages.spec.ts`
  - new `apps/web/tests/e2e/rules-page.spec.ts`

### Decision Completeness

- Goal: stable user-facing Thai errors for touched flows, smaller rules page view logic, and better immediate-discovery failure visibility.
- Non-goals:
  - no repo-wide migration of every API error to structured codes in this slice
  - no backend capability-contract redesign for rules entitlements
  - no worker runtime redesign or queue semantics changes
- Success criteria:
  - login/signup/rules UI no longer depends on fragile English wording for the covered cases
  - rules page plan/tab/copy helpers are extracted and typed
  - discover subprocess failures produce actionable API logs
  - targeted tests pass
- Changed public interfaces:
  - API JSON error bodies for covered auth/rules failures gain stable `code` fields
  - selected 422 responses gain structured codes in the error body
- Edge cases:
  - preserve Thai-friendly fallback when an unknown backend error arrives without a code
  - preserve existing auth behavior/status codes
  - preserve immediate dispatch durability and test override behavior
- Rollout/backout:
  - safe, additive API error-body change; web will still keep detail fallback
  - helper extraction is internal-only and low-risk to revert

### Dependencies

- Existing FastAPI exception handling and route-layer error mapping
- Existing `ApiError.code` support in `apps/web/src/lib/api.ts`
- Existing rules page query contract from `fetchRules()` / `useRules()`
- Existing immediate-discovery queue/processor wiring in `apps/api/src/egp_api/main.py`

### Validation

- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
- `./.venv/bin/ruff check apps/api packages`
- `./.venv/bin/python -m compileall apps/api/src packages`
- `(cd apps/web && npm test -- auth-pages.spec.ts rules-page.spec.ts)` if supported; otherwise `npx playwright test ...`
- `(cd apps/web && npm run typecheck)`
- `(cd apps/web && npm run build)`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| auth/rules structured error codes | route exception paths | `apps/api/src/egp_api/routes/auth.py`, `apps/api/src/egp_api/routes/rules.py` | none |
| selected validation error code mapping | FastAPI exception handling | `apps/api/src/egp_api/main.py` | none |
| code-first API localization | web API/client helpers | `apps/web/src/lib/api.ts` | none |
| signup code-based error display | `/signup` submit path | `apps/web/src/app/signup/page.tsx` | none |
| rules page view helper | `/rules` page render | `apps/web/src/app/(app)/rules/page.tsx` plus new helper module | none |
| discover subprocess failure logging | discovery dispatch processor -> app state spawner | `apps/api/src/egp_api/main.py` | `discovery_jobs` |

## Plan Draft B

### Overview

- Limit backend changes to route-generated `code` fields for known failure cases and keep 422 payload shape unchanged.
- Move only frontend pages away from English matching by reading `ApiError.code` where available and retaining a smaller fallback map for old responses.
- Extract only the rules plan/tab model first, leaving some page-local copy branches in place if that keeps the change tighter.
- Log subprocess launch failures and non-zero exits, but avoid changing stdout/stderr capture strategy unless a focused test proves it safe.

### Files To Change

- Same core files as Draft A, but the new frontend helper scope stays narrower.

### Implementation Steps

1. RED backend tests for route-level `code` fields in auth and rules failures.
2. RED frontend e2e tests for signup duplicate/validation handling and rules tabs.
3. Implement route-level `code` values only for the concrete cases already surfaced in login/signup/rules UI.
4. Update `localizeApiError()` to prefer `code` and fallback to legacy detail matching.
5. Refactor signup page to use the new codes and keep one simple generic fallback.
6. Extract rules plan/tab display config into a small helper module and keep the rest of the component intact.
7. Log subprocess failures with exit code and a bounded stderr preview.
8. Run focused validation.

### Test Coverage

- Same focused backend tests.
- Same Playwright coverage, but no new unit-style frontend tests.

### Decision Completeness

- Goal: practical hardening with minimum surface area.
- Non-goals: generic validation-code framework and deep rules-page architecture changes.
- Success criteria: covered UI flows rely on stable codes where the backend now provides them; rules page shrinks modestly; immediate-discovery failures are visible.
- Changed public interfaces: only selected route error bodies gain `code`.
- Edge cases: untouched endpoints may still return plain details and must keep working through frontend fallback.
- Rollout/backout: very low-risk and incremental.

### Dependencies

- Same as Draft A.

### Validation

- Same focused validation gates as Draft A.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| route-level auth/rules error codes | route exception paths | `apps/api/src/egp_api/routes/auth.py`, `apps/api/src/egp_api/routes/rules.py` | none |
| code-first localization | shared web API helper | `apps/web/src/lib/api.ts` | none |
| rules plan model helper | `/rules` page render | new helper imported by `apps/web/src/app/(app)/rules/page.tsx` | none |
| discover subprocess logging | discovery dispatch processor -> app spawner | `apps/api/src/egp_api/main.py` | `discovery_jobs` |

## Comparative Analysis

- Draft A gives a cleaner long-term base by handling selected validation errors at the app level instead of leaving 422 parsing logic scattered in the frontend.
- Draft B is smaller, but it leaves the signup validation path partly coupled to unstable FastAPI wording unless more frontend special-casing remains.
- Draft A better addresses the concrete review concern about brittle localization while still keeping scope bounded to touched flows.
- Draft B is useful as a fallback if the validation handler turns out to be noisier than expected, but it is weaker on the root cause.

## Unified Execution Plan

### Overview

- Follow Draft A for covered auth/signup/rules flows, but keep the backend validation-code mapper intentionally narrow.
- Prefer additive `code` fields over changing status codes or replacing readable `detail` text.
- Extract a small rules view-model/helper module that owns plan tier resolution, tab definitions, badge/copy, and header subtitle selection.
- Improve discover spawner logging with bounded stderr capture and explicit non-zero exit logging.

### Files To Change

- `apps/api/src/egp_api/routes/auth.py`
- `apps/api/src/egp_api/routes/rules.py`
- `apps/api/src/egp_api/main.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/signup/page.tsx`
- `apps/web/src/app/(app)/rules/page.tsx`
- `apps/web/src/app/(app)/rules/` new helper module
- `tests/phase4/test_auth_api.py`
- `tests/phase2/test_rules_api.py`
- `tests/phase2/test_immediate_discover.py`
- `apps/web/tests/e2e/auth-pages.spec.ts`
- `apps/web/tests/e2e/rules-page.spec.ts`

### Implementation Steps

1. Backend RED tests:
   - auth register duplicate-email response includes a stable code
   - auth reset/invite/verify/MFA failures that the frontend localizes include stable codes where touched by current pages
   - rules entitlement and validation failures include stable codes
   - selected payload-validation failures return predictable field codes
2. Frontend RED tests:
   - signup duplicate-email and validation errors render Thai messages without relying on English detail text
   - rules page shows the correct tabs and plan copy for free-trial, one-time, and monthly states
3. Implement narrow backend error-code helpers:
   - add small JSON error helpers in auth/rules routes where exceptions are already mapped
   - add a narrow `RequestValidationError` handler in `create_app()` that emits `code` values for covered auth/rules fields while keeping the default detail payload available enough for debugging
4. Implement frontend code-first localization:
   - add a code-to-Thai map in `apps/web/src/lib/api.ts`
   - make `localizeApiError()` use `error.code` first, then fallback to existing detail matching
   - simplify signup page error normalization to code-based branches only where needed
5. Extract rules page view logic:
   - move plan tier resolution, tab config, plan display config, and header subtitle selection into a typed helper module under the rules route directory
   - update `page.tsx` to consume the helper with no behavior drift
6. Improve immediate discovery observability:
   - capture stderr from the worker subprocess
   - log timeout, spawn exceptions, and non-zero exit codes with keyword/profile context and a bounded stderr preview
   - keep success path quiet enough to avoid noisy logs
7. Run focused validation, then broader compile/type/build checks as needed.

### Test Coverage

- Backend:
  - `tests/phase4/test_auth_api.py`
  - `tests/phase2/test_rules_api.py`
  - `tests/phase2/test_immediate_discover.py`
- Frontend:
  - `apps/web/tests/e2e/auth-pages.spec.ts`
  - `apps/web/tests/e2e/rules-page.spec.ts`

### Decision Completeness

- Goal:
  - remove brittle English-string coupling in the touched web flows
  - reduce rules page view logic density
  - improve observability for immediate discovery failures
- Non-goals:
  - migrate every endpoint to a universal error-code taxonomy
  - redesign rules entitlements into a backend capability contract
  - alter durable discovery semantics or worker API shape
- Measurable success criteria:
  - covered API errors return stable `code` fields
  - signup/login/rules e2e assertions do not depend on backend English detail text for the covered paths
  - rules page helper extraction reduces plan-specific branching in `page.tsx`
  - subprocess failures show actionable logs with exit/timeout context
- Changed public interfaces:
  - additive `code` field on covered auth/rules JSON error responses
  - additive `code` field on selected validation errors for covered request payloads
- Edge cases and failure modes:
  - unknown codes still fall back to Thai generic messaging
  - legacy plain-detail errors still localize through fallback matching
  - subprocess stderr may be empty; logs must still include exit/timeout context
  - schedule/rules behavior must stay identical by plan tier after extraction
- Rollout/backout expectations:
  - additive and low-risk; if needed, frontend fallback preserves compatibility with older responses
- Concrete acceptance checks:
  - focused pytest and Playwright suites pass
  - `npm run typecheck` and `npm run build` pass
  - `ruff` and `compileall` pass for touched Python code

### Dependencies

- Existing FastAPI route exception paths and middleware wiring
- Existing `ApiError.code` plumbing in `apps/web/src/lib/api.ts`
- Existing rules response shape from `/v1/rules`
- Existing durable discovery queue and dispatcher wiring

### Validation

- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
- `./.venv/bin/ruff check apps/api packages`
- `./.venv/bin/python -m compileall apps/api/src packages`
- `(cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts)`
- `(cd apps/web && npm run typecheck)`
- `(cd apps/web && npm run build)`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| auth structured errors | `POST /v1/auth/*` failure paths | `apps/api/src/egp_api/routes/auth.py` | none |
| rules structured errors | `POST /v1/rules/profiles` failure paths | `apps/api/src/egp_api/routes/rules.py` | none |
| selected validation code mapping | FastAPI exception handler | `apps/api/src/egp_api/main.py` | none |
| code-first frontend localization | all pages using `localizeApiError()` / `throwApiError()` | `apps/web/src/lib/api.ts` | none |
| signup code-based messaging | `/signup` submit flow | `apps/web/src/app/signup/page.tsx` | none |
| rules page plan view-model | `/rules` route render path | new helper imported by `apps/web/src/app/(app)/rules/page.tsx` | none |
| discover subprocess observability | queue dispatch -> `discover_spawner` | `apps/api/src/egp_api/main.py` | `discovery_jobs` |

## Implementation (2026-04-07 14:48:47 +07)

### Goal

- Ship the medium-risk hardening slice:
  - structured backend error codes for covered auth and rules failures
  - code-first Thai localization in the web client
  - extracted rules plan/tab/header view model
  - better logging around immediate discovery spawn failures

### What Changed By File

- `apps/api/src/egp_api/routes/auth.py`
  - Added a small auth error-code map and JSON helper.
  - Covered login/register/reset/invite/verify/MFA route failures now return additive `code` fields while keeping the existing `detail` strings and status codes.
- `apps/api/src/egp_api/routes/rules.py`
  - Added structured codes for rules validation and entitlement failures.
  - Kept route behavior and immediate-dispatch scheduling unchanged.
- `apps/api/src/egp_api/main.py`
  - Added a narrow `RequestValidationError` handler that emits stable codes for the touched auth/rules payload validation cases while preserving the underlying 422 `detail` list.
- `apps/web/src/lib/api.ts`
  - Added code-first Thai translation mapping.
  - `localizeApiError()` now prefers `ApiError.code` before falling back to the legacy English-detail translation list.
- `apps/web/src/app/signup/page.tsx`
  - Replaced brittle English substring parsing with code-based handling for duplicate-account and validation cases.
  - Preserved generic 422 and generic fallback behavior.
- `apps/web/src/app/(app)/rules/view-model.tsx`
  - New typed helper module for plan-tier resolution, tab definitions, plan display metadata, and header subtitle selection.
- `apps/web/src/app/(app)/rules/page.tsx`
  - Removed inline plan-tier/tab/header model logic and switched to the new helper.
  - Kept page behavior and copy unchanged other than sourcing it from the helper.
- `tests/phase4/test_auth_api.py`
  - Added coverage for register duplicate-email code, register validation code, MFA invalid-code response, and updated the wrong-password expectation for the additive auth code.
- `tests/phase2/test_rules_api.py`
  - Added assertions for structured rules error codes on entitlement and blank-name failures.
- `tests/phase2/test_immediate_discover.py`
  - Added coverage that `_make_discover_spawner()` logs keyword context when subprocess creation fails.
- `apps/web/tests/e2e/auth-pages.spec.ts`
  - Added signup coverage for duplicate-account and password-validation messages driven by stable backend codes.
- `apps/web/tests/e2e/rules-page.spec.ts`
  - Added focused rules page coverage for free-trial, one-time, and monthly plan tab/copy behavior.

### TDD Evidence

- Tests added/changed:
  - `tests/phase4/test_auth_api.py`
  - `tests/phase2/test_rules_api.py`
  - `tests/phase2/test_immediate_discover.py`
  - `apps/web/tests/e2e/auth-pages.spec.ts`
  - `apps/web/tests/e2e/rules-page.spec.ts`
- RED command:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
- RED failure reason:
  - route responses were missing `code` fields
  - 422 validation responses had no structured code
  - discover spawn logging coverage found no keyword-context warning path for the helper seam under test
- GREEN backend command:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
- GREEN frontend command:
  - `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts`

### Tests Run And Results

- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
  - passed (`34 passed`)
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts`
  - passed (`13 passed`)
- `cd apps/web && npm run typecheck`
  - passed
- `./.venv/bin/ruff check apps/api packages`
  - passed
- `./.venv/bin/python -m compileall apps/api/src packages`
  - passed
- `cd apps/web && npm run build`
  - passed

### Wiring Verification Evidence

| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| auth structured error codes | YES | Verified by route reads in `apps/api/src/egp_api/routes/auth.py` and passing `tests/phase4/test_auth_api.py` coverage across login/register/reset/invite/verify/MFA paths |
| rules structured error codes | YES | Verified by route reads in `apps/api/src/egp_api/routes/rules.py` and passing `tests/phase2/test_rules_api.py` profile-creation failure coverage |
| selected validation code mapping | YES | Verified by `RequestValidationError` handler in `apps/api/src/egp_api/main.py` and passing register 422 test in `tests/phase4/test_auth_api.py` |
| code-first frontend localization | YES | Verified by `apps/web/src/lib/api.ts` call sites plus passing signup Playwright assertions in `apps/web/tests/e2e/auth-pages.spec.ts` |
| signup code-based messaging | YES | Verified by `apps/web/src/app/signup/page.tsx` import/use path and passing Playwright signup error spec |
| rules page view-model helper | YES | Verified by import and runtime use in `apps/web/src/app/(app)/rules/page.tsx` and passing `apps/web/tests/e2e/rules-page.spec.ts` |
| discover spawn failure logging | YES | Verified by `_make_discover_spawner()` call path in `apps/api/src/egp_api/main.py` and passing `tests/phase2/test_immediate_discover.py` helper-level logging coverage |

### Behavior Changes And Risk Notes

- Covered auth and rules error responses now include additive `code` fields; clients that ignore them remain compatible.
- `localizeApiError()` is now safer for the covered flows because wording changes in backend `detail` text no longer break Thai messaging when a known code is present.
- Rules page visual behavior is intended to remain unchanged; risk is low because the extraction is internal and covered by focused Playwright specs.
- Immediate-discovery observability is improved for spawn exceptions through tested warning logs, but this slice did not yet add stderr/non-zero-exit capture from the subprocess itself.

### Follow-Ups And Known Gaps

- Extend structured codes beyond the touched auth/rules surfaces if we want substring fallback to become rare across the rest of the app.
- Consider adding stderr/non-zero-exit logging in `_make_discover_spawner()` as a follow-up if we want deeper worker failure observability beyond spawn exceptions.
- If desired, add repeat-run flake checks for the focused Playwright/backend suites in a follow-up pass.

## Follow-Up Implementation (2026-04-07 15:17:52 +07)

### Goal

- Finish the remaining immediate-discovery observability hardening and complete a formal skeptical review of the current slice.

### What Changed By File

- `apps/api/src/egp_api/main.py`
  - `_make_discover_spawner()` now captures worker `stderr`, logs non-zero exits with a bounded stderr preview, and handles `TimeoutExpired` by killing the subprocess and logging timeout context.
  - Spawn-exception logging now includes `tenant_id` and `profile_id` alongside `keyword`.
- `tests/phase2/test_immediate_discover.py`
  - Added RED/GREEN coverage for non-zero exit logging with stderr preview.
  - Added RED/GREEN coverage for timeout cleanup and timeout-context logging.
- `apps/web/src/app/login/page.tsx`
  - Updated MFA reveal and messaging logic to use stable backend codes (`mfa_code_required`, `invalid_mfa_code`, `invalid_credentials`) instead of raw English details.
- `apps/web/tests/e2e/auth-pages.spec.ts`
  - Updated the MFA-required mocked response to return the new code so the auth spec validates the code-based path.

### TDD Evidence

- Tests added/changed:
  - `tests/phase2/test_immediate_discover.py`
  - `apps/web/src/app/login/page.tsx`
  - `apps/web/tests/e2e/auth-pages.spec.ts`
- RED command:
  - `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py -q`
- RED failure reason:
  - `_make_discover_spawner()` did not log non-zero worker exits, did not preserve stderr summaries, and did not kill/wait on timeout.
- GREEN command:
  - `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py -q`

### Tests Run And Results

- `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py -q`
  - passed (`7 passed`)
- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
  - passed (`36 passed`)
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts tests/e2e/rules-page.spec.ts`
  - passed (`13 passed`)
- `./.venv/bin/ruff check apps/api packages && ./.venv/bin/python -m compileall apps/api/src packages`
  - passed
- `cd apps/web && npm run typecheck && npm run build`
  - passed
- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
  - passed (`21 passed`)
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts`
  - passed (`10 passed`)

### Wiring Verification Evidence

| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| discover worker stderr / exit-code logging | YES | Verified in `_make_discover_spawner()` call path in `apps/api/src/egp_api/main.py` and passing helper-level tests in `tests/phase2/test_immediate_discover.py` |
| login MFA code-based UI path | YES | Verified in `apps/web/src/app/login/page.tsx` and passing `apps/web/tests/e2e/auth-pages.spec.ts` MFA flow |

### Behavior Changes And Risk Notes

- Immediate discovery failures are now more diagnosable from API logs because non-zero exit and timeout cases include context plus a bounded stderr preview.
- Successful subprocess completion remains behaviorally unchanged.
- Logging still keeps `stdout` discarded; this is intentional to avoid noisy logs while retaining worker error context.

## Review (2026-04-07 15:17:52 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: current working tree
- Scope: `working-tree`
- Commands Run:
  - `git status --porcelain=v1`
  - targeted file reads for `apps/api/src/egp_api/main.py`, `apps/api/src/egp_api/routes/auth.py`, `apps/api/src/egp_api/routes/rules.py`, `apps/web/src/lib/api.ts`, `apps/web/src/app/login/page.tsx`, `apps/web/src/app/signup/page.tsx`, `apps/web/src/app/(app)/rules/view-model.tsx`, `tests/phase2/test_immediate_discover.py`
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
  - `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts`

### Findings
MEDIUM
- `apps/web/src/app/login/page.tsx` originally still depended on English `detail` text for MFA-required, invalid-MFA, and invalid-credentials handling even after the backend and shared client had moved to stable error codes. This would silently regress the login MFA UX if backend wording changed. Fixed during the review by switching the login page to use `mfa_code_required`, `invalid_mfa_code`, and `invalid_credentials` codes, then rerunning focused auth backend and Playwright coverage.

### Open Questions / Assumptions
- No findings remain after the login MFA code-path fix.
- Review scope was limited to the current medium-risk slice and its immediate runtime wiring, not the unrelated pre-existing working tree changes.

### Recommended Tests / Validation
- No additional tests required beyond the focused suites already rerun for this slice.
- Optional follow-up: repeat the focused backend and Playwright suites 3x if we want an explicit flake check pass.

### Rollout Notes
- Error-code additions are additive and backward-compatible for existing clients.
- API logging volume increases only on failure paths for immediate discovery worker spawning.
