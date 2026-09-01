# Coding Log — public MVP runbook contract

- Started: 2026-09-01 20:34:04 +07
- Repo: `/Users/subhajlimanond/dev/egp`
- Session worktree: `/Users/subhajlimanond/dev/egp-public-mvp-runbook-contract`
- Branch: `fix/public-mvp-runbook-contract`
- Baseline: `1a69f2ed03a71a3e73db7b0beb1b6669a4fb553b`
- Goal: land the bounded documentation/static-test correction before any exact-SHA runtime build.
- Runtime boundary: no image build, production query, backup, migration, deploy, browser action,
  ingestion, supervision, rollback rehearsal, or activation is authorized in this lifecycle.

## Ownership and preserved state

The primary agent owns tests, documentation, lifecycle evidence, gates, review, and delivery. There
is no production-code slice, so no `luna_implementer` handoff or ownership receipt is required.

Baseline worktrees, all user-owned and outside cleanup scope:

- `/Users/subhajlimanond/dev/egp` on `main` at `1a69f2ed...`, dirty with protected logs/docs;
- `/Users/subhajlimanond/dev/egp-exact-canary-false-success-repair` on
  `fix/exact-canary-false-success-repair` at `5ffbfebd...`;
- `/Users/subhajlimanond/dev/egp-ops-main` detached at `722b1e0e...`;
- `/Users/subhajlimanond/dev/egp-public-mvp-track-bc` detached at `30ebdeec...`.

This session created only `/Users/subhajlimanond/dev/egp-public-mvp-runbook-contract`. The dirty
primary checkout and its `.codex/coding-log.current` were not changed.

## Locked scope

Substantive files:

- `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`;
- `tests/operations/test_remote_crawl_assets.py`.

Lifecycle file:

- this Coding Log; the session-local ignored `.codex/coding-log.current` points here.

No application/service source, shell implementation, runtime configuration, migration, schema,
Compose, API, worker, verifier, CLI behavior, environment contract, or public endpoint change is
allowed.

## RED

Command:

```text
.venv/bin/python -m pytest \
  tests/operations/test_remote_crawl_assets.py::test_public_mvp_runbook_uses_explicit_manifest_check_mode \
  tests/operations/test_remote_crawl_assets.py::test_public_mvp_runbook_describes_actual_migration_lock_order \
  tests/operations/test_remote_crawl_assets.py::test_public_mvp_runbook_separates_migration_040_attestation -q
```

Observed expected result: `3 failed in 0.06s`.

- manifest gate failed because the runbook used the bare CLI without required `--check`;
- lock-order test failed because the runbook lacked the before-connection verification contract;
- 040-separation test failed because postflight wording omitted explicit 038/039 fields and
  overstated the preflight's migration scope.

## GREEN implementation

- Added exactly the three planned structural tests and normalized Stage 7 whitespace so prose
  wrapping does not weaken or spuriously fail the semantic contract.
- Changed the source gate to `check_migration_manifest.py --check`.
- Documented byte/manifest verification before DB connection, followed by advisory-locked
  ledger/digest/application work.
- Limited candidate postflight to 038/039 and made migration 040 a separate ledger, constraint,
  and `/ready` proof.
- Added an authority-approved positive bundle age below 86,400 seconds, passed to the existing
  verifier, while explicitly preserving the installer's unchanged default behavior.

Initial GREEN command: the three named tests above.

Observed result: `3 passed in 0.04s`. An intermediate run had one pass and two failures because
literal strings crossed Markdown line wraps; the tests were corrected to normalize whitespace,
then the locked semantic scope passed.

## Primary verification

- Focused asset module: `28 passed in 7.33s`.
- Existing runbook overlap: `3 passed, 89 deselected`.
- Manifest: `migration manifest verified: 42 file(s)`.
- Ruff on changed test: passed.
- Frozen lock: `.tools/uv-0.11.32/bin/uv lock --check` resolved 92 packages and passed.
- Shell syntax: `run_remote_crawl.sh`, `install_launchd.sh`, and `check_launch_gates.sh` passed.
- `git diff --check`: passed.
- Full Python gate: `2085 passed, 4 skipped, 114 warnings in 249.24s`.
- Three affected-scope repeats: `28 passed` in 3.60s, 5.27s, and 4.98s.
- Full-suite residue: a zero-byte session-generated `test.sqlite3` was removed; ignored caches and
  the frozen `.venv`/`.tools` remain local and untracked.

## Wiring verification

| Component | Non-test call site | Registration/config load | Schema/contract match |
|---|---|---|---|
| Manifest source gate | `scripts/check_migration_manifest.py:93` | required `--check` mode at line 78 | `packages/db/src/migrations/manifest.sha256`, verified 42/42 |
| Migrator ordering | `packages/db/src/egp_db/migration_runner.py:131` | payload load at line 140, DB connect at line 148, advisory lock at line 152 | ledger/digest/application remain under acquired lock |
| Candidate postflight | `scripts/candidate_integrity_preflight.py:336` | 038/039 ledger fields at lines 60-61 and 268-269 | report does not expose migration 040 |
| Migration readiness | `apps/api/src/egp_api/services/readiness_service.py:120` | `/ready` registered in `apps/api/src/egp_api/bootstrap/middleware.py:158` | separate pending/unexpected migration counts |

## Independent QCHECK and remediation

The read-only `terra_support` QCHECK reported:

- HIGH: the approved tighter bundle age was not a hard installer-enforced activation boundary;
- MEDIUM: migration-040 ledger/digest/constraint proof had no exact read-only command.

Disposition and remediation, owned by the primary:

- Preserved the locked docs/tests-only scope and explicitly labeled the tighter age as a procedural
  campaign control. The runbook now stops and requires a separately tested installer contract if a
  hard activation-boundary limit is required; it no longer implies that the unchanged installer
  enforces the private tighter age.
- Added a bounded `REPEATABLE READ READ ONLY` `psycopg` packet that records and validates the 040
  ledger tail/digest and `pg_get_constraintdef(...)` output privately. Strengthened the existing
  third regression test to require those query anchors. During formal-review preparation, the
  primary replaced an interim `psql "$DATABASE_URL"` form because expanding the credential-bearing
  URL into process arguments could expose it; the regression now rejects that unsafe form. No
  production probe was executed.
- Chained the two approved-age guards to the verifier with `&&`, so an out-of-policy configured
  value cannot fall through to the explicit bundle-verification command.

Post-remediation verification:

- affected asset module: `28 passed`;
- full verifier/runbook module: `92 passed`;
- extracted migration-040 attestation Python packet compiled successfully;
- Ruff, manifest 42/42, static query-packet contract, and `git diff --check`: passed;
- final-candidate full Python gate: `2085 passed, 4 skipped, 114 warnings in 233.16s`;
- final affected-scope repeats: `28 passed` in 3.25s, 3.17s, and 4.45s;
- the full gate's zero-byte session-generated `test.sqlite3` residue was removed again.

## Review and delivery

Commit, PR, merge, exact-SHA local-main landing, and worktree closeout are pending.

## Review (2026-09-01 20:48:26 +07) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-public-mvp-runbook-contract`
- Branch: `fix/public-mvp-runbook-contract`
- Scope: staged working tree against `1a69f2ed03a71a3e73db7b0beb1b6669a4fb553b`
- Commands Run: `git status --porcelain=v1`; targeted staged `git diff`; `git diff
  --staged --check`; focused/full/repeated pytest; Ruff; frozen lock check; migration manifest check;
  shell syntax checks; extracted attestation-packet compilation
- RepoPrompt: initial discovery/context was bound to `/Users/subhajlimanond/dev/egp`; formal-review
  rebinding to the new session worktree had no existing workspace match, so review used the built
  RepoPrompt context plus the complete targeted staged diff.

### Findings

CRITICAL

- No findings.

HIGH

- No findings. The independent QCHECK's activation-age finding was remediated by accurately
  labeling the tighter age as procedural, chaining the explicit verification guards, and requiring
  a separate installer-contract PR when hard activation-boundary enforcement is required.

MEDIUM

- No findings. The independent QCHECK's migration-040 evidence gap was remediated with a bounded,
  environment-only, read-only `psycopg` attestation packet and stronger static assertions.

LOW

- No findings.

### Open Questions / Assumptions

- The campaign-approved tighter bundle age remains procedural by the locked docs/tests-only design;
  the existing installer still independently uses its 86,400-second default.
- The migration-040 packet was syntax-compiled and source-reviewed but intentionally not executed
  against production; its live output remains a later authority-gated acceptance input.

### Recommended Tests / Validation

- Preserve the recorded `2085 passed, 4 skipped` full Python gate and final three `28 passed`
  affected-scope repeats as the accepted local candidate evidence.
- After merge, freeze and qualify the merge SHA before any image build or runtime action.

### Rollout Notes

- This PR establishes documentation/source acceptance only. It does not establish image,
  production-schema, deployment, browser, ingestion, supervision, rollback, bundle, or activation
  acceptance.
- Runtime authority, browser-observation authority, and live-ingestion authority remain distinct
  later boundaries.
