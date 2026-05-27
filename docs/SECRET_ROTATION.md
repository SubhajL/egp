# Secret Rotation Runbook

Operator runbook for rotating every credential the e-GP Intelligence Platform
relies on. Pair this with `deploy/.env.production.example` (the source of truth
for env var names) and `/etc/egp/egp.env` (the deployed file).

> **Status:** shipped in PR-B of the deployment-readiness initiative.
> Cadence: **rotate quarterly** by default, **immediately on incident**, and
> **on operator handoff**. Mark each rotation in the operator change log.

---

## 1. Common workflow

For every secret below, the process follows the same shape:

| Step | Meaning |
|---|---|
| **Generate** | Exact shell command for a fresh value |
| **Roll** | Where the value is stored — env file, secret manager, provider dashboard |
| **Restart** | Which services must be restarted to pick up the new value |
| **Verify** | Observable signal that the new value is live and working |
| **Window** | How long the old and new values can coexist (overlap requirement) |
| **Frequency** | Default cadence (incident / quarterly / annual) |

A rotation is **complete** only when the old value has been revoked at the
source (provider dashboard, IAM policy, etc.) and the verify step shows the
new value in use.

---

## 2. `EGP_JWT_SECRET` — API JWT signing key

Used by `apps/api` to sign session JWTs.

- **Generate**: `openssl rand -hex 32`
- **Roll**: edit `/etc/egp/egp.env`; replace the `EGP_JWT_SECRET=` line.
- **Restart**: `sudo systemctl restart egp-api.service` (or the API container
  / `pm2 reload egp-api` depending on deploy).
- **Verify**: after restart, log in as any test user — the new session cookie
  contains a JWT signed with the new secret. Existing sessions issued under
  the previous secret are invalidated (this is expected; see Window).
- **Window**: **zero overlap**. Rotating this secret invalidates all in-flight
  sessions. Schedule for off-peak. Communicate to users that they'll be
  re-prompted to log in.
- **Frequency**: quarterly, or immediately if leaked.

> **Note**: the API falls back to `SUPABASE_JWT_SECRET` if `EGP_JWT_SECRET` is
> empty. Don't rely on the fallback in production — set `EGP_JWT_SECRET`
> explicitly.

---

## 3. `EGP_PAYMENT_CALLBACK_SECRET` — internal callback shared-secret

Used by `apps/api/src/egp_api/routes/billing.py:234` to authorize internal
callbacks (e.g. payment-reconciliation worker → API). The API does a strict
string-equality compare on the `x-egp-payment-callback-secret` request header
against the env var — this is **not** an HMAC, just a shared secret.

- **Generate**: `openssl rand -hex 32`
- **Roll**: edit `/etc/egp/egp.env`; replace `EGP_PAYMENT_CALLBACK_SECRET=`.
  Also update the same value in every caller (worker / cron jobs / scripts)
  that sends the `x-egp-payment-callback-secret` header.
- **Restart**: `sudo systemctl restart egp-api.service` first, then restart
  every caller that holds the secret.
- **Verify**: trigger a synthetic internal-callback request (e.g. cron job
  manual run) → API returns 200 → journalctl shows no
  `invalid payment callback secret` errors.
- **Window**: **zero overlap** — the API only checks the current env value;
  there is no dual-secret support. Plan a planned-restart window where the
  API and all callers restart in lockstep (or briefly accept 401s from
  callers using the old secret until they restart).
- **Frequency**: quarterly, or immediately if leaked.

> This is **NOT** the OPN webhook signature secret. OPN webhooks are
> authenticated separately via `EGP_OPN_WEBHOOK_SECRET` (HMAC, see §5).

---

## 4. `EGP_INTERNAL_WORKER_TOKEN` — worker → API authentication

Used by `apps/worker` to authenticate to API internal endpoints (e.g. document
ingest, run-status updates).

- **Generate**: `openssl rand -hex 32`
- **Roll**: update **both** `/etc/egp/egp.env` (used by api) AND every host
  running workers. Edit `EGP_INTERNAL_WORKER_TOKEN` and the legacy peer
  `EGP_API_BEARER_TOKEN` to the same value.
- **Restart**: API first (`systemctl restart egp-api.service`), then each
  worker (`systemctl restart egp-worker@*.service`).
- **Verify**: tail `egp-worker@*.service` journalctl; the next discovery run's
  internal API calls should succeed (HTTP 200). 401/403 means a worker is
  still using the old token.
- **Window**: keep the API accepting **both** old and new tokens for **15
  minutes** by temporarily exporting both as a comma-separated value (if the
  code supports it) — OR plan a brief planned-downtime window where api
  restarts first, then all workers. Default deployment expects the planned
  restart approach.
- **Frequency**: quarterly, or immediately if leaked.

---

## 5. `EGP_OPN_SECRET_KEY` and `EGP_OPN_WEBHOOK_SECRET` — OPN Payments

Used by the OPN payment provider integration. Two separate values rotated
together because they live in the same provider dashboard.

`EGP_OPN_WEBHOOK_SECRET` is the HMAC secret used to verify incoming OPN
webhook signatures (`apps/api/src/egp_api/services/payment_provider.py:213`).
The API only checks the CURRENT env value, so rotation requires a planned
cutover — there is no dual-secret support in the code today.

- **Generate**: provision a new key pair in the [OPN
  dashboard](https://dashboard.omise.co/) → **Settings** → **Keys** → **Generate
  new key pair**.
- **Roll**: edit `/etc/egp/egp.env`; replace `EGP_OPN_SECRET_KEY=` and
  `EGP_OPN_WEBHOOK_SECRET=`.
- **Restart**: `sudo systemctl restart egp-api.service`
- **Verify**: trigger a sandboxed payment via the OPN dashboard's test mode;
  API responds 200 and a `payment_provider_webhook` row appears in
  `payment_provider_webhooks` with `verified=true`.
- **Window**: **zero overlap** at the API level. Planned-cutover procedure:
  1. Disable webhook delivery in OPN dashboard (or pause incoming payments)
  2. Restart `egp-api.service` with the new keys
  3. Re-enable webhook delivery in OPN dashboard with the new key active
  4. Revoke the old key in the OPN dashboard
  If you cannot tolerate a brief webhook-delivery pause, add dual-secret
  support to the code first (out of scope for PR-B).
- **Frequency**: quarterly, or immediately if leaked.

> `EGP_OPN_PUBLIC_KEY` is not a secret (it's published to browsers) but should
> still be updated in lockstep when generating a new key pair.

---

## 5b. `EGP_STRIPE_SECRET_KEY` and `EGP_STRIPE_WEBHOOK_SECRET` — Stripe Payments

> **Full deployment runbook**: [`docs/STRIPE_DEPLOYMENT.md`](./STRIPE_DEPLOYMENT.md)
> — covers account setup (Stripe Thailand vs Atlas), webhook endpoint
> configuration, test-mode → live cutover, and common gotchas.


Used by `StripeProvider` in `apps/api/src/egp_api/services/payment_provider.py`
when `EGP_PAYMENT_PROVIDER=stripe`. Two keys rotated independently:

- **`EGP_STRIPE_SECRET_KEY`** (`sk_live_*` or `sk_test_*`) is the API
  Bearer token used for `POST /v1/payment_intents` and `POST /v1/payment_links`.
- **`EGP_STRIPE_WEBHOOK_SECRET`** (`whsec_*`) is the HMAC-SHA256 key used
  to verify the `Stripe-Signature` header on incoming webhooks.

Rotation procedure:

- **Generate (secret key)**: Stripe Dashboard → **Developers → API keys
  → Roll** a restricted key with `read_write` on `PaymentIntents`,
  `PaymentLinks`, `Charges`.
- **Generate (webhook secret)**: Dashboard → **Developers → Webhooks**
  → click your endpoint → **Roll secret**.
- **Roll**: update `/etc/egp/egp.env` with the new value(s).
- **Restart**: `sudo systemctl restart egp-api.service` (Stripe key
  is only read at startup, like OPN).
- **Verify**: send a sandboxed test PaymentIntent via the Stripe
  Dashboard's **Webhooks → Send test webhook**; API responds 200 and
  `payment_provider_events` records the event with `verified=true`.
- **Window**: **zero overlap** at the API level (mirrors OPN; the
  provider only reads the current env value). For the **webhook
  secret** specifically, Stripe supports up to 2 active signing secrets
  for ~24h after rotation — that gives a generous overlap window AT
  STRIPE's side. For the API key, no overlap; plan a brief restart.
- **Frequency**: quarterly, or immediately on leak.

> Stripe API version is pinned in `StripeProvider._api_version`
> (currently `2026-04-22.dahlia`). Bumping the version is a code
> change, not a rotation.

---

## 6. `EGP_BACKUP_R2_SECRET_ACCESS_KEY` — Cloudflare R2 backup credentials

Used by `scripts/pg_backup.sh` and `scripts/artifact_backup.sh` to upload to
Cloudflare R2. The access key ID is non-secret but should be rotated together.

- **Generate**: Cloudflare dashboard → **R2** → **Manage R2 API tokens** →
  **Create API token** (scope: Object Read & Write, bucket: backup bucket).
- **Roll**: edit `/etc/egp/egp.env` (or `/etc/egp/backup.env` if you use the
  scoped subset) — update `EGP_BACKUP_R2_ACCESS_KEY_ID` and
  `EGP_BACKUP_R2_SECRET_ACCESS_KEY`.
- **Restart**: nothing to restart (cron / systemd timer picks up env on next
  run). To verify immediately:
  ```
  set -a && . /etc/egp/egp.env && set +a && /opt/egp/scripts/pg_backup.sh
  ```
- **Verify**: the manual backup run produces a new `.dump.gz` + `.sha256` in
  the local cache AND the file appears in the R2 bucket (Cloudflare dashboard).
- **Window**: keep the old token active for **24 hours** so any in-flight
  scheduled backup completes. Then delete the old token in the Cloudflare
  dashboard.
- **Frequency**: quarterly, or immediately if leaked.

---

## 7. `SUPABASE_SERVICE_ROLE_KEY` — Supabase Storage + Auth

Used by `apps/api` to call Supabase Storage with full bypass privileges, and
to validate Supabase-issued JWTs. **High-value secret** — full read/write on
the Supabase project.

- **Generate**: Supabase dashboard → **Project Settings** → **API** → **Service
  role secret** → **Generate new key**.
- **Roll**: edit `/etc/egp/egp.env`; replace `SUPABASE_SERVICE_ROLE_KEY=`.
- **Restart**: `sudo systemctl restart egp-api.service` and any worker that
  reads it (`systemctl restart egp-worker@*.service`).
- **Verify**: API can ingest a new test document via the document-upload
  endpoint AND retrieve it via signed URL. Both must succeed end-to-end.
- **Window**: Supabase supports **only one** active service-role key at a
  time, so plan a brief restart window. Tail `egp-api.service` for any 401
  errors during the cutover.
- **Frequency**: quarterly, or immediately on any suspected platform-account
  compromise.

---

## 8. Postgres password (`DATABASE_URL`)

The password embedded in `DATABASE_URL=postgresql://egp:PASSWORD@host/db`.

- **Generate**: `openssl rand -hex 24`
- **Roll**: two steps:
  1. In Postgres as a superuser: `ALTER ROLE egp WITH PASSWORD '<new>';`
  2. Edit `/etc/egp/egp.env` and reconstruct `DATABASE_URL` with the new
     password.
- **Restart**: `sudo systemctl restart egp-api.service egp-worker@*.service`
- **Verify**: API health endpoint returns 200; tail journalctl for both
  services to confirm no `password authentication failed` errors.
- **Window**: Postgres only enforces one password per role. Plan a brief
  restart window (~30s) where API and workers restart together. Connections
  open at the moment of `ALTER ROLE` continue with the old credential; new
  connections need the new credential.
- **Frequency**: quarterly, or immediately on any suspected DB compromise.

> If using Supabase managed Postgres, generate the new password via the
> Supabase dashboard (**Settings** → **Database** → **Database password**).

---

## 9. `EGP_STORAGE_CREDENTIALS_SECRET` — per-tenant storage credentials envelope

Used by the credentials envelope to encrypt per-tenant Google Drive / OneDrive
OAuth tokens at rest. Rotating this requires re-encrypting every tenant's
stored token.

- **Generate**: `openssl rand -hex 32`
- **Roll**: requires a one-time migration:
  1. Bring up a maintenance window
  2. Decrypt all existing credentials envelopes with the OLD secret
  3. Re-encrypt with the NEW secret
  4. Atomically swap the values
  Migration tooling for this is **not** in the repo yet — file a ticket
  before attempting to rotate this secret.
- **Restart**: full API + worker restart after migration completes
- **Verify**: pick a tenant with stored credentials, fetch their connector
  status — should remain "connected" without re-OAuth prompt.
- **Window**: requires a maintenance window. Plan in advance.
- **Frequency**: annual, or immediately on any suspected compromise of the
  envelope key.

---

## 10. `EGP_GRAFANA_ADMIN_PASSWORD` — Grafana admin login

Used by the `docker-compose.monitoring.yml` overlay (PR-E) to set the
initial Grafana admin password on first container start. Grafana stores
the password hash in its own SQLite volume (`egp_grafana_data`); the
env var is read by Grafana ONLY on first startup. Subsequent changes
must go through the Grafana UI or `grafana cli admin reset-admin-password`.

- **Generate**: `openssl rand -hex 24`
- **Roll**: two-step (env var alone is insufficient because Grafana
  persists the hash):
  1. Update via Grafana CLI:
     ```bash
     docker compose -f docker-compose.yml -f docker-compose.monitoring.yml \
         exec grafana grafana cli admin reset-admin-password '<new-password>'
     ```
  2. Update `EGP_GRAFANA_ADMIN_PASSWORD` in `/etc/egp/egp.env` so future
     container recreates use the new value.
- **Restart**: no restart needed for the password change itself; the
  env-var update only affects fresh `docker volume rm egp_grafana_data`
  recreations.
- **Verify**: log into Grafana via the SSH tunnel
  (`ssh -L 3001:127.0.0.1:3000 user@host` → `http://localhost:3001`)
  with the new password.
- **Window**: zero overlap; the CLI reset takes effect immediately.
- **Frequency**: quarterly, or immediately if leaked.

> The Grafana admin user has full read/write access to all dashboards
> and data sources. Treat this password as a launch-critical secret.

---

## 11. Operator-level credentials (not in env)

Some operator-facing credentials are NOT in `/etc/egp/egp.env` but should
follow the same cadence:

- **OPN dashboard login** — rotate password annually; enable 2FA.
- **Cloudflare dashboard login** — rotate password annually; enable 2FA.
- **Supabase project owner** — rotate password annually; enable 2FA.
- **AWS Lightsail SSH key** — rotate yearly; revoke any compromised
  intermediate hosts immediately.
- **Cron / systemd-unit owner shell account** — review yearly; remove
  any unused operators.

---

## 12. Change-log template

Whenever you rotate a secret, append a line to the operator change log:

```
2026-Q3 | 2026-08-15 | alice@example.com | rotated EGP_JWT_SECRET
                                          | reason: scheduled quarterly
                                          | verify: smoke-login ok
```

This makes the next operator (or audit) able to reconstruct WHO rotated WHAT
WHEN.

---

## 13. Emergency rotation (leaked secret)

If a secret is suspected leaked:

1. **Revoke at source first**, before rotating the env file. The leaked value
   must stop working.
   - OPN: dashboard → keys → revoke
   - Cloudflare R2: dashboard → R2 tokens → revoke
   - Supabase: dashboard → API → revoke service-role key
   - For `EGP_JWT_SECRET` / `EGP_PAYMENT_CALLBACK_SECRET` /
     `EGP_INTERNAL_WORKER_TOKEN`: skip directly to step 2 (no external
     "revoke" — they're shared secrets, so rotating them IS revocation)
2. Follow the normal rotation procedure for the affected secret (sections 2-9).
3. Audit `egp-api.service` and `egp-worker@*.service` journalctl for any
   suspicious requests between leak time and revocation time.
4. File an incident report — include the leak vector, blast radius, and
   audit findings.
5. If the leak vector was a committed file, force-rewrite git history to
   remove it. Notify all collaborators to re-clone.
