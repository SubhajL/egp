## Plan Draft A

### Overview
- Replace the current public-env bearer token bridge with a real cookie-based user/session model in the API and web app.
- Keep bearer-token auth working in the API for compatibility, but make the web app authenticate through `/v1/auth/login`, hold no public token, and rely on HttpOnly session cookies.

### Files to Change
- `packages/db/src/migrations/010_user_sessions.sql`: add password and session persistence schema.
- `packages/db/src/egp_db/repositories/auth_repo.py`: tenant/user lookup, password hashing, session issuance, session lookup, logout/revoke.
- `packages/db/src/egp_db/repositories/__init__.py`: export auth repository symbols.
- `apps/api/src/egp_api/auth.py`: accept cookie-backed auth context in addition to bearer tokens.
- `apps/api/src/egp_api/main.py`: wire auth repository/service, session-aware middleware, cookie config, and auth routes.
- `apps/api/src/egp_api/config.py`: auth/session/cookie/CORS config helpers.
- `apps/api/src/egp_api/routes/auth.py`: login/logout/me endpoints.
- `apps/api/src/egp_api/services/auth_service.py`: orchestrate login/logout/session lookups.
- `apps/api/src/egp_api/services/admin_service.py`: support creating/updating users with passwords.
- `apps/api/src/egp_api/routes/admin.py`: accept password fields on admin user mutations.
- `apps/web/src/lib/api.ts`: stop defaulting to public bearer token auth, send credentials, add auth fetch functions.
- `apps/web/src/app/login/page.tsx`: implement real login form with tenant slug, email, and password.
- `apps/web/src/app/(app)/layout.tsx`: redirect unauthenticated users to login or render gated shell.
- `tests/phase4/test_auth_api.py`: session/login/logout/me coverage.
- `tests/phase4/test_admin_api.py`: admin user password creation/update coverage.

### Implementation Steps
- TDD sequence:
  1. Add/stub auth API tests for login failure, login success, cookie session, logout, and `/v1/me`.
  2. Run targeted pytest and confirm failure on missing routes/logic.
  3. Implement migration, repository, service, route, and middleware changes to pass.
  4. Add admin-user password tests, fail them, then implement password-aware admin flows.
  5. Update web login/client wiring, run typecheck/build, and refactor minimally.
- `hash_password(password: str) -> str`: derive a salted PBKDF2 password hash string with strong iteration count.
- `verify_password(password: str, encoded_hash: str) -> bool`: validate password input against stored hash.
- `SqlAuthRepository.authenticate_user(...)`: resolve tenant by slug, find active user by email, verify password.
- `SqlAuthRepository.create_session(...)`: mint opaque session token, persist hashed token with expiry, return raw token.
- `SqlAuthRepository.get_session_auth_context(...)`: resolve session cookie to active user/tenant/role context.
- `AuthService.login(...)`: authenticate user and issue cookie-ready session token.
- `AuthService.logout(...)`: revoke current session token and clear cookie.
- `routes/auth.login`: fail closed on bad slug/email/password with 401.
- `routes/auth.me`: return current user and tenant snapshot for the signed-in session.
- `routes/admin.create_user/update_user`: allow password set/reset, reject weak/blank passwords.
- `api.ts` fetch helpers: use `credentials: "include"` and remove public token dependency from normal flows.
- `login/page.tsx`: collect tenant slug, email, password; call API login; redirect on success; show server error on failure.

### Test Coverage
- `tests/phase4/test_auth_api.py::test_login_rejects_invalid_credentials`
  - Reject bad tenant/email/password combinations.
- `tests/phase4/test_auth_api.py::test_login_sets_session_cookie_and_me_reads_session`
  - Successful login yields usable session cookie.
- `tests/phase4/test_auth_api.py::test_logout_revokes_session_and_me_becomes_401`
  - Logout invalidates active session.
- `tests/phase4/test_auth_api.py::test_bearer_auth_still_works_for_compatibility`
  - Existing bearer token access remains valid.
- `tests/phase4/test_auth_api.py::test_suspended_or_passwordless_user_cannot_login`
  - Fail closed for incomplete user credentials.
- `tests/phase4/test_admin_api.py::test_create_user_can_store_password`
  - Admin-created users can log in.
- `tests/phase4/test_admin_api.py::test_update_user_can_rotate_password`
  - Password rotation invalidates old secret.

### Decision Completeness
- Goal:
  - Ship a real web login/session path that does not rely on public frontend bearer tokens.
- Non-goals:
  - Full Supabase Auth integration.
  - SSO/social login.
  - Password reset emails.
- Success criteria:
  - Web app can sign in with tenant slug/email/password and access API via HttpOnly session cookie.
  - `NEXT_PUBLIC_EGP_API_BEARER_TOKEN` is no longer required for normal web usage.
  - Existing bearer-token tests still pass.
- Public interfaces:
  - New endpoints: `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/me`.
  - New env vars: session cookie and CORS settings if needed.
  - New migration for session storage and password hash column.
- Edge cases / failure modes:
  - Invalid credentials: 401, no cookie.
  - Suspended/deactivated user: 403 or 401 fail closed.
  - Expired/revoked session: 401 and cookie clear on logout path.
  - Missing tenant slug on login: 422.
- Rollout & monitoring:
  - Keep bearer auth compatibility during rollout.
  - Watch auth/login failure logs and session issuance counts.
  - Backout by disabling web login usage while leaving bearer auth in place.
- Acceptance checks:
  - `pytest` targeted auth/admin suites pass.
  - `npm run typecheck` and `npm run build` pass.
  - Manual login works against local API/web.

### Dependencies
- Existing `python-jose` stays for bearer compatibility.
- No new Python dependency required if password hashing uses stdlib PBKDF2.

### Validation
- Run auth/admin pytest suites.
- Run web typecheck/build.
- Manual smoke: login, load dashboard, logout, dashboard redirects/fails.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `routes/auth.py` | Browser login/logout/me requests | `apps/api/src/egp_api/main.py` router include | `users`, `user_sessions`, `tenants` |
| `AuthService` | auth route handlers and middleware | `app.state.auth_service` in API app factory | `users`, `user_sessions`, `tenants` |
| `SqlAuthRepository` | auth service + middleware session lookup | imported/wired in API app factory | `users`, `user_sessions`, `tenants` |
| Migration `010_user_sessions.sql` | DB boot/migration runner | migration runner + app startup schema | `users.password_hash`, `user_sessions` |
| Web login form | `/login` submit handler | `apps/web/src/app/login/page.tsx` | N/A |
| Session-aware fetch helpers | all web API calls | `apps/web/src/lib/api.ts` | N/A |

## Plan Draft B

### Overview
- Use signed JWT session cookies instead of DB-backed opaque sessions.
- Add password hashes for users, issue short-lived session JWTs on login, and let the browser authenticate through cookies without storing public env tokens.

### Files to Change
- `packages/db/src/migrations/010_user_passwords.sql`: add password hash column only.
- `packages/db/src/egp_db/repositories/auth_repo.py`: tenant/user lookup and password verification.
- `apps/api/src/egp_api/auth.py`: issue and validate session JWT cookies.
- `apps/api/src/egp_api/main.py`: session-cookie middleware wiring.
- `apps/api/src/egp_api/routes/auth.py`: login/logout/me.
- `apps/api/src/egp_api/config.py`: cookie/session config.
- `apps/api/src/egp_api/services/admin_service.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/login/page.tsx`
- `tests/phase4/test_auth_api.py`

### Implementation Steps
- TDD sequence:
  1. Add login/logout/me tests expecting session cookie auth.
  2. Run and capture route failures.
  3. Implement password verification and JWT-cookie issuance.
  4. Update web client and login page.
  5. Run targeted backend/frontend gates.
- `issue_session_jwt(...)`: create short-lived signed cookie token with subject/tenant/role.
- `authenticate_request(...)`: inspect bearer header first, then session cookie JWT.
- `AuthService.login(...)`: verify tenant/email/password and return session JWT.

### Test Coverage
- Same route-level auth tests as Draft A, but session verification asserts JWT cookie path rather than DB session revocation state.

### Decision Completeness
- Goal:
  - Replace public env-token auth in the web app.
- Non-goals:
  - Server-side session persistence.
- Success criteria:
  - Browser login works with cookie-based auth.
  - API continues to accept existing bearer tokens.
- Public interfaces:
  - Same auth endpoints as Draft A.
  - Password hash schema change only.
- Edge cases / failure modes:
  - Logout clears cookie but cannot centrally revoke already-issued JWTs.
  - Password rotation may require a version claim or shorter TTL to be trustworthy.
- Rollout & monitoring:
  - Simpler migration, less DB churn.
  - More exposure to token replay until expiry.
- Acceptance checks:
  - Same as Draft A.

### Dependencies
- No new deps.

### Validation
- Same as Draft A.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `routes/auth.py` | Browser auth requests | API app router include | `users`, `tenants` |
| Session JWT helpers | middleware auth path | `egp_api/auth.py` | N/A |
| Web login form | `/login` submit | `apps/web/src/app/login/page.tsx` | N/A |

## Comparative Analysis & Synthesis

### Strengths
- Draft A has stronger logout/revocation semantics and a truer session model.
- Draft B is smaller and faster to land.

### Gaps
- Draft B underspecifies revocation, password rotation invalidation, and support/operator logout guarantees.
- Draft A adds one more table and repo, but that complexity is justified at an auth boundary.

### Trade-offs
- Draft A favors operational correctness and future extensions like session listing/revocation.
- Draft B favors speed but leaves meaningful security gaps.

### Compliance
- Both follow repo conventions, but Draft A better matches “real user/session model” rather than “JWT cookie bridge.”

## Unified Execution Plan

### Overview
- Implement tenant-scoped password login with DB-backed opaque sessions stored in HttpOnly cookies.
- Preserve bearer-token auth for compatibility, but move the web app to credentialed cookie requests so normal web usage no longer depends on `NEXT_PUBLIC_EGP_API_BEARER_TOKEN` or `NEXT_PUBLIC_EGP_TENANT_ID`.

### Files to Change
- `packages/db/src/migrations/010_user_sessions.sql`: add `users.password_hash` and `user_sessions`.
- `packages/db/src/egp_db/repositories/auth_repo.py`: password hashing, tenant/user auth lookup, session create/revoke/lookup.
- `packages/db/src/egp_db/repositories/__init__.py`: export auth repo.
- `apps/api/src/egp_api/auth.py`: cookie + bearer auth resolution helpers.
- `apps/api/src/egp_api/config.py`: session cookie/CORS config.
- `apps/api/src/egp_api/services/auth_service.py`: login/logout/me orchestration.
- `apps/api/src/egp_api/routes/auth.py`: auth endpoints.
- `apps/api/src/egp_api/main.py`: wire auth repo/service, auth router, middleware, and CORS.
- `apps/api/src/egp_api/services/admin_service.py`: allow password set/reset on user mutations.
- `apps/api/src/egp_api/routes/admin.py`: request schema additions for password fields.
- `apps/web/src/lib/api.ts`: credentialed fetches and auth helpers.
- `apps/web/src/app/login/page.tsx`: working login UX.
- `apps/web/src/app/(app)/layout.tsx`: auth guard/redirect.
- `tests/phase4/test_auth_api.py`: new auth/session TDD suite.
- `tests/phase4/test_admin_api.py`: password-management coverage updates.
- `docs/FRONTEND_HANDOFF.md`: mark env bearer token bridge deprecated/replaced.

### Implementation Steps
- TDD sequence (REQUIRED):
  1. Add `tests/phase4/test_auth_api.py` with login/logout/me/bearer-compat cases.
  2. Run `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q` and confirm RED due to missing routes/logic.
  3. Implement migration, repository, service, route, config, and middleware changes to pass.
  4. Extend admin password tests, run RED, implement admin password create/reset behavior.
  5. Update web auth/client wiring, run `npm run typecheck` and `npm run build`, then refactor only if needed.
- `hash_password`, `verify_password`:
  - Use salted PBKDF2-HMAC-SHA256 encoded into a single string.
  - Reject blank and too-short passwords fail closed.
- `SqlAuthRepository.find_login_user(tenant_slug, email)`:
  - Resolve tenant by slug, find active user by tenant/email, return tenant + user + password hash.
- `SqlAuthRepository.create_session(...)`:
  - Generate opaque token, persist only token hash, store expiry and revocation metadata.
- `SqlAuthRepository.get_session_auth_context(session_token)`:
  - Hash token, join `user_sessions`, `users`, and `tenants`, ensure all are active/unexpired.
- `AuthService.login/logout/get_current_user`:
  - Centralize cookie-independent business logic and error classification.
- `authenticate_request` / middleware:
  - Prefer bearer header when present for compatibility.
  - Otherwise resolve cookie session.
- `routes/auth.login/logout/me`:
  - Set and clear HttpOnly cookie with secure config.
- `AdminService.create_user/update_user`:
  - Accept optional password on create and update for real user provisioning.
- `api.ts`:
  - Send `credentials: "include"` on fetch/json/blob calls.
  - Remove public bearer token from normal request path.
  - Add `login`, `logout`, and `fetchMe`.
- `login/page.tsx`:
  - Add tenant slug field.
  - Submit to login endpoint and redirect to app on success.
  - Render server-side failure message for bad credentials.

### Test Coverage
- `tests/phase4/test_auth_api.py::test_login_requires_valid_tenant_slug_email_and_password`
  - Reject invalid tenant/email/password tuples.
- `tests/phase4/test_auth_api.py::test_login_sets_http_only_session_cookie`
  - Successful login returns cookie session.
- `tests/phase4/test_auth_api.py::test_me_uses_session_cookie_without_tenant_param`
  - Session resolves tenant automatically.
- `tests/phase4/test_auth_api.py::test_logout_revokes_cookie_session`
  - Revoked session cannot access `/v1/me`.
- `tests/phase4/test_auth_api.py::test_bearer_tokens_remain_supported`
  - Existing API clients still authenticate.
- `tests/phase4/test_auth_api.py::test_passwordless_or_suspended_user_cannot_login`
  - Fail closed for incomplete or inactive accounts.
- `tests/phase4/test_admin_api.py::test_create_user_with_password_can_subsequently_login`
  - Admin provisioning creates usable account.
- `tests/phase4/test_admin_api.py::test_update_user_password_rotates_credentials`
  - Old password fails, new password succeeds.

### Decision Completeness
- Goal:
  - Convert the web app from public-env token auth to real user/session auth.
- Non-goals:
  - Supabase Auth integration.
  - Password reset/recovery emails.
  - MFA/SSO.
- Success criteria:
  - A provisioned user can log in through the web UI using tenant slug + email + password.
  - API requests from the web succeed with cookie sessions and no public bearer token env.
  - `/v1/me` returns current user/tenant context.
  - Logout revokes the session.
  - Existing bearer-based tests continue to pass.
- Public interfaces:
  - New endpoints: `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/me`.
  - New request fields: `tenant_slug`, `email`, `password`; admin create/update optional `password`.
  - New env vars/config: session cookie name/max-age/secure flag and allowed frontend origins.
  - New schema: `users.password_hash`, `user_sessions`.
- Edge cases / failure modes:
  - Invalid credentials: 401, no session cookie.
  - Tenant slug mismatch or unknown tenant: 401 fail closed.
  - User suspended/deactivated: 403 fail closed.
  - Passwordless admin-created user: cannot log in until password set.
  - Expired/revoked session: 401 fail closed.
  - Cross-origin cookie misconfig: login may succeed but browser won’t send cookie; mitigate with explicit CORS/cookie config.
- Rollout & monitoring:
  - Keep bearer auth enabled for compatibility while web migrates.
  - Update docs to mark `NEXT_PUBLIC_EGP_API_BEARER_TOKEN` deprecated.
  - Backout by continuing to use bearer auth for clients while disabling web login route consumption if necessary.
  - Watch login failure rate, session creation rate, and unexpected 401s from `/v1/me`.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py tests/phase4/test_webhooks_api.py -q`
  - `(cd apps/web && npm run typecheck)`
  - `(cd apps/web && npm run build)`

### Dependencies
- Python stdlib PBKDF2 + `secrets`/`hmac`.
- Existing FastAPI and `python-jose`.

### Validation
- Automated:
  - targeted pytest auth/admin suites.
  - web typecheck/build.
- Manual:
  - create or seed a user with password.
  - log in from `/login`.
  - load dashboard and admin pages.
  - log out and confirm protected page access is denied or redirected.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `packages/db/src/migrations/010_user_sessions.sql` | migration runner / app DB init | `egp_db.migration_runner` and normal migration sequence | `users.password_hash`, `user_sessions` |
| `packages/db/src/egp_db/repositories/auth_repo.py` | auth service + middleware session lookup | imported into `apps/api/src/egp_api/main.py` | `users`, `user_sessions`, `tenants` |
| `apps/api/src/egp_api/services/auth_service.py` | auth route handlers | `app.state.auth_service` in `create_app()` | `users`, `user_sessions`, `tenants` |
| `apps/api/src/egp_api/routes/auth.py` | `/v1/auth/login`, `/v1/auth/logout`, `/v1/me` | `app.include_router(auth_router)` in `create_app()` | N/A |
| session-aware middleware in `apps/api/src/egp_api/auth.py` | every protected request | `@app.middleware("http")` in `apps/api/src/egp_api/main.py` | `user_sessions`, `users`, `tenants` |
| `apps/web/src/lib/api.ts` auth client changes | all browser API requests | imported by existing hooks/pages | N/A |
| `apps/web/src/app/login/page.tsx` | browser login form submit | Next app route page | N/A |
| `apps/web/src/app/(app)/layout.tsx` auth guard | protected app shell render | route-group layout | N/A |

## Implementation Summary

### Goal
- Replace the public `NEXT_PUBLIC_EGP_API_BEARER_TOKEN` browser auth bridge with a real user/session model for the web app, while preserving bearer-token compatibility for existing API callers.

### Files Changed
- `packages/db/src/migrations/010_user_sessions.sql`
- `packages/db/src/egp_db/repositories/auth_repo.py`
- `packages/db/src/egp_db/repositories/__init__.py`
- `packages/db/src/egp_db/repositories/notification_repo.py`
- `apps/api/src/egp_api/auth.py`
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/main.py`
- `apps/api/src/egp_api/routes/auth.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/api/src/egp_api/services/auth_service.py`
- `apps/api/src/egp_api/services/admin_service.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/auth.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/app/login/page.tsx`
- `apps/web/src/app/(app)/layout.tsx`
- `apps/web/src/components/layout/app-header.tsx`
- `docs/FRONTEND_HANDOFF.md`
- `tests/phase4/test_auth_api.py`
- `tests/phase4/test_admin_api.py`

### RED / GREEN Record
- RED:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
  - Failed with missing schema/routes, including `sqlite3.OperationalError: table users has no column named password_hash` and `/v1/me` returning `404`.
- GREEN:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
  - Result: `5 passed in 0.80s`
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_admin_api.py -q`
  - Result: `18 passed in 1.96s`
  - `(cd apps/web && npm run typecheck)`
  - Result: success
  - `(cd apps/web && npm run lint)`
  - Result: success
  - `(cd apps/web && npm run build)`
  - Result: success

### Wiring Verification Notes
- Backend:
  - `create_app()` now wires `auth_repository`, `auth_service`, session-cookie config, auth router, CORS with credentials, and middleware fallback from bearer header to cookie session.
  - Admin user create/update can now provision or rotate passwords.
- Frontend:
  - All browser API calls now use `credentials: "include"` instead of a public bearer token.
  - `/login` now performs a real login with `tenant_slug`, `email`, and `password`, seeds the `["me"]` React Query cache, and guards against open redirects.
  - `(app)` route group now blocks unauthenticated renders and redirects 401 users to `/login`.
  - Header now shows the current session user/tenant and supports logout.
- Build-specific fix:
  - Next.js static build rejected `useSearchParams()` in a protected layout without suspense. Resolved by removing query-string dependency from the `(app)` auth gate and wrapping the login page search-param read in `Suspense`.

### Risks / Follow-ups
- The web app still has some legacy `tenant_id` compatibility paths in older components. Auth no longer depends on them, but they should be removed as a cleanup pass.
- There is still no password reset, invite flow, email verification, or MFA. This implementation establishes the core session model only.
- Cookie/CORS settings must be configured correctly in each deployed environment or the browser session will appear to “log in” without persisting.
