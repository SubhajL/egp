# Remote Local Crawler (Track C) — temporary "www" bridge

The e-GP site is gated by Cloudflare Turnstile/PAT: only a **real Mac Chrome with a
warmed persistent profile** passes attestation. Headless/containerized Chrome on
Lightsail returns `401` and retrieves nothing. So for the temporary "www" launch we
run the **crawler on the operator's Mac**, while the **API/control-plane stays on
Lightsail** and the **frontend on Vercel**.

This is **Track C** in [`TRACKS.md`](../TRACKS.md) — the single, deliberate, *guarded*
exception to the "local tools never touch production" rule.

> ⚠️ **This writes PRODUCTION.** `.env.remotecrawl` points at the live database and
> control-plane. The runner refuses to start unless every safety rail is in place.

---

## How it fits together

```
Vercel UI ──HTTPS──▶ Lightsail API (Caddy/TLS)
  click "recrawl"        POST /v1/rules/recrawl → queue_active_discovery_jobs()
                              │
                              ▼
                      discovery_jobs (PRODUCTION Postgres)  ◀── shared durable queue
                              ▲
   Mac dispatch executor ─────┘  claims pending rows  (the Mac is the SOLE claimer)
   scripts/run_remote_crawl.sh watch
        │ spawns subprocess (stdin JSON)
        ▼
   egp_worker.main ──CDP──▶ REAL Mac Chrome (warmed persistent profile) ──▶ gprocurement.go.th
        ├─ runs / profiles / tasks ─────▶ PRODUCTION Postgres   (via SSH tunnel, required)
        ├─ project events ──HTTPS /internal/worker/projects/* (X-EGP-Worker-Token) ──▶ Lightsail API
        └─ TOR documents ──HTTPS──▶ Cloudflare R2 (s3 backend; same bucket the API serves)
```

Why the Mac still needs the database: the worker is DB-coupled — `run_discover_workflow`
reads crawl profiles and writes `crawl_runs` / `crawl_tasks` / `projects` directly. The
HTTPS event sink (`ApiProjectEventSink`) only redirects *project-event* writes, so a live
production DB connection from the Mac is required. That connection is the **SSH tunnel**.

---

## Database topology

This setup uses **Topology A — SSH tunnel to the Lightsail Postgres**. The container
Postgres is published to the VM loopback (`127.0.0.1:15432`) and forwarded to the Mac
over SSH. Postgres is **never** exposed on a public interface.

(Topology B — a managed Postgres reachable directly over TLS with `sslmode=require`
(e.g. Neon, RDS) — is also supported by the guard; set `DATABASE_URL` to that
connection string and skip the tunnel.)

---

## One-time setup

> Deployment-specific values (server IP, Cloudflare account ID, domain) are kept in the
> operator's local notes, **not** in this public repo.

### Applying R2 + the tunnel to a box that predates #139 (override-file method)

PR #139 adds the R2 env passthrough to the base `docker-compose.yml`, and #138 adds
`docker-compose.pg-tunnel.yml`. If the box is on an **older** revision (e.g. `#136`)
you don't need a full upgrade — the image already has the boto3/`s3`
code, so just add an **untracked** `docker-compose.override.yml` (auto-merged by Compose,
no git drift, survives a later `git pull`):

```yaml
# /home/ubuntu/egp/docker-compose.override.yml
services:
  postgres:
    ports: ["127.0.0.1:15432:5432"]      # loopback only — tunnel target, never public
  api:
    environment: &r2
      S3_BUCKET: ${S3_BUCKET:-}
      AWS_ENDPOINT_URL_S3: ${AWS_ENDPOINT_URL_S3:-}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:-}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:-}
      AWS_DEFAULT_REGION: ${AWS_DEFAULT_REGION:-}
      SUPABASE_URL: ${SUPABASE_URL:-}
      SUPABASE_SERVICE_ROLE_KEY: ${SUPABASE_SERVICE_ROLE_KEY:-}
      SUPABASE_STORAGE_BUCKET: ${SUPABASE_STORAGE_BUCKET:-}
  discovery-executor:
    environment: *r2
```
```bash
cd /home/ubuntu/egp
sudo docker compose --env-file /etc/egp/egp.env config -q        # validate
sudo docker compose --env-file /etc/egp/egp.env up -d api postgres
docker exec egp-api-1 printenv AWS_ENDPOINT_URL_S3               # confirm the API got it
```
After a full deploy to #139+, delete the override (the base compose then carries these).

### Lightsail (control-plane only)

1. In `/etc/egp/egp.env` confirm:
   ```
   EGP_BACKGROUND_RUNTIME_MODE=external
   # Artifacts on Cloudflare R2 (s3 backend) — MUST match what the Mac uploads,
   # so the API can serve documents via signed URLs.
   EGP_ARTIFACT_STORE=s3
   S3_BUCKET=egp-documents
   AWS_ENDPOINT_URL_S3=https://<account>.r2.cloudflarestorage.com
   AWS_ACCESS_KEY_ID=…  AWS_SECRET_ACCESS_KEY=…  AWS_DEFAULT_REGION=auto
   #  ^ MUST be AWS_DEFAULT_REGION (not AWS_REGION) — it forces SigV4 presigned
   #    URLs; AWS_REGION=auto alone yields SigV2, which R2 rejects.
   EGP_INTERNAL_WORKER_TOKEN=…            # the Mac sends this as X-EGP-Worker-Token
   ```
2. Bring the stack up **without** the in-box crawler, **with** the tunnel overlay:
   ```bash
   cd /srv/egp
   docker compose --env-file /etc/egp/egp.env \
     -f docker-compose.yml -f docker-compose.pg-tunnel.yml \
     up -d --build --scale discovery-executor=0
   docker compose --env-file /etc/egp/egp.env ps discovery-executor   # → 0 replicas
   curl -fsS https://api.<domain>/health
   ```
   Scaling `discovery-executor=0` is **critical**: if the Lightsail executor runs it will
   claim jobs and crawl headless → Cloudflare `401`. The Mac must be the only crawler.
3. (Optional) Install the scheduled-enqueue timer so interval crawls keep getting queued
   even though the in-box executor is off:
   ```bash
   sudo cp deploy/systemd/egp-scheduled-enqueue.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now egp-scheduled-enqueue.timer
   ```
   This runs `python -m egp_api.executors.scheduled_discovery_enqueue` (DB-only, no
   browser) on the discovery-executor image. The per-tenant `crawl_interval_hours` still
   governs whether a tenant is actually due.

### Mac (the crawler)

1. Bootstrap the venv (`./scripts/bootstrap_python_env.sh`) and install Playwright/Chrome deps as usual.
2. Create the env file from the template and lock it down:
   ```bash
   cp .env.remotecrawl.example .env.remotecrawl
   chmod 600 .env.remotecrawl
   ```
   Fill in: `EGP_REMOTECRAWL_SSH_HOST`, the production `DATABASE_URL` (tunnel form
   `…@127.0.0.1:15432/egp`), `EGP_INTERNAL_API_BASE_URL=https://api.<domain>`,
   `EGP_INTERNAL_WORKER_TOKEN`, the R2 vars (`S3_BUCKET`, `AWS_ENDPOINT_URL_S3`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`), `EGP_BROWSER_CHROME_PATH`, and a
   persistent profile dir **outside** OneDrive/iCloud/Dropbox.
3. Validate — the guard fails closed on any missing/unsafe value:
   ```bash
   scripts/run_remote_crawl.sh check
   ```

---

## Daily operation

### Manual / on-demand

```bash
scripts/run_remote_crawl.sh tunnel        # terminal 1: SSH tunnel to prod Postgres
scripts/run_remote_crawl.sh warm-profile  # once, until Cloudflare clears
scripts/run_remote_crawl.sh crawl 5       # drain up to 5 pending prod jobs, then exit
# …or continuously:
scripts/run_remote_crawl.sh watch
```

### Always-on (launchd)

```bash
scripts/install_launchd.sh install     # tunnel + watcher auto-start at login, restart on crash
scripts/install_launchd.sh install --with-warm  # optional: also run keep-warm every 15 min
scripts/install_launchd.sh status
scripts/install_launchd.sh uninstall
```
By default two agents are installed: `com.egp.pg-tunnel` (the SSH tunnel) and
`com.egp.remote-crawl` (the watcher — run under `caffeinate -i` so the Mac never
idle-sleeps while actively watching). `com.egp.pg-warm` is optional; install it
only with `--with-warm` if you deliberately want a browser keep-warm every 15 min.
Logs: `~/Library/Logs/egp/{tunnel,crawl,warm}.log`.

### Keeping the profile warm (Cloudflare clearance)

"Warm" vs "cold" describes the **crawler's persistent profile**, not the e-GP
site. Cloudflare Turnstile issues a per-profile clearance (`cf_clearance`) that
**expires after tens of minutes**; on a cold/expired profile the search UI never
renders and a crawl fails with a `wait_for_selector` timeout on the Search button.

The default watcher does **on-demand pre-dispatch warm/preflight** instead of
opening Chrome every 15 minutes forever. When a pending job is dispatched in
persistent-profile mode, the dispatcher takes the same profile lock used by the
crawl, checks `<profile>/.egp-profile-state.json`, and warms only if the last
successful warm or crawl is older than
`EGP_BROWSER_WARMUP_STALE_AFTER_SECONDS` (default 1800 seconds). A successful
crawl refreshes that timestamp, so back-to-back jobs do not relaunch a warm
browser.

When explicitly installed with `scripts/install_launchd.sh install --with-warm`,
`com.egp.pg-warm` runs `run_remote_crawl.sh warm-profile` every 15 minutes to
refresh that clearance, so scheduled/triggered crawls are less likely to hit a cold profile.
It is **lock-safe**: `warm-profile` takes the *same* exclusive profile lock
(`<profile>/.egp-crawl.lock`, via `egp_crawler_core.profile_lock`) that a crawl
holds, so a heartbeat firing mid-crawl exits as a no-op (`WARMUP_SKIP`) instead
of launching a second Chrome on the profile (which would corrupt it). A running
crawl is itself keeping the profile warm, so skipping is correct.

> ⚠️ The **one-time initial** warm (and any warm after a full lapse — e.g. the
> Mac was off for hours) may need a human to solve a Cloudflare challenge: run
> `scripts/run_remote_crawl.sh warm-profile` once and clear it on screen. The
> timer only *refreshes* an already-valid clearance — it cannot solve an
> interactive challenge unattended.

### Triggering a crawl

From the Vercel UI, click **recrawl** or create/update a keyword profile. That calls
`POST /v1/rules/recrawl` (or `/v1/rules/profiles`), which enqueues `discovery_jobs`. The
Mac watcher claims and crawls them. Scheduled crawls are queued by the Lightsail timer.

---

## Safety model

`scripts/remote_crawl_guard.py` (unit-tested) refuses to run unless:

| Check | Requirement |
|---|---|
| Production ack | `EGP_REMOTECRAWL_PRODUCTION_ACK=I_UNDERSTAND_THIS_WRITES_PRODUCTION` |
| Event transport | `EGP_INTERNAL_API_BASE_URL` is `https://` |
| Artifacts | `EGP_ARTIFACT_STORE=s3` + `S3_BUCKET` + `AWS_ENDPOINT_URL_S3` (R2) + `AWS_ACCESS_KEY_ID/SECRET` (or `supabase` + its vars) |
| Browser | real `EGP_BROWSER_CHROME_PATH`, `EGP_BROWSER_PROFILE_MODE=persistent`, dir outside synced folders |
| Single-flight | `EGP_DISCOVERY_WORKER_COUNT=1` |
| Database | SSH-tunnel loopback port **or** TLS managed-Postgres URL (`sslmode=require`) — **never** `localhost:5434` |

The guard runs before every `crawl`/`watch`, including under launchd, so a misconfigured
environment can never auto-loop against the wrong database.

---

## Risks & rollback

- **Two crawlers racing** → verify `discovery-executor` shows 0 replicas; the Mac's
  persistent-profile flock prevents a second local worker.
- **Mac offline** → jobs sit `pending` (durable queue, no loss). A run left `running` after
  a mid-job crash can be reconciled manually in `crawl_runs`.
- **Wrong artifact store** → guard requires an API-served store (`s3`/R2 or `supabase`) and
  rejects `local`, so documents always land where the API can serve them.
- **Rollback** → `scripts/install_launchd.sh uninstall` (or stop `watch`), close the tunnel,
  and leave `discovery-executor=0` (crawling paused, control-plane intact). Reverting to
  in-box crawling means accepting the known Cloudflare `401`.
