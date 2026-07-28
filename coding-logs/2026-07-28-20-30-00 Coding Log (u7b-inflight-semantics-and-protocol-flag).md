# Coding Log — U7b prerequisite: in-flight semantics + protocol flag

**Date:** 2026-07-28
**Worktree:** `/Users/subhajlimanond/dev/egp-u7b`
**Branch:** `feat/crawler-agent-contract-api` from `origin/main @ 77dc9a55` (post-U7a)
**Lifecycle:** g2 (`g2-planning` → `g2-coding` → `g2-qcheck`)

## Scope

The blocking prerequisite Codex identified during U7a review (finding Q2-4), plus the
`EGP_CRAWLER_AGENT_PROTOCOL` flag. Ships **inert**: nothing can set `result_received` yet
and the flag defaults to `off`.

## Codex adversarial plan review (gpt-5.6-sol, xhigh) — verdict: REJECT

Two findings changed this PR; the rest apply to the still-unlanded contract layer and are
carried forward.

| # | Finding | Disposition |
|---|---|---|
| P1 | The in-flight inventory was incomplete. | **ACCEPTED.** I had planned 4 sites; my own exhaustive `job_status` grep found 8 *before* Codex returned, and Codex independently confirmed the same extra paths (`rules_service` ×2, `create_pending_discovery_job_if_absent`, SOC runbook). All 8 fixed via one shared definition. |
| P2 | **Do not widen `count_pending_discovery_jobs` in place** — it feeds `queued_keyword_count`, compared against `max_queued_keywords`, which is a queue-*depth* cap. `result_received` is unfinished but no longer queued. | **ACCEPTED — reverted work already on this branch.** I had widened it, mis-reading the cap as a concurrency budget; concurrency is separately `inflight_run_count >= max_concurrent_runs` (`entitlement_service.py:293`). Restored to pending-only with a comment explaining why, and the test now asserts the pending-only behaviour so it cannot drift. Admission semantics for in-flight-but-unapplied work is a deliberate U8 decision. |
| P3 | FN3's replay path is self-contradictory: the first submission moves the job to `result_received` and clears the claim, so an identical replay fails the `WHERE job_status='pending' AND claim_token=…` guard before reaching the inbox uniqueness check. | **ACCEPTED — carried to the contract-layer PR.** Redesign: look the inbox row up **first** by `(tenant_id, job_id, claim_token)`; matching SHA ⇒ return it, differing SHA ⇒ 409; only when absent do the atomic UPDATE+INSERT. |
| P4 | "Catch UNIQUE then SELECT" is invalid in PostgreSQL — the transaction aborts. | **ACCEPTED — carried.** Use `begin_nested()` (the idiom already in `document_persistence.py:92`) or `ON CONFLICT`. Independently corroborated: my own U7a test hit exactly this (`InFailedSqlTransaction`). |
| P5 | A shared `Engine` is not a shared transaction — sequential repository calls each open their own. | **ACCEPTED — carried.** Atomicity requires the new repository to execute both statements on **one connection**. My earlier "single transaction is feasible" note was right about the engine but sloppy about the mechanism. |
| P6 | R14 (idempotent effects) is false for the existing services: project upsert then notify, run creation in its own transaction, document storage writing to object storage, audit separately, notifications creating UUIDs + email + webhook enqueue. | **ACCEPTED — carried to U7c.** Needs an effect ledger / transactional outbox; "single transaction" is not achievable across object storage and email. |
| P7 | **U7c cannot ingest documents from descriptors alone** — document ingestion requires the actual `file_bytes` and scoped artifact upload is U9. | **ACCEPTED — U7c must be re-scoped.** Either narrow it to project/status envelopes and reject document envelopes as unsupported-until-U9, or defer U7c. |
| P8 | No production path creates `execution_backend='agent'` jobs, so the endpoints can be "enabled" and still claim nothing. | **ACCEPTED — recorded.** Routing is a U8 decision; harmless while dark. |
| P9 | `off\|shadow\|primary` is underspecified — the database only has `legacy\|agent`, so `shadow` and `primary` are operationally identical today. | **ACCEPTED — recorded.** The three values ship per spec; distinct behaviour is defined in U8 when there is a shadow path to compare. |
| P10 | 404-when-off has a precedence problem: FastAPI body validation can return 422 before a service-level gate. | **ACCEPTED — carried.** The off-gate must live in a dependency that runs before handler/body work. |

## Changes

| File | Change |
|---|---|
| `packages/shared-types/.../enums.py` | `IN_FLIGHT_DISCOVERY_JOB_STATUSES` + `..._VALUES` — one definition for all 8 sites |
| `packages/db/.../discovery_job_repo.py` | site 6 dedupe widened; `count_pending_discovery_jobs` explicitly kept pending-only |
| `packages/db/.../recrawl_request_repo.py` | `_resolve_job_state` maps `result_received` → `running`; both conflict selects widened |
| `apps/api/.../rules_service.py` | `pending_job_keys` + `active_request_ids` widened |
| `scripts/requeue_failed_discovery_runs.py` | conflict select widened |
| `docs/SOC_INCIDENT_RESPONSE.md` | manual backfill dedupe widened; `execution_backend` spelled out |
| `apps/api/.../config.py` | `CrawlerAgentProtocol` + `get_crawler_agent_protocol` (default `off`) |
| `deploy/.env.production.example` | `EGP_CRAWLER_AGENT_PROTOCOL=off` (required by the AST drift test) |
| `tests/phase3/test_crawler_agent_inflight_semantics.py` | 8 tests |

## TDD evidence

RED: `ImportError: cannot import name 'IN_FLIGHT_DISCOVERY_JOB_STATUSES'`, then for the
enqueue-dedupe site `assert True is False` — a duplicate job really was created.
GREEN: 8/8.

## Gates (local only — CI dead, E0)

| Gate | Result |
|---|---|
| ruff | clean |
| pytest **3× consecutive** | **1282 / 1282 / 1282 passed**, 2 skipped, 0 failed |
| baseline `main@77dc9a55` | 1274 passed, 2 skipped |
| env-template drift test | green (the flag's oracle) |
| OpenAPI | unchanged; no `apps/web` files touched |

## Remaining for U7

- **U7b contract layer** — repo/service/endpoints, with the P3/P4/P5/P10 corrections.
- **U7c** — blocked on P7 (documents need U9's artifact transport) and P6 (effect ledger).
  Must be re-scoped before implementation.
