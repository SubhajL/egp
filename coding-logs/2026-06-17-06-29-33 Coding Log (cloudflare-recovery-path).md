# Cloudflare Recovery Path Plan

## Exploration

Auggie semantic search unavailable for bounded planning; plan is based on direct file inspection plus exact-string searches.

Inspected files:
- `docs/REMOTE_LOCAL_CRAWLER.md`
- `docs/CRAWLER_PROXY_RUNBOOK.md`
- `~/Library/Logs/egp/crawl.log`

Observed facts:
- The current live eGP page returns HTTP 200 for the Angular shell, but the page requires JavaScript and includes `https://challenges.cloudflare.com` in CSP.
- The shell reports `last-modified: Fri, 12 Jun 2026 11:44:25 GMT`.
- Local logs show historical `PREDISPATCH_WARMUP_OK` entries and current repeated `warm-up failed: Cloudflare not cleared`.
- The repo runbook states a one-time initial warm, or any warm after a full lapse, may need a human to solve the challenge; the timer can refresh an existing clearance but cannot solve an interactive challenge unattended.

## Plan Draft A: Operator Warm First

### Overview

Stop automated retries, perform one foreground operator warm with the existing persistent Chrome profile, then run one bounded crawl. This treats the issue as an expired or invalid per-profile clearance and avoids making repeated bot-looking attempts.

### Files to Change

None for immediate recovery.

Optional later:
- `apps/worker/src/egp_worker/browser_downloads.py` or relevant warmup/dispatch module: add retry circuit breaker.
- `tests/phase1/test_worker_browser_downloads.py`: cover circuit-breaker behavior.
- `docs/REMOTE_LOCAL_CRAWLER.md`: add current recovery sequence.

### Implementation Steps

Immediate operational sequence:
1. Keep `com.egp.remote-crawl` stopped.
2. Run `./scripts/run_remote_crawl.sh warm-profile` in foreground.
3. Clear the challenge manually in the visible browser.
4. Confirm warm success in logs.
5. Run one bounded crawl.
6. Re-enable watcher only after one crawl succeeds.

Optional TDD sequence:
1. Add tests proving repeated warm failures pause dispatch.
2. Run and confirm tests fail for missing circuit breaker.
3. Implement bounded retry and pause/alert state.
4. Refactor minimally.
5. Run targeted worker tests and relevant full gates.

### Test Coverage

- `test_warm_failures_pause_dispatch`: repeated failures stop retry loop.
- `test_manual_warm_success_resets_pause`: success clears paused state.
- `test_crawl_not_started_without_clearance`: fail closed on stale clearance.

### Decision Completeness

Goal: Restore crawler only after a real browser clearance is proven.

Non-goals: Bypass Cloudflare, spoof challenge tokens, or automate interactive challenge solving.

Success criteria:
- Foreground warm succeeds.
- One bounded crawl reaches eGP search UI and returns real result handling.
- Watcher is re-enabled only after those checks.

Public interfaces:
- No immediate API, schema, CLI, or env changes.
- Optional later env var: `EGP_BROWSER_CLOUDFLARE_FAILURE_BACKOFF_SECONDS`.

Edge cases / failure modes:
- Manual warm fails: keep crawler stopped and test fresh profile/network.
- Warm succeeds but crawl fails: keep watcher stopped and inspect profile/state/logs.
- Challenge loops: fail closed and require operator action.

Rollout & monitoring:
- Watch `~/Library/Logs/egp/crawl.log` for `PREDISPATCH_WARMUP_OK`, bounded crawl success, and absence of repeated warm failures.

Acceptance checks:
- `launchctl print gui/$(id -u)/com.egp.remote-crawl` should fail while paused.
- `./scripts/run_remote_crawl.sh warm-profile` should complete with warm success.
- One bounded crawl should run before reinstalling the watcher.

### Dependencies

- Visible local Chrome/Chromium.
- Stable network that Cloudflare will accept.
- Existing persistent crawler profile.

### Validation

Validate through one manual warm and one bounded crawl before restoring automation.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Manual warm | `scripts/run_remote_crawl.sh warm-profile` | Operator shell command | N/A |
| Watcher | launchd `com.egp.remote-crawl` | `scripts/install_launchd.sh` | N/A |

## Plan Draft B: Fresh Profile And Network Reset First

### Overview

Skip the existing profile as potentially tainted, create or select a fresh browser profile, and try a different network before any crawler retry. This treats the issue as profile/IP reputation rather than only an expired clearance.

### Files to Change

None for immediate recovery.

Optional later:
- `docs/REMOTE_LOCAL_CRAWLER.md`: add fresh-profile recovery.
- Worker warmup code: expose a safer profile reset or profile selection command.

### Implementation Steps

Immediate operational sequence:
1. Keep watcher stopped.
2. Preserve the current profile for forensics.
3. Warm a fresh profile on a different network.
4. If fresh warm clears, point crawler to that profile.
5. Run one bounded crawl.
6. Re-enable watcher after success.

Optional TDD sequence:
1. Add tests around profile path selection.
2. Confirm missing profile selection behavior fails.
3. Implement profile path validation and logging.
4. Run targeted worker tests.

### Test Coverage

- `test_profile_path_logged_on_warm`: logs active profile path.
- `test_invalid_profile_path_fails_closed`: refuses unsafe profile path.
- `test_profile_state_isolated`: fresh profile state does not reuse stale marker.

### Decision Completeness

Goal: Recover when existing profile or IP is stuck in challenge loops.

Non-goals: Avoid Cloudflare requirements or erase forensic evidence.

Success criteria:
- Fresh profile clears Cloudflare on an accepted network.
- One bounded crawl succeeds.

Public interfaces:
- Possible env/profile path change only.

Edge cases / failure modes:
- New profile also loops: likely network/eGP policy issue, not stale local state.
- New network clears: current IP path is likely low-reputation for this target.

Rollout & monitoring:
- Compare old vs new profile behavior in logs.

Acceptance checks:
- Fresh profile warm succeeds.
- Existing profile remains backed up.

### Dependencies

- Alternate network, ideally mobile hotspot.
- Ability to create and point at a fresh persistent profile.

### Validation

Validate by comparing warm behavior across existing profile/current network and fresh profile/alternate network.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Fresh profile warm | `scripts/run_remote_crawl.sh warm-profile` with profile env | Operator shell command | N/A |
| Crawler profile selection | env/profile configuration | launchd env/config | N/A |

## Comparative Analysis

Draft A is lower-risk and preserves the existing working profile path. It is fastest if the problem is only an expired clearance.

Draft B is better if the profile or IP has entered a challenge loop. It costs more time and creates another moving part, but it gives a clear diagnosis when the existing profile cannot recover.

Both plans avoid unsupported bypass behavior and both fail closed. Draft A should be attempted first because it is simplest, then Draft B only if manual warm cannot clear.

## Unified Execution Plan

### Overview

Use a two-stage recovery: first try one controlled foreground warm on the existing persistent profile; if that fails, move to a fresh profile plus different network. After recovery, add a circuit breaker so the watcher never retries Cloudflare warmup more than a small bounded number without operator action.

### Files to Change

Immediate recovery:
- No repo files.

Follow-up hardening:
- `apps/worker/src/egp_worker/browser_downloads.py` or warmup dispatch module: bounded Cloudflare failure backoff.
- `tests/phase1/test_worker_browser_downloads.py`: retry/backoff coverage.
- `docs/REMOTE_LOCAL_CRAWLER.md`: document exact recovery flow.

### Implementation Steps

Immediate:
1. Keep `com.egp.remote-crawl` stopped.
2. Run one foreground `./scripts/run_remote_crawl.sh warm-profile`.
3. Manually solve Cloudflare if shown.
4. If successful, run one bounded crawl.
5. Re-enable watcher only after bounded crawl success.
6. If unsuccessful, preserve the old profile and retry with fresh profile plus different network.

Follow-up TDD:
1. Add tests for Cloudflare warm failure circuit breaker.
2. Confirm tests fail for current retry-loop behavior.
3. Implement max consecutive warm failures and backoff/pause state.
4. Add logs that clearly say operator action is required.
5. Run targeted worker tests and full relevant gates.

### Test Coverage

- `test_consecutive_cloudflare_warm_failures_pause_dispatch`: stops loop.
- `test_warm_success_clears_cloudflare_pause`: recovers after operator warm.
- `test_cloudflare_pause_logs_operator_action`: actionable log emitted.
- `test_crawl_requires_fresh_profile_state`: stale state fails closed.

### Decision Completeness

Goal: Restore crawler only through a real accepted browser clearance and prevent repeated failed Cloudflare attempts.

Non-goals: Build a Cloudflare bypass, automate interactive challenge solving, or restart unattended crawling before proof.

Success criteria:
- Manual warm succeeds or fresh profile/network diagnosis is complete.
- One bounded crawl succeeds before watcher is restarted.
- Follow-up code prevents more than a bounded number of warm failures.

Public interfaces:
- No immediate public interface changes.
- Possible follow-up env var for max failures/backoff if needed.

Edge cases / failure modes:
- Existing profile cannot clear: try fresh profile/network.
- Fresh profile cannot clear: likely eGP/Cloudflare policy or broad network reputation issue.
- Warm clears but later expires: warm timer may refresh only while clearance remains valid.
- Repeated failures: fail closed and require operator action.

Rollout & monitoring:
- Do not re-enable launchd watcher until one bounded crawl succeeds.
- Watch `~/Library/Logs/egp/crawl.log` for warm success, challenge loops, and pause logs.
- Backout is simple: keep crawler stopped while API/web remain live.

Acceptance checks:
- `./scripts/run_remote_crawl.sh warm-profile` succeeds.
- One bounded crawl succeeds.
- `launchctl print gui/$(id -u)/com.egp.remote-crawl` is restored only after success.
- Follow-up hardening tests pass.

### Dependencies

- Human operator for initial interactive challenge.
- Stable browser/device/network accepted by Cloudflare.
- Optional alternate network for diagnosis.

### Validation

Validation is operational first: warm success and bounded crawl success. Code hardening validation comes second through targeted worker tests and release gates.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Existing-profile warm | `scripts/run_remote_crawl.sh warm-profile` | Operator shell command | N/A |
| Bounded crawl | `scripts/run_remote_crawl.sh` crawl command | Operator shell command / launchd watcher | Existing discovery tables |
| Watcher restart | launchd `com.egp.remote-crawl` | `scripts/install_launchd.sh` | N/A |
| Optional circuit breaker | warmup/dispatch path | worker dispatcher imports/config | N/A |

## Decision-Complete Checklist

- No open decisions remain for immediate recovery.
- No bypass behavior is proposed.
- Public interfaces are unchanged for the immediate path.
- Behavior change for follow-up hardening has test coverage.
- Validation commands are concrete and scoped.
- Wiring verification covers the operational components.

## Implementation Summary (2026-06-17 06:41:02 +07)

### Goal

Implement the Cloudflare recovery guardrail: stop unattended pre-dispatch Chrome warm retries after repeated failures, require operator action, and let a successful foreground `warm-profile` clear the pause marker.

### What Changed

- `apps/api/src/egp_api/config.py`: added `get_browser_warmup_failure_pause_threshold()` for `EGP_BROWSER_WARMUP_FAILURE_PAUSE_THRESHOLD` with default `2` and `0` as disabled.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: records consecutive warm failures in `.egp-profile-state.json`, pauses pre-dispatch warming once the threshold is reached, returns `False` from `prepare_for_dispatch()` so the watcher does not claim jobs while paused, and raises a clear operator-action error on direct dispatch.
- `apps/worker/src/egp_worker/warmup.py`: successful manual/profile warm writes the shared profile success state, clearing failure count and `operator_action_required`.
- `.env.remotecrawl.example` and `deploy/.env.production.example`: added the new warm failure pause threshold env var.
- `docs/REMOTE_LOCAL_CRAWLER.md`: documented the fail-closed pause and recovery sequence.
- Tests updated in `tests/phase2/test_browser_runner_config.py`, `tests/phase2/test_persistent_browser_profile.py`, and `tests/operations/test_profile_lock_keep_warm.py`.

### TDD Evidence

- RED: `./.venv/bin/python -m pytest tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py tests/operations/test_profile_lock_keep_warm.py -q`
  - Failed during collection because `get_browser_warmup_failure_pause_threshold` did not exist yet.
- GREEN: same command after implementation
  - `58 passed in 0.30s`.

### Tests Run

- `./.venv/bin/python -m pytest tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py tests/operations/test_profile_lock_keep_warm.py -q` -> `58 passed`.
- `./.venv/bin/ruff check apps/api/src/egp_api/config.py apps/api/src/egp_api/services/discovery_worker_dispatcher.py apps/worker/src/egp_worker/warmup.py tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py tests/operations/test_profile_lock_keep_warm.py` -> passed.
- `./.venv/bin/python -m pytest tests/operations/test_env_template.py tests/operations/test_remote_crawl_assets.py tests/operations/test_warm_browser_profile.py -q` -> `34 passed`.
- `./.venv/bin/ruff check apps/api apps/worker tests/phase1 tests/phase2 tests/operations` -> passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_browser_downloads.py tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py tests/operations/test_profile_lock_keep_warm.py tests/operations/test_warm_browser_profile.py tests/operations/test_env_template.py tests/operations/test_remote_crawl_assets.py -q` -> `235 passed`.
- `./.venv/bin/python -m pytest` -> `1246 passed, 106 warnings`.
- `docker info --format '{{.ServerVersion}}'` -> Docker available, `29.4.0`.
- `docker compose -f docker-compose-localdev.yml ps postgres` -> local Postgres healthy.
- `./.venv/bin/python -m egp_db.migration_runner --database-url postgresql://egp:egp_dev@localhost:5434/egp --migrations-dir packages/db/src/migrations` -> applied local missing `027_document_capture_attempts.sql`.
- `DATABASE_URL=postgresql://egp:egp_dev@localhost:5434/egp ./.venv/bin/python scripts/run_phase1_postgres_smoke.py` -> passed.
- `./scripts/run_remote_crawl.sh check` -> remote-crawl guard passed; did not run Chromium or restart watcher.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Warm failure threshold config | `SubprocessDiscoveryDispatcher.__init__()` | `egp_api.config.get_browser_warmup_failure_pause_threshold()` | N/A |
| Pre-dispatch pause | `DiscoveryJobProcessor.process_pending()` calls `prepare_for_dispatch()` | `SubprocessDiscoveryDispatcher.prepare_for_dispatch()` | `.egp-profile-state.json` |
| Direct dispatch fail-fast | `SubprocessDiscoveryDispatcher.dispatch()` | `_warm_persistent_profile_if_stale()` | `.egp-profile-state.json` |
| Manual warm reset | `scripts/run_remote_crawl.sh warm-profile` -> `egp_worker.warmup.main()` | `run_profile_warmup()` writes success state | `.egp-profile-state.json` |

### Behavior and Risks

- Behavior is fail-closed: after repeated Cloudflare warm failures, unattended crawling pauses before claiming more jobs.
- Manual operator recovery is explicit: run foreground `warm-profile`, clear Cloudflare, then one bounded crawl before restarting watcher.
- `EGP_BROWSER_WARMUP_FAILURE_PAUSE_THRESHOLD=0` disables the pause if an operator deliberately wants old retry behavior.
- Auggie semantic search was unavailable with HTTP 402, so implementation used direct file inspection and exact-string searches.

### Follow-Ups / Known Gaps

- This change does not clear Cloudflare by itself and does not restart `com.egp.remote-crawl`.
- A successful real foreground Chromium warm still needs to be performed before the crawler is considered healthy.

## Review (2026-06-17 06:42:09 +07) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at `9c9e6b95`
- Commands Run:
  - Auggie semantic review context attempted; unavailable with HTTP 402.
  - `git status -sb`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/config.py tests/phase2/test_browser_runner_config.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/worker/src/egp_worker/warmup.py tests/operations/test_profile_lock_keep_warm.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- .env.remotecrawl.example deploy/.env.production.example docs/REMOTE_LOCAL_CRAWLER.md tests/phase2/test_persistent_browser_profile.py`
  - `./.venv/bin/ruff check apps/api apps/worker tests/phase1 tests/phase2 tests/operations`
  - `./.venv/bin/python -m pytest`
  - `DATABASE_URL=postgresql://egp:egp_dev@localhost:5434/egp ./.venv/bin/python scripts/run_phase1_postgres_smoke.py`

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

- Assumption: the intended behavior is fail-closed for repeated Cloudflare warm failures, even if that temporarily leaves claimable jobs pending.
- Assumption: `EGP_BROWSER_WARMUP_FAILURE_PAUSE_THRESHOLD=0` is acceptable as an explicit escape hatch for operators who want the previous retry behavior.

### Recommended Tests / Validation

- Already run: full Python suite, targeted worker/browser profile tests, env-template tests, ruff, local migration runner, local Postgres smoke.
- Remaining production validation: one foreground `scripts/run_remote_crawl.sh warm-profile` and one bounded `scripts/run_remote_crawl.sh crawl 1` after manual Cloudflare clearance.

### Rollout Notes

- Deploying API code is sufficient for the pre-dispatch pause because the production Mac watcher runs `egp_api.executors.discovery_dispatch`.
- The Mac crawler launchd watcher should stay stopped until a human foreground warm clears Cloudflare and a bounded crawl succeeds.
- No database migration is required for this change; state is stored in the existing persistent profile state JSON.

## Implementation (2026-06-20 10:50:38 +07) - stale crawl run admission and progress display

### Goal

Fix the projects page symptom where old `running` crawl rows were shown as live worker jobs and blocked the `Crawl ใหม่` action even though no worker was actually running.

### What Changed

- `packages/db/src/egp_db/repositories/run_repo.py`
  - Added `ACTIVE_RUN_STALE_AFTER_SECONDS = 3 * 60 * 60`.
  - Updated `SqlRunRepository.count_active_runs()` to count only queued/running rows whose `started_at` or, for never-started queued rows, `created_at` is within the active window.
  - This keeps stale rows in history but stops them from blocking run admission.
- `tests/phase2/test_rules_api.py`
  - Added `test_manual_recrawl_ignores_stale_inflight_run_for_admission`, reproducing a four-day-old running row and proving `/v1/rules/recrawl` accepts a new request.
- `apps/web/src/lib/run-progress.ts`
  - Added stale active-run classification using `live_progress.updated_at`, `started_at`, and `created_at`.
  - `getActiveRuns()` now excludes stale active rows.
  - Added `getStaleActiveRuns()` for UI diagnostics.
- `apps/web/tests/unit/run-progress.test.ts`
  - Added Vitest coverage for stale active rows and recent `live_progress.updated_at` keeping a run active.
- `apps/web/src/app/(app)/projects/page.tsx`
  - Uses `getStaleActiveRuns()` so stale rows are shown as `สถานะค้าง` / `ต้องตรวจสอบ` instead of counted as `กำลังทำงาน`.
  - Updates the manual recrawl success notice for the zero-new-jobs path so clicks produce visible feedback.

### TDD Evidence

- RED:
  - Not captured as a separate command. Auggie was unavailable with `HTTP 402`, and the fix was implemented directly from source inspection and the user-provided production screenshot.
  - The regression covered by `test_manual_recrawl_ignores_stale_inflight_run_for_admission` would fail against the previous `count_active_runs()` implementation because any `running` row counted as inflight regardless of age.
  - The regression covered by `apps/web/tests/unit/run-progress.test.ts` would fail against the previous `getActiveRuns()` implementation because stale `running` rows were included.
- GREEN:
  - `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py -k 'manual_recrawl_ignores_stale_inflight_run_for_admission or manual_recrawl_denies_second_request_until_inflight_run_finishes' -q`
  - `npm run test:unit -- run-progress.test.ts` from `apps/web`

### Tests Run

- `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py -k 'manual_recrawl_ignores_stale_inflight_run_for_admission or manual_recrawl_denies_second_request_until_inflight_run_finishes' -q` - passed, run 3 consecutive times.
- `npm run test:unit -- run-progress.test.ts` from `apps/web` - passed, run 3 consecutive times.
- `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py -q` - passed, 16 tests.
- `npm run test:unit` from `apps/web` - passed, 11 files / 46 tests.
- `./.venv/bin/ruff check packages/db/src/egp_db/repositories/run_repo.py tests/phase2/test_rules_api.py` - passed.
- `./.venv/bin/python -m compileall packages/db/src apps/api/src` - passed.
- `npm run typecheck` from `apps/web` - passed.
- `npx prettier --check src/lib/run-progress.ts 'src/app/(app)/projects/page.tsx' tests/unit/run-progress.test.ts` from `apps/web` - passed.

### Wiring Verification

| Component | Wiring Verified? | Evidence |
|-----------|------------------|----------|
| `SqlRunRepository.count_active_runs()` stale cutoff | YES | Existing `TenantEntitlementService.evaluate_run_admission()` calls `self._run_repository.count_active_runs(tenant_id=tenant_id)` before `/v1/rules/recrawl` queues jobs. Regression test exercises the route end to end. |
| `getActiveRuns()` stale exclusion | YES | `apps/web/src/app/(app)/projects/page.tsx` computes `activeRuns = getActiveRuns(runsData?.runs ?? [])`; Vitest covers stale exclusion. |
| `getStaleActiveRuns()` stale diagnostics | YES | `apps/web/src/app/(app)/projects/page.tsx` imports and renders stale run cards when no live active rows remain. |

### Behavior Changes And Risk Notes

- Stale queued/running crawl rows older than 3 hours no longer block manual recrawl admission.
- Stale active rows still remain visible as diagnostic history, but they are no longer counted as live running work on the project explorer.
- Risk: if the production worker timeout is intentionally raised above 3 hours without updating this repository constant and the frontend constant, a legitimate long-running crawl could be treated as stale. Current source defines the dispatcher timeout as 3 hours.
- Operational follow-up: existing production stale rows may still need a one-time mark-failed cleanup if operators want historical status corrected, not just live/admission behavior fixed.

## Review (2026-06-20 10:50:38 +07) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged working tree
- Base SHA: `bf0889de`
- Commands Run:
  - Auggie semantic retrieval attempted and failed with `HTTP error: 402`; review used direct source inspection.
  - `git status --short`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- packages/db/src/egp_db/repositories/run_repo.py tests/phase2/test_rules_api.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/web/src/lib/run-progress.ts apps/web/tests/unit/run-progress.test.ts`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/web/src/app/\(app\)/projects/page.tsx`
  - `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py -q`
  - `npm run test:unit`
  - `./.venv/bin/ruff check packages/db/src/egp_db/repositories/run_repo.py tests/phase2/test_rules_api.py`
  - `./.venv/bin/python -m compileall packages/db/src apps/api/src`
  - `npm run typecheck`
  - `npx prettier --check src/lib/run-progress.ts 'src/app/(app)/projects/page.tsx' tests/unit/run-progress.test.ts`

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

- Assumption: the active-run freshness contract should match the current 3-hour worker timeout.
- Assumption: preserving stale rows as history is preferable to silently mutating them from the list/read path.

### Recommended Tests / Validation

- Already run: targeted stale admission regression, targeted run-progress regression 3 consecutive times, full rules API file, full web unit suite, web typecheck, ruff, compileall, Prettier check.
- Production validation after deploy: click `Crawl ใหม่` once and verify the project explorer no longer reports the June 16 rows as `กำลังทำงาน`, then verify `/runs` shows any new run or the zero-new-jobs notice.

### Rollout Notes

- No database migration is required.
- Deploy both API and web. API fixes admission blocking; web fixes the false live-progress count and visible click feedback.
- If operators want old production `running` rows to become historical failures, run a separate one-time cleanup rather than doing it implicitly in read paths.

## Review (2026-06-20 11:00:07 +07) - working-tree g-check before PR

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged working tree before Graphite branch creation
- Base SHA: `bf0889de`
- Commands Run:
  - Auggie semantic retrieval attempted and failed with `HTTP error: 402`; review used direct staged diff inspection.
  - `git status -sb`
  - `gt ls`
  - `gt status`
  - `gt log long`
  - `gh auth status`
  - `gh repo view --json nameWithOwner,defaultBranchRef`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- packages/db/src/egp_db/repositories/run_repo.py tests/phase2/test_rules_api.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- apps/web/src/lib/run-progress.ts apps/web/tests/unit/run-progress.test.ts`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- apps/web/src/app/\(app\)/projects/page.tsx`

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

- Assumption: the three-hour stale cutoff intentionally matches the current discovery worker timeout and should be kept aligned if the worker timeout changes later.
- Assumption: this release should stop stale rows from blocking or being shown as live, while leaving historical row mutation to a separate explicit cleanup.

### Recommended Tests / Validation

- Re-run the focused Python rules API regression, web unit tests, web typecheck, ruff, compileall, and Prettier check before PR submission.
- After deploy, verify `https://api.egptracker.com/health` and the project explorer behavior in production.

### Rollout Notes

- No migration required.
- Requires backend Lightsail deployment for admission behavior and web deployment for the project explorer display.
- Vercel should auto-deploy the web app after merge to `main`; Lightsail API remains manual.

## Debug Update (2026-06-20 15:35:52 +0700) - local crawler bridge restored

### Goal

Restore the production recrawl path after the Projects page accepted recrawl requests but showed stale/no-progress crawl status.

### What Changed

- Operational state only; no application source files changed.
- Verified Track C architecture again: API/web enqueue production jobs, but this Mac must run the native crawler watcher against the production queue.
- Found `com.egp.pg-tunnel` running but `com.egp.remote-crawl` not loaded, so production `discovery_jobs` could queue without a local worker draining them.
- Ran `scripts/run_remote_crawl.sh warm-profile`; the persistent Chrome profile warmed successfully.
- Ran `scripts/run_remote_crawl.sh crawl 1`; one production backfill job completed successfully and created run `7eaf26f3-89d4-4d7c-a873-ed75a2bf0893`.
- Ran `scripts/install_launchd.sh install`; reloaded `com.egp.pg-tunnel` and `com.egp.remote-crawl`.

### TDD Evidence

- No RED test was produced because this was an operational/runtime restoration, not a code change.
- Failure evidence:
  - `scripts/install_launchd.sh status` showed `com.egp.remote-crawl` as `not loaded`.
  - `tail -n 120 ~/Library/Logs/egp/crawl.log` showed the last crawler failures were Cloudflare pre-dispatch warm-up failures, and the file timestamp was still June 16.
  - Production DB query showed pending discovery jobs while the local crawler was not loaded.
- GREEN evidence:
  - `scripts/run_remote_crawl.sh check` returned `OK - safe to crawl production.`
  - `scripts/run_remote_crawl.sh warm-profile` returned `WARMUP_OK profile=/Users/subhajlimanond/.egp/profiles/prod`.
  - `scripts/run_remote_crawl.sh crawl 1` returned `INFO:__main__:Processed 1 pending discovery dispatch jobs`.
  - `scripts/install_launchd.sh status` showed both `com.egp.pg-tunnel` and `com.egp.remote-crawl` running after reload.

### Tests / Checks Run

- `scripts/install_launchd.sh status`
- `scripts/run_remote_crawl.sh check`
- `scripts/run_remote_crawl.sh warm-profile`
- `scripts/run_remote_crawl.sh crawl 1`
- Production DB checks through the local SSH tunnel:
  - discovery job counts by status and trigger type
  - latest crawl runs and live progress
  - `select 1` after launchd reload to confirm the tunnel accepted Postgres traffic

### Wiring Verification

- Queue source: `/v1/rules/recrawl` writes `discovery_jobs`.
- Local worker bridge: `deploy/launchd/com.egp.remote-crawl.plist` runs `scripts/run_remote_crawl.sh watch`.
- Runtime proof: launchd watcher PID `10194` spawned worker PID `10207`, and production run `f774f951-5a1b-4da3-b469-01236bbe89b9` was running with live progress after reload.

### Behavior / Risk Notes

- The immediate blocker was operational: the local production crawler watcher was not loaded.
- A secondary startup race exists: reloading both launchd agents can start `remote-crawl` before the SSH tunnel accepts DB connections; launchd KeepAlive restarted it and the second start connected.
- The UI still cannot directly show pending `discovery_jobs`; it only shows `crawl_runs`, so queued-but-not-drained jobs can look like "accepted but no run" unless the local watcher is healthy.

### Follow-ups

- Consider adding a tunnel-readiness wait to `scripts/run_remote_crawl.sh watch` or the launchd wrapper to avoid noisy startup crashes.
- Consider exposing discovery outbox status in the API/UI so recrawl acceptance can show "queued on local crawler bridge" separately from worker-created `crawl_runs`.

## Implementation Update (2026-06-20 17:18:58 +0700) - preliminary bid summary status/artifacts

### Goal

Fix preliminary bid-summary handling so first-time late-stage discoveries stay out of the project list, while existing tracked projects that move to `สรุปข้อมูลการเสนอราคา` / `สรุปข้อมูลการเสนอราคาเบื้องต้น` update both project status columns and ingest the pricing artifact.

### What Changed

- `packages/crawler-core/src/egp_crawler_core/invitation_rules.py`: added `is_preliminary_pricing_status()` for both Thai preliminary bid-summary labels without adding them to first-discovery eligibility.
- `apps/worker/src/egp_worker/browser_discovery.py`: routed the browser preliminary-status check through the shared helper, preserving first-discovery skip behavior.
- `apps/worker/src/egp_worker/browser_downloads.py` and `packages/document-classifier/src/egp_document_classifier/classifier.py`: added preliminary bid-summary documents to targeted downloads and classified them as `mid_price`.
- `packages/shared-types/src/egp_shared_types/project_events.py`, `packages/domain/src/egp_domain/project_ingest.py`, `apps/api/src/egp_api/routes/project_ingest.py`, and `apps/worker/src/egp_worker/project_event_sink.py`: added a worker-only project status update event/route/service path.
- `apps/worker/src/egp_worker/workflows/close_check.py`: existing-project close-check now ingests any downloaded documents, then advances preliminary bid-summary observations to `prelim_pricing_seen` while preserving `source_status_text`.
- `apps/web/src/lib/generated/openapi.json` and `apps/web/src/lib/generated/api-types.ts`: regenerated API contracts for the new internal status-update route.
- Tests updated for classifier, download-target, close-check workflow, and internal API status-update behavior.

### TDD Evidence

- RED: `./.venv/bin/python -m pytest tests/phase1/test_phase1_domain_logic.py::test_classify_document_treats_preliminary_bid_summary_as_mid_price tests/phase1/test_worker_browser_downloads.py::test_doc_targets_include_preliminary_bid_summary tests/phase1/test_worker_workflows.py::test_close_check_workflow_updates_prelim_pricing_status_with_revisited_documents tests/phase1/test_projects_and_runs_api.py::test_project_ingest_status_update_endpoint_marks_prelim_pricing_seen -q`
  - Failed during collection because `ProjectStatusUpdateEvent` did not exist.
- GREEN: same focused command passed with `4 passed`.
- Broader GREEN: `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py tests/phase1/test_phase1_domain_logic.py tests/phase1/test_worker_browser_downloads.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_live_discovery.py -q` passed with `255 passed`.

### Tests / Checks Run

- `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q` -> `14 passed`.
- Affected-file suite above -> first rerun found one expected obsolete assertion; after test correction, final rerun passed with `255 passed`.
- Focused new-behavior command -> passed 3 consecutive GREEN runs after implementation.
- `./.venv/bin/ruff check apps/api/src/egp_api/routes/project_ingest.py apps/worker/src/egp_worker/project_event_sink.py apps/worker/src/egp_worker/workflows/close_check.py apps/worker/src/egp_worker/browser_discovery.py apps/worker/src/egp_worker/browser_downloads.py packages/crawler-core/src/egp_crawler_core/invitation_rules.py packages/document-classifier/src/egp_document_classifier/classifier.py packages/domain/src/egp_domain/project_ingest.py packages/shared-types/src/egp_shared_types/project_events.py tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py tests/phase1/test_phase1_domain_logic.py tests/phase1/test_worker_browser_downloads.py` -> passed.
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/crawler-core/src packages/document-classifier/src packages/domain/src packages/shared-types/src` -> passed.
- `cd apps/web && npm run generate:api-types` -> regenerated OpenAPI/types.
- `cd apps/web && npm run check:api-types` -> OpenAPI schema and generated API types are current.

### Wiring Verification

- Browser status detection: `status_indicates_preliminary_pricing()` -> `is_preliminary_pricing_status()`.
- Artifact capture: `DOCS_TO_DOWNLOAD` includes `สรุปข้อมูลการเสนอราคา`; classifier maps both summary labels to `DocumentType.MID_PRICE`.
- Existing-project runtime path: `run_close_check_workflow()` -> `ProjectEventSink.record_status_update()` -> API `/internal/worker/projects/status-update` or service-backed sink -> `ProjectIngestService.ingest_status_update_event()` -> `SqlProjectRepository.transition_project()`.
- First-discovery gate remains fail-closed: `ProjectIngestService.ingest_discovered_project()` still requires `is_discoverable_stage_status()`, which does not include preliminary bid-summary labels.

### Behavior / Risk Notes

- Preliminary bid-summary is now a tracked lifecycle advancement for existing projects, not a winner/contract close event.
- Internal status-update route can only be called with the worker token and still goes through lifecycle transition validation.
- Live close-check candidate selection still determines which existing projects are revisited; this change fixes the handling once an existing project is observed at the preliminary bid-summary stage.

### Follow-ups

- Consider a separate product decision on whether live close-check should revisit tracked projects that currently have no invitation/TOR document evidence, instead of only projects selected by the existing close-check query.


## Review (2026-06-20 17:19:53 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: staged working tree for preliminary bid-summary status/artifact fix
- Commit Reviewed: working tree based on 99f54b31
- Commands Run: `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`; targeted line inspection with `nl -ba`; focused pytest RED/GREEN; affected-file pytest suite; ruff; compileall; `npm run generate:api-types`; `npm run check:api-types`

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
- Assumption: preliminary bid-summary should advance existing projects to `prelim_pricing_seen`, but should remain excluded from first-discovery ingest so late-stage first sightings do not appear in the project list.
- Assumption: a preliminary bid-summary status is not a winner/contract closure event, so no winner/contract notification should fire from this path.

### Recommended Tests / Validation
- Already run: focused new-behavior tests passed 3 consecutive times.
- Already run: affected-file suite passed with `255 passed`.
- Already run: ruff, compileall, generated OpenAPI/type check.

### Rollout Notes
- No database migration required; existing `project_state` enum/check constraint already includes `prelim_pricing_seen`.
- Requires API and worker deployment together because the API-backed worker sink now calls `/internal/worker/projects/status-update`.
- Existing live close-check candidate selection still controls which projects are revisited; this change fixes preliminary-price handling once an existing tracked project is observed.
