# Coding Log: Safe Frontend Next-Path Normalization

Started: 2026-08-13 17:09:22 +0700
Branch: `fix/safe-next-path`
Baseline: `237c40bac1df645b673bee4dd34dff21a84e1ff1`
DREP: `coding-logs/2026-08-13-17-09-22 DREP (safe-next-path).md`

## Planning and discovery

- PR #210 (atomic account actions) was admin-squash-merged and exact-landed before this worktree.
- Session worktree is clean from `origin/main`; ignored `.venv` and `apps/web/node_modules` links are
  protected setup and will never be staged.
- RepoPrompt was bound to the exact worktree and produced a focused plan across the helper, every
  login/signup navigation sink, unit/browser tests, and CI topology.
- Independent read-only Terra reconnaissance confirmed `/\\attacker.invalid`, mixed separator, and
  ASCII control forms pass the prefix guard and resolve cross-origin under WHATWG rules.
- Policy decision: reject suspicious separator spellings in the pathname, including encoded
  separators; allow such text only in query/fragment when full parsing remains same-origin.
- Implementation is PRIMARY-owned by g2 Q1 because this is a security boundary. No DeepSeek doctor,
  egress, handoff, or production editing is permitted.

## Protected baseline

- Do not stage `.venv` or `apps/web/node_modules`.
- Do not inspect or modify F6/crawler work or the primary checkout's pre-existing dirty files.
- Planned product/test scope is exactly `auth.ts`, `auth.test.ts`, and `auth-pages.spec.ts`.

## TDD slice: safe next paths

- Primary-authored acceptance tests are `apps/web/tests/unit/auth.test.ts` and the hostile `@critical`
  cases in `apps/web/tests/e2e/auth-pages.spec.ts`.
- RED hashes: unit `30d701548beff668b20cdf78a300dc41e69ce164844468220cd020363e55aae4`;
  browser `9394da70d282f8723c73aac5f3d5dd5ac91e95475df335790ddc53ed931e8d9b`.
- Unit RED: **14 failed, 18 passed, 2 skipped** in the focused file. Every failure was a planned
  mixed/backslash/control/encoded-path/fallback case returning the unsafe candidate.
- Chromium RED: **4 failed**. Login, signup, and authenticated navigation left the application and
  reached `chrome-error://chromewebdata/`; login-to-signup propagated `/\\attacker.invalid/path`.
- No fixture, dependency, server-start, or unrelated assertion failure contaminated RED.
- First browser GREEN attempt proved all four flows reached `/dashboard`, but three test-only origin
  assertions incorrectly expected port 3000 while Playwright config authoritatively uses 3100. The
  hostile trap also covered only HTTPS despite the HTTP test base. The acceptance harness was
  corrected to capture the runtime app origin and trap both HTTP/HTTPS; no production contract or
  implementation changed.

## GREEN and gates

- Implementation remained PRIMARY-only and changed only `apps/web/src/lib/auth.ts`: pathname
  separator screening plus dual-base WHATWG origin/user-info validation, validated fallback, and
  terminal `/dashboard`.
- Focused unit scope: **34 passed**; focused hostile Chromium scope: **4 passed**. Both scopes passed
  three consecutive times after the test-harness correction.
- Full frontend unit: **83 passed** across 12 files.
- Full Playwright: **47 passed**, including all hostile `@critical` cases and preserved valid
  `/security` login/signup flows.
- API type freshness, TypeScript typecheck, ESLint with zero warnings, and Next production build all
  passed. Informational Node deprecation and Next edge-runtime static-generation warnings persist.
- Frozen lock check and full repository ruff lint passed. Full compile passed.
- Whole-tree ruff format check remains independently red on **44 pre-existing Python files**, none
  changed by this frontend PR; no unrelated formatting was applied.
- Full Python suite: **1594 passed, 2 skipped, 1 failed**. The sole failure was unrelated
  `test_dispatch_renews_lease_during_blocking_worker`; isolated feature-worktree reruns were one pass
  and one fail, while exact landed `main` passed three consecutive times. No Python source/test file
  differs in this PR, so this is recorded as a timing-sensitive non-regression gate failure rather
  than hidden or remediated here.
- Main-sync check confirmed branch and `origin/main` SHA equality at baseline but correctly reported
  `ok=false` because the intended worktree changes and protected setup links are uncommitted.

## Independent QCHECK

- Independent read-only Terra QCHECK found no actionable findings across the complete tracked diff,
  WHATWG behavior, all navigation sinks, fallback handling, and CI test selection.
- Independent reruns: focused unit **34 passed**, complete auth browser spec **18 passed**, and diff
  whitespace check clean.

## Review (2026-08-13 17:28:00 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-g2-safe-next-path`
- Branch: `fix/safe-next-path`
- Scope: complete intended tracked change against
  `237c40bac1df645b673bee4dd34dff21a84e1ff1`
- Evidence: selected diff artifacts, shared helper, every runtime sink, unit/Chromium tests, CI
  selection, DREP, and gate record.

### Findings

CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings.

LOW
- No findings.

### Formal disposition

- **APPROVED — no actionable findings.**
- WHATWG dual-base same-origin validation, pathname encoded-separator boundary, validated fallback,
  all login/signup sinks, browser tests, and `@critical` CI selection are correct and complete.
- `.venv` and `apps/web/node_modules` are local lifecycle setup only and must remain unstaged.
- The unrelated Python lease flake and pre-existing whole-tree formatter failures are accurately
  disclosed and do not change this frontend security disposition.
