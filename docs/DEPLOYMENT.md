# Deployment - Safe Operating Point

This is the **landing page** for production deployment guidance. For end-to-end setup (Lightsail provisioning, Caddy, DNS, OPN webhook wiring) see [`LIGHTSAIL_LOW_COST_LAUNCH.md`](LIGHTSAIL_LOW_COST_LAUNCH.md). This document defines the **only currently-supported runtime configuration** until the Phase 1 concurrency hardening work lands.

## Required configuration

| Env var | Required value | Why |
|---|---|---|
| `EGP_BACKGROUND_RUNTIME_MODE` | `external` | Run the discovery dispatch loop as a standalone process so a 3-hour `proc.communicate()` cannot freeze the API event loop. |
| `EGP_DISCOVERY_WORKER_COUNT` | `1` | Keep single-worker mode until PR-03 is observed cleanly and host-level rate limiting ships. See "When worker_count can increase" below. |
| `EGP_DISCOVERY_LEASE_SECONDS` | `60` | Renewable ownership window for a claimed discovery job. An executor crash makes the job reclaimable after this window instead of leaving stale work stuck forever. |
| `EGP_DISCOVERY_LEASE_HEARTBEAT_SECONDS` | `20` | Renewal interval while a worker subprocess is active. It must be positive and shorter than the lease. |
| `EGP_BROWSER_CDP_PORT_BASE` | `9222` | First Chrome remote-debugging port available for discovery workers. |
| `EGP_BROWSER_CDP_PORT_RANGE` | `200` | Number of deterministic per-run CDP ports reserved on each host. |
| `EGP_BROWSER_PROFILE_ROOT` | `~/.egp/profiles` | Root for per-run Chrome user-data directories; keep this outside synced folders. |
| `EGP_EGP_SITE_ERROR_THRESHOLD` | `2` | Open the host-shared e-GP circuit after repeated site-error toasts. |
| `EGP_EGP_SITE_ERROR_BASE_SECONDS` | `300` | Initial cooldown after the site-error threshold is reached. |
| `EGP_EGP_SITE_ERROR_MAX_SECONDS` | `1800` | Cap exponential site-error cooldowns at 30 minutes. |

Both compose files in this repo (`docker-compose.yml`, `docker-compose-localdev.yml`) default to the safe worker-count value. The browser isolation env vars have code defaults, but production should set them explicitly so operators know which host ports and profile root are reserved. Do not raise `EGP_DISCOVERY_WORKER_COUNT` in production until the prerequisites in [When worker_count can increase](#when-worker_count-can-increase) are met.

## Process topology

The production compose stack runs the discovery dispatcher as a separate service:

- `api` - serves HTTP, `EGP_BACKGROUND_RUNTIME_MODE=external` disables the embedded dispatch loop.
- `discovery-executor` - runs `python -m egp_api.executors.discovery_dispatch`, claims discovery jobs from the outbox, spawns one worker subprocess per job.
- `webhook-executor` - runs `python -m egp_api.executors.webhook_delivery` for outbound webhook delivery.

This is implemented as the `api`, `discovery-executor`, and `webhook-executor` services in [`docker-compose.yml`](../docker-compose.yml).

## Renewable claims and typed failures

Every claimed `discovery_jobs` row receives a unique claim token and expiring lease. The
dispatcher renews that lease while its worker subprocess is alive. Only the current,
unexpired token may mark the job dispatched, retrying, or failed; a late process from an
older claim is rejected. If an executor dies, another executor can reclaim the row after
`lease_expires_at` instead of treating the old `processing_started_at` value as permanent
ownership.

Keep the heartbeat comfortably below the lease duration. A 20-second heartbeat and 60-second
lease tolerate a missed renewal while bounding crash recovery to about one minute. Transient
renewal errors are retried until the last confirmed lease expires. A confirmed stale token or
expired lease cancels the worker process group, including Chrome/Xvfb, before releasing its
browser-profile lock. Raising the worker timeout does not require raising the lease because
ownership is renewed throughout the crawl.

Dispatch outcomes now persist stable `last_error_code` values separately from human-readable
`last_error`. Pre-dispatch pauses likewise return an exact blocker (`circuit_open`,
`profile_busy`, `profile_warm_retry`, or `profile_operator_action_required`) without claiming
work. Use these codes for automation and dashboards; retain the free-form error only for
operator detail. The database and repository both reject values outside the shared failure-code
vocabulary.

Migration `032` protects an old-version in-flight row with a sentinel lease lasting through the
remainder of the legacy three-hour subprocess timeout. For a clean rollout, stop and drain all
old API-embedded and standalone discovery executors before applying the migration, then start only
the new lease-aware executor. Do not run mixed versions deliberately; the sentinel is a crash-safe
rollout guard, not a substitute for draining.

## Browser isolation

Each discovery worker subprocess receives a deterministic browser configuration derived from its run ID:

- `browser_cdp_port = EGP_BROWSER_CDP_PORT_BASE + sha256(run_id) % EGP_BROWSER_CDP_PORT_RANGE`
- `browser_profile_dir = EGP_BROWSER_PROFILE_ROOT / run_id`

The dispatcher removes the per-run profile directory after the worker exits. Cleanup refuses to delete paths outside `EGP_BROWSER_PROFILE_ROOT`, and cleanup failures are logged without changing the worker result.

## When `worker_count` can increase

Before per-run browser isolation shipped, `apps/worker/src/egp_worker/browser_discovery.py` used the default CDP port `9222` and Chrome user-data-dir `~/download/TOR/.browser_profile`. With `EGP_DISCOVERY_WORKER_COUNT > 1` on a single host and shared browser settings:

1. Worker A launches Chrome on port 9222 with the shared profile dir.
2. Worker B launches Chrome with the same `--user-data-dir`; Chrome's profile singleton lock forwards Worker B's launch to Worker A's running process, and Worker B's `--remote-debugging-port=9222` is ignored.
3. Worker B's Playwright `connect_over_cdp("http://127.0.0.1:9222")` connects to **Worker A's browser**.
4. Two crawl jobs silently drive one browser, causing wrong-tenant attribution and mixed downloads.

PR-03 removes that specific collision by assigning per-run ports and profile dirs. Keep `EGP_DISCOVERY_WORKER_COUNT=1` for the first PR-03 observation window, then pilot `2` on one host only after confirming no orphan Chrome PIDs or profile-root growth.

Raise `EGP_DISCOVERY_WORKER_COUNT` above 1 broadly **only after all three** of these have shipped and been observed in production for 48h+:

1. Per-worker browser isolation (unique CDP port + unique Chrome user-data-dir per spawn).
2. Host-level rate limiter against `gprocurement.go.th` with exponential backoff + circuit breaker.
3. Observability metrics for `egp_worker_subprocess_count`, `egp_egp_request_total`, and `egp_dispatch_duration_seconds`.

See the launch-readiness rollout plan tracked in `coding-logs/` for the gating criteria per PR.

## PR-00 deploy observation gate

After deploying this safe operating point, observe for 24h before shipping the next PR.

Watch:

- API p99 latency during at least one live crawl.
- Exactly one Chrome process per host:

```bash
ps aux | grep -c "Chrome.*remote-debugging-port"
```

Rollback trigger:

- API p99 latency exceeds the pre-deploy baseline by more than 50%.

Next-PR gate:

- Exactly one Chrome process is confirmed during at least one live crawl.

## Rollback

If the external dispatcher misbehaves and you need to fall back to embedded mode temporarily:

```bash
docker compose --env-file .deploy/egp.env stop webhook-executor discovery-executor
# edit .deploy/egp.env: set EGP_BACKGROUND_RUNTIME_MODE=embedded
docker compose --env-file .deploy/egp.env up -d api
```

**Do not run the external executor services while the API is in embedded mode**. Both will compete for the same outbox jobs.

Full rollback procedure: [`LIGHTSAIL_LOW_COST_LAUNCH.md` Rollback to embedded mode](LIGHTSAIL_LOW_COST_LAUNCH.md#rollback-to-embedded-mode).
