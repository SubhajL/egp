# Worker Live Discovery Slice

## Overview

Implement the first real migration slice from the legacy `egp_crawler.py` into `apps/worker`: browser-driven discovery. This slice moves Chrome/CDP startup, Cloudflare wait, keyword search, result paging, and project detail extraction into worker-owned modules while keeping persistence on the existing run/task/project ingest path.

## Review (2026-04-07 07:29 local) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: `working-tree`
- Commands Run: `git status --porcelain=v1`, `git diff -- apps/api/src/egp_api/main.py apps/api/src/egp_api/routes/auth.py apps/api/src/egp_api/services/auth_service.py tests/phase4/test_auth_api.py tests/phase4/test_registration.py`, `git diff -- apps/web/src/app/login/page.tsx apps/web/src/app/signup/page.tsx apps/web/src/lib/api.ts apps/web/package.json apps/web/playwright.config.ts apps/web/next.config.mjs apps/web/tsconfig.json apps/web/next-env.d.ts apps/web/scripts/dev.sh apps/web/scripts/dev-web.sh docs/FRONTEND_HANDOFF.md docs/MANUAL_WEB_APP_TESTING.md tests/phase2/test_rules_api.py`, `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_registration.py tests/phase2/test_rules_api.py -q`, `./.venv/bin/ruff check apps/api packages tests/phase4/test_auth_api.py tests/phase4/test_registration.py tests/phase2/test_rules_api.py`, `(cd apps/web && npm run typecheck && npm run build)`

### Findings
CRITICAL
- No findings.

HIGH
- Resolved during review: email-only login originally selected the first matching user across tenants, which could have logged a shared email into the wrong workspace. The repository now fails closed unless the email maps to exactly one tenant, and coverage was added in `tests/phase4/test_auth_api.py`.

MEDIUM
- No findings.

LOW
- `apps/web/next-env.d.ts` now points at `.next-dev/types/routes.d.ts`, which is acceptable for local dev but remains a generated-file deviation from Next defaults. Residual risk is low because `apps/web/tsconfig.json` now includes both `.next/types/**/*.ts` and `.next-dev/types/**/*.ts`, and production `npm run build` passed.

### Open Questions / Assumptions
- Assumed the intended product rule is global duplicate-email prevention across tenants, so failing closed on ambiguous email-only login is safer than guessing a tenant.
- Assumed local Postgres-backed `npm run dev` should prefer convenience and auto-run pending migrations before boot.

### Recommended Tests / Validation
- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase4/test_registration.py tests/phase2/test_rules_api.py -q`
- `./.venv/bin/ruff check apps/api packages tests/phase4/test_auth_api.py tests/phase4/test_registration.py tests/phase2/test_rules_api.py`
- `cd apps/web && npm run typecheck && npm run build`
- Manual smoke on `localhost:3002` for signup, login, dashboard, and rules page with a Postgres-backed dev stack.

### Rollout Notes
- Postgres-backed local dev now depends on the migration runner being available in `../../.venv/bin/python`; if the venv is missing, `apps/web/scripts/dev.sh` will fail early instead of silently booting stale schema.
- Existing long-running dev servers need a restart to pick up the `.next-dev` isolation and loopback host-alignment fixes.

## Scope

- In scope:
  - live browser-driven discovery in `apps/worker`
  - worker profile defaults for `tor` / `toe` / `lue`
  - worker command dispatch support for live discovery
  - tests for live discovery orchestration and dispatch
- Out of scope in this slice:
  - document download migration
  - close-check browser sweep migration
  - scheduler/cron orchestration
  - full retirement of legacy `egp_crawler.py`

## Files Changed

- `apps/worker/src/egp_worker/profiles.py`
  - Added worker-side profile defaults and keyword resolution.
- `apps/worker/src/egp_worker/browser_discovery.py`
  - Added focused browser discovery module extracted from legacy behavior.
- `apps/worker/src/egp_worker/workflows/discover.py`
  - Added live discovery support while keeping synthetic payload mode intact.
- `apps/worker/src/egp_worker/main.py`
  - Wired `discover` command to accept `live` and `profile` inputs.
- `apps/worker/src/egp_worker/workflows/__init__.py`
  - Exported the discover workflow symbol.
- `tests/phase1/test_worker_live_discovery.py`
  - Added regression coverage for live discovery orchestration and worker dispatch.

## Plan

### Draft A

1. Add tests for `run_discover_workflow(..., live=True)` and worker command dispatch.
2. Extract browser/session helpers from the legacy crawler into a worker module.
3. Extend discover workflow to switch between synthetic payload mode and live crawl mode.
4. Keep the existing event-ingest boundary so persistence stays API/DB-owned.
5. Run worker gates and compile checks.

Strengths:
- minimal runtime surface change
- preserves existing ingest path
- delivers a real crawl slice quickly

Gaps:
- document download remains in legacy script
- browser parsing is still incomplete versus the monolith

### Draft B

1. First extract profile + parser modules into `packages/crawler-core`.
2. Then add a new browser orchestrator in worker.
3. After that, rewire discover workflow to depend on the package extractions.

Strengths:
- cleaner package boundaries
- more reusable long term

Gaps:
- slower path to first real crawler parity
- higher chance of getting stuck on abstraction work before runtime value

### Chosen Plan

Use Draft A for this slice. It gets the worker to perform a real live discovery crawl with the fewest moving parts while preserving the event-ingest control-plane boundary. Package extraction can continue in later slices without blocking first runtime value.

## TDD Evidence

### RED

Command:

```bash
./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q
```

Observed failures:

- `run_discover_workflow()` rejected new `live_discovery` parameter.
- `run_worker_job()` did not forward `live` to discover workflow.

### GREEN

Commands:

```bash
./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py -q
./.venv/bin/ruff check apps/worker packages tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py
./.venv/bin/python -m compileall apps/worker/src packages
```

Results:

- worker discovery tests passed
- lint passed
- compileall passed

## Implementation Notes

### `profiles.py`

- Copied the legacy profile keyword defaults into worker-owned structured defaults.
- Added `resolve_profile_keywords()` so live discovery can use either an explicit keyword or a profile default set.

### `browser_discovery.py`

- Extracted a focused subset of legacy runtime behavior:
  - Chrome launch with CDP
  - Playwright attach
  - Cloudflare wait
  - search page interaction
  - result paging
  - project detail extraction
- Kept this slice intentionally limited to discovery metadata only.
- Did not reintroduce Excel, OneDrive state, or document download behavior.

### `discover.py`

- Added `live`, `profile`, and `live_discovery` options.
- Preserved existing synthetic input mode used by current tests/callers.
- When live mode is enabled, the workflow crawls first, then emits the same `DiscoveredProjectEvent` contract as before.

### `main.py`

- `run_worker_job()` now accepts:
  - `live: true|false`
  - `profile: tor|toe|lue`
- Existing discover command behavior remains compatible.

## Wiring Verification

| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| `egp_worker.browser_discovery.crawl_live_discovery()` | YES | `apps/worker/src/egp_worker/workflows/discover.py` calls it when `live=True` |
| `run_discover_workflow(..., live=...)` | YES | `apps/worker/src/egp_worker/main.py` forwards `live` and `profile` from `run_worker_job()` |
| worker discover command live mode | YES | `tests/phase1/test_worker_live_discovery.py::test_run_worker_job_dispatches_live_discover_command` |
| event-ingest persistence path | YES | live discovery still emits `DiscoveredProjectEvent` through `project_event_sink.record_discovery()` in `discover.py` |

## Behavior Change

- Before this slice, worker discover only accepted precomputed `discovered_projects` payloads.
- After this slice, worker discover can now perform a real live browser crawl for discovery when invoked with `live=true`.

## Remaining Gaps

- No document download migration yet.
- No browser-driven close-check sweep yet.
- Result parsing is still a minimal extraction and may need hardening against live site changes.
- No scheduler yet to launch periodic live crawls automatically.

## Risk Notes

- The new browser discovery module is intentionally narrow and still depends on selectors copied from the legacy script.
- Procurement type inference is currently simple (`consulting` if text includes `ที่ปรึกษา`, else `services`) and should be refined in later slices.
- Live e-GP behavior was not exercised in CI; only orchestration paths were validated locally via tests.

## Validation

```bash
./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py -q
./.venv/bin/ruff check apps/worker packages tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py
./.venv/bin/python -m compileall apps/worker/src packages
```

All passed.

## Review (2026-04-06 22:40 local) - working-tree crawler slice

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Scope: worker live discovery working tree slice
- Commands Run:
  - `git status --porcelain=v1`
  - `git diff --name-only -- apps/worker/src/egp_worker/main.py apps/worker/src/egp_worker/workflows/discover.py apps/worker/src/egp_worker/workflows/__init__.py apps/worker/src/egp_worker/browser_discovery.py apps/worker/src/egp_worker/profiles.py tests/phase1/test_worker_live_discovery.py`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py -q` repeated 3 times

### Findings
No findings.

Residual risks:
- Live e-GP interaction is not exercised in CI, so selector brittleness remains a real risk.
- `_return_to_results()` still relies on browser back-navigation for this first slice; if the SPA mutates history unexpectedly, later hardening may prefer explicit re-navigation plus state reconstruction.

### Open Questions / Assumptions
- Assumed first-slice success means real live discovery orchestration exists, not full document-download parity.
- Assumed document download and close-check browser migration remain follow-up slices.

### Recommended Tests / Validation
- Run one manual live worker job against a safe tenant and confirm discovered projects land in `projects`, `project_aliases`, `crawl_runs`, and `crawl_tasks`.
- Add one integration harness later that stubs Playwright page transitions more deeply than the current orchestration tests.

### Rollout Notes
- Enable live discovery behind explicit worker payloads using `{"command":"discover","live":true,...}` first.
- Do not retire `egp_crawler.py` yet; document download and close-check are still incomplete.

## Implementation (2026-04-06 23:05 local) - next crawler slices

### Goal

Plan and implement the next three crawler slices after live discovery:
1. browser download persistence wiring
2. live close-check orchestration
3. scheduled discovery planning from tenant cadence + active profiles

### Plan

#### Overview

Keep the worker entrypoint thin and implement the next slices as deterministic, testable modules rather than background daemons or direct control-plane mutations. The worker should still emit events and artifacts; API/DB layers remain the owners of persistent product state.

#### Files To Change

- `apps/worker/src/egp_worker/browser_downloads.py`
- `apps/worker/src/egp_worker/scheduler.py`
- `apps/worker/src/egp_worker/workflows/close_check.py`
- `tests/phase1/test_document_infrastructure.py`
- `tests/phase1/test_worker_live_discovery.py`

#### Implementation Steps

1. Add RED tests for:
   - ingesting multiple downloaded browser artifacts
   - sourcing close-check observations from a live sweep helper
   - building due scheduled discovery jobs from tenant cadence/profile inputs
2. Implement a browser download ingestion helper that forwards downloaded file bytes into existing `ingest_document_artifact(...)`.
3. Extend `run_close_check_workflow(...)` to support a live observation source while preserving the existing direct observation mode.
4. Implement a deterministic scheduler planner that turns cadence/profile snapshots into `discover` worker jobs.
5. Run worker/document tests, lint, and compile checks.

#### Test Coverage

- `tests/phase1/test_document_infrastructure.py::test_ingest_downloaded_documents_persists_multiple_downloads`
- `tests/phase1/test_worker_live_discovery.py::test_run_close_check_workflow_uses_live_observation_source_when_observations_missing`
- `tests/phase1/test_worker_live_discovery.py::test_build_scheduled_discovery_jobs_returns_due_active_profile_keywords`

#### Decision Completeness

- Goal: add real runtime support modules for the next three crawler slices without introducing unwired daemons.
- Non-goals:
  - full browser document-download parity in this pass
  - full browser close-check site navigation in this pass
  - automatic background scheduling service in this pass
- Success criteria:
  - downloaded document bytes can be persisted in bulk through a worker helper
  - close-check workflow can source observations from a live sweep helper
  - scheduled discovery jobs can be derived from cadence/profile data deterministically
- Public interfaces changed:
  - `run_close_check_workflow(..., live_projects=..., live_observation_sweep=...)`
  - new modules `egp_worker.browser_downloads` and `egp_worker.scheduler`
- Rollout: helper-level enablement first; keep legacy crawler/runtime fallback in place.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `ingest_downloaded_documents()` | future browser download workflow calls | imported from `egp_worker.browser_downloads` | `documents`, `document_diffs` |
| live close-check observation path | `run_close_check_workflow()` | called from worker runtime/tests | `crawl_runs`, `crawl_tasks`, project ingest path |
| `build_scheduled_discovery_jobs()` | future scheduler/driver invocation | imported from `egp_worker.scheduler` | tenant cadence + `crawl_profiles` + `crawl_profile_keywords` snapshots |

### TDD Evidence

#### RED

Command:

```bash
./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_document_infrastructure.py -q
```

Observed failure reason:

- import errors for missing modules `egp_worker.scheduler` and `egp_worker.browser_downloads`

#### GREEN

Commands:

```bash
./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py -q
./.venv/bin/ruff check apps/worker packages tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py
./.venv/bin/python -m compileall apps/worker/src packages
```

Results:

- 22 tests passed
- lint passed
- compileall passed

### What Changed

- `apps/worker/src/egp_worker/browser_downloads.py`
  - Added `ingest_downloaded_documents(...)` to persist multiple browser-downloaded artifacts through the existing document ingest path.
- `apps/worker/src/egp_worker/scheduler.py`
  - Added `build_scheduled_discovery_jobs(...)` to derive due worker jobs from tenant cadence and active profile keywords.
- `apps/worker/src/egp_worker/workflows/close_check.py`
  - Added optional `live_projects` + `live_observation_sweep` support so close-check can source observations dynamically instead of only receiving precomputed inputs.
- `tests/phase1/test_document_infrastructure.py`
  - Added coverage for multiple downloaded document persistence.
- `tests/phase1/test_worker_live_discovery.py`
  - Added coverage for live close-check orchestration and scheduled discovery planning.

### Wiring Verification Evidence

- `browser_downloads.py` delegates directly to `ingest_document_artifact(...)`, so it is backed by the already-wired document repository/storage path.
- `close_check.py` still uses `project_event_sink.record_close_check(...)`, so project-state persistence remains API-owned.
- `scheduler.py` is deterministic and standalone by design; it intentionally produces worker job payloads rather than running its own background loop.

### 2026-04-06 23:xx Local - Complete Remaining Worker Runtime Slices

- Goal:
  - finish the remaining real worker runtime slices that were still missing after the first live-discovery pass
  - wire browser document extraction, browser close-check sweep, and DB-backed scheduled execution into actual callable worker paths
- What changed by file and why:
  - `apps/worker/src/egp_worker/browser_downloads.py`
    - replaced the earlier ingest-only helper with extracted Playwright download logic for direct downloads, content-view saves, new-tab saves, request fallback, and TOR subpage file lists
    - kept `ingest_downloaded_documents(...)` as the persistence bridge so browser bytes still flow through existing document metadata/storage wiring
  - `apps/worker/src/egp_worker/browser_discovery.py`
    - added optional `include_documents` handling so live discovery can collect browser-downloaded artifacts while already inside the project detail page
  - `apps/worker/src/egp_worker/browser_close_check.py`
    - added a focused browser sweep that searches current open projects by project number/name and returns status observations for close-check processing
  - `apps/worker/src/egp_worker/workflows/discover.py`
    - added `artifact_root` input
    - after discovery persistence, now ingests any `downloaded_documents` attached to the discovered payload
    - default live discovery path now requests browser document collection
  - `apps/worker/src/egp_worker/workflows/close_check.py`
    - added `live=True` project loading from the project repository when explicit observations are absent
    - default live path now calls `crawl_live_close_check(...)` when no injected observation sweep is provided
  - `apps/worker/src/egp_worker/scheduler.py`
    - kept deterministic job planner
    - added `run_scheduled_discovery(...)` to load active tenants/settings/profiles, derive last scheduled run timestamps from run history, compute due jobs, and execute them through an injected job runner
  - `apps/worker/src/egp_worker/main.py`
    - wired `artifact_root` into `discover`
    - wired `live` into `close_check`
    - added `run_scheduled_discovery` command dispatch
  - `packages/db/src/egp_db/repositories/admin_repo.py`
    - added `list_active_tenants()` so the scheduler can load eligible tenants without using ad hoc SQL in the worker
  - `tests/phase1/test_worker_live_discovery.py`
    - added RED/GREEN coverage for post-discovery downloaded-document ingest, live close-check project loading, scheduler execution, close-check worker dispatch, and scheduled-runner dispatch
- TDD evidence:
  - Tests added/changed:
    - `tests/phase1/test_worker_live_discovery.py`
  - RED command:
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q`
  - RED failure reason:
    - import error because `run_scheduled_discovery` did not yet exist in `egp_worker.scheduler`
  - GREEN commands:
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q`
    - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py -q`
    - repeated twice more with the same targeted pytest command to check flakiness
    - `./.venv/bin/ruff check apps/worker packages tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py`
    - `./.venv/bin/python -m compileall apps/worker/src packages`
    - `./.venv/bin/python -m compileall apps/worker/src/egp_worker/browser_downloads.py`
- Tests run and results:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py -q` -> `27 passed`
  - repeated twice -> `27 passed` and `27 passed`
  - `./.venv/bin/ruff check apps/worker packages tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py` -> all checks passed
  - `./.venv/bin/python -m compileall apps/worker/src packages` -> passed
- Wiring verification table:

| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| browser document extraction | YES | `browser_discovery.py` now imports `collect_downloaded_documents(...)` and attaches `downloaded_documents` during `open_and_extract_project(...)`; `discover.py` ingests them after `record_discovery(...)` |
| live close-check browser sweep | YES | `close_check.py` defaults `live=True` with no explicit observations to `crawl_live_close_check(...)`; `main.py` passes `live` through worker command dispatch |
| DB-backed scheduled runner | YES | `main.py` dispatches `run_scheduled_discovery`; `scheduler.py` loads active tenants via `admin_repo.list_active_tenants()`, settings via `get_tenant_settings()`, profiles via `list_profiles_with_keywords()`, and recent run history via `run_repo.list_runs()` |
| active-tenant scheduler repository path | YES | `admin_repo.py` now exposes `list_active_tenants()` for worker scheduler use instead of worker-local SQL |
- Behavior changes and risk notes:
  - live discover runs can now produce persisted document artifacts as part of the same worker flow if the browser can fetch them successfully
  - live close-check can now browse the site for current statuses instead of requiring precomputed observations
  - scheduled discovery now has a callable execution path, but it is still an on-demand worker command rather than a daemonized background service
  - browser download behavior is intentionally extracted minimally from the legacy crawler and may still need production hardening against site-specific edge cases not covered by repo tests
- Follow-ups and known gaps:
  - no end-to-end browser test harness exists in-repo for the real e-GP site, so browser-runtime validation is still based on extracted logic plus non-browser unit/integration coverage
  - the scheduled runner executes jobs when invoked, but external infrastructure still needs to trigger that worker command on a cadence in production

## Review (2026-04-07 local) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: `working-tree`
- Commands Run:
  - `git status --short --branch`
  - `git diff --name-only`
  - targeted `git diff -- ...` for API/web/rules and worker runtime files
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py -q`
  - `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/ruff check apps/api apps/worker packages tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_document_infrastructure.py tests/phase2/test_rules_api.py tests/phase4/test_admin_api.py`
  - `./.venv/bin/python -m compileall apps packages`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run build`

### Findings
HIGH
- `apps/worker/src/egp_worker/main.py` and `apps/worker/src/egp_worker/scheduler.py`
  - Initial review found that `run_scheduled_discovery` only planned jobs and returned counts; when called through the worker entrypoint it did not execute discover jobs, so scheduled runs would report success without producing crawl runs.
  - Fix applied: `main.py` now passes a `job_runner` that dispatches `discover` worker payloads, and regression coverage was added in `tests/phase1/test_worker_live_discovery.py`.

HIGH
- `apps/worker/src/egp_worker/workflows/discover.py`
  - Initial review found that live discovery payloads could contain raw `bytes` in `downloaded_documents`, which is unsafe for JSON-backed crawl task persistence and API transport snapshots.
  - Fix applied: task payloads are now sanitized via `_task_safe_payload(...)` before persistence, while raw bytes still flow only into `ingest_downloaded_documents(...)`; regression coverage was added in `tests/phase1/test_worker_live_discovery.py`.

### Open Questions / Assumptions
- Assumed this PR intentionally combines the earlier rules/admin/product work with the worker-runtime migration because both sets of changes are present in the working tree and were validated together.
- Assumed excluding unrelated untracked local artifacts and older coding logs from the PR is the correct scope.

### Recommended Tests / Validation
- Run a real local invocation of `run_scheduled_discovery` against a seeded Postgres database once browser credentials/profile state are available.
- Run one manual live `discover` and one manual live `close_check` against the real e-GP site to validate extracted browser behavior beyond mocked/integration coverage.

### Rollout Notes
- No findings remain after the two high-severity issues above were fixed and the relevant tests/build checks were rerun successfully.

## Review (2026-04-07 13:45 local) - working-tree (rules page redesign)

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feat/rules-page-plan-aware-redesign`
- Scope: `working-tree`
- Commands Run: `git status --porcelain=v1`, `git diff -- apps/web/src/app/(app)/rules/page.tsx`, `npm run typecheck`, `npm run build`, `npm run lint`

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- Three unused imports (`ArrowUpRight`, `Crown`, `RulesResponse`) were caught and removed before commit. The imports were speculative placeholders from the initial rewrite and had no runtime impact but would have been noise.

LOW
- The `headerTitle` variable computes the same value ("คำค้นติดตาม") for all three plan tiers. This is intentional for now (single page title) but the ternary structure is unnecessary — could be simplified to a constant. Left as-is since it documents intent for future per-tier differentiation.
- The `RuleProfile` type still carries `max_pages_per_keyword`, `close_consulting_after_days`, `close_stale_after_days` fields in the API response, but the UI no longer displays them. This is correct by design — the fields remain in the API contract for backend use, the UI simply stops exposing them to customers.

### Open Questions / Assumptions
- Assumed that the `ClosureRulesSummary` import and `ClosureTab` component are safe to remove entirely from the rules page, since closure rules are system behavior described in docs, not a customer-facing control.
- Assumed `entitlements.plan_code` is always populated by the API when a subscription exists — the `resolvePlanTier()` fallback to `free_trial` handles the null/unknown case safely.
- Assumed that the notification tab showing "กำลังเตรียมระบบ" for `event_wiring_complete === false` is acceptable since the feature is still being built.

### Recommended Tests / Validation
- Manual test with each plan tier (free_trial, one_time_search_pack, monthly_membership) to verify correct tabs appear.
- Manual test with no active subscription (null plan_code) to verify free_trial fallback.
- Verify keyword creation still works end-to-end after the form language changes.
- Verify schedule save still works for monthly_membership tier.

### Rollout Notes
- This is a purely frontend change — no API, database, or worker modifications.
- Build size for `/rules` is stable at 7.16 kB.
- All gates pass: typecheck, build, lint.

## Review (2026-04-07 09:45) - PR #30 full diff (2 commits)

### Reviewed
- Repo: egp
- Branch: feat/rules-page-plan-aware-redesign
- Scope: pr-diff (PR #30, commits bc4f857..f35447f vs main)
- Commands Run: `gh pr view 30`, `gh pr checks 30`, `git diff main...feat/rules-page-plan-aware-redesign`, typecheck, build

### Findings

CRITICAL
- (none)

HIGH
- (none)

MEDIUM
1. **headerTitle ternary is a no-op** (line 807-811): All three branches return the same string `"คำค้นติดตาม"`. This works but is dead code — either simplify to a constant or differentiate the titles per tier.
2. **Unused import: `ShieldCheck`** — still imported (line 10) and used in `NotificationsTab`, but the closure tab that was the primary consumer was removed. The remaining usage is fine but worth noting the icon semantics shifted. No build error.

LOW
1. **`WatchlistCard` shows per-profile quota line** (line 217-221) counting `profile.keywords.length / entitlements.keyword_limit` — this can be confusing when a tenant has multiple profiles since the quota is tenant-wide, not per-profile. Cosmetic issue, not a correctness bug.
2. **Tab bar renders before `QueryState` resolves** — tabs are visible while data is loading, but tab content shows the loading state. Acceptable UX but could flash the wrong tab count momentarily if the tier changes after data loads (handled by the `useEffect` on line 573-577).
3. **Missing `key` stability for tab icons** — `tabsForPlan` creates new JSX elements (`<Search />`, `<Clock3 />`, etc.) on every call. Since `tabs` is memoized by `tier` this is fine in practice, but the icon elements inside the memoized array are new references each time `tier` changes (which is rare).

### Open Questions / Assumptions
- The `ClosureRulesSummary` type is still imported and present in the API response but no longer consumed by the UI. Assumed this is intentional — the backend still returns it, the frontend ignores it.
- `Sparkles` icon (upgrade CTA) appears in both the entitlements card and the read-only schedule tab for free_trial. Assumed this intentional redundancy is acceptable for two different upgrade messages.
- CI checks were pending at review time; local gates all pass.

### Recommended Tests / Validation
- Manual test: switch between plan tiers and verify schedule tab shows read-only for free_trial/one_time, editable for monthly.
- Verify the immediate-crawl info line renders correctly in the keyword composer across all tiers.
- Confirm the upgrade CTA in the schedule tab only appears for free_trial (not one_time_search_pack).

### Rollout Notes
- Frontend-only change, no backend modifications.
- Build size for `/rules` grew slightly: 7.16 kB → 7.45 kB (expected from added schedule read-only UI).
- All local gates pass: typecheck, build, lint.
- CI checks pending on GitHub at time of review.

## Review (2026-04-07 local) - PR #31

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `fix/rules-page-nav-label-and-tab-style`
- Scope: pr-diff (PR #31, 4 commits, 17 files changed, +198 -108)
- Commands Run: `gh pr view 31`, `gh pr checks 31`, `git diff main...HEAD -- <paths>`, `npm run typecheck`, `npm run build`, `npm run lint`

### PR Summary
4 commits across 17 files:
1. Nav label rename ("กฎและโปรไฟล์" → "คำค้นติดตาม") + tab bar redesign (pill → underline)
2. Show plan summary line on all tabs (was hidden on entitlements tab)
3. Parse Pydantic 422 validation errors; Thai signup error normalization
4. Centralised `localizeApiError()` helper; updated all 16 catch blocks to never expose English API details

### Findings

CRITICAL — None

HIGH — None

MEDIUM
1. **Translation map ordering may cause wrong match** — `localizeApiError` uses `.includes()` substring matching and returns the first match. If a future API error contains a substring of an earlier pattern (e.g. "invalid token" inside "invalid or expired password reset token"), the shorter pattern wins and returns a less specific Thai message. Current entries happen to be ordered correctly (specific-first for tokens), but this is fragile.
   - File: `apps/web/src/lib/api.ts` (API_ERROR_TRANSLATIONS array)
   - Fix direction: Order longer/more-specific patterns before shorter ones, or switch to exact equality for known full strings and reserve `.includes()` only for genuine substring patterns.
   - Test: Unit test with overlapping substrings to verify correct precedence.

2. **`localizeApiError` silently swallows unknown errors** — When an error doesn't match any pattern, the fallback is returned and the original English detail is lost entirely. This is the intended UX behaviour (never show English), but makes debugging harder since the original detail is neither logged nor available in dev tools.
   - Fix direction: Consider `console.warn` in development mode when falling back, so devs can see the unmapped English string in the browser console.
   - Risk: Low — only affects developer experience, not end users.

LOW
3. **No unit tests for `localizeApiError`** — The function has ~50 translation entries and substring-matching logic but no test coverage. A regression in pattern ordering or matching logic would silently degrade UX.
   - Fix direction: Add a small test file (e.g. `apps/web/src/__tests__/localizeApiError.test.ts`) with cases for exact matches, substring matches, no-match fallback, and `null`/`undefined` inputs.

4. **`project-list.tsx` still references `NEXT_PUBLIC_EGP_TENANT_ID` in Thai message** — The tenant config message now reads "กรุณาเพิ่ม `NEXT_PUBLIC_EGP_TENANT_ID`..." which mixes Thai with an env var name. This is fine for developer-facing legacy code but could confuse non-technical users if exposed.
   - File: `apps/web/src/components/project-list.tsx`
   - Risk: Very low — this component is a legacy Phase 1 component unlikely to be shown to end users.

5. **Unused `ApiError` import in `invite/page.tsx`** — The old code used `ApiError` for `instanceof` checks, but the new `localizeApiError` call handles that internally. The import was updated to remove `ApiError` — correct.

### Open Questions / Assumptions
- Assumption: All known API error strings from the Python backend are covered by the 50-entry map. New endpoints or error messages added to the backend will need corresponding entries.
- The PR title says "align nav label and redesign rules page tab bar" but the scope grew significantly to include error localization. Consider updating the PR description.

### Recommended Tests / Validation
- Unit test for `localizeApiError()` covering: exact match, substring match, overlapping patterns, no-match fallback, non-Error input, null/undefined.
- Manual verification that login, signup, billing, and rules pages show Thai errors when API returns 4xx/5xx.
- Verify 422 Pydantic errors on signup show field-specific Thai messages (password too short, invalid email, missing company name).

### Rollout Notes
- Frontend-only changes, no backend modifications needed.
- All local quality gates pass: typecheck, build (21 routes), lint.
- CI checks pending on GitHub at time of review (Python lint passed, other checks running).
- Build size for `/rules` changed: 7.45 kB → 7.92 kB (tab bar redesign + localizeApiError import).
- No breaking changes to API contracts.

## Review (2026-04-07 13:30 local) - last-commit

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feat/immediate-discover-on-profile-create`
- Scope: `last-commit` (8db5bed)
- Commands Run: `git show --name-status --stat HEAD`, `git show HEAD -- <each file>`, Auggie codebase-retrieval for worker stdin protocol and discover workflow signature, `pytest tests/phase2/test_immediate_discover.py -v`, `pytest tests/phase2/test_rules_api.py -v`, `ruff check`, `compileall`

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
1. **stderr silenced in production spawner** — `stderr=subprocess.DEVNULL` in `_make_discover_spawner()` means worker tracebacks are permanently lost. The `_logger.warning` only fires on subprocess-level failures (e.g., `Popen` itself fails or `communicate()` times out), not on worker-internal errors.
   - *Why it matters*: If a keyword discover workflow crashes inside the worker, there's no log trail in the API process. Operators would need to independently find the worker's own log output.
   - *Fix direction*: Consider `stderr=subprocess.PIPE` and logging `proc.stderr` on non-zero exit codes, or at minimum `stderr=subprocess.STDOUT` piped to a log file. Alternatively, accept this as intentional since the worker is a separate process with its own logging — but document the tradeoff.
   - *Verdict*: Acceptable for now since worker processes have their own stdout/stderr and the spawner is best-effort. Flag for future observability improvements.

2. **No deduplication guard** — If a user rapidly creates profiles with overlapping keywords, multiple concurrent discover workers will run for the same keyword. The discover workflow will create duplicate runs and potentially duplicate project records.
   - *Why it matters*: Could cause data duplication in `crawl_runs` and `projects` tables.
   - *Fix direction*: The worker's `record_discovery()` path should be idempotent (upsert by project number), so project-level duplication is likely safe. Run-level duplication (multiple crawl_runs for the same keyword in the same minute) is cosmetic. Acceptable for MVP.

LOW
1. **10-minute timeout per keyword** — `proc.communicate(timeout=600)` is generous. If a user creates a profile with 20 keywords, that's up to 20 concurrent subprocesses, each potentially holding for 10 minutes. Resource consumption could spike.
   - *Fix direction*: Consider a lower timeout (120s) or limiting concurrent spawns. Not urgent for current usage patterns.

2. **`profile_id` passed but unused by worker** — The spawner sends `profile_id` as a kwarg in the route, but the actual `Popen` payload in `_make_discover_spawner` does not include `profile_id` in the JSON dict. It's accepted as a parameter but discarded.
   - *Impact*: No bug — the worker doesn't need `profile_id` currently. The parameter exists for future traceability. Harmless but slightly confusing.

### Open Questions / Assumptions
- The worker's `run_discover_workflow` is idempotent at the project level (upsert by project_number), so concurrent duplicate spawns won't cause corrupt data — just redundant crawl runs.
- BackgroundTasks run sync callables in a threadpool, so `proc.communicate()` does not block the event loop. Verified correct per Starlette docs.
- Starlette TestClient executes BackgroundTasks synchronously before returning the response, so recorder-based tests are deterministic. Verified correct.

### Recommended Tests / Validation
- Current coverage is adequate for the feature scope:
  - `test_profile_creation_triggers_discover_per_keyword` — verifies spawner called once per keyword with correct args
  - `test_profile_creation_succeeds_when_spawner_is_none` — verifies graceful degradation
- Optional future test: verify that a spawner that raises an exception doesn't break profile creation (currently implied by the try/except in the spawner, but not directly tested in the route layer).

### Rollout Notes
- No database migrations required.
- No new dependencies.
- Feature is automatically active when `DATABASE_URL` is set (spawner is always wired).
- Spawner failures are swallowed — profile creation succeeds regardless. This is the correct behavior for a best-effort enhancement.

## Review (2026-04-07 14:05 local) - system

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feat/immediate-discover-on-profile-create`
- Scope: PRs `#29`, `#30`, `#31`, `#32`
- Commands Run: `gh pr view 29/30/31/32 --json ...`, Auggie semantic review for auth/rules/immediate-discovery paths, targeted reads of `apps/api/src/egp_api/{main.py,routes/auth.py,services/auth_service.py,routes/rules.py}`, `packages/db/src/egp_db/repositories/auth_repo.py`, `apps/web/src/app/{login,signup}/page.tsx`, `apps/web/src/app/(app)/rules/page.tsx`, `apps/web/src/lib/{api.ts,hooks.ts}`, targeted `grep` for `localizeApiError` and frontend test coverage
- Sources: root `AGENTS.md`, `apps/api/AGENTS.md`, `apps/web/AGENTS.md`, PR metadata and current runtime wiring

### High-Level Assessment
- The direction is strong. These PRs materially improved product coherence: auth is more self-serve, the rules page is much more customer-facing, Thai localization is centralized instead of scattered, and PR32 closes a real product gap by making the backend honor the UI promise of immediate crawl start.
- The system is also still in a “fast-moving monolith” phase. The main weakness is not code quality in the small; it is that several user-facing behaviors are encoded as stringly-typed conventions across layers: plan tiers in the frontend, English error text translated in the client, and immediate crawl dispatch piggybacked on an API process background task.
- Net: good product progress, good pragmatism, but the next step should be contract-hardening and operational hardening rather than more UI churn.

### As-Is Pipeline Summary
- Auth:
  - Web login/signup pages call `apps/web/src/lib/api.ts` helpers.
  - `POST /v1/auth/login` accepts optional `tenant_slug`, but `apps/web/src/app/login/page.tsx` currently submits only `email`, `password`, and optional `mfa_code`.
  - `AuthService.login()` falls back to cross-tenant lookup when `tenant_slug` is absent.
  - `auth_repo.find_login_user_by_email()` returns a user only when the email maps to exactly one tenant; otherwise it returns `None`.
- Rules UI:
  - `apps/web/src/app/(app)/rules/page.tsx` fetches a single rules snapshot via `useRules()`.
  - The page derives tab visibility, plan badges, quota copy, upgrade messaging, and schedule editability from `entitlements.plan_code` plus local helper logic.
  - Mutations call `createRuleProfile()` and `updateTenantSettings()`, then re-fetch the whole rules query.
- Immediate discovery:
  - `POST /v1/rules/profiles` creates the profile, then schedules one `BackgroundTasks` job per keyword.
  - `app.state.discover_spawner` in `apps/api/src/egp_api/main.py` launches `python -m egp_worker.main`, writes a JSON `discover` payload to stdin, and waits for completion.
  - The worker runs `run_discover_workflow(..., live=True, trigger_type="profile_created")`.

### Strengths
- Good product-loop closure: PR32 makes the backend align with the UI promise instead of leaving “immediate crawl” as copy only.
- Good UX prioritization: PR29/30/31 reduced internal jargon and made the product feel more customer-facing.
- Good fail-closed auth change: duplicate email across tenants no longer logs the user into an arbitrary workspace.
- Good pragmatic centralization: `localizeApiError()` is better than duplicating raw `error.message` handling in many pages.
- Good incremental strategy: the changes stayed within current architecture rather than forcing premature infrastructure.

### Key Risks / Gaps
CRITICAL
- No findings.

HIGH
- **Shared-email users can now be locked out from the web login flow.**
  - Evidence: `apps/web/src/app/login/page.tsx` submits `login({ email, password, mfa_code })` with no `tenant_slug`, while `packages/db/src/egp_db/repositories/auth_repo.py` returns `None` when an email exists in more than one tenant and `AuthService.login()` converts that to `invalid credentials`.
  - Observable symptom: a valid user with the same email in two workspaces cannot log in from the current web UI, and the error message implies the password is wrong.
  - Boundary that fails: UI capability no longer matches backend auth contract.
  - Fix direction: bring back an advanced/fallback workspace field on the login page, or return a structured `ambiguous_email_requires_workspace` error and reveal the field only when needed.

- **Immediate discovery dispatch is non-durable and can be lost after a 201 response.**
  - Evidence: `apps/api/src/egp_api/routes/rules.py` uses `BackgroundTasks.add_task(...)`; `apps/api/src/egp_api/main.py` spawns the worker from inside the API process with no persisted job/outbox.
  - Observable symptom: profile creation succeeds, but if the API process is recycled, crashes, or the task never runs after the response is sent, the “start immediately” promise is silently missed until the next scheduled crawl.
  - Boundary that fails: request/response success is not coupled to dispatch durability.
  - Fix direction: introduce a durable job table/outbox for discovery requests before moving to a separate queueing system.

MEDIUM
- **Frontend localization is brittle because it is keyed off English backend text, not stable error codes.**
  - Evidence: `apps/web/src/lib/api.ts` uses substring matching in `API_ERROR_TRANSLATIONS`; `apps/web/src/app/signup/page.tsx` also special-cases 422 messages by inspecting English fragments like `password` and `short`.
  - Impact: harmless backend wording changes can silently regress Thai UX across many pages.
  - Fix direction: move to structured API error codes plus optional localized display strings.

- **Plan and capability logic is hardcoded in one large page component, creating contract drift risk.**
  - Evidence: `apps/web/src/app/(app)/rules/page.tsx` defines `resolvePlanTier()`, `tabsForPlan()`, `PLAN_DISPLAY`, schedule rules, upgrade copy, and tab rendering in one client page.
  - Impact: the frontend is effectively re-implementing entitlement semantics locally. If plans evolve, the page can drift from backend truth.
  - Fix direction: have the API return a normalized capability model for the rules screen, or at least move plan/tier derivation into a typed shared module.

- **Observability on immediate crawl failures is weak.**
  - Evidence: `_make_discover_spawner()` sends both `stdout` and `stderr` to `DEVNULL`, and only logs when `Popen` or `communicate()` itself raises.
  - Impact: worker-internal failures are difficult to diagnose from the API side.
  - Fix direction: capture non-zero exit codes and stderr summary, or emit a run/event record before handoff.

- **Frontend coverage does not appear to match the importance of the UX changes.**
  - Evidence: I found backend tests for auth and rules APIs, and Playwright is configured in `apps/web/package.json`, but I did not find dedicated coverage for the new rules-plan tabs, Thai error localization behavior, or the ambiguous-email login fallback.
  - Impact: regressions here are likely to be caught late by manual QA.

LOW
- **Rules page is carrying too much responsibility in one file.**
  - `apps/web/src/app/(app)/rules/page.tsx` is doing layout, product logic, mutation orchestration, copy, and rendering branches in one place.

- **Defaulting unknown plans to `free_trial` is safe but potentially misleading.**
  - `resolvePlanTier()` treats unknown/null as `free_trial`. That avoids crashes but can hide config/contract drift.

- **Current mutation flow always re-fetches the whole rules snapshot.**
  - This is simple and correct, but eventually the page will benefit from React Query mutations and targeted cache updates.

### Nit-Picks / Nitty Gritty
- `profile_id` is passed through the route-side spawner call but not forwarded in the worker JSON payload. Not wrong, just slightly confusing.
- `localizeApiError()` is a solid step, but it now acts like a mini translation engine inside the API client; that deserves tests of its own.
- `signup/page.tsx` contains business-specific 422 parsing that probably belongs next to the shared API error normalization rather than in one page.
- `getApiBaseUrl()` loopback normalization is pragmatic and helpful for local dev, but it is doing environment-policy work in the client. Keep it documented and narrow.

### Drift Matrix
- Intended: email-only login should simplify auth without losing access for valid users in multi-tenant setups.
  - Implemented: duplicate emails fail closed, but the login page no longer appears to provide a workspace disambiguation path.
  - Impact: some legitimate users are blocked.
  - Fix direction: conditional workspace fallback.

- Intended: the rules page should reflect entitlements and plan differences clearly.
  - Implemented: the frontend derives most plan semantics itself from `plan_code`.
  - Impact: fast to ship, but contract drift risk grows with pricing/product complexity.
  - Fix direction: server-provided rules-screen capabilities.

- Intended: immediate crawl should start right away when a watchlist is created.
  - Implemented: API-process background task starts a subprocess best-effort.
  - Impact: good user-perceived latency when it works; no durable guarantee when the API process is interrupted.
  - Fix direction: durable dispatch record before async execution.

### Tactical Improvements (1-3 days)
1. Add ambiguous-email recovery to login.
   - Done when: a user can enter email/password first, then if the API returns an ambiguity code, the UI reveals a workspace field and retries successfully.
2. Add 3-5 Playwright scenarios for the changed UX.
   - Cover: signup duplicate-email path, login with MFA, rules page tabs by plan tier, Thai localization on a representative API error, immediate-crawl success notice.
3. Split `apps/web/src/app/(app)/rules/page.tsx` into smaller components.
   - Minimum split: `RulesTabs`, `KeywordsTab`, `ScheduleTabView`, `EntitlementsView`, and a `rules-view-model.ts` helper.
4. Improve immediate-discovery logging.
   - Log keyword, tenant_id, subprocess exit status, and a short stderr tail on failure.
5. Move signup/login normalization rules into shared API error helpers.
   - Done when: page components stop doing English-fragment parsing directly.

### Strategic Improvements (1-6 weeks)
1. Introduce structured API error codes.
   - Why now: localization and auth flows are getting richer; string matching will get more brittle with every feature.
   - Safe migration: keep `detail` for humans, add `code` for machines, and migrate pages gradually.
2. Add a server-driven capability contract for the rules screen.
   - Example: `rules_ui = { tabs: [...], can_edit_schedule: true, upgrade_cta: "..." }`.
   - Why now: plan-aware UI is already complex enough that frontend-only derivation is becoming product logic duplication.
3. Introduce a durable discovery dispatch table/outbox.
   - Why now: PR32 is the first user-triggered async action with product promises attached.
   - Safe migration: keep the same worker command payload, but write `pending` jobs to Postgres and have the scheduler/worker claim them.

### Big Architectural Changes (only if justified)
- Proposal: move from API-spawned subprocesses to a DB-backed job/outbox model for async discovery.
  - Pros:
    - durable handoff
    - retries/backoff
    - better observability
    - easier concurrency control and dedupe
  - Cons:
    - more infrastructure logic
    - requires job lifecycle schema and worker claim protocol
  - Migration plan:
    1. Add a `discovery_jobs` table with `pending/running/succeeded/failed`.
    2. On profile creation, write jobs transactionally with the profile.
    3. Keep the current subprocess path as a temporary “wake-up” mechanism if needed.
    4. Add a worker command to claim and execute pending jobs.
    5. Once stable, remove direct API subprocess spawning.
  - Why now / why not:
    - Do it soon if immediate discovery is core to customer retention or volume is increasing.
    - Do not do it immediately if current traffic is tiny and the team needs to keep shipping product-facing features this week.

### Open Questions / Assumptions
- I assume duplicate emails across tenants are a real supported scenario, because the backend explicitly handles them.
- I assume the worker and run repositories are already reasonably idempotent at the project level; otherwise duplicate immediate crawls become more serious.
- I did not run the Playwright suite in this review; the frontend testing comments are based on code search and current visible coverage.
- Pre-commit hooks pass (ruff). All 9 tests pass (2 new + 7 existing rules API tests).
