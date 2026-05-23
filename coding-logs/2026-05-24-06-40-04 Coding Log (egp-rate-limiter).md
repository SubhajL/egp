# Coding Log: egp-rate-limiter

## Plan Draft A

### Overview
Add a host-level file-lock token bucket in `crawler-core` and wire worker browser actions through it. Browser navigation, search submit, pagination, and document download clicks will all acquire a token before touching e-GP.

### Files To Change
- `packages/crawler-core/src/egp_crawler_core/rate_limiter.py`: file-lock token bucket, circuit breaker, env config, and backoff helpers.
- `packages/crawler-core/src/egp_crawler_core/__init__.py`: export the rate limiter API.
- `apps/worker/src/egp_worker/browser_discovery.py`: wrap `page.goto`, search submit, and pagination click actions; use exponential backoff on recovery retries.
- `apps/worker/src/egp_worker/browser_downloads.py`: wrap download clicks, inferred `goto`, and direct request download calls; use exponential backoff in toast recovery.
- `packages/observability/src/egp_observability/metrics.py`, `packages/observability/src/egp_observability/__init__.py`, `packages/observability/src/egp_metrics.py`: expose helpers for `egp_egp_request_total` and `egp_rate_limiter_wait_seconds`.
- `tests/concurrency/test_rate_limiter.py`: concurrency and circuit tests.

### Implementation Steps
1. Add failing tests for file-lock RPS enforcement, circuit open/reset, env config, and low-cardinality metrics.
2. Run the new tests and confirm RED due missing module/API.
3. Implement `RateLimiterConfig`, `FileLockRateLimiter`, `CircuitOpenError`, and `exponential_backoff_delay`.
4. Add worker-side wrappers that call the limiter and metrics helpers around e-GP browser operations.
5. Replace retry sleeps with backoff helper where the code is actually retrying a failed e-GP operation.
6. Run focused worker/rate-limiter tests, ruff, compileall, and review gates.

### Test Coverage
- `test_file_lock_rate_limiter_limits_requests_across_workers`: stub server timestamps stay under configured RPS.
- `test_circuit_opens_after_429_burst_and_resets`: 429 threshold opens circuit until reset window.
- `test_rate_limiter_config_reads_environment`: env vars produce expected runtime config.
- `test_egp_metric_helpers_record_limiter_and_request_outcomes`: rollout metrics emit expected names/labels.

### Decision Completeness
- Goal: prevent multi-worker bursts against e-GP and expose throttling/circuit observability.
- Non-goals: no Playwright integration test with real Chrome, no DB schema changes, no UI changes.
- Success criteria: tests prove cross-thread/process-safe pacing, circuit reset, metrics, and worker wrappers are wired.
- Public interfaces: new env vars `EGP_EGP_RPS`, `EGP_EGP_BURST`, `EGP_EGP_CIRCUIT_429_THRESHOLD`, `EGP_EGP_CIRCUIT_RESET_SECONDS`.
- Edge cases: invalid env falls back to safe defaults; zero/negative RPS disables token waits but circuit still works; circuit-open acquisition waits by default and can fail fast in tests.
- Rollout: default RPS is 0.5 and burst 1, no feature flag; watch 429 rate, wait histogram, and crawl timeout behavior.
- Acceptance checks: focused pytest for new limiter and worker browser suites; ruff and compileall for touched Python.

### Dependencies
Uses stdlib `fcntl` for POSIX file locks; deployment target is Linux/macOS-compatible.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `rate_limiter.py` | worker browser action wrappers | imports in `browser_discovery.py` and `browser_downloads.py` | N/A |
| Env config | `RateLimiterConfig.from_env()` | default limiter factory in core module | Env vars listed above |
| Metrics helpers | worker wrappers | imports from `egp_observability.metrics` | existing Prometheus metrics |

## Plan Draft B

### Overview
Implement a worker-local in-memory limiter rather than a file-lock limiter. This is simpler and easier to test but does not coordinate multiple worker processes on the same host.

### Files To Change
- `apps/worker/src/egp_worker/rate_limiter.py`: in-memory token bucket and backoff.
- `apps/worker/src/egp_worker/browser_discovery.py`: wrap browser actions.
- `apps/worker/src/egp_worker/browser_downloads.py`: wrap browser actions.
- `tests/phase1/test_worker_rate_limiter.py`: unit tests only.

### Implementation Steps
1. Add failing unit tests for local pacing and circuit breaker.
2. Implement in-memory limiter.
3. Wire worker actions.
4. Run focused tests and lint.

### Test Coverage
- `test_worker_limiter_waits_between_actions`: local token bucket spaces calls.
- `test_worker_limiter_opens_circuit`: local 429 threshold opens.

### Decision Completeness
- Goal: reduce single-process request bursts.
- Non-goals: host-level coordination across subprocesses.
- Success criteria: one worker respects RPS.
- Public interfaces: same env vars.
- Edge cases: multiple workers can still exceed host RPS.
- Rollout: insufficient for PR-06's multi-worker pilot.
- Acceptance checks: unit tests only.

### Dependencies
No file locking, only stdlib time/threading.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| worker limiter | worker browser actions | imports in worker modules | N/A |

## Comparative Analysis
Draft A matches the rollout requirement because it coordinates all workers on a host using a shared lock file. Draft B has less code but fails the core operational need once `EGP_DISCOVERY_WORKER_COUNT` rises above one. Draft A is the correct implementation despite extra filesystem state.

## Unified Execution Plan

### Overview
Implement Draft A with a stdlib-only core rate limiter and worker-local observability wrappers. Keep retries explicit: only recovery/retry waits get exponential backoff and jitter, while DOM stabilization sleeps remain fixed.

### Files To Change
- `packages/crawler-core/src/egp_crawler_core/rate_limiter.py`: new core component.
- `packages/crawler-core/src/egp_crawler_core/__init__.py`: exports.
- `apps/worker/src/egp_worker/browser_discovery.py`: rate-limited goto/search/pagination plus retry backoff.
- `apps/worker/src/egp_worker/browser_downloads.py`: rate-limited download actions/request fallback plus retry backoff.
- `packages/observability/src/egp_observability/metrics.py`: `record_egp_request()` and `observe_rate_limiter_wait()`.
- `packages/observability/src/egp_observability/__init__.py`, `packages/observability/src/egp_metrics.py`: exports.
- `tests/concurrency/test_rate_limiter.py`: core concurrency and wiring tests.
- `tests/phase2/test_observability_metrics.py`: metrics helper assertions.

### TDD Sequence
1. Add `tests/concurrency/test_rate_limiter.py` and metrics helper test.
2. Run focused pytest and confirm RED.
3. Implement core limiter/backoff and metric helpers.
4. Wire worker wrappers around target e-GP operations.
5. Run focused tests until GREEN.
6. Run concurrency test three times, ruff, compileall, and formal review.

### Function Details
- `RateLimiterConfig.from_env()`: parse safe env defaults and create a shared state path under temp.
- `FileLockRateLimiter.acquire()`: lock state file, refill tokens, enforce circuit window, and return wait seconds.
- `FileLockRateLimiter.record_outcome()`: record `429` bursts and reset on successful outcomes.
- `exponential_backoff_delay()`: calculate bounded jittered retry delay.
- Worker `_run_egp_limited_action()`: acquire limiter, observe wait seconds, run browser action, classify outcome, and record request/circuit metrics.

### Test Coverage
- `test_file_lock_rate_limiter_limits_requests_across_workers`: stub server records timestamp spacing.
- `test_circuit_opens_after_429_burst_and_resets`: circuit fail-fast before reset and succeeds after.
- `test_rate_limiter_config_reads_environment`: env values wire to config.
- `test_browser_discovery_goto_and_search_use_rate_limiter`: worker actions call limiter.
- `test_browser_download_click_uses_rate_limiter`: download click path calls limiter.
- `test_egp_metric_helpers_record_limiter_and_request_outcomes`: metrics are emitted.

### Decision Completeness
- Goal: host-level request pacing and retry backoff before multi-worker throughput pilot.
- Non-goals: no real e-GP/browser integration, no new deployment manifest change, no schema/UI changes.
- Success criteria: one shared state file paces concurrent workers, circuit opens on 429 burst, worker call sites use the limiter, metrics expose waits/outcomes.
- Public interfaces: env vars `EGP_EGP_RPS`, `EGP_EGP_BURST`, `EGP_EGP_CIRCUIT_429_THRESHOLD`, `EGP_EGP_CIRCUIT_RESET_SECONDS`.
- Edge cases/failure modes: corrupt state is reset safely; lock file parent is created; circuit-open waits by default but tests can fail fast; metric import failure never breaks crawling.
- Rollout/monitoring: no feature flag; default `EGP_EGP_RPS=0.5`; watch `egp_egp_request_total{outcome="429"}`, `egp_rate_limiter_wait_seconds`, and crawl timeout rates.
- Acceptance checks: focused pytest for new limiter and affected worker suites, repeated concurrency test, ruff, compileall.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `rate_limiter.py` | `browser_discovery._run_egp_limited_action()` and `browser_downloads._run_egp_limited_action()` | module imports in worker browser files | N/A |
| Env config | `get_default_rate_limiter()` | called by worker wrappers | Env vars listed above |
| Metrics helpers | worker wrappers | imported from `egp_observability.metrics` | Prometheus registry |
| Tests | pytest | `tests/concurrency` and `tests/phase2` discovery | N/A |

### Cross-Language Schema Verification
No DB schema or cross-language contract changes are planned.

## Implementation Summary

- Added `egp_crawler_core.rate_limiter` with a file-lock token bucket, circuit breaker,
  env-backed configuration, default limiter factory, and jittered exponential backoff.
- Exported the limiter API from `egp_crawler_core`.
- Added Prometheus helper APIs for `egp_egp_request_total` and
  `egp_rate_limiter_wait_seconds`.
- Wrapped worker discovery e-GP navigation, search submit, pagination, detail-opening
  clicks, and recovery reloads through the limiter.
- Wrapped worker document download e-GP clicks, inferred viewer navigation, project
  detail reloads, and direct request fallback through the limiter.
- Kept DOM stabilization sleeps fixed and changed only retry/recovery waits to the
  backoff helper.
- Fixed a token-bucket state bug found during RED/GREEN: persisted `0.0` tokens must
  stay zero rather than falling back to a full burst.

## Verification

- RED: `pytest tests/concurrency/test_rate_limiter.py tests/phase2/test_observability_metrics.py -q -k 'rate_limiter or egp_request'`
  failed on missing `egp_crawler_core.rate_limiter`.
- GREEN: same focused test set: `7 passed, 8 deselected`.
- Existing worker browser suites:
  `pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_browser_downloads.py -q`
  passed twice; final post-format run was `113 passed`.
- Repeated PR-06 concurrency gate:
  `pytest tests/concurrency/test_rate_limiter.py -q` passed three consecutive runs
  with `6 passed` each run.
- `ruff format` completed; 5 files reformatted.
- `ruff check` passed for all touched Python files.
- `compileall packages/crawler-core/src packages/observability/src apps/worker/src`
  passed.

## Formal Review (g-check)

### Findings
No blocking correctness issues found in the staged PR-06 patch.

### Residual Risks
- Browser click paths cannot observe HTTP status codes directly, so 429 classification is
  exact for direct request fallback and exception messages, while normal Playwright
  click/navigation paths rely on limiter pacing and downstream page-state recovery.
- No live e-GP/Chrome integration test was run; coverage is focused on the file-lock
  limiter, circuit behavior, worker call-site wiring, metrics, and existing fake-page
  browser suites.

### Review Notes
- The file-lock token bucket persists host-shared state under the temp directory and
  handles corrupt or missing state by rebuilding a safe default state.
- The limiter bug found by the first GREEN attempt was fixed by preserving persisted
  `0.0` token values instead of treating them as absent.
- Metrics labels remain low-cardinality: request outcome only, and wait seconds as a
  histogram without tenant, keyword, or URL labels.
