# Observability Runbook

This runbook covers the self-hosted Prometheus + Grafana monitoring
stack shipped as the `docker-compose.monitoring.yml` overlay. Pairs with
the production env template ([`deploy/.env.production.example`](../deploy/.env.production.example))
and the Lightsail launch guide
([`docs/LIGHTSAIL_LOW_COST_LAUNCH.md`](./LIGHTSAIL_LOW_COST_LAUNCH.md)).

> **Status:** shipped in PR-E of the deployment-readiness initiative.
> The monitoring overlay is **opt-in** — bring it up explicitly with
> `-f docker-compose.monitoring.yml` after the base stack is healthy.

---

## 1. What you get

| Component | Image | Purpose |
|---|---|---|
| Prometheus | `prom/prometheus:v3.11.3` | Scrapes the API's `/metrics` every 15s; 14-day local retention |
| Grafana | `grafana/grafana:11.4.0` | Auto-loads the pre-built "e-GP Observability Baseline" dashboard |

Both services bind to **`127.0.0.1` only** — no public exposure.
Operators access the UIs via SSH tunnel (§4).

### What the dashboard covers

The auto-loaded `e-GP Observability Baseline` dashboard (10 panels)
includes:

- Request rate (per route, 2xx vs 5xx split)
- p50/p95/p99 request latency
- Worker queue depth + run-status distribution
- Rate-limiter token availability + 429 count
- Tenant admission rejections (PR-08)

### What's NOT in PR-E

- **Worker `/metrics` endpoint**: workers update Prometheus counters
  in-process but do not yet expose an HTTP listener. Tracked as a
  follow-up; until then, worker metrics are visible only as
  side-effects on API-side metrics.
- **Node-exporter** (host CPU/memory/disk): can be added later as a
  second overlay; the launch baseline gets by on Lightsail's built-in
  host metrics.
- **Alertmanager**: dashboards alone for launch; pager wiring deferred.

---

## 2. Bring-up

### 2.1 One-time setup

Add `EGP_GRAFANA_ADMIN_PASSWORD` to `/etc/egp/egp.env` (the env file
created in [Lightsail §5](./LIGHTSAIL_LOW_COST_LAUNCH.md)):

```bash
echo "EGP_GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 24)" | \
    sudo tee -a /etc/egp/egp.env
```

(You can also use a passphrase; just make sure it's stored in a
secret manager you control. Rotation procedure:
[`docs/SECRET_ROTATION.md`](./SECRET_ROTATION.md) §10.)

### 2.2 Start the overlay

```bash
docker compose --env-file /etc/egp/egp.env \
    -f docker-compose.yml \
    -f docker-compose.monitoring.yml \
    up -d prometheus grafana
```

The base stack (api, worker, postgres, caddy) stays running; the
overlay just adds Prometheus + Grafana alongside it.

### 2.3 Verify

```bash
# Prometheus is scraping the API
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml \
    exec prometheus wget -qO- http://localhost:9090/-/healthy
# Expect: Prometheus Server is Healthy.

# API target is "UP" in Prometheus
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml \
    exec prometheus wget -qO- 'http://localhost:9090/api/v1/targets' \
    | python3 -m json.tool | grep -E '"health"|"job"'
# Expect: "health": "up" for the egp_api job.

# Grafana is up
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml \
    exec grafana wget -qO- http://localhost:3000/api/health
# Expect: {"database":"ok","version":"11.4.0"}
```

---

## 3. Reach the UIs via SSH tunnel

Because the services bind to `127.0.0.1` only, you need an SSH tunnel
to access them from your laptop:

### Grafana (most common)

```bash
# From your laptop
ssh -L 3001:127.0.0.1:3000 user@your-lightsail-host
# Then open http://localhost:3001 in your browser
# Login: admin / $EGP_GRAFANA_ADMIN_PASSWORD (from the env file)
```

The pre-built dashboard is at **Dashboards → Browse → e-GP Observability Baseline**.

### Prometheus (for ad-hoc PromQL queries)

```bash
ssh -L 9090:127.0.0.1:9090 user@your-lightsail-host
# Then open http://localhost:9090 in your browser
```

Useful PromQL queries to know:

```promql
# Per-route 5xx rate, last 5 min
sum by (route) (rate(egp_request_total{status_class="5xx"}[5m]))

# p95 request latency, last 5 min
histogram_quantile(0.95, sum by (le, route) (
  rate(egp_request_duration_seconds_bucket[5m])
))

# Tenant admission rejections (PR-08), last 1h
sum by (tenant_id) (increase(egp_admission_rejected_total[1h]))
```

---

## 4. Grafana Cloud Free alternative

If you prefer to keep Grafana Cloud-hosted (e.g., dashboard access
without SSH tunneling), drop the overlay's `grafana` service and use
Grafana Cloud Free instead. Prometheus stays self-hosted on the
Lightsail VM.

### 4.1 Free tier limits (as of 2026-05)

- 10K active series
- 14 days retention
- 3 users
- 50 alert rules

Fits the launch baseline comfortably.

### 4.2 Setup

1. Sign up at <https://grafana.com/products/cloud/> — pick the Free tier.
2. **Connections → Add new connection → Prometheus** → choose **Self-managed**.
3. Grafana Cloud gives you a `remote_write` endpoint + an access token.
4. Add a `remote_write` block to `deploy/prometheus.yml` (keep the
   existing self-hosted scrape config):

   ```yaml
   remote_write:
     - url: https://prometheus-us-central1.grafana.net/api/prom/push
       basic_auth:
         username: <your-stack-id>
         password: <your-grafana-cloud-token>
   ```

5. Rebuild the prometheus container to pick up the new config:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.monitoring.yml \
       restart prometheus
   ```

6. Drop the `grafana` service from the overlay (`docker compose ... rm -f grafana`)
   or leave it as a local fallback.

7. Import the dashboard JSON into Grafana Cloud:
   `infrastructure/grafana/dashboard.json` → **Dashboards → New → Import**.

**Trade-off:** Grafana Cloud sees only the metrics you `remote_write` to
it. You keep data sovereignty (Prometheus is self-hosted), at the cost
of double-writing every metric.

---

## 5. Resource budget

The overlay adds **~400–600 MB** of memory to the host:

| Service | RAM (steady) | Disk (after 14d) |
|---|---|---|
| Prometheus | ~250–400 MB | ~500 MB – 2 GB (depends on series cardinality) |
| Grafana | ~150–200 MB | ~50 MB (mostly SQLite + provisioned dashboards) |

On a **$12/mo Lightsail (4 GB / 2 vCPU)** with the base stack
(api + worker + postgres + caddy ~1.5 GB), there's enough headroom.
On a $5/mo (1 GB) instance, the monitoring overlay would push the box
into swap — upgrade first.

To reduce footprint:

- Drop Prometheus retention from 14d to 7d:
  edit `docker-compose.monitoring.yml` and change
  `--storage.tsdb.retention.time=14d` → `--storage.tsdb.retention.time=7d`,
  then `docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d prometheus`.
- Switch to the Grafana Cloud Free pattern (§4) — saves the Grafana
  container entirely (~150 MB).

---

## 6. Operational drills

### 6.1 Disk usage check

```bash
# How big is Prometheus's TSDB?
docker volume inspect egp_prometheus_data \
    --format '{{ .Mountpoint }}' | xargs -I {} sudo du -sh {}
```

If it grows past 5 GB, lower retention.

### 6.2 Rebuild dashboard from canonical

If someone hand-edits `infrastructure/grafana/dashboard.json` (the
canonical source), sync the deployment copy:

```bash
cp infrastructure/grafana/dashboard.json \
   deploy/grafana/dashboards/egp-overview.json

# Grafana auto-reloads provisioned dashboards every 30s
# (see deploy/grafana/provisioning/dashboards/dashboards.yml).
```

The drift test `tests/operations/test_observability_stack.py::test_deployed_dashboard_matches_canonical_source`
catches divergence at CI time.

### 6.3 Reset Grafana admin password

If you lose the admin password:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml \
    exec grafana grafana cli admin reset-admin-password '<new-password>'

# Then update /etc/egp/egp.env so future restarts use the new value:
sudo nano /etc/egp/egp.env
# (edit EGP_GRAFANA_ADMIN_PASSWORD=...)
```

---

## 7. Upgrade procedure

When bumping image versions:

1. **Stage**: test the new tag locally first
   (`docker compose -f docker-compose.yml -f docker-compose.monitoring.yml pull && up -d`).
2. Update `docker-compose.monitoring.yml` to pin the new tag.
3. Run the drift test: `./.venv/bin/python -m pytest tests/operations/test_observability_stack.py -v`.
4. Bring up the updated stack on prod:
   ```bash
   docker compose --env-file /etc/egp/egp.env \
       -f docker-compose.yml -f docker-compose.monitoring.yml pull
   docker compose --env-file /etc/egp/egp.env \
       -f docker-compose.yml -f docker-compose.monitoring.yml up -d prometheus grafana
   ```
5. Verify Prometheus targets are still healthy + Grafana dashboards
   render (sometimes major Grafana upgrades touch dashboard schema).
6. Commit the version bump as a small follow-up PR.

---

## 8. Rollback

To stop the monitoring overlay without losing accumulated metrics:

```bash
docker compose --env-file /etc/egp/egp.env \
    -f docker-compose.yml -f docker-compose.monitoring.yml \
    stop prometheus grafana

docker compose --env-file /etc/egp/egp.env \
    -f docker-compose.yml -f docker-compose.monitoring.yml \
    rm -f prometheus grafana
```

**Volumes are intentionally kept** so you can resume later. To wipe
metrics history too:

```bash
docker volume rm egp_prometheus_data egp_grafana_data
```

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Grafana login fails | Wrong `EGP_GRAFANA_ADMIN_PASSWORD` | Reset via `grafana cli admin reset-admin-password` (§6.3) |
| Prometheus shows `egp_api` target as **down** | API not running OR not on the same Compose network | `docker compose ps api`; verify api container is healthy |
| Dashboard panels say "No data" | Prometheus has no scrape history yet | Wait 30–60s after first bring-up; check Prometheus → Status → Targets |
| Grafana port 3000 conflicts with apps/web | The base stack's `web` is gated behind `--profile single-host` (PR-D) so it doesn't conflict by default. If you DO run single-host AND monitoring together, remap Grafana to 127.0.0.1:3002 in the overlay. |
| Disk filling up | TSDB at 14d retention with high cardinality | Lower to 7d (§5) or run `docker system prune --volumes` carefully |
| `docker compose config` errors | `EGP_GRAFANA_ADMIN_PASSWORD` not set | Add to `/etc/egp/egp.env` or pass via `--env-file` |

---

## 10. Follow-up work

These are explicitly **NOT** in PR-E and tracked for follow-up:

- **Worker `/metrics` HTTP endpoint**: workers update counters
  in-process but lack an HTTP listener. Add a small `prometheus_client.start_http_server(port)`
  call in `apps/worker/src/egp_worker/main.py` and add the worker job
  to `deploy/prometheus.yml`.
- **Node exporter** for host CPU/memory/disk
  (`prom/node-exporter:latest`).
- **Alertmanager** wiring with pager destinations (PagerDuty, OpsGenie,
  or just email-via-Resend).
- **Public read-only Grafana**: expose a redacted "status page" without
  SSH tunneling. Needs Grafana's Viewer-role + a public dashboard +
  Caddy proxy block.
