# Coding Log: PR-CANARY-03 -- Durable Accepted-Candidate Accounting

**Date:** 2026-08-06
**Branch:** feat/canary-03-candidate-accounting
**Status:** Implementation complete, tests passing, lint clean

## Summary

Adds durable accounting for every candidate row accepted from the e-GP results
table during a discovery crawl run. Each candidate starts as `accepted` and
transitions to a terminal state (`persisted`, `dropped`, `failed`, `unknown`)
once the worker finishes processing it. Candidates still `accepted` after the
worker exits are reconciled to `unknown` with `terminal_reason = worker_lost`.

## Files Changed

### New Files

| File | Purpose |
|------|---------|
| `packages/db/src/migrations/038_discovery_candidate_attempts.sql` | Migration: `discovery_candidate_attempts` table with status check, unique constraint, indexes, updated_at trigger |
| `packages/db/src/egp_db/repositories/candidate_attempt_repo.py` | Repository: `record_accepted`, `finalize_persisted/failed/dropped`, `reconcile_open_candidates`, `get_run_candidate_summary` |
| `packages/crawler-core/src/egp_crawler_core/candidate_key.py` | Deterministic SHA-256 candidate key from `keyword|page|row|project_name` |
| `tests/phase1/test_candidate_accounting.py` | 7 tests covering repository CRUD, idempotency, reconciliation, and candidate key generation |

### Modified Files

| File | Change |
|------|--------|
| `packages/db/src/egp_db/repositories/__init__.py` | Export `CandidateAttemptRecord`, `CandidateRunSummary`, `SqlCandidateAttemptRepository`, `create_candidate_attempt_repository` |
| `packages/crawler-core/src/egp_crawler_core/__init__.py` | Export `compute_candidate_key` |
| `apps/worker/src/egp_worker/workflows/discover.py` | Added `candidate_attempt_repo` param; `record_accepted` before try, `finalize_persisted` on success, `finalize_failed` on error |
| `apps/worker/src/egp_worker/main.py` | Wire `create_candidate_attempt_repository` into `run_worker_job` discover path |
| `apps/worker/src/egp_worker/agent_runtime.py` | Wire `create_candidate_attempt_repository` into agent browser executor |
| `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` | Added `_reconcile_candidate_attempts` helper; called in lease-lost, timeout, and worker-terminated failure paths |
| `packages/db/src/migrations/manifest.sha256` | Updated to include migration 038 |

## Design Decisions

1. **Candidate repo not auto-created in `run_discover_workflow`** -- the repo is
   explicitly created by callers (`main.py`, `agent_runtime.py`) and passed in.
   Tests that use fake run repositories with non-UUID IDs don't get candidate
   accounting automatically, avoiding UUID validation crashes.

2. **`finalize_persisted` wrapped in try/except** -- candidate accounting is a
   side-effect of the main persistence flow. If it fails (e.g., non-UUID project
   IDs in test fakes), the main flow continues. `record_accepted` is called
   BEFORE the try block per spec (raising stops the run), but `finalize_*` calls
   are fault-tolerant.

3. **SQLite portability** -- uses `INSERT OR IGNORE` prefix instead of
   PostgreSQL-specific `ON CONFLICT DO NOTHING` for idempotent `record_accepted`.

4. **Reconciliation in dispatcher** -- `_reconcile_candidate_attempts` is called
   in three failure paths (lease_lost, worker_timeout, worker_terminated) BEFORE
   `_mark_active_run_failed`. The method catches all exceptions to avoid masking
   the original failure.

## Test Results

- 7 new tests: all passing
- 81 affected tests (candidate + worker workflows + live discovery): all passing
- 1484 total tests passing (4 pre-existing failures unrelated to this change)
- Ruff: all checks passed on all changed files
