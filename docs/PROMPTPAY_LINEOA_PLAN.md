# Manual PromptPay + LINE OA Payment Flow — Implementation Plan

**Branch:** `feat/payment-lineoa`
**Author:** Claude (synthesized from Claude Code + Codex analysis, grounded in the existing billing code)
**Date:** 2026-05-29

## Why this shape

The operator cannot onboard Stripe/OPN/2C2P without a Thai company registration.
The bootstrap pattern is **personal PromptPay QR + manual slip verification via LINE OA**
(฿0 fees, human-in-the-loop). The codebase already has a mature billing stack
(`PaymentProvider` protocol, `billing_*` tables, billing page with QR + polling),
so we **reuse it** rather than build parallel `payment_intents` tables.

### Key decisions

1. **Reference code = existing `billing_records.record_number`** (e.g. `INV-2026-0001`).
   No new column. It is already the QR reference and is shown in the UI.
   Caveat: `record_number` is unique per `(tenant_id, record_number)`, not globally —
   slip→record matching only auto-matches when **exactly one** record bears the code,
   otherwise the slip stays `pending` for manual admin selection.
2. **Forwarding target = LINE OA** (required to receive slip webhooks). Personal LINE
   id is kept only as a display/contact fallback.
3. **Activation is always manual** — admin verifies a slip; no auto-activation from OCR.
4. **Verify reuses the existing settle path** — verifying a slip settles the linked
   `billing_payment_request`, which records a payment + reconciles + activates the
   subscription via `BillingService` (all existing logic).

## Components

### Part A — Personal PromptPay QR provider (backend)
- `BillingPaymentProvider.PROMPTPAY_MANUAL = "promptpay_manual"` (shared-types enum).
- Migration `024_promptpay_manual_provider.sql`: extend CHECK constraints on
  `billing_payment_requests` + `billing_provider_events` to allow `promptpay_manual`.
- `PromptpayManualProvider` in `payment_provider.py` (reuses `promptpay.build_promptpay_payload`);
  wired into `build_payment_provider`. `parse_callback` accepts an admin-synthesized
  settled payload (used by the verify path; no external webhook).

### Part B — LINE slip tables + repositories
- Migration `025_line_payment_slips.sql`:
  - `payment_slips` (nullable tenant_id/billing_record_id/payment_request_id until matched,
    `line_user_id`, `line_message_id` UNIQUE for idempotency, `image_object_key`,
    `reference_code_match`, `verification_status` ∈ {pending,matched,verified,rejected},
    `verified_by_user_id`, `verified_at`, `verification_notes`, timestamps).
  - `line_admin_subscribers` (`line_user_id` UNIQUE, nullable `tenant_id`, timestamps).
- Repos: `payment_slips.py`, `line_admin_subscribers.py`; `find_billing_records_by_number`
  helper on the billing repo.

### Part C — LINE integration service + routes
- `services/line_integration.py`: `verify_line_signature` (HMAC-SHA256 base64),
  `extract_reference_code` (regex `INV-\d{4}-\d+`), `HttpLineMessagingClient`
  (stdlib urllib; content + push endpoints), event parsing.
- `services/line_slip_service.py`: on image event → download → store (ArtifactStore)
  → idempotent slip row → match reference → push admin notification; `verify_slip` /
  `reject_slip` orchestration.
- Routes `routes/line_integration.py`: `POST /v1/integrations/line/webhook` (public,
  signature-verified) + admin slip endpoints (`GET /v1/billing/slips`,
  `POST /v1/billing/slips/{id}/verify`, `/reject`, `GET /v1/billing/slips/{id}/image`).
  Register in `bootstrap/middleware.py`; instantiate service in `bootstrap/services.py`.
- Config getters: `EGP_LINE_CHANNEL_SECRET`, `EGP_LINE_CHANNEL_ACCESS_TOKEN`,
  `EGP_LINE_ADMIN_USER_IDS`, `EGP_ADMIN_CONSOLE_BASE_URL`.
- `GET /v1/billing/payment-config` → `{ provider, line_add_url }` so the frontend knows
  which provider to request and the LINE deep link (avoids duplicating server config).

### Part D — Frontend (Next.js)
- `api.ts`: payment-config fetch, slip list/verify/reject, image URL; send the
  server-configured provider when creating a payment request.
- Billing page: prominent reference code + "ส่งสลิปผ่าน LINE" deep-link button.
- Admin page: "สลิปการชำระเงิน" tab — pending slips with image preview + Verify/Reject.

### Part E — Rich menu deploy script
- `scripts/deploy_line_richmenu.py` (idempotent: list→delete→create→upload→set-default),
  pure helpers unit-tested; image via Pillow + Thai font or a provided PNG path.

## Quality gates
`ruff check apps/ packages/ && pytest <new tests> && (cd apps/web && npx tsc --noEmit && npx eslint src/)`

## Implementation order (each step shippable)
1. Part A (enum + migration 024 + provider + tests) ← core "personal QR".
2. Part B (migration 025 + repos + tests).
3. Part C (LINE service + webhook + admin verify routes + tests).
4. Part D (frontend QR/LINE button + admin slips UI).
5. Part E (rich menu script).
6. Env template + docs + coding log.
