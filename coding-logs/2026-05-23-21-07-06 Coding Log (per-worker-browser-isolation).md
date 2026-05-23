# PR-03 Per-Worker Browser Isolation Coding Log

## Planning (2026-05-23 21:07:06 +0700)

Auggie semantic search unavailable: `codebase-retrieval` returned HTTP 429. This plan is based on direct file inspection and exact identifier searches of:

- `AGENTS.md`
- `apps/api/AGENTS.md`
- `apps/worker/AGENTS.md`
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/executors/discovery_dispatch.py`
- `apps/worker/src/egp_worker/main.py`
- `apps/worker/src/egp_worker/browser_discovery.py`
- `tests/phase1/test_api_discovery_spawn.py`
- `tests/phase1/test_worker_live_discovery.py`
- `docs/DEPLOYMENT.md`

### Plan Draft A - Dispatcher-Owned Isolation

#### Overview

Generate a unique CDP port and Chrome user-data-dir in the API subprocess dispatcher before launching each worker. The worker already accepts `browser_settings`, so the smallest runtime change is to enrich that payload and let `egp_worker.main._build_browser_settings()` map it into `BrowserDiscoverySettings`.

#### Files to Change

- `apps/api/src/egp_api/config.py`: add env helpers for browser CDP base, range, and profile root.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: derive per-run browser payload, persist debug metadata, and clean profile dirs in `finally`.
- `apps/worker/src/egp_worker/main.py`: keep/extend browser payload mapping for nested and flat fields.
- `tests/phase1/test_api_discovery_spawn.py`: test distinct ports, profile dirs, and cleanup.
- `tests/phase1/test_worker_live_discovery.py`: test worker-side mapping from dispatcher keys.
- `docs/DEPLOYMENT.md`: document new env vars and relaxed single-worker warning.

#### Implementation Steps

TDD sequence:

1. Add failing dispatcher tests for deterministic per-run CDP port/profile-dir and cleanup.
2. Run the focused tests and confirm they fail because the payload only includes `max_pages_per_keyword`.
3. Add config helpers and dispatcher payload enrichment.
4. Add cleanup in dispatcher `finally`, keeping existing log-handle cleanup.
5. Run focused tests and ruff; refactor only if the interfaces are awkward.

Functions:

- `get_browser_cdp_port_base()`: returns positive integer from `EGP_BROWSER_CDP_PORT_BASE`, default `9222`.
- `get_browser_cdp_port_range()`: returns positive integer from `EGP_BROWSER_CDP_PORT_RANGE`, default `200`.
- `get_browser_profile_root()`: returns expanded/resolved path from `EGP_BROWSER_PROFILE_ROOT`, default `~/.egp/profiles`.
- `_resolve_browser_settings_payload(...)`: adds `browser_cdp_port` and `browser_profile_dir` derived from `run_id`.
- `_browser_port_for_run(...)`: hashes run ID into the configured range.
- `_cleanup_browser_profile_dir(...)`: removes only per-run dirs under the configured profile root.

#### Test Coverage

- `test_discover_spawner_assigns_distinct_browser_isolation_payloads`: unique ports/profile dirs.
- `test_discover_spawner_cleans_browser_profile_dir_after_worker_exit`: cleanup after success.
- `test_discover_spawner_cleans_browser_profile_dir_after_worker_failure`: cleanup after failure.
- `test_run_worker_job_forwards_flat_browser_isolation_settings`: flat payload mapping.

#### Decision Completeness

- Goal: one worker subprocess maps to one Chrome CDP port and one Chrome profile dir.
- Non-goals: raising `EGP_DISCOVERY_WORKER_COUNT`, adding rate limiting, adding real Playwright/lsof integration in normal CI.
- Success criteria: two dispatches with different run IDs produce different CDP ports and profile dirs; profile dirs are removed after completion; worker maps the payload to `BrowserDiscoverySettings`.
- Public interfaces: `EGP_BROWSER_CDP_PORT_BASE`, `EGP_BROWSER_CDP_PORT_RANGE`, `EGP_BROWSER_PROFILE_ROOT`; `browser_settings.browser_cdp_port`; `browser_settings.browser_profile_dir`.
- Edge cases / failure modes: invalid env values fail closed at dispatch build time; profile cleanup never deletes paths outside root; cleanup logs and continues if removal fails.
- Rollout & monitoring: keep `EGP_DISCOVERY_WORKER_COUNT=1` for first observation window; then pilot `2` on one host. Watch Chrome PID count and profile root growth.
- Acceptance checks: focused pytest for dispatcher/worker settings; `ruff check apps/api apps/worker tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py`; compile API/worker modules.

#### Dependencies

Uses Python stdlib only: `hashlib`, `shutil`, and `pathlib`.

#### Validation

Run focused tests first, then relevant ruff/compile gates. Manual production validation remains the rollout gate because CI should not spawn real Chrome.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Browser env helpers | `SubprocessDiscoveryDispatcher.dispatch()` | imported into `discovery_worker_dispatcher.py` | N/A |
| Browser isolation payload | worker stdin JSON | `SubprocessDiscoveryDispatcher.dispatch()` payload | N/A |
| Worker browser mapping | `run_worker_job(command="discover")` | `_build_browser_settings()` called before `run_discover_workflow()` | N/A |
| Profile cleanup | dispatcher `finally` | `SubprocessDiscoveryDispatcher.dispatch()` | N/A |

Cross-language schema verification: no DB schema changes.

### Plan Draft B - Worker-Owned Isolation

#### Overview

Let the API dispatcher pass only `run_id`; teach the worker to compute CDP port and profile dir during `_build_browser_settings()`. This keeps browser-specific defaults closer to browser code but splits operational env parsing across API and worker processes.

#### Files to Change

- `apps/worker/src/egp_worker/main.py`: derive default port/profile from run ID.
- `apps/worker/src/egp_worker/browser_discovery.py`: maybe update `BrowserDiscoverySettings` defaults.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: cleanup profile root after worker exit, likely duplicating worker path logic.
- `tests/phase1/test_worker_live_discovery.py`: worker derivation tests.
- `tests/phase1/test_api_discovery_spawn.py`: dispatcher cleanup tests.
- `docs/DEPLOYMENT.md`: env docs.

#### Implementation Steps

TDD sequence:

1. Add worker tests for run-ID-derived defaults.
2. Add dispatcher tests for cleanup using the same derivation function.
3. Implement shared derivation or duplicate conservatively.
4. Run focused tests, ruff, and compile.

Functions:

- `_derive_browser_settings_from_run_id(...)`: compute worker-owned isolation.
- `_cleanup_browser_profile_dir(...)`: dispatcher cleanup must mirror worker-derived path.

#### Test Coverage

- `test_run_worker_job_derives_browser_isolation_from_run_id`: worker computes defaults.
- `test_discover_spawner_removes_worker_derived_profile_dir`: dispatcher cleanup mirrors worker.

#### Decision Completeness

- Goal: ensure per-run browser isolation without requiring API to know browser details.
- Non-goals: changing worker count or adding rate limiting.
- Success criteria: worker derives distinct values; dispatcher cleanup targets same dir.
- Public interfaces: same env vars, but consumed by worker and dispatcher.
- Edge cases / failure modes: drift between worker derivation and dispatcher cleanup is the main risk; fail closed on invalid env.
- Rollout & monitoring: same as Draft A.
- Acceptance checks: same focused tests and gates.

#### Dependencies

Stdlib only.

#### Validation

Focused worker tests must prove derivation. Dispatcher cleanup tests must protect against drift.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Worker derivation | `run_worker_job(command="discover")` | `_build_browser_settings()` | N/A |
| Dispatcher cleanup | dispatcher `finally` | duplicated/mirrored path logic | N/A |

Cross-language schema verification: no DB schema changes.

### Comparative Analysis

Draft A is safer operationally because the dispatcher owns the lifecycle: it creates the worker run, sends the exact browser settings, can persist them in summary metadata, and can clean the exact directory it assigned. Draft B keeps browser defaults local to worker code but creates a drift hazard between the worker's chosen profile path and the dispatcher's cleanup target.

Both plans follow the repo's control-plane/worker-plane split. Draft A better matches the PR scope wording: "Extend `_resolve_browser_settings_payload` to compute `browser_cdp_port` and `browser_profile_dir`."

### Unified Execution Plan

#### Overview

Implement Draft A. The dispatcher will compute deterministic per-run browser isolation from new env vars, include it in the existing worker payload, and clean the per-run profile directory after the worker exits.

#### Files to Change

- `apps/api/src/egp_api/config.py`: new browser env parsing helpers.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: payload enrichment and cleanup.
- `apps/worker/src/egp_worker/main.py`: verify/adjust mapping for `browser_cdp_port` and `browser_profile_dir`.
- `tests/phase1/test_api_discovery_spawn.py`: dispatcher tests.
- `tests/phase1/test_worker_live_discovery.py`: worker mapping test if current coverage is insufficient.
- `docs/DEPLOYMENT.md`: document new env vars and pilot gate.

#### Implementation Steps

TDD sequence:

1. Add/stub dispatcher tests:
   - ports derive from run IDs and stay inside `[base, base + range)`.
   - profile dirs equal `profile_root / run_id`.
   - cleanup removes the per-run profile dir after success and worker failure.
2. Run `./.venv/bin/python -m pytest tests/phase1/test_api_discovery_spawn.py -q` and confirm RED.
3. Implement config helpers, derivation, and cleanup.
4. Run focused tests until GREEN.
5. Run worker mapping test; add coverage only if current test does not cover flat keys.
6. Run `./.venv/bin/ruff check apps/api apps/worker tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py`.
7. Run `./.venv/bin/python -m compileall apps/api/src apps/worker/src`.
8. Stage intended files, run g-check review, fix findings, then commit/PR.

Functions:

- `get_browser_cdp_port_base()`: parse `EGP_BROWSER_CDP_PORT_BASE`, default `9222`, fail closed when invalid.
- `get_browser_cdp_port_range()`: parse `EGP_BROWSER_CDP_PORT_RANGE`, default `200`, fail closed when invalid.
- `get_browser_profile_root()`: parse `EGP_BROWSER_PROFILE_ROOT`, default `~/.egp/profiles`.
- `_browser_cdp_port_for_run_id(run_id, base, port_range)`: deterministic hash modulo range.
- `_resolve_browser_settings_payload(..., run_id, profile_root, cdp_port_base, cdp_port_range)`: returns max-page profile settings plus browser isolation keys.
- `_cleanup_browser_profile_dir(profile_dir, profile_root)`: removes only safe per-run dirs under root.

#### Test Coverage

- `test_discover_spawner_assigns_browser_isolation_payload_from_run_id`: deterministic port and profile dir.
- `test_discover_spawner_assigns_distinct_browser_isolation_payloads`: two runs do not share isolation settings.
- `test_discover_spawner_cleans_browser_profile_dir_after_success`: no profile dir left on success.
- `test_discover_spawner_cleans_browser_profile_dir_after_failure`: no profile dir left on subprocess failure.
- `test_run_worker_job_forwards_browser_settings_to_discover_workflow`: existing mapping covers the worker handoff.

#### Decision Completeness

- Goal: eliminate shared CDP port/profile dir collisions across concurrent worker subprocesses on one host.
- Non-goals: enabling production worker count > 1 in this PR, implementing host-level rate limiting, adding DB migrations, or modifying discovery job claim fairness.
- Success criteria: focused tests pass; runtime payload includes `browser_cdp_port` and `browser_profile_dir`; cleanup is fail-safe and bounded to the configured root; docs describe observation before raising worker count.
- Public interfaces: new env vars `EGP_BROWSER_CDP_PORT_BASE`, `EGP_BROWSER_CDP_PORT_RANGE`, `EGP_BROWSER_PROFILE_ROOT`; worker payload keys `browser_settings.browser_cdp_port`, `browser_settings.browser_profile_dir`.
- Edge cases / failure modes:
  - Invalid port env values: fail closed with `RuntimeError`.
  - Port hash collision when range too small: deterministic but possible; default range 200 keeps risk low for small worker counts.
  - Profile cleanup failure: log warning and continue because dispatch outcome should still reflect worker result.
  - Path traversal/symlink-like unsafe cleanup target: refuse cleanup outside configured root.
- Rollout & monitoring:
  - Keep `EGP_DISCOVERY_WORKER_COUNT=1` for 72h.
  - Pilot `EGP_DISCOVERY_WORKER_COUNT=2` on one host for 48h.
  - Watch worker subprocess count, orphan Chrome PIDs, and profile root growth.
  - Roll back by restoring `EGP_DISCOVERY_WORKER_COUNT=1` and previous image if orphan PIDs exceed worker count after 60s or tenant attribution anomalies appear.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py -q`
  - `./.venv/bin/ruff check apps/api apps/worker tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py`
  - `./.venv/bin/python -m compileall apps/api/src apps/worker/src`

#### Dependencies

No new third-party dependencies.

#### Validation

CI validates payload and cleanup behavior without launching real Chrome. Production validation uses the rollout watch metrics and `pgrep`/profile-root inspection from the PR plan.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Env helpers | `SubprocessDiscoveryDispatcher.__init__()` | imported from `egp_api.config` | N/A |
| Browser isolation payload | worker subprocess stdin | `SubprocessDiscoveryDispatcher.dispatch()` JSON payload | N/A |
| Worker settings mapping | discover worker command | `egp_worker.main.run_worker_job()` calls `_build_browser_settings()` | N/A |
| Profile cleanup | dispatch completion path | `SubprocessDiscoveryDispatcher.dispatch()` `finally` | N/A |
| Deployment docs | operator rollout | `docs/DEPLOYMENT.md` | N/A |

Cross-language schema verification: no DB schema changes.

#### Decision-Complete Checklist

- No open implementation decisions remain.
- Public env vars and payload keys are listed.
- Behavior changes have focused tests.
- Validation commands are scoped to touched API/worker code.
- Wiring verification covers each new runtime component.
- Rollout/backout is documented.

## Implementation Summary (2026-05-23 21:24:00 +0700)

### Goal

Implement PR-03 per-worker browser isolation through PR-ready local changes: deterministic per-run Chrome CDP ports, per-run Chrome profile dirs, worker payload mapping, cleanup, deployment docs, and compose env wiring.

### What Changed

- `apps/api/src/egp_api/config.py`: added `EGP_BROWSER_CDP_PORT_BASE`, `EGP_BROWSER_CDP_PORT_RANGE`, and `EGP_BROWSER_PROFILE_ROOT` helpers with safe defaults.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: added deterministic port derivation, profile-dir derivation bounded to the configured root, browser settings payload enrichment, and profile-dir cleanup in `finally`.
- `apps/worker/src/egp_worker/main.py`: normalized nested browser payload aliases so `browser_cdp_port` maps to `BrowserDiscoverySettings.cdp_port`.
- `apps/api/tests/test_browser_isolation.py`: added dispatcher isolation and cleanup coverage.
- `tests/phase1/test_api_discovery_spawn.py`: updated max-pages payload assertion to include the new always-present browser isolation keys.
- `tests/phase1/test_worker_live_discovery.py`: changed worker handoff coverage to use nested `browser_cdp_port`.
- `docker-compose.yml` and `docker-compose-localdev.yml`: exposed browser isolation env vars on `discovery-executor`.
- `docker-compose.yml` and `docker-compose-localdev.yml`: exposed browser isolation env vars on `api` too, so embedded-mode fallback gets the same explicit settings.
- `docs/DEPLOYMENT.md` and `docs/LIGHTSAIL_LOW_COST_LAUNCH.md`: documented new env vars, isolation behavior, and rollout gate.

### TDD Evidence

RED:

- Command: `./.venv/bin/python -m pytest apps/api/tests/test_browser_isolation.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py -q`
- Result: failed during collection because `_browser_cdp_port_for_run_id` did not exist yet. This proved the new browser isolation tests were exercising missing implementation.

GREEN:

- Command: `./.venv/bin/python -m pytest apps/api/tests/test_browser_isolation.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py -q`
- Result: `56 passed in 0.64s`
- Command repeated after docs/compose edits for flakiness check.
- Result: `56 passed in 0.68s`
- Command repeated a third time for flakiness check.
- Result: `56 passed in 0.60s`

### Tests And Gates

- `./.venv/bin/ruff check apps/api apps/worker tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py` -> passed.
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src` -> passed.
- `docker compose -f docker-compose-localdev.yml config --quiet` -> passed.
- `EGP_POSTGRES_PASSWORD=dummy EGP_PAYMENT_CALLBACK_SECRET=dummy EGP_JWT_SECRET=dummy EGP_WEB_ALLOWED_ORIGINS=https://app.example.test EGP_WEB_BASE_URL=https://app.example.test EGP_INTERNAL_WORKER_TOKEN=dummy NEXT_PUBLIC_EGP_API_BASE_URL=https://api.example.test NEXT_PUBLIC_SITE_URL=https://app.example.test EGP_API_DOMAIN=api.example.test EGP_APP_DOMAIN=app.example.test docker compose -f docker-compose.yml config --quiet` -> passed.
- Initial production compose validation without required env vars failed, as expected, because `NEXT_PUBLIC_SITE_URL` is required for interpolation.
- `./.venv/bin/python -m pytest tests/phase2/test_background_runtime_mode.py -q` -> `7 passed`.

### Wiring Verification Evidence

| Component | Wiring Verified? | Evidence |
|---|---|---|
| Env helpers | YES | `SubprocessDiscoveryDispatcher.__init__()` reads all three helpers before dispatching jobs. |
| Browser isolation payload | YES | `SubprocessDiscoveryDispatcher.dispatch()` always includes `browser_settings` in worker stdin JSON. |
| Worker mapping | YES | `run_worker_job(command="discover")` passes `_build_browser_settings(payload)` into `run_discover_workflow()`. |
| Profile cleanup | YES | Dispatcher `finally` calls `_cleanup_browser_profile_dir()` after log handle close. |
| Compose env | YES | `docker compose ... config --quiet` passes for production and localdev compose files. |

### Behavior Changes And Risk Notes

- Dispatcher now fails closed during construction when browser CDP env values are invalid or the configured range exceeds port 65535.
- Cleanup is best effort: it refuses paths outside `EGP_BROWSER_PROFILE_ROOT`, refuses the root itself, logs failures, and does not mask the worker result.
- Default range `200` can still collide by hash if many concurrent runs are active; the rollout keeps `EGP_DISCOVERY_WORKER_COUNT=1` first and pilots `2` before broad rollout.

### Follow-Ups / Known Gaps

- CI tests do not spawn real Chrome or assert `lsof` output; that remains a production/pilot observation gate.
- Host-level rate limiting is still PR-06 and must ship before broad worker-count increases.

## Review (2026-05-23 21:34:00 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feat/per-worker-browser-isolation`
- Commit reviewed: staged working tree based on `1e414652`
- Commands Run:
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --name-only`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached -- apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached -- apps/api/src/egp_api/config.py apps/worker/src/egp_worker/main.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached -- apps/api/tests/test_browser_isolation.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached -- docker-compose.yml docker-compose-localdev.yml docs/DEPLOYMENT.md docs/LIGHTSAIL_LOW_COST_LAUNCH.md`
  - `nl -ba apps/api/src/egp_api/services/discovery_worker_dispatcher.py | sed -n '25,120p'`
  - `nl -ba apps/api/src/egp_api/services/discovery_worker_dispatcher.py | sed -n '210,400p'`
  - `nl -ba apps/worker/src/egp_worker/main.py | sed -n '30,75p'`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --check --cached`

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

- Assumes deterministic run-ID hashing is acceptable for the pilot worker counts in PR-03. With the default range of 200, collisions remain theoretically possible but unlikely at worker_count 2; broader concurrency still depends on later rollout gates.
- Assumes real Chrome/lsof validation is performed during the observation window, not in normal CI.

### Recommended Tests / Validation

- Already run focused pytest, ruff, compileall, and both compose config validations.
- Production pilot should verify no orphan Chrome PIDs after runs and no profile-root growth under `EGP_BROWSER_PROFILE_ROOT`.

### Rollout Notes

- Keep `EGP_DISCOVERY_WORKER_COUNT=1` for the first PR-03 observation window.
- Pilot `EGP_DISCOVERY_WORKER_COUNT=2` on one host only after single-worker behavior is clean.
- Roll back by restoring worker count to 1 and redeploying the previous image if orphan Chrome PIDs exceed worker count after 60 seconds or any tenant attribution anomaly appears.
