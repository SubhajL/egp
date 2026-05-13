# Cloudflare Quick Tunnel for Local OPN Webhook Testing

This guide is for **local testing and debugging** when you want OPN to call your
**locally running FastAPI server on a local port** through a temporary public HTTPS URL.

It complements:

- [`docs/MANUAL_WEB_APP_TESTING.md`](MANUAL_WEB_APP_TESTING.md) for normal local product testing
- [`docs/AWS_LAMBDA_OPN_WEBHOOK.md`](AWS_LAMBDA_OPN_WEBHOOK.md) for the AWS Lambda production-style webhook ingress option
- [`docs/LIGHTSAIL_LOW_COST_LAUNCH.md`](LIGHTSAIL_LOW_COST_LAUNCH.md) for the cheap single-host production launch path

---

## When to use this

Use this when:

- your API is running locally on a port such as `8000` or `8010`
- you want to test **real OPN webhook callbacks** without deploying anything to AWS yet
- you need a valid public HTTPS URL for the OPN **test** dashboard

Do **not** use this as the production webhook architecture.

---

## What it does

- runs `cloudflared tunnel --url http://127.0.0.1:<port>`
- gives you a temporary `https://...trycloudflare.com` URL
- prints the exact eGP webhook endpoint:

```text
https://<random>.trycloudflare.com/v1/billing/providers/opn/webhooks
```

Helper script:

- [`scripts/cloudflare_opn_webhook_tunnel.py`](../scripts/cloudflare_opn_webhook_tunnel.py)

---

## Prerequisites

### 1. Install `cloudflared`

On macOS:

```bash
brew install cloudflared
```

Verify:

```bash
cloudflared --version
```

### 2. Start the local API on a local port

Examples:

#### API only

```bash
cd apps/api
../../.venv/bin/uvicorn src.main:app --reload --port 8000
```

#### Web + API dev flow

```bash
cd apps/web
npm run dev
```

That flow usually starts the API on port `8010`.

### 3. Confirm health locally

```bash
curl http://127.0.0.1:8000/health
```

or

```bash
curl http://127.0.0.1:8010/health
```

---

## Start the tunnel

### If API is on port 8010

```bash
./.venv/bin/python scripts/cloudflare_opn_webhook_tunnel.py --port 8010
```

### If API is on port 8000

```bash
./.venv/bin/python scripts/cloudflare_opn_webhook_tunnel.py --port 8000
```

The helper intentionally ignores `~/.cloudflared/config.yml` by running Cloudflare with an empty config.
This prevents existing named-tunnel ingress rules from hijacking your quick tunnel target.

### Example output

```text
=== OPN local webhook test endpoint ===
Local API target: http://127.0.0.1:8010
Tunnel URL:       https://gentle-river-bank.trycloudflare.com
Webhook URL:      https://gentle-river-bank.trycloudflare.com/v1/billing/providers/opn/webhooks
OPN test keys:    https://dashboard.omise.co/test/keys
OPN test webhook: https://dashboard.omise.co/test/webhooks
```

Keep this process running while testing.

---

## Configure OPN test dashboard

Use the **test** dashboard only:

- keys: `https://dashboard.omise.co/test/keys`
- webhooks: `https://dashboard.omise.co/test/webhooks`

Paste the printed webhook URL into the OPN test webhook endpoint.

---

## End-to-end local test flow

1. start your local API
2. start the Cloudflare quick tunnel helper
3. set the printed webhook URL in OPN test dashboard
4. in eGP, create or select a bill and generate an OPN PromptPay request
5. confirm the payment request exists locally in the DB
6. in the OPN **test** dashboard, open the charge
7. use **Actions** to mark it **Successful** or **Failed**
8. watch the local API logs for the callback
9. verify billing/payment state changes locally in eGP

---

## Local debugging tips

### Watch API logs

If running `uvicorn` directly, keep that terminal visible.

If running the combined web dev flow:

```bash
cd apps/web
npm run dev
```

watch the API subprocess logs in that terminal.

### Test the public tunnel quickly

Once the tunnel is up:

```bash
curl https://<random>.trycloudflare.com/health
```

You should get:

```json
{"status":"ok"}
```

### Common failure modes

- `400 invalid opn webhook signature`
  - local API is using the wrong `EGP_OPN_SECRET_KEY` or `EGP_OPN_WEBHOOK_SECRET`
- `404 payment request not found`
  - webhook arrived for a provider reference not stored locally yet
- `502 ...`
  - provider/runtime failure in the app logic
  - or your local `cloudflared` is picking up an existing `~/.cloudflared/config.yml` with unrelated ingress rules
- Cloudflare URL changes
  - quick tunnels are temporary; update OPN test webhook again after restarting the tunnel

---

## Important limitations

- quick tunnel URLs are **temporary**
- tunnel depends on your local machine staying online
- not suitable for production payment settlement
- best for debugging, demos, and integration validation only

---

## Recommendation

Use this guide for:

- local debugging
- early webhook integration testing
- validating OPN callback flow before choosing production hosting

For production:

- use the main public API on a real host, or
- use the Lambda ingress path in [`docs/AWS_LAMBDA_OPN_WEBHOOK.md`](AWS_LAMBDA_OPN_WEBHOOK.md)
