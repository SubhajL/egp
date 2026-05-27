# Stripe Deployment Runbook

Operator runbook for switching the e-GP Intelligence Platform's payment
processor from OPN to Stripe. Pairs with the Stripe provider class
(PR-F) and the webhook route (PR-G).

> **Status:** shipped in PR-G of the launch-readiness initiative.
> Stripe is offered as an alternative to OPN, configurable via
> `EGP_PAYMENT_PROVIDER=stripe`. Both providers can coexist in the
> codebase; only one is active per deployment.

---

## 1. When to use Stripe vs OPN

| Dimension | OPN (Omise) | Stripe Thailand | Stripe Atlas (US LLC) |
|---|---|---|---|
| Account requirements | บริษัท จำกัด required (no individual accounts for SaaS recurring) | Both Thai company AND individual (บุคคลธรรมดา) accepted as of 2026 | US LLC; ~$500 setup + $100/yr maintenance |
| Setup time | 5–10 business days KYC | ~5 business days verification | ~3 weeks (incorporation + Stripe approval) |
| PromptPay support | Native, 1.5% + ฿1.50 | Native (Thailand only), 0.95% + ฿3 | **NOT available** — Atlas accounts are USD-denominated, card-only for THB |
| Card support | Native | Native | Native |
| Settlement | T+1 / T+2 | T+2 / T+7 | T+7+ (international wire) |
| Best for | Thai SaaS with company entity; PromptPay-heavy customers | Thai operators wanting lower PromptPay fees; or individuals who can't get OPN | Thai individuals who can't form a company AND want Stripe ecosystem (card-only) |

**Recommended:** stay with OPN if the company-registration timeline is
manageable. Switch to Stripe Thailand only if you need lower PromptPay
fees or your customers strongly prefer Stripe Checkout UX. Stripe
Atlas is the **last-resort** path — losing PromptPay coverage typically
costs more in conversion than the Stripe ecosystem benefits.

---

## 2. One-time account setup

### Path A: Stripe Thailand (recommended for Thai operators)

1. Sign up at <https://dashboard.stripe.com/register> — pick **Thailand**
   as your country.
2. Choose **Individual (บุคคลธรรมดา)** or **Company** based on your
   situation.
3. Provide:
   - Thai national ID (for individuals) OR DBD certificate (for companies)
   - Thai bank account for settlement
   - Business description (e-GP procurement intelligence; tag as "SaaS / data analytics")
   - Estimated monthly volume
4. Wait for KYC approval (typically 1–5 business days).
5. Once approved, you can take live payments. Verify in **Dashboard →
   Home → Activate live payments**.

### Path B: Stripe Atlas (US LLC; card-only)

1. Apply at <https://stripe.com/atlas> — ~$500 incorporation fee.
2. Atlas handles: Delaware LLC formation, EIN, banking, Stripe Account.
3. After ~3 weeks, you have a US business entity that can accept Stripe
   payments globally (but NOT PromptPay — that's Stripe Thailand only).
4. Pay ~$100/yr maintenance (registered agent + state filings).

> **VAT/tax warning**: a US Atlas LLC selling to Thai customers triggers
> Thai withholding tax + US 1040-NR filings. Consult an accountant. Not
> recommended unless other paths are blocked.

---

## 3. Get your API keys

1. Dashboard → **Developers → API keys**.
2. Note two key pairs visible:
   - **Test mode** (`sk_test_*` / `pk_test_*`): use during integration
   - **Live mode** (`sk_live_*` / `pk_live_*`): use for production
3. Click **Reveal** on the test-mode secret key, copy it.
4. Also copy the test-mode publishable key (used by the frontend).

> **Security:** keys with prefix `sk_*` are server-only. Never put them
> in `NEXT_PUBLIC_*` env vars, browser code, or GitHub. Rotation:
> see [`docs/SECRET_ROTATION.md`](./SECRET_ROTATION.md) §5b.

---

## 4. Configure the webhook endpoint

Stripe needs to know where to deliver payment events.

1. Dashboard → **Developers → Webhooks → Add endpoint**.
2. **Endpoint URL**: `https://api.<your-domain>/v1/billing/providers/stripe/webhooks`
3. **Events to send**: select **exactly** these 5 (others will be
   rejected with HTTP 400):
   - `payment_intent.succeeded`
   - `payment_intent.payment_failed`
   - `payment_intent.canceled`
   - `checkout.session.completed`
   - `checkout.session.expired`
4. Click **Add endpoint**.
5. On the new endpoint page, click **Reveal** under **Signing secret**.
   The secret starts with `whsec_*` — copy it.

> **CRITICAL GOTCHA**: the `whsec_*` shown here is your **Dashboard
> endpoint signing secret**. It is NOT the same as the `whsec_*` that
> the **Stripe CLI** prints when you run `stripe listen`. The CLI
> secret is for local forwarding only and will NOT verify Dashboard-
> originated webhook deliveries. Always use the value from the
> Dashboard endpoint page in `EGP_STRIPE_WEBHOOK_SECRET`.

---

## 5. Wire env vars

In `/etc/egp/egp.env` (or your Compose env file), set:

```bash
EGP_PAYMENT_PROVIDER=stripe
EGP_STRIPE_SECRET_KEY=sk_test_<your-test-secret>   # or sk_live_*
EGP_STRIPE_WEBHOOK_SECRET=whsec_<your-endpoint-signing-secret>
EGP_STRIPE_PUBLISHABLE_KEY=pk_test_<your-test-publishable>  # optional; for frontend
```

Restart the API service:

```bash
sudo systemctl restart egp-api.service
```

Verify in journalctl that the service came up clean:

```bash
sudo journalctl -u egp-api.service -n 50 --no-pager
```

---

## 6. Test-mode validation

Before flipping the live switch, validate the integration end-to-end
in test mode.

### 6.1 Send a synthetic test webhook from Dashboard

1. Dashboard → **Developers → Webhooks → [your endpoint] → Send test webhook**.
2. Pick event type: `payment_intent.succeeded`.
3. Click **Send test webhook**.
4. Watch the API:
   ```bash
   sudo journalctl -u egp-api.service -f
   ```
5. Expected: a 404 response (no matching payment request in your DB),
   AND the signature verification step succeeded — that's the right
   "test-mode handshake works" signal. If you see 400 with "signature"
   in the message, your `EGP_STRIPE_WEBHOOK_SECRET` is wrong (likely
   the CLI secret, not the Dashboard secret — see §4).

### 6.2 Test PromptPay end-to-end (Thai accounts only)

1. Create a test billing record + payment request via the API:
   ```bash
   curl -X POST https://api.example.com/v1/billing/records \
       -H "Authorization: Bearer $TOKEN" \
       -d '{...}'
   ```
2. The API returns a `payment_url` and `qr_payload`.
3. Open the QR in Stripe's test PromptPay simulator:
   <https://dashboard.stripe.com/test/payments/promptpay-tester>.
4. Mark the test payment as paid.
5. Stripe fires `payment_intent.succeeded` → your webhook → billing
   record transitions to `paid`.

### 6.3 Test Card end-to-end

1. Create a card payment request via the API.
2. Open the returned `payment_url` (Stripe Payment Link).
3. Use Stripe's test card: `4242 4242 4242 4242`, any future expiry,
   any CVV.
4. Stripe fires `checkout.session.completed` → webhook → billing record
   transitions to `paid`.

### 6.4 Raw-body smoke (advanced)

If you suspect Caddy or another reverse proxy is mutating the body:

```bash
echo '{"id":"evt_test","type":"payment_intent.succeeded","created":1,"data":{"object":{"id":"pi_test","amount":2500,"currency":"thb","status":"succeeded","created":1}}}' > /tmp/event.json

# Compute signature locally (NEVER do this in production scripts;
# this is only for smoke-testing the proxy chain)
TS=$(date +%s)
PAYLOAD=$(cat /tmp/event.json)
SIG=$(printf "%s.%s" "$TS" "$PAYLOAD" | openssl dgst -sha256 -hmac "$EGP_STRIPE_WEBHOOK_SECRET" -hex | cut -d' ' -f2)

# IMPORTANT: --data-binary preserves the exact bytes; --data would
# strip trailing newlines and break the signature.
curl -X POST https://api.example.com/v1/billing/providers/stripe/webhooks \
    --data-binary @/tmp/event.json \
    -H "Content-Type: application/json" \
    -H "Stripe-Signature: t=${TS},v1=${SIG}"

# Expected: 404 (no matching payment request) with signature verified.
# A 400 with "signature" → your proxy is mutating the body.
```

---

## 7. Test-mode → live-mode cutover

When you're ready to take real money:

1. **In Stripe Dashboard**, switch the toggle from **Test mode** to
   **Live mode** (top-left).
2. Go to **Developers → API keys**, copy the **live** `sk_live_*` key.
3. Go to **Developers → Webhooks**, add a new endpoint (same URL),
   select the same 5 events, copy the new **live** `whsec_*` signing
   secret.
4. Edit `/etc/egp/egp.env`:
   ```bash
   EGP_STRIPE_SECRET_KEY=sk_live_...    # was sk_test_*
   EGP_STRIPE_WEBHOOK_SECRET=whsec_...  # was the test-mode whsec
   ```
5. Restart the API: `sudo systemctl restart egp-api.service`
6. Run one **real** test transaction with a small amount (e.g. ฿10
   minimum for PromptPay) to verify live-mode end-to-end.
7. (Optional but recommended) **Disable** the test-mode endpoint in
   Stripe Dashboard to prevent confusion. The test-mode keys remain
   valid for sandbox use; they just won't deliver to your prod endpoint.

---

## 8. Common gotchas

| Issue | Cause | Fix |
|---|---|---|
| Webhook returns 400 "signature" | Wrong `whsec_*` (using CLI secret instead of Dashboard) | Copy `whsec_*` from Dashboard endpoint page, not from `stripe listen` |
| Webhook returns 404 | Payment request not found in DB for the `provider_reference` | Verify `EGP_PAYMENT_PROVIDER=stripe` AND a payment request was created via the API before the webhook fired |
| PromptPay create fails on Stripe Atlas | Atlas accounts are USD-only; PromptPay requires Stripe Thailand | Use card payments only on Atlas accounts |
| `next_action.promptpay_display_qr_code` missing | Stripe API version mismatch OR `confirm=true` not set | The provider class sets both (PR-F); upgrade if you see this with up-to-date code |
| Payment Link paid multiple times | Pre-PR-F code allowed reuse | PR-F shipped `restrictions[completed_sessions][limit]=1`; verify your Stripe API version is `2026-04-22.dahlia` or later |
| Webhook signature works in test but fails in live | Different signing secrets per endpoint | Each endpoint has its own `whsec_*`; the test-mode and live-mode endpoints are separate |
| Stripe-Version header mismatch warnings | Stripe deprecated the pinned version | Bump `StripeProvider._api_version` (see `payment_provider.py` constant) and test before re-deploying |

---

## 9. Rolling back to OPN

If Stripe doesn't work out (KYC rejection, fee structure changes, etc.),
rollback is one env-file edit:

```bash
sudo nano /etc/egp/egp.env
# Change EGP_PAYMENT_PROVIDER=stripe → EGP_PAYMENT_PROVIDER=opn

sudo systemctl restart egp-api.service
```

The Stripe webhook endpoint stays mounted but inactive (no Stripe
requests will arrive). Optionally remove the Stripe webhook endpoint in
the Stripe Dashboard to avoid stale delivery attempts (which would
return 404 from your API and pile up retries).

### 9.1 Coexistence note

Both providers can be in the codebase simultaneously, but only one is
active at a time (the value of `EGP_PAYMENT_PROVIDER`). To support
**both** in production (e.g., let customers choose), additional product
work is required (provider-selection UI, per-tenant config, separate
billing records). Out of scope for PR-G.

---

## 10. Reference: what the route does

The Stripe webhook handler at
`apps/api/src/egp_api/routes/billing.py:handle_stripe_provider_webhook`
mirrors the OPN handler exactly:

1. Reads the **raw body bytes** (preserving exact whitespace — critical
   for HMAC).
2. Parses JSON (400 on malformed).
3. Calls `BillingService.handle_provider_webhook(provider=STRIPE, ...)`.
4. The service:
   - Calls `StripeProvider.parse_callback(payload, headers, raw_body)`
   - Verifies the `Stripe-Signature` header HMAC
   - Maps event type → `BillingPaymentRequestStatus`
   - Looks up the payment request by `provider_reference` (PaymentIntent
     id for promptpay; Payment Link id for card via `payment_link`
     field on the session)
   - Updates the record + writes an idempotency-keyed row to
     `billing_provider_events`
5. Returns `BillingRecordDetailResponse` (200), or `HTTPException` 400 /
   404 / 502 for various failure modes.

The endpoint **bypasses auth middleware** (added to allowlist in
`bootstrap/middleware.py`) because Stripe doesn't send Authorization
headers — signature verification IS the authentication.

---

## 11. Where to learn more

- Stripe API reference: <https://docs.stripe.com/api>
- Webhook signatures: <https://docs.stripe.com/webhooks/signatures>
- PromptPay (Thailand): <https://docs.stripe.com/payments/promptpay>
- Payment Links: <https://docs.stripe.com/payment-links>
- Stripe Thailand pricing: <https://stripe.com/en-th/pricing>
- Stripe Atlas: <https://stripe.com/atlas>
- Secret rotation: [`docs/SECRET_ROTATION.md`](./SECRET_ROTATION.md) §5b
- Lightsail deployment: [`docs/LIGHTSAIL_LOW_COST_LAUNCH.md`](./LIGHTSAIL_LOW_COST_LAUNCH.md)
