# Coding Log: Launch-Readiness Week Summary (7-Day Roll-Up)

## Scope (2026-05-26 09:21:17)

Roll-up of all work merged between 2026-05-19 and 2026-05-26. This week landed the full PR-00 → PR-08 concurrency / observability / admission-control hardening series, plus operational tooling and deployment-doc corrections that make the codebase launch-ready. Future sessions can pick up directly from the "Pending / Next Up" section.

---

## Headline narrative

Going into this week, the codebase had a single-host runtime that worked but had several known fragility points: an in-process discovery dispatcher that could freeze the API event loop, no per-worker browser isolation (any `EGP_DISCOVERY_WORKER_COUNT > 1` silently caused cross-tenant attribution because workers shared a Chrome profile lock), no host-level e-GP rate limiter, race-prone project/document upserts under concurrent crawls, no fair-claim guarantee across tenants, no per-tenant admission cap on inflight runs, and no Prometheus metrics. All of those landed this week as a sequenced PR series. On top of that, two operational scripts and three deployment-doc updates shipped, leaving the codebase positioned for an initial production launch on AWS Lightsail Singapore with Vercel frontend.

---

## PR-00 → PR-08 hardening series

Merged 2026-05-23 → 2026-05-24. All shipped, observed locally, tests green (final state: 616/0). Detailed coding logs already exist in `coding-logs/` for each PR; this section is the index.

| PR | Commit | Branch | Coding-log file | Purpose |
|---|---|---|---|---|
| **PR-00** | 72762939 | `chore/p0-safe-discovery-worker-default` | (none — config only) | Default `EGP_DISCOVERY_WORKER_COUNT=1`, `EGP_BACKGROUND_RUNTIME_MODE=external`; carve out single-host safe operating point |
| **PR-01** | e571a9f1 | `feat/observability-metrics` | `2026-05-23-11-58-54 Coding Log (observability-metrics).md` | Prometheus middleware in API, worker metrics, `/metrics` endpoint, Grafana dashboard JSON + alert YAML |
| **PR-02** | 186bbf3a | `fix/dispatcher-event-loop-unblock` | `2026-05-23-12-23-22 Coding Log (dispatcher-event-loop-unblock).md` | Wrap `run_discovery_dispatch_once` in `asyncio.to_thread`; convert route-kick paths to wake-signal write |
| **PR-03** | 265258cf | `feat/per-worker-browser-isolation` | `2026-05-23-21-07-06 Coding Log (per-worker-browser-isolation).md` | Deterministic per-run CDP port + profile dir; `finally`-block cleanup; new env vars `EGP_BROWSER_CDP_PORT_BASE/RANGE`, `EGP_BROWSER_PROFILE_ROOT` |
| **PR-04** | 1752f18a | `fix/project-upsert-on-conflict` | `2026-05-24-06-05-09 Coding Log (project-upsert-on-conflict).md` | `INSERT ... ON CONFLICT (tenant_id, canonical_project_id) DO UPDATE`; alias + status_events `DO NOTHING`; migration `021_project_status_events_dedup.sql` |
| **PR-05** | 4a2552b0 | `fix/document-upsert-on-conflict` | `2026-05-24-06-26-50 Coding Log (document-upsert-on-conflict).md` | `ON CONFLICT DO NOTHING` for documents; orphan blob cleanup if write wins race but DB insert loses |
| **PR-06** | b589a02c | `feat/egp-rate-limiter` | `2026-05-24-06-40-04 Coding Log (egp-rate-limiter).md` | `FileLockRateLimiter` (token bucket) + exponential backoff with jitter + circuit breaker; wired into `browser_discovery.py` + `browser_downloads.py` |
| **PR-07** | b25f9e0f | `feat/fair-discovery-claim` | `2026-05-24-07-02-42 Coding Log (fair-discovery-claim).md` | `ROW_NUMBER() OVER (PARTITION BY tenant_id ORDER BY next_attempt_at)` in `claim_pending_discovery_jobs` |
| **PR-08** | 3b34abf6 | `feat/tenant-admission-control` | `2026-05-24-08-45-58 Coding Log (tenant-admission-control).md` | Migration `022_tenant_concurrent_caps.sql` adds `max_concurrent_runs` + `max_queued_keywords` to `tenant_entitlements`; `check_runs_admission()` gates `queue_active_discovery_jobs`; 429 with structured payload + UI "queued" badge |

**Net effect**: `EGP_DISCOVERY_WORKER_COUNT=1` is now the production safe operating point. Ramping past 1 is gated on operational evidence (see "Next-PR gate" in the rollout plan), but the *code* supports up to N workers cleanly.

**Where to find the rollout plan in context**: the user pasted a 400-line PR-by-PR Rollout Sequence spec into the conversation that originated this work; not committed to repo. Key constants:
- Safe RPS default: `EGP_EGP_RPS=0.5`, `EGP_EGP_BURST=1`
- Circuit threshold: `EGP_EGP_CIRCUIT_429_THRESHOLD=5`, reset `EGP_EGP_CIRCUIT_RESET_SECONDS=300`
- Browser ports: base `9222`, range `200` → ports 9222–9421 reserved per host

---

## Post-hardening operational tooling

| PR | Commit | Branch | Purpose |
|---|---|---|---|
| **#112** | b9652720 | `fix/stale-test-assertions` | Fix 3 stale tests in `tests/phase1/test_projects_and_runs_api.py` and `tests/phase3/test_payment_links.py`. Two missed `_seed_active_profile_keyword(...)` after the entitlement-strictening from PR #97 (2026-05-18); one had `keyword_limit == 5` for monthly_membership which became unlimited in PR #102 (2026-05-21). 613/3 → **616/0**. |
| **#113** | 4990d2ad | `chore/launch-gate-checker` | `scripts/check_launch_gates.sh` — one-shot Mode A checker: hits `/metrics`, counts Chrome PIDs, profile dirs, runs cross-tenant SQL, reads PR-04/05/06/08 metric outcomes. PASS/FAIL/SKIP per gate, exits 1 on any fail. Has `--probe-admission` flag for the functional 202→429 probe. |
| **#114** | e6c86de5 | `chore/mode-c-scaffolding` | `scripts/mode_c/{egp_stub_server.py, mode_c_full_run.py, circuit_open_smoke.py}` — local two-worker dry run with stdlib HTTP stub of gprocurement.go.th, exercises real `FileLockRateLimiter` + metric instrumentation. Used to validate rate-limiter engaging and circuit-breaker behavior before any prod `worker_count` ramp. |

**Validation receipts** (run during the session that produced these):
- All 9 `tests/concurrency/` tests pass in 1.85s
- Full suite (616 tests) passes in ~85s
- `mode_c_full_run.py` 60s clean-path run: wait_count 0→100, observed RPS 1.65 ≤ cap 2.0, 0 429s
- `mode_c_full_run.py` 45s with `STUB_BURST_429_EVERY=5`: 16 429s recorded, RPS still 1.60
- `circuit_open_smoke.py`: opens after 3 consecutive 429s with reset_in=5.00s, auto-closes after 5.5s
- Bounded Mode C with stubbed Popen: profile dirs (pre-populated with fake Chrome state files) deleted by dispatcher's `finally`-block under concurrent dispatch

---

## Deployment-doc updates

| PR | Commit | Branch | What changed |
|---|---|---|---|
| **#115** | 7fe23ac0 | `docs/lightsail-post-pr08-update` | Multiple updates to `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`: explicit `ap-southeast-1` (Singapore) region, Vercel-vs-in-Compose-`web` clarification, new pre-ramp validation section pointing at `check_launch_gates.sh` + `scripts/mode_c/`, new OPN cost + KYC timeline section, expanded upgrade path (off-box backups → Postgres → Hetzner/Bangkok-local). Initial sizing claim of "$24 = 4 GB" was wrong — fixed in #116. |
| **#116** | e2e49db6 | `docs/lightsail-bundle-pricing-fix` | Corrected Lightsail bundle/price mapping: $12 = 4 GB / 2 vCPU / 80 GB / 4 TB (cheapest viable); $24 = 8 GB / 2 vCPU / 160 GB / 5 TB (recommended for ramp). Added Thai THB cost table covering USD billing, ~1.5% Thai bank FX markup, conditional 7% Thai VAT. Approximate fixed monthly floor: ฿470 (4 GB) or ฿890 (8 GB). |

**Important context on doc trust**: `docs/LIGHTSAIL_LOW_COST_LAUNCH.md` now refers to "verify pricing at <https://aws.amazon.com/lightsail/pricing/>" because AWS adjusts bundle pricing periodically. The committed numbers reflect AWS's pricing as of 2026-05-24; verify before next purchase.

---

## Decisions made (worth re-reading in future sessions)

### Cloud platform
- **Decision**: AWS Lightsail Singapore $24/mo (8 GB) recommended; $12/mo (4 GB) as cheapest viable starting point
- **Why**: Predictable bundled pricing, generous transfer (4–5 TB), ~30–45 ms RTT to Bangkok, has docs-aligned upgrade path (Lambda OPN webhook, RDS migration), Singapore region closest to e-GP servers
- **Migration trigger**: if monthly Lightsail bill > ~$60, evaluate Hetzner Cloud Singapore CPX31 (~$14–16/mo at 4 GB / 4 vCPU / 20 TB) or Bangkok-local IDC if crawler latency to e-GP becomes blocking
- **Not chosen and why**: Fly.io/Railway/Render (don't fit Chromium + persistent profile + long subprocess model); Stripe Atlas Delaware C-corp (Thai-domestic SaaS doesn't justify $1.5–2k/yr US compliance overhead)

### Frontend
- **Decision**: Vercel Hobby (free) for production frontend; in-Compose `web` service is single-host-convenience only
- **Why**: Marketing/page-view spikes don't touch the VM; the workers' crawl load is gated by admission control regardless of viewer count

### Payments
- **Decision**: Stay with OPN; register a บริษัท จำกัด in parallel with infrastructure setup
- **Why**: OPN integration already exists in repo (`PaymentProvider` abstraction at `apps/api/src/egp_api/services/billing_service.py:14` with only OPN implemented), PromptPay-heavy customer base aligns with OPN's pricing (1.5% + ฿1.50 vs Stripe's 1.65%), T+1/T+2 settlement vs Stripe's T+7
- **Open question**: confirm with Omise sales directly whether individual accounts are eligible for SaaS recurring billing (likely "no" but should verify in one email)
- **OPN KYC docs needed**: DBD certificate, director ID + selfie, Thai bank statement, sample invoice. Timeline 5–10 business days.
- **VAT registration**: only required past ฿1.8M annual revenue; defer initially

### Worker ramp gating
- **Decision**: Do not raise `EGP_DISCOVERY_WORKER_COUNT` past 1 until `scripts/check_launch_gates.sh` is green for 48+ hours AND `scripts/mode_c/mode_c_full_run.py` validates the rate limiter and circuit breaker under sustained synthetic load
- **Why**: PR-03 (browser isolation) is the riskiest item — silent cross-tenant attribution is the worst-case failure mode
- **Ramp sequence**: 1 → 2 (one host pilot, 48h observation) → 4 (broader rollout)

---

## Pending / Next Up — deployment-readiness PR plan

The deployment-readiness audit (from this week's session) identified the following gaps. **None block code merging; all are pre-production-launch items.** Plan documented in detail in conversation history; summarized here for pickup.

### Critical-path PRs (estimated 10–15 hours total)

| PR | Branch | Est. lines | Est. work | Priority | What it ships |
|---|---|---|---|---|---|
| **PR-A** | `feat/postgres-backup-and-restore` | ~180 | 3–4 h | 🔴 Highest | `scripts/pg_backup.sh`, `scripts/pg_restore.sh`, `docs/BACKUP_AND_RESTORE.md`, smoke test, R2/S3 upload pattern, 14-day local + 30-day remote retention |
| **PR-B** | `docs/env-template-and-secret-rotation` | ~120 | 1–2 h | 🟡 | `deploy/.env.production.example` (all 36 `EGP_*` vars grouped by required/recommended/optional), `docs/SECRET_ROTATION.md` runbook for `EGP_JWT_SECRET`, `EGP_PAYMENT_CALLBACK_SECRET`, `EGP_INTERNAL_WORKER_TOKEN`, `EGP_OPN_WEBHOOK_SECRET`, `EGP_POSTGRES_PASSWORD` |
| **PR-C** | `feat/seed-first-admin-script` | ~150 | 2–3 h | 🟡 | `scripts/seed_first_admin.py` (non-interactive, idempotent, refuses to run if tenant already has >0 admins), `tests/operations/test_seed_first_admin.py` |
| **PR-D** | `feat/vercel-deployment-config` | ~100 | 1–2 h | 🟢 | `apps/web/vercel.json`, `docs/VERCEL_DEPLOYMENT.md`, move Compose `web` service behind `profiles: [single-host]` flag |
| **PR-E** | `feat/observability-stack-deployment` | ~200 | 3–4 h | 🟡 | `docker-compose.monitoring.yml` (overlay), `deploy/prometheus.yml`, Grafana provisioning, dashboard auto-import, SSH-tunnel pattern docs, Grafana Cloud Free alternative |

### Optional PRs (only if Stripe is chosen)

| PR | Branch | Est. lines | Est. work | What it ships |
|---|---|---|---|---|
| **PR-F** | `feat/stripe-payment-provider-class` | ~350 | 6–8 h | `StripeProvider` implementing existing `PaymentProvider` abstract interface, `EGP_STRIPE_*` env vars, tests mirroring OPN |
| **PR-G** | `feat/stripe-webhook-route` | ~200 | 3–4 h | New `POST /v1/billing/providers/stripe/webhooks`, end-to-end integration test, `docs/STRIPE_DEPLOYMENT.md` |

**Stripe decision is open**: pending answer from Omise sales on individual account eligibility. If OPN works for individuals (unlikely for SaaS), the company-registration delay is avoidable. If OPN requires a company (likely), the 2–4 week บริษัท จำกัด registration runs in parallel with closed beta on test mode.

### Non-PR action items

- **OPN live KYC**: start ASAP if not already; 5–10 business day timeline is on the critical path
- **บริษัท จำกัด registration**: ~฿7,000–20,000, 2–4 weeks if doing DIY; longer if via a firm
- **Lightsail provision**: do day-of-launch, not before (~15 min setup)
- **DNS**: Cloudflare DNS with proxy OFF for `api.*` (anti-bot can break OPN webhooks); proxy can be ON for `app.*`
- **OPN dashboard config**: swap webhook URL from Cloudflare tunnel to `https://api.yourdomain.com/v1/billing/providers/opn/webhooks` on launch day

### Files / locations referenced in pending plan

- `apps/api/src/egp_api/services/payment_provider.py` — abstract interface (Stripe adapter would sit alongside the OPN implementation)
- `apps/api/src/egp_api/services/billing_service.py:14` — payment provider injection point
- `apps/api/src/egp_api/bootstrap/services.py` — provider selection from `EGP_PAYMENT_PROVIDER` env var
- `apps/api/src/egp_api/routes/billing.py` — current OPN webhook route (Stripe webhook would mirror)
- `deploy/caddy/Caddyfile` — already correct; no edits needed
- `docker-compose.yml` — production stack, may need `profiles:` flag added for `web` service in PR-D

---

## Working-tree state at log time

- Branch: `main`
- HEAD: `e2e49db6` (PR #116)
- Tests: 616 passed / 0 failed (last full run from PR #112 lineage)
- Lint: ruff clean, tsc clean, eslint clean
- Uncommitted: two pre-existing `coding-logs/*.md` modifications (unrelated to PR work) and untracked `artifacts/` + `egp-dev-logs/` directories — those have been in the tree all week, not blocking anything

---

## How to resume in a new session

1. Read this file (you're doing that now) and any specific per-PR coding-log files referenced in the table above
2. Check `git log --since='2026-05-26' --pretty=format:'%h %ad %s' --date=short` to see anything that landed after this log
3. Pick a PR from "Critical-path PRs" — recommended order: **PR-A first** (backup is the highest-risk gap)
4. The g-submit workflow (which produced #112–#116) is what should be used for each — sync, edit, `gt create`, `gt submit --publish`, `gh pr merge --squash --admin --delete-branch`, `gt sync`

---

## Open questions for the user (next time)

1. **OPN individual vs company**: has the email/call to Omise sales happened? Answer drives whether to start PR-F/PR-G work or finish the OPN-only critical path.
2. **Lightsail bundle preference**: $12/mo (4 GB) for cheapest launch, or $24/mo (8 GB) for ramp headroom? Affects monthly burn ฿470 vs ฿890.
3. **Backup destination**: Cloudflare R2 free tier (10 GB free) is the recommended target for PR-A; need to confirm or pick a different backup destination before starting.
4. **Closed beta timing**: targeting which week for first real-user exposure? Drives whether to do PR-A through PR-E sequentially or in parallel.
