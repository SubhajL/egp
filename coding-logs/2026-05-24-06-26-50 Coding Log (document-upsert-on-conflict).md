# Coding Log: document-upsert-on-conflict

## Plan Draft A

### Overview
Make document metadata persistence idempotent under duplicate concurrent inserts. Keep blob storage cleanup conservative so only storage keys not referenced by the winning database row are deleted.

### Files To Change
- `packages/db/src/egp_db/repositories/document_persistence.py`: replace the insert race with dialect `ON CONFLICT` handling and conflict cleanup.
- `tests/concurrency/test_document_upsert_concurrent.py`: add a concurrent duplicate store test against SQLite metadata plus local blob storage.
- `packages/observability/src/egp_observability/metrics.py` and `packages/observability/src/egp_metrics.py`: expose a low-cardinality document conflict recording helper if instrumentation is needed.

### Implementation Steps
1. Add a failing concurrency test with three threads storing the same `(tenant_id, project_id, sha256, document_type, document_phase)`.
2. Run the new test and confirm current code raises or leaves extra blobs.
3. Add a local `_dialect_insert()` helper mirroring the project upsert pattern.
4. Insert document metadata with `ON CONFLICT DO NOTHING` for PostgreSQL/SQLite, then select the canonical row by the unique key.
5. If the insert lost the race, return `created=False`, do not create diffs/reviews, and delete only blob keys not equal to the persisted row's primary or managed backup keys.
6. Add optional conflict metric recording using existing `egp_document_upsert_conflicts_total{outcome=...}`.
7. Run focused tests, ruff, compileall, and review gates.

### Test Coverage
- `test_concurrent_document_upsert_is_idempotent`: duplicate concurrent stores yield one row and no orphan blobs.
- Existing document persistence tests: duplicate replay, superseding, diff, review, and backup behavior still pass.

### Decision Completeness
- Goal: make duplicate document persistence concurrency-safe and blob-clean.
- Non-goals: no schema migration, no API contract changes, no behavior changes for non-duplicate document versions.
- Success criteria: three concurrent stores of identical document content return one document id, one database row, one retained blob, and no exceptions.
- Public interfaces: no new DB schema; optional metric helper uses existing `egp_document_upsert_conflicts_total` labels.
- Edge cases: if conflict row already points to the just-written key, do not delete it; if conflict row points elsewhere, cleanup the losing blob; if non-conflict write failure occurs, existing cleanup path still deletes written blobs and re-raises.
- Rollout: no feature flag; deploy as DB integrity fix; watch document conflict counter and blob/DB drift.
- Acceptance checks: focused pytest, repeated concurrency test, ruff, compileall.

### Dependencies
SQLAlchemy dialect insert support for PostgreSQL and SQLite is already present through SQLAlchemy 2.x.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| document conflict insert helper | `SqlDocumentRepository.store_document()` | `SqlDocumentRepository` mixin composition in `document_repo.py` | `documents(tenant_id, project_id, sha256, document_type, document_phase)` |
| concurrency test | pytest | test discovery under `tests/concurrency` | `documents` |
| metric helper | `store_document()` conflict branch | import from `egp_observability.metrics` | existing `egp_document_upsert_conflicts_total` |

## Plan Draft B

### Overview
Use `ON CONFLICT DO UPDATE` as a no-op update with `RETURNING` to fetch the canonical row in one round trip. This minimizes select logic but mutates the winning row on every replay.

### Files To Change
- `packages/db/src/egp_db/repositories/document_persistence.py`: use dialect upsert with `RETURNING`.
- `tests/concurrency/test_document_upsert_concurrent.py`: same concurrency regression coverage.

### Implementation Steps
1. Add the failing concurrency test.
2. Replace plain insert with dialect upsert keyed on the existing document uniqueness constraint.
3. Use returned row to determine whether the caller created a new row or hit an existing row.
4. Cleanup losing blobs when returned row id differs from the candidate document id.
5. Run gates.

### Test Coverage
- `test_concurrent_document_upsert_is_idempotent`: duplicate concurrent stores collapse to one row.
- Existing persistence tests verify non-duplicate version behavior.

### Decision Completeness
- Goal: one DB row and no unhandled IntegrityError during duplicate document races.
- Non-goals: no migration, no domain classifier changes.
- Success criteria: no exceptions and no extra artifacts after concurrent duplicate stores.
- Public interfaces: none.
- Edge cases: no-op update could still bump row MVCC metadata; cleanup must not delete canonical storage.
- Rollout: no flag; monitor existing document conflict metric.
- Acceptance checks: focused test repeated three times, full document persistence test, ruff, compileall.

### Dependencies
Requires reliable `RETURNING` behavior across supported SQLite and PostgreSQL dialects.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| document upsert | `SqlDocumentRepository.store_document()` | mixin composition in `document_repo.py` | `documents` unique key |
| test | pytest | test discovery | `documents` |

## Comparative Analysis
Draft A avoids mutating the winning document row during replay and works without depending on dialect `RETURNING` behavior. Draft B is more compact but performs a no-op update on conflicts and could make duplicate replays look like writes at the database layer. Draft A better preserves "never overwrite, always supersede" semantics and gives explicit cleanup control.

## Unified Execution Plan

### Overview
Implement Draft A: use `ON CONFLICT DO NOTHING` plus a canonical select, then return the existing row for duplicate races. Cleanup only storage keys that are not referenced by the canonical document row.

### Files To Change
- `packages/db/src/egp_db/repositories/document_persistence.py`: add dialect insert helper, conflict branch, cleanup helper, and metric/log records.
- `tests/concurrency/test_document_upsert_concurrent.py`: add race harness and assertions.
- `packages/observability/src/egp_observability/metrics.py`: add `record_document_upsert_conflict(outcome)`.
- `packages/observability/src/egp_metrics.py`: re-export the helper.

### TDD Sequence
1. Add `test_concurrent_document_upsert_is_idempotent`.
2. Run `./.venv/bin/python -m pytest tests/concurrency/test_document_upsert_concurrent.py -q` and confirm RED.
3. Implement minimal document persistence upsert/cleanup.
4. Run the new test until GREEN.
5. Run `tests/phase1/test_document_persistence.py`, repeated concurrency test, ruff, compileall.

### Function Details
- `_dialect_insert(table, connection)`: return PostgreSQL or SQLite insert builders when available, plain insert otherwise.
- `_insert_document_metadata(...)`: execute conflict-aware metadata insert and return the persisted row plus whether it was created.
- `_cleanup_unreferenced_blob_writes(...)`: delete written blob keys that are not referenced by the canonical row.
- `record_document_upsert_conflict(outcome)`: increment existing low-cardinality document conflict counter.

### Test Coverage
- `test_concurrent_document_upsert_is_idempotent`: three duplicate threads collapse to one document.
- Existing `test_store_document_dedupes_same_project_and_hash`: sequential duplicate replay still returns `created=False`.
- Existing backup cleanup tests: non-conflict write failures still cleanup.

### Decision Completeness
- Goal: idempotent duplicate document upsert with no orphan blobs.
- Non-goals: no migration, no API/UI change, no new labels beyond `outcome`.
- Success criteria: exact duplicate races produce one row, one canonical artifact, no exception, and `created=False` for losing callers.
- Public interfaces: no DB/API/env changes; metric helper records existing `egp_document_upsert_conflicts_total`.
- Edge cases/failure modes: fail closed on unexpected DB/storage errors by cleanup and re-raise; duplicate conflicts fail open to idempotent existing-row return; cleanup skips canonical storage keys.
- Rollout/monitoring: deploy as unflagged DB fix; monitor document IntegrityError rate, blob/DB drift, and `egp_document_upsert_conflicts_total{outcome="resolved"}`.
- Acceptance checks: `pytest tests/concurrency/test_document_upsert_concurrent.py -q`, `pytest tests/phase1/test_document_persistence.py -q`, `ruff check` on changed Python files, and `python -m compileall packages/db/src packages/observability/src`.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| document upsert | `SqlDocumentRepository.store_document()` | `DocumentPersistenceMixin` inherited by `SqlDocumentRepository` | `documents_project_hash_class_phase_uq` |
| conflict metric | duplicate conflict branch in `store_document()` | imported from `egp_observability.metrics` | `egp_document_upsert_conflicts_total` |
| concurrency test | pytest | `tests/concurrency/test_document_upsert_concurrent.py` | `documents` unique key |

### Cross-Language Schema Verification
Direct inspection found the SQL migration unique index and SQLAlchemy table agree on `tenant_id`, `project_id`, `sha256`, `document_type`, and `document_phase`. No frontend or API schema changes are involved.

## Implementation Summary (2026-05-24 06:34:55 +07)

### Goal
Implement PR-05: make document persistence idempotent for duplicate concurrent document stores and clean losing blob writes.

### What Changed
- `packages/db/src/egp_db/repositories/document_persistence.py`: added dialect-aware `ON CONFLICT DO NOTHING`, canonical row selection, safe cleanup of unreferenced blob writes, and conflict logging/metrics.
- `tests/concurrency/test_document_upsert_concurrent.py`: added a three-thread race harness that forces the old pre-check/insert race.
- `packages/observability/src/egp_observability/metrics.py`, `packages/observability/src/egp_observability/__init__.py`, and `packages/observability/src/egp_metrics.py`: exposed `record_document_upsert_conflict()` for the existing rollout metric.
- `tests/phase2/test_observability_metrics.py`: asserted `egp_document_upsert_conflicts_total{outcome="resolved"}` records.

### TDD Evidence
- RED: `PYTHONPATH=apps/api/src:apps/worker/src:packages/observability/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/db/src:packages/notification-core/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/concurrency/test_document_upsert_concurrent.py -q` failed with `sqlite3.IntegrityError: UNIQUE constraint failed: documents.tenant_id, documents.project_id, documents.sha256, documents.document_type, documents.document_phase`.
- GREEN: same command passed with `1 passed in 0.33s` after the upsert/cleanup implementation.

### Tests Run
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/observability/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/db/src:packages/notification-core/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/concurrency/test_document_upsert_concurrent.py tests/phase1/test_document_persistence.py tests/phase2/test_observability_metrics.py -q` -> `33 passed`.
- `PYTHONPATH=apps/api/src:apps/worker/src:packages/observability/src:packages/shared-types/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/db/src:packages/notification-core/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/concurrency/test_document_upsert_concurrent.py -q` -> passed three consecutive single-test runs.
- `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check packages/db/src/egp_db/repositories/document_persistence.py packages/observability/src/egp_observability/__init__.py packages/observability/src/egp_observability/metrics.py packages/observability/src/egp_metrics.py tests/concurrency/test_document_upsert_concurrent.py tests/phase2/test_observability_metrics.py` -> passed.
- `/Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall packages/db/src packages/observability/src` -> passed.

### Wiring Verification
- `SqlDocumentRepository` inherits `DocumentPersistenceMixin`, so `store_document()` is the runtime entry point for the new insert path.
- `rg` verified schema alignment for `documents_project_hash_class_phase_uq` in `packages/db/src/migrations/002_document_tenant_scope.sql` and `packages/db/src/egp_db/repositories/document_schema.py`.
- The conflict metric uses existing `egp_document_upsert_conflicts_total` and is exported through both observability package entry points.

### Behavior And Risk Notes
- Duplicate conflicts return `created=False` with the canonical document and do not create duplicate diffs or reviews.
- Cleanup skips primary and backup storage keys referenced by the canonical row, including encoded external-provider keys.
- Unexpected storage or DB failures still use the existing fail-closed cleanup/re-raise path.

### Follow-Ups / Known Gaps
- No migration was added because the unique document key already exists in migrations and SQLAlchemy metadata.

## Review (2026-05-24 06:35:57 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-pr05`
- Branch: `fix/document-upsert-on-conflict`
- Scope: staged working tree against `484b911d`
- Commands Run: Auggie review retrieval attempted and returned HTTP 429; `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; staged targeted diffs for `document_persistence.py`, observability metrics, and the concurrency test; focused pytest, ruff, compileall commands listed above.

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
- Assumes PostgreSQL and SQLite remain the supported repository dialects for this path; both support the dialect `on_conflict_do_nothing` API used here.

### Recommended Tests / Validation
- Already run: focused persistence/observability suites, three consecutive concurrency single-test runs, scoped ruff, and compileall.
- Remote CI should still run the broader repo gates before merge.

### Rollout Notes
- No feature flag or migration. Watch `egp_document_upsert_conflicts_total{outcome="resolved"}`, document IntegrityError logs, and blob/DB drift after deploy.
