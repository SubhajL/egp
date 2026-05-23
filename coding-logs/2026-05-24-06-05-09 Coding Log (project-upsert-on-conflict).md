# PR-04 Project Upsert ON CONFLICT Coding Log

## Planning (2026-05-24 06:05:09 +0700)

Auggie semantic search unavailable: `codebase-retrieval` returned HTTP 429. This plan is based on direct file inspection and exact identifier searches of:

- `AGENTS.md`
- `packages/AGENTS.md`
- `packages/db/AGENTS.md`
- `docs/MIGRATION_POLICY.md`
- `packages/db/src/egp_db/repositories/project_persistence.py`
- `packages/db/src/egp_db/repositories/project_aliases.py`
- `packages/db/src/egp_db/repositories/project_schema.py`
- `packages/db/src/egp_db/repositories/project_utils.py`
- `packages/db/src/migrations/001_initial_schema.sql`
- `tests/phase1/test_project_and_run_persistence.py`
- `tests/phase1/test_migration_runner.py`

### Plan Draft A - Atomic Upserts In Existing Repository Methods

#### Overview

Convert the project write path from read-then-insert/update to a dialect-aware SQLAlchemy `INSERT ... ON CONFLICT` implementation. Keep the public `SqlProjectRepository.upsert_project()` API unchanged, update aliases and status events to use conflict-safe inserts, and add the status-event uniqueness migration required for concurrent writers.

#### Files To Change

- `packages/db/src/egp_db/repositories/project_persistence.py`: replace project insert/update split with one atomic upsert, then select the persisted row.
- `packages/db/src/egp_db/repositories/project_aliases.py`: make alias inserts and status-event inserts `ON CONFLICT DO NOTHING`.
- `packages/db/src/egp_db/repositories/project_schema.py`: add SQLAlchemy metadata uniqueness for status events so test-created schemas match migrations.
- `packages/db/src/migrations/021_project_status_events_dedup.sql`: add status-event duplicate cleanup and unique constraint.
- `tests/concurrency/test_project_upsert_concurrent.py`: add Postgres concurrency coverage.

#### Implementation Steps

TDD sequence:

1. Add `test_concurrent_project_upsert_is_idempotent` and `test_concurrent_project_upsert_dedupes_status_events`.
2. Run the new test and confirm the current read-then-insert path raises or creates duplicate status events under concurrency.
3. Implement dialect-aware project/alias/status-event upsert helpers.
4. Add the migration and schema metadata uniqueness.
5. Run focused tests, migration tests if Postgres binaries are present, ruff, and compileall.

Functions:

- `_insert_project_on_conflict(...)`: build one project insert/upsert statement for PostgreSQL and SQLite.
- `_build_project_values(...)`: keep normalization and timestamp values in one place for insert/update values.
- `_upsert_aliases(...)`: issue conflict-safe inserts without a prior select.
- `_insert_status_event(...)`: issue `ON CONFLICT DO NOTHING` on `(project_id, normalized_status, observed_at)` after preserving adjacent duplicate suppression.

#### Test Coverage

- `test_concurrent_project_upsert_is_idempotent`: five threads create one project row.
- `test_concurrent_project_upsert_dedupes_aliases`: alias rows remain unique.
- `test_concurrent_project_upsert_dedupes_status_events`: duplicate observed status is deduped.
- Migration runner existing test: applies `021_project_status_events_dedup.sql`.

#### Decision Completeness

- Goal: make concurrent project persistence idempotent and eliminate project/status-event integrity races.
- Non-goals: document upsert behavior, admission control, rate limiting, or changing project lifecycle semantics beyond race safety.
- Success criteria: five concurrent upserts for one `(tenant_id, canonical_project_id)` complete with zero exceptions, exactly one project row, deduped aliases, and deduped status events.
- Public interfaces: one DB migration adds unique constraint `project_status_events_project_status_observed_uq`; no API/env/CLI changes.
- Edge cases / failure modes: invalid lifecycle transitions still fail closed via `transition_state`; duplicate status events are ignored; aliases use conflict no-op; migration removes pre-existing exact duplicates before adding the constraint.
- Rollout & monitoring: apply migration after duplicate pre-check; watch project upsert IntegrityError logs and project/status event counts.
- Acceptance checks: new concurrency test passes; `compileall packages/db/src`; `ruff check packages/db/src tests/concurrency/test_project_upsert_concurrent.py`; migration runner applies all migrations if local Postgres is available.

#### Dependencies

No new package dependency. Uses SQLAlchemy dialect-specific insert helpers already covered by existing dependencies.

#### Validation

Run the new concurrency test repeatedly, package compile, ruff, and migration runner coverage when Postgres binaries are installed.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Project upsert | `SqlProjectRepository.upsert_project()` | `SqlProjectRepository(ProjectPersistenceMixin, ...)` | `projects(tenant_id, canonical_project_id)` |
| Alias conflict handling | `upsert_project()` -> `_upsert_aliases()` | `ProjectAliasMixin` inheritance | `project_aliases(project_id, alias_type, alias_value)` |
| Status-event constraint | `upsert_project()` -> `_insert_status_event()` | migration runner loads sorted SQL files | `project_status_events(project_id, normalized_status, observed_at)` |

Cross-language schema verification: exact searches show project persistence is Python-only repository code; API/worker use `SqlProjectRepository`, and SQL migrations define `projects`, `project_aliases`, and `project_status_events` with matching names.

### Plan Draft B - Retry IntegrityError Around Existing Flow

#### Overview

Keep the current read-then-insert/update structure and catch `IntegrityError` from project, alias, and status-event inserts. On conflict, re-read the row and retry the update portion.

#### Files To Change

- `project_persistence.py`: wrap insert path in retry logic.
- `project_aliases.py`: catch duplicate alias/status events.
- `project_schema.py` and migration: add status-event uniqueness.
- `tests/concurrency/test_project_upsert_concurrent.py`: same behavioral coverage.

#### Implementation Steps

TDD sequence:

1. Add the same concurrency tests.
2. Confirm current behavior fails under concurrent inserts.
3. Add bounded retry on project insert conflict.
4. Add conflict catches around alias and status events.
5. Run focused tests and gates.

Functions:

- `_upsert_project_with_retry(...)`: retry the existing write flow after unique conflicts.
- `_insert_alias_or_ignore(...)`: catch duplicate alias integrity errors.
- `_insert_status_event_or_ignore(...)`: catch duplicate status-event integrity errors.

#### Test Coverage

- Same tests as Draft A.

#### Decision Completeness

- Goal: make concurrent writes complete without user-visible errors.
- Non-goals: replacing the persistence structure with lower-level SQL.
- Success criteria: same row/count outcomes as Draft A.
- Public interfaces: same migration and constraint as Draft A.
- Edge cases / failure modes: bounded retries could still race and fail after retry budget; catches must not swallow unrelated integrity errors.
- Rollout & monitoring: same as Draft A, with extra watch for residual retries/failures.
- Acceptance checks: same as Draft A.

#### Dependencies

No new package dependency.

#### Validation

Same tests and gates as Draft A.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Retry project upsert | `SqlProjectRepository.upsert_project()` | `SqlProjectRepository(ProjectPersistenceMixin, ...)` | `projects(tenant_id, canonical_project_id)` |
| Retry alias/status inserts | `_upsert_aliases()`, `_insert_status_event()` | `ProjectAliasMixin` inheritance | `project_aliases`, `project_status_events` |
| Status-event constraint | migration runner | sorted migration filenames | `project_status_events` |

Cross-language schema verification: same table-name verification as Draft A.

### Comparative Analysis

Draft A directly uses the database's conflict resolution mechanism and removes the race window at the project, alias, and status-event write sites. It better matches PR-04's explicit scope and avoids treating expected contention as exceptions.

Draft B is less invasive but preserves more read-then-write complexity and risks swallowing or retrying the wrong failures. It is a fallback if dialect-specific upsert support creates unacceptable portability issues.

### Unified Execution Plan

#### Overview

Implement Draft A with small helper functions so `upsert_project()` remains readable. Keep behavior compatible for SQLite tests and PostgreSQL production by selecting the insert dialect from `connection.dialect.name`.

#### Files To Change

- `packages/db/src/egp_db/repositories/project_persistence.py`
- `packages/db/src/egp_db/repositories/project_aliases.py`
- `packages/db/src/egp_db/repositories/project_schema.py`
- `packages/db/src/migrations/021_project_status_events_dedup.sql`
- `tests/concurrency/test_project_upsert_concurrent.py`

#### Implementation Steps

TDD sequence:

1. Add failing concurrency tests in `tests/concurrency/test_project_upsert_concurrent.py`.
2. Run the new test and record RED failure.
3. Implement project/alias/status-event `ON CONFLICT` helpers.
4. Add migration and metadata constraint.
5. Run focused tests three times, then ruff, compileall, migration test.
6. Run QCHECK and formal `g-check` before commit.

Functions:

- `_dialect_insert(table, connection)`: return PostgreSQL, SQLite, or generic insert for unsupported dialects.
- `_project_insert_values(...)`: normalize record fields and timestamps for insertion.
- `_project_update_values(...)`: compute conflict update values while preserving existing optional values where needed.
- `_upsert_aliases(...)`: insert each alias with `DO NOTHING`.
- `_insert_status_event(...)`: insert status event with `DO NOTHING` under the new unique constraint.

#### Test Coverage

- `test_concurrent_project_upsert_is_idempotent`: concurrent calls return one project id.
- `test_concurrent_project_upsert_keeps_aliases_unique`: no duplicate alias rows.
- `test_concurrent_project_upsert_dedupes_status_events`: no duplicate status event rows.
- `test_migration_runner_applies_and_records_all_versions`: new migration participates in sorted migrations.

#### Decision Completeness

- Goal: make PR-04 project persistence safe under concurrent crawls.
- Non-goals: PR-05 document upsert/orphan cleanup; PR-06 rate limiting; UI/API behavior changes.
- Success criteria: tests prove zero exceptions, one project row, alias uniqueness, and status-event dedupe after concurrent writes.
- Public interfaces: new migration `021_project_status_events_dedup.sql`; repository method signature unchanged.
- Edge cases / failure modes: unsupported SQL dialects keep generic insert path and may still rely on existing uniqueness; SQLite and PostgreSQL get atomic conflict behavior; migration deletes duplicate status rows deterministically by keeping the earliest `created_at`.
- Rollout & monitoring: run duplicate pre-check before migration; monitor `IntegrityError` logs and future project upsert conflict metrics when available.
- Acceptance checks: focused concurrency pytest, compileall, ruff, migration runner test when possible.

#### Dependencies

No new dependencies.

#### Validation

Use a temp SQLite DB for fast concurrency regression and local Postgres migration runner when binaries are available. If Postgres is not available, note that migration runner test skips by design.

#### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Project upsert helper | `ProjectPersistenceMixin.upsert_project()` | `SqlProjectRepository` mixin inheritance | `projects` unique `(tenant_id, canonical_project_id)` |
| Alias no-op conflicts | `upsert_project()` -> `_upsert_aliases()` | `ProjectAliasMixin` mixin inheritance | `project_aliases` unique `(project_id, alias_type, alias_value)` |
| Status-event no-op conflicts | `upsert_project()` -> `_insert_status_event()` | `ProjectAliasMixin` mixin inheritance | `project_status_events` unique `(project_id, normalized_status, observed_at)` |
| Migration 021 | `egp_db.migration_runner.apply_migrations()` | filename-sorted `packages/db/src/migrations` | `project_status_events` |

#### Decision-Complete Checklist

- No open decisions remain for the implementer.
- Changed public interface is the `021` migration only.
- Every behavior change has a concurrency test.
- Validation commands are scoped and concrete.
- Wiring table covers code helpers and migration.
- Rollout/backout is specified for the deployment-visible migration.

## Implementation (2026-05-24 06:13:57 +0700)

### Goal

Implement PR-04: make concurrent project upserts idempotent with database conflict handling, dedupe aliases/status events, and add the status-event uniqueness migration.

### What Changed

- `packages/db/src/egp_db/repositories/project_persistence.py`: added dialect-aware `INSERT ... ON CONFLICT DO UPDATE` for first-write project creation. If another writer wins the insert race, the code routes through the existing update path so lifecycle transitions still use `transition_state()`.
- `packages/db/src/egp_db/repositories/project_aliases.py`: changed alias and status-event inserts to dialect-aware `ON CONFLICT DO NOTHING`.
- `packages/db/src/egp_db/repositories/project_schema.py`: added SQLAlchemy metadata uniqueness for `(project_id, normalized_status, observed_at)`.
- `packages/db/src/migrations/021_project_status_events_dedup.sql`: deletes exact duplicate status events, then adds `project_status_events_project_status_observed_uq`.
- `tests/concurrency/test_project_upsert_concurrent.py`: added a deterministic five-thread race harness that previously forced the `projects(tenant_id, canonical_project_id)` unique race.

### TDD Evidence

- RED: `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/domain/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/concurrency/test_project_upsert_concurrent.py -q` failed with `sqlite3.IntegrityError: UNIQUE constraint failed: projects.tenant_id, projects.canonical_project_id`.
- GREEN: same command passed after the upsert implementation.
- Flake check: same concurrency test passed three times after final code changes.

### Tests Run

- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/domain/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/concurrency/test_project_upsert_concurrent.py -q` -> passed.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/domain/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_project_and_run_persistence.py -q` -> `17 passed`.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/domain/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_upserts_and_notifies_new_projects -q` -> passed.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/domain/src:packages/notification-core/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_migration_runner.py -q` -> passed.
- `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check packages/db/src tests/concurrency/test_project_upsert_concurrent.py` -> passed.
- `/Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall packages/db/src` -> passed.
- `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --check` -> passed.

### Known Test Gap / Residual Failure

- Full `tests/phase1/test_projects_and_runs_api.py -q` was attempted and failed in two run-creation assertions: `test_projects_and_runs_endpoints_accept_limit_and_offset` expected two runs but received zero, and `test_finish_run_failed_emits_run_failed_notification` received a response without `run`. The project-list/project-ingest tests in that file passed; the failures are in the run endpoint path and appear outside the PR-04 project-upsert change.

### Wiring Verification Evidence

| Component | Wiring Verified? | Evidence |
|---|---|---|
| Project conflict insert | YES | `ProjectPersistenceMixin.upsert_project()` calls `_upsert_project_by_canonical()` when `_find_existing_row()` returns no row. |
| Lifecycle guard after race conflict | YES | If the selected row id differs from the candidate id, `upsert_project()` runs the existing `transition_state()` update branch. |
| Alias conflict no-op | YES | `_upsert_aliases()` writes via dialect insert with `on_conflict_do_nothing()` on the existing alias unique key. |
| Status-event conflict no-op | YES | `_insert_status_event()` writes via dialect insert with `on_conflict_do_nothing()` on the new unique key. |
| Migration | YES | `test_migration_runner_applies_and_records_all_versions` passed with `021_project_status_events_dedup.sql` in sorted migrations. |

### Behavior Changes And Risk Notes

- Concurrent first-seen project writes no longer surface project unique `IntegrityError`; one row wins and other writers converge on it.
- Alias and status-event duplicate writes are no-op conflicts, not application exceptions.
- Migration is deployment-visible and should still be preceded by the duplicate pre-check from the rollout plan.

### Follow-Ups / Known Gaps

- No explicit project-upsert conflict metrics were added in this PR; rollout should rely on log IntegrityError rate until metric instrumentation is added.

## Review (2026-05-24 06:15:41 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-pr04`
- Branch: `fix/project-upsert-on-conflict`
- Scope: staged working tree based on `6fc0223f`
- Commands Run:
  - `git status -sb`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached -- packages/db/src/egp_db/repositories/project_persistence.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached -- packages/db/src/egp_db/repositories/project_aliases.py packages/db/src/egp_db/repositories/project_schema.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached -- packages/db/src/migrations/021_project_status_events_dedup.sql tests/concurrency/test_project_upsert_concurrent.py`
  - `nl -ba packages/db/src/egp_db/repositories/project_persistence.py | sed -n '35,290p'`
  - `nl -ba packages/db/src/egp_db/repositories/project_aliases.py | sed -n '60,180p'`
  - `nl -ba packages/db/src/migrations/021_project_status_events_dedup.sql | sed -n '1,80p'`
  - `nl -ba tests/concurrency/test_project_upsert_concurrent.py | sed -n '1,150p'`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --check`

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

- Assumes `normalized_status` is non-null for project-upsert-generated status events. The new unique key follows the PR scope and protects the active path; historical/null rows are still possible because PostgreSQL unique constraints treat nulls as distinct.
- Assumes migration 021 is applied after the rollout pre-check for exact duplicates.

### Recommended Tests / Validation

- Already run focused concurrency, project repository, project ingest route, migration runner, ruff, compileall, and diff whitespace checks.
- Keep the rollout monitor focused on project upsert `IntegrityError` logs and status-event duplicate counts.

### Rollout Notes

- Apply `021_project_status_events_dedup.sql` during the PR-04 maintenance window.
- Roll back by reverting application code and dropping `project_status_events_project_status_observed_uq` only if post-deploy status-event inserts fail unexpectedly.
