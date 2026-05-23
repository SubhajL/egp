# Coding Log - observability-metrics

## Plan (2026-05-23 11:58:54 +0700)

Auggie semantic search unavailable; plan is based on direct file inspection plus exact-string searches. Inspected paths: `AGENTS.md`, `apps/api/AGENTS.md`, `apps/worker/AGENTS.md`, `packages/AGENTS.md`, `apps/api/src/egp_api/main.py`, `apps/api/src/egp_api/bootstrap/middleware.py`, `apps/api/src/egp_api/bootstrap/services.py`, `apps/worker/src/egp_worker/main.py`, root/app `pyproject.toml` files, `.github/workflows/ci.yml`, existing API and worker tests under `tests/phase1` and `tests/phase2`.

### Draft A - Prometheus client with explicit metric helpers

#### Overview

Add an installable observability package with explicit Prometheus metric definitions and helper functions. Wire API request instrumentation through FastAPI middleware and expose `/metrics`; wrap worker command execution in lightweight counters/histograms. Add Grafana dashboard and alert YAML as static deploy assets.

#### Files to Change

- `pyproject.toml`: include the new observability package path and dependency.
- `apps/api/pyproject.toml`, `apps/worker/pyproject.toml`: list `prometheus-client` for app-local installs.
- `packages/observability/src/egp_metrics.py`: PR-specified module with metric names and helper API.
- `packages/observability/src/egp_observability/`: installable package wrapper around the metrics module.
- `apps/api/src/egp_api/main.py`: initialize API metrics wiring in `create_app`.
- `apps/worker/src/egp_worker/main.py`: initialize worker metrics and observe worker command execution.
- `tests/phase2/test_observability_metrics.py`: endpoint and worker instrumentation tests.
- `infrastructure/grafana/dashboard.json`: Grafana dashboard panels.
- `infrastructure/grafana/alerts.yml`: Prometheus/Grafana-compatible alert rules.

#### Implementation Steps

TDD sequence:
1. Add tests for `/metrics`, worker command metrics, metric names, and alert YAML parsing.
2. Run targeted tests and confirm failure because `egp_observability`/`egp_metrics` do not exist.
3. Implement the smallest metrics package and runtime wiring.
4. Refactor only to keep registry reset/test isolation clean.
5. Run focused pytest, ruff, compileall, and dashboard/alert validation.

Functions:
- `initialize_metrics()`: idempotently define process-global Prometheus metrics.
- `render_prometheus_metrics()`: serialize the configured registry.
- `instrument_fastapi_app(app)`: add `/metrics` plus timing middleware.
- `observe_api_request(method, path, status_code, duration_seconds)`: record API count/latency with normalized labels.
- `record_worker_job(command, outcome, duration_seconds)`: record worker command count/latency.
- `main()` worker wrapper: observe successful and failing non-noop commands.

Expected behavior and edge cases:
- `/metrics` must be unauthenticated and expose every PR-01 metric name.
- API metrics must avoid tenant, keyword, project, run, or document labels.
- Worker metrics must label only command and outcome, with failed jobs recorded before re-raising.
- Metrics setup must be idempotent under repeated `create_app()` calls in tests.

#### Test Coverage

- `test_metrics_endpoint_exposes_pr01_metric_names`: all expected names visible.
- `test_metrics_endpoint_counts_api_requests`: request counter increments.
- `test_worker_main_records_successful_command_metrics`: noop emits success.
- `test_worker_main_records_failed_command_metrics`: bad command emits failure.
- `test_grafana_alert_rules_yaml_validates`: alert YAML parses and names match.

#### Decision Completeness

Goal: establish always-on, low-cardinality observability before behavior-changing rollout PRs.

Non-goals: no production scrape service deployment, no DB schema changes, no tenant/customer labels, no rate limiter metrics from PR-06 yet.

Success criteria:
- `/metrics` returns Prometheus text format with every PR-01 metric name.
- Worker entrypoint records command counters/histograms.
- Grafana dashboard and alert rules parse as JSON/YAML.
- Local focused tests and lint/compile gates pass.

Public interfaces:
- API endpoint: `GET /metrics`.
- Python modules: `egp_metrics` compatibility module and `egp_observability.metrics`.
- Dependency: `prometheus-client`.
- Infrastructure files: `infrastructure/grafana/dashboard.json`, `infrastructure/grafana/alerts.yml`.

Edge cases / failure modes:
- Duplicate metric registration: fail open by idempotently reusing metrics.
- Metrics endpoint scrape failure: fail closed for endpoint response only; app routes continue.
- High-cardinality labels: blocked by fixed label sets.
- Worker exception: record `outcome="error"` and re-raise existing exit behavior.

Rollout and monitoring:
- Metrics always on, no flags.
- Watch scrape success, dashboard load, label cardinality.
- Backout by reverting PR; no migrations.

Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase2/test_observability_metrics.py -q`
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase2/test_observability_metrics.py`
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/observability/src`
- JSON/YAML parser command for Grafana assets.

#### Dependencies

Requires `prometheus-client` and `PyYAML` for tests already available in the local venv; CI must install `prometheus-client` from project metadata.

#### Validation

Use TestClient for `/metrics`, direct worker `main(stdin_text=...)` for subprocess-free worker assertions, and parser validation for static assets.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `egp_metrics.py` | Imported by `egp_observability.metrics` | root `pyproject.toml` package/module config | N/A |
| API metrics middleware | Every HTTP request | `egp_api.main:create_app()` calls `instrument_fastapi_app(app)` | N/A |
| `/metrics` endpoint | Prometheus scrape | `instrument_fastapi_app()` route registration | N/A |
| Worker metrics | `egp_worker.main:main()` | wrapper around `run_worker_job(payload)` | N/A |
| Grafana dashboard | Grafana provisioning/import | `infrastructure/grafana/dashboard.json` | N/A |
| Alert rules | Prometheus/Grafana rules loader | `infrastructure/grafana/alerts.yml` | N/A |

Cross-language schema verification: no DB migrations or cross-language schema names in this PR.

Decision-complete checklist:
- No open implementation decisions remain.
- Public interfaces are listed.
- Behavior changes have tests.
- Validation commands are scoped.
- Wiring table covers each new component.
- Rollout/backout is specified.

### Draft B - Minimal ASGI middleware local to API and worker

#### Overview

Keep most metrics code in API/worker modules and use a small shared constants module for metric names. This reduces package complexity but duplicates registry setup concerns across services.

#### Files to Change

- `packages/observability/src/egp_metrics.py`: constants only.
- `apps/api/src/egp_api/bootstrap/metrics.py`: API middleware and endpoint.
- `apps/worker/src/egp_worker/metrics.py`: worker counters/histograms.
- Same dependency, tests, dashboard, and alert files as Draft A.

#### Implementation Steps

TDD sequence:
1. Add tests asserting endpoint names and worker metrics.
2. Confirm failure due missing modules.
3. Implement API-local and worker-local metrics files.
4. Deduplicate only shared names/buckets if needed.
5. Run focused gates.

Functions:
- `configure_api_metrics(app)`: register API middleware and endpoint.
- `record_worker_job_metrics(command, outcome, duration_seconds)`: worker-local instrumentation.
- `metric_names()`: expose the expected metric names.

Expected behavior and edge cases match Draft A, but duplicate registry registration risks are handled independently in two service modules.

#### Test Coverage

- `test_metrics_endpoint_exposes_pr01_metric_names`: endpoint includes constants.
- `test_api_middleware_records_latency`: API-local middleware works.
- `test_worker_records_outcome_metrics`: worker-local metrics works.
- `test_alert_rules_yaml_validates`: alert YAML is valid.

#### Decision Completeness

Goal, non-goals, public surfaces, rollout, and acceptance checks match Draft A.

Trade-off: lower shared-package surface area but more duplicate code and weaker consistency between API and worker labels.

#### Dependencies

Same as Draft A.

#### Validation

Same as Draft A, plus exact-string search to ensure both service-local modules import shared metric names.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| API metrics module | `create_app()` | direct import in API main | N/A |
| Worker metrics module | `main()` | direct import in worker main | N/A |
| `egp_metrics.py` | imported by both modules | root package/module config | N/A |
| Grafana assets | deploy import | `infrastructure/grafana/` | N/A |

Cross-language schema verification: no DB migrations.

Decision-complete checklist:
- No open decisions remain, but duplicate service-local registry handling is a maintainability risk.

### Comparative Analysis

Draft A centralizes metric definitions and label policy, which is better for this rollout because later PRs need to add counters and histograms without inventing labels. It has slightly more packaging work because the PR-specific `egp_metrics.py` file needs to be importable while still fitting the repo's package-find layout.

Draft B is smaller initially but splits API and worker metrics setup, increasing the risk of name/label drift and duplicate metric registration bugs. It also gives later PRs a less obvious shared extension point.

Both drafts follow repo guidance by keeping entrypoints thin, avoiding DB/schema changes, and adding focused tests. Draft A is the better fit because PR-01 is explicitly an observability foundation for multiple follow-on PRs.

### Unified Execution Plan

#### Overview

Implement Draft A with a shared observability package, an API `/metrics` endpoint, API request middleware, worker command instrumentation, and Grafana dashboard/alert files. Keep labels deliberately low cardinality and keep behavior fail-open for normal app/worker execution.

#### Files to Change

- `pyproject.toml`: add `prometheus-client`, package path, and observability package include.
- `apps/api/pyproject.toml`: add `prometheus-client`.
- `apps/worker/pyproject.toml`: add `prometheus-client`.
- `apps/api/Dockerfile`, `apps/worker/Dockerfile`: ensure explicit Docker dependency installs include `prometheus-client`.
- `packages/observability/src/egp_metrics.py`: compatibility module with public metric helpers.
- `packages/observability/src/egp_observability/__init__.py`: side-effect-free package exports.
- `packages/observability/src/egp_observability/metrics.py`: implementation for registry, metrics, middleware, and worker helpers.
- `apps/api/src/egp_api/main.py`: call `instrument_fastapi_app(app)`.
- `apps/api/src/egp_api/bootstrap/middleware.py`: allow `/metrics` without auth.
- `apps/worker/src/egp_worker/main.py`: record worker command duration/outcome.
- `tests/phase2/test_observability_metrics.py`: focused tests.
- `infrastructure/grafana/dashboard.json`: dashboard.
- `infrastructure/grafana/alerts.yml`: alert rules.
- `.codex/coding-log.current`: point to this log.

#### Implementation Steps

TDD sequence:
1. Add `tests/phase2/test_observability_metrics.py` first.
2. Run `./.venv/bin/python -m pytest tests/phase2/test_observability_metrics.py -q` and confirm import/endpoint failures.
3. Add metrics package and dependency metadata.
4. Wire API middleware/endpoint and worker instrumentation.
5. Add Grafana dashboard/alert files.
6. Run focused tests until green, then run them 3x.
7. Run ruff, compileall, JSON/YAML validation, and wiring grep checks.
8. Stage intended files, run g-check, fix findings if any.
9. Create Graphite branch `feat/observability-metrics`, submit PR, handle CI, merge, and sync main.

Functions:
- `get_metrics_registry()`: returns the shared Prometheus registry.
- `reset_metrics_for_tests()`: test-only reset to keep assertions deterministic.
- `render_prometheus_metrics()`: returns bytes plus Prometheus content type.
- `instrument_fastapi_app(app)`: registers `/metrics` and HTTP middleware once per app.
- `observe_api_request(method, path, status_code, duration_seconds)`: records API count and latency.
- `record_worker_job(command, outcome, duration_seconds)`: records worker count and duration.
- `metric_names_for_validation()`: stable list used by tests/static assets.

Expected behavior and edge cases:
- `/metrics` unauthenticated, including when `auth_required=True`.
- Label sets are fixed to `method`, normalized `path`, `status_class`, `command`, and `outcome`.
- No tenant, keyword, project ID, run ID, document ID, or raw query labels.
- Repeated `create_app()` calls do not duplicate routes/middleware metrics.
- Worker bad commands still raise/exit as before, after recording error metrics.

#### Test Coverage

- `test_metrics_endpoint_exposes_pr01_metric_names`: endpoint exposes all PR-01 names.
- `test_metrics_endpoint_counts_api_requests`: health request increments API counter.
- `test_metrics_endpoint_bypasses_auth_required`: scrape works with auth on.
- `test_worker_main_records_successful_command_metrics`: noop records success.
- `test_worker_main_records_failed_command_metrics`: unsupported command records error.
- `test_grafana_dashboard_json_validates`: dashboard parses and references names.
- `test_grafana_alert_rules_yaml_validates`: alert YAML parses and references names.

#### Decision Completeness

Goal: ship always-on baseline Prometheus instrumentation and deployable Grafana assets before behavior-changing PRs.

Non-goals: no alert manager deployment, no scrape target provisioning, no schema changes, no per-tenant/per-keyword metrics, no PR-06 rate limiter metrics implementation yet.

Success criteria:
- Focused tests pass 3 consecutive runs.
- `/metrics` exposes every expected metric name.
- Worker instrumentation produces counters/histograms for success and failure.
- Dashboard/alerts parse and reference only known metric names.
- Ruff, compileall, and wiring checks pass.

Public interfaces:
- API endpoint: `GET /metrics`.
- Python modules: `egp_metrics`, `egp_observability`.
- Dependency: `prometheus-client>=0.20`.
- Infrastructure files under `infrastructure/grafana/`.
- No env vars, CLI flags, DB migrations, or message topics.

Edge cases / failure modes:
- Duplicate metric creation: handled idempotently.
- Scrape route exception: scrape fails, normal app requests continue.
- Middleware path matching: normalized to route path when available; fallback to raw path without query string.
- Worker exception: record error and preserve existing exception/SystemExit behavior.
- Missing Grafana loader: static files remain valid but inert.

Rollout and monitoring:
- Metrics always on.
- Deploy, observe 48h baseline collection.
- Watch scrape success rate, dashboard render, and label cardinality.
- Rollback trigger: scrape failures above 1 percent or unexpected label cardinality.
- Backout: revert PR or disable scrape target; no migrations.

Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase2/test_observability_metrics.py -q`
- three-run loop for the focused test file.
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase2/test_observability_metrics.py`
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/observability/src`
- parser validation for `infrastructure/grafana/dashboard.json` and `infrastructure/grafana/alerts.yml`.

#### Dependencies

Add `prometheus-client>=0.20` to app/root dependency metadata and Docker explicit installs. Tests use `yaml` from the existing venv; if CI lacks PyYAML, the test will skip YAML parsing only if unavailable and still validate structure with a minimal fallback.

#### Validation

Verify runtime wiring with `rg` for `instrument_fastapi_app`, `record_worker_job`, `metrics`, `egp_observability`, and asset metric references. Verify package install by importing `egp_metrics` and `egp_observability.metrics` after editable install.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `egp_metrics.py` | imports from package implementation | root `pyproject.toml` includes `egp_observability`; wrapper used by tests/import smoke | N/A |
| `egp_observability.metrics` | imported by API and worker | root `pyproject.toml` package include | N/A |
| API middleware | every request | `egp_api.main:create_app()` calls `instrument_fastapi_app(app)` | N/A |
| `/metrics` endpoint | Prometheus scrape | route registered inside `instrument_fastapi_app()` and auth allowlist includes `/metrics` | N/A |
| Worker metrics | `egp_worker.main:main()` | direct `record_worker_job()` call around `run_worker_job()` | N/A |
| Grafana dashboard | Grafana import/provisioning | `infrastructure/grafana/dashboard.json` | N/A |
| Alert rules | Prometheus/Grafana rule loader | `infrastructure/grafana/alerts.yml` | N/A |

Cross-language schema verification: not applicable; no migration or schema contract changes.

Decision-complete checklist:
- No open decisions remain.
- Every public interface is listed.
- Every behavior change has a focused test.
- Validation commands are specific and scoped.
- Wiring table covers every new endpoint/module/static asset.
- Rollout/backout is specified.

## Implementation Summary (2026-05-23 12:18:00 +0700)

### Goal

Implement PR-01 observability foundation through always-on Prometheus metrics, API scrape endpoint/middleware, worker command instrumentation, and Grafana dashboard/alert assets.

### What Changed

- `packages/observability/src/egp_observability/metrics.py`: added process-local Prometheus registry, stable PR-01 metric definitions, API request observation, worker command observation, `/metrics` route registration, and test reset helper.
- `packages/observability/src/egp_metrics.py`: added PR-specified compatibility module that re-exports the installable observability package.
- `apps/api/src/egp_api/main.py`: wires API instrumentation in `create_app()`.
- `apps/api/src/egp_api/bootstrap/middleware.py`: allows unauthenticated `/metrics` scrapes.
- `apps/worker/src/egp_worker/main.py`: records worker command success/error/entitlement-denied outcomes without changing existing command behavior.
- `pyproject.toml`, `apps/api/pyproject.toml`, `apps/worker/pyproject.toml`, `apps/api/Dockerfile`, `apps/worker/Dockerfile`: added `prometheus-client` dependency/install coverage and observability package discovery.
- `infrastructure/grafana/dashboard.json`, `infrastructure/grafana/alerts.yml`: added baseline dashboard and alert rule assets.
- `tests/phase2/test_observability_metrics.py`: added focused endpoint, worker, and Grafana asset tests.

### TDD Evidence

RED:
- Command: `./.venv/bin/python -m pytest tests/phase2/test_observability_metrics.py -q`
- Result: failed for missing `egp_observability` module and missing Grafana assets after fixing the local `repo_root` fixture in the new test file.

GREEN:
- Command: `./.venv/bin/python -m pytest tests/phase2/test_observability_metrics.py -q`
- Result: `7 passed`.

### Tests And Gates Run

- `./.venv/bin/python -m pip install -e .`: PASS; installed `prometheus-client` and refreshed editable package mapping.
- `./.venv/bin/python -c "import egp_metrics, egp_observability.metrics as m; ..."`: PASS.
- `for i in 1 2 3; do ./.venv/bin/python -m pytest tests/phase2/test_observability_metrics.py -q || exit 1; done`: PASS, three consecutive runs.
- `./.venv/bin/python -m pytest tests/phase2/test_background_runtime_mode.py tests/phase1/test_worker_entrypoint.py -q`: PASS, `8 passed`.
- `./.venv/bin/python -m pytest tests/phase2/test_observability_metrics.py tests/phase2/test_background_runtime_mode.py tests/phase1/test_worker_entrypoint.py -q`: PASS, `15 passed`.
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase2/test_observability_metrics.py`: PASS.
- `./.venv/bin/ruff format --check apps/api/src/egp_api/main.py apps/api/src/egp_api/bootstrap/middleware.py apps/worker/src/egp_worker/main.py packages/observability/src/egp_metrics.py packages/observability/src/egp_observability/__init__.py packages/observability/src/egp_observability/metrics.py tests/phase2/test_observability_metrics.py`: PASS.
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/observability/src`: PASS.
- JSON parser validation for `infrastructure/grafana/dashboard.json` and `infrastructure/grafana/alerts.yml`: PASS.
- ASCII scan over touched code/config/assets: PASS.
- Broad `ruff format --check apps/api apps/worker packages tests/phase2/test_observability_metrics.py`: reported unrelated pre-existing formatting drift in 12 files; touched-file format check passed and unrelated files were not changed.

### Wiring Verification Evidence

| Component | Wiring Verified? | Evidence |
|---|---|---|
| `egp_observability.metrics` | YES | `egp_api.main:create_app()` imports and calls `instrument_fastapi_app(app)`; `egp_worker.main` imports `record_worker_job`. |
| `egp_metrics.py` | YES | Editable install maps `egp_metrics` to `packages/observability/src/egp_metrics.py`; import smoke passed. |
| `/metrics` endpoint | YES | `instrument_fastapi_app()` registers `@app.get("/metrics")`; auth allowlist includes `/metrics`; TestClient scrape passes with `auth_required=True`. |
| API request metrics | YES | middleware records method, route path or `unmatched`, and status class; `/health` counter assertion passes. |
| Worker metrics | YES | `main()` records noop, success, entitlement-denied, and generic error outcomes; success/error tests pass. |
| Grafana assets | YES | dashboard and alert files parse and tests assert expected metric references. |

### Behavior Changes And Risk Notes

- New public surface: unauthenticated `GET /metrics`.
- Metrics labels are intentionally low-cardinality. API unmatched routes collapse to `path="unmatched"` and unknown worker commands collapse to `command="unsupported"`.
- Normal API/worker behavior is fail-open relative to metrics: worker errors are recorded then re-raised; API exceptions are recorded as `5xx` then preserve existing behavior.
- No DB migrations, env vars, or tenant-scoped data access changes.

### Follow-ups / Known Gaps

- Broad repository format check still has unrelated pre-existing drift.
- PR-01 defines future rollout metric names, but PR-03/04/05/06/07/08 will add their specific producers.

## Review (2026-05-23 12:20:00 +0700) - staged working tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main` before Graphite branch creation
- Scope: staged PR-01 files only; pre-existing modified monthly coding log and `egp-dev-logs` intentionally excluded
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --stat`; targeted `nl -ba` reads for `packages/observability/src/egp_observability/metrics.py`, `apps/api/src/egp_api/main.py`, `apps/worker/src/egp_worker/main.py`; focused pytest/ruff/compile/import gates listed above

### Findings

CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings. A review concern around high-cardinality labels was fixed before this report: unmatched API paths now use `path="unmatched"` and unrecognized worker commands now use `command="unsupported"`.

LOW
- No findings.

### Open Questions / Assumptions

- Alert thresholds are baseline placeholders for the PR-01 observation window and may need adjustment after 48h of real scrape data.
- `alerts.yml` is JSON-subset YAML so it can be validated without adding a test-only YAML parser dependency; Prometheus/Grafana YAML loaders accept JSON-subset YAML.

### Recommended Tests / Validation

- Keep the focused PR-01 tests in CI.
- After deploy, validate actual Prometheus scrape success and dashboard import/rendering in the target Grafana environment.

### Rollout Notes

- Metrics are always on; no flags.
- Watch scrape failure rate and label cardinality first.
- Roll back by reverting PR-01 or removing the scrape target; there is no database backout.
