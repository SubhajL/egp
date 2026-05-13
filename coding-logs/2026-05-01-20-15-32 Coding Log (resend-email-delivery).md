## Plan Draft A

### Overview
Introduce Resend as a first-class outbound email provider while preserving the existing SMTP path as a fallback. Wire the Python notification/auth flow and the separate Next.js inquiry mailer to prefer Resend when configured, add focused tests for provider selection and payload sending, and document the new env surface without committing secrets.

### Files to Change
- `packages/notification-core/src/egp_notifications/service.py`
  Add Resend config/types plus provider-aware send logic shared by API email flows.
- `apps/api/src/egp_api/config.py`
  Add config readers for Resend env vars and provider preference.
- `apps/api/src/egp_api/main.py`
  Pass Resend config into `NotificationService` creation.
- `apps/api/pyproject.toml`
  Add any runtime dependency only if unavoidable; prefer stdlib HTTP and keep this unchanged if possible.
- `tests/phase2/test_notification_service.py`
  Add provider-selection and Resend payload tests.
- `tests/phase4/test_auth_api.py`
  Add config-driven API test coverage for Resend-enabled password reset / verification behavior if practical.
- `apps/web/src/lib/mailer.ts`
  Add Resend-based sending path and provider/env selection for inquiry emails.
- `apps/web/src/app/api/inquiry/route.ts`
  Minimal touch only if needed for updated error handling or imports.
- `apps/web/package.json`
  Update only if a new dependency is introduced; avoid this by using `fetch`.
- `docker-compose.yml`
  Forward Resend env vars into the API container and optionally the web container.
- `.env.example`
  Document `EGP_RESEND_*` keys and provider preference examples.

### Implementation Steps
- TDD sequence:
  1. Add notification-service tests that fail because Resend config/path does not exist yet.
  2. Run the focused pytest file and confirm failures are due to missing Resend support.
  3. Implement the smallest Python/provider changes to make those tests pass.
  4. Add or extend auth/API tests only where config wiring needs runtime proof.
  5. Add the web Resend path and validate with typecheck rather than inventing a new web unit harness.
  6. Run focused fast gates: pytest, ruff, compileall, web typecheck.
- Function names / behavior:
  - `get_resend_config(...)`: read `EGP_RESEND_API_KEY`, `EGP_RESEND_FROM`, optional `EGP_EMAIL_PROVIDER`, and return a normalized config object or `None`.
  - `NotificationService._send_email_via_resend(...)`: POST to Resend’s `/emails` endpoint with `from`, `to`, `subject`, and `text`, raising on non-2xx responses.
  - `NotificationService.email_delivery_configured()`: treat injected sender, Resend config, or SMTP config as valid delivery backends.
  - `sendInquiryNotification(...)`: prefer Resend when configured, sending HTML + text-compatible payloads to ops and submitter without mailbox credentials.
- Edge cases:
  - If `EGP_EMAIL_PROVIDER=resend` but the API key/from address is missing, fail closed as “not configured”.
  - If provider is unset, prefer Resend when fully configured, otherwise fall back to SMTP for backward compatibility.
  - Preserve current injected `email_sender` test hooks as highest-priority override.

### Test Coverage
- `tests/phase2/test_notification_service.py`
  - `test_email_delivery_configured_with_resend_config`
    Resend counts as configured delivery backend.
  - `test_send_email_message_uses_resend_http_api`
    Sends correct authorization and payload.
  - `test_injected_email_sender_overrides_resend_and_smtp`
    Existing fake sender still wins.
  - `test_send_raises_when_resend_returns_error`
    Provider surfaces delivery failure.
- `tests/phase4/test_auth_api.py`
  - `test_forgot_password_works_with_resend_configured_sender`
    Configured provider allows reset token issuance.
  - `test_email_verification_works_with_resend_configured_sender`
    Verification path stays wired through notification service.

### Decision Completeness
- Goal:
  - Remove the need to use mailbox SMTP credentials as the primary production path.
  - Allow the API and inquiry form to send transactional mail through Resend.
- Non-goals:
  - No inbound email/reply processing.
  - No template-hosting migration to Resend templates.
  - No dashboard/webhook integration in this pass.
- Success criteria:
  - Python notification service can send through Resend with a verified `from` address and API key.
  - Password reset / verification / invite flows remain functional through existing API routes.
  - Web inquiry route can send via Resend without SMTP credentials.
  - Local docs/config examples show the new env vars and container wiring.
- Public interfaces:
  - New env vars: `EGP_RESEND_API_KEY`, `EGP_RESEND_FROM`, optional `EGP_EMAIL_PROVIDER`.
  - Existing SMTP env vars remain supported for fallback.
  - No API route/schema changes.
- Edge cases / failure modes:
  - Fail closed when the selected provider is incompletely configured.
  - Raise/log provider failures rather than claiming success.
  - Preserve current generic forgot-password response for unknown users.
- Rollout & monitoring:
  - Roll out by setting `EGP_EMAIL_PROVIDER=resend` plus `EGP_RESEND_API_KEY` and verified `EGP_RESEND_FROM`.
  - Backout is env-only: unset provider or revert to SMTP vars.
  - Watch API logs for Resend 4xx/5xx responses.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py -q`
  - `./.venv/bin/python -m ruff check apps/api packages tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py`
  - `./.venv/bin/python -m compileall apps/api/src packages`
  - `(cd apps/web && npm run typecheck)`

### Dependencies
- Official Resend API contract: `https://api.resend.com/emails` with bearer auth and `User-Agent`.
- No new runtime libraries if using stdlib/fetch HTTP clients.

### Validation
- Configure local env with `EGP_EMAIL_PROVIDER=resend`, `EGP_RESEND_API_KEY`, and a verified `EGP_RESEND_FROM`.
- Trigger `/v1/auth/password/forgot` and confirm the request returns `202` and Resend accepts the email.
- Submit the inquiry route and confirm both ops and customer emails are accepted by Resend.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `ResendConfig` + send path in notification-core | `AuthService._send_email_if_configured()` and notification dispatchers | `apps/api/src/egp_api/main.py` creates `NotificationService(...)` | N/A |
| Resend env readers | `create_app()` config resolution | `apps/api/src/egp_api/config.py` imported by `apps/api/src/egp_api/main.py` | N/A |
| Web inquiry Resend sender | `POST /api/inquiry` | `apps/web/src/app/api/inquiry/route.ts` imports `sendInquiryNotification()` | N/A |
| Compose/env wiring | container startup | `docker-compose.yml` and root `.env.example` | N/A |

### Cross-Language Schema Verification
- No database migration or schema touch is required.
- Python and TypeScript changes are config-only and transport-only.

### Decision-Complete Checklist
- No open public-interface decisions remain.
- New env vars and fallback behavior are explicit.
- Every behavior change has at least one validation target.
- Runtime wiring points are identified for API and web surfaces.

## Plan Draft B

### Overview
Implement Resend only for the Python API/auth flow and leave the web inquiry mailer on SMTP for now. This is smaller and lower-risk, but it leaves the repo with two different outbound mail strategies and keeps mailbox credentials in one remaining path.

### Files to Change
- `packages/notification-core/src/egp_notifications/service.py`
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/main.py`
- `tests/phase2/test_notification_service.py`
- `tests/phase4/test_auth_api.py`
- `docker-compose.yml`
- `.env.example`

### Implementation Steps
- TDD sequence:
  1. Add failing Resend tests in `test_notification_service.py`.
  2. Implement Resend transport in Python only.
  3. Add API wiring test if needed.
  4. Update env docs and Compose.
- Function names / behavior:
  - Same Python-side helpers as Draft A, but no TypeScript changes.
- Edge cases:
  - Web inquiry route still depends on SMTP and remains out of scope.

### Test Coverage
- Same Python tests as Draft A, minus web implications.

### Decision Completeness
- Goal:
  - Fix product auth emails without mailbox SMTP dependency.
- Non-goals:
  - No web inquiry migration.
- Success criteria:
  - Password-reset, invite, and verification emails can use Resend.
- Public interfaces:
  - Same new env vars on the API side only.
- Edge cases / failure modes:
  - Inquiry route remains on SMTP; inconsistent provider story remains.
- Rollout & monitoring:
  - Simpler rollout, but operationally split.
- Acceptance checks:
  - Python-only checks plus maybe no web gate.

### Dependencies
- Same Resend HTTP API.

### Validation
- Trigger only auth-related email flows.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Python Resend transport | `AuthService` mail paths | `create_app()` -> `NotificationService(...)` | N/A |
| API config/env wiring | config helpers | `apps/api/src/egp_api/config.py` | N/A |

### Cross-Language Schema Verification
- No schema changes.

### Decision-Complete Checklist
- Complete for API auth mail, incomplete for repo-wide outbound email consistency.

## Comparative Analysis & Synthesis

### Strengths
- Draft A removes the customer-mailbox dependency across both current outbound email surfaces.
- Draft B is smaller and faster to land for the password-reset concern.

### Gaps
- Draft A touches two stacks and therefore needs more verification.
- Draft B leaves the inquiry flow on SMTP, so the same product concern still exists elsewhere.

### Trade-offs
- Draft A has broader consistency and a cleaner operational story.
- Draft B has less code churn but preserves split behavior.

### Compliance
- Both plans keep app entrypoints thin, preserve package/app boundaries, avoid schema work, and keep secrets out of git.
- Draft A better matches the repo’s shared-logic guidance because it removes provider-specific behavior from app callers and keeps transport concerns centralized where possible.

## Unified Execution Plan

### Overview
Implement Draft A with one pragmatic boundary: use a shared Resend config and transport pattern across Python and TypeScript, but avoid adding new SDK dependencies if direct HTTP/fetch is sufficient. Preserve injected test senders and SMTP fallback for backward compatibility, while allowing the repo to switch cleanly to `EGP_EMAIL_PROVIDER=resend`.

### Files to Change
- `packages/notification-core/src/egp_notifications/service.py`
  Add `ResendConfig`, provider selection, direct Resend HTTP sending, and updated configured checks.
- `apps/api/src/egp_api/config.py`
  Add Resend env readers and provider selection helper(s).
- `apps/api/src/egp_api/main.py`
  Wire Resend config into `NotificationService`.
- `tests/phase2/test_notification_service.py`
  Add tests for configured state, HTTP payload/headers, and precedence rules.
- `tests/phase4/test_auth_api.py`
  Preserve existing fake-sender coverage and add focused config-driven behavior only if needed to prove wiring.
- `apps/web/src/lib/mailer.ts`
  Replace SMTP-only transport selection with provider-aware Resend-or-SMTP logic, preferring Resend when configured.
- `docker-compose.yml`
  Pass `EGP_EMAIL_PROVIDER`, `EGP_RESEND_API_KEY`, and `EGP_RESEND_FROM` into API and web containers.
- `.env.example`
  Document the Resend-first configuration and keep SMTP variables as fallback examples.

### Implementation Steps
- TDD sequence:
  1. Add failing tests in `tests/phase2/test_notification_service.py` for Resend config recognition and HTTP send payload.
  2. Run `./.venv/bin/python -m pytest tests/phase2/test_notification_service.py -q` and confirm failures are due to missing Resend support.
  3. Implement `ResendConfig`, provider selection, and HTTP sending in `notification-core` using stdlib networking.
  4. Wire `apps/api` config + `create_app()` to pass the Resend config into `NotificationService`.
  5. If needed, add one focused auth API test proving configured delivery through the existing runtime path.
  6. Update the web inquiry mailer to use Resend when configured and SMTP only as fallback.
  7. Update `.env.example` and `docker-compose.yml`.
  8. Run the relevant Python and TypeScript gates, then do a skeptical review of the touched surface.
- Function names / behavior:
  - `class ResendConfig`: hold API key, from address, API base URL, and optional audience/provider metadata if needed later.
  - `get_resend_config(...)`: return a normalized config only when the required values are present.
  - `get_email_provider(...)`: optionally honor `EGP_EMAIL_PROVIDER`; otherwise provider selection remains auto-detect.
  - `NotificationService._send_email_via_resend(...)`: send `from`, `to`, `subject`, and `text`; set `Authorization`, `Content-Type`, and `User-Agent`; raise a helpful error on non-2xx.
  - `sendInquiryNotification(...)`: send HTML + text payloads via Resend `fetch`, otherwise use existing SMTP logic.
- Expected behavior and edge cases:
  - Injected test sender still overrides all provider configs.
  - `resend` selected but incomplete config returns “not configured” rather than falling through silently.
  - Unset provider auto-detects Resend first, then SMTP.
  - Web inquiry route continues working with SMTP if Resend is absent, preserving backward compatibility.

### Test Coverage
- `tests/phase2/test_notification_service.py`
  - `test_email_delivery_configured_with_resend_config`
    Resend config enables delivery.
  - `test_send_email_message_uses_resend_http_api`
    Correct headers and JSON body sent.
  - `test_injected_email_sender_overrides_resend_and_smtp`
    Test sender precedence remains intact.
  - `test_send_email_message_returns_false_without_any_provider`
    Unconfigured delivery stays false.
  - `test_send_resend_raises_on_non_success_response`
    API failure surfaces explicitly.
- `tests/phase4/test_auth_api.py`
  - `test_forgot_password_returns_503_when_selected_provider_is_incomplete`
    Selected-but-broken provider fails closed.
  - Optional focused runtime wiring test if direct `NotificationService` tests are insufficient.
- `apps/web`
  - No new harness by default; rely on `npm run typecheck` and the route’s existing compile path.

### Decision Completeness
- Goal:
  - Use Resend for transactional outbound email without relying on a customer mailbox account.
- Non-goals:
  - No inbound/reply processing, template migration, or delivery-event webhooks.
  - No UI changes beyond keeping current flows operational.
- Success criteria:
  - API auth emails can be sent with only Resend env vars configured.
  - Inquiry emails can also be sent with Resend configured.
  - SMTP remains usable as a fallback when Resend is not configured.
  - Tests and validation commands pass on the touched surfaces.
- Public interfaces:
  - New env vars: `EGP_EMAIL_PROVIDER` (optional), `EGP_RESEND_API_KEY`, `EGP_RESEND_FROM`, optional `EGP_RESEND_API_BASE`.
  - Existing SMTP env vars remain supported.
  - No route or schema changes.
- Edge cases / failure modes:
  - Fail closed when the explicitly selected provider lacks required config.
  - Log/raise provider API failures instead of reporting false success.
  - Preserve generic-success behavior for unknown forgot-password email addresses.
- Rollout & monitoring:
  - Preferred rollout: set `EGP_EMAIL_PROVIDER=resend`, `EGP_RESEND_API_KEY`, `EGP_RESEND_FROM`.
  - Backout: unset provider or switch to `smtp`.
  - Monitor app logs for Resend 401/403/429/5xx responses and rate-limit errors.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py -q`
  - `./.venv/bin/python -m ruff check apps/api packages tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py`
  - `./.venv/bin/python -m compileall apps/api/src packages`
  - `(cd apps/web && npm run typecheck)`
  - `docker compose config | rg -n "EGP_(EMAIL_PROVIDER|RESEND_API_KEY|RESEND_FROM|RESEND_API_BASE)"`

### Dependencies
- Resend official docs reviewed:
  - `https://resend.com/docs/api-reference/introduction`
  - `https://resend.com/docs/api-reference/emails/send-email`
  - `https://resend.com/docs/send-with-python`
- No additional runtime dependencies if stdlib/fetch HTTP clients are used.

### Validation
- Local env:
  - `EGP_EMAIL_PROVIDER=resend`
  - `EGP_RESEND_API_KEY=re_...`
  - `EGP_RESEND_FROM=<verified sender>`
- Trigger `/v1/auth/password/forgot` and `/v1/auth/email/verification/send`.
- Submit the inquiry form/route and confirm Resend accepts both outbound sends.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `ResendConfig` / provider-aware `NotificationService` | `AuthService._send_email_if_configured()` and notification dispatchers | `apps/api/src/egp_api/main.py` instantiates `NotificationService(...)` | N/A |
| API Resend config readers | `create_app()` configuration resolution | `apps/api/src/egp_api/config.py` imported in `apps/api/src/egp_api/main.py` | N/A |
| Web provider-aware mailer | `POST /api/inquiry` | `apps/web/src/app/api/inquiry/route.ts` imports `sendInquiryNotification()` from `apps/web/src/lib/mailer.ts` | N/A |
| Container/env wiring | process startup | `docker-compose.yml` plus root `.env.example` | N/A |

### Cross-Language Schema Verification
- No schema, migration, or repository changes are expected.
- Work is limited to config/env and outbound email transport.

### Decision-Complete Checklist
- No open decisions remain for the implementer.
- Every new env var is named and scoped.
- Behavioral changes map to concrete tests or validation commands.
- Runtime wiring is identified for Python API and Next.js route surfaces.
- Rollout/backout is env-based and explicit.

### Discovery Note
- Auggie semantic search was unavailable due to `429 Too Many Requests`; this plan is based on direct file inspection and exact-string searches across:
  - `packages/notification-core/src/egp_notifications/service.py`
  - `apps/api/src/egp_api/config.py`
  - `apps/api/src/egp_api/main.py`
  - `apps/api/src/egp_api/services/auth_service.py`
  - `tests/phase2/test_notification_service.py`
  - `tests/phase4/test_auth_api.py`
  - `tests/phase4/test_admin_api.py`
  - `apps/web/src/lib/mailer.ts`
  - `apps/web/src/app/api/inquiry/route.ts`
  - `apps/api/pyproject.toml`
  - `apps/web/package.json`

## 2026-05-01 20:21:03 +0700 - Resend provider implementation

### Goal of the change
- Add a Resend-backed transactional email path so password reset, invite, verification, and inquiry emails no longer require a mailbox SMTP account as the primary delivery mechanism.

### What changed (by file) and why
- `packages/notification-core/src/egp_notifications/service.py`
  Added `ResendConfig`, provider-aware delivery selection, direct Resend HTTP sending, and explicit error surfacing while preserving injected test senders and SMTP fallback.
- `apps/api/src/egp_api/config.py`
  Added `get_email_provider()` and `get_resend_config()` so the API can resolve Resend settings from env without hard-coding transport logic in routes/services.
- `apps/api/src/egp_api/main.py`
  Wired provider selection into `NotificationService` creation so auth mail flows use Resend when configured and can fail closed when `EGP_EMAIL_PROVIDER=resend` is selected without valid Resend config.
- `apps/web/src/lib/mailer.ts`
  Replaced the SMTP-only assumption with provider-aware Resend-or-SMTP sending for inquiry emails, including Resend text/html payloads and SMTP fallback.
- `tests/phase2/test_notification_service.py`
  Added Resend-focused tests covering configured state, request payload/headers, and explicit failure handling.
- `tests/phase4/test_auth_api.py`
  Added a runtime wiring test that proves `/v1/auth/password/forgot` sends through Resend when the env is configured.
- `docker-compose.yml`
  Forwarded `EGP_EMAIL_PROVIDER`, `EGP_RESEND_API_KEY`, `EGP_RESEND_FROM`, and `EGP_RESEND_API_BASE` into both API and web containers.
- `.env.example`
  Switched the example to a Resend-first local setup while retaining SMTP fallback keys.

### TDD evidence
- Tests added/changed:
  - `tests/phase2/test_notification_service.py::test_email_delivery_configured_with_resend_config`
  - `tests/phase2/test_notification_service.py::test_send_email_message_uses_resend_http_api`
  - `tests/phase2/test_notification_service.py::test_send_email_message_raises_when_resend_returns_error`
  - `tests/phase4/test_auth_api.py::test_forgot_password_uses_resend_when_configured`
- RED command:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_service.py -q`
  - Failure reason: `ImportError: cannot import name 'ResendConfig' from 'egp_notifications.service'`
- GREEN command:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py -q`

### Tests run (exact commands) and results
- `./.venv/bin/python -m pytest tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py -q`
  Passed: `36 passed`
- `./.venv/bin/python -m ruff check apps/api packages tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py`
  Passed
- `./.venv/bin/python -m compileall apps/api/src packages`
  Passed
- `cd apps/web && npm run typecheck`
  Passed
- `cd apps/web && npm run lint`
  Passed
- `docker compose config | rg -n "EGP_(EMAIL_PROVIDER|RESEND_API_KEY|RESEND_FROM|RESEND_API_BASE)" -C 1`
  Passed

### Wiring verification evidence
- `apps/api/src/egp_api/services/auth_service.py` continues to call `NotificationService.send_email_message()` through `_send_email_if_configured()`, so the auth routes did not need any transport-specific branching.
- `apps/api/src/egp_api/main.py:create_app()` now resolves `EGP_EMAIL_PROVIDER` and passes `smtp_config` and/or `resend_config` into `NotificationService`, which is the runtime registration point for API mail delivery.
- `apps/web/src/app/api/inquiry/route.ts` still calls `sendInquiryNotification()`; only the transport logic under `apps/web/src/lib/mailer.ts` changed, so the route wiring remains intact.
- `docker-compose.yml` now exposes the Resend env vars to both the API and web processes, closing the previous config gap.

### Behavior changes and risk notes
- API auth emails and web inquiry emails now prefer Resend when `EGP_EMAIL_PROVIDER=resend` or when provider is `auto` and valid Resend config is present.
- SMTP remains supported as a fallback when Resend is not configured.
- Fail-closed behavior is intentional when `EGP_EMAIL_PROVIDER=resend` is selected but `EGP_RESEND_API_KEY` or `EGP_RESEND_FROM` is missing.
- Resend HTTP failures now raise explicit runtime errors instead of silently pretending email was sent.

### Follow-ups / known gaps
- No delivery-event webhooks, templates, or inbound reply handling were added.
- The web inquiry path is covered by typecheck/lint rather than a dedicated route/unit harness.
- Auggie remained unavailable due to `429 Too Many Requests`; implementation used direct file inspection and targeted tests.

## Review (2026-05-01 20:21:03 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree (Resend-related files only)
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- packages/notification-core/src/egp_notifications/service.py apps/api/src/egp_api/config.py apps/api/src/egp_api/main.py tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py apps/web/src/lib/mailer.ts docker-compose.yml .env.example`; `./.venv/bin/python -m pytest tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py -q`; `./.venv/bin/python -m ruff check apps/api packages tests/phase2/test_notification_service.py tests/phase4/test_auth_api.py`; `./.venv/bin/python -m compileall apps/api/src packages`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run lint`; `docker compose config | rg -n "EGP_(EMAIL_PROVIDER|RESEND_API_KEY|RESEND_FROM|RESEND_API_BASE)" -C 1`

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
- Assumed keeping SMTP as a fallback is desirable for backward compatibility even though Resend is now the preferred provider.
- Assumed `EGP_RESEND_FROM` will be set to a sender already verified in Resend before production use.

### Recommended Tests / Validation
- Set `EGP_EMAIL_PROVIDER=resend`, `EGP_RESEND_API_KEY`, and `EGP_RESEND_FROM`, then manually trigger `/v1/auth/password/forgot` against a reachable mailbox.
- Submit the `/api/inquiry` route in the target environment and confirm both ops and submitter emails appear in Resend logs.

### Rollout Notes
- No schema or migration changes.
- Rollout/backout is env-only: choose `resend`, `smtp`, or `auto` with the corresponding credentials.

## 2026-05-02 05:39:00 +0700 - root env canonicalization

### Goal of the change
- Make local env management a single-source-of-truth setup that works for Docker Compose, the API, and the Next.js app without duplicating `.env` files.

### What changed (by file) and why
- `.env`
  Created the root local env file from the existing `apps/web/.env.local` values so Compose and root-launched processes have a canonical env source.
- `apps/web/.env.local`
  Replaced the standalone file with a symlink to `../../.env` so Next.js local dev still reads the same variables without drift.

### TDD evidence
- RED command:
  Not produced. This was a local env-file layout change rather than application logic.
- GREEN command:
  `ls -la .env apps/web/.env.local && readlink apps/web/.env.local`

### Tests run (exact commands) and results
- `ls -la .env apps/web/.env.local && readlink apps/web/.env.local`
  Passed. Verified root `.env` exists and `apps/web/.env.local` points to `../../.env`.

### Wiring verification evidence
- Docker Compose auto-loads root `.env` from the repo root.
- Next.js still sees `apps/web/.env.local`, which now resolves to the same root `.env`.

### Behavior changes and risk notes
- Editing either path now affects the same underlying file.
- This was intentionally implemented as a symlink, not a copy, to avoid future config drift.

### Follow-ups / known gaps
- The root `.env` currently contains the existing local values only; Resend keys still need to be filled in manually if you want to switch delivery over.

## 2026-05-02 05:48:16 +0700 - root resend env placeholders

### Goal of the change
- Add the Resend provider entries to the canonical root `.env` so local runtime config is structurally ready for a real Resend key and sender.

### What changed (by file) and why
- `.env`
  Added `EGP_EMAIL_PROVIDER=resend`, `EGP_RESEND_API_KEY`, `EGP_RESEND_FROM`, and `EGP_RESEND_API_BASE` using placeholder/example values so the local env file now matches the implemented provider wiring.

### TDD evidence
- RED command:
  Not produced. This was a local secret/config placeholder update.
- GREEN command:
  `sed -n '1,40p' .env`

### Tests run (exact commands) and results
- `sed -n '1,40p' .env`
  Passed. Verified the Resend keys are present in the canonical root env file.

### Wiring verification evidence
- `apps/web/.env.local` already symlinks to `../../.env`, so the new Resend entries are visible to Next.js local dev immediately.
- Root `.env` is also the file Docker Compose auto-loads from the repo root.

### Behavior changes and risk notes
- The app is now configured to prefer Resend locally, but delivery will still fail until `EGP_RESEND_API_KEY` and `EGP_RESEND_FROM` are replaced with real working values.

### Follow-ups / known gaps
- The secret and sender are placeholders only; they need to be replaced before restarting the services.

## 2026-05-02 06:04:59 +0700 - local uvicorn restart

### Goal of the change
- Restart the local API `uvicorn` process and ensure it comes up successfully with the shared root `.env`.

### What changed (by file) and why
- `.env`
  Quoted the `EGP_RESEND_FROM` value so `source .env` works in shell-launched local API commands.
- `.env.example`
  Quoted the example `EGP_RESEND_FROM` value for the same reason and to keep the example shell-safe.

### TDD evidence
- RED command:
  - `../../.venv/bin/uvicorn src.main:app --reload --host 127.0.0.1 --port 8010`
  - Failure reason: `RuntimeError("DATABASE_URL is required")` because bare local `uvicorn` does not auto-load root `.env`.
- Additional failure discovered:
  - `set -a; source ../../.env; set +a; nohup ../../.venv/bin/uvicorn ...`
  - Failure reason: shell parse error from unquoted `EGP_RESEND_FROM` with angle brackets.
- GREEN command:
  - `set -a; source ../../.env; set +a; ../../.venv/bin/uvicorn src.main:app --reload --host 127.0.0.1 --port 8010`

### Tests run (exact commands) and results
- `curl -fsS http://127.0.0.1:8010/health`
  Passed. Returned `{"status":"ok"}`.
- `lsof -nP -iTCP:8010 -sTCP:LISTEN`
  Passed. Verified local Python processes are listening on `127.0.0.1:8010`.

### Wiring verification evidence
- Local API launch now depends on `set -a; source ../../.env; set +a` from `apps/api` so the root canonical env file is loaded.
- `apps/web/.env.local` still symlinks to the same root `.env`, so quoting the sender value is compatible with both Next.js local env parsing and shell sourcing.

### Behavior changes and risk notes
- Local shell-launched `uvicorn` now starts successfully with the shared env file.
- The running local API process is on `127.0.0.1:8010`, matching the existing local setup.

### Follow-ups / known gaps
- If you later restart `uvicorn` manually, use the env-sourced form or a wrapper script; plain `uvicorn` from `apps/api` still will not auto-load root `.env` by itself.

## 2026-05-02 06:14:47 +0700 - local web restart

### Goal of the change
- Restart the local Next.js web app on port `3002` and verify it is serving with the shared `.env.local` symlinked config.

### What changed (by file) and why
- No repo files changed for the restart itself.

### TDD evidence
- RED command:
  - `nohup ./scripts/dev-web.sh --hostname 127.0.0.1 --port 3002 >/tmp/egp-web-dev.log 2>&1 &`
  - Failure reason: the detached process exited immediately without staying attached; the successful path was confirmed by running the same command in the foreground.
- GREEN command:
  - `./scripts/dev-web.sh --hostname 127.0.0.1 --port 3002`

### Tests run (exact commands) and results
- `curl -I -sS http://127.0.0.1:3002`
  Passed. Returned `HTTP/1.1 200 OK`.
- `lsof -nP -iTCP:3002 -sTCP:LISTEN`
  Passed. Verified Node is listening on `127.0.0.1:3002`.

### Wiring verification evidence
- `apps/web/scripts/dev-web.sh` launches `npx next dev`.
- Next.js reported `Environments: .env.local`, and `apps/web/.env.local` already symlinks to the canonical root `.env`.

### Behavior changes and risk notes
- The local web app is now running interactively on `127.0.0.1:3002`.
- No code-path behavior changed; this was a runtime restart only.

### Follow-ups / known gaps
- The current working web session is a live foreground dev process rather than a detached service.

## 2026-05-02 06:17:36 +0700 - web inquiry runtime validation

### Goal of the change
- Validate that the local web inquiry route can actually send through Resend after the web restart.

### What changed (by file) and why
- No repo files changed during this validation step.

### TDD evidence
- RED command:
  - `curl -sS -X POST http://127.0.0.1:3002/api/inquiry -F 'services=tor' -F 'packageSize=small' -F 'projectRef=TEST-RESEND-002' -F 'companyName=EGP Local Test' -F 'contactName=Subhaj Test' -F 'email=limanond.subhaj@gmail.com' -F 'phone=0800000000' -F 'notes=Local Resend inquiry test after clean restart'`
  - Failure reason: Resend returned `403` with `The gmail.com domain is not verified`.
- GREEN command:
  - Not produced for delivery itself because the provider rejected the sender domain. Route reachability was still confirmed with `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3002` returning `200`.

### Tests run (exact commands) and results
- `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3002`
  Passed. Returned `200`.
- `curl -sS -X POST http://127.0.0.1:3002/api/inquiry ...`
  Failed at provider layer. Response body: `{"ok":false,"error":"Failed to process submission"}`.
- Next.js server log
  Showed the route executed, skipped unset `OPS_EMAIL`, and then raised:
  - `Resend email delivery failed (403): {"statusCode":403,"message":"The gmail.com domain is not verified. Please, add and verify your domain on https://resend.com/domains","name":"validation_error"}`

### Wiring verification evidence
- The route reached `sendInquiryNotification()` successfully.
- The mailer selected Resend and called the provider API.
- Failure occurred after transport selection, at Resend sender-domain validation.

### Behavior changes and risk notes
- The web app integration is structurally correct.
- Actual delivery is blocked until `EGP_RESEND_FROM` uses a sender on a domain verified in the connected Resend account.

### Follow-ups / known gaps
- `OPS_EMAIL` is still unset, so the inquiry flow currently attempts only the submitter confirmation email.

## Review (2026-05-02 06:26:36 +0700) - system

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: external subsystem pattern review (`swoc*` auth-email implementations)
- Commands Run: `find /Users/subhajlimanond/dev -maxdepth 1 -type d -name 'swoc*' | sort`; `rg -n "resend|RESEND|magic link|signIn|forgot password|verification|nodemailer|smtp" ...`; targeted `sed -n` reads of package files and auth/email route/service files
- Sources: `/Users/subhajlimanond/dev/swoc-dev-2/swoc-nlp-web-config-4/package.json`; `/Users/subhajlimanond/dev/swoc-dev-2/swoc-nlp-web-config-4/app/api/public-forgot-password/route.js`; `/Users/subhajlimanond/dev/swoc-dev-2/swoc-nlp-web-config-4/app/api/setup-account/send-verification/route.js`; `/Users/subhajlimanond/dev/swoc-dev-2/swoc-nlp-web-config-4/app/api/email/route.js`; `/Users/subhajlimanond/dev/swoc-social-listening-fullstack/apps/backend/src/services/email.service.ts`; `/Users/subhajlimanond/dev/swoc-social-listening-fullstack/apps/backend/src/controllers/user-account.controller.ts`

### High-Level Assessment
- I did not find a Resend-based login or auth-email implementation in the `swoc*` repos inspected.
- The two repos with relevant auth-email flows both use `nodemailer` and SMTP.
- `swoc-dev-2/swoc-nlp-web-config-4` is a Next.js app where forgot-password sends directly from the route, while verification flows delegate to an internal `/api/email` route.
- `swoc-social-listening-fullstack` is an Express/Node backend with a centralized `EmailService` that sends welcome/login-credential emails via SMTP and falls back to Ethereal for testing.

### Strengths
- `swoc-dev-2/swoc-nlp-web-config-4` separates verification token generation from delivery and centralizes templated delivery in `/api/email`.
- `swoc-social-listening-fullstack` has a clean service abstraction for account email and a testing fallback via Ethereal.

### Key Risks / Gaps (severity ordered)
CRITICAL
- No critical findings.

HIGH
- No Resend integration was found, so there is no proven Resend sender/domain pattern to reuse directly from these repos.

MEDIUM
- `swoc-dev-2/swoc-nlp-web-config-4` mixes two delivery styles for auth email:
  - direct SMTP in `app/api/public-forgot-password/route.js`
  - indirect SMTP via `app/api/email/route.js` from `app/api/setup-account/send-verification/route.js`
  This split increases drift risk between auth flows.

LOW
- `swoc-social-listening-fullstack` sends initial login credentials in plaintext welcome emails via `EmailService.sendWelcomeEmail()`, which is a product decision but not a pattern to copy into EGP.

### Nit-Picks / Nitty Gritty
- `swoc-dev-2/swoc-nlp-web-config-4/package.json` includes `nodemailer` but nothing Resend-related.
- `swoc-dev-2/swoc-nlp-web-config-4/app/api/public-forgot-password/route.js` reads `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`/`SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` and optionally falls back to DB table `swoc_email_config`.
- `swoc-dev-2/swoc-nlp-web-config-4/app/api/email/route.js` is the central template mail API for `verification`, `approval`, and `reset_password`, again entirely over SMTP.
- `swoc-social-listening-fullstack/apps/backend/src/services/email.service.ts` initializes `nodemailer.createTransport(...)` from `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_SECURE`, else falls back to `nodemailer.createTestAccount()` for Ethereal.

### Tactical Improvements (1–3 days)
1. If you want to borrow from `swoc*`, copy the architectural shape, not the transport: central email service/API plus flow-specific templates.
2. Keep EGP’s provider abstraction and swap only the transport backend, because the `swoc*` repos do not solve the Resend verified-domain requirement.

### Strategic Improvements (1–6 weeks)
1. If you later unify all EGP outbound mail, the best `swoc*` idea to reuse is the centralized mailer boundary, not the SMTP implementation.

### Open Questions / Assumptions
- Assumed `swoc-dev-2/swoc-nlp-web-config-4` is the repo you had in mind because it contains forgot-password and verification email flows.
- Assumed “user login” here includes welcome/setup, verification, and forgot-password style auth-adjacent email.

## 2026-05-02 06:40:37 +07 - Local fallback to Gmail SMTP

### Goal of the change
- Switch the local EGP runtime from Resend back to SMTP and point both API and web mail delivery at `limanond.subhaj@gmail.com`.

### What changed (by file) and why
- [`.env`](/Users/subhajlimanond/dev/egp/.env:1)
  - Changed `EGP_EMAIL_PROVIDER` from `resend` to `smtp`.
  - Added Gmail SMTP settings: `EGP_SMTP_HOST`, `EGP_SMTP_PORT`, `EGP_SMTP_USERNAME`, `EGP_SMTP_FROM`, `EGP_SMTP_USE_TLS`.
  - Added `OPS_EMAIL=limanond.subhaj@gmail.com` so the inquiry route has an ops recipient in SMTP mode.
  - Left `EGP_SMTP_PASSWORD` empty because the real Gmail app password is not available in the repo and cannot be inferred safely.

### TDD evidence
- Tests added/changed:
  - None. This was an operational env switch, not an application code change.
- RED command:
  - `curl -s -o /tmp/egp_inquiry_smtp.json -w '%{http_code}\n' -X POST http://127.0.0.1:3002/api/inquiry -F 'services=tor' -F 'packageSize=small' -F 'projectRef=TEST-SMTP-001' -F 'companyName=EGP Local Test' -F 'contactName=Subhaj Test' -F 'email=limanond.subhaj@gmail.com' -F 'phone=0800000000' -F 'notes=Local SMTP inquiry test' && cat /tmp/egp_inquiry_smtp.json`
  - Failure reason: the web mailer rejected SMTP setup because `EGP_SMTP_PASSWORD` is still empty and threw `SMTP is not configured. Set EGP_SMTP_HOST, EGP_SMTP_USERNAME, and EGP_SMTP_PASSWORD.`
- GREEN command:
  - `curl -s http://127.0.0.1:8010/health`
  - Passed with `{"status":"ok"}` after restarting uvicorn against the SMTP-based `.env`.
- Why no full GREEN delivery run:
  - A real Gmail SMTP app password is required to authenticate; without that secret, no successful delivery run can be produced.

### Tests run (exact commands) and results
- `set -a; source .env; set +a; printf 'provider=%s\nsmtp_host=%s\nsmtp_user=%s\nsmtp_pass_len=%s\n' "$EGP_EMAIL_PROVIDER" "$EGP_SMTP_HOST" "$EGP_SMTP_USERNAME" "${#EGP_SMTP_PASSWORD}"`
  - Confirmed the local shell resolves `provider=smtp`, `smtp_host=smtp.gmail.com`, `smtp_user=limanond.subhaj@gmail.com`, and `smtp_pass_len=0`.
- `curl -s http://127.0.0.1:8010/health`
  - Passed. Returned `{"status":"ok"}`.
- `lsof -nP -iTCP:8010 -sTCP:LISTEN && lsof -nP -iTCP:3002 -sTCP:LISTEN`
  - Passed. Confirmed local API on `127.0.0.1:8010` and web on `127.0.0.1:3002`.
- `curl -s -o /tmp/egp_inquiry_smtp.json -w '%{http_code}\n' -X POST http://127.0.0.1:3002/api/inquiry ...`
  - Failed with `500` and body `{"ok":false,"error":"Failed to process submission"}`.
- Next.js dev log
  - Confirmed the route reached `sendInquiryNotification()` and failed in `getSmtpTransporter()` because `EGP_SMTP_PASSWORD` is empty.

### Wiring verification evidence
- `apps/web/src/lib/mailer.ts` selected the SMTP branch because `EGP_EMAIL_PROVIDER=smtp`.
- `apps/web/src/app/api/inquiry/route.ts` reached `sendInquiryNotification()` successfully and failed only at transport setup validation.
- `apps/api/src/egp_api/main.py` constructs `NotificationService` with SMTP config when `get_email_provider()` resolves to `smtp`, so the API auth mail path is pointed at the same Gmail SMTP configuration.

### Behavior changes and risk notes
- Both local servers are now running with SMTP selected instead of Resend.
- Actual email delivery is still blocked until `EGP_SMTP_PASSWORD` is filled with a valid Gmail app password for `limanond.subhaj@gmail.com`.
- Using a personal Gmail mailbox as sender is operationally workable for local testing, but it remains a poor long-term production sender identity.

### Follow-ups / known gaps
- Set `EGP_SMTP_PASSWORD` in the root `.env` to the real Gmail app password, then restart the API and web processes and re-run the inquiry/reset flow.

## 2026-05-02 13:24:50 +07 - Gmail SMTP validation succeeded

### Goal of the change
- Verify that the live local EGP web inquiry flow can now send through Gmail SMTP after the app password was added to the shared root `.env`.

### What changed (by file) and why
- No code files changed.
- Operational state changed because the existing root [`.env`](/Users/subhajlimanond/dev/egp/.env:1) now contains a non-empty `EGP_SMTP_PASSWORD`, and both local processes were restarted to load the updated env.

### TDD evidence
- Tests added/changed:
  - None. This was runtime validation of existing wiring.
- RED command:
  - Not produced in this validation pass because the prior failure case had already been captured above (`EGP_SMTP_PASSWORD` missing). This pass specifically re-ran the same flow after the secret was populated.
- GREEN command:
  - `curl -s -o /tmp/egp_inquiry_smtp_retry.json -w '%{http_code}\n' -X POST http://127.0.0.1:3002/api/inquiry -F 'services=tor' -F 'packageSize=small' -F 'projectRef=TEST-SMTP-002' -F 'companyName=EGP Local Test' -F 'contactName=Subhaj Test' -F 'email=limanond.subhaj@gmail.com' -F 'phone=0800000000' -F 'notes=Local SMTP inquiry retest after app-password update' && cat /tmp/egp_inquiry_smtp_retry.json`
  - Passed with:
    - `200`
    - `{"ok":true}`

### Tests run (exact commands) and results
- `curl -s http://127.0.0.1:8010/health`
  - Passed. Returned `{"status":"ok"}`.
- `curl -s -o /tmp/egp_inquiry_smtp_retry.json -w '%{http_code}\n' -X POST http://127.0.0.1:3002/api/inquiry ...`
  - Passed. Returned `200` and `{"ok":true}`.
- Next.js dev log
  - Confirmed the route compiled and processed the submission without transport errors.

### Wiring verification evidence
- `apps/web/src/app/api/inquiry/route.ts` reached `sendInquiryNotification()` successfully.
- `apps/web/src/lib/mailer.ts` selected the SMTP branch and completed without throwing.
- The API process was also restarted against the same root `.env`, so auth-related mail paths now point at the same working Gmail SMTP credentials.

### Behavior changes and risk notes
- Local SMTP delivery is now operational for the web inquiry flow.
- Because `OPS_EMAIL` and the submitter email are both `limanond.subhaj@gmail.com` in the current local env, one inquiry submission likely generates two messages to the same inbox: the ops notification and the submitter confirmation.
- This validates local transport, not inbox placement quality; Gmail may still classify messages into categories or spam based on content and sender reputation.

### Follow-ups / known gaps
- If you want clearer local testing, set `OPS_EMAIL` to a different inbox so the ops and confirmation messages are easy to distinguish.
- The auth flows should now also be able to use Gmail SMTP, but they were not exercised in this specific pass.

## 2026-05-04 07:29:33 +07 - Fixed local registration API target

### Goal of the change
- Restore local self-registration from the Next.js frontend after the browser showed `ERR_CONNECTION_REFUSED` on `:8000/v1/auth/register` and `:8000/v1/me`.

### What changed (by file) and why
- [`.env`](/Users/subhajlimanond/dev/egp/.env:22)
  - Changed `NEXT_PUBLIC_EGP_API_BASE_URL` from `http://127.0.0.1:8000` to `http://127.0.0.1:8010`.
  - Reason: the local FastAPI server was listening on `127.0.0.1:8010`, while nothing was bound to port `8000`. The public frontend env overrode the safe `8010` fallback already present in `apps/web/src/lib/api.ts`.

### TDD evidence
- Tests added/changed:
  - None. This was a runtime config fix plus end-to-end verification.
- RED command:
  - `curl -sS -o /tmp/egp_api8000_probe.txt -w '%{http_code}\n' http://127.0.0.1:8000/v1/me || true`
  - Failure reason: connection refused because no local API process was listening on port `8000`.
- GREEN command:
  - `curl -s -c /tmp/egp-register-cookie.txt -o /tmp/egp-register.json -w '%{http_code}\n' -X POST http://127.0.0.1:8010/v1/auth/register -H 'Content-Type: application/json' --data '{"company_name":"Codex Verify Co 20260504072908","email":"codex.verify.20260504072908@example.com","password":"verify-pass-123"}' && cat /tmp/egp-register.json`
  - Passed with `200` and a valid `CurrentSessionResponse`.

### Tests run (exact commands) and results
- `lsof -nP -iTCP:8010 -sTCP:LISTEN || true`
  - Passed. Confirmed local API was on `127.0.0.1:8010`.
- `lsof -nP -iTCP:8000 -sTCP:LISTEN || true`
  - Returned no listener.
- `curl -s http://127.0.0.1:8010/health`
  - Passed. Returned `{"status":"ok"}`.
- `curl -s -c /tmp/egp-register-cookie.txt -o /tmp/egp-register.json -w '%{http_code}\n' -X POST http://127.0.0.1:8010/v1/auth/register -H 'Content-Type: application/json' --data '{"company_name":"Codex Verify Co 20260504072908","email":"codex.verify.20260504072908@example.com","password":"verify-pass-123"}' && cat /tmp/egp-register.json`
  - Passed. Created a new `free_trial` tenant and `owner` user.
- `curl -s -b /tmp/egp-register-cookie.txt http://127.0.0.1:8010/v1/me`
  - Passed. Confirmed the issued session cookie authenticates the new account.
- `psql 'postgresql://egp:egp_dev@localhost:5432/egp' -F $'\t' -Atc "select t.slug, t.plan_code, u.email, u.role, u.status, coalesce(to_char(u.email_verified_at,'YYYY-MM-DD HH24:MI:SS TZ'),'') from users u join tenants t on t.id=u.tenant_id where lower(u.email)='codex.verify.20260504072908@example.com';"`
  - Passed. Confirmed DB persistence: tenant plan `free_trial`, role `owner`, status `active`.

### Wiring verification evidence
- `apps/web/src/lib/api.ts:getApiBaseUrl()` defaults to `8010`, but it first honors `NEXT_PUBLIC_EGP_API_BASE_URL`.
- `apps/web/src/lib/api.ts:register()`, `login()`, and `fetchMe()` all build their URLs through `buildUrl()` and therefore inherit that public API base URL.
- Restarting the Next.js dev server was required so the updated public env value from the root `.env` symlinked through `apps/web/.env.local` was reloaded.

### Behavior changes and risk notes
- Local browser registration/login/session bootstrap should now target the live API on `127.0.0.1:8010` instead of a dead `8000`.
- This fix is local-env specific. If another environment truly hosts the API on `8000`, that environment still needs its own correct env file.
- Auggie MCP remained unavailable (`429 Too Many Requests`), so this debug pass used direct file inspection and runtime probes.

### Follow-ups / known gaps
- Reload any stale browser tab that was opened before the Next.js restart so it picks up the rebuilt client bundle.
- The missing `favicon.ico` and `data-scroll-behavior="smooth"` warning are unrelated to registration and were not addressed here.

## 2026-05-08 09:57:24 +07 - Reset free-trial keyword slot for tenant `lll`

### Goal of the change
- Reset the free-trial tenant `lll` for user `limanond.subhaj@gmail.com` so the tenant can add a new keyword again.

### What changed (by file) and why
- No code files changed.
- Database state changed in local Postgres:
  - Deactivated the tenant’s only active crawl profile in `crawl_profiles` by setting `is_active=false`.
  - Reason: free trial currently allows `keyword_limit=1`, and tenant `lll` already had one active keyword (`คลังข้อมูล ระบบสารสนเทศ`) on one active profile. The rules/entitlement logic counts active keywords across active profiles, so deactivating that profile reopens one slot without disturbing the subscription or user account.

### TDD evidence
- Tests added/changed:
  - None. This was an operational tenant-state reset.
- RED command:
  - `./.venv/bin/python - <<'PY' ... service.get_snapshot(tenant_id='db354496-da2d-4c58-a95b-f75e7055704a') ... PY`
  - Pre-change failure condition:
    - `plan_code=free_trial`
    - `subscription_status=active`
    - `keyword_limit=1`
    - `active_keyword_count=1`
    - `remaining_keyword_slots=0`
    - `active_keywords=['คลังข้อมูล ระบบสารสนเทศ']`
  - Failure reason: no remaining keyword slots, so adding a new active keyword would exceed the free-trial plan limit.
- GREEN command:
  - `./.venv/bin/python - <<'PY' ... service.get_snapshot(tenant_id='db354496-da2d-4c58-a95b-f75e7055704a') ... PY`
  - Post-change result:
    - `plan_code=free_trial`
    - `subscription_status=active`
    - `keyword_limit=1`
    - `active_keyword_count=0`
    - `remaining_keyword_slots=1`
    - `active_keywords=[]`
    - `over_keyword_limit=False`

### Tests run (exact commands) and results
- `psql 'postgresql://egp:egp_dev@localhost:5432/egp' -F $'\t' -Atc "select t.id, t.slug, t.name, t.plan_code, t.is_active, u.id, u.email, u.role, u.status from tenants t left join users u on u.tenant_id=t.id where t.slug='lll' or lower(u.email)=lower('limanond.subhaj@gmail.com') order by t.slug, u.email;"`
  - Passed. Confirmed tenant `lll` and active owner `limanond.subhaj@gmail.com`.
- `psql 'postgresql://egp:egp_dev@localhost:5432/egp' -F $'\t' -Atc "select cp.id, cp.name, cp.profile_type, cp.is_active, cpk.id, cpk.keyword, cpk.position from crawl_profiles cp left join crawl_profile_keywords cpk on cpk.profile_id=cp.id where cp.tenant_id='db354496-da2d-4c58-a95b-f75e7055704a' order by cp.created_at, cpk.position;"`
  - Pre-change: one active profile `คำค้นหลัก` with keyword `คลังข้อมูล ระบบสารสนเทศ`.
- `psql 'postgresql://egp:egp_dev@localhost:5432/egp' -c "update crawl_profiles set is_active=false, updated_at=now() where tenant_id='db354496-da2d-4c58-a95b-f75e7055704a' and is_active=true;"`
  - Passed. Updated `1` row.
- `./.venv/bin/python - <<'PY' ... TenantEntitlementService.get_snapshot(...) ... PY`
  - Passed. Confirmed `active_keyword_count=0` and `remaining_keyword_slots=1` after the reset.
- `psql 'postgresql://egp:egp_dev@localhost:5432/egp' -F $'\t' -Atc "select cp.id, cp.name, cp.is_active, coalesce(string_agg(cpk.keyword, ', ' order by cpk.position), '') from crawl_profiles cp left join crawl_profile_keywords cpk on cpk.profile_id=cp.id where cp.tenant_id='db354496-da2d-4c58-a95b-f75e7055704a' group by cp.id, cp.name, cp.is_active order by cp.created_at;"`
  - Passed. Confirmed the profile now exists as inactive (`f`) and still retains its keyword history.

### Wiring verification evidence
- `apps/api/src/egp_api/services/entitlement_service.py` computes `active_keyword_count` from `profile_repository.list_active_keywords(tenant_id=tenant_id)`.
- `packages/db/src/egp_db/repositories/profile_repo.py:list_active_keywords()` only includes keywords from profiles where `profile.is_active` is true.
- `apps/api/src/egp_api/services/rules_service.py:create_profile()` blocks new keyword creation only when `len(prospective_keywords) > snapshot.keyword_limit`.
- Therefore deactivating the only active profile correctly resets the tenant from `1 / 1` to `0 / 1` active keywords.

### Behavior changes and risk notes
- Tenant `lll` can now add one new active keyword under the free-trial plan.
- The previous keyword configuration was not deleted; it is preserved on an inactive profile for reference/history.
- If someone reactivates the old profile before removing/replacing keywords, the tenant will go back to having zero remaining slots.
- Auggie MCP remained unavailable (`429 Too Many Requests`), so this reset used direct file inspection plus database verification.

### Follow-ups / known gaps
- If the user wants a full “clean slate” in the UI, the next step would be adding a supported profile edit/deactivate route instead of operational DB changes.

## Review (2026-05-08 10:10:15 +07) - bug-path review

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree / live discovery investigation for run `597f60a1-d13a-414b-aed7-d46b4db912f7`
- Commands Run: `rg -n "LIVE_PROGRESS|keyword_no_results|search_keyword|is_no_results_page|get_results_rows|status_matches_target" apps packages tests -S`; targeted `sed -n` and `nl -ba` reads of `apps/worker/src/egp_worker/browser_discovery.py`, `apps/worker/src/egp_worker/workflows/discover.py`, `apps/web/src/lib/run-progress.ts`, and `tests/phase1/test_worker_browser_discovery.py`; `psql` reads of `crawl_runs` / `crawl_tasks`; two bounded live repro scripts against `https://process5.gprocurement.go.th/egp-agpc01-web/announcement`

### Findings
HIGH
- The worker can falsely conclude `keyword_no_results` before the e-GP results table finishes hydrating. In [apps/worker/src/egp_worker/browser_discovery.py](/Users/subhajlimanond/dev/egp/apps/worker/src/egp_worker/browser_discovery.py:1542), `wait_for_results_ready()` returns as soon as `is_no_results_page()` becomes true during any of only three 1-second polls. The live reproduction showed the exact same page state transition for keyword `คลังข้อมูล`: at `t=0` the results table body was `ไม่พบข้อมูล`, but at `t=1` the table had `10` rows. Because [search_keyword()](/Users/subhajlimanond/dev/egp/apps/worker/src/egp_worker/browser_discovery.py:1728) treats that early return as final and the main crawl loop immediately emits `keyword_no_results` at [browser_discovery.py:204](/Users/subhajlimanond/dev/egp/apps/worker/src/egp_worker/browser_discovery.py:204), the crawler silently drops real matches. Fix direction: require the no-results state to remain stable for a minimum settle window or until the result marker stops changing, instead of treating the first placeholder render as final. Test needed: a browser-discovery unit test where the table first renders a placeholder `ไม่พบข้อมูล` row and then real rows on the next poll.

- A false-negative crawl is reported as a green success all the way to the UI. The discover workflow finishes as `succeeded` whenever no exception is raised, even if zero projects were persisted, at [apps/worker/src/egp_worker/workflows/discover.py](/Users/subhajlimanond/dev/egp/apps/worker/src/egp_worker/workflows/discover.py:367). The frontend then renders `keyword_no_results` as a neutral progress string in [apps/web/src/lib/run-progress.ts](/Users/subhajlimanond/dev/egp/apps/web/src/lib/run-progress.ts:42) while the run status remains successful. In your concrete case, the run row showed `succeeded` with `projects_seen=0`, even though the live repro found `10` visible rows and at least three first-page rows whose statuses matched the crawler’s target (`หนังสือเชิญชวน/ประกาศเชิญชวน`). This is a silent correctness bug, not just a UX nit, because operators are told the crawl finished normally when it actually missed eligible procurement records. Fix direction: distinguish “completed with verified zero matches” from “crawler uncertainty / ambiguous zero result”, and fail or mark partial when the search page shows a transient no-results shell followed by rows. Validation needed: integration coverage that forces this transient state and asserts the run is not marked plain `succeeded`.

MEDIUM
- The no-results branch has almost no forensic output, so debugging live misses is harder than it needs to be. There is a purpose-built `log_results_debug_snapshot()` helper in [apps/worker/src/egp_worker/browser_discovery.py](/Users/subhajlimanond/dev/egp/apps/worker/src/egp_worker/browser_discovery.py:2053), but the `keyword_no_results` branch at [browser_discovery.py:204](/Users/subhajlimanond/dev/egp/apps/worker/src/egp_worker/browser_discovery.py:204) only emits a terse progress event and the artifact directory stores only `worker.log`. That is why the original run log could not tell whether the page was truly empty, temporarily empty, or blocked by a stale widget state. The current tests also miss this class of race: [tests/phase1/test_worker_browser_discovery.py](/Users/subhajlimanond/dev/egp/tests/phase1/test_worker_browser_discovery.py:1084) stubs `is_no_results_page()` as an immediate boolean sequence, but there is no test for “placeholder no-results first, real rows later.” Fix direction: capture a debug snapshot or HTML/PNG artifact before accepting `keyword_no_results`, and add a regression test that models delayed row hydration.

LOW
- The `(node:...) [DEP0169] url.parse()` warning in the worker log is noise, not the cause of this miss. It should still be cleaned up because it pollutes live debugging output and can distract operators from the real crawler state. Validation needed: run the worker entrypoint with deprecation traces once after replacing legacy URL parsing.

### Open Questions / Assumptions
- Assumed the target business behavior is to collect rows in status `หนังสือเชิญชวน/ประกาศเชิญชวน`; the live repro confirmed such rows exist on the first results page for `คลังข้อมูล`.
- Assumed the screenshot and the reproduced query are against the same public search surface (`/announcement`) and budget year `2569`, which matched the live page default on May 8, 2026.

### Recommended Tests / Validation
- Add a unit test for `wait_for_results_ready()` where `get_results_rows()` returns `[]`, `is_no_results_page()` returns `True` on the first poll, and rows appear on the second/third poll; assert the function does not settle early.
- Add an integration test around `search_keyword()` / `crawl_live_discovery()` that simulates the e-GP shell row `ไม่พบข้อมูล` before the async result payload arrives.
- Add a workflow test asserting that ambiguous zero-result crawls are not marked plain `succeeded`.
- Preserve and inspect an HTML or screenshot artifact whenever `keyword_no_results` is emitted in live runs.

### Rollout Notes
- Any fix here changes crawl behavior on the public e-GP site, so keep the first rollout behind extra logging/artifact capture.
- Re-run the exact tenant/profile/keyword (`lll`, profile `dca2b7a1-12c1-413b-8876-a0e53d915fa4`, keyword `คลังข้อมูล`) after the fix as the primary regression check.
