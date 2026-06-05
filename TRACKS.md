# Two Tracks: localhost vs production

This repo runs on **two strictly separated tracks** so local experiments can never
touch production — plus one deliberate, **guarded** bridge (Track C) for the temporary
"www" setup where crawling must happen on a real Mac. Separation happens on three
axes — **code, config, data**.

| Axis | **Track A — localhost (your Mac)** | **Track B — production / upgrades** | **Track C — remote crawler (temp bridge)** |
|---|---|---|---|
| **Code** | run from a worktree; never commit runtime tweaks | `feat/*`,`fix/*` → PR → `main`; tag releases | prod-pinned code run natively on the Mac |
| **Run** | `scripts/run_local.sh` → `docker-compose-localdev.yml` + native crawler | Lightsail host: `docker-compose.yml`; Vercel: `apps/web` | `scripts/run_remote_crawl.sh` (guarded) + launchd; Lightsail runs API only (`discovery-executor` scaled to 0) |
| **Config** | `.env.localdev` (this repo, gitignored, **no secrets**) | `/etc/egp/egp.env` (Lightsail) + Vercel env UI | `.env.remotecrawl` (gitignored, **points at PRODUCTION**) |
| **Data** | Docker volume `egp_egp_pgdata` @ `localhost:5434`, artifacts on local FS | Lightsail Postgres + Cloudflare R2 (artifacts) | **PRODUCTION** Lightsail Postgres via SSH tunnel (`127.0.0.1:15432`) + Cloudflare R2 (artifacts) |
| **Auth/pay** | `EGP_AUTH_REQUIRED=true`, `mock_promptpay` | real auth + OPN/Stripe | reads/writes the real production control-plane |

### The one rule that prevents every mix-up
> **The localhost track and the production track never share an env file or a DB connection string.**
> Local tools only ever see `localhost:5434`. Production config lives only on the host + Vercel.

**Track C is the single, deliberate exception** — and it is fail-closed. `scripts/run_remote_crawl.sh`
refuses to start unless `scripts/remote_crawl_guard.py` confirms an explicit production
acknowledgement, an HTTPS API + Cloudflare R2 (s3) artifacts, a warmed single-flight Chrome profile,
and a DB target that is the SSH-tunnel loopback or a TLS managed-Postgres URL — **never** `localhost:5434`. It is the
exact inverse of `run_local.sh`'s localhost-only guard. See [`docs/REMOTE_LOCAL_CRAWLER.md`](docs/REMOTE_LOCAL_CRAWLER.md).

---

## Track A — run & crawl locally

```bash
scripts/run_local.sh up        # OrbStack + Docker stack (UI/API/DB), auth ON, isolated env
scripts/run_local.sh crawl 5   # one-shot native crawl (real Mac Chrome) of up to 5 queued keywords
scripts/run_local.sh watch     # continuous native crawler — keywords added in the UI auto-crawl
scripts/run_local.sh status
scripts/run_local.sh down
```

- UI: http://localhost:3002 · API: http://localhost:8010 · Postgres: `localhost:5434`
- The wrapper **always** passes `--env-file .env.localdev` and **never** reads the root `.env`.
- Crawling runs **natively** (real Chrome). The in-container `discovery-executor` is stopped on `up`
  because headless-in-Linux Chrome can't clear Cloudflare (identical to the Lightsail failure).

### Optional hardening — quarantine the prod-flavored root `.env`
The root `.env` holds production-style secrets and `docker compose` auto-reads it if you ever run
a bare `docker compose` command. The wrapper avoids that, but to remove the footgun entirely:
```bash
mv .env .env.production.local   # still gitignored (.env.*.local); nothing in the repo auto-loads it
```

---

## Track C — remote local crawler (temporary "www" bridge)

The crawler must run on a real Mac (Cloudflare Turnstile blocks headless/Lightsail Chrome), but the
API lives on Lightsail and the frontend on Vercel. Track C bridges them: the Mac is the **sole**
claimer of the production `discovery_jobs` queue and crawls with real Chrome, while Lightsail runs the
API as a pure control-plane.

```bash
cp .env.remotecrawl.example .env.remotecrawl && chmod 600 .env.remotecrawl   # then fill it in
scripts/run_remote_crawl.sh check          # fail-closed env validation
scripts/run_remote_crawl.sh tunnel         # SSH tunnel to prod Postgres (or run via launchd)
scripts/run_remote_crawl.sh warm-profile   # warm the persistent Chrome profile (once)
scripts/run_remote_crawl.sh watch          # claim + crawl the PRODUCTION queue
scripts/install_launchd.sh install         # always-on: tunnel + watcher as launchd agents
```

On Lightsail, bring the stack up **without** the in-box crawler so the Mac is the only crawler:
```bash
docker compose --env-file /etc/egp/egp.env \
  -f docker-compose.yml -f docker-compose.pg-tunnel.yml \
  up -d --scale discovery-executor=0
```
Full runbook: [`docs/REMOTE_LOCAL_CRAWLER.md`](docs/REMOTE_LOCAL_CRAWLER.md).

---

## Track B — GitHub branching, deploys, and versioning

### Branch model (trunk-based + tags — best for a small team)
- **`main` is always deployable.** Never push to it directly (CLAUDE.md rule).
- Work on short-lived branches: `feat/<x>`, `fix/<x>` → open a **PR** → CI (tests/lint/types) → **squash-merge** to `main`.
- Every PR gets an automatic **Vercel Preview URL** — that's your staging for the frontend.
- Test upgrades on **Track A** (localhost) before they reach `main`.

### Releases & how V0.1 stays separate from V0.x / x.x
Use **semantic version tags** on `main`. `0.x` = pre-1.0 (minor versions may break).

```bash
git tag -a v0.1.0 -m "First production release"   # tag the CURRENT live state
git push origin v0.1.0
```

- **Production is pinned to a tag, not bleeding-edge `main`.** `main` moves ahead toward `v0.2.0`
  while production keeps serving `v0.1.0`.
- **Upgrade flow:** merge tested work into `main` → when ready, `git tag -a v0.2.0` → deploy that tag.
- **Keeping a v0.1 line alive while building v0.2** (e.g. a customer pinned to it): cut a release
  branch from the tag and patch there —
  ```bash
  git switch -c release/0.1 v0.1.0     # hotfixes land here → tag v0.1.1, v0.1.2 …
  ```
  `main` continues toward `v0.2.0`; the two never collide.

### Deploying a version
- **Frontend (Vercel):** production = the `main` branch (or set Vercel's *Production Branch* to a
  `production` branch you fast-forward to a tag at release time). PRs = preview deploys automatically.
- **API/workers (Lightsail host):**
  ```bash
  ssh <host> 'cd /home/ubuntu/egp && git fetch --tags && git checkout v0.1.0 \
    && sudo docker compose --env-file /etc/egp/egp.env up -d --build'
  ```
  Upgrade = checkout the new tag + `up -d --build`. Rollback = checkout the previous tag.

### Mapping the two tracks to git worktrees
- **Track A (localhost)** = **this checkout** (`~/dev/egp`). It owns `.venv`, the Docker stack, and
  the local DB. Keep it on a stable ref and run `scripts/run_local.sh` here. The localdev stack uses
  fixed container names (`egp-postgres`, …), so only **one** local stack runs at a time — run it
  only from here.
- **Track B (upgrades)** = a separate worktree at `~/dev/egp-upgrades` (branch `develop`): make code
  changes, branch `feat/*`/`fix/*`, push, open PRs into `main`. Do **not** start the Docker stack
  there (container-name collision); it's for code + tests + PRs. Created with:
  ```bash
  git worktree add ~/dev/egp-upgrades -b develop   # then inside it: git switch -c feat/<x>
  git worktree list
  ```
