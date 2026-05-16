# Coding Log: Standalone Webhook Executor

## Plan Draft A - Extract reusable executor module and reuse it from FastAPI lifespan

### Overview
Move webhook delivery polling out of the FastAPI background bootstrap into a standalone API executor module. The API can keep embedded polling for now by importing the executor loop, while operators gain a runnable `python -m egp_api.executors.webhook_delivery` process that can drain queued webhook deliveries independently.

### Files to Change
- `apps/api/src/egp_api/executors/__init__.py`: package marker for API executor entrypoints.
- `apps/api/src/egp_api/executors/webhook_delivery.py`: build a notification repository-backed `WebhookDeliveryProcessor`, expose once/loop runner helpers, and provide a CLI `main()`.
- `apps/api/src/egp_api/bootstrap/background.py`: remove local webhook polling implementation and call the executor loop from lifespan.
- `tests/phase2/test_webhook_executor.py`: cover once mode, loop stop behavior, CLI processor construction seam, and lifespan reuse if practical.

### TDD Sequence
1. Add tests that import `egp_api.executors.webhook_delivery` and expect `run_webhook_delivery_once`, `run_webhook_delivery_loop`, and `main` behavior.
2. Run the focused tests and confirm import/function failures.
3. Implement the executor module with dependency-injection seams for tests.
4. Rewire `bootstrap/background.py` to use the executor loop without changing embedded API behavior.
5. Run focused tests, ruff, and compileall.

### Function Notes
- `build_webhook_delivery_processor(database_url)`: creates a shared engine, notification repository, and `WebhookDeliveryProcessor`.
- `run_webhook_delivery_once(processor, limit)`: drains one claim batch and returns processed count.
- `run_webhook_delivery_loop(processor, stop_event, poll_interval_seconds, logger)`: repeatedly drains pending deliveries until stopped; logs and continues on processor errors.
- `main(argv, processor_factory)`: CLI entrypoint supporting `--database-url`, `--once`, `--limit`, and `--poll-interval-seconds`.

### Test Coverage
- `test_run_webhook_delivery_once_passes_limit`: validates once mode limit wiring.
- `test_run_webhook_delivery_loop_processes_until_stop_event`: validates standalone loop can drain outside FastAPI.
- `test_main_once_builds_processor_from_database_url`: validates CLI parsing and factory seam.
- `test_background_lifespan_uses_executor_loop`: validates embedded API wiring reuses executor loop.

### Decision Completeness
- Goal: webhook delivery can run independently of HTTP serving.
- Non-goals: disabling embedded API loop by config, compose/deployment wiring, discovery executor extraction, schema changes.
- Success criteria: standalone module is runnable; tests prove it drains pending deliveries outside API; API embedded behavior remains wired.
- Public interfaces: new module CLI `python -m egp_api.executors.webhook_delivery`; optional flags `--database-url`, `--once`, `--limit`, `--poll-interval-seconds`.
- Edge cases/failure modes: missing `DATABASE_URL` fails fast via existing config; processor exceptions in long-running loop are logged and retried next tick; once mode returns non-zero only if construction/processing raises.
- Rollout/backout: additive executor; embedded API behavior remains default. Backout is reverting the executor import/wiring.
- Acceptance checks: focused pytest, ruff on touched files, compileall for API.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `egp_api.executors.webhook_delivery` | `python -m egp_api.executors.webhook_delivery` | Python module execution | `webhook_deliveries`, `webhook_subscriptions` via notification repository |
| `run_webhook_delivery_loop` | FastAPI lifespan embedded poller and standalone CLI | imported in `apps/api/src/egp_api/bootstrap/background.py` | same existing tables |
| `WebhookDeliveryProcessor` | executor builder / existing service bootstrap | notification repository factory | same existing tables |

## Plan Draft B - Create API service class only, no CLI yet

### Overview
Extract the polling loop into an app service class and leave a CLI for PR 8. This is smaller, but it does not satisfy PR 6's standalone runnable process goal.

### Files to Change
- `apps/api/src/egp_api/services/webhook_executor.py`: service class with loop helper.
- `apps/api/src/egp_api/bootstrap/background.py`: call the service class.
- tests around the service class.

### TDD Sequence
1. Add service-class loop tests.
2. Move lifespan loop into service class.
3. Keep all runtime invocation embedded.

### Test Coverage
- Loop drains and stops.
- Lifespan starts the service loop.

### Decision Completeness
- Goal: reduce lifespan ownership.
- Non-goal: standalone CLI.
- Public interfaces: none.
- Gap: does not let webhook delivery run independently of HTTP serving.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Webhook executor service | API lifespan only | `build_lifespan()` | existing webhook tables |

## Comparative Analysis
Draft A better matches the phase goal because it creates a real standalone runnable process while preserving embedded behavior. Draft B is lower risk but under-delivers the PR boundary and would force PR 8 to do both mode flags and first executor extraction. Draft A is still small because it reuses existing repositories and `WebhookDeliveryProcessor` unchanged.

## Unified Execution Plan
Use Draft A. Keep embedded API behavior unchanged for now, but make the loop implementation and runnable entrypoint live outside FastAPI lifespan. Do not introduce runtime mode flags or compose changes in PR 6; that belongs to PR 8 after discovery has a matching executor.

### Exact Steps
1. Add `tests/phase2/test_webhook_executor.py` with failing tests for once mode, loop stop behavior, CLI once mode, and background import wiring.
2. Add `egp_api.executors` package and `webhook_delivery.py` module.
3. Implement processor builder using `get_database_url`, `create_shared_engine`, and `create_notification_repository`.
4. Implement once/loop helpers with graceful long-loop exception logging.
5. Implement CLI `main()` with deterministic arguments and `SystemExit(main())` module execution.
6. Rewire `bootstrap/background.py` to import and call `run_webhook_delivery_loop` for embedded mode.
7. Run focused pytest, ruff, compileall, and formal review.

### Acceptance Checks
- `./.venv/bin/python -m pytest tests/phase2/test_webhook_executor.py -q`
- `./.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py tests/phase2/test_notification_dispatch.py -q`
- `./.venv/bin/ruff check apps/api/src/egp_api/bootstrap/background.py apps/api/src/egp_api/executors tests/phase2/test_webhook_executor.py`
- `./.venv/bin/python -m compileall apps/api/src`

### Decision-Complete Checklist
- No DB/schema changes.
- No deployment mode flag in this PR.
- Standalone process has an explicit module entrypoint.
- Embedded API behavior remains on the existing `webhook_delivery_processor_enabled` gate.
- Tests cover the new runtime entrypoint and loop behavior.


## Implementation Update - 2026-05-16 09:51:11 

### Goal
Extract webhook delivery polling into a standalone runnable executor while preserving the existing embedded FastAPI lifespan behavior.

### What Changed
- `apps/api/src/egp_api/executors/__init__.py`
  - Added a package for API-owned standalone runtime executors.
- `apps/api/src/egp_api/executors/webhook_delivery.py`
  - Added `build_webhook_delivery_processor(...)` to create a repository-backed `WebhookDeliveryProcessor` from a database URL.
  - Added `run_webhook_delivery_once(...)` for one-batch draining.
  - Added `run_webhook_delivery_loop(...)` for long-running polling outside the API process.
  - Added CLI `main(...)` for `python -m egp_api.executors.webhook_delivery` with `--database-url`, `--once`, `--limit`, and `--poll-interval-seconds`.
- `apps/api/src/egp_api/bootstrap/background.py`
  - Removed the inline webhook polling loop and imports `run_webhook_delivery_loop` from the standalone executor module.
  - Preserved the existing embedded gate via `app.state.webhook_delivery_processor_enabled`.
- `tests/phase2/test_webhook_executor.py`
  - Added tests for once mode, standalone loop stop behavior, CLI factory wiring, and API background reuse of the executor loop.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase2/test_webhook_executor.py -q`
  - Failed during collection with `ModuleNotFoundError: No module named 'egp_api.executors'`.
- GREEN: `./.venv/bin/python -m pytest tests/phase2/test_webhook_executor.py -q`
  - Passed: 4 tests.

### Tests / Gates Run
- `./.venv/bin/ruff format apps/api/src/egp_api/bootstrap/background.py apps/api/src/egp_api/executors/__init__.py apps/api/src/egp_api/executors/webhook_delivery.py tests/phase2/test_webhook_executor.py`
- `./.venv/bin/ruff check apps/api/src/egp_api/bootstrap/background.py apps/api/src/egp_api/executors tests/phase2/test_webhook_executor.py`
- `./.venv/bin/python -m pytest tests/phase2/test_webhook_executor.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_notification_dispatch.py -q`
- `./.venv/bin/python -m compileall apps/api/src`

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `egp_api.executors.webhook_delivery` | `python -m egp_api.executors.webhook_delivery` | module-level `if __name__ == "__main__"` | `webhook_deliveries`, `webhook_subscriptions` through `SqlNotificationRepository` |
| `run_webhook_delivery_loop` | standalone CLI long-running mode and embedded API lifespan | imported by `apps/api/src/egp_api/bootstrap/background.py` | existing webhook tables |
| `WebhookDeliveryProcessor` standalone builder | CLI `main()` / tests via `processor_factory` seam | `build_webhook_delivery_processor()` | existing webhook tables |

### Behavior / Risk Notes
- No schema, API endpoint, env-var, or deployment mode changes.
- Embedded API behavior remains enabled/disabled by the existing SQLite/Postgres gate.
- Long-running executor logs processor exceptions and retries next poll rather than exiting on one transient delivery failure.
- PR 8 can later add explicit embedded/external runtime flags and compose wiring.

### Follow-ups / Known Gaps
- Discovery still needs a matching standalone executor in PR 7.
- Runtime mode/configuration and local deployment wiring remain intentionally deferred to PR 8.


## Validation Update - 2026-05-16 09:52:22 

- Re-ran `./.venv/bin/ruff check apps/api/src/egp_api/bootstrap/background.py apps/api/src/egp_api/executors tests/phase2/test_webhook_executor.py` after moving long-running event creation into the executor coroutine.
- Re-ran `./.venv/bin/python -m pytest tests/phase2/test_webhook_executor.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_notification_dispatch.py -q` and confirmed 22 passing tests.
- Re-ran `./.venv/bin/python -m compileall apps/api/src`.
- Verified the module entrypoint with `./.venv/bin/python -m egp_api.executors.webhook_delivery --help`.


## Review (2026-05-16 09:52:39 ) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree for PR 6 standalone webhook executor
- Commands Run:
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - targeted diff inspection for `apps/api/src/egp_api/bootstrap/background.py`
  - targeted file inspection for `apps/api/src/egp_api/executors/webhook_delivery.py` and `tests/phase2/test_webhook_executor.py`
  - `./.venv/bin/ruff check apps/api/src/egp_api/bootstrap/background.py apps/api/src/egp_api/executors tests/phase2/test_webhook_executor.py`
  - `./.venv/bin/python -m pytest tests/phase2/test_webhook_executor.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_notification_dispatch.py -q`
  - `./.venv/bin/python -m egp_api.executors.webhook_delivery --help`
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
- Assumption: PR 6 should add the standalone process without disabling the embedded API lifespan loop yet; explicit embedded/external mode selection remains PR 8.
- Assumption: using the existing `DATABASE_URL` resolution and notification repository factory is the right operational contract for the standalone process.

### Recommended Tests / Validation
- Already run: focused executor tests, notification dispatch tests, high-risk architecture tests, ruff check, module help smoke, and API compileall.
- Before merge: inspect compact PR/check status. Per user instruction, broken GitHub Actions may be bypassed for merge.

### Rollout Notes
- No schema, endpoint, env-var, or compose changes.
- New optional operational entrypoint: `python -m egp_api.executors.webhook_delivery`.
- Embedded API behavior remains unchanged until a later runtime-mode PR.


## Review (2026-05-16 10:08:54 +07) - working-tree PR 7 discovery executor

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree before Graphite branch creation
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `nl -ba` reads for `apps/api/src/egp_api/executors/discovery_dispatch.py`, `apps/api/src/egp_api/bootstrap/background.py`, and `tests/phase2/test_discovery_executor.py`; `./.venv/bin/python -m pytest tests/phase2/test_discovery_executor.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_immediate_discover.py tests/phase2/test_webhook_executor.py tests/phase1/test_high_risk_architecture.py tests/phase1/test_api_discovery_spawn.py -q`; `./.venv/bin/ruff check apps/api tests/phase2/test_discovery_executor.py`; `./.venv/bin/python -m compileall apps/api/src`
- Auggie: attempted review-context retrieval, received HTTP 429, used direct inspection fallback.

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
- Assumption: PR 8 will add the explicit embedded/external runtime mode and deployment wiring; this PR intentionally only creates the standalone runnable executor while preserving existing embedded startup behavior.

### Recommended Tests / Validation
- Completed focused discovery/background validation: 38 tests passed.
- Completed API ruff and compileall gates.
- CI should still run the broader repo gates after PR submission.

### Rollout Notes
- `python -m egp_api.executors.discovery_dispatch` now supports standalone execution with `--database-url`, `--artifact-root`, `--once`, `--limit`, and `--poll-interval-seconds`.
- FastAPI embedded mode still starts the discovery loop when the existing database-backend flag enables it, but that loop now comes from the standalone executor module.


## Implementation Summary (2026-05-16 10:09:23 +07) - PR 7 standalone discovery executor

### Goal
Extract discovery dispatch polling from FastAPI lifespan into a standalone runnable executor while preserving the existing embedded API behavior, retry processing, and missing-worker reconciliation.

### What Changed
- `apps/api/src/egp_api/executors/discovery_dispatch.py`
  - Added a standalone discovery dispatch runtime builder backed by discovery job, run, and profile repositories.
  - Added one-shot and long-running executor functions.
  - Added missing-worker reconciliation before and after each processing batch, matching the prior embedded loop behavior.
  - Added CLI support for `python -m egp_api.executors.discovery_dispatch` with database URL, artifact root, once, limit, and poll interval options.
- `apps/api/src/egp_api/bootstrap/background.py`
  - Removed the embedded discovery loop implementation from lifespan.
  - Rewired embedded API startup to call the standalone executor loop with the existing app-state processor and run service.
- `tests/phase2/test_discovery_executor.py`
  - Added tests for one-shot dispatch, long-running dispatch, CLI runtime construction, and lifespan reuse of the standalone loop.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase2/test_discovery_executor.py -q`
  - Failed during collection with `ImportError: cannot import name 'discovery_dispatch' from 'egp_api.executors'` because the standalone executor did not exist yet.
- GREEN: `./.venv/bin/python -m pytest tests/phase2/test_discovery_executor.py -q`
  - Passed: 4 tests.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase2/test_discovery_executor.py -q` - passed, 4 tests.
- `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/phase2/test_immediate_discover.py tests/phase2/test_webhook_executor.py -q` - passed, 21 tests.
- `./.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py tests/phase1/test_api_discovery_spawn.py -q` - passed, 13 tests.
- `./.venv/bin/python -m pytest tests/phase2/test_discovery_executor.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_immediate_discover.py tests/phase2/test_webhook_executor.py tests/phase1/test_high_risk_architecture.py tests/phase1/test_api_discovery_spawn.py -q` - passed, 38 tests.
- `./.venv/bin/ruff check apps/api tests/phase2/test_discovery_executor.py` - passed.
- `./.venv/bin/python -m compileall apps/api/src` - passed.

### Wiring Verification
- Entry point: `python -m egp_api.executors.discovery_dispatch` calls `main()` and can run one batch or poll indefinitely.
- Embedded API registration: `build_lifespan()` imports `run_discovery_dispatch_loop` from the executor module and passes `app.state.discovery_dispatch_processor`, `app.state.run_service`, and `os.getpid()`.
- Dispatcher abstraction: `build_discovery_dispatch_runtime()` constructs `SubprocessDiscoveryDispatcher` and injects it into `DiscoveryDispatchProcessor`.
- Schema/table: no schema changes; executor uses the existing discovery jobs and crawl runs repositories.

### Behavior / Risk Notes
- Embedded API discovery behavior remains enabled by the existing database-backend flag.
- Standalone loop catches unexpected per-tick exceptions and logs them so a transient repository/dispatch error does not permanently stop the external executor.
- Runtime mode selection and compose/deployment wiring remain follow-up work for PR 8.

### Follow-ups / Known Gaps
- PR 8 should add explicit embedded/external runtime configuration and deployment documentation.
