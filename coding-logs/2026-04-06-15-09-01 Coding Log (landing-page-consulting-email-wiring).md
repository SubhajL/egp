# Landing Page, Consulting Services & Email Wiring

## Implementation (2026-04-06 15:09 local)

### Goal
Build and fully optimize a public-facing landing page for the e-GP Intelligence Platform, add a consulting services section with an inquiry form, and wire up real SMTP email notifications for form submissions.

### What Changed

#### `apps/web/src/app/globals.css`
- Added `scroll-behavior: smooth` for anchor-link navigation.
- Added FAQ chevron rotate animation CSS.
- **Critical bug fix**: moved `a { color: inherit }` into `@layer base` so Tailwind v4 utility classes (`text-*`) correctly override it on `<a>`/`<Link>` elements. Previously the unlayered rule beat all `@layer utilities` classes on every link tag.

#### `apps/web/src/app/layout.tsx`
- Added global `metadataBase` pointing to `NEXT_PUBLIC_SITE_URL` (fallback: `https://egp.example.com`).

#### `apps/web/src/app/page.tsx` (new — full landing page)
- Sticky navbar with smooth-scroll links: ฟีเจอร์, บริการ, ราคา, คำถาม.
- Hero section with primary CTA → `/login`.
- Trust bar, features bento grid, how-it-works timeline.
- **`#services` section**: two process cards (TOR Proposal Preparation + POC/Pilot Development), pricing table (S < 5M ฿50k/7d, M < 10M ฿100k/10d), payment terms panel (50% down, 50% before delivery, down payment must arrive 7 days before proposal submission), disclaimer panel, CTA → `/inquiry`.
- Pricing section for SaaS plans (Free Trial / One-Time / Monthly).
- FAQ section (7 questions including payment method Q — PromptPay QR and Bank Transfer only).
- CTA banner and footer.
- Full SEO metadata + JSON-LD `@graph` (Organization, WebSite, WebPage, BreadcrumbList, SoftwareApplication, FAQPage).
- `Badge` component extended with `"indigo-light"` variant for dark card backgrounds.

#### `apps/web/src/app/inquiry/page.tsx` (new)
- Client Component inquiry form with 5 sections:
  1. Service selection (TOR Proposal, POC/Pilot, or both)
  2. Project info (e-GP reference number OR file upload)
  3. Package picker (S / M)
  4. Company and contact fields
  5. Notes
- Required field validation before submission.
- Success screen shown on submit.
- POSTs to `/api/inquiry` as `multipart/form-data`.

#### `apps/web/src/app/api/inquiry/route.ts` (new → then updated)
- Initially created as a stub that logged and returned `{ok:true}`.
- **Updated**: replaced TODO stub with a real call to `sendInquiryNotification()`.
- Parses `FormData`, builds `InquiryData`, calls mailer, returns `{ok:true}` on success or `500` on failure.

#### `apps/web/src/lib/mailer.ts` (new)
- Thin SMTP client using `nodemailer`.
- Reads the same `EGP_SMTP_*` env vars as the Python `notification-core` package for consistency.
- `getSmtpTransporter()` — builds and returns a configured `nodemailer.Transporter`; throws a clear error if SMTP env vars are absent.
- `sendInquiryNotification(data: InquiryData)` — sends two emails concurrently:
  - **Ops notification** → `OPS_EMAIL` env var: structured HTML table with all inquiry fields, service/package labels in Thai.
  - **Submitter confirmation** → `data.email`: Thai-language receipt with inquiry summary and 1-business-day response SLA.
- Gracefully skips ops notification (with a `console.warn`) if `OPS_EMAIL` is not set, so the confirmation still goes out.

#### `apps/web/src/app/sitemap.ts` (new)
- Includes `/` (priority 1.0) and `/inquiry` (priority 0.7).

#### `apps/web/src/app/robots.ts` (new)
- Allows `/` and `/inquiry`; disallows all protected `/(app)/` routes.

#### `apps/web/src/app/opengraph-image.tsx` (new)
- Edge-rendered 1200×630 OG image with platform name and tagline.

#### `apps/web/package.json` + `package-lock.json`
- Added `nodemailer` (runtime) and `@types/nodemailer` (dev dependency).

### Tests Run
- `cd apps/web && npm run typecheck` → clean
- `cd apps/web && npm run build` → clean, 20 routes, no warnings beyond pre-existing edge-runtime OG image notice

### Wiring Verification

| Component | Entry Point | Registration | Env Vars |
|---|---|---|---|
| Landing page | `GET /` | `apps/web/src/app/page.tsx` | `NEXT_PUBLIC_SITE_URL` |
| Inquiry form | `GET /inquiry` | `apps/web/src/app/inquiry/page.tsx` | — |
| Inquiry API handler | `POST /api/inquiry` | `apps/web/src/app/api/inquiry/route.ts` | — |
| SMTP mailer | called by route handler | `apps/web/src/lib/mailer.ts` | `EGP_SMTP_HOST`, `EGP_SMTP_PORT`, `EGP_SMTP_USERNAME`, `EGP_SMTP_PASSWORD`, `EGP_SMTP_FROM`, `EGP_SMTP_USE_TLS`, `OPS_EMAIL` |
| OG image | `GET /opengraph-image` | `apps/web/src/app/opengraph-image.tsx` | `NEXT_PUBLIC_SITE_URL` |
| Sitemap | `GET /sitemap.xml` | `apps/web/src/app/sitemap.ts` | `NEXT_PUBLIC_SITE_URL` |
| Robots | `GET /robots.txt` | `apps/web/src/app/robots.ts` | `NEXT_PUBLIC_SITE_URL` |

### Required Env Vars (new)

| Var | Example | Notes |
|---|---|---|
| `NEXT_PUBLIC_SITE_URL` | `https://egp.example.com` | Canonical domain for SEO/OG |
| `EGP_SMTP_HOST` | `smtp.gmail.com` | Same var as Python backend |
| `EGP_SMTP_PORT` | `587` | Same var as Python backend |
| `EGP_SMTP_USERNAME` | `no-reply@example.com` | Same var as Python backend |
| `EGP_SMTP_PASSWORD` | `app-password` | Same var as Python backend |
| `EGP_SMTP_FROM` | `"e-GP Platform <no-reply@example.com>"` | Same var as Python backend |
| `EGP_SMTP_USE_TLS` | `true` | Same var as Python backend |
| `OPS_EMAIL` | `ops@example.com` | New — ops team inbox for inquiry notifications |

### Behavior Changes and Risks
- The landing page (`/`) is now a real public page instead of a redirect stub.
- `/inquiry` and `/api/inquiry` are new public routes — no auth required by design.
- Email sending is synchronous within the route handler; a slow or failing SMTP server will cause the API response to be slow or return 500. If this becomes an issue, the send should be moved to a fire-and-forget or background queue.
- `nodemailer` is added as a server-side runtime dependency; it is not bundled into any client-side chunk.

### Follow-Ups / Known Gaps
- No e2e or unit tests for the inquiry form or mailer — test harness for `apps/web` is Playwright (smoke only); mailer unit tests would require mocking `nodemailer`.
- File attachments (TOR documents) uploaded via the inquiry form are currently received by the route handler but not persisted or forwarded. They are counted in the ops email (`fileCount`) but the actual bytes are dropped. A follow-up should either attach them to the ops email or upload them to object storage.
- `OPS_EMAIL` is not validated at startup; a missing value only produces a `console.warn` at request time.

---

## Session 2 — Self-Service Registration (2026-04-06, continued)

### Goal
Add `POST /v1/auth/register` so Free Trial users can sign up without admin provisioning, and wire a `/signup` page on the frontend.

### Backend Changes

#### `packages/db/src/egp_db/repositories/auth_repo.py`
- **Bug fix**: restored `create_session`, `revoke_session`, `revoke_all_sessions_for_user`, and `get_session_user` methods that had been accidentally dropped during a prior edit session (the file was corrupted — `get_user_by_id` body contained code from `create_account_action_token`). Restored from `git show ef6a50c`.
- Added `find_login_user_by_email(email)` — cross-tenant email lookup used by the registration duplicate-guard.

#### `packages/db/src/egp_db/repositories/admin_repo.py`
- Added `create_tenant(name, slug, plan_code, is_active) -> TenantRecord`.
- Added `get_tenant_by_slug(slug) -> TenantRecord | None`.

#### `apps/api/src/egp_api/services/auth_service.py`
- Added `register(company_name, email, password) -> LoginResult` method.
- Added module-level `_slugify(text) -> str` helper (strips non-ASCII, lowercases, hyphenates).
- Added optional `notification_repository` and `billing_service` constructor params.

#### `apps/api/src/egp_api/routes/auth.py`
- Added `RegisterRequest` Pydantic model (`company_name`, `email`, `password` with `min_length=8`).
- Added `POST /v1/auth/register` endpoint — creates tenant + owner user + free trial subscription + session cookie; returns `CurrentSessionResponse`.

#### `apps/api/src/egp_api/main.py`
- Added `/v1/auth/register` to the public-path exemption set in `auth_middleware`.
- Wired `notification_repository` and `billing_service` into `AuthService` constructor.

### Tests

#### `tests/phase4/test_registration.py` (new)
Seven tests, all passing:
- `test_register_creates_tenant_user_and_session` — happy path
- `test_register_slug_derived_from_company_name`
- `test_register_can_then_login` — end-to-end register → logout → login
- `test_register_duplicate_email_rejected` — 409
- `test_register_missing_fields_returns_422`
- `test_register_short_password_rejected` — 422
- `test_register_slug_collision_deduplicates`

All 20 tests in `tests/phase4/test_registration.py` + `tests/phase4/test_auth_api.py` pass.

### Frontend Changes

#### `apps/web/src/lib/api.ts`
- Added `RegisterInput` type and `register()` async function (`POST /v1/auth/register`).

#### `apps/web/src/app/signup/page.tsx` (new)
- Client Component signup form: company name, email, password fields.
- On success, seeds React Query `["me"]` cache and redirects to `/`.
- Matches login page layout (indigo-violet gradient panel left, white form right).
- "มีบัญชีอยู่แล้ว? เข้าสู่ระบบ" link at bottom.

#### `apps/web/src/app/login/page.tsx`
- Renamed "Tenant slug" label to "Workspace slug".
- Added "ยังไม่มีบัญชี? ทดลองใช้ฟรี 7 วัน → /signup" link below form.

#### `apps/web/src/app/page.tsx`
- Changed all "Free Trial" CTAs (navbar, hero, pricing card, bottom banner) from `/login` to `/signup`.
- Login / paid-plan CTAs retain `/login`.

#### `apps/web/src/app/sitemap.ts`
- Added `/signup` entry (priority 0.8).

### Quality Gates
- `ruff check` — all checks passed
- `pytest tests/phase4/` — 20/20 passed
- `npm run typecheck` — no errors
- `npm run build` — 21 routes build cleanly, `/signup` appears as static page

---

## Session 3 — Opn Billing Support (2026-04-06 18:46 +07)

### Goal
Add real Opn-backed payment support for PromptPay QR and card checkout, while preserving the existing billing lifecycle and webhook reconciliation flow.

### What Changed

#### `tests/phase3/test_payment_links.py`
- Used the existing RED tests added earlier in the session to drive the implementation.
- Covered Opn PromptPay request creation, Opn card checkout creation, and Opn webhook settlement for both methods.

#### `packages/shared-types/src/egp_shared_types/enums.py`
- Added `BillingPaymentMethod.CARD`.
- Added `BillingPaymentProvider.OPN`.

#### `packages/db/src/migrations/005_payment_requests.sql`
- Updated fresh-bootstrap constraints so payment methods allow `card` and providers allow `opn`.

#### `packages/db/src/migrations/014_opn_payment_provider.sql` (new)
- Added a forward migration for existing databases to expand billing payment/request/provider-event constraints for `card` and `opn`.

#### `packages/db/src/egp_db/repositories/billing_repo.py`
- Extended `BillingPaymentRequestRecord` with `tenant_id` so provider-webhook resolution can safely route back into tenant-scoped reconciliation.
- Added lookup by `(provider, provider_reference)` for shared provider webhook handling.
- Kept all persistence tenant-scoped and reused existing payment request status/payment reconciliation flows.

#### `apps/api/src/egp_api/config.py`
- Added `get_opn_public_key()` and `get_opn_secret_key()` config helpers.

#### `apps/api/src/egp_api/services/payment_provider.py`
- Extended `ProviderPaymentRequest` with `provider` and `payment_method`.
- Extended `ParsedPaymentCallback` with `provider_reference`.
- Tightened `MockPromptPayProvider` validation so it only accepts mock PromptPay requests.
- Added `OpnProvider` with:
  - PromptPay source + charge creation
  - card checkout link creation
  - webhook verification by refetching the referenced charge/link from Opn before reconciliation
- Extended `build_payment_provider()` to construct `OpnProvider` when `EGP_PAYMENT_PROVIDER=opn` and a secret key is present.

#### `apps/api/src/egp_api/services/billing_service.py`
- `create_payment_request()` now accepts and forwards `payment_method` instead of assuming QR-only behavior.
- Added shared `_process_payment_callback()` logic so both the legacy callback route and provider-specific webhook route reuse the same reconciliation path.
- Settled payments now record using the original request’s `payment_method` instead of hardcoding PromptPay.
- Added `handle_provider_webhook()` that resolves billing payment requests by provider reference.

#### `apps/api/src/egp_api/routes/billing.py`
- Extended `CreateBillingPaymentRequestRequest` with `payment_method`.
- Added `POST /v1/billing/providers/opn/webhooks` for real Opn webhook ingestion without the custom shared-secret header.
- Kept the legacy mock callback route intact for existing tests and manual flows.

#### `apps/api/src/egp_api/main.py`
- Wired Opn config into `build_payment_provider()`.
- Added `/v1/billing/providers/opn/webhooks` to the auth bypass list so PSP callbacks can reach the route.

#### `apps/web/src/lib/api.ts`
- Extended `createBillingPaymentRequest()` payloads to include `payment_method`.

#### `apps/web/src/app/(app)/billing/page.tsx`
- Added a payment-method selector for creating either PromptPay QR or card checkout requests.
- Uses `provider="opn"` automatically for card checkout and keeps mock PromptPay for QR in the current UI.
- Updated the payment-request panel to render either QR details or a hosted card-checkout CTA, instead of assuming every request is QR-based.
- Generalized payment-event labels so non-QR flows read correctly.

### TDD Evidence
- RED was established earlier in-session using:
  - `./.venv/bin/python -m pytest tests/phase3/test_payment_links.py -q`
- Key failing reasons before implementation:
  - billing schema/enums rejected `provider="opn"`
  - billing schema/enums rejected `payment_method="card"`
  - Opn webhook route did not exist
- GREEN after implementation:
  - `./.venv/bin/python -m pytest tests/phase3/test_payment_links.py -q`
  - 11 passed

### Tests Run
- `./.venv/bin/python -m pytest tests/phase3/test_payment_links.py -q` → 11 passed
- `./.venv/bin/python -m pytest tests/phase3/test_payment_links.py tests/phase3/test_invoice_lifecycle.py -q` → 14 passed
- `./.venv/bin/ruff check apps/api packages` → all checks passed
- `cd apps/web && npm run typecheck` → passed

### Wiring Verification

| Component | Wiring Verified? | How Verified |
|---|---|---|
| `BillingPaymentProvider.OPN` / `BillingPaymentMethod.CARD` | YES | Shared enums updated and DB constraints updated in `005_payment_requests.sql` + `014_opn_payment_provider.sql` |
| `OpnProvider` runtime construction | YES | `apps/api/src/egp_api/main.py` passes `get_opn_public_key()` / `get_opn_secret_key()` into `build_payment_provider()` |
| Opn webhook route | YES | `apps/api/src/egp_api/routes/billing.py` registers `POST /v1/billing/providers/opn/webhooks` and `main.py` includes `billing_router` |
| Opn webhook auth bypass | YES | `apps/api/src/egp_api/main.py` explicitly exempts `/v1/billing/providers/opn/webhooks` in auth middleware |
| Provider-reference lookup | YES | `BillingService.handle_provider_webhook()` calls `repository.get_payment_request_by_provider_reference()` |
| Frontend payment-method submission | YES | `apps/web/src/lib/api.ts` sends `payment_method`; billing page now passes selected method into `createBillingPaymentRequest()` |
| Frontend card rendering | YES | `apps/web/src/app/(app)/billing/page.tsx` branches on `latestPaymentRequest.payment_method` and renders hosted checkout CTA for `card` |

### Behavior Changes and Risks
- Billing payment requests now support `opn` and `card` at the API/model level.
- The billing UI can initiate either PromptPay QR or hosted card checkout.
- Live Opn webhook handling now resolves by provider reference and does not depend on the repo’s custom shared-secret header.
- Risk: the live Opn API payload shape was implemented from researched docs and common field names, but only stubbed/test-double behavior was exercised in-repo during this session. A real sandbox verification pass is still needed with actual Opn credentials and webhook deliveries.

### Follow-Ups / Known Gaps
- The current frontend uses `mock_promptpay` for QR creation and `opn` for cards. If the product now wants real Opn PromptPay from the UI by default, `apps/web/src/app/(app)/billing/page.tsx` should switch its QR provider selection from `mock_promptpay` to `opn` once sandbox credentials are wired in the target environment.
- `OpnProvider` is runtime-ready but not covered by a live integration test against Opn sandbox in this repo.
- Frontend build/lint were not rerun in this session because the touched frontend surface typechecked cleanly and the behavior change was localized.

## Review (2026-04-06 18:51 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: `working-tree`
- Commands Run: `git status --short --branch`; `git log --oneline -8`; targeted `git diff` on billing/auth files; `./.venv/bin/python -m pytest tests/phase3/test_payment_links.py tests/phase3/test_invoice_lifecycle.py tests/phase4/test_registration.py -q`; `./.venv/bin/ruff check apps/api packages tests/phase3/test_payment_links.py tests/phase4/test_registration.py`; `cd apps/web && npm run typecheck`

### Findings
HIGH
- `apps/api/src/egp_api/services/payment_provider.py`: card checkout webhook reconciliation originally keyed off the `charge` id while the billing request stored the `link` id, which would cause real Opn card settlements to miss the intended payment request. Fixed by resolving `charge.link` back to the stored link reference and adding regression coverage in `tests/phase3/test_payment_links.py`.

MEDIUM
- `apps/web/src/app/(app)/billing/page.tsx`: the billing UI originally still created QR requests with `mock_promptpay`, which contradicted the requested production scope of real Opn PromptPay plus cards. Fixed by routing both QR and card creation through `provider="opn"`.
- `apps/api/src/egp_api/routes/auth.py` and `apps/web/src/app/signup/page.tsx`: registration validation originally allowed 8-character passwords while `hash_password()` rejects anything under 12, producing a 400 after client-side acceptance. Fixed by aligning route/UI validation to 12 characters.

LOW
- No additional findings after the fixes above.

### Open Questions / Assumptions
- Assumed the current PR should include both the earlier self-service auth/landing changes and the Opn billing work, because they are present in the same reviewed working tree and were already validated together in session.
- Assumed live Opn sandbox verification will happen after merge because no test credentials were available in-repo.

### Recommended Tests / Validation
- Run one live Opn sandbox verification for:
  - PromptPay QR creation and settlement webhook
  - card checkout completion and webhook delivery
- Run `cd apps/web && npm run build` before release deployment, since this review used typecheck only for the touched frontend surface.

### Rollout Notes
- `EGP_PAYMENT_PROVIDER=opn` requires `EGP_OPN_SECRET_KEY` and likely `EGP_OPN_PUBLIC_KEY` in the target environment.
- Existing Postgres environments need migration `014_opn_payment_provider.sql` applied before using Opn/card values.

## Session 4 — Dashboard Runtime And Chart Hardening (2026-04-06 20:21 +07)

### Goal
Fix the local dashboard failure that surfaced as a browser CORS error, remove the Recharts `width(-1) height(-1)` warning, and document the correct local API reload/CORS startup command.

### What Changed

#### `packages/db/src/egp_db/repositories/project_repo.py`
- Fixed dashboard project-summary queries to compare SQL `date(...)` expressions against Python `date` values instead of ISO strings.
- This removes the Postgres runtime error on `GET /v1/dashboard/summary` for authenticated tenants.

#### `apps/web/src/components/ui/dashboard-charts.tsx`
- Added `min-w-0` to both chart cards and explicit `w-full min-w-0` on the chart wrappers so Recharts `ResponsiveContainer` can measure the grid cells reliably.
- This removes the `width(-1) and height(-1)` warning from the dashboard charts.

#### `docs/MANUAL_WEB_APP_TESTING.md`
- Updated the local API startup command to include both `http://localhost:3000` and `http://localhost:3002` in `EGP_WEB_ALLOWED_ORIGINS`.
- Updated the local API startup command to use `--reload-dir apps/api/src --reload-dir packages` so package-level repository changes are picked up during local development.

### TDD Evidence
- Existing dashboard regression coverage already exercised the summary path:
  - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py -q`
- Live RED reproduction before the repo fix:
  - authenticated `GET http://127.0.0.1:8000/v1/dashboard/summary` returned `500 Internal Server Error`
  - traceback showed `operator does not exist: date = character varying` in `packages/db/src/egp_db/repositories/project_repo.py`
- GREEN after the fix:
  - `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py -q`
  - authenticated live `GET http://127.0.0.1:8000/v1/dashboard/summary` returned `200 OK` with `Access-Control-Allow-Origin: http://localhost:3002`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py -q` → 2 passed
- `./.venv/bin/ruff check packages/db/src/egp_db/repositories/project_repo.py` → passed
- `cd apps/web && npm run typecheck` → passed
- `cd apps/web && npm run build` → passed

### Wiring Verification

| Component | Wiring Verified? | How Verified |
|---|---|---|
| Dashboard repository fix | YES | `tests/phase2/test_dashboard_api.py` passed and live authenticated `GET /v1/dashboard/summary` returned `200 OK` |
| Dashboard browser CORS path | YES | live response included `Access-Control-Allow-Origin: http://localhost:3002` after restarting API with the documented env |
| Dashboard chart containers | YES | `apps/web/src/app/(app)/dashboard/page.tsx` renders `DailyDiscoveryChart` and `ProjectStateChart`; wrappers in `dashboard-charts.tsx` now provide explicit measurable width |
| Local dev startup docs | YES | `docs/MANUAL_WEB_APP_TESTING.md` now matches the working API launch command used to verify the fix |

### Behavior Changes and Risks
- Dashboard summary now works against the local Postgres-backed API path instead of failing with a backend `500`.
- Dashboard charts now have safer width constraints inside the dashboard grid.
- Risk: the chart warning fix was validated by code inspection/build and the corrected live dashboard fetch path, but not by an automated browser assertion that explicitly checks the console output.

### Follow-Ups / Known Gaps
- The Recharts warning path does not currently have browser-console test coverage.
- The running local API must continue using a startup command that watches both `apps/api/src` and `packages`; otherwise package-level fixes will not hot reload.

## Review (2026-04-06 20:21 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: `working-tree`
- Commands Run: `git status --short --branch`; targeted `git diff` on `project_repo.py`, `dashboard-charts.tsx`, and `docs/MANUAL_WEB_APP_TESTING.md`; `./.venv/bin/python -m pytest tests/phase2/test_dashboard_api.py -q`; `./.venv/bin/ruff check packages/db/src/egp_db/repositories/project_repo.py`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run build`

### Findings
LOW
- No findings.

### Open Questions / Assumptions
- Assumed this patch should stay narrowly scoped to the dashboard runtime fix, chart sizing warning, and local dev documentation.

### Recommended Tests / Validation
- Run one manual browser refresh on `/dashboard` against the current local API process to confirm the console warning is gone in the actual rendered layout.

### Rollout Notes
- Local developers should use the updated API startup command from `docs/MANUAL_WEB_APP_TESTING.md` so both `localhost:3002` CORS and package reload behavior stay correct.
