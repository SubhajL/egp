# DREP: Environment Parity

## 0. Repository profile

- Root: `/Users/subhajlimanond/dev/egp-g2-env-parity`
- Branch: `fix/environment-parity`
- Baseline: `8b4a6476517519bb580cbf774af1de519c3bdbec` (`origin/main`)
- Baseline status: clean
- Policies: root `AGENTS.md` and `CLAUDE.md`; preserve TDD, secrets hygiene, and one-PR delivery.
- Stack: Python 3.12, pytest, PyYAML, Docker Compose.
- Coding Log: `coding-logs/2026-08-13-15-14-30 Coding Log (environment-parity).md`
- External egress: user selected g2, but no repository content is delegated. Slice is PRIMARY because it is small and sequential; DeepSeek adds no value.
- Scoped gate: `./.venv/bin/python -m pytest tests/operations/test_env_template.py tests/phase1/test_worker_build_browser_settings.py -q`
- Full gates: `uv lock --check`; `uv run --frozen ruff check apps/ packages/ tests/ scripts/`; `uv run --frozen ruff format --check apps/ packages/ tests/ scripts/`; `uv run --frozen python -m compileall apps packages`; `./.venv/bin/python -m pytest tests/ apps/ packages/ -q`; `./.venv/bin/python scripts/check_main_sync.py --json`.
- Migration policy: no schema or manifest change.

## 1. Goal, non-goals, and success

Declare the two genuine optional runtime inputs omitted from the production environment contract and relay browser diagnostics into the discovery executor. Preserve current blank/unset behavior: no SHA derivation, diagnostics disabled, no directory creation, and no retention choice.

Non-goals: choosing or mounting a durable diagnostics path, enabling diagnostics, deriving a release SHA, changing runtime Python behavior, changing local-development Compose, or changing remote-crawler policy.

Success means the existing two environment-template failures become green, the executor receives an explicitly configured diagnostics value, blank values preserve current behavior, Compose renders, and the full repository gate passes.

Public surface: `deploy/.env.production.example` gains optional blank `EGP_RELEASE_SHA` and `EGP_BROWSER_DIAGNOSTICS_DIR`; `docker-compose.yml` relays `EGP_BROWSER_DIAGNOSTICS_DIR` to `discovery-executor`. No API, schema, CLI, or runtime-code changes.

Failure semantics: blank/unset fails open to omitted release metadata and disabled diagnostics. A nonblank diagnostics path remains operator-owned and must already be writable; this PR does not claim activation safety.

Rollout: deploy template and Compose declaration together. Backout: revert the PR; runtime behavior for blank values is unchanged.

## 2. Requirements

- **R1** `deploy/.env.production.example` declares `EGP_RELEASE_SHA` in the optional section with a blank value.
- **R2** `deploy/.env.production.example` declares `EGP_BROWSER_DIAGNOSTICS_DIR` in the optional section with a blank value.
- **R3** `docker-compose.yml` relays `${EGP_BROWSER_DIAGNOSTICS_DIR:-}` only to the `discovery-executor` runtime that launches the worker.
- **R4** Tests prove both variables are optional declarations and the diagnostics relay is wired; no allowlist hides either runtime input.
- **R5** Existing unset/blank worker behavior stays green and Docker Compose renders from the production template.

## 3. File contract

| ID | Path | Action | Anchor | Exports/contracts | Purpose |
|---|---|---|---|---|---|
| F1 | `tests/operations/test_env_template.py` | MODIFY | environment-template tests | none | RED proof for optional declarations and executor relay |
| F2 | `deploy/.env.production.example` | MODIFY | optional section | two optional env keys | authoritative deployment declaration |
| F3 | `docker-compose.yml` | MODIFY | `discovery-executor.environment` | Compose env relay | pass diagnostics setting to worker process |

## 4. Function contract

No runtime function changes.

- **FN1** `test_runtime_diagnostics_and_release_vars_are_optional()` in F1 parses the template and requires both keys in the optional section with blank placeholders.
- **FN2** `test_discovery_executor_relays_optional_observability_vars()` in F1 parses Compose and requires the exact blank-default diagnostics and release values in `services.discovery-executor.environment`.

## 5. Test contract

- **T1** `test_runtime_diagnostics_and_release_vars_are_optional`
  - Covers: R1, R2, R4
  - Type: contract
  - Arrange: parse authoritative production template.
  - Act: read both entries.
  - Assert: both exist, are optional, and blank.
  - RED command: `./.venv/bin/python -m pytest tests/operations/test_env_template.py::test_runtime_diagnostics_and_release_vars_are_optional -q`
  - RED proof: `EGP_RELEASE_SHA` lookup is absent before the implementation.
- **T2** `test_discovery_executor_relays_optional_observability_vars`
  - Covers: R3, R4
  - Type: configuration wiring
  - Arrange: parse `docker-compose.yml` with PyYAML.
  - Act: inspect discovery executor environment.
  - Assert: exact blank-default diagnostics and release interpolations are present.
  - RED command: `./.venv/bin/python -m pytest tests/operations/test_env_template.py::test_discovery_executor_relays_optional_observability_vars -q`
  - RED proof: environment mapping lacks `EGP_BROWSER_DIAGNOSTICS_DIR`.
- **T3** existing `test_env_template_tracks_runtime_egp_vars` and `test_env_template_covers_all_compose_required_vars`
  - Covers: R1, R2, R4
  - GREEN command: full scoped gate.
- **T4** existing `tests/phase1/test_worker_build_browser_settings.py`
  - Covers: R5
  - GREEN command: full scoped gate.

## 6. Traceability

| Requirement | Runtime realization | Tests | Files | Slice |
|---|---|---|---|---|
| R1 | `deploy/.env.production.example` optional declaration | T1,T3 | F1,F2 | S1 |
| R2 | `deploy/.env.production.example` optional declaration | T1,T3 | F1,F2 | S1 |
| R3 | `services.discovery-executor.environment` relay | T2 | F1,F3 | S1 |
| R4 | parser assertions and existing drift scan | T1,T2,T3 | F1,F2,F3 | S1 |
| R5 | blank interpolation plus existing worker normalization | T4 and Compose config | F2,F3 | S1 |

## 7. Wiring

| Component | Non-test runtime caller | Registration/config load | Schema/contract evidence |
|---|---|---|---|
| `EGP_RELEASE_SHA` | `egp_api.executors.discovery_dispatch` structured startup events | `docker-compose.yml` discovery executor env | optional blank declaration in F2 |
| `EGP_BROWSER_DIAGNOSTICS_DIR` | `egp_worker.main._build_browser_settings()` in the subprocess launched by discovery executor | F3 Compose env; child inherits executor env | optional blank declaration in F2; T2 |

## 8. Slice plan

| ID | Requirements/files/tests | Owner | Q0-Q3 result | Stop line | Production allowlist | Oracle | Done when |
|---|---|---|---|---|---|---|---|
| S1 | R1-R5; F1-F3; T1-T4 | PRIMARY | Q0: delegation unnecessary for small sequential config slice | PRIMARY | none | T1-T4 plus Compose render | primary verifies all gates and delivery |

Stop if a nonblank diagnostics path, mount, retention policy, runtime-code change, or any file outside F1-F3 becomes necessary.

## 9. Gates, review, rollout, and rollback

1. Author T1/T2 and confirm their predicted RED failures.
2. Implement only F2/F3 and confirm scoped GREEN.
3. Run affected scope three consecutive times.
4. Run Compose render, full gates, in-session QCHECK, and formal `g-check`.
5. Commit, PR, required checks, authorized admin merge, and exact-SHA local-main landing.
6. Remove the session worktree only after artifacts and merged commit are retained.

No feature flag is needed because empty values preserve existing behavior. Revert is the exact rollback.

## 10. Do-not-touch and baseline

Do not touch runtime Python, migration files, `.env.remotecrawl.example`, local-development Compose, F6 artifacts, primary-checkout dirty files, or any file outside F1-F3 plus this DREP/Coding Log/pointer. Baseline is the clean worktree at `8b4a6476517519bb580cbf774af1de519c3bdbec`.

Decision-complete checklist: every ID resolves; every requirement has runtime/config realization and test evidence; public changes and blank failure semantics are locked; no architecture or deployment-policy choice remains for implementation.
