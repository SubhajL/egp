# Coding Log: PR-CANARY-02 — Dispatcher Fault Injection

**Date:** 2026-08-06
**Slug:** pr-canary-02-fault-injection
**Status:** COMPLETE

## Goal

Add deterministic fault injection to the subprocess dispatcher so canary runs
can simulate real failure modes without hitting e-GP.

## Files Changed

1. `apps/api/src/egp_api/services/discovery_dispatch.py`
   - Added `fault_mode: str | None = None` field to `DiscoveryDispatchRequest` dataclass

2. `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
   - Added `_simulate_fault()` module-level function (47 lines) handling 5 fault modes + unknown fail-closed
   - Added call site in `dispatch_cancellable()` inside the payload try block, after `dispatch_started` event, before `json.dumps()`

3. `tests/phase1/test_structured_logging.py`
   - Added helper `_parse_structured_events()` for DRY event parsing across fault tests
   - Added helper `_make_fault_request()` for DRY request construction
   - T16: `test_fault_injection_worker_timeout` — DiscoverySpawnError with WORKER_TIMEOUT
   - T17: `test_fault_injection_nonzero_exit` — DiscoverySpawnError with WORKER_EXIT_NONZERO
   - T18: `test_fault_injection_missing_result` — DiscoverySpawnError with WORKER_RESULT_MISSING
   - T19: `test_fault_injection_entitlement_denied` — NonRetriableDiscoveryDispatchError with ENTITLEMENT_DENIED
   - T20: `test_fault_injection_unknown_mode_fails_closed` — ValueError on bogus mode
   - T21: `test_no_subprocess_spawned_during_fault_injection` — Popen never called for any valid fault mode

## Fault Modes

| fault_mode          | Exception raised                       | failure_code           |
|---------------------|----------------------------------------|------------------------|
| worker_timeout      | DiscoverySpawnError                    | WORKER_TIMEOUT         |
| nonzero_exit        | DiscoverySpawnError                    | WORKER_EXIT_NONZERO    |
| missing_result      | DiscoverySpawnError                    | WORKER_RESULT_MISSING  |
| entitlement_denied  | NonRetriableDiscoveryDispatchError     | ENTITLEMENT_DENIED     |
| worker_crash        | NonRetriableDiscoveryDispatchError     | WORKER_TERMINATED      |
| (unknown)           | ValueError                             | n/a                    |

## Design Decisions

- Fault injection is placed INSIDE the payload try block so the existing gap-cleanup
  handler (`except Exception:` at the payload level) flushes `pending_log_events`
  (containing both `dispatch_started` and `dispatch_failed`) and closes `log_handle`
  before re-raising. No existing exception handlers or finally blocks were modified.
- Each fault mode raises the FINAL exception type (the one the real handler would
  produce), not the intermediate exception (e.g., `DiscoverySpawnError` with
  `WORKER_TIMEOUT` instead of `subprocess.TimeoutExpired`), because the injection
  point is before the proc try block whose handlers do the conversion.
- Every simulated fault writes `dispatch_failed` with `reason="fault_injection"` and
  `injected_fault=<mode>` to `pending_log_events` BEFORE raising, enabling
  observability of injected faults in the structured log.

## Test Results

- 21/21 tests pass (15 existing + 6 new)
- ruff check: all checks passed
- 3x flakiness check: 21 passed x3 (0.83s, 0.54s, 0.56s)
