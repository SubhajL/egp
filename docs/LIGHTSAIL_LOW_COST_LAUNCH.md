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

- background execution is controlled by `EGP_BACKGROUND_RUNTIME_MODE`
- in `embedded` mode, the FastAPI app starts lifespan background loops from [`apps/api/src/egp_api/bootstrap/background.py`](../apps/api/src/egp_api/bootstrap/background.py)
- in `external` mode, standalone executor processes run webhook delivery and discovery dispatch outside the HTTP server
- discovery dispatch still spawns worker subprocesses locally via `_make_discover_spawner(...)`
- worker jobs run through `python -m egp_worker.main`
- browser-driven discovery lives in the worker package and expects a normal host/container runtime

That makes a small always-on VM a better fit than a cold-start-heavy serverless platform for the **initial launch**.

---

## Recommendation summary

### Recommended low-cost stack

- **Frontend**: Vercel Hobby (free) — keeps marketing/traffic spikes off the VM
- **Backend API**: one AWS Lightsail Linux instance in Singapore
- **Database**: PostgreSQL on the same instance initially
- **Reverse proxy / TLS**: Caddy
- **DNS**: Cloudflare DNS (or Route 53 if you already use AWS DNS) — keep `api.*` as DNS-only (proxy OFF) so OPN webhooks reach you directly
- **OPN webhook endpoint**: served by the main FastAPI app on the same instance
- **Background executors**: Compose services on the same instance
- **Scheduled discovery**: cron or systemd timer on the same instance if needed

### Why Vercel for the frontend (not the in-Compose `web` service)

The production Compose file ships a `web` Next.js service for single-host *convenience*, but the production target is **Vercel**. A marketing push hits page views, not crawls — Vercel's free tier absorbs viral spikes without touching your VM. The in-Compose `web` is only suitable when you have not yet wired up Vercel.

### Recommended starting size

Lightsail Linux bundles (always verify current pricing at <https://aws.amazon.com/lightsail/pricing/> — AWS adjusts these):

| USD/mo | RAM | vCPU | SSD | Transfer | Fits this app? |
|---|---|---|---|---|---|
| $3.50 | 512 MB | 2 | 20 GB | 1 TB | ❌ OOMs on first crawl |
| $5 | 1 GB | 2 | 40 GB | 2 TB | ❌ Swap-thrashes |
| $7 | 2 GB | 2 | 60 GB | 3 TB | ⚠️ Tight at `worker_count=1` |
| **$12** | **4 GB** | **2** | **80 GB** | **4 TB** | ✅ **Cheapest viable** |
| **$24** | **8 GB** | **2** | **160 GB** | **5 TB** | ✅ **Headroom through `worker_count=4`** |
| $44 | 16 GB | 4 | 320 GB | 6 TB | Overkill for launch |

**Pick one of two**:

- **Cheapest viable launch**: **$12/month (4 GB / 2 vCPU)** — runs the stack at `EGP_DISCOVERY_WORKER_COUNT=1`. You will need to resize before ramping past 1 worker.
- **Recommended for ramp**: **$24/month (8 GB / 2 vCPU)** — buys you headroom through `worker_count=2 → 4` without a forced live migration. The extra ~฿420/month is cheap insurance against a viral marketing moment hitting an under-sized box.

**Region**: `ap-southeast-1` (Singapore) — closest to Thai customers and to gprocurement.go.th (~30–45 ms RTT).

**Why not the $3.50 / $5 / $7 bundles**: this repo's API and worker images both bake Chromium via `playwright install chromium --with-deps` (see `apps/api/Dockerfile:23`, `apps/worker/Dockerfile:21`). A single Chromium process with a populated profile is ~500 MB RSS, and the rest of the stack (Postgres + API + executors + Caddy + optional in-Compose Next.js) lands around 1.5 GB. The $5 bundle (512 MB) OOM-kills on the first crawl and the $7 bundle (1 GB / 2 GB depending on AWS's current tiering) swap-thrashes.

If crawling bursts at `EGP_DISCOVERY_WORKER_COUNT=1` already pressure the box, move to the next size up before raising the worker count further.

### Cost in Thai Baht (for operators billing from Thailand)

Lightsail is billed **in USD globally** — Singapore region uses the same USD prices as US regions. Your Thai card issuer does the FX conversion.

Three layers of cost to budget for:

1. **Base USD**: bundle price (e.g., $12 or $24).
2. **Thai bank FX markup**: typically 1.0–2.5% on top of spot rate. Effective rate ~฿35.5 to ฿36.5 per USD (varies; check your card's terms).
3. **Thai VAT 7%**: only applies once your AWS account has a Thai tax ID attached (typically after registering a บริษัท จำกัด with the Revenue Department). Pre-registration, no VAT line on the AWS invoice. Once you cross ฿1.8M revenue and must file VAT returns, the 7% becomes input VAT you can claim back.

Approximate monthly cost at the time of writing:

| Bundle | USD | THB (no VAT, 1.5% FX markup) | THB (with 7% VAT) |
|---|---|---|---|
| $12 (4 GB) | $12 | **~฿426** | ~฿456 |
| $24 (8 GB) | $24 | **~฿853** | ~฿912 |

Add ~฿36/month amortised for a `.com` domain (~$12/year) and ~฿3/month for Cloudflare R2 backup storage. **Total fixed monthly floor**: approximately **฿470 (cheapest) or ฿890 (recommended)** before any per-transaction OPN/Stripe fees.

Annual fixed cost: **~฿5,600** (4 GB tier) or **~฿10,700** (8 GB tier).

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

background executors on the same VM
  -> webhook delivery executor
  -> discovery dispatch executor
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

Create one Linux instance in the **ap-southeast-1 (Singapore)** region.

Suggested image:

- Ubuntu 22.04 or 24.04 LTS

Suggested bundle (see the table under "Recommended starting size" for the full comparison):

- **$12/month** (4 GB RAM, 2 vCPU, 80 GB SSD, 4 TB transfer) — cheapest viable, requires resize before `worker_count > 1`.
- **$24/month** (8 GB RAM, 2 vCPU, 160 GB SSD, 5 TB transfer) — recommended; covers ramp through `worker_count=4` without re-sizing.

Anything below the 4 GB tier will OOM under crawl load because of the bundled Chromium. Verify current bundle pricing at <https://aws.amazon.com/lightsail/pricing/> before purchasing — AWS adjusts these.

Also attach:

- **static IP** (free while attached)
- **automatic snapshots** (~$0.05 / GB / month)

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
EGP_BACKGROUND_RUNTIME_MODE=external
EGP_DISCOVERY_WORKER_COUNT=1
EGP_BROWSER_CDP_PORT_BASE=9222
EGP_BROWSER_CDP_PORT_RANGE=200
EGP_BROWSER_PROFILE_ROOT=/srv/egp/browser-profiles
```

### Notes

- Use **test** OPN keys first until live KYC clears on the OPN dashboard.
- If using SMTP / Resend / storage provider credentials, add them here too.
- Keep this file out of Git.

### Generating strong secrets

```bash
openssl rand -hex 32   # EGP_JWT_SECRET
openssl rand -hex 32   # EGP_PAYMENT_CALLBACK_SECRET
openssl rand -hex 32   # EGP_INTERNAL_WORKER_TOKEN
openssl rand -hex 24   # EGP_POSTGRES_PASSWORD
```

Each secret should be unique per environment. Never reuse dev secrets in production.

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
- `migrate`
- `api`
- `webhook-executor`
- `discovery-executor`
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

The production-oriented Compose file runs background work outside the API process:

- `api` serves HTTP with `EGP_BACKGROUND_RUNTIME_MODE=external`
- `webhook-executor` runs `python -m egp_api.executors.webhook_delivery`
- `discovery-executor` runs `python -m egp_api.executors.discovery_dispatch`
- the discovery executor claims discovery jobs and spawns worker subprocesses locally

This avoids duplicate queue processing while keeping all services on one cheap host.

### Rollback to embedded mode

If you need to simplify the runtime during an incident:

1. stop the executor services:

```bash
docker compose --env-file .deploy/egp.env stop webhook-executor discovery-executor
```

2. set `EGP_BACKGROUND_RUNTIME_MODE=embedded` in `.deploy/egp.env`
3. restart the API:

```bash
docker compose --env-file .deploy/egp.env up -d api
```

In embedded mode the API resumes the legacy in-process background behavior. Do not leave external executors running while the API is in embedded mode.

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

## Pre-ramp operational validation

After Compose is up and HTTPS is live, validate the post-PR-08 safe operating point before exposing the URL publicly:

```bash
# Point at your running API; needs DATABASE_URL and EGP_BROWSER_PROFILE_ROOT to match prod env
API_URL=https://api.yourdomain.com \
DATABASE_URL=postgresql://egp:...@127.0.0.1:5432/egp \
EGP_BROWSER_PROFILE_ROOT=/srv/egp/browser-profiles \
EGP_DISCOVERY_WORKER_COUNT=1 \
  ./scripts/check_launch_gates.sh
```

Expect **PASS** for /metrics reachable, Chrome PID cap, project/document upsert outcomes, and 429-rate gate. **SKIP** is acceptable for the rate-limiter-engaging and cross-tenant DB gates until you have driven at least one real crawl.

Before any ramp of `EGP_DISCOVERY_WORKER_COUNT` past 1, also run the Mode C dry run against a local stub:

```bash
python scripts/mode_c/egp_stub_server.py &           # terminal A
python scripts/mode_c/mode_c_full_run.py             # terminal B
python scripts/mode_c/circuit_open_smoke.py          # one-shot sanity
```

These exercise the production rate-limiter under sustained synthetic load without touching the real e-GP and prove the gates would be green at higher worker counts.

## Payment provider (OPN) cost and timeline

The Lightsail instance is the only fixed monthly cost. OPN/Omise charges per-transaction only and has no monthly fee, but two things deserve planning:

| Item | Detail |
|---|---|
| Account / monthly fee | ฿0 |
| PromptPay QR fee | 1.5% + ฿1.50 per transaction |
| Domestic credit/debit card | 3.65% + ฿10 per transaction |
| International cards | 4.65% + ฿10 per transaction |
| Settlement to Thai bank | T+1 to T+2 |
| **Live KYC timeline** | **5–10 business days** — start this concurrently with infrastructure provisioning |
| KYC documents | DBD certificate, director ID + selfie, bank statement, sample invoice |

Run with OPN **test** keys until live KYC clears, then swap `EGP_OPN_SECRET_KEY` / `EGP_OPN_PUBLIC_KEY` / `EGP_OPN_WEBHOOK_SECRET` to the live values. No code change is required.

**Effective revenue erosion** is ~1.6% (PromptPay-heavy mix) to ~4% (card-heavy mix). Plan pricing accordingly.

## How crawling runs on this setup

## Immediate / product-triggered crawl

This repo currently supports API-triggered discovery that spawns worker subprocesses locally.

That means:

- user creates or updates a profile / recrawl action
- the API queues discovery jobs
- in external mode, the discovery executor claims jobs
- in embedded mode, the API dispatch loop claims jobs
- the active discovery dispatch path spawns a worker subprocess per keyword

This behavior is already in the code. The checked-in Compose runtime now runs the dispatch loop as a separate always-on executor service while staying on the same VM.

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

1. **Off-box Postgres backups first** (Cloudflare R2 / Supabase Storage / S3) — single-VM Postgres with no off-box backup is one disk failure away from total data loss
2. **Raise `EGP_DISCOVERY_WORKER_COUNT`** from 1 → 2 → 4 once `scripts/check_launch_gates.sh` is consistently green and Mode C dry runs validate the new count
3. Move Postgres off-box (Supabase or RDS) when single-tenant query load begins to compete with API responsiveness
4. Split browser worker onto separate compute (Hetzner Singapore or a second Lightsail box) when crawl bursts at worker_count=4 start starving the API
5. Optionally move OPN webhook ingress to Lambda using [`docs/AWS_LAMBDA_OPN_WEBHOOK.md`](AWS_LAMBDA_OPN_WEBHOOK.md) if you want the payment-critical path isolated from the rest of the API surface
6. Later move API to ECS/Fargate if needed

That path keeps the initial launch cheap without locking you into the single-VM architecture forever.

### When to consider leaving Lightsail entirely

If your monthly bill on Lightsail exceeds **~$60** (two $24 instances + automatic snapshots + extra storage), it is usually cheaper at that point to:

- **Hetzner Cloud Singapore CPX31**: ~$14–16/month for 4 GB / 4 vCPU / 160 GB NVMe / 20 TB transfer — same Singapore region, ~40% cheaper at higher specs, EUR billing
- **Bangkok-local IDC** (True IDC, INET, NTT): ~$42–84/month at similar specs, but ~5 ms RTT to gprocurement.go.th (vs. ~30–45 ms from Singapore) — worth it only when crawler latency becomes a real bottleneck

Both migrations are a one-day job: `pg_dump`, `git pull`, `docker compose up`, repoint DNS. The Compose file is the only deployment unit, so there is no vendor lock-in cost being captured.

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
