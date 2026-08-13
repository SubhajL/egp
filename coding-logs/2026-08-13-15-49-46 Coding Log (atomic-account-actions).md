# Coding Log: Atomic Account Actions

Started: 2026-08-13 15:49:46 +0700  
Branch: `fix/atomic-account-actions`  
Baseline: `ffbe4338f6b7c896936cdc12f5e82cebe9b3e96f`  
DREP: `coding-logs/2026-08-13-15-49-46 DREP (atomic-account-actions).md`

## Planning and discovery

- Environment-parity PR #209 was admin-squash-merged and exact-landed before this worktree was created.
- Session worktree: `/Users/subhajlimanond/dev/egp-g2-atomic-account-actions`, clean from `origin/main` except an untracked `.venv` link; intended disposition is removal after merged exact-SHA landing.
- RepoPrompt bound to the exact worktree and ran one focused context build across routes, service, repository, schema, callers, and real-PostgreSQL tests.
- Independent read-only Terra challenge confirmed the unlocked select/unconditional update race, pre-action token burn, missing token/user tenant-equality predicate, and lack of active checks in verification.
- DREP decision: conditional PostgreSQL update-returning is the single winner authority. Association/inactivity failures raise inside the transaction so consumption rolls back before service error translation.
- No migration is needed. Migrations 001/010/011 already provide the required fields/indexes.
- Delegation: PRIMARY by g2 Q1. No DeepSeek doctor, egress, handoff, or production editing.

## Protected baseline

- Do not stage `.venv`.
- Do not inspect or modify F6/crawler work.
- Production-file scope is only `auth_repo.py` and `auth_service.py`; acceptance tests are primary-owned.

## TDD slice: atomic invite, reset, and verification

- Primary-authored acceptance test: `tests/operations/test_atomic_account_actions.py`.
- Initial RED command: `./.venv/bin/python -m pytest tests/operations/test_atomic_account_actions.py::test_each_account_action_has_exactly_one_postgres_winner -q`.
- Expected and observed RED: collection failed only because `AccountActionTargetInactiveError` and the purpose-specific atomic repository methods did not exist. This exact missing export was the planned introduced contract; no fixture or dependency failure occurred.
- Initial acceptance-test SHA-256: `67e3bfafd6c8d3d7774cf65f1d708af06487352dd1a0822f39a7a1320325ff9d`.
- Worktree import correction: the shared ignored virtualenv points editable packages at the primary checkout. All implementation tests therefore use explicit worktree-first `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/domain/src:packages/crawler-core/src:packages/notification-core/src:packages/observability/src` so stale main cannot produce false GREEN.
- Implementation is PRIMARY-only in `auth_repo.py` and `auth_service.py`; no delegate or other product-code writer ran.
- Design: conditional `UPDATE ... RETURNING` predicates hash, purpose, unconsumed state, and database `CURRENT_TIMESTAMP` expiry. Invalid association and inactive targets raise inside the transaction so the claim rolls back before normal error translation.
- Real-PostgreSQL concurrency GREEN: `test_each_account_action_has_exactly_one_postgres_winner` — **3 passed**, one per purpose.
- Complete real-PostgreSQL contract matrix — **21 passed**: concurrency, replay, expiry, wrong purpose, tenant/user mismatch, inactive tenant/user, injected protected-write rollback, and retry.
- Integrated repository + route scope — **49 passed**.
- Route coverage preserves exact replay error codes for invite/reset/verification and proves inactive verification leaves its token retryable after reactivation.
- Call-site audit: `consume_account_action_token` has no definition or reference; each atomic repository method has exactly one production caller in `AuthService`.
- Scoped lint passed after removing one unused test import. Scoped formatter changed only `auth_repo.py` and the new test; all four scoped files now pass format check.

## Final GREEN and gates

- Acceptance scope repeated three consecutive times: **49 passed** in 11.87s, **49 passed** in 11.43s, **49 passed** in 12.50s.
- Broader auth/admin/PostgreSQL gate: **115 passed** (final rerun 31.89s).
- Migration manifest: **41 files verified** with `scripts/check_migration_manifest.py --check`; the first invocation omitted required `--check` and was a usage error, not a manifest failure.
- Full compile: passed.
- Full ruff lint over apps/packages/tests/scripts: passed.
- Full Python suite with explicit worktree-first `PYTHONPATH`: **1591 passed, 2 skipped, 112 pre-existing SQLAlchemy/sqlite warnings** in 228.84s.
- Frontend first attempt failed at dependency resolution because the clean helper worktree had no `node_modules`; no meaningful typecheck ran.
- Worktree setup correction: linked ignored `apps/web/node_modules` to the primary checkout's existing dependency tree; no tracked file changed.
- Frontend typecheck: passed.
- Frontend lint: passed with zero warnings.
- Frontend production build: passed; existing Node `module.register()` deprecation and Next edge-runtime static-generation warnings remain informational.
- Test-hardening pass added password-state, correct-action-after-wrong-purpose, full unchanged-state, thread-termination, replay-no-second-effect, and reset-cookie-revocation assertions. One temporary test-only `NameError` from the previously removed `verify_password` import was corrected; final scope is **49 passed**.

## Wiring evidence

- `/v1/auth/invite/accept` -> `AuthService.accept_invite()` -> `SqlAuthRepository.accept_invite_atomically()` -> conditional token claim + users update + user_sessions insert.
- `/v1/auth/password/reset` -> `AuthService.reset_password()` -> `SqlAuthRepository.reset_password_atomically()` -> conditional token claim + users update + active user_sessions revocation.
- `/v1/auth/email/verify` -> `AuthService.verify_email()` -> `SqlAuthRepository.verify_email_atomically()` -> conditional token claim + users verification update.
- Bootstrap registration is unchanged: one shared `SqlAuthRepository` instance remains in the repository bundle and `AuthService` composition.
- Schema matches migrations 001/010/011; no migration or manifest bytes changed.

## Independent QCHECK and remediation

- First QCHECK finding (MEDIUM): hashing before token validation changed invalid-token + short-password requests from the established invalid-token 400 to an uncaught validation error. Remediated with a service-owned zero-argument password-hash factory invoked only after conditional claim and active-target validation inside the repository transaction.
- Regression evidence: invalid/replayed invite and reset tokens with one-character passwords retain exact `invalid_*_token` 400 responses; a valid token with a weak password rolls back and succeeds on retry.
- QCHECK re-review confirmed invalid-token precedence and transaction/secret boundaries, then found valid weak passwords still surfaced as HTTP 500. Remediated with the explicit route contract: HTTP 400, detail `password must be at least 12 characters`, code `password_too_short`.
- Mismatch test strengthened to snapshot both original and corrupt-target users plus both reset sessions when applicable; every password, verification, session, revocation, and token field remains unchanged.
- Post-remediation scoped GREEN: **53 passed**.
- Post-remediation affected scope repeated three times: **53 passed** in 12.32s, **53 passed** in 11.71s, **53 passed** in 12.48s.

## Review (2026-08-13 16:43:00 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-g2-atomic-account-actions`
- Branch: `fix/atomic-account-actions`
- Scope: working tree against `ffbe4338f6b7c896936cdc12f5e82cebe9b3e96f`
- Commands Run: changed-file/call-site audit; real-PostgreSQL acceptance and rollback tests; route tests; full Python/lint/compile/migration/frontend gates; RepoPrompt formal review.

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- P2 lifecycle contract mismatch: DREP FN4 documented a `LoginUserRecord | None` return and an unused returned token ID, while implementation returns `(user, tenant_id, user_id) | None` and SQL returns only tenant/user IDs.

LOW
- No findings.

### Open Questions / Assumptions
- Mixed-version old API replicas must be drained promptly; no migration sequencing is required.
- PostgreSQL is the concurrency oracle; SQLite route tests are integration/error-contract evidence only.

### Recommended Tests / Validation
- Preserve the 21-test real-PostgreSQL matrix and 53-test integrated scope.
- Re-run changed-surface gates after any product-code remediation.
- Re-review the corrected DREP against the exact function signature and SQL `RETURNING` list.

### Rollout Notes
- Replace/drain old API replicas together. Monitor purpose-specific 400s and database errors without logging secrets or tokens.
- Code-only rollback is mechanically possible but reintroduces the original race.

### Formal disposition
- P2 accepted and remediated in documentation only: FN4 now exactly matches the implemented tuple and SQL result.
- Product code/tests unchanged by this disposition; previous GREEN evidence remains exact.
