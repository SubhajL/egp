# Manual PromptPay + LINE OA Payment Runbook

The ฿0-fee bootstrap payment path: a customer pays a **personal PromptPay QR**
and forwards the slip image via **LINE OA**; an operator verifies the slip in the
admin console, which activates the subscription. No registered acquirer is
required. Migrate to `opn`/`stripe` once a Thai company is registered.

## Architecture

```
User (billing page)                LINE OA                      API (FastAPI)
  Upgrade → QR + reference  ──►  add-friend deep link  ──►  POST /v1/integrations/line/webhook
  pays in banking app            sends slip image            ├─ verify X-Line-Signature
  taps "ส่งสลิปผ่าน LINE"          (+ reference text)           ├─ download image → artifact store
                                                              ├─ payment_slips row (idempotent)
                                                              ├─ match reference → billing_record
                                                              └─ push admin notification
Admin console → สลิปการชำระเงิน → Verify ──► BillingService.verify_manual_payment
                                              record promptpay_qr payment + reconcile
                                              → record PAID → subscription ACTIVE
```

- Provider: `PromptpayManualProvider` (no acquirer, no provider webhook; QR built
  locally from `EGP_PROMPTPAY_PROXY_ID` via the EMVCo helper).
- Reference code = the billing record's `record_number` (e.g. `INV-2026-0001`).
  Auto-matches only when exactly one record bears that number; otherwise the slip
  stays pending for manual admin selection.
- Tables: `payment_slips`, `line_payment_contexts`, `line_admin_subscribers`
  (migration `025`); provider value added in migration `024`.

## One-time setup

1. **Create the LINE OA** at https://www.linebiz.com/th/ and a Messaging API
   channel at https://developers.line.biz/console/ (needs a Thai phone + ID).
2. **Collect credentials** from the channel: *Channel secret* and a long-lived
   *Channel access token*.
3. **Find your admin LINE userId** (send a message to the OA and read the
   webhook `source.userId`, or use the LINE console).
4. **Set environment variables** (see `deploy/.env.production.example`):
   ```
   EGP_PAYMENT_PROVIDER=promptpay_manual
   EGP_PROMPTPAY_PROXY_ID=0812345678          # your personal PromptPay phone/ID
   EGP_LINE_CHANNEL_SECRET=...
   EGP_LINE_CHANNEL_ACCESS_TOKEN=...
   EGP_LINE_ADMIN_USER_IDS=Uxxxxxxxx           # comma-separated
   EGP_LINE_ADD_URL=https://line.me/R/ti/p/@your-oa-id
   EGP_ADMIN_CONSOLE_BASE_URL=https://app.egptracker.com
   ```
   Frontend (Vercel): no extra `NEXT_PUBLIC_*` needed — the billing page reads
   the provider + LINE link from `GET /v1/billing/payment-config`.
5. **Point the LINE webhook** to `https://api.egptracker.com/v1/integrations/line/webhook`
   in the channel settings, and enable "Use webhook".
6. **Deploy the rich menu** (idempotent):
   ```
   EGP_LINE_CHANNEL_ACCESS_TOKEN=... ./.venv/bin/python scripts/deploy_line_richmenu.py \
     --egp-billing-url https://app.egptracker.com/billing \
     --trading-url https://app.egptracker.com/billing \
     --image artifacts/line_richmenu.png   # or omit + pass --font to auto-render
   ```

## Daily operation

1. Customer upgrades → sees QR + reference + a green **ส่งสลิปผ่าน LINE** button.
2. Customer pays, taps the button (LINE opens with the reference pre-filled),
   and sends the slip image.
3. You receive a LINE push: *"💰 สลิปการชำระเงินใหม่…"* with the reference + a link.
4. Admin console → **สลิปการชำระเงิน** tab → review the slip image against the
   amount → **ยืนยันและเปิดใช้งาน** (activates the subscription) or **ปฏิเสธ**.
5. The customer receives an automatic LINE confirmation.

## Notes & limits

- **No webhook reconciliation** — Thai banks don't expose merchant payment events
  without an acquirer; verification is human. Promise an activation SLA in the OA.
- **Refunds** are manual (bank transfer back + admin record adjustment).
- Slips with no matching reference stay `pending`; ask the customer for the
  reference, or match manually once the reference text arrives.
- Webhook requests with an invalid `X-Line-Signature` are rejected (HTTP 400).
