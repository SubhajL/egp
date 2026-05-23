# PR-02 Plan: Dispatcher Event Loop Unblock

Generated: 2026-05-23 12:23:22 Asia/Bangkok

Auggie semantic search unavailable: `codebase-retrieval` returned HTTP 429. This plan is based on direct file inspection plus exact-string searches. Inspected files:

- `AGENTS.md`
- `CLAUDE.md`
- `apps/api/AGENTS.md`
- `apps/api/src/egp_api/executors/discovery_dispatch.py`
- `apps/api/src/egp_api/bootstrap/background.py`
- `apps/api/src/egp_api/bootstrap/services.py`
- `apps/api/src/egp_api/routes/rules.py`
- `tests/phase2/test_discovery_executor.py`
- `tests/phase2/test_immediate_discover.py`
- `tests/phase2/test_rules_api.py`
- `tests/phase2/test_background_runtime_mode.py`

## Plan Draft A

### Overview

Move the synchronous discovery dispatch batch out of the asyncio event loop with `asyncio.to_thread`. Replace route-level dispatch execution with a wake signal so route handlers no longer start crawler dispatch work as FastAPI background tasks.

### Files To Change

- `apps/api/src/egp_api/executors/discovery_dispatch.py`: add non-blocking async loop execution and wake-event support.
- `apps/api/src/egp_api/bootstrap/background.py`: create and expose the discovery wake signal from lifespan.
- `apps/api/src/egp_api/routes/rules.py`: replace direct `process_pending` route kicks with a wake call.
- `tests/phase2/test_discovery_executor.py`: add event-loop responsiveness coverage.
- `tests/phase2/test_rules_api.py` or `tests/phase2/test_immediate_discover.py`: cover route wake behavior.

### Implementation Steps

TDD sequence:

1. Add a failing async test proving `run_discovery_dispatch_loop` does not block `asyncio.sleep(0.1)` while `process_pending` is blocked.
2. Add a failing route test proving route kicks call a wake signal and do not call `processor.process_pending`.
3. Implement the smallest loop change with `await asyncio.to_thread(run_discovery_dispatch_once, ...)`.
4. Add a small wake-signal helper that can be set from sync route handlers.
5. Wire the wake signal into lifespan and routes.
6. Run focused pytest, ruff, and compile checks.

Functions:

- `run_discovery_dispatch_loop`: process each batch in a worker thread and wait on either stop or wake events between polls.
- `DiscoveryDispatchWakeSignal.wake`: thread-safe wake method for sync FastAPI route handlers.
- `_wake_discovery_dispatch`: route helper that logs and writes the wake signal when enabled.

Edge behavior:

- If the wake signal is missing, route calls are no-ops rather than failing user requests.
- If the dispatcher raises, the existing warning path remains and the loop continues.
- If a wake happens during a batch, the next loop iteration runs without waiting for the full poll interval.

### Test Coverage

- `test_run_discovery_dispatch_loop_does_not_block_event_loop`: concurrent sleep completes while processor blocks.
- `test_profile_route_kick_writes_wake_signal_without_processing`: profile create wakes, no dispatch call.
- `test_update_route_kick_writes_wake_signal_without_processing`: profile update wakes, no dispatch call.
- `test_recrawl_route_kick_writes_wake_signal_without_processing`: manual recrawl wakes, no dispatch call.

### Decision Completeness

Goal: prevent discovery dispatch from blocking the API event loop and remove route-level background dispatch work.

Non-goals: no DB schema changes, no worker browser isolation, no admission control, no changes to dispatch claim ordering.

Success criteria:

- Async responsiveness test passes.
- Route tests prove route kicks write a wake signal instead of executing `process_pending`.
- Existing discovery executor and rules API tests pass after expectation updates.

Public interfaces:

- No API endpoint shape changes.
- No env vars or migrations.
- Internal app-state addition: `app.state.discovery_dispatch_wake_signal`.

Failure modes:

- Wake signal missing: fail open; request still succeeds and queued jobs wait for polling/external dispatcher.
- Dispatch batch raises: fail open with existing warning and retry on the next loop.
- Threadpool saturation: bounded to the dispatch loop path instead of the event loop; monitoring remains API p99 and threadpool depth.

Rollout and monitoring:

- No flag. Deploy after PR-01 observability baseline.
- Watch API p99 during crawls and Starlette threadpool depth.
- Roll back on latency regression or threadpool exhaustion.

Acceptance checks:

- `./.venv/bin/python -m pytest tests/phase2/test_discovery_executor.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
- `./.venv/bin/ruff check apps/api tests/phase2/test_discovery_executor.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py`
- `./.venv/bin/python -m compileall apps/api/src`

### Dependencies

No new package dependencies. Uses `asyncio.to_thread`, available in Python 3.12.

### Validation

Use deterministic tests with a thread-blocked fake processor and route-level fake wake signal.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `run_discovery_dispatch_loop` to-thread path | API lifespan and executor `_run_forever()` | `apps/api/src/egp_api/bootstrap/background.py` and `apps/api/src/egp_api/executors/discovery_dispatch.py` | N/A |
| `DiscoveryDispatchWakeSignal` | rules route helper calls `wake()` | `build_lifespan()` stores it on `app.state.discovery_dispatch_wake_signal` | N/A |
| route wake helper | `POST /v1/rules/profiles`, `PATCH /v1/rules/profiles/{id}`, `POST /v1/rules/recrawl` | `apps/api/src/egp_api/routes/rules.py` | `discovery_jobs` remains existing queue |

Cross-language schema verification: no schema or cross-language contract changes.

### Checklist

- No open decisions remain.
- Public interface changes are internal-only and listed.
- Every behavior change has at least one test.
- Validation commands are scoped to touched files.
- Wiring table covers each new runtime component.

## Plan Draft B

### Overview

Make the dispatch loop non-blocking with `asyncio.to_thread`, but avoid adding a dedicated wake-signal abstraction. Routes would call a raw `asyncio.Event` stored on app state.

### Files To Change

- `apps/api/src/egp_api/executors/discovery_dispatch.py`: add to-thread execution and optional wake event.
- `apps/api/src/egp_api/bootstrap/background.py`: store raw `asyncio.Event` on app state.
- `apps/api/src/egp_api/routes/rules.py`: call `wake_event.set()`.
- `tests/phase2/test_discovery_executor.py`: async responsiveness test.
- `tests/phase2/test_rules_api.py`: raw-event wake route tests.

### Implementation Steps

TDD sequence:

1. Add failing event-loop responsiveness test.
2. Add failing route wake test with fake event.
3. Wrap dispatch batch in `asyncio.to_thread`.
4. Store raw event on app state.
5. Call `.set()` from route handlers.
6. Run focused gates.

Functions:

- `run_discovery_dispatch_loop`: same as Draft A, but accepts a raw wake event.
- route helper: minimal helper that sets the event if present.

### Test Coverage

- `test_run_discovery_dispatch_loop_does_not_block_event_loop`: event loop remains responsive.
- `test_route_kick_sets_wake_event`: route writes event.

### Decision Completeness

Goal, non-goals, success criteria, rollout, and acceptance checks are the same as Draft A.

Public interfaces:

- Internal app-state addition: raw `asyncio.Event` or compatible object.

Failure modes:

- Raw event is not thread-safe when set from sync route handlers running in Starlette's threadpool. This is the key weakness.

### Dependencies

No new dependencies.

### Validation

Same as Draft A, but tests need to account for the raw-event thread-safety gap.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| raw wake event | rules route handlers | `build_lifespan()` | N/A |
| to-thread dispatch loop | API lifespan and executor `_run_forever()` | `background.py`, `discovery_dispatch.py` | N/A |

Cross-language schema verification: no schema changes.

### Checklist

- One open concern remains: thread-safe route writes to an asyncio primitive.

## Comparative Analysis

Draft A is safer because it hides event-loop thread affinity behind a tiny helper that can use `loop.call_soon_threadsafe`. It also gives tests a stable fake surface for route kicks.

Draft B is smaller, but it risks setting `asyncio.Event` from a worker thread because the route functions are synchronous. That would be brittle under ASGI execution and harder to reason about in production.

Both drafts preserve the PR scope, avoid migrations and external dependencies, and keep route user-facing responses unchanged.

## Unified Execution Plan

### Overview

Use Draft A. Implement the loop unblock with `asyncio.to_thread`, add a thread-safe `DiscoveryDispatchWakeSignal`, wire it through lifespan, and update route kicks to wake the loop rather than execute the processor.

### Files To Change

- `apps/api/src/egp_api/executors/discovery_dispatch.py`: add `DiscoveryDispatchWakeSignal`, optional wake support in loop, and to-thread dispatch.
- `apps/api/src/egp_api/bootstrap/background.py`: create a wake signal and expose it on app state while the embedded loop is running.
- `apps/api/src/egp_api/routes/rules.py`: remove `BackgroundTasks` route-kick execution and call `_wake_discovery_dispatch`.
- `tests/phase2/test_discovery_executor.py`: async responsiveness and wake-loop tests.
- `tests/phase2/test_rules_api.py` and/or `tests/phase2/test_immediate_discover.py`: update route-kick expectations to queued-plus-wake instead of immediate dispatch.

### Implementation Steps

TDD sequence:

1. Add event-loop responsiveness test; run it and confirm it fails because the sleep is blocked.
2. Add route wake test; run it and confirm it fails because current code calls `process_pending`.
3. Implement `DiscoveryDispatchWakeSignal` and `asyncio.to_thread` loop execution.
4. Wire `app.state.discovery_dispatch_wake_signal` from lifespan.
5. Replace route `BackgroundTasks` parameters and `background_tasks.add_task(processor.process_pending)` calls with wake-signal writes.
6. Update existing route-kick tests whose old expectation was immediate dispatch from SQLite route background tasks.
7. Run focused tests, ruff, compileall, and a final working-tree review.

Functions:

- `DiscoveryDispatchWakeSignal.__init__(loop, event)`: stores the event loop and event.
- `DiscoveryDispatchWakeSignal.wake()`: schedules `event.set()` via `loop.call_soon_threadsafe`.
- `DiscoveryDispatchWakeSignal.clear()`: clears the event from the loop owner.
- `run_discovery_dispatch_loop(..., wake_signal=None)`: runs batches in a thread and waits for stop or wake.
- `_wake_discovery_dispatch(request, job_count)`: no-op for zero jobs, disabled route kicks, or missing signal; otherwise logs and wakes.

Expected behavior:

- Embedded background dispatch no longer blocks the event loop.
- Routes return after queueing jobs; dispatch happens via the loop or external executor.
- SQLite tests move from immediate dispatch assertions to queue/wake assertions because no embedded loop exists for SQLite.

### Test Coverage

- `test_run_discovery_dispatch_loop_does_not_block_event_loop`: loop stays responsive during blocked dispatch.
- `test_run_discovery_dispatch_loop_wakes_before_poll_interval`: wake signal interrupts long poll wait.
- `test_profile_creation_writes_discovery_wake_signal`: profile create writes wake.
- `test_profile_update_writes_discovery_wake_signal`: profile update writes wake.
- `test_manual_recrawl_writes_discovery_wake_signal`: recrawl writes wake.
- Existing dispatch tests continue covering actual `DiscoveryDispatchProcessor.process_pending`.

### Decision Completeness

Goal: unblock the API event loop and remove route-triggered dispatch execution.

Non-goals: no new executor process, no browser isolation, no DB migrations, no new metrics beyond PR-01.

Success criteria:

- New responsiveness test proves `asyncio.sleep(0.1)` completes while dispatch is blocked.
- Route tests prove route kicks wake without directly invoking `process_pending`.
- Existing discovery queue persistence and processor tests pass.

Public interfaces:

- No endpoint, schema, env var, CLI flag, or migration changes.
- Internal app-state key: `discovery_dispatch_wake_signal`.

Failure modes:

- Missing wake signal: fail open, request still succeeds and queued jobs wait for poll/external executor.
- Wake before loop starts: fail open, event is absent and no request failure occurs.
- Dispatch error: fail open with warning and retry.
- Threadpool pressure: monitored operationally; code removes route background dispatch pressure.

Rollout and monitoring:

- No feature flag.
- Deploy for 48h observation.
- Watch API p99 during crawls and Starlette threadpool depth.
- Roll back on latency regression or threadpool exhaustion.

Acceptance checks:

- `./.venv/bin/python -m pytest tests/phase2/test_discovery_executor.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py -q`
- `./.venv/bin/ruff check apps/api tests/phase2/test_discovery_executor.py tests/phase2/test_rules_api.py tests/phase2/test_immediate_discover.py`
- `./.venv/bin/python -m compileall apps/api/src`

### Dependencies

No new dependencies.

### Validation

Focused pytest for dispatcher loop and route rules. Ruff and compileall for touched Python paths.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `DiscoveryDispatchWakeSignal` | `_wake_discovery_dispatch()` in rules routes | `build_lifespan()` assigns `app.state.discovery_dispatch_wake_signal` | N/A |
| `run_discovery_dispatch_loop` to-thread batch | API lifespan and `python -m egp_api.executors.discovery_dispatch` | `background.py` and `_run_forever()` | N/A |
| route wake helper | profile create/update and manual recrawl routes | direct calls in `routes/rules.py` | existing `discovery_jobs` queue |

Cross-language schema verification: no DB migration, no table or column names changed.

### Decision-Complete Checklist

- No open decisions remain for implementation.
- Public/internal interface changes are listed.
- Behavior changes have failing tests planned.
- Validation commands are specific and scoped.
- Wiring table covers all new components.

## Implementation Summary (2026-05-23 12:31:26 +07)

### Goal

Implement PR-02 by preventing synchronous discovery dispatch work from blocking the API event loop, and by replacing route-level background dispatch execution with a wake-signal write.

### What Changed

- `apps/api/src/egp_api/executors/discovery_dispatch.py`: added `DiscoveryDispatchWakeSignal`, moved `run_discovery_dispatch_once` behind `asyncio.to_thread`, and added wake-aware polling between dispatch batches.
- `apps/api/src/egp_api/bootstrap/background.py`: changed route-kick enablement to embedded-loop backends, created the wake signal during lifespan startup, and passed it into the dispatch loop.
- `apps/api/src/egp_api/routes/rules.py`: removed `BackgroundTasks` dispatch calls and added `_wake_discovery_dispatch`.
- `tests/phase2/test_dispatcher_event_loop.py`: added event-loop responsiveness and wake-before-poll coverage.
- `tests/phase2/test_immediate_discover.py`, `tests/phase2/test_rules_api.py`, `tests/phase2/test_background_runtime_mode.py`: updated expectations from inline route dispatch to queued jobs plus wake signaling.

### TDD Evidence

RED:

- `./.venv/bin/python -m pytest tests/phase2/test_dispatcher_event_loop.py::test_run_discovery_dispatch_loop_does_not_block_event_loop -q`
- Result: failed in 5.24s because `asyncio.sleep(0.1)` resumed after the blocking dispatch call finished.

RED:

- `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py::test_profile_creation_writes_wake_signal_without_inline_dispatch -q`
- Result: failed because the route still executed `processor.process_pending` as a Starlette background task.

GREEN:

- `./.venv/bin/python -m pytest tests/phase2/test_dispatcher_event_loop.py tests/phase2/test_discovery_executor.py tests/phase2/test_immediate_discover.py tests/phase2/test_rules_api.py tests/phase2/test_background_runtime_mode.py -q`
- Result: 38 passed in 1.75s.

### Tests And Checks Run

- `./.venv/bin/ruff check apps/api tests/phase2/test_dispatcher_event_loop.py tests/phase2/test_discovery_executor.py tests/phase2/test_immediate_discover.py tests/phase2/test_rules_api.py tests/phase2/test_background_runtime_mode.py` - passed.
- `./.venv/bin/python -m compileall apps/api/src` - passed.
- `./.venv/bin/python scripts/check_main_sync.py --json` - main and origin/main synced, but command exited nonzero because the working tree is intentionally dirty before commit plus pre-existing unrelated local files.

### Wiring Verification Evidence

- Runtime dispatch entry point remains `build_lifespan()` and standalone `_run_forever()`.
- `build_lifespan()` stores `app.state.discovery_dispatch_wake_signal` and passes it to `run_discovery_dispatch_loop`.
- Rules routes call `_wake_discovery_dispatch()` after successful queueing for profile create, profile update, and manual recrawl.

### Behavior And Risk Notes

- Fail open if no wake signal is registered; queued jobs remain available for polling or the external dispatcher.
- Dispatch exceptions retain the existing warning-and-continue behavior.
- No endpoint schema, env var, CLI flag, or migration changes.

### Follow-Ups

- Observation should follow the rollout plan: API p99 during crawls and Starlette threadpool depth for 48h.

## Review (2026-05-23 12:35:00 +07) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `fix/dispatcher-event-loop-unblock`
- Scope: working tree for PR-02 files; pre-existing `coding-logs/2026-05-21-12-22-11 Coding Log (monthly-discovery-crawl-hardening).md` and `egp-dev-logs` excluded from PR scope.
- Commit base: `67fbe422`
- Commands Run: Auggie review context request (HTTP 429), targeted `git diff`, targeted `nl -ba` inspections, focused pytest, ruff, compileall.

### Findings

CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings after changing discovery lifespan shutdown to set the stop event, wake the loop, and await completion instead of cancelling the `asyncio.to_thread` waiter.

LOW
- No findings.

### Open Questions / Assumptions

- Assumption: route-kick semantics now mean "wake embedded dispatcher loop" rather than "execute dispatch inline"; SQLite/local tests were updated to queue jobs without route dispatch because SQLite does not run the embedded loop.

### Recommended Tests / Validation

- Already run: `./.venv/bin/python -m pytest tests/phase2/test_dispatcher_event_loop.py tests/phase2/test_discovery_executor.py tests/phase2/test_immediate_discover.py tests/phase2/test_rules_api.py tests/phase2/test_background_runtime_mode.py -q` - 38 passed.
- Already run: `./.venv/bin/ruff check apps/api tests/phase2/test_dispatcher_event_loop.py tests/phase2/test_discovery_executor.py tests/phase2/test_immediate_discover.py tests/phase2/test_rules_api.py tests/phase2/test_background_runtime_mode.py` - passed.
- Already run: `./.venv/bin/python -m compileall apps/api/src` - passed.

### Rollout Notes

- No feature flag or migration.
- Watch API p99 during crawls and Starlette threadpool depth during the 48h observation window.
- Roll back on latency regression or threadpool exhaustion per PR-02 rollout plan.
