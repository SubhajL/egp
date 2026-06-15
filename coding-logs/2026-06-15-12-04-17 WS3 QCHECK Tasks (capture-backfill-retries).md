# WS3 QCHECK Tasks — document-capture backfill retries (2026-06-15)

For a **local manual Codex session**. Branch: `feat/ws3-capture-backfill-retries`
(PR pending). Run each task against the diff vs `origin/main`; mark CRITICAL/HIGH/
MEDIUM/LOW. Automated Codex QCHECK already ran 3 rounds (final: SHIP, 0 findings);
this list is for an independent human-driven pass.

Scope: `packages/db/.../document_capture_attempt_repo.py`,
`packages/shared-types/.../enums.py`,
`apps/api/.../executors/document_backfill_enqueue.py`,
`apps/worker/.../workflows/discover.py` + tests.

## Correctness — candidate selection (`list_due_backfill_candidates`)
1. **Terminal-only cap (P1a).** Confirm `enqueued`/`skipped`/`succeeded` never count
   toward `max_attempts`; only `failed`/`timeout` feed `transient_count`. Verify a
   project enqueued N>cap times (no terminal) is still selectable.
2. **Stale-enqueued throttle.** Confirm a fresh `enqueued` (< `enqueued_stale_after_seconds`,
   3h) excludes the row in SQL, and one past the horizon does not; and that a later
   terminal supersedes the throttle. Check the SQL predicate's NULL handling
   (`transient_latest`/`no_doc_latest` NULL branches).
3. **Domain-aware cadence (P1b).** `no_documents` → retry once per `no_documents_retry_seconds`
   (24h), stop after the proposal deadline (SQL `proposal >= now`) or
   `no_documents_max_age_days` (30d from FIRST no_documents). `failed`/`timeout` →
   exponential backoff + count cap. Verify the branch is chosen by the **truly newest**
   terminal (the `case(...)` `latest_terminal_expr`, NOT `coalesce`), ties → transient.
4. **Prefetch starvation.** The bounded `limit * 5` prefetch + Python cadence filter:
   confirm throttled/exhausted rows are excluded in SQL (so they can't fill the window)
   and that not-yet-due rows sort LAST via `latest_terminal_expr`. Try to construct a
   flood that still starves a due row (e.g., many not-yet-due rows with a recent terminal
   that nonetheless sorts before a due row) — is `limit * 5` always sufficient, or should
   it page until `limit` due collected?
5. **Tie semantics.** SQL uses `transient_latest >= no_doc_latest` (tie→transient);
   Python uses `no_doc_latest > transient_latest` for `latest_is_no_doc`. Confirm these
   agree on the exact-equal-timestamp edge and that mixed histories can't double-count.
6. **`max(terminal_times)` in Python** vs the SQL `case` — confirm they pick the same row
   in all None/equal combinations.

## SQL portability & schema
7. `not_()`, `case()`, `func.coalesce`, window `row_number` (profiles) — confirm identical
   results on **SQLite (tests) and PostgreSQL (prod)**, especially `NOT (NULL-bearing AND/OR)`
   truth tables and timestamp tz comparisons (naive vs aware via `_aware_datetime`).
8. No migration: `reason` stays `TEXT`. Confirm no schema change is required and the
   `status` CHECK constraint is untouched.

## arch#3 — structured reasons
9. Confirm raw exception strings are NEVER stored as `reason` (cardinality) — `failed_error`
   maps to `DocumentCaptureReason.FAILED`. Spot-check every `record_attempt(reason=...)` call
   site (enqueuer, worker discover.py both paths) uses an enum value.
10. UI/API: `reason` is passed through; web branches on `status`, not `reason`
    (`apps/web/.../projects/[id]/page.tsx`). Confirm changing reason strings doesn't break
    the capture-status empty-state UI.

## Ops / behavior-change risk
11. **Crawl-volume**: `no_documents` now retries daily for up to 30 days (was: stop after 3
    attempts). Estimate worst-case backfill job volume vs the e-GP rate limiter + Track-C
    single-Mac throughput. Are the defaults (24h / 30d / 3h) safe? They're tunable via the
    new CLI flags + `enqueue_document_backfill_jobs` params.
12. Backward-compat: `list_due_backfill_candidates` new params are keyword-only with
    defaults — confirm all existing callers/tests are unaffected.

## Tests
13. Verify the regression tests actually fail on the pre-fix code (terminal-cap,
    stale-enqueued, no_documents cadence/30d, transient backoff, enqueued-flood starvation,
    old-transient+fresh-no-doc starvation, mixed-history-not-exhausted, reason-enum).
