# Coding Log: ws2-discovery-anomaly-canary (2026-06-15)

WS2 ("Make misses impossible to hide") from the discovery-completeness unified plan
(`coding-logs/2026-06-14-11-33-19 …`, §4 WS2). WS1 (header-derived columns, PR #149)
is already shipped; this is the follow-up that makes a silent discovery miss
impossible to hide as a plain `succeeded` run. Scope chosen by product owner:
**Core + full Prometheus**.

## Problem

After WS1, discovery can still silently return zero projects if (a) e-GP's status
vocabulary gains an unseen pre-award spelling, or (b) a *required* results-table
header is renamed so the table isn't recognized. The column-drift incident hid for
weeks precisely because "rows found, zero eligible" looked like a successful run.

## What changed

### Worker (emits telemetry only — control-plane/worker-plane split)
- `apps/worker/.../browser_discovery.py`:
  - `KeywordScanAccumulator` aggregates per-keyword scan telemetry across pages
    (`rows_scanned`, `status_eligible`, `accepted`, `rejected_by_status`,
    `skip_hits`, `dedup_hits`, `unreadable_rows`, `status_buckets`, `egp_found`,
    `header_signature`, `header_signature_drift`).
  - `_results_header_signature()` + pinned `EXPECTED_RESULTS_HEADER_SIGNATURE`
    (the known-good 7-column layout) → drift fingerprint.
  - `_read_egp_found_count()` reads e-GP's `จำนวนโครงการที่พบ : N`.
  - `_collect_keyword_projects` now emits a `keyword_scan_summary` progress event
    at keyword end; `page_scan_finished` is preserved.
  - **Canary** (`reason_code = no_eligible_rows`): `rows_scanned > 0 && status_eligible == 0`
    OR `egp_found > 0 && rows_scanned == 0` (table not recognized). Keyed off
    *status-eligible* (before skip/dedup) so all-skipped / all-duplicate keywords
    are NOT false positives.

### Shared types
- `packages/shared-types/.../enums.py`: `CrawlOutcomeReason` StrEnum (shared reason
  codes for telemetry + Prometheus labels).

### Workflow (classify + persist; no migration)
- `apps/worker/.../workflows/discover.py`: `keyword_scan_summary` with
  `reason_code == no_eligible_rows` is a non-terminal anomaly that flips run status
  (detected at event arrival, because `keyword_finished` is emitted *after* the
  summary). Header drift is **informational only** (logged + persisted + metric;
  does NOT fail the run — WS1 made columns header-derived). Telemetry persists to
  `crawl_runs.summary_json["keyword_scans"]`.

### Observability (API control plane owns /metrics)
- `packages/observability/.../metrics.py`: 5 metrics —
  `egp_discovery_keyword_scans_total{outcome,reason}`,
  `egp_discovery_rows_scanned_total{outcome}`,
  `egp_discovery_eligible_rows_total{outcome}`,
  `egp_discovery_anomalies_total{reason}`,
  `egp_discovery_header_signature_drift_total`. Helpers + whitelisted labels
  (untrusted persisted JSON → unknowns collapse to `unknown`, bounding cardinality).
- `apps/api/.../discovery_worker_dispatcher.py`: `_emit_discovery_run_metrics()`
  reads the worker-written run summary after the one-shot subprocess exits and emits
  metrics in the API process (the worker has no scrapeable `/metrics`). Never fails
  dispatch (guards non-dict `summary_json`, swallows errors).
- `infrastructure/grafana/dashboard.json` (+ byte-identical `deploy/grafana/dashboards/egp-overview.json`):
  2 new panels. `infrastructure/grafana/alerts.yml`: `EGPDiscoveryEligibilityRateCollapsed`
  (critical), `EGPDiscoveryZeroEligibleScans`, `EGPDiscoveryHeaderSignatureDrift`.
- `docs/OBSERVABILITY.md`: documents the WS2 metrics/alerts + why they're API-emitted.
- `apps/web/.../run-progress.ts`: label for the `keyword_scan_summary` stage.

## Design decisions
1. Canary keys off **status-eligible** rows, not post-skip/dedup `accepted`, so
   legitimate all-skipped/all-duplicate keywords don't trip it.
2. **Header drift = informational** (not run-failing); the unambiguous bug signal is
   the fleet `EGPDiscoveryEligibilityRateCollapsed` alert + the canary.
3. Metrics emitted **API-side** from the persisted run summary (control-plane owns
   state + `/metrics`; worker is a one-shot subprocess). No worker HTTP server.
4. **No DB migration** — telemetry rides in existing JSON columns.

## TDD evidence
- RED→GREEN per component (enum → accumulator/canary → workflow → metrics → dispatcher).
- Full sweep: **1043 passed**, 3× consecutive with zero flakiness; `ruff check apps/ packages/ tests/` clean; `tsc --noEmit` clean (web).
- Known **pre-existing** failure (NOT WS2): `tests/operations/test_env_template.py::test_env_template_tracks_runtime_egp_vars`
  (`EGP_BROWSER_PREDISPATCH_WARM_SECONDS` / `EGP_BROWSER_WARMUP_STALE_AFTER_SECONDS`
  missing from the env template — from the persistent-profile warmup feature).
  Confirmed identical failure with WS2 changes stashed.

## QCHECK (Codex gpt-5.5, xhigh, two rounds)
- Round 1 → BLOCK: HIGH-1 (canary used post-skip/dedup count), HIGH-2
  (renamed required header → silent miss), MEDIUM-1 (non-dict `summary_json` could
  fail dispatch), MEDIUM-2 (label cardinality), MEDIUM-3 (alert-test coverage).
- All fixed (status-eligible canary + `egp_found>0 && rows_scanned==0` canary +
  isinstance guard + label whitelist + alert assertions), each with regression tests.
- Round 2 → **SHIP**: all prior findings resolved, no new findings.

## Wiring
All new exports have non-test importers: `CrawlOutcomeReason` (discover.py),
`KeywordScanAccumulator` (browser_discovery.py), `record_discovery_keyword_scan`
(dispatcher), `_emit_discovery_run_metrics` (dispatch success path),
`EXPECTED_RESULTS_HEADER_SIGNATURE` (accumulator). Metric-name contract kept in
lockstep across metrics.py / both test files / dashboard.json / deploy copy / alerts.yml.

## Follow-ups (not in this PR)
- Precise `status → ProjectState` mapping for pre-award stages.
- WS5 (prod re-scan repair), WS3/WS4 (capture/backfill + fleet ops) per the unified plan §4.
- Pre-existing `test_env_template` env-var drift (separate concern).
