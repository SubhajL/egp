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
