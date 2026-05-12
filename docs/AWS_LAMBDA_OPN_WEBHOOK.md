# AWS Lambda OPN Webhook

This repo now includes a **Lambda-only webhook ingress path** for OPN/Omise payment callbacks.
It is intended for teams that want a stable public HTTPS endpoint for payment settlement without
exposing the full FastAPI app.

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

## Required environment variables

The Lambda runtime needs the same core payment settings used by the API service:

- `DATABASE_URL`
- `EGP_PAYMENT_PROVIDER=opn`
- `EGP_OPN_SECRET_KEY`
- `EGP_OPN_PUBLIC_KEY` (optional)

## Deploy with AWS SAM

Build and deploy from the repo root:

```bash
sam build -t apps/api/aws/opn-webhook-lambda-template.yaml
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

The template expects:

- database URL
- OPN secret/public keys
- subnet IDs + security groups when the Lambda must reach a private database

If your database is publicly reachable (for example a managed external Postgres endpoint with IP allow-listing),
you can remove `VpcConfig` from the template before deploy.

## OPN dashboard configuration

Set the webhook URL in OPN to the output from the stack, for example:

```text
https://abc123.execute-api.ap-southeast-1.amazonaws.com/prod/v1/billing/providers/opn/webhooks
```

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

## When to use this vs FastAPI route

Use the Lambda ingress when you need:

- a cheap stable public webhook URL
- no public FastAPI exposure
- independent scaling for payment callbacks

Keep the normal FastAPI route when:

- your API is already public and stable
- you prefer a single deployment surface
- you do not want separate AWS infrastructure for webhooks
