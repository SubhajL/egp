# Launchd Warm Profile Opt-In

## Investigation

User reported that egptracker web appears to call the local crawler every 15-20 minutes.

Auggie semantic search was unavailable with HTTP 402, so investigation used local code and runtime evidence.

Runtime evidence:
- `launchctl list` showed `com.egp.pg-warm`, `com.egp.remote-crawl`, and `com.egp.pg-tunnel` installed.
- `launchctl print gui/$(id -u)/com.egp.pg-warm` showed `run interval = 900 seconds`, `runs = 51`, and command `scripts/run_remote_crawl.sh warm-profile`.
- `~/Library/Logs/egp/warm.log` showed repeated `WARMUP_START` / `WARMUP_OK` entries.

Conclusion:
- The 15-minute activity is not caused by the web app. It is the launchd profile warmer (`com.egp.pg-warm`) installed by `scripts/install_launchd.sh install`.
- Immediate local fix applied: unloaded `com.egp.pg-warm` and removed `~/Library/LaunchAgents/com.egp.pg-warm.plist`.

## Plan

Make the keep-warm timer opt-in so future installs do not silently restore the every-15-minute browser warm-up.

Files:
- `scripts/install_launchd.sh`: default labels become tunnel + watcher only; add `install --with-warm` for the optional keep-warm timer.
- `docs/REMOTE_LOCAL_CRAWLER.md`: clarify the default install behavior and the explicit opt-in.
- `tests/operations/test_remote_crawl_assets.py`: static tests for the new contract.

Validation:
- `./.venv/bin/python -m pytest tests/operations/test_remote_crawl_assets.py -q`
- `./.venv/bin/ruff check tests/operations/test_remote_crawl_assets.py`

## Implementation Summary (2026-06-08 06:18 +07)

### What Changed

- `scripts/install_launchd.sh`: default `install` now installs only `com.egp.pg-tunnel` and `com.egp.remote-crawl`; `com.egp.pg-warm` is installed only with `install --with-warm`. `status` and `uninstall` still inspect/remove all three labels so an existing warm timer is not stranded.
- `docs/REMOTE_LOCAL_CRAWLER.md`: updated launchd instructions to say the 15-minute keep-warm timer is optional and must be explicitly requested.
- `tests/operations/test_remote_crawl_assets.py`: added a regression asserting the warm-profile timer is opt-in.

### TDD Evidence

RED:

`./.venv/bin/python -m pytest tests/operations/test_remote_crawl_assets.py -q -k warm_profile_timer_opt_in`

Result: failed because the installer still used the all-agent default label list.

GREEN:

`./.venv/bin/python -m pytest tests/operations/test_remote_crawl_assets.py -q`

Result: 11 passed.

### Validation

- `bash -n scripts/install_launchd.sh scripts/run_remote_crawl.sh` -> passed.
- `./.venv/bin/python -m pytest tests/operations/test_remote_crawl_assets.py -q` -> 11 passed.
- `./.venv/bin/ruff check tests/operations/test_remote_crawl_assets.py` -> passed.
- `scripts/install_launchd.sh status` -> `com.egp.pg-warm` not loaded; `com.egp.pg-tunnel` and `com.egp.remote-crawl` still running.

### Operational Action Taken

Stopped the currently installed 15-minute timer:

`launchctl bootout "gui/$(id -u)/com.egp.pg-warm" 2>/dev/null || true; rm -f "$HOME/Library/LaunchAgents/com.egp.pg-warm.plist"`

### Risk Notes

- With the warm timer disabled, the crawler profile may go cold between manual/scheduled crawls. A future crawl may need `scripts/run_remote_crawl.sh warm-profile` manually if Cloudflare clearance expires.
- Manual/queued crawling is still available because `com.egp.remote-crawl` remains running.

## Implementation Summary (2026-06-08 06:35:02 +07)

### Goal

Replace surprise interval-based Chrome warming with on-demand stale-profile warm/preflight before dispatching queued discovery jobs.

### What Changed

- `apps/api/src/egp_api/services/discovery_dispatch.py`: added a pre-dispatch preparer hook and a claimable-job probe before claim, so idle watcher polls do not warm Chrome.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: added `has_claimable_discovery_jobs()` using the same pending/due/stale filters as the claim path.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: added persistent-profile freshness state (`.egp-profile-state.json`), stale checking, locked `prepare_for_dispatch()`, and success timestamp updates after warm/crawl.
- `apps/worker/src/egp_worker/warmup.py`: extracted reusable `run_profile_warmup()` and browser-payload settings conversion for in-process pre-dispatch warm/preflight.
- `apps/api/src/egp_api/executors/discovery_dispatch.py`, `apps/api/src/egp_api/bootstrap/services.py`, and `apps/api/src/egp_api/main.py`: wired the dispatcher as the pre-dispatch preparer in standalone and embedded runtime paths.
- `.env.remotecrawl.example`, `docs/REMOTE_LOCAL_CRAWLER.md`, `TRACKS.md`, and launchd plist comments: documented on-demand stale warm as the default, with the 15-minute timer remaining opt-in.

### TDD Evidence

RED:

`./.venv/bin/python -m pytest tests/phase2/test_persistent_browser_profile.py -q`

Result: 3 failed because `egp_worker.warmup` did not yet expose `run_profile_warmup()` for dispatcher reuse.

GREEN:

`./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/concurrency/test_fair_claim.py tests/phase2/test_persistent_browser_profile.py tests/phase2/test_browser_runner_config.py tests/operations/test_profile_lock_keep_warm.py tests/operations/test_warm_browser_profile.py tests/operations/test_remote_crawl_assets.py apps/api/tests/test_dispatch_trigger_metadata.py -q`

Result: 84 passed.

### Validation

- `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/concurrency/test_fair_claim.py tests/phase2/test_persistent_browser_profile.py tests/phase2/test_browser_runner_config.py tests/operations/test_profile_lock_keep_warm.py tests/operations/test_warm_browser_profile.py tests/operations/test_remote_crawl_assets.py apps/api/tests/test_dispatch_trigger_metadata.py -q` -> 84 passed.
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase2/test_discovery_dispatch.py tests/concurrency/test_fair_claim.py tests/phase2/test_persistent_browser_profile.py tests/phase2/test_browser_runner_config.py tests/operations/test_profile_lock_keep_warm.py tests/operations/test_warm_browser_profile.py tests/operations/test_remote_crawl_assets.py apps/api/tests/test_dispatch_trigger_metadata.py` -> passed.
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages` -> passed.

### Wiring Verification

- Standalone watcher path: `build_discovery_dispatch_runtime()` passes the `SubprocessDiscoveryDispatcher` as both dispatcher and `pre_dispatch_preparer`.
- Embedded API path: `configure_services()` passes `_AppStateDiscoveryDispatcher` as the preparer; `_AppStateDiscoveryDispatcher.prepare_for_dispatch()` delegates to `app.state.discover_spawner.prepare_for_dispatch()`.
- Runtime ordering is `has_claimable_discovery_jobs()` -> `prepare_for_dispatch()` -> `claim_pending_discovery_jobs()` -> worker dispatch; if the profile lock is busy, the preparer returns `False` and the processor leaves the job unclaimed for a later poll.
- Persistent-profile lock is still the same shared `.egp-crawl.lock`; pre-dispatch warm uses it before claim, and direct dispatch keeps a stale check while holding the lock as a fallback.

### Behavior Changes And Risk Notes

- Default Track C installs no longer need interval warm activity for normal queued crawls; a stale profile is warmed only when a claimable job exists.
- A successful warm or crawl writes `<profile>/.egp-profile-state.json`; invalid/missing state is treated as stale.
- If Cloudflare requires manual interaction, the first stale job can still be delayed or retried; the manual `scripts/run_remote_crawl.sh warm-profile` operator command remains available.
- Multiple remote watchers could both observe a claimable job and race into pre-warm, but the shared profile lock defers the losing preparer before claim. Track C still requires one crawler via `EGP_DISCOVERY_WORKER_COUNT=1`.

## Review (2026-06-08 06:37:12 +07) - working-tree intended slice

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree intended on-demand pre-dispatch warm slice
- Commit reviewed: working tree on `aeabe47e`
- Commands Run: Auggie codebase retrieval (failed with HTTP 402); `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- ...`; line-numbered `nl -ba ... | sed -n ...`; `./.venv/bin/python -m pytest tests/phase2/test_discovery_dispatch.py tests/concurrency/test_fair_claim.py tests/phase2/test_persistent_browser_profile.py tests/phase2/test_browser_runner_config.py tests/operations/test_profile_lock_keep_warm.py tests/operations/test_warm_browser_profile.py tests/operations/test_remote_crawl_assets.py apps/api/tests/test_dispatch_trigger_metadata.py -q`; `./.venv/bin/ruff check apps/api apps/worker packages tests/phase2/test_discovery_dispatch.py tests/concurrency/test_fair_claim.py tests/phase2/test_persistent_browser_profile.py tests/phase2/test_browser_runner_config.py tests/operations/test_profile_lock_keep_warm.py tests/operations/test_warm_browser_profile.py tests/operations/test_remote_crawl_assets.py apps/api/tests/test_dispatch_trigger_metadata.py`; `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages`

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

- Assumes Track C remains single-crawler operationally (`EGP_DISCOVERY_WORKER_COUNT=1`) and that multiple host-level watcher processes are accidental rather than expected capacity.
- Assumes `.egp-profile-state.json` may live inside the persistent profile directory because it is local operational state and protected by the same profile lock during writes from this path.

### Recommended Tests / Validation

- Already run: focused pytest set covering pre-claim preparation ordering, no prepare while idle, lock-busy deferral, stale/recent profile state, reusable warmup, ops assets, trigger metadata, and fair claim behavior (`84 passed`).
- Already run: `ruff check` over touched API/worker/package/test areas.
- Already run: `compileall` over API, worker, and packages.
- Optional live validation: enqueue one production-safe test discovery job with a stale profile state and confirm logs show `PREDISPATCH_WARMUP_START` before claim/worker dispatch; then enqueue a second job and confirm warm is skipped.

### Rollout Notes

- The 15-minute launchd timer is now opt-in; default freshness comes from `EGP_BROWSER_WARMUP_STALE_AFTER_SECONDS=1800` and `EGP_BROWSER_PREDISPATCH_WARM_SECONDS=0`.
- If the profile lock is busy, the processor leaves the job unclaimed for a later poll instead of failing the job.
- A cold profile that requires manual Cloudflare interaction can still delay the first stale job; `scripts/run_remote_crawl.sh warm-profile` remains the manual operator path.
