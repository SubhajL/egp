# DREP: Atomic Account Actions

## 0. Repository profile

- Root: `/Users/subhajlimanond/dev/egp-g2-atomic-account-actions`
- Branch: `fix/atomic-account-actions`
- Baseline: `ffbe4338f6b7c896936cdc12f5e82cebe9b3e96f` (`origin/main`)
- Baseline status: only untracked `.venv` link; protected setup, never staged.
- Policies: root `AGENTS.md`, `CLAUDE.md`, `apps/api/AGENTS.md`, `packages/db/AGENTS.md`.
- Stack: Python 3.12+, FastAPI, SQLAlchemy Core, PostgreSQL 15+, pytest.
- Coding Log: `coding-logs/2026-08-13-15-49-46 Coding Log (atomic-account-actions).md`.
- External egress: user selected g2, but S1 is PRIMARY by Q1 because it is authentication, security, tenancy, and concurrency. No DeepSeek doctor or handoff.
- Scoped gates: new real-PostgreSQL account-action tests; `tests/phase4/test_auth_api.py`; `tests/phase4/test_admin_api.py`.
- Full gates: repository lint/compile/test plus prescribed web gates and exact main-sync validation.
- Migration policy: no migration. Existing 001/010/011 schema is sufficient and immutable.

## 1. Goal, non-goals, and success

Make invite acceptance, password reset, and email verification one-time atomic database actions. A single conditional token claim and every purpose-specific protected mutation commit or roll back in one transaction; exactly one concurrent claimant succeeds.

Non-goals: token issuance/email delivery, MFA, login/registration transactions, session-auth performance, JWT policy, RBAC, SSRF, F6/crawler work, schema changes, generalized unit-of-work APIs, or public route/schema changes.

Success criteria:

- Invite claim + password + verification + session commit together.
- Reset claim + password + all-session revocation commit together.
- Verification claim + verified timestamp commit together.
- Exactly one of two concurrent PostgreSQL claimants succeeds for each purpose.
- Protected-action failure rolls back token consumption and every earlier effect.
- Replay, expiry, wrong action, tenant/user mismatch, inactive tenant, and inactive user fail closed without consuming the token.
- Exact existing route status codes, error codes/messages, and invite cookie contract remain.
- No migration, unsafe consume call site, or unrelated security change lands.

Public interfaces: existing success and invalid-token HTTP contracts remain. Valid-token password validation is explicitly normalized to HTTP 400 with detail `password must be at least 12 characters` and code `password_too_short`. No schema/env/CLI changes. Internal repository replaces `consume_account_action_token()` with three purpose-specific atomic methods and a result/exception contract.

Failure semantics: invalid/expired/replayed/wrong-purpose/association mismatch returns no result and is translated to the existing purpose-specific invalid-token error. Inactive target raises an internal typed error translated to `account is not active`; token remains unconsumed. SQL/connection/deadlock/trigger failures propagate and roll back. Fail closed.

Rollout: replace/drain all old API replicas promptly because mixed-version old processes retain the race. No DB sequencing. Rollback is code-only but reintroduces the vulnerability.

## 2. Requirements

- **R1** A conditional token update is the sole winner authority and predicates hash, exact purpose, unconsumed state, and database-time expiry.
- **R2** Token target resolution requires token tenant = user tenant = tenant row; mismatch fails closed and rolls back the claim.
- **R3** All three purposes require active tenant and active user before protected mutation; inactivity rolls back the claim.
- **R4** Invite atomically sets password, verifies email, inserts exactly one hashed session, and returns the raw session token only after commit.
- **R5** Reset atomically sets password and revokes every active session for the same tenant/user.
- **R6** Verification atomically sets the verified timestamp.
- **R7** Any protected SQL failure rolls back token consumption and all action effects, leaving the same token retryable when the failure is removed.
- **R8** Exactly one of two concurrent PostgreSQL claimants succeeds per purpose; the loser receives the normal invalid result.
- **R9** Replay, expiry, wrong purpose, mismatch, and inactivity preserve protected state and do not consume the token.
- **R10** Routes preserve exact success/cookie/error contracts.
- **R11** No unsafe generic consume method or production call site remains.

## 3. File contract

| ID | Path | Action | Anchor | Exports/contracts | Purpose |
|---|---|---|---|---|---|
| F1 | `tests/operations/test_atomic_account_actions.py` | CREATE | whole file | tests only | real-PG concurrency, rollback, invalid-state oracle |
| F2 | `tests/phase4/test_auth_api.py` | MODIFY | invite/reset/verification tests | tests only | preserve route/error/cookie contracts |
| F3 | `packages/db/src/egp_db/repositories/auth_repo.py` | MODIFY | account token/session methods | `AtomicInviteAcceptanceResult`, `AccountActionTargetInactiveError`, three atomic methods | transaction authority |
| F4 | `apps/api/src/egp_api/services/auth_service.py` | MODIFY | `accept_invite`, `reset_password`, `verify_email` | public signatures unchanged | integrate atomic methods and exact errors |
| F5 | `apps/api/src/egp_api/routes/auth.py` | MODIFY | invite/reset exception mapping and `AUTH_ERROR_CODES` | HTTP 400 `password_too_short` | preserve invalid-token precedence and normalize valid-token validation |

No other production file, test fixture, migration, manifest, or route is in scope.

## 4. Function contract

**FN1 `accept_invite_atomically(*, token, password_hash_factory, session_expires_in_seconds) -> AtomicInviteAcceptanceResult | None` (F3)**

- Pre: service supplies a zero-argument password-hash factory; raw token may be invalid.
- Post: one transaction conditionally claims an invite token, validates exact tenant/user association and active states, updates password+verification, inserts one hashed session, rereads the user, commits, and returns user+raw session token.
- Errors: invalid states return `None`; inactive raises `AccountActionTargetInactiveError`; SQL exceptions propagate and roll back.
- Invariants: repository receives only the service-owned hash callback, invokes it after claim/target validation inside the transaction, never stores raw password or raw session token, and rolls back the claim if hashing fails.
- Caller: `AuthService.accept_invite()` only.

**FN2 `reset_password_atomically(*, token, password_hash_factory) -> bool` (F3)**

- Pre: service supplies a zero-argument password-hash factory.
- Post: claim, tenant-scoped password update, and all active-session revocations commit once.
- Errors/invariants: as FN1; no sessions is a valid success.
- Caller: `AuthService.reset_password()` only.

**FN3 `verify_email_atomically(*, token) -> bool` (F3)**

- Post: claim and tenant-scoped email verification commit once for an active target.
- Errors/invariants: as FN1; already verified remains a valid action if a live token was issued.
- Caller: `AuthService.verify_email()` only.

**FN4 `_claim_account_action_target(connection, *, token, purpose) -> tuple[LoginUserRecord, str, str] | None` (F3)**

- Performs `UPDATE account_action_tokens SET consumed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE token_hash=:hash AND purpose=:purpose AND consumed_at IS NULL AND expires_at > CURRENT_TIMESTAMP RETURNING tenant_id,user_id`, then returns `(validated_user, tenant_id, user_id)` after exact association/activity checks.
- A zero-row return is invalid. Then locks/reads the associated user+tenant with exact tenant equality. Association absence raises a private rollback sentinel caught outside the transaction and returned as invalid. Inactivity raises the typed inactive error outside the transaction. Both exceptions force rollback of the claim.
- Same claim algorithm and lock order for all actions.

**FN5 service methods (F4)**

- Supply a service-owned password-hash callback for invite/reset. It executes only after an eligible target is claimed, preserving invalid-token error precedence; any validation/hash failure rolls the claim back.
- Map no-result and inactive typed errors to the existing exact `PermissionError` strings.
- Invite builds `LoginResult` from the returned user/session without a second write.

## 5. Test contract

**T1 `test_each_account_action_has_exactly_one_postgres_winner` (F1)**

- Covers: R1,R4-R6,R8.
- Arrange: migrated PostgreSQL, one active tenant/user/token per purpose, reset session where relevant, two synchronized independent threads.
- Assert: one success, one invalid result, one consumed row, exactly one purpose effect.
- RED command: `./.venv/bin/python -m pytest tests/operations/test_atomic_account_actions.py::test_each_account_action_has_exactly_one_postgres_winner -q`
- RED proof: current repository lacks all three atomic methods (contract absence) and current consume flow cannot satisfy the adapter.

**T2 `test_each_account_action_rolls_back_claim_when_protected_write_fails` (F1)**

- Covers: R4-R7.
- Arrange: per-purpose PostgreSQL trigger raises on session insert, session revoke, or user verification update after claim.
- Assert: operation raises; token stays unconsumed; password/verification/sessions unchanged; removing trigger permits same token to succeed.

**T3 `test_each_account_action_rejects_wrong_purpose_expiry_and_replay` (F1)**

- Covers: R1,R8,R9.
- Assert invalid result, no consumption/effect; correct action remains usable for wrong-purpose token.

**T4 `test_each_account_action_rejects_tenant_user_mismatch` (F1)**

- Covers: R2,R9.
- Direct-seed valid tenant A token targeting user B from tenant B; assert invalid, unconsumed, no mutation.

**T5 `test_each_account_action_rejects_inactive_target_without_consuming` (F1)**

- Covers: R3,R9.
- Parameterize inactive tenant and suspended/deactivated user; assert typed inactive error and unchanged token/effects.

**T6 route regression additions in F2**

- Covers: R10.
- Assert invite cookie/success/replay, reset success/replay/session revocation, verification success/replay, and exact inactive response while token remains usable after reactivation.

All real-PG tests use `TempPostgresCluster` + canonical `apply_migrations`; SQLite is never concurrency authority.

## 6. Traceability

| Requirement | Runtime realization | Tests | Files | Slice |
|---|---|---|---|---|
| R1 | FN4 conditional update-returning | T1,T3 | F1,F3 | S1 |
| R2 | FN4 exact association query + rollback sentinel | T4 | F1,F3 | S1 |
| R3 | FN4 active predicate + typed rollback | T5,T6 | F1-F4 | S1 |
| R4 | FN1 | T1,T2,T6 | F1-F4 | S1 |
| R5 | FN2 | T1,T2,T6 | F1-F4 | S1 |
| R6 | FN3 | T1,T2,T6 | F1-F4 | S1 |
| R7 | engine transaction + propagated trigger failure | T2 | F1,F3,F4 | S1 |
| R8 | FN4 row-count/return authority | T1,T3 | F1,F3 | S1 |
| R9 | FN4 predicates/sentinels | T3-T5 | F1,F3 | S1 |
| R10 | FN5 route integration and explicit validation mapping | T6 | F2,F4,F5 | S1 |
| R11 | removal plus exact call-site search | T1-T6 + `rg` | F3,F4 | S1 |

## 7. Wiring

| Component | Non-test runtime caller | Registration/config load | Schema/contract evidence |
|---|---|---|---|
| FN1 | `AuthService.accept_invite` -> `/v1/auth/invite/accept` | existing `SqlAuthRepository` in repository bundle and `AuthService` bootstrap | users, tenants, account_action_tokens, user_sessions in migrations 001/010/011 |
| FN2 | `AuthService.reset_password` -> `/v1/auth/password/reset` | same | same |
| FN3 | `AuthService.verify_email` -> `/v1/auth/email/verify` | same | users, tenants, account_action_tokens |
| FN4 | FN1-FN3 only | private helper in repository | token hash/purpose/expiry/consumed fields and independent tenant/user FKs verified |

## 8. Slice plan

| ID | Requirements/files/tests | Owner | Q0-Q3 result | Stop line | Production allowlist | Oracle | Done when |
|---|---|---|---|---|---|---|---|
| S1 | R1-R11; F1-F4; T1-T6 | PRIMARY | Q1: auth/security/tenancy/concurrency prohibited | PRIMARY | none | real-PG T1-T5 + route T6 | primary verifies gates/reviews/delivery |

Stop and revise the DREP if schema, migration, another route/public contract, external I/O, another repository, or any file outside F1-F5 is required.

## 9. Gates, review, rollout, and rollback

1. Author F1/F2 acceptance tests and confirm exact expected RED.
2. Implement F3/F4 only; confirm GREEN.
3. Repeat affected scopes three consecutive times.
4. Verify `rg` has no unsafe consume call or method.
5. Run scoped lint/format/compile, PostgreSQL tests, full Python suite, frontend gates, migration manifest, and main-sync check.
6. Independent non-implementer QCHECK, then formal `g-check`; remediate and rerun when material.
7. Conventional commit, one PR, hosted-check evidence, authorized admin squash merge, exact remote/local main equality.
8. Close the session worktree under the worktree-closeout protocol.

Monitoring: observe action-specific 400 rates and database errors after rollout; never log tokens or password/session material. Replace all old API replicas promptly. Exact rollback is code revert with no data migration, but it restores the old race.

## 10. Do-not-touch and baseline

Do not touch routes other than F5, schemas, migrations/manifests, fixtures, F6/crawler files, JWT/RBAC/SSRF/session-auth slices, lifecycle artifacts except this DREP/log, `.venv`, Git state outside primary-owned delivery, or any file outside F1-F5. Baseline: `ffbe4338f6b7c896936cdc12f5e82cebe9b3e96f`; acceptance tests are primary-owned and their hashes are recorded after RED.

Decision-complete checklist: all IDs resolve; every requirement has runtime realization and a failing test; all new components have wiring; exact public/failure/rollout/rollback contracts are locked; no DeepSeek slice exists; no architecture or migration decision is left to implementation.
