# Coding Log: Environment Parity

Started: 2026-08-13 15:14:30 +0700  
Branch: `fix/environment-parity`  
Baseline: `8b4a6476517519bb580cbf774af1de519c3bdbec`  
DREP: `coding-logs/2026-08-13-15-14-30 DREP (environment-parity).md`

## Planning and discovery

- Preflight proved local `main == origin/main == 8b4a6476517519bb580cbf774af1de519c3bdbec` and preserved all primary-checkout dirty artifacts.
- Session worktree: `/Users/subhajlimanond/dev/egp-g2-env-parity`, created clean from `origin/main`; intended disposition is removal after merged exact-SHA landing.
- RepoPrompt bound to the exact worktree after one focused context build against the equivalent baseline in the primary root. Direct focused reads revalidated the three planned files.
- Read-only Terra support independently confirmed the exact baseline: `tests/operations/test_env_template.py` had 2 failures and 13 passes. The missing inputs are `EGP_RELEASE_SHA` and `EGP_BROWSER_DIAGNOSTICS_DIR`; Compose separately lacks the diagnostics relay.
- Decision: both variables are genuine optional runtime inputs with blank defaults. This PR declares and relays them without choosing a diagnostics path, mount, retention policy, or SHA derivation.
- Delegation: PRIMARY. No DeepSeek handoff or external repository egress; small sequential configuration slice.

## Baseline protection

- Worktree baseline status: clean.
- Primary checkout remains out of scope and dirty with pre-existing logs, docs, and `test.sqlite3`.
- F6 is already landed at the baseline SHA and is not recreated or modified.

## TDD slice: optional runtime environment parity

- Test files: `tests/operations/test_env_template.py`.
- Initial command using worktree-local `./.venv/bin/python` failed before collection because clean helper worktrees do not contain the ignored virtualenv. It is not RED evidence.
- Exact RED command: `/Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/operations/test_env_template.py::test_runtime_diagnostics_and_release_vars_are_optional tests/operations/test_env_template.py::test_discovery_executor_relays_browser_diagnostics_dir -q`.
- Expected and observed RED: both tests failed with `KeyError: 'EGP_BROWSER_DIAGNOSTICS_DIR'`; the production template and executor environment lacked the locked declarations.
- Acceptance assertions are now locked. Implementation is limited to blank optional entries in `deploy/.env.production.example` and the exact blank-default relay in `docker-compose.yml`.
- Failure semantics remain fail-open: blank release identity is omitted and blank diagnostics remain disabled. No path, mount, retention, or activation policy is guessed.

## GREEN and primary-owned gates

- Scoped GREEN: `./.venv/bin/python -m pytest tests/operations/test_env_template.py tests/phase1/test_worker_build_browser_settings.py -q` — **25 passed**.
- Affected scope repeated three consecutive times — **25 passed** in each run.
- Scoped lint: `python -m ruff check tests/operations/test_env_template.py` — passed.
- Scoped format: `python -m ruff format --check tests/operations/test_env_template.py` — already formatted.
- Compose render: `docker compose --env-file deploy/.env.production.example config -q` — passed.
- Full lint: `python -m ruff check apps/ packages/ tests/ scripts/` — passed.
- Full compile: `python -m compileall -q apps packages` — passed.
- Full tests, first run: 2 failures, 1567 passed, 2 skipped. Backup CLI failed only because the helper worktree lacked the ignored `.venv`; discovery lease timing test ended pending despite excluding a competing claim.
- Worktree setup correction: linked the ignored `.venv` path to the primary checkout's existing environment. This changes no tracked file.
- Focused qualification rerun: both prior failures passed (**2 passed**).
- Full tests after setup correction: **1569 passed, 2 skipped, 112 warnings** in 210.49 seconds.
- Repository-wide format check remains a pre-existing baseline failure: 30 untouched files would be reformatted. The changed test file passes its scoped format check; unrelated files were not bulk-formatted.
- `uv lock --check` was unreached because `uv` is absent from PATH and no installed uv binary was found. `uv.lock` and dependency declarations are unchanged by this PR.

## Wiring evidence

- `docker-compose.yml` now passes the optional diagnostics value into `services.discovery-executor.environment`.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` launches the child worker with inherited environment, so the setting reaches `apps/worker/src/egp_worker/main.py::_build_browser_settings()`.
- Empty interpolation preserves `None` diagnostics behavior, proven by the existing worker settings tests.
- `EGP_RELEASE_SHA` remains wired through the same executor environment and is now declared in the authoritative production template.

## Independent QCHECK

- Provider: `terra_support`, read-only; exact three-file working-tree diff.
- Result: no blocking findings.
- MEDIUM future-regression note: Compose rendering is an explicit manual gate rather than a Docker subprocess test. Disposition: accepted as residual test-layer risk; actual blank/nonblank Compose rendering passed, and requiring Docker inside the portable unit suite is not justified for this config-only PR.
- LOW release-relay coverage gap: accepted and remediated by extending T2 to assert the existing exact `${EGP_RELEASE_SHA:-}` relay alongside diagnostics.
- LOW activation caveat: accepted as intentional non-goal. A nonblank diagnostics path still requires a separate mount, writable-path, and retention decision.

## Review (2026-08-13 15:38:00 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-g2-env-parity`
- Branch: `fix/environment-parity`
- Scope: working tree against `8b4a6476517519bb580cbf774af1de519c3bdbec`
- Commands Run: tracked diff/name/status inspection; RepoPrompt focused review; scoped pytest/ruff/format; Compose render; full pytest/lint/compile gates recorded above.

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
- A nonblank diagnostics path is intentionally not activation-ready without an operator-selected writable mount and retention policy.
- Docker Compose rendering remains an explicit delivery gate rather than a subprocess dependency inside the portable unit suite.

### Recommended Tests / Validation
- Keep the exact optional-section and executor-relay assertions.
- Keep `docker compose --env-file deploy/.env.production.example config -q` in delivery validation.
- Re-run focused and repository gates on the final candidate SHA.

### Rollout Notes
- Blank values preserve existing behavior: no release metadata and no diagnostics output.
- Roll out the template and Compose declaration together. Exact rollback is revert of this config-only PR.

### Formal disposition
- Formal `g-check`: **PASS, no findings**.
- Residual risks are documented non-goals and do not block this parity repair.
