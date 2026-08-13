# Coding Log: Document and Run Route RBAC

Started: 2026-08-13 17:45:25 +0700
Branch: `fix/document-run-rbac`
Baseline: `0f4d24db892ac75aaab968996ac8ff3c79de2105`
DREP: `coding-logs/2026-08-13-17-45-25 DREP (document-run-rbac).md`

## Planning and discovery

- PR #211 safe-next-path was admin-squash-merged and exact-landed before this worktree.
- RepoPrompt mapped all 13 routes, auth dependencies, services, repositories, tests, and worker boundary.
- Independent Terra found viewer mutation access, foreign-project document/task association, and the
  foreign-run 403 existence oracle. The DREP was revised before RED to include these requested
  wrong-tenant cases.
- Constructor inventory found a standalone discovery `RunService` used only for missing-worker
  reconciliation. API composition will supply the project repository; any project-linked task on an
  instance without it fails closed. No discovery production file is changed.
- PRIMARY-only under g2 Q1; no DeepSeek doctor, egress, handoff, or product editing.

## Protected baseline

- Never stage `.venv` or `apps/web/node_modules`.
- Do not touch the primary checkout's dirty files or any prior/F6 worktree.

## RED acceptance contract

- Primary-authored acceptance suite: `tests/phase4/test_document_run_rbac.py`.
- Final RED test hash: `c20d7d383ecfcf61cdea55c4ca3fe77f5c184079213b5ef91a3bfce3005c8ddb`.
- After correcting only test-fixture issues (artifact-root ownership and the existing `approve` enum),
  RED is **8 failed, 2 passed**.
- Intended failures: unknown authenticated roles read successfully; viewer mutation succeeds; worker
  token elevates no role but viewer JWT still mutates; foreign-project document ingest and task
  creation both return 201; foreign run IDs return distinct 403 while missing IDs return 404.
- Passing RED cases confirm global missing-auth 401 and explicit supplied-tenant mismatch 403 are
  already authoritative and must be preserved.

## Compatibility correction

- The first existing-suite run found that strict project existence inside the shared document
  domain service broke 12 auth-disabled/direct-worker storage tests that intentionally ingest without
  a project row. This would violate the worker-automation preservation contract.
- Ownership enforcement was narrowed to authenticated public `/v1/documents/ingest` before the
  service call, using the already wired tenant-aware project repository. Direct workers and
  auth-disabled compatibility remain unchanged; the authenticated exploit/no-side-effect oracle
  remains authoritative.

## GREEN and gates

- Linked-worktree tests use explicit worktree-first `PYTHONPATH`; the shared ignored `.venv` remains
  correctly bound to the protected primary checkout and is never staged.
- Focused security suite: **10 passed** for three consecutive runs.
- Existing document/run/infrastructure/internal-worker/entitlement matrix: **103 passed**.
- Existing authorization-convention matrix: **69 passed**.
- Full Python: **1605 passed, 2 skipped, 113 warnings** in 221.38s.
- Full Playwright: **47 passed**.
- Frontend unit: **83 passed**; API types, TypeScript, ESLint, production build all passed.
- Full repository ruff lint, changed-file formatting, compile, and migration manifest (**41 files**)
  all passed.
- Call-site audit: all 13 route decorators have the selected dependency. The API `RunService`
  receives the project repository; the standalone discovery instance only exposes missing-worker
  reconciliation and never creates tasks. No internal route/schema/generated frontend file changed.

## Independent QCHECK

- Disposition: **PASS — no actionable findings**.
- Independently verified role/dependency coverage, tenant-scoped project and run lookups, uniform
  foreign/missing run behavior, worker-token separation, constructor wiring, and the full changed
  file set.
- Worktree-correct rerun: **10 focused RBAC tests passed** and **86 compatibility tests passed**.
- `git diff --check origin/main` was clean; no QCHECK edits were made.

## Formal g-check and remediation

- Initial disposition: **CHANGES REQUIRED**.
- P1 fixed: run creation now validates caller-controlled `profile_id` through a tenant-scoped
  profile lookup before entitlement/persistence; foreign/missing profiles are uniform 404s.
- P1 fixed: authenticated document project preflight now remains inside the route's `ValueError`
  mapping, preserving malformed-ID 422 rather than an unhandled 500.
- P2 fixed: added missing-project no-side-effect cases and a compact owner/admin/support/analyst
  read/mutation matrix.
- Machine-local `.venv` and `apps/web/node_modules` symlinks remain untracked setup artifacts and
  are explicitly excluded from staging.
- Remediation RED: **2 failed, 16 passed**, each for the intended new boundary. Remediation GREEN:
  **18 passed**. Compatibility rerun: **125 passed**.
- Second formal pass found the analogous malformed task-project 500. Added primary RED
  (**1 failed, 20 passed**), mapped repository `ValueError` to 422, and expanded missing/foreign/
  malformed profile coverage.
- Final focused suite: **21 passed**; compatibility matrix: **125 passed**; changed-file Ruff format,
  Ruff lint, and `git diff --check` passed.
- Final formal disposition: **PASS — no P0, P1, or P2 findings**.
