# Coding Log: PR-CANARY-03 F1 — PostgreSQL Dialect Fix

**Date:** 2026-08-06
**Slug:** pr-canary-03-f1-postgres-dialect
**Status:** IN PROGRESS

## Goal

Fix the ship-blocking F1 defect from the PR-CANARY-03 review: `record_accepted`
emits `INSERT OR IGNORE` (SQLite-only), which aborts every crawl on PostgreSQL.
Replace with the repo's canonical dialect-agnostic `on_conflict_do_nothing`
pattern, and add a PostgreSQL-dialect test so this class of bug cannot pass again.

## Phase 3-4: Codex adversarial review + synthesis

Codex (gpt-5.6-sol, xhigh) reviewed the plan against the source spec. Dispositions:

- **T1 vacuity (ACCEPTED):** an independently-rebuilt statement could pass while
  production stays broken. → T1 now captures the REAL statement `record_accepted`
  executes (SQLAlchemy `before_execute` listener) and compiles THAT against the
  postgresql dialect.
- **T2 setup incomplete (ACCEPTED):** migration 038 is not standalone — it needs
  migration 001 (`uuid_generate_v4`, `tenants`, `update_updated_at_column`). → T2
  uses `TempPostgresCluster` + `apply_migrations` (FULL set) + seeds a tenant,
  matching `run_phase1_postgres_project_run_smoke`. Binaries are present, so T2 is
  MANDATORY (the non-foolable oracle), not availability-skipped.
- **"038 on SQLite" (ACCEPTED):** 038 is PG-specific; SQLite path uses
  `bootstrap_schema=True`. Existing `test_record_accepted_is_idempotent` already
  covers SQLite replay — not duplicated.
- **Read Committed race (NOTED, no action):** benign under the engine's default
  isolation; no isolation override exists.

### Findings routed to OTHER slices (NOT fixed here — F1 scope only)
- `reconcile_open_candidates` filters by `run_id` only, missing `tenant_id`
  (CLAUDE.md tenant-scope MUST) → **F5 slice**.
- `finalize_*` returns None for both same-terminal replay and conflicting-terminal
  rewrite; spec wants conflict REJECTED distinctly → **F6 slice**.

## Implementation + Gates

**Stop line:** Claude implements (Q0: DB write path + the exact defect class that
shipped broken). No delegation.

**TDD:** T1 + T2 written and RED-proven first.
- T2 reproduced the REAL bug on real PostgreSQL: `ProgrammingError: syntax error
  at or near "OR"` → `INSERT OR IGNORE INTO discovery_candidate_attempts`.
- T1 captured the real statement and found `OR IGNORE`.
- After the `_dialect_insert` + `on_conflict_do_nothing` fix: both GREEN.
- T1 non-vacuity MUTATION-verified: reverting to `prefix_with("OR IGNORE")` makes
  T1 fail; restoring makes it pass.

**Gates:** ruff clean; 31-test regression suite green; 3x flakiness stable
(incl. real-Postgres T2 each round).

## Review — Round 1 (loop-until-dry: DRY)

Implementer: Claude. Both tiers independent of implementer.

- **Tier 1 (Opus agent):** No correctness findings. Independently confirmed T1
  fails on old code / passes on new; T2 ran on real PostgreSQL. Trivial nit: test
  engines not `dispose()`d.
- **Tier 2 (Codex gpt-5.6-sol):** No F1 correctness findings — SHIP. index_elements
  matches migration 038 constraint; T1 non-vacuous; T2 faithful. One LOW: stale
  module docstring said T1 compiles PostgreSQL (it compiles SQLite; T2 is the PG
  proof).

**Dispositions:**
- LOW (docstring) → FIXED.
- Trivial (engine dispose) → NOTED, not fixed: pure hygiene, no failure mode;
  fixing requires reaching into the private `_engine` attribute (worse smell).

Post-fix change was docstring-only (no logic), so the round is DRY: zero open
CRITICAL/HIGH, gates re-run green.

**STATUS: COMPLETE**
