# Deployment - Safe Operating Point

This is the **landing page** for production deployment guidance. For end-to-end setup (Lightsail provisioning, Caddy, DNS, OPN webhook wiring) see [`LIGHTSAIL_LOW_COST_LAUNCH.md`](LIGHTSAIL_LOW_COST_LAUNCH.md). This document defines the **only currently-supported runtime configuration** until the Phase 1 concurrency hardening work lands.

## Required configuration

| Env var | Required value | Why |
|---|---|---|
| `EGP_BACKGROUND_RUNTIME_MODE` | `external` | Run the discovery dispatch loop as a standalone process so a 3-hour `proc.communicate()` cannot freeze the API event loop. |
| `EGP_DISCOVERY_WORKER_COUNT` | `1` | Per-spawn browser isolation is not yet implemented. See "Why worker_count must stay at 1" below. |

Both compose files in this repo (`docker-compose.yml`, `docker-compose-localdev.yml`) default to these values. Do not override them in production until the prerequisites in [Why worker_count must stay at 1](#why-worker_count-must-stay-at-1) are met.

## Process topology

The production compose stack runs the discovery dispatcher as a separate service:

- `api` - serves HTTP, `EGP_BACKGROUND_RUNTIME_MODE=external` disables the embedded dispatch loop.
- `discovery-executor` - runs `python -m egp_api.executors.discovery_dispatch`, claims discovery jobs from the outbox, spawns one worker subprocess per job.
- `webhook-executor` - runs `python -m egp_api.executors.webhook_delivery` for outbound webhook delivery.

This is implemented as the `api`, `discovery-executor`, and `webhook-executor` services in [`docker-compose.yml`](../docker-compose.yml).

## Why `worker_count` must stay at 1

`apps/worker/src/egp_worker/browser_discovery.py` currently hardcodes CDP port `9222` and Chrome user-data-dir `~/download/TOR/.browser_profile`. The API dispatcher at `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` does not override either when spawning workers. With `EGP_DISCOVERY_WORKER_COUNT > 1` on a single host:

1. Worker A launches Chrome on port 9222 with the shared profile dir.
2. Worker B launches Chrome with the same `--user-data-dir`; Chrome's profile singleton lock forwards Worker B's launch to Worker A's running process, and Worker B's `--remote-debugging-port=9222` is ignored.
3. Worker B's Playwright `connect_over_cdp("http://127.0.0.1:9222")` connects to **Worker A's browser**.
4. Two crawl jobs silently drive one browser, causing wrong-tenant attribution and mixed downloads.

Until per-worker CDP port + per-spawn profile dir are plumbed through the dispatcher payload (rollout-plan Item 2), the only safe value is `EGP_DISCOVERY_WORKER_COUNT=1`.

## When the safe operating point can be relaxed

Raise `EGP_DISCOVERY_WORKER_COUNT` above 1 **only after all three** of these have shipped and been observed in production for 48h+:

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
