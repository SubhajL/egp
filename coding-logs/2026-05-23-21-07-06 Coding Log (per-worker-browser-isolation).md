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

## Merge (2026-05-24 06:01:34 +0700)

- PR #106 (`feat: isolate discovery worker browsers`) was admin-merged into `main`.
- Merge commit: `6fc0223f2876d0fc9011c1cf178bc39a09d45646`.
- Pre-merge GitHub state: PR was mergeable but blocked by failed CI/claude checks; all CI jobs ended in 1-2 seconds with no step details in compact metadata.
- Local sync: fetched `origin/main` and updated local `main` to match `origin/main`.
- Next: monitor the PR-03 production pilot gates described above.


## Review (2026-06-07 18:07:19 +0700) - system

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: document capture/retry/status visibility subsystem
- Commands Run: git rev-parse --show-toplevel; git branch --show-current; git status --porcelain=v1; git log -n 20 --oneline --decorate; rg for document capture/retry/API/UI identifiers; nl/sed on worker, API, web, db, docs, and tests.
- Sources: AGENTS.md; CLAUDE.md; docs/PRD.md; docs/DEPLOYMENT.md; docs/REMOTE_LOCAL_CRAWLER.md; docs/LIGHTSAIL_LOW_COST_LAUNCH.md; apps/worker/src/egp_worker/browser_downloads.py; browser_discovery.py; browser_close_check.py; workflows/discover.py; workflows/close_check.py; apps/api/src/egp_api/executors/discovery_dispatch.py; scheduled_discovery_enqueue.py; services/discovery_worker_dispatcher.py; apps/api/src/egp_api/routes/documents.py; routes/projects.py; packages/db project/document repositories; apps/web project detail page; relevant phase1/phase2/phase4 tests.

### High-Level Assessment
- The prior diagnosis is mostly correct: the project-detail empty document panel reflects zero persisted rows from /v1/documents/projects/{project_id}, not entitlement filtering.
- Document capture is a single live attempt per discovery observation and has brittle targeted-table heuristics: fixed 0.5s settle, header keyword gate, >=3 cell row requirement, label-first target matching, and final-TOR label filtering.
- The close-check live retry path does have a catch-22: it selects only projects that already have invitation-stage document rows, excluding zero-doc misses.
- Production/off-box Track C runners dispatch discovery jobs, not close_check jobs. However scheduled discovery enqueue exists and can be a retry path if the timer is installed and due jobs are generated; the original statement that close-check is the only possible retry mechanism is too absolute.
- Capture status is produced in worker payload/raw_snapshot, but raw_snapshot is stored on project_status_events, not projects, and status event deduplication can prevent later capture outcomes from being persisted.

### Strengths
- Worker discovery keeps metadata when document collection times out, so project rows are not lost with document failures.
- Discovery dispatcher explicitly sends live_include_documents=true.
- Document list endpoint is tenant/project scoped and ungated; download byte/link paths are entitlement-gated.
- Tests already cover no_documents/timeout payload marking, close-check document revisit plumbing, and the current has_invitation_stage_documents=True selector.
- Scheduled discovery enqueue exists for the off-box topology and can create repeat discovery jobs without browser work on the VM.

### Key Risks / Gaps (severity ordered)
CRITICAL
- Zero-document projects are excluded from close-check retries. close_check.py lines 111-116 calls list_projects(..., has_invitation_stage_documents=True), and project_queries.py lines 182-191 defines that as a document row with source_status_text like invitation. Impact: first-pass zero-doc projects cannot be recovered by close-check.
- Capture outcome persistence is not a reliable project-level fact. browser_discovery.py lines 1077-1105 writes document_collection_status into raw_snapshot, but project_schema.py lines 108-123 stores raw_snapshot only on project_status_events. project_aliases.py lines 122-134 skips inserting a new status event when observed_status_text and normalized_status match the latest event, so later retry outcomes can be invisible.

HIGH
- Targeted document-table detection is brittle. browser_downloads.py lines 377-391 performs a fixed 0.5s sleep and only considers tables whose th text contains ดูข้อมูล or ดาวน์โหลด. Rows with icon-only headers, late-rendered tables, or non-table/card layouts can produce zero downloadable_rows.
- Targeted row parsing drops plausible rows. browser_downloads.py lines 398-401 skips rows with fewer than 3 td cells; two-cell layouts (label + action) are currently ignored.
- Final TOR collection can discard valid artifacts based on label-only classification. browser_downloads.py lines 433-439 filters successful final-target downloads using is_final_tor_doc_label on source_label/doc_name, while classifier.py lines 70-142 can return OTHER for odd/bare labels. The ingest classifier can use file_name/status/page context, but this early filter happens before ingest.
- Track C production runner does not invoke close_check. scripts/run_remote_crawl.sh lines 62-63 and discovery_dispatch.py lines 63-105/133-155 only claim discovery_jobs and dispatch discover worker payloads. The worker supports close_check commands, but no checked runner/scheduler sends them.

MEDIUM
- Scheduled discovery is a partial retry path, not a complete backfill. scheduled_discovery_enqueue.py lines 44-89 can enqueue due active profile keywords, and discovery_job_repo.py lines 194-244 allows new schedule jobs after no pending duplicate remains. But docs mark timer install optional, and it retries by keyword/search-result availability, not by explicit zero-doc/backfill state.
- UI empty state lacks operational context. apps/web/src/app/(app)/projects/[id]/page.tsx lines 408-414 renders a flat empty message from documents.length; it ignores status_events.raw_snapshot even though routes/projects.py lines 54-62 and 144-162 expose it.
- Observability lacks a low-cardinality document collection metric. metrics.py defines API, worker, e-GP request, queue, dispatch, and upsert metrics, but no document_collection_status counter; current signals are logs/progress payloads.

LOW
- The recommended confirmation SQL in the prior analysis is wrong for this schema: projects has no raw_snapshot column. Query latest project_status_events.raw_snapshot instead, and treat the result as possibly stale due event dedupe.
- Existing parser tests focus on header-keyed table happy paths and procurement-plan fallbacks. Missing fixture tests for delayed tables, two-cell rows, icon-only action columns, generic doc links/buttons, and final-TOR filename fallback.

### Nit-Picks / Nitty Gritty
- _download_documents_from_current_view waits for a table and can find nested download tables, but the initial targeted scan still fails before that path unless it first matches a target row or falls to narrow detail-page candidates.
- collect_downloaded_documents skips fallback after any clean targeted success, which is fine for avoiding duplicates but can hide other document categories if the first target succeeds and later targets silently miss without throwing.
- The UI has crawl evidence available through /v1/projects/{project_id}/crawl-evidence; an operator-focused status summary could draw from both latest status event raw_snapshot and recent task payload/result_json.

### Tactical Improvements (1-3 days)
1. Add a document-backfill selection path for open/early projects with zero documents or latest capture outcome in no_documents/timeout/failed/deferred; do not reuse has_invitation_stage_documents=True.
2. Wire a scheduled/runner command for document backfill or close-check-with-documents in Track C, with a bounded limit and tenant scoping.
3. Add first-class latest document_collection_status/reason fields or a latest document_collection_observations table; do not rely only on deduped status_events.raw_snapshot.
4. Surface capture status in project detail API/UI and replace the flat empty state with status-aware copy.
5. Add a Prometheus counter such as egp_document_collection_total{status,reason} plus task/run summary counts.

### Strategic Improvements (1-6 weeks)
1. Split document collection into its own durable job type keyed by tenant_id/project_id, with retry/backoff, max age, status, and operator retry controls.
2. Treat document capture attempts as audit/observability events separate from lifecycle status events, so repeated same-status observations are preserved without polluting lifecycle history.
3. Maintain fixture-based crawler parser tests from real e-GP HTML snapshots for each known layout family.

### Big Architectural Changes (only if justified)
- Proposal: introduce a document_capture_jobs/document_capture_attempts subsystem rather than overloading discovery and close_check.
  - Pros: explicit retries, metrics, UI status, decouples document availability from lifecycle closure, avoids catch-22.
  - Cons: new schema and scheduler path; needs careful tenant scoping and queue bounds.
  - Migration Plan: first add latest capture fields/attempt table; populate from existing latest status_events where possible; enqueue only zero-doc early/open projects; run dry/limited Track C batches; then make discovery enqueue capture jobs instead of doing all capture inline.
  - Tests/Rollout: unit tests for selectors and retry state; repository tests for tenant isolation; worker tests for job status transitions; staged batch limit in production; metrics alert on failed/timeout/no_documents rates.

### Open Questions / Assumptions
- I did not run the production read-only DB query, so the exact failure mode for project 8e645ef7-a063-45b9-a8bb-cec61d6983fa remains unconfirmed.
- Whether scheduled discovery is currently installed in production is operational state, not provable from code. The repo documents it as optional in the off-box Track C setup.
