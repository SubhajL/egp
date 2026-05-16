# Coding Log: Worker Dispatch Abstraction

## Plan Draft A - Concrete dispatcher object, preserve compatibility callable

### Overview
Introduce a real discovery worker dispatch abstraction while preserving the current subprocess behavior. Move subprocess launch ownership behind a `DiscoveryDispatcher.dispatch(...)` implementation and keep `app.state.discover_spawner` as a compatibility callable for the existing immediate discover path.

### Files to Change
- `apps/api/src/egp_api/services/discovery_dispatch.py`: change protocol from callable to dispatcher object and add request/value object if useful.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: new subprocess-backed dispatcher implementation wrapping current worker launch behavior.
- `apps/api/src/egp_api/main.py`: keep public factory compatibility while delegating to the new dispatcher implementation.
- `apps/api/src/egp_api/bootstrap/services.py`: instantiate one dispatcher and inject it into `DiscoveryDispatchProcessor`.
- `tests/phase2/test_discovery_dispatch.py`: prove processor depends on dispatcher object, not raw callable.
- `tests/phase1/test_api_discovery_spawn.py` and `tests/phase2/test_immediate_discover.py`: preserve worker payload/error behavior.

### TDD Sequence
1. Add/adjust tests for dispatcher object injection and subprocess dispatcher behavior.
2. Run focused tests and confirm failure due missing `dispatch` object contract / missing module.
3. Implement dispatcher protocol and subprocess-backed class.
4. Wire bootstrap to pass the dispatcher directly to `DiscoveryDispatchProcessor`.
5. Run focused gates, then ruff/compileall for touched Python code.

### Function / Class Notes
- `DiscoveryDispatcher.dispatch(...)`: dispatches one keyword discovery job; raises retriable or non-retriable exceptions as today.
- `SubprocessDiscoveryDispatcher.dispatch(...)`: owns run reservation, payload construction, worker subprocess launch, log capture, timeout/non-zero handling, and failure marking.
- `_make_discover_spawner(...)`: compatibility factory returning the subprocess dispatcher callable so existing route code and tests stay stable.

### Test Coverage
- `test_discovery_dispatch_processor_uses_dispatcher_object`: processor calls `.dispatch(...)` with job fields.
- Existing spawn tests: worker payload, run summary, timeout, non-zero, entitlement denial, profile settings remain unchanged.
- Bootstrap smoke, if available: app state exposes dispatcher and processor uses the same abstraction.

### Decision Completeness
- Goal: isolate worker launching behind a dispatcher abstraction.
- Non-goals: external queue backend, separate executor process, runtime mode flags, DB/schema changes.
- Success criteria: processor no longer invokes a raw callable; subprocess launch is in a named implementation; existing behavior tests pass.
- Public interfaces: no API endpoint, env var, CLI, migration, or schema changes.
- Edge cases/failure modes: timeout remains retriable dispatch failure; worker signal termination remains non-retriable; entitlement denial remains non-retriable; spawn exceptions still log keyword context.
- Rollout/backout: behavior-preserving refactor; revert PR if dispatcher wiring causes unexpected launch failures.
- Acceptance checks: focused pytest for dispatch/spawn tests, ruff on API, compileall on API.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `SubprocessDiscoveryDispatcher` | discovery queue loop and route kick call dispatcher/spawner | `configure_services()` via factory from `create_app()` | N/A |
| `DiscoveryDispatchProcessor` dispatcher dependency | `process_job()` | `app.state.discovery_dispatch_processor` | `discovery_jobs` repository only |

## Plan Draft B - Minimal adapter around existing callable

### Overview
Keep subprocess code in `egp_api.main` and add only a `CallableDiscoveryDispatcher` adapter that exposes `.dispatch(...)`. This is the smallest diff, but leaves worker launch behavior in the app entrypoint.

### Files to Change
- `apps/api/src/egp_api/services/discovery_dispatch.py`: add object protocol and callable adapter.
- `apps/api/src/egp_api/bootstrap/services.py`: wrap `discovery_dispatcher_factory(app)` with adapter.
- `tests/phase2/test_discovery_dispatch.py`: update fakes to object protocol.

### TDD Sequence
1. Add test requiring `.dispatch(...)` object protocol.
2. Run failing focused test.
3. Add adapter and processor change.
4. Run dispatch tests.

### Test Coverage
- Processor object protocol dispatch test.
- Existing callable-based spawn tests unchanged.

### Decision Completeness
- Goal: object abstraction with minimal code motion.
- Non-goals: moving subprocess launch out of `main.py`.
- Success criteria: processor only knows `.dispatch(...)`.
- Public interfaces: none.
- Edge cases/failure modes: unchanged because behavior code is unmoved.
- Rollout/backout: tiny refactor, low risk.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Callable adapter | `DiscoveryDispatchProcessor.process_job()` | `configure_services()` | N/A |

## Comparative Analysis
Draft A better matches PR 5's architectural intent because it makes worker dispatch a named implementation rather than hiding subprocess details in `main.py`. Draft B is safer as a tiny diff, but it under-delivers the phase goal and makes PR 6/7 extraction harder. Both preserve public behavior and avoid schema/runtime flag changes.

## Unified Execution Plan
Use Draft A, but preserve the old `_make_discover_spawner(...)` callable factory as a compatibility façade. This keeps the diff reviewable, unlocks later executor work, and avoids changing route code that still expects `app.state.discover_spawner`.

### Exact Steps
1. Add a failing processor test using an object with `.dispatch(...)`, not a callable.
2. Add a failing/import test or update spawn tests for `SubprocessDiscoveryDispatcher` if needed.
3. Implement protocol change in `discovery_dispatch.py`.
4. Create `discovery_worker_dispatcher.py` by moving subprocess dispatch logic out of `main.py` with the same helper behavior.
5. Change `main.py` to import/re-export the dispatcher factory and constant for test compatibility.
6. Change `configure_services()` to instantiate one dispatcher, store it on app state, keep `discover_spawner`, and pass dispatcher to processor.
7. Run focused tests: `tests/phase2/test_discovery_dispatch.py`, `tests/phase1/test_api_discovery_spawn.py`, selected immediate discover spawner tests.
8. Run `./.venv/bin/ruff check apps/api tests/phase1/test_api_discovery_spawn.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_immediate_discover.py` and `./.venv/bin/python -m compileall apps/api/src`.

### Acceptance Checks
- Processor tests pass and prove object protocol.
- Existing subprocess worker dispatch behavior tests pass unchanged or with import-only updates.
- Bootstrap still exposes `app.state.discover_spawner` for immediate route kick.
- No DB/schema/API/env changes.

### Decision-Complete Checklist
- No open product decisions remain.
- No changed public API surface.
- Behavior changes are covered by focused tests.
- Validation commands are scoped to touched files.
- Wiring table covers new dispatcher component.


## Implementation Update - 2026-05-16 09:40:08 

### Goal
Introduce PR 5's discovery worker dispatch abstraction while keeping current subprocess launch behavior unchanged.

### What Changed
- `apps/api/src/egp_api/services/discovery_dispatch.py`
  - Added `DiscoveryDispatchRequest` and changed `DiscoveryDispatcher` from a raw callable protocol to an object protocol with `dispatch(request)`.
  - `DiscoveryDispatchProcessor.process_job()` now builds a request object and dispatches through the abstraction.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
  - Added `SubprocessDiscoveryDispatcher`, which owns the existing worker subprocess launch, payload construction, log capture, timeout handling, non-zero handling, entitlement-denial parsing, and run failure marking.
- `apps/api/src/egp_api/main.py`
  - Slimmed worker-launch code out of the app entrypoint.
  - Kept `_make_discover_spawner(...)` and `DISCOVER_WORKER_TIMEOUT_SECONDS` as compatibility exports for existing tests/callers.
  - Added an app-state dispatcher object that preserves the prior behavior where tests/runtime can override `app.state.discover_spawner` after app creation.
- `apps/api/src/egp_api/bootstrap/services.py`
  - Wires `app.state.discovery_dispatcher` and injects that exact object into `DiscoveryDispatchProcessor`.
- `tests/phase2/test_discovery_dispatch.py`
  - Updated processor tests to require dispatcher objects and request values.
- `tests/phase1/test_high_risk_architecture.py`
  - Verifies app state exposes `discovery_dispatcher` and the processor uses it.
- `tests/phase1/test_api_discovery_spawn.py`
  - Updated subprocess monkeypatch targets to the new worker dispatcher module.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase1/test_high_risk_architecture.py::test_create_app_exposes_expected_bootstrap_state -q`
  - Failed during collection because `DiscoveryDispatchRequest` did not exist yet.
- GREEN focused: `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_high_risk_architecture.py::test_create_app_exposes_expected_bootstrap_state tests/phase2/test_immediate_discover.py::test_make_discover_spawner_logs_spawn_failure_with_keyword_context tests/phase2/test_immediate_discover.py::test_make_discover_spawner_logs_non_zero_exit_with_stderr_preview tests/phase2/test_immediate_discover.py::test_make_discover_spawner_logs_timeout_with_keyword_context tests/phase2/test_immediate_discover.py::test_make_discover_spawner_raises_non_retriable_error_for_entitlement_denial tests/phase2/test_immediate_discover.py::test_make_discover_spawner_forwards_profile_id_in_worker_payload tests/phase2/test_immediate_discover.py::test_make_discover_spawner_enables_live_document_collection_in_worker_payload -q`
  - Passed: 15 tests.
- GREEN widened: `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_immediate_discover.py -q`
  - Passed: 30 tests.

### Tests / Gates Run
- `./.venv/bin/ruff format apps/api/src/egp_api/main.py apps/api/src/egp_api/bootstrap/services.py apps/api/src/egp_api/services/discovery_dispatch.py apps/api/src/egp_api/services/discovery_worker_dispatcher.py tests/phase2/test_discovery_dispatch.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_immediate_discover.py`
- `./.venv/bin/ruff check apps/api/src/egp_api/main.py apps/api/src/egp_api/bootstrap/services.py apps/api/src/egp_api/services/discovery_dispatch.py apps/api/src/egp_api/services/discovery_worker_dispatcher.py tests/phase2/test_discovery_dispatch.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_immediate_discover.py`
- `./.venv/bin/python -m compileall apps/api/src`

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `SubprocessDiscoveryDispatcher` | `app.state.discover_spawner(...)` compatibility callable | `configure_services()` via `_make_discover_spawner(...)` from `create_app()` | N/A |
| app-state dispatcher object | `DiscoveryDispatchProcessor.process_job()` | `app.state.discovery_dispatcher` in `configure_services()` | N/A |
| `DiscoveryDispatchProcessor` | background loop / route-kick `processor.process_pending()` | `app.state.discovery_dispatch_processor` in `configure_services()` | `discovery_jobs` via existing repository |

### Behavior / Risk Notes
- No API, schema, env-var, or CLI surface changes.
- Retriable vs non-retriable worker failure behavior is intended to be unchanged.
- Preserved post-create override behavior for `app.state.discover_spawner`; this mattered for existing tests and is safer for local/runtime injection.
- During an early widened test run, the temporary wrong wiring launched real workers and created local `artifacts/`; those generated files were removed and are not part of the PR.

### Follow-ups / Known Gaps
- PR 6/7 can now replace the `SubprocessDiscoveryDispatcher` implementation or relocate executor ownership without changing `DiscoveryDispatchProcessor`.


## Review (2026-05-16 09:40:50 ) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree for PR 5 worker dispatch abstraction
- Commands Run:
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - targeted diff inspection for `main.py`, `bootstrap/services.py`, `discovery_dispatch.py`, and dispatch tests
  - `./.venv/bin/ruff check apps/api/src/egp_api/main.py apps/api/src/egp_api/bootstrap/services.py apps/api/src/egp_api/services/discovery_dispatch.py apps/api/src/egp_api/services/discovery_worker_dispatcher.py tests/phase2/test_discovery_dispatch.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_immediate_discover.py`
  - `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_immediate_discover.py -q`
  - `./.venv/bin/python -m compileall apps/api/src`

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Assumption: preserving `app.state.discover_spawner` override semantics is intentional until later PRs introduce explicit external executor/runtime mode flags.
- Assumption: keeping the logger name as `egp_api.main` in the extracted dispatcher is acceptable because it preserves existing test and operational log expectations.

### Recommended Tests / Validation
- Already run: focused dispatch tests, worker-spawn behavior tests, immediate-discover route-kick tests, high-risk architecture tests, ruff check, and API compileall.
- Before final PR merge: verify compact GitHub PR metadata/check status; per user instruction, broken GitHub Actions may be bypassed for merge.

### Rollout Notes
- No schema, API, env-var, or CLI changes.
- Behavior is intended to be refactor-only. Backout is a normal PR revert if worker dispatch or route-kick behavior regresses.
