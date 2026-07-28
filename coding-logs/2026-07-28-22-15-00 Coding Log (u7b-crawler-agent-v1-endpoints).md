# Coding Log — U7b: crawler-agent V1 claim/renew/result endpoints

**Date:** 2026-07-28
**Worktree:** `/Users/subhajlimanond/dev/egp-u7b2`
**Branch:** `feat/crawler-agent-v1-endpoints` from `origin/main @ 486a33bc`
**Lifecycle:** g2 (`g2-planning` → `g2-coding` → `g2-qcheck`)

## Scope

The V1 crawler-agent contract made real but inert: claim / renew / result
repository, service, and authenticated endpoints that return 404 while
`EGP_CRAWLER_AGENT_PROTOCOL=off` (the default, landed in #187).

Out of scope: the inbox processor (U7c), agent client and shadow canary (U8),
scoped artifact upload (U9).

## Design corrections forced by the plan review

The first design was rejected. Three corrections are load-bearing and are
documented in the module docstrings so they cannot be "simplified" away:

1. **Replay lookup comes first.** Accepting a result moves the job to the
   non-claimable `result_received` state and clears its claim, so a replay can no
   longer satisfy a `WHERE job_status='pending' AND claim_token=…` guard — the
   first submission already invalidated it. `record_result_envelope` therefore
   consults the inbox **before** attempting the transition.
2. **One connection, one transaction.** A shared `Engine` is not a shared
   transaction; two sequential repository calls would give two, and a crash
   between them would strand the job in `result_received` with no result to apply.
   The transition and the insert execute on a single connection.
3. **SAVEPOINT around the insert.** A UNIQUE violation aborts the enclosing
   PostgreSQL transaction, so "catch IntegrityError then SELECT" cannot recover.
   `begin_nested()` is used, mirroring `document_persistence.py`.
4. **The protocol gate is a router dependency**, so a disabled endpoint answers
   404 before FastAPI validates the body — otherwise a malformed body against a
   disabled feature would return 422 and reveal the payload shape.

## Implementation bug caught by its own test

The first cut of the replay path returned the existing inbox row **without
comparing the envelope fingerprint**, so a conflicting body would have been
reported as a successful replay instead of a 409.
`test_same_claim_different_body_conflicts` failed with `DID NOT RAISE
IdempotencyConflictError`. Fixed to compare `envelope_sha256` before returning.

## TDD note (honest)

The repository was written **before** its tests (seam-first), so this layer has no
RED. Non-vacuity was established by **mutation instead**: removing the
replay-first lookup — i.e. reverting to the rejected design — fails exactly
`test_identical_replay_returns_the_original_row` and
`test_same_claim_different_body_conflicts`, and nothing else. The endpoint layer
did produce a genuine RED: the route-inventory oracle failed the moment the three
routes were registered, before they were added to `INTERNAL_ROUTE_CASES`.

## Non-vacuous endpoint evidence

The existing auth matrix accepts any allow-listed status and already treats 404 as
a valid authenticated result, so a permanently-404 endpoint would satisfy both it
and the route inventory. `tests/phase3/test_crawler_agent_endpoints.py` is the
compensating evidence: it turns the protocol on and drives
claim → renew → result → replay → conflict end to end against real PostgreSQL.

## QCHECK

**Tier 2 first attempt was a FALSE NEGATIVE.** Codex returned 9 lines saying its
`g-check` workflow was blocked because `.codex/coding-log.current` was missing from
this worktree — it never reviewed anything. Caught by `g2-qcheck`'s errored-reviewer
rule ("0 findings with an errored reviewer is not a pass"). The pointer was created
and the review re-run.

**Tier 2 (re-run) verdict: "correctness is refuted."** Dispositions:

| # | Finding | Sev | Disposition |
|---|---|---|---|
| Q1 | **Concurrent replay returns stale instead of replay.** Two identical deliveries can both miss the initial inbox lookup; one wins the transition and commits, the other blocks on the row lock, gets zero updated rows and raises stale. | HIGH | **FIXED.** A zero-row transition now re-reads the inbox: matching digest ⇒ replay, differing ⇒ conflict, absent ⇒ genuinely stale. |
| Q2 | **The global worker token has effective all-tenant authority.** Any holder can drain work for every tenant; `agent_id` is accepted but never persisted or bound to the lease. | HIGH | **ACCEPTED AS AN EXPLICIT RELEASE DECISION, not fixed here.** This is a pre-existing property of every `/internal/worker/*` route — `project_ingest` is strictly worse, trusting a body-supplied `tenant_id` outright. U7b *improves* on it by deriving tenant from the claimed row. Real remediation is per-agent credentials / mTLS and DB-enforced tenancy, i.e. U8 and U10–U12. Binding `agent_id` to the lease needs a migration and is recorded as U8 work. |
| Q3 | The architecture test I opted into would fail: the factory lacks `bootstrap_schema`. | MEDIUM | **FIXED** — and found independently by the 3× gate before the review was read. `bootstrap_schema: bool = False` added to repository and factory, wired through the bundle. |
| Q4 | Generated OpenAPI declared only 200/422 while runtime returns 201/204/409. | MEDIUM | **FIXED.** Explicit `responses={...}` on all three routes; schema and TS regenerated. |
| Q5 | Claim TOCTOU is safe but lossy — with two agents and two jobs both may pick the same candidate and the loser reports "no work". | MEDIUM | **FIXED.** Bounded retry skips a contended row and tries the next; test asserts two agents get two different jobs. |
| Q6 | The parity test compares only column names, so the SQLAlchemy table can omit constraints PostgreSQL enforces. | LOW | **PARTIALLY FIXED.** The error-code CHECK is now mirrored onto the table. Composite-FK and index parity remain unmodelled on the SQLite side; recorded rather than silently ignored. |

Codex also confirmed: no double-write or state corruption; no legacy-executor
regression; wiring (bundle, `app.state`, router, barrels) reachable and complete.

Its pytest could not run (read-only sandbox has no writable temp dir), so its
analysis is static; all execution evidence here is local.

### A vacuous test caught by mutation

My first test for Q1 passed *both* with and without the fix — the step-1 lookup
catches a serial replay before the zero-row branch is ever reached, so it proved
nothing. Rewritten to force the first lookup to miss (exactly as a concurrent
snapshot would) and assert the branch is entered; re-mutation now fails precisely
that test.

## Gates (local only — CI dead, E0)

| Gate | Result |
|---|---|
| ruff | clean |
| pytest **3× consecutive** | **1307 / 1307 / 1307 passed**, 2 skipped, 0 failed |
| baseline `main@486a33bc` | 1282 passed, 2 skipped |
| `tsc --noEmit` | clean |
| `eslint --max-warnings=0` | clean |
| `npm run check:api-types` | current (3 new paths + declared status codes) |

Net new tests: 25 (14 repository-contract, 6 endpoint, 1 column-parity, plus the
3 auth-matrix rows).
