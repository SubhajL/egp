# Vercel Deployment Runbook

This runbook covers deploying the `apps/web` Next.js frontend to **Vercel
Hobby (free)** while the backend stays on AWS Lightsail. The in-Compose
`web` service is gated behind a `profiles: ["single-host"]` flag so the
default `docker compose up -d` does not start it.

> **Status:** shipped in PR-D of the deployment-readiness initiative.
> Pairs with [`deploy/.env.production.example`](../deploy/.env.production.example)
> (PR-B) and [`docs/LIGHTSAIL_LOW_COST_LAUNCH.md`](./LIGHTSAIL_LOW_COST_LAUNCH.md).

---

## 1. When to use Vercel vs single-host Compose

| Mode | When to use | Frontend | Compose command |
|---|---|---|---|
| **Vercel** (default) | Production launches. Marketing traffic spikes won't touch the API VM. | Vercel Hobby (free) | `docker compose up -d` (does NOT start `web`) |
| **Single-host** | Dev environments and tiny low-budget launches. | In-Compose `web` service on the API VM | `docker compose --profile single-host up -d` |

The repo ships with the Vercel-mode default. Switching to single-host
is just the `--profile single-host` flag.

---

## 2. One-time Vercel project setup

### 2.1 Import the project

1. Sign into <https://vercel.com> with the GitHub account that owns the repo.
2. **Add New → Project → Import Git Repository** → pick `SubhajL/egp`.
3. Configure the project:
   - **Framework Preset**: `Next.js` (auto-detected)
   - **Root Directory**: `apps/web` (set this in the Vercel UI — it
     cannot be configured via `vercel.json`)
   - **Build & Output Settings**: leave defaults (the values are
     pulled from `apps/web/vercel.json` — install: `npm ci`, build:
     `rm -rf .next && next build`, output: `.next`)
   - **Node.js Version**: `24.x` (Vercel default at time of writing)

### 2.2 Environment variables

In **Settings → Environment Variables**, add the following. Set each
for the three environments (Production, Preview, Development) unless
otherwise noted.

| Key | Production value | Preview | Required? |
|---|---|---|---|
| `NEXT_PUBLIC_EGP_API_BASE_URL` | `https://api.example.com` | same as prod | **Yes** |
| `NEXT_PUBLIC_SITE_URL` | `https://app.example.com` | leave blank or use Vercel's `${VERCEL_URL}` | **Yes** |
| `NEXT_PUBLIC_EGP_EXPLORER_BASE_URL` | `https://app.example.com/explorer` | as above | Optional |
| `NEXT_PUBLIC_EGP_TENANT_ID` | leave blank (logged-in users get their own tenant) | leave blank | Optional — only useful for the logged-out demo browse |

> **Important:** Vercel inlines `NEXT_PUBLIC_*` vars into the build at
> compile time. Changing any of these requires a redeploy with
> **"Use existing build cache: OFF"** to bust the cache, otherwise the
> stale value remains in the bundle.

### 2.3 Custom domain

1. **Settings → Domains → Add** → enter your app domain (e.g.
   `app.example.com`).
2. Vercel will give you a CNAME target (e.g. `cname.vercel-dns.com`).
3. In your DNS provider (we recommend Cloudflare DNS), add a CNAME
   record for `app.example.com` pointing to that target. **Proxy can
   stay ON** for Cloudflare unless you need raw IP access.
4. Vercel auto-provisions a Let's Encrypt cert.

The Lightsail-hosted API stays on `api.example.com`; that DNS goes to
the Lightsail static IP, NOT to Vercel.

### 2.4 Branch settings

- **Production Branch**: `main`
- **Preview Branches**: all other branches automatically get a preview
  deploy at `https://<branch-name>-<project>-<team>.vercel.app`.

---

## 3. CORS and cookie configuration

The frontend at `app.example.com` calls the API at `api.example.com`
directly (verified by `apps/web/src/lib/api.ts:155-167`). This is a
**cross-origin** request, so the API must allow it.

### 3.1 Production CORS

In your production env file (`/etc/egp/egp.env`), set:

```bash
EGP_WEB_ALLOWED_ORIGINS=https://app.example.com
```

### 3.2 Preview-deploy CORS (optional)

To let Vercel preview URLs (`https://<branch>-<project>-<scope>.vercel.app`)
hit the API, set the regex override. **Scope the regex tightly to your
project's Vercel preview pattern** — a broad regex would let any other
vercel.app subdomain (including unrelated/malicious sites) receive
credentialed CORS responses.

Find your scope by opening any preview deployment URL — it will look
like `https://<branch>-egp-<your-scope>.vercel.app`. Use that scope in
the regex:

```bash
# CORRECT — tight scope to YOUR project/team
EGP_WEB_ALLOW_ORIGIN_REGEX=^https://[a-z0-9-]+-egp-<your-scope>\.vercel\.app$
```

**DO NOT use** the loose form `^https://[a-z0-9-]+\.vercel\.app$` — the
API reflects the origin with `Access-Control-Allow-Credentials: true`
(see `apps/api/src/egp_api/bootstrap/middleware.py:64`), so a broad
regex paired with `SameSite=None` cookies would let any
`anything.vercel.app` page issue authenticated requests against your
API. Always scope by project name AND team/scope slug.

The API treats the regex as an additive allow-list — any origin
matching either the literal list (`EGP_WEB_ALLOWED_ORIGINS`) or the
regex (`EGP_WEB_ALLOW_ORIGIN_REGEX`) passes CORS.

### 3.3 Cookies

The API's session cookies are scoped to `api.example.com` (host-only,
not `Domain=.example.com`). The frontend at `app.example.com` calls
the API with `credentials: "include"` (cross-origin).

For cross-origin cookie flow to work, you MUST set BOTH:

```bash
EGP_SESSION_COOKIE_SECURE=true       # required for SameSite=None per browser rules
EGP_SESSION_COOKIE_SAMESITE=none     # required for cross-origin cookie flow
```

The production env template defaults `EGP_SESSION_COOKIE_SAMESITE=lax`
(which is correct for single-host deploys but **blocks cross-origin
cookies** in Vercel mode). Override it to `none` in
`/etc/egp/egp.env` for Vercel-mode launches.

Verify your settings actually wire through to the cookie by inspecting
the `Set-Cookie` header on the API's login response — it should
include `SameSite=None; Secure`.

**You only need a `Domain=.example.com` cookie configuration if** the
app host (`app.example.com`) itself needs to read the session cookie
from JavaScript — which the current flow does not. Defer this change
unless adding cross-host SSO.

---

## 4. Cost and limits (Vercel Hobby)

As of 2026-05, Hobby plan limits:

- **Bandwidth**: 100 GB / month "Fast Data Transfer"
- **Serverless function invocations**: 1,000,000 / month
- **Build minutes**: 6,000 / month
- **Build concurrency**: 1

**Personal-use clause**: the Hobby plan is documented as for personal,
non-commercial use. Verify your traffic plan against Vercel's current
terms; for serious commercial traffic, upgrade to Pro ($20/mo per
team member) before launch.

Verify current limits at <https://vercel.com/docs/limits/overview>.

### When to upgrade to Pro

Upgrade when:
- Bandwidth approaches 100 GB/month (Pro: 1 TB included)
- You need preview-deploy password protection
- Marketing campaigns are expected to spike build minutes
- A team beyond one operator needs access

---

## 5. Day-2 operations

### 5.1 Rolling out a frontend change

1. Push to `main` (or merge a PR) → Vercel auto-builds + deploys.
2. Wait for the green check on the deployment.
3. Verify on `https://app.example.com` (your custom domain) within 60s
   of "ready" status.

### 5.2 Rollback

Vercel keeps every deployment. To roll back:

1. **Deployments tab** → find the last-known-good deployment.
2. **... menu → "Promote to Production"** → confirm.

Rollback is near-instant (DNS doesn't change; Vercel just swaps
the active build).

### 5.3 Redeploy with cache bust (e.g. after env-var change)

1. **Deployments → latest → ... → Redeploy**
2. **Uncheck** "Use existing Build Cache"
3. Confirm.

---

## 6. Switching between Vercel and single-host modes

### Vercel mode (default)

```bash
# Backend on Lightsail (no `web` in compose)
docker compose --env-file /etc/egp/egp.env up -d
# DNS:
#   app.example.com → CNAME to Vercel
#   api.example.com → A record to Lightsail static IP
```

### Single-host mode

```bash
# Backend + frontend on the same VM
docker compose --env-file /etc/egp/egp.env --profile single-host up -d
# DNS:
#   app.example.com → A record to Lightsail static IP (Caddy handles routing)
#   api.example.com → same IP, different Caddy host block
```

The Caddyfile at `deploy/caddy/Caddyfile` has host blocks for both
domains. In Vercel mode the `app.example.com` block is dead code (DNS
doesn't point there), and in single-host mode it's active.

---

## 7. Common gotchas

| Symptom | Likely cause | Fix |
|---|---|---|
| Frontend loads but API calls 404 | `NEXT_PUBLIC_EGP_API_BASE_URL` not set in Vercel UI | Set the var; redeploy with cache OFF |
| Preview deploys fail CORS | `EGP_WEB_ALLOW_ORIGIN_REGEX` not set on API | Set the regex per §3.2 |
| 502 on `app.example.com` after switching to Vercel | DNS still points to Lightsail | Update DNS CNAME to Vercel target |
| Vercel build fails with `Cannot find module 'next'` | Vercel can't find package.json under Root Directory | Confirm Root Directory is `apps/web` in Vercel UI |
| Stale value in browser despite new deploy | Build cache reused stale env var | Redeploy with "Use existing Build Cache" OFF |
| Vercel deploy succeeds but app shows old code | Browser cache | Hard-reload (Cmd-Shift-R / Ctrl-Shift-R) |

---

## 8. Reference: what `apps/web/vercel.json` does

```json
{
  "framework": "nextjs",        # Auto-detect Next.js handlers
  "installCommand": "npm ci",   # Deterministic install
  "buildCommand": "rm -rf .next && next build",
  "outputDirectory": ".next",
  "regions": ["sin1"],          # Singapore (matches Lightsail Singapore RTT)
  "headers": [...]              # HSTS + X-Frame-Options + nosniff + Permissions-Policy
}
```

Notable: `env` is intentionally omitted. Vercel UI is the source of
truth for env vars; committing them to `vercel.json` would either leak
secrets or commit placeholders that get overridden anyway.

`redirects` and `rewrites` are also omitted. The frontend calls the API
directly at `NEXT_PUBLIC_EGP_API_BASE_URL` (no `/api/*` proxy is
needed). Only the inline `apps/web/src/app/api/inquiry/route.ts` Next
route is hosted on Vercel; everything else is backend.

---

## 9. Disaster scenarios

- **Vercel outage**: switch DNS for `app.example.com` to the Lightsail
  IP and run `docker compose --profile single-host up -d`. Set
  `NEXT_PUBLIC_EGP_API_BASE_URL` in the env file as the in-Compose
  build args read it.
- **Lightsail outage**: frontend stays up on Vercel but shows API errors;
  set a maintenance page in Vercel by redeploying with an env var
  `NEXT_PUBLIC_MAINTENANCE_MODE=true` and gating the layout. (Not
  implemented in PR-D; flagged for follow-up if needed.)
- **Both down**: see `docs/BACKUP_AND_RESTORE.md` §5 (Disaster recovery
  — full restore to a new host).
