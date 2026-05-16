# Coding Log - PR 8 Background Runtime Mode

Created: 2026-05-16T10:17:02.352046+07:00

Auggie semantic search unavailable: `mcp__auggie_mcp__.codebase_retrieval` returned HTTP 429. This plan is based on direct file inspection plus exact-string searches.

Inspected files:
- `AGENTS.md`
- `apps/api/AGENTS.md`
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/bootstrap/background.py`
- `apps/api/src/egp_api/bootstrap/services.py`
- `apps/api/src/egp_api/executors/webhook_delivery.py`
- `apps/api/src/egp_api/executors/discovery_dispatch.py`
- `apps/api/src/egp_api/main.py`
- `tests/phase1/test_high_risk_architecture.py`
- `tests/phase2/test_immediate_discover.py`
- `tests/phase2/test_webhook_executor.py`
- `tests/phase2/test_discovery_executor.py`
- `docker-compose-localdev.yml`
- `docker-compose.yml`
- `.env.example`
- `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`

## Plan Draft A - Minimal explicit mode in service bootstrap

### Overview
Add `EGP_BACKGROUND_RUNTIME_MODE` with `embedded` and `external` values. Keep existing SQLite/Postgres dispatch-path behavior in embedded mode, and force all API-owned background processing off in external mode so standalone executor services own polling.

### Files to Change
- `apps/api/src/egp_api/config.py`: add `BackgroundRuntimeMode` type and `get_background_runtime_mode()` parser.
- `apps/api/src/egp_api/bootstrap/services.py`: accept a resolved runtime mode and derive app-state background flags from it.
- `apps/api/src/egp_api/main.py`: resolve the env flag and pass it to service bootstrap.
- `tests/phase2/test_background_runtime_mode.py`: add focused config/bootstrap tests.
- `tests/phase2/test_immediate_discover.py`: adjust backend dispatch-path expectation to include mode.
- `docker-compose-localdev.yml`: set API to external mode and add webhook/discovery executor services.
- `docker-compose.yml`: set API to external mode and add executor services for production-like single-host runtime.
- `.env.example`: document the new env var.
- `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`: update runtime behavior and rollback instructions.

### Implementation Steps
TDD sequence:
1. Add tests for config parsing and create_app flags in embedded/external modes.
2. Run tests and confirm failure because config/helper does not exist.
3. Implement parser and service bootstrap flag derivation.
4. Update compose/docs.
5. Run focused pytest, ruff, compileall, and compose config validation.

Function names:
- `get_background_runtime_mode(override: str | None = None)`: returns `embedded` or `external`; rejects unknown values.
- `_background_processors_enabled(...)`: small internal helper or direct logic in `configure_services()` to keep flag calculation readable.

### Test Coverage
- `test_get_background_runtime_mode_defaults_to_embedded`: default compatibility mode.
- `test_get_background_runtime_mode_rejects_unknown_values`: invalid env fails clearly.
- `test_create_app_external_background_mode_disables_embedded_processors`: API does not run loops or route kicks.
- `test_create_app_embedded_background_mode_preserves_postgres_processors`: Postgres keeps embedded behavior.

### Decision Completeness
Goal: allow explicit embedded vs external background execution.
Non-goals: replace subprocess worker dispatch, add a queue backend, or alter document ingestion.
Success criteria: API state flags disable both webhook/discovery embedded loops and discovery route kicks in external mode; standalone executor services are documented and wired in compose.
Public interfaces: new env var `EGP_BACKGROUND_RUNTIME_MODE=embedded|external`; no API/schema changes.
Edge cases / failure modes: invalid mode fails closed with a clear error; SQLite embedded behavior remains route-kick only; external mode disables API processing even on SQLite/Postgres.
Rollout & monitoring: deploy external services first with API in external mode; rollback by setting mode to embedded and stopping executor services. Watch executor logs for queued jobs and worker failures.
Acceptance checks: focused tests, ruff, compileall, `docker compose config` for both compose files.

### Dependencies
Requires PR 6 and PR 7 executor modules, now on `main`.

### Validation
Run pytest for background/runtime tests and executor tests, ruff for API/tests, compileall for API, compose config validation.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `EGP_BACKGROUND_RUNTIME_MODE` | `create_app()` | `egp_api.config.get_background_runtime_mode()` | N/A |
| Embedded loop flags | FastAPI lifespan | `configure_services()` app-state flags | N/A |
| Webhook executor service | `python -m egp_api.executors.webhook_delivery` | Compose service command | notification outbox tables via repository |
| Discovery executor service | `python -m egp_api.executors.discovery_dispatch` | Compose service command | discovery jobs/crawl runs via repositories |

## Plan Draft B - Runtime mode object in background bootstrap

### Overview
Create a richer runtime policy object consumed by `bootstrap/background.py`, leaving `configure_services()` mostly unchanged. The lifespan would decide whether to start loops based on mode while route-kick logic would be separately disabled in service bootstrap.

### Files to Change
Same files as Draft A, plus more changes in `bootstrap/background.py` to make lifespan mode-aware.

### Implementation Steps
TDD sequence:
1. Add tests around `build_lifespan()` not scheduling tasks under external mode.
2. Add runtime policy object and attach it to `app.state`.
3. Update route-kick flag separately.
4. Update compose/docs and run gates.

Function names:
- `BackgroundRuntimePolicy`: carries booleans for webhook loop, discovery loop, and route kick.
- `build_background_runtime_policy(...)`: derives policy from mode and database URL.

### Test Coverage
- `test_external_policy_disables_all_background_work`: policy-level expectations.
- `test_embedded_policy_preserves_backend_defaults`: current behavior retained.
- `test_lifespan_respects_external_policy`: no tasks scheduled.

### Decision Completeness
Goal: centralize background runtime decisions in a typed policy object.
Non-goals: same as Draft A.
Success criteria: same behavior as Draft A, with more explicit policy structure.
Public interfaces: same `EGP_BACKGROUND_RUNTIME_MODE` env var.
Edge cases / failure modes: invalid mode fail closed; policy makes impossible combinations less likely.
Rollout & monitoring: same as Draft A.
Acceptance checks: same plus lifespan scheduling tests.

### Dependencies
Requires standalone executor modules from PR 6/7.

### Validation
Same local gates as Draft A.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `BackgroundRuntimePolicy` | `configure_services()` / `build_lifespan()` | app-state policy | N/A |
| `EGP_BACKGROUND_RUNTIME_MODE` | `create_app()` | config parser | N/A |
| Executor compose services | Docker Compose | service commands | existing repositories |

## Comparative Analysis
Draft A is smaller and keeps existing app-state flags as the contract that lifespan already understands. It requires fewer moving parts and directly targets PR 8's explicit-mode requirement.

Draft B is more extensible but adds a policy abstraction before there is enough complexity to justify it. It also touches lifespan more heavily even though existing flag checks already do the runtime gating.

Both drafts preserve existing behavior by default and introduce only one public env var. Draft A is the better fit for a reviewable PR because it changes the smallest behavioral surface while still wiring standalone executor processes.

## Unified Execution Plan

### Overview
Implement Draft A with one small helper function in `bootstrap/services.py` if needed for readability. The public contract is `EGP_BACKGROUND_RUNTIME_MODE`, defaulting to `embedded`; `external` disables API-owned background processors and discovery route kicks while compose runs webhook and discovery executors as separate services.

### Files to Change
- `apps/api/src/egp_api/config.py`: add `BackgroundRuntimeMode` and `get_background_runtime_mode()`.
- `apps/api/src/egp_api/main.py`: pass resolved mode into `configure_services()`.
- `apps/api/src/egp_api/bootstrap/services.py`: set app-state flags based on mode.
- `tests/phase2/test_background_runtime_mode.py`: new tests for parser and app state.
- `tests/phase2/test_immediate_discover.py`: update old runtime path test to assert embedded/external semantics.
- `docker-compose-localdev.yml`: add `EGP_BACKGROUND_RUNTIME_MODE=external` to API and add executor services.
- `docker-compose.yml`: add production-like executor services and external API mode.
- `.env.example`: include the new env var and value guidance.
- `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`: describe separated runtime, commands, rollout, rollback.

### Implementation Steps
TDD sequence:
1. Add tests for default/override/env/invalid mode parsing.
2. Add tests for app-state flags in embedded SQLite, embedded Postgres, and external Postgres.
3. Run focused tests and confirm expected import/assertion failures.
4. Implement config parser and service bootstrap mode wiring.
5. Update compose/docs/env example.
6. Run focused tests, ruff, compileall, and compose config checks.

Function names:
- `get_background_runtime_mode(override: str | None = None) -> BackgroundRuntimeMode`: normalizes explicit override or `EGP_BACKGROUND_RUNTIME_MODE`; accepts `embedded` and `external`; raises `RuntimeError` on unsupported values.
- `configure_services(..., background_runtime_mode: BackgroundRuntimeMode, ...)`: keeps default app-state construction but derives `webhook_delivery_processor_enabled`, `discovery_dispatch_processor_enabled`, and `discovery_dispatch_route_kick_enabled` from mode.

Expected behavior and edge cases:
- Default mode is embedded to preserve current deployments.
- Embedded + SQLite: no embedded loops; route kick remains enabled.
- Embedded + Postgres: webhook/discovery embedded loops enabled; discovery route kick disabled.
- External + any DB: embedded loops disabled; discovery route kick disabled.
- Invalid env var fails application creation before serving traffic.

### Test Coverage
- `test_get_background_runtime_mode_defaults_to_embedded`: default compatibility.
- `test_get_background_runtime_mode_reads_environment`: env value parsed.
- `test_get_background_runtime_mode_rejects_unknown_value`: fail closed.
- `test_create_app_external_background_mode_disables_api_background_work`: all API background flags off.
- `test_create_app_embedded_background_mode_preserves_database_defaults`: existing backend behavior retained.
- `test_discovery_dispatch_runtime_uses_background_mode_and_database_backend`: route/loop semantics explicit.

### Decision Completeness
Goal: make background execution mode explicit and runnable as external services.
Non-goals: new queue infrastructure, scheduling changes, worker image split, DB migrations, route/API contract changes.
Success criteria: tests prove flags; compose validates; docs describe rollout/rollback; default preserves current behavior.
Public interfaces: `EGP_BACKGROUND_RUNTIME_MODE=embedded|external`; Compose adds `webhook-executor` and `discovery-executor` services; no DB migrations.
Edge cases / failure modes: invalid mode raises `RuntimeError`; external mode avoids duplicate processing by disabling API route kicks and embedded loops; executor crashes restart via Compose.
Rollout & monitoring: switch API to external mode only when executor services are healthy; monitor executor logs, discovery job backlog, webhook delivery backlog, and crawl run worker_lost failures. Rollback by setting `EGP_BACKGROUND_RUNTIME_MODE=embedded` and stopping executor services.
Acceptance checks: `pytest` focused tests pass; `ruff` passes; `compileall` passes; both compose files render with required env placeholders supplied.

### Dependencies
PR 6 and PR 7 are already merged to `main`.

### Validation
- `./.venv/bin/python -m pytest tests/phase2/test_background_runtime_mode.py tests/phase2/test_immediate_discover.py tests/phase2/test_webhook_executor.py tests/phase2/test_discovery_executor.py tests/phase1/test_high_risk_architecture.py -q`
- `./.venv/bin/ruff check apps/api tests/phase2/test_background_runtime_mode.py tests/phase2/test_immediate_discover.py`
- `./.venv/bin/python -m compileall apps/api/src`
- `docker compose -f docker-compose-localdev.yml config`
- `env EGP_POSTGRES_PASSWORD=x EGP_PAYMENT_CALLBACK_SECRET=x EGP_JWT_SECRET=x EGP_WEB_ALLOWED_ORIGINS=https://app.example EGP_WEB_BASE_URL=https://app.example EGP_INTERNAL_WORKER_TOKEN=x NEXT_PUBLIC_EGP_API_BASE_URL=https://api.example NEXT_PUBLIC_SITE_URL=https://app.example EGP_API_DOMAIN=api.example EGP_APP_DOMAIN=app.example docker compose -f docker-compose.yml config`

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `get_background_runtime_mode()` | `create_app()` startup | `apps/api/src/egp_api/main.py` passes to `configure_services()` | N/A |
| API embedded webhook flag | FastAPI lifespan | `app.state.webhook_delivery_processor_enabled` in `configure_services()` | notification repository tables |
| API embedded discovery flag | FastAPI lifespan | `app.state.discovery_dispatch_processor_enabled` in `configure_services()` | `discovery_jobs`, `crawl_runs` |
| API discovery route kick flag | rules route immediate processing | `app.state.discovery_dispatch_route_kick_enabled` in `configure_services()` | `discovery_jobs` |
| `webhook-executor` Compose service | `python -m egp_api.executors.webhook_delivery` | `docker-compose*.yml` service command | notification repository tables |
| `discovery-executor` Compose service | `python -m egp_api.executors.discovery_dispatch` | `docker-compose*.yml` service command | `discovery_jobs`, `crawl_runs` |


## Review (2026-05-16 10:21:31 +07) - working-tree PR 8 background runtime mode

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree before Graphite branch creation
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `nl -ba` reads for config, background bootstrap, service bootstrap, main app wiring, runtime tests, and compose services; focused pytest; ruff; compileall; compose config validation.
- Auggie: attempted semantic review retrieval; received HTTP 429, used direct inspection fallback.

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
- Assumption: future deployments that set `EGP_BACKGROUND_RUNTIME_MODE=embedded` will stop `webhook-executor` and `discovery-executor`, as documented, to avoid duplicate processing.
- Assumption: executor health checks are not required in this PR; Compose restart policy and log monitoring are sufficient for this small runtime separation step.

### Recommended Tests / Validation
- Completed focused runtime/background tests: 35 passed.
- Completed `./.venv/bin/ruff check apps/api packages`.
- Completed `./.venv/bin/python -m compileall apps/api/src`.
- Completed `docker compose -f docker-compose-localdev.yml config`.
- Completed production `docker compose -f docker-compose.yml config` with required placeholder env vars supplied.

### Rollout Notes
- Default code behavior remains `embedded`; checked-in Compose defaults API to `external` and runs separate executor services.
- Rollback is documented: stop executor services, set `EGP_BACKGROUND_RUNTIME_MODE=embedded`, restart API.


## Implementation Summary (2026-05-16 10:21:58 +07) - PR 8 background runtime mode

### Goal
Add explicit embedded/external background runtime mode and wire local/production Compose so webhook delivery and discovery dispatch can run outside the API process.

### What Changed
- `apps/api/src/egp_api/config.py`
  - Added `BackgroundRuntimeMode` and `get_background_runtime_mode()`.
  - Default remains `embedded`; unsupported values raise a clear `RuntimeError`.
- `apps/api/src/egp_api/main.py`
  - Added optional `background_runtime_mode` override for tests/programmatic app creation.
  - Resolves `EGP_BACKGROUND_RUNTIME_MODE` during app startup.
- `apps/api/src/egp_api/bootstrap/background.py`
  - Made discovery loop and route-kick helper functions mode-aware.
- `apps/api/src/egp_api/bootstrap/services.py`
  - Stores `app.state.background_runtime_mode`.
  - Disables webhook loop, discovery loop, and discovery route kicks when mode is `external`.
- `tests/phase2/test_background_runtime_mode.py`
  - Added parser and app-state coverage for embedded/external modes.
- `tests/phase2/test_immediate_discover.py`
  - Updated dispatch-path expectations for explicit mode plus database backend.
- `docker-compose-localdev.yml` and `docker-compose.yml`
  - Compose API defaults to external mode.
  - Added `webhook-executor` and `discovery-executor` services using the existing API image.
- `.env.example`
  - Documented `EGP_BACKGROUND_RUNTIME_MODE`.
- `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`
  - Updated runtime shape, executor services, rollout, and rollback guidance.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase2/test_background_runtime_mode.py tests/phase2/test_immediate_discover.py::test_discovery_dispatch_runtime_uses_single_dispatch_path_per_database_backend -q`
  - Failed during collection with `ImportError: cannot import name 'get_background_runtime_mode' from 'egp_api.config'`.
- GREEN: same command after implementation passed: 6 tests.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase2/test_background_runtime_mode.py tests/phase2/test_immediate_discover.py tests/phase2/test_webhook_executor.py tests/phase2/test_discovery_executor.py tests/phase1/test_high_risk_architecture.py -q` - passed, 35 tests.
- `./.venv/bin/ruff check apps/api tests/phase2/test_background_runtime_mode.py tests/phase2/test_immediate_discover.py` - passed.
- `./.venv/bin/ruff check apps/api packages` - passed.
- `./.venv/bin/python -m compileall apps/api/src` - passed.
- `docker compose -f docker-compose-localdev.yml config` - passed.
- `env EGP_POSTGRES_PASSWORD=x EGP_PAYMENT_CALLBACK_SECRET=x EGP_JWT_SECRET=x EGP_WEB_ALLOWED_ORIGINS=https://app.example EGP_WEB_BASE_URL=https://app.example EGP_INTERNAL_WORKER_TOKEN=x NEXT_PUBLIC_EGP_API_BASE_URL=https://api.example NEXT_PUBLIC_SITE_URL=https://app.example EGP_API_DOMAIN=api.example EGP_APP_DOMAIN=app.example docker compose -f docker-compose.yml config` - passed.

### Wiring Verification
- Env/config: `EGP_BACKGROUND_RUNTIME_MODE` enters through `get_background_runtime_mode()` and `create_app()`.
- API app state: `configure_services()` sets `background_runtime_mode`, `webhook_delivery_processor_enabled`, `discovery_dispatch_processor_enabled`, and `discovery_dispatch_route_kick_enabled`.
- Embedded runtime: `build_lifespan()` still reads the existing app-state booleans before starting loops.
- External runtime: Compose starts `python -m egp_api.executors.webhook_delivery` and `python -m egp_api.executors.discovery_dispatch` as separate services.
- Schema/table: no migrations; executor services use existing notification, discovery job, and crawl run repositories.

### Behavior / Risk Notes
- Code default is still `embedded` for compatibility outside Compose.
- Compose defaults API to `external` to prevent duplicate queue processing when executor services are running.
- Invalid mode fails startup rather than silently choosing a runtime shape.

### Follow-ups / Known Gaps
- Add executor health checks or backlog metrics in a later observability PR if needed.
