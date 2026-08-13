# DREP: Safe Frontend Next-Path Normalization

## 0. Repository profile

- Root: `/Users/subhajlimanond/dev/egp-g2-safe-next-path`
- Branch: `fix/safe-next-path`
- Baseline: `237c40bac1df645b673bee4dd34dff21a84e1ff1` (`origin/main`)
- Baseline status: clean tracked tree; ignored/untracked `.venv` and `apps/web/node_modules`
  links are protected setup and never staged.
- Policies: root `AGENTS.md`, `CLAUDE.md`, and `apps/web/AGENTS.md`.
- Stack: Next.js 15, React 19, strict TypeScript, Vitest, Playwright Chromium.
- Coding Log: `coding-logs/2026-08-13-17-09-22 Coding Log (safe-next-path).md`.
- External egress: user selected g2, but this security boundary is PRIMARY-owned under Q1. No
  DeepSeek doctor or handoff.
- Scoped gates: `apps/web/tests/unit/auth.test.ts` and hostile `@critical` auth Playwright tests.
- Full gates: frontend pre-PR gate, repository Python gates, and exact main-sync validation.
- Migration policy: no migration, schema, API, environment, or dependency change.

## 1. Goal, non-goals, and success

Make every value returned by `normalizeNextPath` a deterministic same-origin, app-relative
destination under WHATWG URL semantics. Reject suspicious separator spellings instead of
canonicalizing them.

Safe candidates retain their exact path, query, and fragment. Unsafe candidates use the validated
fallback; an unsafe fallback uses terminal `/dashboard`. The default remains `/dashboard`.

Non-goals: consumer-page refactors, preserving protected-route query strings, external allowlists,
server middleware, auth/session behavior, billing precedence, backend/API/schema changes,
dependencies, F6, or any other security-train item.

Success criteria:

- Literal scheme-relative, backslash, mixed-separator, control-separated authority, absolute URL,
  and pathname-encoded separator inputs fail closed.
- Every accepted result resolves to the trusted origin with no user-info under WHATWG semantics.
- Valid internal destinations preserve exact path, query, and fragment behavior.
- Login, signup, authenticated redirect, and login-to-signup handoff cannot leave the app origin.
- New hostile browser regressions are tagged `@critical` and existing `/security` flows remain green.
- Only the three planned product/test files and this DREP/log land.

Public interface: `normalizeNextPath(value, fallback?) -> string` is unchanged. Only unsafe inputs'
observable result becomes the safe fallback. Failure is synchronous and fail-closed; parser errors
never escape.

Rollout is one independent frontend PR with no flag or migration. Rollback is code-only but restores
the open redirect and therefore requires an immediate corrected security patch.

## 2. Requirements

- **R1** Output is a root-relative application path, never a scheme, authority, or relative path.
- **R2** Accepted output resolved by WHATWG parsing retains the trusted protocol, host, port, and
  origin, with empty username/password.
- **R3** Null, empty, relative, absolute, scheme-like, literal `//`, backslash, mixed separator,
  control-separated authority, and browser-interpreted absolute forms fail closed.
- **R4** Before the first `?` or `#`, reject literal backslash and case-insensitive `%2f` or `%5c`.
- **R5** Encoded slash/backslash text occurring only in query or fragment remains valid when the
  complete destination is same-origin.
- **R6** Validation applies after the query parser's single decoding layer; outer-query cases must
  prove exposed hostile separators are rejected without speculative recursive decoding.
- **R7** Valid candidates retain their exact original path, query, and fragment string.
- **R8** The optional fallback is validated under the same contract; invalid fallback terminates at
  compile-time-known `/dashboard`.
- **R9** Existing billing-overdue precedence and valid `/security` continuation remain unchanged.
- **R10** The shared helper protects login/signup already-authenticated navigation, post-auth hard
  navigation, and login-to-signup propagation.
- **R11** Every hostile Chromium regression is selected by CI through `@critical`.

## 3. File contract

| ID | Path | Action | Anchor | Contract | Purpose |
|---|---|---|---|---|---|
| F1 | `apps/web/tests/unit/auth.test.ts` | MODIFY | new `normalizeNextPath` suite | tests only | parser-backed RED matrix |
| F2 | `apps/web/tests/e2e/auth-pages.spec.ts` | MODIFY | auth continuation tests | tests only | real Chromium sink coverage |
| F3 | `apps/web/src/lib/auth.ts` | MODIFY | `normalizeNextPath` | public signature unchanged | central URL policy |

No login/signup/layout/config/package/lockfile/backend/migration file is in scope.

## 4. Function contract

**FN1 `normalizeNextPath(value, fallback = "/dashboard") -> string` (F3)**

- Preserve the public signature and accepted candidate text.
- Call private FN2 for the candidate. If accepted, return it unchanged.
- Otherwise call FN2 for fallback. If accepted, return it unchanged.
- Otherwise return `/dashboard` without recursion.
- Never read browser globals, current origin, storage, time, or mutable state.

**FN2 private `normalizeSafeAppDestination(candidate) -> string | null` (F3)**

- Reject empty/non-root-relative candidates.
- Isolate pathname before the earliest `?`/`#`; reject literal backslash and `%2f`/`%5c`
  case-insensitively there.
- Resolve the complete candidate against two distinct fixed HTTPS sentinel bases using `new URL`.
- Require each resolution to retain its base origin and empty username/password.
- Return the original candidate on success, otherwise `null`; parsing exceptions fail closed.
- Dual bases prevent an authority-like input naming one sentinel from becoming a false acceptance.

Complexity is linear in input length with two constant parser calls. The function is pure,
idempotent, synchronous, and concurrency-independent.

## 5. Test contract

**T1 parser-semantic unit matrix (F1)**

- Valid: `/dashboard`, `/security`, path+query+fragment, and encoded separator text in query/hash.
- Invalid: null/empty/relative, absolute/scheme-like, `//` and `///`, literal backslash, `/\\host`,
  `/\\/host`, deeper backslash, tab/newline/CR authority forms, and pathname `%2f`/`%5c` in mixed
  case.
- `URLSearchParams` cases model the consumer's one decode layer.
- Every result is parsed against a trusted base and asserted same-origin with exact expected URL.
- Valid and invalid custom fallback cases prove R8.
- RED command: `npm run test:unit -- tests/unit/auth.test.ts -t "normalizes next paths"`.
- Predicted RED: current prefix guard returns mixed-separator and pathname-encoded inputs unchanged.

**T2 hostile browser continuations (F2)**

- Successful login and signup with hostile `next` finish at same-origin `/dashboard` and never reach
  a trapped reserved attacker origin.
- Already-authenticated login and signup with hostile `next` finish at `/dashboard`.
- `registration_required` forwards only `/dashboard`; valid `/security` handoff is preserved.
- All hostile titles contain `hostile next` and `@critical`.
- RED command: `./scripts/run-playwright.sh tests/e2e/auth-pages.spec.ts --grep "hostile next"`.
- Predicted RED: current hard navigation or router navigation follows the browser-interpreted foreign
  authority, or the unsafe value is propagated to signup.

## 6. Traceability

| Requirements | Runtime realization | Tests | Files | Slice |
|---|---|---|---|---|
| R1-R3 | FN1/FN2 parser and relative-path policy | T1,T2 | F1-F3 | S1 |
| R4-R6 | pathname boundary and encoded-separator policy | T1 | F1,F3 | S1 |
| R7-R8 | exact accepted string + validated fallback | T1 | F1,F3 | S1 |
| R9 | consumers unchanged | existing + T2 | F2 | S1 |
| R10-R11 | central helper at all sinks + tagged Chromium cases | T2 | F2,F3 | S1 |

## 7. Wiring

| Route | Runtime path | Evidence |
|---|---|---|
| protected producer | layout -> `buildCurrentPath` -> encoded login query | existing `/security` test |
| login authenticated | decoded query -> FN1 -> billing check -> `router.replace` | T2 |
| login success | decoded query -> FN1 -> login/cache -> billing check -> `location.assign` | T2 + existing valid test |
| login to signup | FN1 -> `URLSearchParams.set` -> signup query -> FN1 | T2 |
| signup authenticated | decoded query -> FN1 -> billing check -> `router.replace` | T2 |
| signup success | decoded query -> FN1 -> register/cache -> `location.assign` | T2 + existing valid test |

Call-site inspection found only login and signup consumers and no custom-fallback runtime callers.
Their shared-helper wiring is already complete and must remain unchanged.

## 8. Slice plan

| ID | Requirements/files/tests | Owner | Q0-Q3 | Stop line | Oracle | Done when |
|---|---|---|---|---|---|---|
| S1 | R1-R11; F1-F3; T1-T2 | PRIMARY | Q1 security boundary | PRIMARY | Vitest matrix + Chromium sinks | gates, reviews, delivery exact |

No production delegation or allowlist exists. Independent Terra support was read-only and confirmed
the browser bypass/call-site map; PRIMARY owns RED, implementation, gates, review, and delivery.

Stop and revise if a new consumer/custom fallback, consumer-page edit, extra browser decode, new
dependency/config, backend/API/schema/migration change, or file outside F1-F3 becomes necessary.

## 9. Gates, review, rollout, and rollback

1. Author T1/T2 and confirm intended RED.
2. Implement F3 and confirm focused GREEN.
3. Repeat focused unit/browser scopes three times.
4. Run frontend unit, Playwright, API type, TypeScript, lint, and production-build gates.
5. Run repository uv-lock, ruff lint/format, compile, full Python, and exact main-sync gates.
6. Independent QCHECK followed by formal `g-check`; remediate and rerun material scopes.
7. Conventional commit, one PR, hosted-check evidence, authorized admin squash merge, and exact
   origin/local-main equality.
8. Remove only this session worktree and its feature refs.

Monitor post-release auth continuation errors and unexpected `/dashboard` fallbacks without logging
query data. Rollback is a revert of the three-file code/test change and restores the vulnerability.

## 10. Do-not-touch and baseline

Do not touch login/signup/layout production pages, `buildCurrentPath`, packages/lockfiles, configs,
backend, APIs, schemas, migrations, F6/crawler work, other security-train slices, lifecycle artifacts
except this DREP/log, or primary checkout dirt. Baseline:
`237c40bac1df645b673bee4dd34dff21a84e1ff1`.

Decision complete: requirements, functions, RED contracts, wiring, scope, stop lines, gates,
rollout, rollback, and PRIMARY ownership are locked before implementation.
