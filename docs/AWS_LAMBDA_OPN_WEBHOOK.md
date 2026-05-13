# AWS Lambda OPN Webhook

This repo now includes a **Lambda-only webhook ingress path** for OPN/Omise payment callbacks.
It is intended for teams that want a stable public HTTPS endpoint for payment settlement without
exposing the full FastAPI app.

If you instead want the cheapest single-VM launch path for the current repo shape, see
[`docs/LIGHTSAIL_LOW_COST_LAUNCH.md`](LIGHTSAIL_LOW_COST_LAUNCH.md).

If you want to test OPN callbacks against a **local API port** through a temporary
Cloudflare URL, see [`docs/CLOUDFLARE_LOCAL_OPN_WEBHOOK.md`](CLOUDFLARE_LOCAL_OPN_WEBHOOK.md).

## What it does

- Receives `POST /v1/billing/providers/opn/webhooks` through API Gateway.
- Verifies `x-opn-signature` using the existing OPN provider logic.
- Looks up the billing payment request by provider reference.
- Reuses the existing billing repository + settlement logic, including callback idempotency.
- Returns a JSON response suitable for API Gateway / Lambda integration.

Handler module:

- `egp_api.lambda_handlers.opn_webhook.lambda_handler`

Container build file:

- `apps/api/Dockerfile.lambda-opn-webhook`

SAM template:

- `apps/api/aws/opn-webhook-lambda-template.yaml`

## Runtime configuration options

The Lambda supports three configuration modes:

### Option A — direct environment variables

- `DATABASE_URL`
- `EGP_PAYMENT_PROVIDER=opn`
- `EGP_OPN_SECRET_KEY`
- `EGP_OPN_PUBLIC_KEY` (optional)
- `EGP_OPN_WEBHOOK_SECRET` (recommended for Omise-Signature verification)

### Option B — Secrets Manager JSON bundle

Set:

- `EGP_LAMBDA_CONFIG_SECRET_ARN`

Secret value must be a JSON object like:

```json
{
  "database_url": "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
  "opn_secret_key": "skey_test_xxxxx",
  "opn_public_key": "pkey_test_xxxxx",
  "opn_webhook_secret": "base64_webhook_secret_from_opn_dashboard"
}
```

### Option C — SSM Parameter Store JSON bundle

Set:

- `EGP_LAMBDA_CONFIG_SSM_PARAMETER`

Parameter value should be the same JSON object as the Secrets Manager example above.

### Precedence

Direct environment variables override values loaded from Secrets Manager or SSM. If both
`EGP_LAMBDA_CONFIG_SECRET_ARN` and `EGP_LAMBDA_CONFIG_SSM_PARAMETER` are set, the secret ARN wins.

## Deploy with AWS SAM

Build and deploy from the repo root:

```bash
sam build -t apps/api/aws/opn-webhook-lambda-template.yaml
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

The template supports either:

- direct parameter values (`DatabaseUrl`, `OpnSecretKey`, `OpnPublicKey`), or
- a single Secrets Manager JSON bundle (`ConfigSecretArn`), or
- a single SSM JSON bundle (`ConfigSsmParameterName`)

You still provide subnet IDs + security groups when the Lambda must reach a private database.

### Example Secrets Manager setup

```bash
aws secretsmanager create-secret \
  --name egp/opn-webhook/config \
  --secret-string '{
    "database_url":"postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
    "opn_secret_key":"skey_test_xxxxx",
    "opn_public_key":"pkey_test_xxxxx",
    "opn_webhook_secret":"base64_webhook_secret_from_opn_dashboard"
  }'
```

Then pass the resulting ARN as `ConfigSecretArn` during `sam deploy --guided`.

### Example SSM setup

```bash
aws ssm put-parameter \
  --name /egp/opn-webhook/config \
  --type SecureString \
  --value '{
    "database_url":"postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME",
    "opn_secret_key":"skey_test_xxxxx",
    "opn_public_key":"pkey_test_xxxxx",
    "opn_webhook_secret":"base64_webhook_secret_from_opn_dashboard"
  }'
```

Then pass `/egp/opn-webhook/config` as `ConfigSsmParameterName`.

If your database is publicly reachable (for example a managed external Postgres endpoint with IP allow-listing),
you can remove `VpcConfig` from the template before deploy.

## OPN dashboard configuration

Set the webhook URL in OPN to the output from the stack, for example:

```text
https://abc123.execute-api.ap-southeast-1.amazonaws.com/prod/v1/billing/providers/opn/webhooks
```

Use the **test dashboard** while validating the integration:

- keys: `https://dashboard.omise.co/test/keys`
- webhooks: `https://dashboard.omise.co/test/webhooks`

The OPN documentation for PromptPay confirms that in **test mode** you can manually mark the
charge as successful or failed from the dashboard to simulate settlement, and webhook completion
is then delivered to your configured endpoint.

## Notes

- API Gateway must pass the **raw request body** through to Lambda; the handler uses the raw body for signature verification.
- The Lambda returns `404` when the provider reference is unknown, `400` for invalid payload/signature issues, and `502` for provider/runtime failures.
- The same callback can be delivered more than once; settlement remains idempotent because it reuses the existing repository callback dedupe path.

## Local test shape

The Lambda handler accepts standard API Gateway proxy-style events:

```json
{
  "headers": {
    "x-opn-signature": "base64-hmac-signature",
    "content-type": "application/json"
  },
  "body": "{\"id\":\"evt_test_001\",\"key\":\"charge.complete\",\"data\":{...}}",
  "isBase64Encoded": false
}
```

## Ready OPN payment for testing

### 1. Prepare test keys

In the OPN test dashboard, collect:

- test secret key: `skey_test_...`
- test public key: `pkey_test_...`

### 2. Deploy the webhook target

Choose one public HTTPS target:

- the new AWS Lambda URL from this stack, or
- the existing FastAPI route if your API is already public

For Lambda, deploy with either direct parameters or the Secrets Manager / SSM bundle described above.

### 3. Configure the test webhook endpoint in OPN

In `dashboard.omise.co/test/webhooks`, set the endpoint to:

```text
https://<your-api-gateway-domain>/prod/v1/billing/providers/opn/webhooks
```

### 4. Verify database reachability from Lambda

Before testing real callbacks, ensure the Lambda can reach the database:

- if the database is private, provide working subnet IDs + security groups
- if the database is public, allow Lambda egress or remove `VpcConfig` from the template

### 5. Generate a payment request from eGP

In the product:

1. create or select a billing record with outstanding balance
2. generate an OPN PromptPay payment request
3. confirm the payment request row exists in the DB and has a provider reference

The webhook settlement path depends on this provider reference existing before OPN sends `charge.complete`.

### 6. Simulate settlement in test mode

For PromptPay test charges, OPN documents that you can:

1. open the charge in the **test dashboard**
2. use **Actions**
3. manually mark the charge as **Successful** or **Failed**

That should trigger a webhook event such as `charge.complete` to your Lambda endpoint.

### 7. Confirm settlement in eGP

After the webhook fires, verify:

- Lambda returns `200`
- billing record status moves forward (typically to `paid` after reconciliation)
- payment request status becomes settled
- one payment row is recorded
- repeat delivery of the same event does **not** create duplicate payments

### 8. Troubleshooting checklist

If testing fails:

- `400 invalid opn webhook signature` → wrong `EGP_OPN_SECRET_KEY` or `EGP_OPN_WEBHOOK_SECRET`
- `404 payment request not found` → webhook arrived before eGP created/stored the request reference
- `502 ...` → Lambda can run but cannot complete provider/runtime/DB work
- timeout / no logs → VPC, subnet, route table, or security group issue

## When to use this vs FastAPI route

Use the Lambda ingress when you need:

- a cheap stable public webhook URL
- no public FastAPI exposure
- independent scaling for payment callbacks

Keep the normal FastAPI route when:

- your API is already public and stable
- you prefer a single deployment surface
- you do not want separate AWS infrastructure for webhooks
