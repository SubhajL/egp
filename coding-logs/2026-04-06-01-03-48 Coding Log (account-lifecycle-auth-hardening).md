# Plan Draft A

## Overview
- Extend the existing cookie-session auth system into a usable account lifecycle: invite-only onboarding, password reset, explicit email verification, and optional TOTP MFA.
- Keep the design inside the current API/web apps and shared DB package. Reuse the already-wired SMTP/email sender path in `NotificationService` instead of creating a separate mail service.

## Files to Change
- `packages/db/src/migrations/011_auth_lifecycle.sql`: add user verification/MFA columns and a durable token table for invite/reset/verify flows.
- `packages/db/src/egp_db/repositories/auth_repo.py`: add token issuance/consumption, MFA secret storage, email verification updates, and login lookups that include MFA state.
- `packages/db/src/egp_db/repositories/notification_repo.py`: align `users` table metadata with new auth columns.
- `apps/api/src/egp_api/services/auth_service.py`: add invite acceptance, forgot/reset password, verification send/consume, and MFA setup/enable/disable/login verification orchestration.
- `apps/api/src/egp_api/routes/auth.py`: expose public auth lifecycle endpoints and authenticated MFA/email endpoints.
- `apps/api/src/egp_api/services/admin_service.py`: add invite issuance for tenant admins.
- `apps/api/src/egp_api/routes/admin.py`: add admin invite endpoint and response models.
- `apps/api/src/egp_api/main.py`: wire auth email sender/service dependencies if needed.
- `apps/web/src/lib/api.ts`: add auth lifecycle request/response helpers and remove normal tenant-scoped `tenant_id` query/body usage.
- `apps/web/src/lib/hooks.ts`: add hooks for current auth lifecycle queries if needed.
- `apps/web/src/lib/auth.ts`: add shared auth lifecycle helpers for invite/reset/verify pages.
- `apps/web/src/app/login/page.tsx`: add optional MFA code handling and verification-state messaging.
- `apps/web/src/app/invite/page.tsx`: accept invite token, set password, create session.
- `apps/web/src/app/forgot-password/page.tsx`: request reset email.
- `apps/web/src/app/reset-password/page.tsx`: consume reset token and set new password.
- `apps/web/src/app/verify-email/page.tsx`: consume verification token and show result.
- `apps/web/src/app/(app)/admin/page.tsx`: add invite actions and remove tenant_id for normal tenant-scoped admin calls.
- `tests/phase4/test_auth_api.py`: add invite/reset/verify/MFA coverage.
- `tests/phase4/test_admin_api.py`: add invite issuance coverage.
- `docs/FRONTEND_HANDOFF.md`: document new auth lifecycle endpoints and frontend pages.

## Implementation Steps
- TDD sequence (REQUIRED):
  1. Extend `tests/phase4/test_auth_api.py` with invite accept, forgot/reset, verify email, MFA login/setup cases; extend `tests/phase4/test_admin_api.py` with invite issuance.
  2. Run the targeted pytest slice and confirm RED for missing schema/routes/behavior.
  3. Implement the DB schema and repository primitives first.
  4. Implement service-layer orchestration and route handlers.
  5. Implement minimal frontend pages/forms and remove legacy tenant-scoped inputs from normal tenant flows.
  6. Run targeted pytest, web typecheck/lint/build, and narrow lint/compile checks.
- `SqlAuthRepository.create_auth_token(...)`:
  - Generate raw opaque tokens, persist only token hashes, scope by `tenant_id` and `user_id`, and attach a `purpose`.
  - Revoke prior active tokens for the same purpose/user when the flow should be single-use (invite/reset/verify).
- `SqlAuthRepository.consume_auth_token(...)`:
  - Resolve hashed token, ensure purpose matches, ensure token is unexpired and unconsumed, mark consumed, and return the associated user context.
- `SqlAuthRepository.set_password(...)` / `mark_email_verified(...)` / `set_mfa_secret(...)` / `set_mfa_enabled(...)`:
  - Update the user record explicitly and fail closed on missing users.
- `AuthService.issue_user_invite(...)`:
  - Validate admin-created target user, mint invite token, and send an email containing the invite URL.
- `AuthService.accept_invite(...)`:
  - Consume invite token, set password, mark email verified, and create a session.
- `AuthService.request_password_reset(...)` / `reset_password(...)`:
  - Return generic success for the request path to avoid user enumeration.
  - Consume reset token, set password, optionally revoke stale sessions, and return success.
- `AuthService.send_email_verification(...)` / `verify_email(...)`:
  - Issue single-use verification tokens and mark the user verified on successful consumption.
- `AuthService.setup_mfa(...)` / `enable_mfa(...)` / `disable_mfa(...)`:
  - Use TOTP-compatible secrets and verify codes with a small time-step window.
- `AuthService.login(...)`:
  - If MFA is enabled, require a valid `mfa_code`; otherwise fail closed with a specific message.
- `routes/auth` additions:
  - Public: `POST /v1/auth/password/forgot`, `POST /v1/auth/password/reset`, `POST /v1/auth/invite/accept`, `GET|POST /v1/auth/email/verify`.
  - Authenticated: `POST /v1/auth/email/verification/send`, `POST /v1/auth/mfa/setup`, `POST /v1/auth/mfa/enable`, `POST /v1/auth/mfa/disable`.
- Frontend behavior:
  - Login form gains optional MFA code input.
  - Invite/reset/verify pages use token query params and render clear success/failure states.
  - Normal tenant-scoped admin/data calls stop passing `tenant_id`; support-specific override flows keep it.

## Test Coverage
- `tests/phase4/test_auth_api.py::test_accept_invite_sets_password_marks_email_verified_and_creates_session`
  - Invite token activates account and session.
- `tests/phase4/test_auth_api.py::test_forgot_password_is_generic_and_reset_token_rotates_password`
  - Forgot path avoids enumeration; reset changes password.
- `tests/phase4/test_auth_api.py::test_email_verification_token_marks_user_verified`
  - Verification token updates verification state.
- `tests/phase4/test_auth_api.py::test_login_requires_valid_mfa_code_when_enabled`
  - MFA-enabled users cannot log in without code.
- `tests/phase4/test_auth_api.py::test_mfa_setup_enable_and_disable_round_trip`
  - MFA enrollment and disable path work.
- `tests/phase4/test_admin_api.py::test_admin_can_issue_invite_for_existing_user`
  - Admin invite endpoint sends a tokenized invite.
- `tests/phase4/test_admin_api.py::test_support_override_flows_still_accept_explicit_tenant_id`
  - Cross-tenant support flows keep override semantics.

## Decision Completeness
- Goal:
  - Deliver practical account lifecycle features on top of the new session model and remove leftover frontend tenant-scoping crutches.
- Non-goals:
  - External identity providers, WebAuthn, SMS MFA, recovery codes, SCIM, or audit/event-bus refactors.
- Success criteria:
  - Tenant admin can issue an invite email for a user.
  - Invited user can accept the invite, set a password, and become verified.
  - A user can request and complete password reset.
  - A user can request and complete email verification.
  - A user can enable MFA and must provide a valid MFA code on subsequent logins.
  - Normal frontend tenant-scoped requests no longer send `tenant_id`.
- Public interfaces:
  - New API endpoints under `/v1/auth/*` and `/v1/admin/users/*`.
  - New migration `011_auth_lifecycle.sql`.
  - New web pages `/invite`, `/forgot-password`, `/reset-password`, `/verify-email`.
  - Login payload adds optional `mfa_code`.
- Edge cases / failure modes:
  - Expired/consumed token: fail closed with 400/401.
  - Unknown email on forgot-password: return 202 without disclosure.
  - Invite for suspended/deactivated user: fail closed.
  - MFA secret present but not enabled: login does not require code until enable completes.
  - Invalid TOTP code: fail closed.
- Rollout & monitoring:
  - Existing logins continue to work for users without MFA enabled.
  - Existing accounts remain usable even if `email_verified_at` is null; verification is additive, not a breaking gate.
  - Monitor login failures by reason, invite/reset token consumption success, and SMTP failures.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/ruff check apps/api packages`
  - `(cd apps/web && npm run typecheck && npm run lint && npm run build)`

## Dependencies
- Python stdlib `hmac`, `hashlib`, `base64`, `secrets` for TOTP/token primitives.
- Existing SMTP/email sender wiring through `NotificationService`.

## Validation
- Automated:
  - targeted auth/admin pytest slice, ruff, web typecheck/lint/build.
- Manual:
  - create user, issue invite, accept invite, enable MFA, log out, log back in with MFA, request password reset, verify email.

## Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `011_auth_lifecycle.sql` | migration/bootstrap schema creation | repo creation through shared SQLAlchemy metadata + migration runner | `users`, `auth_tokens` |
| auth token repository methods in `auth_repo.py` | auth/admin services | imported into `AuthService` and `AdminService` via `create_app()` | `auth_tokens`, `users` |
| invite/reset/verify/MFA methods in `AuthService` | auth/admin route handlers | `app.state.auth_service` in `create_app()` | `users`, `auth_tokens`, `user_sessions` |
| admin invite route | `POST /v1/admin/users/{user_id}/invite` | `include_router(admin_router)` in `create_app()` | N/A |
| auth lifecycle routes | `/v1/auth/...` | `include_router(auth_router)` in `create_app()` | N/A |
| invite/reset/verify web pages | Next route pages | `src/app/*/page.tsx` filesystem routing | N/A |

# Plan Draft B

## Overview
- Keep the initial implementation smaller by using one generic account-action token table and email-only verification/MFA bootstrap UX, while limiting frontend work to the login page plus invite/reset/verify pages.
- Defer self-service MFA management UI depth and keep admin UI changes minimal by attaching invite issuance to existing user creation/edit surfaces.

## Files to Change
- Same backend auth/admin/web files as Draft A, but no new standalone settings/security page.
- `apps/web/src/app/(app)/admin/page.tsx`: only add invite issuance controls and tenant cleanup.
- `apps/web/src/app/login/page.tsx`: add MFA code field and links to forgot-password.

## Implementation Steps
- TDD sequence mirrors Draft A.
- Meaningful differences:
  - Use a single `account_action_tokens` table with `purpose` values `invite`, `password_reset`, `email_verification`.
  - Add a public `POST /v1/auth/invite/accept` that both verifies the email and sets the password in one step.
  - Add authenticated `POST /v1/auth/email/verification/send` and public `POST /v1/auth/email/verify`.
  - MFA remains TOTP-based, but setup is entirely API-driven plus a login-page field; no dedicated UI beyond setup response payload exposure for now.
  - Frontend `tenant_id` cleanup is scoped to non-support routes only, leaving support/admin override paths explicit.

## Test Coverage
- Same test files as Draft A, but UI verification remains indirect through build/typecheck rather than page-specific tests.

## Decision Completeness
- Goal:
  - Ship the smallest secure account lifecycle that materially improves onboarding and recovery.
- Non-goals:
  - Rich account settings UX, QR-code generation, or mandatory verification gating for all existing users.
- Success criteria:
  - Invite, reset, verify, and MFA all work through API and minimal UI.
  - Support-mode tenant overrides still function.
  - Ordinary tenant UI no longer passes `tenant_id`.
- Public interfaces:
  - Same endpoint set as Draft A, but no extra frontend security route.
- Edge cases / failure modes:
  - Same as Draft A.
- Rollout & monitoring:
  - Same as Draft A, with explicit choice to keep existing users login-compatible even if unverified.
- Acceptance checks:
  - Same as Draft A.

## Dependencies
- Same as Draft A.

## Validation
- Same as Draft A.

## Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `account_action_tokens` schema | auth/admin lifecycle methods | shared repo metadata + migration | `account_action_tokens` |
| TOTP helpers in `auth_service.py` or `auth_repo.py` | login + MFA routes | called from `AuthService` | `users` |
| admin invite UI actions | admin page user controls | filesystem route `src/app/(app)/admin/page.tsx` | N/A |

# Comparative Analysis & Synthesis

## Strengths
- Draft A is more explicit about dedicated responsibilities and leaves room for future self-service account settings.
- Draft B is more pragmatic: fewer moving parts, less UI sprawl, and a tighter first increment.

## Gaps
- Draft A risks overbuilding the UI layer for a first pass.
- Draft B underspecifies exactly how email sending is surfaced to tests and how MFA enrollment data is exposed to the user.

## Trade-offs
- Both drafts use the same backend foundation. The main difference is UX scope.
- Draft A optimizes for completeness; Draft B optimizes for getting secure lifecycle primitives landed quickly without a broad frontend redesign.

## Compliance
- Both drafts stay within current app/package boundaries, preserve tenant scoping, follow TDD, and avoid introducing a new service.

# Unified Execution Plan

## Overview
- Implement a single, durable account-action token system that supports invite acceptance, password reset, and email verification, then layer minimal TOTP MFA on top of the existing login/session model.
- Keep the web work intentionally narrow: make the login page MFA-capable, add invite/reset/verify pages, and remove `tenant_id` from normal tenant-scoped requests while preserving support override flows.

## Files to Change
- `packages/db/src/migrations/011_auth_lifecycle.sql`: add `users.email_verified_at`, `users.mfa_secret`, `users.mfa_enabled`, and `account_action_tokens`.
- `packages/db/src/egp_db/repositories/auth_repo.py`: token issue/consume/revoke, verification/MFA persistence, MFA-aware user lookups.
- `packages/db/src/egp_db/repositories/notification_repo.py`: align `USERS_TABLE` with new auth columns.
- `apps/api/src/egp_api/services/auth_service.py`: invite/reset/verify/MFA orchestration plus mail composition.
- `apps/api/src/egp_api/routes/auth.py`: expose invite/reset/verify/MFA endpoints and add optional `mfa_code` to login.
- `apps/api/src/egp_api/services/admin_service.py`: add `invite_user(...)`.
- `apps/api/src/egp_api/routes/admin.py`: add invite endpoint.
- `apps/api/src/egp_api/main.py`: ensure auth mail dependencies stay wired for tests/runtime.
- `apps/web/src/lib/api.ts`: add invite/reset/verify/MFA helpers and remove non-support `tenant_id` parameters.
- `apps/web/src/lib/auth.ts`: shared token/query helper utilities.
- `apps/web/src/lib/hooks.ts`: only if new auth-session hooks are needed.
- `apps/web/src/app/login/page.tsx`: MFA input, forgot-password link, better auth error messaging.
- `apps/web/src/app/invite/page.tsx`: accept invite token + password.
- `apps/web/src/app/forgot-password/page.tsx`: submit reset request.
- `apps/web/src/app/reset-password/page.tsx`: reset password with token.
- `apps/web/src/app/verify-email/page.tsx`: verify email with token.
- `apps/web/src/app/(app)/admin/page.tsx`: invite action and normal-tenant cleanup.
- `tests/phase4/test_auth_api.py`: comprehensive auth lifecycle tests.
- `tests/phase4/test_admin_api.py`: admin invite tests.
- `docs/FRONTEND_HANDOFF.md`: document new flows and deprecate remaining `tenant_id` usage except support override.

## Implementation Steps
- TDD sequence (REQUIRED):
  1. Add auth lifecycle tests in `tests/phase4/test_auth_api.py` and invite tests in `tests/phase4/test_admin_api.py`.
  2. Run `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q` and confirm RED.
  3. Implement the schema/repository primitives in `packages/db`.
  4. Implement `AuthService`/`AdminService` and route handlers in `apps/api`.
  5. Implement the minimal web flows and `tenant_id` cleanup in `apps/web`.
  6. Run targeted gates: pytest, ruff, web typecheck/lint/build.
- Functions / methods:
  - `SqlAuthRepository.create_account_action_token(...)`: create single-use hashed tokens for `invite`, `password_reset`, `email_verification`.
  - `SqlAuthRepository.consume_account_action_token(...)`: validate and consume token atomically.
  - `SqlAuthRepository.mark_email_verified(...)`: set `email_verified_at`.
  - `SqlAuthRepository.update_password(...)`: store a new password hash.
  - `SqlAuthRepository.begin_mfa_setup(...)`: persist a generated secret with `mfa_enabled = false`.
  - `SqlAuthRepository.set_mfa_enabled(...)`: turn MFA on/off.
  - `AuthService.invite_user(...)`: issue invite token and send invite email.
  - `AuthService.accept_invite(...)`: consume invite, set password, verify email, create session.
  - `AuthService.request_password_reset(...)`: generic success response plus reset email when applicable.
  - `AuthService.reset_password(...)`: consume reset token and change password.
  - `AuthService.send_email_verification(...)` / `verify_email(...)`: verification lifecycle.
  - `AuthService.setup_mfa(...)` / `enable_mfa(...)` / `disable_mfa(...)`: TOTP enrollment lifecycle.
  - `AuthService.login(...)`: require valid `mfa_code` for MFA-enabled users.
- Expected behavior / edge cases:
  - Tokens are single-use and expire.
  - Forgot-password never reveals whether the email exists.
  - Invite acceptance both verifies email and provisions password in one flow.
  - Existing accounts without `email_verified_at` remain login-capable for backward compatibility.
  - Support-mode tenant selection remains explicit; tenant-scoped normal flows rely on session context only.

## Test Coverage
- `tests/phase4/test_auth_api.py::test_accept_invite_sets_password_marks_email_verified_and_creates_session`
  - Invite acceptance produces verified authenticated user.
- `tests/phase4/test_auth_api.py::test_forgot_password_returns_generic_success_for_unknown_email`
  - Forgot password avoids user enumeration.
- `tests/phase4/test_auth_api.py::test_reset_password_consumes_token_and_replaces_old_password`
  - Reset token is one-shot and rotates password.
- `tests/phase4/test_auth_api.py::test_send_and_consume_email_verification_token`
  - Verification token updates email state.
- `tests/phase4/test_auth_api.py::test_mfa_setup_enable_and_login_require_code`
  - TOTP MFA is enforced after enable.
- `tests/phase4/test_auth_api.py::test_mfa_disable_removes_login_requirement`
  - Disabling MFA restores password-only login.
- `tests/phase4/test_admin_api.py::test_admin_can_issue_invite_for_existing_user`
  - Invite issuance works through admin route.
- `tests/phase4/test_admin_api.py::test_admin_page_mutations_no_longer_require_tenant_id_for_current_tenant`
  - API contracts support session-derived tenant context where intended.

## Decision Completeness
- Goal:
  - Turn the new session model into a complete account lifecycle with onboarding, recovery, verification, and MFA, while cleaning up stale tenant-scoping in the frontend.
- Non-goals:
  - SSO/OIDC, WebAuthn, SMS MFA, recovery codes, or a dedicated account settings redesign.
- Success criteria:
  - Invite, reset, verify, and MFA flows work through API plus minimal web pages.
  - Login page supports MFA-enabled accounts.
  - Normal tenant-scoped frontend requests no longer send `tenant_id`.
  - Support override flows still function.
- Public interfaces:
  - New DB migration `011_auth_lifecycle.sql`.
  - New/changed endpoints:
    - `POST /v1/auth/login` with optional `mfa_code`
    - `POST /v1/auth/invite/accept`
    - `POST /v1/auth/password/forgot`
    - `POST /v1/auth/password/reset`
    - `POST /v1/auth/email/verification/send`
    - `POST /v1/auth/email/verify`
    - `POST /v1/auth/mfa/setup`
    - `POST /v1/auth/mfa/enable`
    - `POST /v1/auth/mfa/disable`
    - `POST /v1/admin/users/{user_id}/invite`
  - New web pages:
    - `/invite`
    - `/forgot-password`
    - `/reset-password`
    - `/verify-email`
- Edge cases / failure modes:
  - Invalid/expired/consumed tokens: fail closed.
  - Unknown email in forgot-password: return success-shaped response without disclosure.
  - Suspended/deactivated users: cannot accept invite, reset password, or log in.
  - Invalid MFA code: fail closed; no session issued.
  - Missing SMTP config with no injected sender: route logic still succeeds where appropriate in tests, but invite/reset/verify email delivery should fail loudly in production-oriented runs.
- Rollout & monitoring:
  - Feature is additive to the current auth model.
  - Backout path: stop surfacing new pages/endpoints while password login and bearer compatibility remain intact.
  - Watch SMTP failures, token-consumption failure rates, password reset request volume, and MFA login failures.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/ruff check apps/api packages`
  - `(cd apps/web && npm run typecheck)`
  - `(cd apps/web && npm run lint)`
  - `(cd apps/web && npm run build)`

## Dependencies
- Existing SMTP/email sender integration in `NotificationService`.
- Python stdlib crypto primitives for password/token/TOTP logic.

## Validation
- Automated:
  - targeted pytest auth/admin slice, `ruff`, web `typecheck`, `lint`, and `build`.
- Manual:
  - issue invite from admin, accept invite via browser, verify login, enable MFA, verify MFA login, request reset, complete reset, verify email token path.

## Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `011_auth_lifecycle.sql` | repo bootstrap / migration runner | shared metadata + migration runner sequence | `users`, `account_action_tokens` |
| account-action token methods in `auth_repo.py` | `AuthService` and `AdminService` | `create_auth_repository()` wired in `create_app()` | `account_action_tokens` |
| invite/reset/verify/MFA service methods | auth/admin route handlers | `app.state.auth_service` and `app.state.admin_service` | `users`, `account_action_tokens`, `user_sessions` |
| `POST /v1/admin/users/{user_id}/invite` | tenant admin action | `admin_router` included in `create_app()` | N/A |
| new `/v1/auth/*` lifecycle routes | public/authenticated browser/API calls | `auth_router` included in `create_app()` | N/A |
| `/invite`, `/forgot-password`, `/reset-password`, `/verify-email` pages | Next.js filesystem routes | `src/app/*/page.tsx` | N/A |

## Decision-Complete Checklist
- No open decisions remain for the implementer.
- Every new public interface is named.
- Every behavior change has tests listed.
- Validation commands are concrete and scoped.
- Wiring Verification covers migration, repo, services, routes, and pages.
- Rollout/backout is specified.

## Review (2026-04-06 01:21:40) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commit: 8c4b542
- Commands Run: git status --porcelain=v1; CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat; ./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q; ./.venv/bin/ruff check apps/api packages; (cd apps/web && npm run typecheck); (cd apps/web && npm run lint); (cd apps/web && npm run build)

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- Password reset is only operational when SMTP or an injected email sender is configured. The generic 202 response intentionally hides account existence, but also means an unconfigured environment will appear healthy while not delivering recovery mail.

LOW
- No frontend page-level tests exist yet; coverage currently relies on API pytest plus Next typecheck/build.

### Open Questions / Assumptions
- Assumed existing users should remain login-capable even if email_verified_at is null.
- Assumed support override should remain the only place where frontend tenant_id is still explicit.

### Recommended Tests / Validation
- Manual browser smoke: admin invite -> /invite acceptance -> /security MFA setup/disable -> forgot-password -> /reset-password -> /verify-email.
- Environment smoke with real SMTP config to validate invite/reset/verify delivery.

### Rollout Notes
- Configure EGP_SMTP_* and EGP_WEB_BASE_URL before relying on invite/reset/verify mail in non-test environments.
- 011_auth_lifecycle.sql must be applied before deploying the new API build.

## Implementation Summary (2026-04-06 07:43:42 +07)

### Goal
- Replace the public browser bearer-token bridge with real account lifecycle auth capabilities around the new cookie session model.
- Deliver invite acceptance, password reset, email verification, TOTP MFA, and frontend cleanup so normal tenant-scoped UI no longer sends `tenant_id`.

### What Changed
- `packages/db/src/migrations/011_auth_lifecycle.sql`
  - Added `users.email_verified_at`, `users.mfa_secret`, `users.mfa_enabled`, and new `account_action_tokens` table to support invite/reset/verify flows without overloading sessions.
- `packages/db/src/egp_db/repositories/auth_repo.py`
  - Added account-action token creation/consumption, email verification mutation, password reset mutation, MFA secret/state mutation, and session revocation helpers.
- `packages/db/src/egp_db/repositories/notification_repo.py`
  - Extended user record metadata so auth/admin APIs can surface email verification and MFA status.
- `packages/notification-core/src/egp_notifications/service.py`
  - Added `send_email_message(...)` so invite/reset/verification flows reuse the existing email transport abstraction instead of introducing ad hoc SMTP code in the API layer.
- `apps/api/src/egp_api/config.py`
  - Added `get_web_base_url(...)` for generating browser links inside invite/reset/verify emails.
- `apps/api/src/egp_api/auth.py`
  - Extended `AuthContext` to carry email verification and MFA state through authenticated request handling.
- `apps/api/src/egp_api/services/auth_service.py`
  - Implemented invite issuance/acceptance, forgot/reset password, verification email send/consume, MFA setup/enable/disable, and MFA-gated login.
- `apps/api/src/egp_api/routes/auth.py`
  - Added public routes for invite accept, password reset request/reset, and email verification plus authenticated routes for verification send and MFA lifecycle actions.
- `apps/api/src/egp_api/services/admin_service.py`
  - Surfaced email verification and MFA status in admin views; direct password provisioning now marks email as verified because the admin is explicitly setting credentials.
- `apps/api/src/egp_api/routes/admin.py`
  - Added `POST /v1/admin/users/{user_id}/invite` so tenant admins can issue onboarding emails without creating separate bootstrap scripts.
- `apps/api/src/egp_api/main.py`
  - Wired the updated auth service with notification delivery and web base URL, and marked the new public lifecycle endpoints as auth-middleware exceptions.
- `apps/web/src/lib/api.ts`
  - Added typed client methods for invite/reset/verify/MFA endpoints, expanded auth/admin user models, and removed `tenant_id` from normal current-tenant fetches and billing/dashboard actions.
- `apps/web/src/lib/auth.ts`
  - Added token normalization utility for public token-driven routes.
- `apps/web/src/lib/constants.ts`
  - Added `/security` navigation entry.
- `apps/web/src/app/login/page.tsx`
  - Confirmed the login page is wired to the real session login flow and extended it to accept an optional MFA code plus a forgot-password path.
- `apps/web/src/app/(app)/security/page.tsx`
  - Added self-service UI for email verification and MFA setup/enable/disable.
- `apps/web/src/app/forgot-password/page.tsx`
  - Added forgot-password request screen.
- `apps/web/src/app/reset-password/page.tsx`
  - Added token-based password reset completion screen.
- `apps/web/src/app/invite/page.tsx`
  - Added invite acceptance screen that sets password, establishes session, and redirects into the app.
- `apps/web/src/app/verify-email/page.tsx`
  - Added token-based email verification landing page.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Added admin invite action, surfaced verification/MFA state, and cleaned up current-tenant admin calls so `tenant_id` is omitted unless support override is explicitly in use.
- `apps/web/src/app/(app)/layout.tsx`, `apps/web/src/components/layout/app-header.tsx`, `apps/web/src/lib/hooks.ts`
  - Continued using the previously-added real session model so the new account lifecycle UI operates against authenticated `/v1/me` state.
- `tests/phase4/test_auth_api.py`
  - Added end-to-end API coverage for invite acceptance, forgot/reset password, email verification, MFA setup/login/disable, and updated fixtures for the new schema columns.
- `tests/phase4/test_admin_api.py`
  - Added coverage for admin invite issuance and tenant resolution when frontend requests omit `tenant_id`.
- `docs/FRONTEND_HANDOFF.md`
  - Replaced the old public token guidance with the new auth lifecycle pages and documented that `tenant_id` should only remain in support-mode cross-tenant flows.

### TDD Evidence
- RED command:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q`
- Key RED failures observed before implementation:
  - `/v1/admin/users/{id}/invite` returned `404`.
  - forgot/reset/verify/MFA routes were missing or blocked by auth middleware.
  - fixture inserts failed after schema expansion until test seed SQL was updated for `users.mfa_enabled`.
- GREEN commands/results:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q` -> `26 passed in 3.19s`
  - `./.venv/bin/ruff check apps/api packages` -> `All checks passed!`
  - `(cd apps/web && npm run typecheck)` -> passed
  - `(cd apps/web && npm run lint)` -> `No ESLint warnings or errors`
  - `(cd apps/web && npm run build)` -> passed

### Wiring Verification Evidence
- Migration `011_auth_lifecycle.sql` introduces the persistence required by repo/service logic.
- `create_auth_repository(...)` remains the single repository factory and now exposes token/session/MFA primitives used by `AuthService`.
- `create_app()` wires `AuthService(auth_repo, notification_service, web_base_url)` and exposes the new auth/admin routes.
- The login page posts to `/v1/auth/login`; invite/reset/verify/MFA pages call the new route set through `apps/web/src/lib/api.ts`.
- Current-tenant dashboard, billing, and run fetches no longer append `tenant_id`; tenant resolution now relies on session context unless support-mode override is intentional.

### Behavior Changes
- Login is a real session-backed flow and now supports MFA code entry.
- Tenant admins can issue invite emails for existing tenant users.
- Users can request password resets without account enumeration leakage.
- Email verification is now explicit and user-visible.
- MFA is opt-in, TOTP-based, and enforced during login once enabled.
- Normal tenant-scoped frontend requests no longer send `tenant_id`; support-mode cross-tenant actions still can.

### Risks / Known Gaps
- Invite/reset/verify emails require `EGP_SMTP_*` and `EGP_WEB_BASE_URL`; without them, the API surface exists but delivery is not operational.
- Existing accounts are intentionally still allowed to log in even if `email_verified_at` is null; tightening that policy would be a separate rollout.
- MFA currently supports TOTP only; recovery codes, device management, and step-up policies are not implemented.
- Frontend coverage still relies on build/type/lint plus backend API tests; no page-level browser tests were added in this slice.

### Follow-ups
- Add browser-level smoke coverage for invite, reset, verify, and MFA flows.
- Decide whether unverified existing accounts should be forced through verification before continued access.
- Add recovery codes and stronger operational guardrails around MFA enrollment/disable flows.
- Add startup/config checks that fail loudly when email-based lifecycle flows are enabled without SMTP configuration.

## Implementation Summary (2026-04-06 08:09:29 +07)

### Goal
- Close the remaining frontend testing gap by adding real browser-level page coverage for the auth lifecycle and protected-route auth behavior.

### What Changed
- `apps/web/package.json`
  - Added `test` and `test:e2e` scripts and declared `@playwright/test` so the frontend has a first-class browser smoke suite.
- `apps/web/package-lock.json`
  - Captured the new Playwright dependency graph.
- `apps/web/playwright.config.ts`
  - Added a minimal Playwright config that boots the Next app locally and runs Chromium-based browser tests against it.
- `apps/web/tests/e2e/auth-pages.spec.ts`
  - Added browser smoke tests for:
    - unauthenticated redirect from `/security` to `/login`
    - login submit with MFA code
    - forgot-password submission
    - invite acceptance redirect into the app
    - reset-password completion redirect
    - verify-email token consumption
    - authenticated `/security` interactions for verification resend and MFA setup
  - Mocked `/v1/*` API traffic at the browser network layer so the suite exercises page behavior without requiring a live API backend.
- `.gitignore`
  - Ignored Playwright output directories (`playwright-report/`, `test-results/`).
- `apps/web/AGENTS.md`
  - Updated the package guidance so the repo now accurately documents the Playwright browser smoke suite and includes `npm test` in the frontend gate.

### TDD Evidence
- Tests added:
  - `apps/web/tests/e2e/auth-pages.spec.ts`
- RED command:
  - `cd apps/web && npm run test:e2e -- --list`
- Key RED failure reason:
  - `Cannot find module '@playwright/test'` from `playwright.config.ts`, confirming the new browser test path was not wired yet.
- Intermediate failure evidence after installing the runner:
  - `cd apps/web && npm run test:e2e`
  - First failed because Chromium was not installed, then failed again because the initial route mock only matched a custom API host while the browser bundle was still calling the default `/v1` backend target. Widening interception to `**/v1/**` fixed the real page-path tests.
- GREEN commands/results:
  - `cd apps/web && npm run test:e2e` -> `7 passed`
  - `cd apps/web && npm run typecheck` -> passed
  - `cd apps/web && npm run lint` -> `No ESLint warnings or errors`
  - `cd apps/web && npm run build` -> passed

### Tests Run
- `cd apps/web && npm run test:e2e -- --list` -> failed as expected before Playwright dependency install
- `cd apps/web && npm install` -> installed Playwright dependency
- `cd apps/web && npx playwright install chromium` -> installed browser runtime
- `cd apps/web && npm run test:e2e` -> passed (`7 passed`)
- `cd apps/web && npm run typecheck` -> passed
- `cd apps/web && npm run lint` -> passed
- `cd apps/web && npm run build` -> passed

### Wiring Verification Evidence
- `npm test` / `npm run test:e2e` now resolve from `apps/web/package.json`.
- `apps/web/playwright.config.ts` starts the Next app and points Playwright at the local frontend server.
- `apps/web/tests/e2e/auth-pages.spec.ts` drives the real Next routes under `src/app/` and stubs only the `/v1/*` API edge, so the browser still executes the actual page code, routing, query state, and UI transitions.
- `apps/web/AGENTS.md` now reflects the new frontend test runner so future work uses the browser suite instead of assuming no frontend tests exist.

### Behavior Changes and Risks
- The repo now has browser-level verification for the auth lifecycle UI instead of relying only on API tests plus build/type/lint.
- The E2E suite currently uses mocked API responses, so it validates page behavior and routing, not end-to-end browser-to-API integration.
- Playwright requires a Chromium download on fresh machines (`npx playwright install chromium`), which is now part of the practical frontend setup even though the binary itself remains untracked.

### Follow-ups / Known Gaps
- Add CI wiring for `npm test` if frontend browser tests are not already part of the pipeline.
- Add at least one end-to-end environment smoke path later that runs against a live API instead of mocked `/v1/*` responses.

## Review (2026-04-06 08:09:58 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commit: 8c4b542
- Commands Run: git status --porcelain=v1; CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat; CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- .gitignore apps/web/AGENTS.md apps/web/package.json apps/web/package-lock.json apps/web/playwright.config.ts apps/web/tests/e2e/auth-pages.spec.ts; cd apps/web && npm run test:e2e; cd apps/web && npm run typecheck; cd apps/web && npm run lint; cd apps/web && npm run build

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
- Assumed mocked `/v1/*` browser coverage is the right first step for closing the immediate page-level gap without introducing backend orchestration into frontend tests.

### Recommended Tests / Validation
- Add one CI execution path for `cd apps/web && npm test` on a clean machine to prove the Playwright browser install/setup assumptions hold in automation.
- Later add at least one live-API browser smoke path in a controlled environment to complement the mocked-page tests.

### Rollout Notes
- Fresh developer and CI machines need `npx playwright install chromium` before running the browser suite.
- The new tests validate page behavior, navigation, and request payloads, but they intentionally stop short of full browser-to-API integration.

## Implementation Summary (2026-04-06 08:31:48 +07)

### Goal
- Unblock PR `#18` by fixing the two failing GitHub checks: `Python Lint & Format` and `Python Tests`.

### What Changed
- `tests/phase2/test_dashboard_api.py`
  - Made the dashboard metrics fixture deterministic by pinning the test reference time to midday UTC. This prevents the `discovered_today` assertion from flaking when CI runs shortly after midnight UTC.
- `apps/api/src/egp_api/auth.py`
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/routes/auth.py`
- `apps/api/src/egp_api/services/auth_service.py`
- `packages/db/src/egp_db/repositories/auth_repo.py`
  - Applied `ruff format` so the Python formatting check matches CI expectations.

### TDD Evidence
- Existing failing CI evidence (RED):
  - `Python Lint & Format` on GitHub run `24014898960` failed because `ruff format --check apps/ packages/` wanted to reformat five Python files.
  - `Python Tests` on GitHub run `24014898960` failed in `tests/phase2/test_dashboard_api.py::test_dashboard_summary_endpoint_returns_repository_backed_metrics` with `assert body["kpis"]["discovered_today"] == 2` / `E assert 1 == 2`.
- GREEN commands/results:
  - `./.venv/bin/ruff check apps/api packages tests/phase2/test_dashboard_api.py tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py` -> `All checks passed!`
  - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py::test_dashboard_summary_endpoint_returns_repository_backed_metrics tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q` -> `27 passed in 3.20s`

### Tests Run
- `./.venv/bin/ruff format apps/api/src/egp_api/auth.py apps/api/src/egp_api/config.py apps/api/src/egp_api/routes/auth.py apps/api/src/egp_api/services/auth_service.py packages/db/src/egp_db/repositories/auth_repo.py tests/phase2/test_dashboard_api.py`
- `./.venv/bin/ruff check apps/api packages tests/phase2/test_dashboard_api.py tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py`
- `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py::test_dashboard_summary_endpoint_returns_repository_backed_metrics tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q`

### Wiring Verification Evidence
- The failing dashboard assertion is on the stable route path `/v1/dashboard/summary` and the change only affects the test fixture clock, not runtime service wiring.
- The formatting changes are no-op behaviorally and only touch the Python files CI reported under `ruff format --check`.

### Behavior Changes and Risks
- No product behavior change.
- The dashboard metrics test is now time-of-day independent, which removes CI flakiness around UTC midnight.

### Follow-ups / Known Gaps
- Re-run or wait for GitHub CI on PR `#18` to confirm the remote checks reflect this follow-up commit.

## Review (2026-04-06 08:32:07 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: feat/account-lifecycle-auth-hardening
- Scope: working-tree
- Commit: 6a33930
- Commands Run: CODEX_ALLOW_LARGE_OUTPUT=1 gh run view 24014898960 --job 70032574047 --log; CODEX_ALLOW_LARGE_OUTPUT=1 gh run view 24014898960 --job 70032574042 --log; ./.venv/bin/ruff format apps/api/src/egp_api/auth.py apps/api/src/egp_api/config.py apps/api/src/egp_api/routes/auth.py apps/api/src/egp_api/services/auth_service.py packages/db/src/egp_db/repositories/auth_repo.py tests/phase2/test_dashboard_api.py; ./.venv/bin/ruff check apps/api packages tests/phase2/test_dashboard_api.py tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py; ./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py::test_dashboard_summary_endpoint_returns_repository_backed_metrics tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q

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
- Assumed the CI-only failure in `test_dashboard_summary_endpoint_returns_repository_backed_metrics` is pure test flakiness caused by UTC-midnight timing, not a product regression.

### Recommended Tests / Validation
- Re-run the GitHub CI checks for PR `#18`.
- If `Python Tests` still fail remotely after this patch, inspect whether the CI workflow includes any other time-sensitive dashboard tests.

### Rollout Notes
- This follow-up changes test determinism and Python formatting only; there is no intended runtime behavior change.
