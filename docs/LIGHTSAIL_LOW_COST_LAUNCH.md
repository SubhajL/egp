# Low-Cost Initial Launch on Lightsail

This guide is the recommended **cheap initial production-style deployment path** for the current `egp` codebase.

The repo now ships two Compose variants:

- [`docker-compose-localdev.yml`](../docker-compose-localdev.yml) for local development
- [`docker-compose.yml`](../docker-compose.yml) for the production-oriented single-host deployment described here

It complements, not replaces:

- [`docs/AWS_LAMBDA_OPN_WEBHOOK.md`](AWS_LAMBDA_OPN_WEBHOOK.md) for the optional Lambda-only OPN webhook ingress path
- [`docs/MANUAL_WEB_APP_TESTING.md`](MANUAL_WEB_APP_TESTING.md) for local/manual product validation
- [`docs/PRICING_AND_ENTITLEMENTS.md`](PRICING_AND_ENTITLEMENTS.md) for billing/plan behavior

---

## Why this guide exists

The current repo is not shaped like a pure scale-to-zero/serverless app.

From the checked-in code:

- the FastAPI app starts **lifespan background loops** in [`apps/api/src/egp_api/main.py`](../apps/api/src/egp_api/main.py)
- the API **spawns worker subprocesses locally** via `_make_discover_spawner(...)`
- worker jobs run through `python -m egp_worker.main`
- browser-driven discovery lives in the worker package and expects a normal host/container runtime

That makes a small always-on VM a better fit than a cold-start-heavy serverless platform for the **initial launch**.

---

## Recommendation summary

### Recommended low-cost stack

- **Frontend**: Vercel Hobby
- **Backend API**: one AWS Lightsail Linux instance
- **Database**: PostgreSQL on the same instance initially
- **Reverse proxy / TLS**: Caddy
- **DNS**: Cloudflare DNS (or Route 53 if you already use AWS DNS)
- **OPN webhook endpoint**: served by the main FastAPI app on the same instance
- **Scheduled discovery**: cron or systemd timer on the same instance

### Recommended starting size

- **Preferred**: Lightsail **$7/month** Linux instance
- **Minimum experimental**: Lightsail **$5/month** Linux instance
- if crawling bursts are heavier than expected, move to the next size up before touching architecture

---

## What this setup is good for

Use this setup when:

- you need a stable public HTTPS API cheaply
- you do not yet know real demand
- crawling is needed, but not as a 24/7 high-volume cluster
- you want the fewest moving parts for launch

Do **not** treat this as the final long-term architecture. It is the cheapest reasonable launch shape for the current repo.

---

## Deployment shape

```text
Users
  -> Vercel frontend
  -> api.yourdomain.com

api.yourdomain.com
  -> Caddy on Lightsail
  -> FastAPI app
  -> local spawned worker subprocesses
  -> local PostgreSQL

OPN webhook
  -> https://api.yourdomain.com/v1/billing/providers/opn/webhooks
```

---

## Hostname for OPN webhook

For this Lightsail path, the recommended production-style webhook endpoint is:

```text
https://api.yourdomain.com/v1/billing/providers/opn/webhooks
```

### How to get the hostname

1. buy a domain from any registrar you trust
2. point DNS for `api.yourdomain.com` to the Lightsail static IP
3. terminate HTTPS on the VM using Caddy + Let’s Encrypt
4. enter that HTTPS URL in the OPN dashboard

If you prefer a Lambda-only public webhook URL later, follow [`docs/AWS_LAMBDA_OPN_WEBHOOK.md`](AWS_LAMBDA_OPN_WEBHOOK.md).

---

## Step-by-step launch plan

## 1. Create the Lightsail instance

Create one Linux instance in the region closest to your users.

Suggested image:

- Ubuntu LTS

Suggested bundle:

- start with **$7/month** if possible
- use **$5/month** only if budget is extremely tight and traffic/crawl volume is low

Also attach:

- **static IP**

---

## 2. Open required ports

Allow inbound traffic for:

- `22` SSH
- `80` HTTP
- `443` HTTPS

Do **not** expose PostgreSQL publicly.

---

## 3. Install runtime dependencies

On the instance install:

- Docker
- Docker Compose plugin
- git
- curl
- optional: `htop`, `jq`

Example high-level commands:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
# then install Docker + compose plugin using Docker's official install steps
```

---

## 4. Clone the repo

```bash
git clone <your-repo-url> egp
cd egp
```

Create a deployment working directory for persistent data, e.g.:

```bash
mkdir -p .deploy/caddy .deploy/postgres .deploy/artifacts
```

The checked-in production Compose stack already expects Caddy config at:

- [`deploy/caddy/Caddyfile`](../deploy/caddy/Caddyfile)

---

## 5. Prepare environment variables

Create a production env file outside Git, for example:

```bash
nano .deploy/egp.env
```

Suggested minimum variables:

```env
DATABASE_URL=postgresql+psycopg://egp:strong_password@127.0.0.1:5432/egp
EGP_AUTH_REQUIRED=true
EGP_JWT_SECRET=replace_with_long_random_secret
EGP_PAYMENT_CALLBACK_SECRET=replace_with_long_random_secret
EGP_OPN_SECRET_KEY=skey_live_or_test_xxxxx
EGP_OPN_PUBLIC_KEY=pkey_live_or_test_xxxxx
EGP_OPN_WEBHOOK_SECRET=base64_webhook_secret_from_opn_dashboard
EGP_PAYMENT_PROVIDER=opn
EGP_WEB_ALLOWED_ORIGINS=https://app.yourdomain.com,https://www.yourdomain.com
EGP_WEB_BASE_URL=https://app.yourdomain.com
NEXT_PUBLIC_EGP_API_BASE_URL=https://api.yourdomain.com
EGP_ARTIFACT_ROOT=/srv/egp/artifacts
```

### Notes

- Use **test** OPN keys first until the full payment flow is proven.
- If using SMTP / Resend / storage provider credentials, add them here too.
- Keep this file out of Git.

---

## 6. Run PostgreSQL locally on the same VM first

For the low-cost launch, run Postgres on the same machine.

That avoids paying separately for managed DB before product demand is known.

Recommended principles:

- bind PostgreSQL to localhost only
- persist data to disk
- take regular backups

You can run Postgres with Docker Compose or directly as a system package. Docker Compose is usually simpler to keep aligned with the rest of the stack.

---

## 7. Run the stack with the production Compose file

Use the checked-in single-host production-oriented Compose stack:

- [`docker-compose.yml`](../docker-compose.yml)

It includes:

- `postgres`
- `redis`
- `migrate`
- `api`
- `web`
- `caddy`

The local development file is now separate and should not be used for production:

- [`docker-compose-localdev.yml`](../docker-compose-localdev.yml)

Use the existing API Dockerfile:

- [`apps/api/Dockerfile`](../apps/api/Dockerfile)

The API image already contains the repo’s Python package layout and browser-related dependencies. That is one reason this VM approach fits the codebase well.

A typical launch command on the VM will look like:

```bash
docker compose --env-file .deploy/egp.env up -d --build
```

### Important runtime behavior from the codebase

The API process does more than serve HTTP:

- starts background dispatch loops
- claims discovery jobs
- spawns worker subprocesses locally

So it should run as a **single always-on service** on this host.

---

## 8. Serve HTTPS with Caddy

Use Caddy in front of FastAPI.

Benefits:

- easiest TLS setup
- automatic Let’s Encrypt renewals
- simple reverse proxy config

Example Caddy concept:

```text
api.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```

Point DNS first, then start Caddy.

---

## 9. Point DNS

Create an `A` record:

- `api.yourdomain.com` -> Lightsail static IP

If your frontend is on Vercel, also point your frontend hostname there separately.

---

## 10. Apply database migrations

Before serving real traffic, apply migrations using the repo’s migration runner.

Use the same database URL the API will use.

---

## 11. Seed or create the first admin/owner user

Use the repo’s existing auth/bootstrap flows or admin APIs to ensure there is at least one owner/admin account before launch.

---

## 12. Configure OPN webhook

After HTTPS is live, set the OPN webhook URL to:

```text
https://api.yourdomain.com/v1/billing/providers/opn/webhooks
```

For detailed OPN/Lambda-specific notes, see [`docs/AWS_LAMBDA_OPN_WEBHOOK.md`](AWS_LAMBDA_OPN_WEBHOOK.md).

---

## How crawling runs on this setup

## Immediate / product-triggered crawl

This repo currently supports API-triggered discovery that spawns worker subprocesses locally.

That means:

- user creates or updates a profile / recrawl action
- the API queues discovery jobs
- the API dispatch loop claims jobs
- the API spawns a worker subprocess per keyword

This behavior is already in the code and does **not** require a separate always-on worker service for the initial launch.

## Scheduled crawl

For scheduled discovery, run a periodic command from the same VM using:

- cron, or
- systemd timer

This is the cheapest production-style scheduler for the current codebase.

### Recommendation

Start with **cron/systemd timer** instead of adding a second permanent worker host.

---

## What to avoid in this launch shape

Avoid these until demand is proven:

- separate ECS/Fargate API + worker services
- separate managed RDS if same-box Postgres is sufficient for now
- tunnel-based production webhooks
- Lambda + local DB proxy chain for the payment-critical path
- multi-node crawling infrastructure

---

## Operational cautions

This setup is intentionally cheap, so be explicit about tradeoffs.

### Risks you are accepting

- single VM = single point of failure
- Postgres and API share one box
- browser-heavy crawl bursts can contend with API resources
- manual backups / restore discipline are required

### Mitigations

- daily DB dumps to off-box storage
- monitor disk space
- monitor memory pressure during crawl bursts
- upgrade VM size early if browser tasks start starving API responsiveness

---

## Suggested upgrade path later

When traction is proven, migrate in this order:

1. move Postgres off-box (Supabase or RDS)
2. split browser worker onto separate compute
3. optionally move OPN webhook ingress to Lambda using [`docs/AWS_LAMBDA_OPN_WEBHOOK.md`](AWS_LAMBDA_OPN_WEBHOOK.md)
4. later move API to ECS/Fargate if needed

That path keeps the initial launch cheap without locking you into the single-VM architecture forever.

---

## Decision rule

Choose this guide when:

- you want the **lowest reasonable cash burn**
- you need **stable HTTPS** for OPN now
- you want to launch with the **fewest code changes**
- you accept a simple single-node architecture temporarily

Choose the Lambda-only webhook guide when:

- you want the webhook endpoint isolated from the main API surface
- you already have a reachable hosted database
- you are comfortable with AWS SAM and Lambda deployment flow
