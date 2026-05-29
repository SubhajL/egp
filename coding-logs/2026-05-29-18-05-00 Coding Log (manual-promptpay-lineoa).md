# Coding Log — Manual PromptPay + LINE OA Payment Flow

**Date:** 2026-05-29
**Branch:** `feat/payment-lineoa`
**Goal:** Implement the ฿0-fee bootstrap payment path — personal PromptPay QR +
manual LINE slip verification — reusing the existing billing stack.

## What shipped

### Part A — Personal PromptPay QR provider
- `BillingPaymentProvider.PROMPTPAY_MANUAL` enum value.
- `PromptpayManualProvider` (builds a real EMVCo QR locally from
  `EGP_PROMPTPAY_PROXY_ID`; `parse_callback` fails closed — no provider webhook).
- Migration `024_promptpay_manual_provider.sql` (CHECK constraints).
- Tests: `tests/phase3/test_promptpay_manual_provider.py`.

### Part B — LINE slip tables + repositories
- Migration `025_line_payment_slips.sql`: `payment_slips` (nullable tenant_id
  until matched), `line_payment_contexts`, `line_admin_subscribers`.
- `line_payment_schema.py`, `line_payment_models.py`, `line_payment_repo.py`
  (`LinePaymentRepository` + `create_line_payment_repository`).
- `BillingInvoiceMixin.find_billing_records_by_number` (auto-match only on a
  unique hit; `record_number` is unique per tenant, not globally).
- Tests: `tests/phase4/test_line_payment_repository.py`.

### Part C — LINE integration service + routes
- `line_integration.py` (signature verify, reference extraction, event parse,
  `HttpLineMessagingClient` over urllib).
- `line_slip_service.py` (`LineSlipService`: ingest → store → match → notify;
  verify/reject admin ops).
- `BillingService.verify_manual_payment` (records a reconciled `promptpay_qr`
  payment → record PAID → subscription ACTIVE).
- `routes/line_integration.py`: `POST /v1/integrations/line/webhook`,
  `GET /v1/billing/slips`, slip verify/reject/image, `GET /v1/billing/payment-config`.
- Config getters `EGP_LINE_*` + `EGP_ADMIN_CONSOLE_BASE_URL`; bootstrap wiring
  (`managed_artifact_store` + `line_payment_repository` exposed on the bundle).
- Tests: `tests/phase3/test_line_integration_helpers.py`,
  `tests/phase4/test_line_webhook_api.py` (full flow incl. idempotency).

### Part D — Frontend
- `lib/line.ts` deep-link helpers (+ `tests/unit/line.test.ts`).
- `api.ts`: `fetchPaymentConfig`, slip list/verify/reject, image URL (hand-written
  types — run `npm run generate:api-types` to fold into generated schema).
- `hooks.ts`: `usePaymentConfig`, `usePaymentSlips`.
- Billing page: server-configured provider, prominent reference code, green
  "ส่งสลิปผ่าน LINE" button.
- Admin page: **สลิปการชำระเงิน** tab — slip preview + verify/reject.

### Part E — Ops/docs
- `scripts/deploy_line_richmenu.py` (idempotent; `build_rich_menu_spec` unit-tested).
- `deploy/.env.production.example`: LINE section + provider note (drift test green).
- `docs/LINE_MANUAL_PROMPTPAY.md` runbook; `docs/PROMPTPAY_LINEOA_PLAN.md` plan.

## Key decisions
- Reused `billing_records`/`billing_payment_requests` rather than new
  `payment_intents` tables (Codex + Claude agreed).
- `parse_callback` fails closed; settlement is an explicit admin action via the
  existing record+reconcile path → all subscription-activation logic reused.
- `line_payment_contexts` remembers the reference text so an image arriving in a
  separate webhook event can still be matched.

## Verification
- `ruff check apps/ packages/` clean; backend suites green (phase2+phase4 = 233,
  plus new provider/repo/webhook/helpers/richmenu/env-template tests).
- New tests stable across 3 consecutive runs.
- Frontend `tsc --noEmit` clean, `next lint` clean, vitest (line/api/hooks) green.

## QCHECK (Codex adversarial review) — all addressed
- CRITICAL: slip routes weren't tenant-scoped (a tenant admin could list/verify
  another tenant's slips). Fixed: `_authorize_slip` + tenant-filtered listing;
  non-operator admins confined to their own tenant's matched slips, unmatched
  inbox is operator/support-only. Regression test added.
- HIGH: `/v1/integrations/line/webhook` wasn't in the auth-bypass allowlist, so
  prod `EGP_AUTH_REQUIRED=true` would block LINE before the HMAC check. Added to
  the allowlist in `bootstrap/middleware.py` (signature check stays mandatory).
- HIGH: a slip could be verified with no stored image. `verify_slip` now requires
  `image_object_key` before settling.
- HIGH (mitigated): concurrent double-verify. Guarded by the verified/rejected
  status check plus `verify_manual_payment` failing closed once the record is
  PAID; residual race is acceptable for a human-driven admin action. Full
  row-lock/transactional claim noted as a future hardening.
- MEDIUM: dropped the `verified_by_user_id → users(id)` FK in migration 025 (the
  auth subject isn't guaranteed to be a users row; matches the SQLAlchemy schema).

## Follow-ups
- Regenerate OpenAPI types so the slip/payment-config endpoints land in the
  generated schema (`npm run generate:api-types`).
- Optional hardening: make slip verify fully transactional (conditional
  `UPDATE ... WHERE verification_status='matched' RETURNING` + payment idempotency key).
- Operator must create the LINE OA + set `EGP_LINE_*` secrets before go-live.
