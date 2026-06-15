# Coding Log: ws3-capture-backfill-retries (2026-06-15)

WS3 backend core ("Document-capture / backfill refinements") from the
discovery-completeness unified plan (§4 WS3). Chosen as the optimal next code
workstream: WS5 is an ops re-scan (not a code PR), WS4's alerts are gated on the
Track-C Prometheus gap (#154); WS3 is unblocked, cohesive with WS2, high-value.

## What changed
- **arch#3** — `DocumentCaptureReason` StrEnum (shared-types); `record_attempt` accepts
  it; the enqueuer + worker (`discover.py`) record structured reason codes instead of
  free-text. Raw exception strings are no longer stored as `reason` (cardinality).
  Column stays `TEXT` — **no migration**.
- **P1a** — `list_due_backfill_candidates` retry cap counts only TERMINAL `failed`/`timeout`
  (`transient_count`); `enqueued`/`skipped`/`succeeded` don't count. A fresh `enqueued`
  throttles re-enqueue until a 3h stale horizon; a later terminal supersedes it.
- **P1b** — domain-aware retry: `no_documents` = daily heartbeat (24h) until the proposal
  deadline / 30-day cap from the first no_documents; `failed`/`timeout` = exponential
  backoff + count cap. Branch chosen by the truly-newest terminal attempt.
- Tunable knobs (`enqueued_stale_after_seconds=10800`, `no_documents_retry_seconds=86400`,
  `no_documents_max_age_days=30`) threaded through the repo, the enqueuer fn, and CLI flags.

## Design
- Deterministic exclusions (throttle, transient-cap exhaustion, no_documents-30d
  exhaustion) are pushed into **SQL** (`not_()` predicates) so the bounded `limit*5`
  prefetch is never starved by ineligible rows; only the time-cadence runs in Python on
  rows that sort last. True "latest terminal" via `case(...)` (NOT `coalesce`, which
  mis-orders old-transient+fresh-no_documents). Portable across SQLite + PostgreSQL.
- `list_due_backfill_candidates` stays backward-compatible (new keyword-only params).

## Verification
- TDD; full sweep **1055 passed, 0 failed**; 3× zero flakiness; `ruff` clean; wiring verified.
- **QCHECK (Codex gpt-5.5 xhigh) — 3 rounds**:
  - R1 BLOCK: HIGH (prefetch page-before-filter), MEDIUM-1 (transient cap counted
    no_documents), MEDIUM-2 (CLI knobs). 
  - R2 BLOCK: MEDIUM-1/2 resolved; HIGH (coalesce ≠ true latest → starvation) — Codex
    reproduced it.
  - R3 **SHIP**: 0 findings; `case()` confirmed portable.
  Each fix shipped with a regression test (enqueued-flood, old-transient+fresh-no_doc
  flood, mixed-history-not-exhausted, terminal-cap, cadence/30d).
- Manual QCHECK task list for a local Codex session:
  `coding-logs/2026-06-15-12-04-17 WS3 QCHECK Tasks (capture-backfill-retries).md`.

## Behavior-change note (ops)
`no_documents` projects now retry daily for up to 30 days (was: stop after 3 attempts) —
product-decided (plan §2 decision 4). Bounded by the enqueuer `limit`, the e-GP rate
limiter, and the tunable knobs. Watch backfill crawl volume after deploy.

## Follow-ups (not in this PR)
- P1c (terminal UI "ไม่พบเอกสารหลังตรวจซ้ำ" state), P2a (fingerprint-only fallback),
  P2b (profile-attribution) per plan §4 WS3.
- WS5 (prod re-scan repair), WS4 (fleet alerts; gated on #154).
