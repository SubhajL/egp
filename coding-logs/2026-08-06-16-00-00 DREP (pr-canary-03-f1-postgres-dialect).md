# DREP: PR-CANARY-03 F1 — PostgreSQL dialect fix for record_accepted

## §0 Repo Profile

- **Language:** Python 3.12+ (3.13.1)
- **Test:** `./.venv/bin/python -m pytest <files> -v` (PYTHONPATH override for worktree)
- **Lint:** `ruff check <files>`
- **Build:** `python -m compileall`
- **Migration policy:** `docs/MIGRATION_POLICY.md`. **No migration in this slice** (038 already applied; this is a code-only dialect fix).
- **Coding log:** `coding-logs/2026-08-06-16-00-00 Coding Log (pr-canary-03-f1-postgres-dialect).md`
- **Repo/runtime ownership:** ours / ours. **Disposition:** production.
- **DB:** PostgreSQL 15+ (Supabase in prod); SQLite only as a test/bootstrap substitute. A healthy `egp-postgres` is running on localhost:5432.

### MUST NOT (CLAUDE.md)
- MUST use Python type hints on all signatures
- MUST scope all DB queries by `tenant_id`
- **T-3: Use a REAL database for integration tests (not mocks)** — the rule violated when F1 shipped (SQLite-only tests hid a PostgreSQL syntax error)

## §1 Goal / Non-Goals

**Goal:** Replace the SQLite-only `INSERT OR IGNORE` in `record_accepted` with the
repo's canonical dialect-agnostic `on_conflict_do_nothing` idiom, so idempotent
candidate insertion works on PostgreSQL (production) and SQLite (tests). Add a
deterministic PostgreSQL-dialect test and a live-Postgres integration test so this
class of dialect bug cannot pass green again.

**Non-Goals:**
- F2/F4/F5/F6 (separate slices) — this slice is F1 only
- No migration, no schema change
- No change to `finalize_*` / `reconcile_open_candidates` (they use UPDATE/SELECT, dialect-neutral — verified below)
- No change to the workflow or dispatcher

## §2 Requirements

| ID | Requirement |
|----|-------------|
| R1 | `record_accepted` emits SQL that is valid on the PostgreSQL dialect — specifically `INSERT ... ON CONFLICT DO NOTHING`, never `INSERT OR IGNORE`. |
| R2 | Idempotency is preserved on both dialects: a second `record_accepted` with the same `(tenant_id, run_id, candidate_key)` inserts no duplicate row and returns the existing row. |
| R3 | On a real PostgreSQL database, `record_accepted` + duplicate replay + `finalize_persisted` complete without a `ProgrammingError`/syntax error and leave exactly one row in the expected state. |

## §3 Change Contract

| ID | Path | Action | Anchor | New exports | Purpose |
|----|------|--------|--------|-------------|---------|
| F1 | `packages/db/src/egp_db/repositories/candidate_attempt_repo.py` | MODIFY | `record_accepted()` L202-207 (the `insert(...).prefix_with("OR IGNORE")` line) + add module-level `_dialect_insert()` helper | `_dialect_insert` (module-private) | dialect-agnostic idempotent insert |

## §4 Function Contracts

```
FN1  _dialect_insert(table, connection)  -> Insert
     File:  F1 (new module-level helper, mirrors project_aliases.py:156)
     Does:  return postgresql.insert(table) when connection dialect is postgresql,
            sqlite.insert(table) when sqlite, else generic insert(table).
     Pre:   connection is an open SQLAlchemy connection.
     Post:  returned statement supports on_conflict_do_nothing on pg/sqlite.
     Notes: <=10 lines; typed.

FN2  (modification) record_accepted(...) -> CandidateAttemptRecord
     Change: replace `insert(t).values(**values).prefix_with("OR IGNORE")` with
             stmt = _dialect_insert(t, conn).values(**values)
             if hasattr(stmt, "on_conflict_do_nothing"):
                 stmt = stmt.on_conflict_do_nothing(
                     index_elements=[t.c.tenant_id, t.c.run_id, t.c.candidate_key])
     Post:  unchanged behaviour on SQLite; VALID + idempotent on PostgreSQL.
            Still returns the existing/just-inserted row via the follow-up SELECT.
     Fix the misleading docstring/comment ("INSERT OR IGNORE ... for portability").
```

## §5 Cross-Language Schema Verification (THE phase that would have caught F1)

- Unique constraint backing the ON CONFLICT: `discovery_candidate_attempts_tenant_run_key UNIQUE (tenant_id, run_id, candidate_key)` — confirmed in `038_discovery_candidate_attempts.sql`. `index_elements` MUST match these three columns exactly, or PG raises "no unique or exclusion constraint matching the ON CONFLICT specification".
- `finalize_persisted/failed/dropped` use `UPDATE ... WHERE ... AND candidate_status='accepted'` — standard SQL, dialect-neutral. No change needed (grep-verified).
- `reconcile_open_candidates` uses `UPDATE ... WHERE run_id=... AND candidate_status='accepted'` — dialect-neutral. No change.
- Compile probe (serverless) already reproduced: current code → `INSERT OR IGNORE INTO discovery_candidate_attempts ...` on postgresql dialect (invalid). This is the RED-proof for T1.

## §6 Traceability Matrix

| Req | Fulfilled at — call site that realizes it | Tests | Files | Slice |
|-----|-------------------------------------------|-------|-------|-------|
| R1 | `record_accepted()` → `_dialect_insert(t,conn).on_conflict_do_nothing(index_elements=[tenant_id,run_id,candidate_key])` | T1 | F1 | S1 |
| R2 | same call site — ON CONFLICT DO NOTHING + follow-up SELECT returns existing row | T1(sqlite replay), T2 | F1 | S1 |
| R3 | same call site executed against real PostgreSQL | T2 | F1 | S1 |

## §5-tests / §5 Test Plan

```
T1   test_record_accepted_compiles_to_valid_postgresql (+ sqlite idempotency)
     File:   tests/phase1/test_candidate_postgres_dialect.py
     Covers: R1, R2
     Type:   unit (dialect compile probe — no server; plus SQLite idempotent replay)
     Arrange: build the statement record_accepted issues; compile against
              sqlalchemy.dialects.postgresql.dialect().
     Act:    compile to string; separately run record_accepted twice on a SQLite
              tmp db with migration 038 applied.
     Assert: compiled SQL contains "ON CONFLICT" and NOT "OR IGNORE";
             SQLite: second call returns same row id, table has exactly 1 row.
     RED-proof: BEFORE fix, compiled SQL contains "OR IGNORE" (verified via probe)
                → assertion fails on the NOT-"OR IGNORE" check. After fix, passes.
     Fixtures: tmp_path

T2   test_record_accepted_round_trips_on_real_postgres
     File:   tests/phase1/test_candidate_postgres_dialect.py
     Covers: R2, R3
     Type:   integration (REAL PostgreSQL — the T-3 rule F1 violated)
     Arrange: connect to Postgres from EGP_TEST_DATABASE_URL or the running
              egp-postgres; create the discovery_candidate_attempts table from
              migration 038 in an isolated schema/temp table; skip (return) if no
              Postgres reachable.
     Act:    record_accepted twice (same key); finalize_persisted once.
     Assert: no exception; exactly one row; status 'persisted' after finalize;
             duplicate insert did not error or duplicate.
     RED-proof: BEFORE fix, record_accepted raises ProgrammingError (syntax error
                near "OR") on PostgreSQL. After fix, completes and dedupes.
     Fixtures: tmp_path; postgres availability guard.
```

## §7 Wiring Verification

`_dialect_insert` is module-private, called only by `record_accepted` (same file). No new public surface. No registration needed.

## §8 Slice Plan

| ID | Scope | Owner | Stop line | Oracle | Done when |
|----|-------|-------|-----------|--------|-----------|
| S1 | F1, T1, T2 | **Claude** | — (Q0: touches a DB write path + the exact defect class that shipped broken; correctness-critical, not delegated) | T1+T2 green + all existing candidate/do-not-touch tests green + lint | Both new tests green (T2 on real PG), existing suite green |

## §9 Risks

| Risk | Trigger | Gate | Rollback |
|------|---------|------|----------|
| `index_elements` mismatch vs actual unique constraint | wrong columns | T2 on real PG raises "no matching ON CONFLICT" | revert |
| SQLite dialect insert lacks on_conflict on old SQLAlchemy | version drift | `hasattr` guard + T1 sqlite replay | guard falls back to plain insert |

## §10 Do-Not-Touch List

- `finalize_persisted/failed/dropped`, `reconcile_open_candidates`, `get_run_candidate_summary` in the same file — dialect-neutral, out of scope for F1
- Migration `038_discovery_candidate_attempts.sql` — already applied, must not edit
- All existing test files
- The workflow (`discover.py`) and dispatcher — F2/F5 slices, not this one
