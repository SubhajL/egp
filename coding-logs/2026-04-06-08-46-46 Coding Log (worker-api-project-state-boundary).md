# Plan Draft A

## Overview

Move project discovery and closure state writes behind an API-owned ingest service while leaving crawl run/task tracking in the worker. The worker will classify crawl results and emit typed discovery/closure events; the API service will validate those events, persist project changes, and trigger notifications.

## Files to Change

- `packages/shared-types/src/egp_shared_types/project_events.py`: shared typed worker-to-API event contract.
- `packages/shared-types/src/egp_shared_types/__init__.py`: export shared event types if needed by callers/tests.
- `apps/api/src/egp_api/services/project_ingest_service.py`: API-owned write orchestration for discovered projects and close-check events.
- `apps/api/src/egp_api/routes/project_ingest.py`: HTTP ingress for worker-emitted project events.
- `apps/api/src/egp_api/main.py`: register the new service and router.
- `apps/worker/src/egp_worker/project_event_sink.py`: sink protocol plus adapters the worker can emit into.
- `apps/worker/src/egp_worker/workflows/discover.py`: replace direct project upsert calls with event emission.
- `apps/worker/src/egp_worker/workflows/close_check.py`: replace direct project transition calls with event emission.
- `tests/phase1/test_worker_workflows.py`: assert worker emits and records run/task outcomes without owning project persistence.
- `tests/phase1/test_projects_and_runs_api.py`: assert API ingest endpoints/services apply state transitions and notifications.

## Implementation Steps

### TDD sequence

1. Add/stub API ingest tests and worker emission tests.
2. Run the targeted pytest commands and confirm they fail because the ingest surface and sink abstraction do not exist yet.
3. Implement the shared event contract, API ingest service/routes, and worker sink changes with the smallest passing slice.
4. Refactor minimally to keep route/service/worker responsibilities clear.
5. Run focused compile, lint, and pytest gates for `apps/api`, `apps/worker`, and `packages/shared-types`.

### Functions / classes

- `DiscoveredProjectEvent`: typed event carrying worker-classified discovery payload for API ingestion.
- `CloseCheckProjectEvent`: typed event carrying worker-classified closure evidence and requested reason.
- `ProjectIngestService.ingest_discovered_project()`: build the upsert record, detect create-vs-update, persist the project, and dispatch new-project notifications when appropriate.
- `ProjectIngestService.ingest_close_check_event()`: validate the closure reason, transition the project through repository/domain rules, and dispatch winner/contract notifications.
- `ProjectEventSink.record_discovery()`: worker-side abstraction for emitting a discovery event.
- `ProjectEventSink.record_close_check()`: worker-side abstraction for emitting a close-check event.
- `ServiceBackedProjectEventSink`: adapter that delegates event handling to the API-owned ingest service for local/test execution.
- `ApiProjectEventSink`: HTTP adapter for calling the API ingress routes when remote wiring is desired.

### Expected behavior and edge cases

- Discover flow still records crawl run/tasks in the worker, but the project write now happens behind the API ingest surface.
- Close-check flow may still classify `closed_reason` in the worker, but the API service decides the persisted next state.
- Discover events for existing projects should upsert without firing a duplicate new-project notification.
- Close-check observations with no matched closure remain skipped and do not call the API ingest service.
- Invalid closure reasons or missing target projects fail closed at the API service and are surfaced back into task `result_json`.

## Test Coverage

- `tests/phase1/test_worker_workflows.py::test_discover_workflow_emits_project_events_and_records_run_tasks`
  Worker emits discovery events instead of upserting directly.
- `tests/phase1/test_worker_workflows.py::test_close_check_workflow_emits_close_events_after_reason_match`
  Worker emits closure events only for matched statuses.
- `tests/phase1/test_projects_and_runs_api.py::test_project_ingest_endpoint_upserts_discovered_project`
  API owns discover persistence and response payload.
- `tests/phase1/test_projects_and_runs_api.py::test_project_ingest_endpoint_transitions_close_check_project`
  API owns closure transition and resulting project state.
- `tests/phase1/test_projects_and_runs_api.py::test_project_ingest_endpoint_preserves_notification_behavior`
  Notifications still fire from API-owned writes.

## Decision Completeness

- Goal: stop the worker from directly mutating project state while preserving current discover/close-check behavior.
- Non-goals: scheduler transport, durable event bus, document-ingest redesign, or changing crawl run/task ownership.
- Success criteria:
  - Worker workflows no longer import or call `SqlProjectRepository.upsert_project()` or `transition_project()`.
  - API service/route owns discover and close-check project persistence.
  - Existing notification behavior remains covered by tests.
  - Focused worker/API tests pass on the new boundary.
- Public interfaces:
  - New API endpoints for worker project ingest.
  - New shared Python event contract module.
  - No schema or migration changes.
- Edge cases / failure modes:
  - Unknown close reason: fail closed with `ValueError`.
  - Missing project during close-check: fail closed with `KeyError`.
  - Existing discovered project: upsert succeeds, notification suppressed.
  - Worker emits no close event when closure text does not match.
- Rollout & monitoring:
  - Backward-compatible code path via service-backed sink for local callers/tests.
  - Watch task failure payloads and API 4xx/5xx responses on ingest routes.
  - Backout is a revert of the ingest service/sink refactor; no schema rollback needed.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_projects_and_runs_api.py -q`
  - `./.venv/bin/ruff check apps/api apps/worker packages/shared-types`
  - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src`

## Dependencies

- Existing `SqlProjectRepository`, `SqlRunRepository`, and notification dispatcher behavior.
- Existing FastAPI auth/tenant resolution patterns for ingest routes.

## Validation

Verify the worker tests no longer depend on project repository writes, then verify the API ingest tests prove the state changes still happen. Confirm `create_app()` wires the new service/router and the worker sink has at least one non-test call site.

## Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `project_events.py` | worker workflows build typed events before emitting | imported by worker workflow modules and API ingest service/routes | `projects`, `project_aliases`, `project_status_events` |
| `ProjectIngestService` | called by API route handlers and local service-backed sink | `apps/api/src/egp_api/main.py` sets `app.state.project_ingest_service` | `projects`, `project_status_events` |
| `project_ingest.py` routes | HTTP POST from worker or tests | `apps/api/src/egp_api/main.py` `include_router()` | `projects`, `project_status_events` |
| `ServiceBackedProjectEventSink` | called from `run_discover_workflow()` and `run_close_check_workflow()` | worker workflow imports/constructs sink | `projects`, `project_status_events` |
| `ApiProjectEventSink` | called from worker when remote API base URL is configured | explicit construction by caller/test; no implicit global wiring | HTTP API only |

## Cross-Language Schema Verification

- Verified project state writes still target existing repository tables only: `projects`, `project_aliases`, `project_status_events`.
- No migration or enum additions are planned for this change.

# Plan Draft B

## Overview

Refactor the worker workflows to become pure event producers and return typed event results, while API-side tests and routes cover all project-state persistence. This is a stricter separation than Draft A but requires more call-site change because existing local callers need to provide a sink explicitly.

## Files to Change

- `packages/shared-types/src/egp_shared_types/project_events.py`: event dataclasses and result types.
- `apps/api/src/egp_api/services/project_ingest_service.py`: API-owned state transition orchestration.
- `apps/api/src/egp_api/routes/project_ingest.py`: ingress routes for discovery and closure events.
- `apps/api/src/egp_api/main.py`: wire service and route.
- `apps/worker/src/egp_worker/workflows/discover.py`: emit-only behavior with required sink dependency.
- `apps/worker/src/egp_worker/workflows/close_check.py`: emit-only behavior with required sink dependency.
- `tests/phase1/test_worker_workflows.py`: fake sink assertions only.
- `tests/phase1/test_projects_and_runs_api.py`: API ingest coverage.

## Implementation Steps

### TDD sequence

1. Add failing tests that require a sink for both worker workflows.
2. Add failing API ingest tests.
3. Implement shared events and API ingest service/routes.
4. Refactor worker workflows to require an injected sink and remove all project repository imports.
5. Run focused gates and wiring checks.

### Functions / classes

- `ProjectEventSink`: required worker protocol for discover/closure emission.
- `ProjectIngestService.ingest_discovered_project()`: API-owned discover persistence.
- `ProjectIngestService.ingest_close_check_event()`: API-owned closure persistence.

### Expected behavior and edge cases

- Worker code becomes transport-agnostic and cannot mutate project state without a sink.
- Local tests must inject a fake or service-backed sink.
- Missing sink fails fast at workflow entry.

## Test Coverage

- `test_discover_workflow_requires_sink_and_records_failures`
  Missing sink is rejected immediately.
- `test_discover_workflow_emits_discovery_events`
  Discovery payload emission is preserved.
- `test_close_check_workflow_emits_only_matched_closure_events`
  Non-matching closure observations are skipped.
- `test_project_ingest_api_owns_project_upsert`
  API owns discover persistence.
- `test_project_ingest_api_owns_project_transition`
  API owns closure transition.

## Decision Completeness

- Goal: establish a hard separation where worker code cannot write project state.
- Non-goals: adding an async queue or a durable event bus.
- Success criteria:
  - Worker workflows import no project repository code.
  - All state mutations live behind API ingest service/routes.
  - Tests prove sink-required worker behavior and API-owned persistence.
- Public interfaces:
  - New API ingest endpoints.
  - Required worker sink dependency.
- Edge cases / failure modes:
  - Missing sink: fail closed at workflow startup.
  - Invalid closure reason or missing project: API returns failure and task is marked failed.
- Rollout & monitoring:
  - Higher integration cost because every caller must provide a sink immediately.
  - Same observability target: worker task results and ingest route failures.
- Acceptance checks:
  - same focused pytest/lint/compile commands as Draft A.

## Dependencies

- Existing repository and notification behavior.
- Callers updated to provide a sink.

## Validation

Verify worker workflows are impossible to run without a sink and that API routes provide the only available write path for project state.

## Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `ProjectEventSink` | worker workflow function parameters | explicit caller injection only | N/A |
| `ProjectIngestService` | API route handlers | `apps/api/src/egp_api/main.py` | `projects`, `project_status_events` |
| `project_ingest.py` routes | HTTP POST from worker | `apps/api/src/egp_api/main.py` `include_router()` | `projects`, `project_status_events` |

## Cross-Language Schema Verification

- No schema changes planned.

# Comparative Analysis & Synthesis

## Strengths

- Draft A preserves local usability and current tests with a service-backed sink while still moving state ownership behind an API service.
- Draft B creates a cleaner hard boundary and removes the last implicit local write path from worker execution.

## Gaps

- Draft A still allows in-process service delegation, so transport isolation is not complete.
- Draft B creates avoidable churn because the repo does not yet have a real worker runtime/composition layer that can supply the sink everywhere.

## Trade-offs

- Draft A optimizes for incremental migration and lower breakage.
- Draft B optimizes for stricter architecture purity at the cost of immediate integration burden.

## Compliance Check

- Both drafts respect the PRD rule that the worker should stop owning product state transitions.
- Draft A better matches current repo maturity because it preserves thin app entrypoints and tests-first delivery without inventing an event bus.

# Unified Execution Plan

## Overview

Implement an API-owned project ingest service and route for discovery/closure events, then refactor the worker workflows to emit typed events into a sink abstraction instead of calling project repositories directly. Use a service-backed sink as the default local adapter so the repo can migrate now without waiting for a full remote worker transport layer.

## Files to Change

- `packages/shared-types/src/egp_shared_types/project_events.py`: shared worker/API event contract.
- `packages/shared-types/src/egp_shared_types/__init__.py`: export event types.
- `apps/api/src/egp_api/services/project_ingest_service.py`: API-owned discover and close-check persistence orchestration.
- `apps/api/src/egp_api/routes/project_ingest.py`: worker-facing HTTP ingress.
- `apps/api/src/egp_api/main.py`: instantiate/register the service and route.
- `apps/worker/src/egp_worker/project_event_sink.py`: protocol plus service-backed and HTTP adapters.
- `apps/worker/src/egp_worker/workflows/discover.py`: emit discovery events through the sink.
- `apps/worker/src/egp_worker/workflows/close_check.py`: emit close-check events through the sink.
- `tests/phase1/test_worker_workflows.py`: convert to fake-sink assertions and run/task behavior checks.
- `tests/phase1/test_projects_and_runs_api.py`: add API ingest tests for discover/close-check ownership and notification continuity.

## Implementation Steps

### TDD sequence

1. Add worker tests that fail because `project_event_sink` and typed project events do not exist.
2. Add API tests that fail because project ingest routes/service do not exist.
3. Implement shared event dataclasses and worker sink protocol/adapters.
4. Implement `ProjectIngestService` and the FastAPI routes that call it.
5. Refactor discover/close-check workflows to build typed events and delegate all project writes to the sink.
6. Run targeted worker/API tests, then `ruff` and `compileall` on touched areas.

### Functions / classes

- `DiscoveredProjectEvent`
  Normalized worker discovery payload, including worker-classified project state and source text.
- `CloseCheckProjectEvent`
  Normalized closure evidence with `project_id`, `closed_reason`, and source text.
- `ProjectIngestService.ingest_discovered_project()`
  Validates the event, uses `build_project_upsert_record()`, detects new-vs-existing records, persists the project, and dispatches `NEW_PROJECT` only on first creation.
- `ProjectIngestService.ingest_close_check_event()`
  Maps close reasons to next states, runs repository transition logic, and dispatches winner/contract notifications from the API layer.
- `ProjectEventSink.record_discovery()` / `record_close_check()`
  Worker-side event emission contract.
- `ServiceBackedProjectEventSink`
  Local adapter that calls `ProjectIngestService` directly for tests and in-process execution.
- `ApiProjectEventSink`
  Optional HTTP adapter for remote worker-to-API calls.

### Expected behavior and edge cases

- Worker workflows still own run/task lifecycle bookkeeping only.
- Discover tasks mark success with API-owned project ids in `result_json`.
- Close-check tasks skip non-matching statuses before calling the sink.
- API ingest rejects invalid closure reasons or unknown target projects instead of silently mutating state.
- Notification behavior remains unchanged, but it now fires from API-owned state writes.

## Test Coverage

- `tests/phase1/test_worker_workflows.py::test_discover_workflow_emits_project_events_and_records_run_tasks`
  Worker emits discovery events and stores run/task evidence.
- `tests/phase1/test_worker_workflows.py::test_close_check_workflow_emits_close_events_after_reason_match`
  Worker emits closure events only when rule matching succeeds.
- `tests/phase1/test_worker_workflows.py::test_close_check_workflow_skips_non_matching_status_without_sink_call`
  Non-matching status does not hit the sink.
- `tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_upserts_and_notifies_new_projects`
  API ingest owns discovery persistence and notification gating.
- `tests/phase1/test_projects_and_runs_api.py::test_project_ingest_close_check_endpoint_transitions_project_state`
  API ingest owns closure transitions and resulting state.

## Decision Completeness

- Goal: restore the documented boundary by removing direct worker ownership of project state transitions.
- Non-goals: add a durable event bus, redesign document ingestion, or move crawl-run persistence into the API.
- Success criteria:
  - `discover.py` and `close_check.py` no longer import `SqlProjectRepository`, `build_project_upsert_record()`, or `transition_project()`.
  - API service/route owns all discover and close-check project writes.
  - Worker and API tests cover the new contract and pass.
  - Runtime wiring is explicit in `create_app()` and the worker sink module.
- Public interfaces:
  - New API routes for project discovery and close-check ingestion.
  - New shared event dataclasses and worker sink adapter module.
  - No migration, env var, or DB schema changes in this slice.
- Edge cases / failure modes:
  - Discover event missing required identity fields: fail closed with `ValueError`.
  - Close-check event with unsupported reason: fail closed with `ValueError`.
  - Close-check event for unknown project: fail closed with `KeyError`.
  - Existing project rediscovered: upsert succeeds, `NEW_PROJECT` notification suppressed.
  - Non-matching close-check status: task marked `skipped`, no API call.
- Rollout & monitoring:
  - Roll out as an internal refactor with HTTP ingress available for remote composition later.
  - Monitor worker task failures and API ingest failures; these are the new boundary health signals.
  - Backout is code-only revert; schema is unchanged.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_projects_and_runs_api.py -q`
  - `./.venv/bin/ruff check apps/api apps/worker packages/shared-types`
  - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src`

## Dependencies

- `SqlProjectRepository` and `SqlRunRepository` remain the persistence layer.
- Existing FastAPI auth/tenant resolution and notification dispatcher wiring in `create_app()`.

## Validation

1. Run worker tests to confirm worker emits events and retains run/task bookkeeping.
2. Run API tests to confirm discover and close-check persistence moved behind the ingest service/routes.
3. Run compile and lint gates on touched directories.
4. Grep for worker-side `upsert_project` / `transition_project` imports to verify the direct boundary violation is gone.

## Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `packages/shared-types/src/egp_shared_types/project_events.py` | imported by worker workflows, sink adapters, and API ingest service | package export via `egp_shared_types` | `projects`, `project_aliases`, `project_status_events` |
| `apps/api/src/egp_api/services/project_ingest_service.py` | route handlers and service-backed sink call its methods at runtime | `apps/api/src/egp_api/main.py` attaches `app.state.project_ingest_service` | `projects`, `project_status_events` |
| `apps/api/src/egp_api/routes/project_ingest.py` | HTTP POST endpoints receive worker discovery/close-check events | `apps/api/src/egp_api/main.py` `include_router(project_ingest_router)` | `projects`, `project_status_events` |
| `apps/worker/src/egp_worker/project_event_sink.py` | worker workflows call `record_discovery()` / `record_close_check()` | imported and constructed inside `discover.py` / `close_check.py` or injected by callers | HTTP or service delegation only |
| `apps/worker/src/egp_worker/workflows/discover.py` | called by worker runtime/tests | `apps/worker/src/egp_worker/main.py` imports workflow symbol | `crawl_runs`, `crawl_tasks` only directly |
| `apps/worker/src/egp_worker/workflows/close_check.py` | called by worker runtime/tests | `apps/worker/src/egp_worker/main.py` imports workflow symbol | `crawl_runs`, `crawl_tasks` only directly |

## Cross-Language Schema Verification

- Verified via repository inspection that this change only uses existing Python-side tables `projects`, `project_aliases`, `project_status_events`, `crawl_runs`, and `crawl_tasks`.
- No migration or enum-storage change is required for the chosen implementation.

# Implementation Summary

## 2026-04-06 08:52:23 +07

- Goal: restore the documented worker/API boundary so discover and close-check project writes are API-owned instead of worker-owned.
- What changed:
  - `packages/shared-types/src/egp_shared_types/project_events.py`
    Added shared `DiscoveredProjectEvent` and `CloseCheckProjectEvent` contracts for worker-to-API project state communication.
  - `packages/shared-types/src/egp_shared_types/__init__.py`
    Exported the shared project event contracts.
  - `apps/api/src/egp_api/services/project_ingest_service.py`
    Added API-owned orchestration for discovered-project upserts and close-check transitions, including notification dispatch.
  - `apps/api/src/egp_api/routes/project_ingest.py`
    Added worker-facing ingest routes for discovery and close-check events.
  - `apps/api/src/egp_api/main.py`
    Wired `ProjectIngestService` into `app.state` and registered the new ingest router.
  - `apps/worker/src/egp_worker/project_event_sink.py`
    Added the worker sink protocol and a service-backed adapter that delegates project writes to the API-owned service.
  - `apps/worker/src/egp_worker/workflows/discover.py`
    Removed direct project repository usage; the workflow now emits `DiscoveredProjectEvent` instances into the sink while still owning crawl run/task bookkeeping.
  - `apps/worker/src/egp_worker/workflows/close_check.py`
    Removed direct project transition calls; the workflow now emits `CloseCheckProjectEvent` instances into the sink after status classification.
  - `tests/phase1/test_worker_workflows.py`
    Reworked worker tests to assert event emission, run/task persistence, skip behavior, and the default service-backed sink path.
  - `tests/phase1/test_projects_and_runs_api.py`
    Added API ingest tests proving discovery upserts, close-check transitions, and notification continuity.
- TDD evidence:
  - RED command:
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q`
  - RED failure reason:
    - `ModuleNotFoundError: No module named 'egp_shared_types.project_events'`
  - GREEN commands:
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q`
    - `./.venv/bin/ruff check apps/api/src/egp_api/main.py apps/api/src/egp_api/routes/project_ingest.py apps/api/src/egp_api/services/project_ingest_service.py apps/worker/src/egp_worker/project_event_sink.py apps/worker/src/egp_worker/workflows/discover.py apps/worker/src/egp_worker/workflows/close_check.py packages/shared-types/src/egp_shared_types/__init__.py packages/shared-types/src/egp_shared_types/project_events.py tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py`
    - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src`
- Tests run and results:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q` -> `12 passed`
  - `./.venv/bin/ruff check ...` -> passed
  - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src` -> passed
- Wiring verification evidence:
  - `apps/api/src/egp_api/main.py` now sets `app.state.project_ingest_service` and `include_router(project_ingest_router)`.
  - `apps/worker/src/egp_worker/workflows/discover.py` and `apps/worker/src/egp_worker/workflows/close_check.py` now call `project_event_sink`.
  - `rg -n "upsert_project\\(|transition_project\\(|build_project_upsert_record\\(" apps/worker/src/egp_worker -g '*.py'` returned no matches, confirming the worker no longer owns direct project state writes.
- Behavior changes and risk notes:
  - Discover and close-check project mutations now pass through the API-owned ingest service.
  - Worker still owns crawl run/task persistence; that operational state remains local to the worker plane.
  - This is intentionally fail-closed for invalid closure reasons or unknown close-check targets because the API service raises rather than silently mutating state.
- Follow-ups / known gaps:
  - The repo now has an HTTP ingest route, but the default worker sink is still an in-process service-backed adapter. A future runtime composition pass can swap that adapter for a remote API transport without reopening the project-state ownership problem.

## 2026-04-06 09:09:29 +07

- Goal: replace the worker’s placeholder/local project-event delegation with a real remote HTTP transport to the API ingest routes.
- What changed:
  - `apps/worker/src/egp_worker/config.py`
    Added worker-side config helpers for `EGP_API_BASE_URL`, `EGP_API_BEARER_TOKEN`, and `EGP_API_TIMEOUT_SECONDS`.
  - `apps/worker/src/egp_worker/project_event_sink.py`
    Added `ApiProjectEventSink`, response decoding, transport error handling, env-driven sink selection, and moved service-backed API imports behind an explicit fallback helper so the worker no longer eagerly imports API code.
  - `apps/api/src/egp_api/routes/project_ingest.py`
    Tightened the worker-facing ingest routes to require a support-role token when auth is enabled and to allow support-role tenant override for cross-tenant worker traffic.
  - `apps/worker/pyproject.toml`
    Added runtime `httpx` dependency for the worker transport.
  - `apps/worker/Dockerfile`
    Added `httpx` to the worker image install set.
  - `tests/phase1/test_worker_workflows.py`
    Added end-to-end remote transport tests for discovery and close-check using `ApiProjectEventSink` against an auth-enabled FastAPI app.
- TDD evidence:
  - RED run:
    - No separate RED run was captured for this incremental continuation. I extended the already-green boundary refactor directly into the transport implementation and verified it with new end-to-end tests afterward.
  - GREEN commands:
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q`
    - `./.venv/bin/ruff check apps/api/src/egp_api/routes/project_ingest.py apps/worker/src/egp_worker/config.py apps/worker/src/egp_worker/project_event_sink.py apps/worker/src/egp_worker/workflows/discover.py tests/phase1/test_worker_workflows.py apps/worker/pyproject.toml`
    - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src`
    - `./.venv/bin/python -c "import egp_worker.project_event_sink as sink; print('import-ok', hasattr(sink, 'ApiProjectEventSink'))"`
- Tests run and results:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q` -> `14 passed`
  - `./.venv/bin/ruff check ...` -> passed
  - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src` -> passed
  - `./.venv/bin/python -c "import egp_worker.project_event_sink as sink; print('import-ok', hasattr(sink, 'ApiProjectEventSink'))"` -> `import-ok True`
- Wiring verification evidence:
  - Worker sink selection now prefers `EGP_API_BASE_URL` and creates `ApiProjectEventSink` for real HTTP transport.
  - The API ingest routes accept authenticated worker traffic with `require_support_role()` and `allow_support_override=True`.
  - Remote-path tests prove discovery and close-check events can cross the worker/API boundary under auth.
- Behavior changes and risk notes:
  - Worker deployments can now call the API over HTTP instead of relying on in-process API imports.
  - When auth is enabled, the worker must use a bearer token whose claims include `role=support`; the ingest route intentionally fails closed without that.
  - Local service-backed fallback still exists for tests and in-process execution, but it is no longer an eager import-time dependency.
- Follow-ups / known gaps:
  - Production deployment still needs actual environment wiring for `EGP_API_BASE_URL`, `EGP_API_BEARER_TOKEN`, and optionally `EGP_API_TIMEOUT_SECONDS`.

## 2026-04-06 09:15:41 +07

- Goal: make the worker transport unambiguously internal-only so it is not mistaken for a user-facing API surface.
- What changed:
  - `apps/api/src/egp_api/routes/project_ingest.py`
    Moved the worker ingest routes under `/internal/worker/projects/*`, changed the route docs/tagging to internal-worker, and replaced support-role JWT logic with a dedicated internal worker token check plus explicit tenant normalization from the payload.
  - `apps/api/src/egp_api/auth.py`
    Added `require_internal_worker_token()` using `X-EGP-Worker-Token` and constant-time comparison.
  - `apps/api/src/egp_api/config.py`
    Added `get_internal_worker_token()` for API-side internal worker auth configuration.
  - `apps/api/src/egp_api/main.py`
    Added `internal_worker_token` app config/state wiring and exempted the internal worker routes from normal user/session auth middleware so they can use their own auth path.
  - `apps/worker/src/egp_worker/config.py`
    Renamed the worker transport config getters to explicit internal names and kept the previous env names as compatibility fallbacks.
  - `apps/worker/src/egp_worker/project_event_sink.py`
    Switched the HTTP sink from bearer auth to `X-EGP-Worker-Token`, updated the route targets to `/internal/worker/projects/*`, and renamed the transport inputs to internal-worker terminology.
  - `tests/phase1/test_worker_workflows.py`
    Updated the remote transport tests to use the internal worker token instead of a support-role JWT.
  - `tests/phase1/test_projects_and_runs_api.py`
    Updated internal-route tests to use the internal prefix/token and added a rejection test for missing worker auth.
- TDD evidence:
  - RED run:
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q`
  - RED failure reason:
    - `503 Service Unavailable` from the internal ingest route when a test app instance was not configured with `internal_worker_token`, confirming the dedicated worker-auth path was active.
  - GREEN commands:
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q`
    - `./.venv/bin/ruff check apps/api/src/egp_api/auth.py apps/api/src/egp_api/config.py apps/api/src/egp_api/main.py apps/api/src/egp_api/routes/project_ingest.py apps/worker/src/egp_worker/config.py apps/worker/src/egp_worker/project_event_sink.py tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py`
    - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src`
- Tests run and results:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q` -> `15 passed`
  - `./.venv/bin/ruff check ...` -> passed
  - `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src` -> passed
- Wiring verification evidence:
  - Internal routes now live at `/internal/worker/projects/discover` and `/internal/worker/projects/close-check`.
  - The worker HTTP sink now sends `X-EGP-Worker-Token` instead of a bearer JWT.
  - The API tests now prove the internal route rejects requests that omit the worker token.
- Behavior changes and risk notes:
  - This path is now separated from user auth and user route naming.
  - `EGP_INTERNAL_WORKER_TOKEN` is required for the internal route to function; without it the API intentionally fails closed with `503`.
  - Worker env names are now explicit: `EGP_INTERNAL_API_BASE_URL`, `EGP_INTERNAL_WORKER_TOKEN`, and `EGP_INTERNAL_API_TIMEOUT_SECONDS`; the previous names remain only as compatibility aliases during transition.
- Follow-ups / known gaps:
  - Deployment/env docs should be updated to stop referring to the older `EGP_API_*` names for this worker transport path.


## Review (2026-04-06 09:19:06 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commands Run: `git status -sb`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py -q`, `./.venv/bin/ruff check apps/api/src/egp_api/auth.py apps/api/src/egp_api/config.py apps/api/src/egp_api/main.py apps/api/src/egp_api/routes/project_ingest.py apps/worker/src/egp_worker/config.py apps/worker/src/egp_worker/project_event_sink.py tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py`, `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/shared-types/src`

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
- Assumed the current compatibility aliases for legacy worker env names are intentional and temporary.
- Assumed `/internal/worker/projects/*` remains undocumented for end users and is only consumed by the internal worker service.

### Recommended Tests / Validation
- Smoke the worker deployment with `EGP_INTERNAL_API_BASE_URL` and `EGP_INTERNAL_WORKER_TOKEN` configured against a live API instance.
- Add deployment/docs updates to prefer `EGP_INTERNAL_*` names over the temporary compatibility aliases.

### Rollout Notes
- Internal worker routes fail closed when `EGP_INTERNAL_WORKER_TOKEN` is unset or missing from requests.
- The worker still supports fallback env names during transition, so deployment cleanup should remove those aliases deliberately rather than by accident.
