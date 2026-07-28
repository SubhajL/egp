# Coding Log — U7 `feat/crawler-agent-contract`

**Started:** 2026-07-28
**Worktree:** `/Users/subhajlimanond/dev/egp-u7`
**Branch:** `feat/crawler-agent-contract` from exact `origin/main` @ `ff1ead3a`
**Lifecycle:** g2 (`g2-planning` → `g2-coding` → `g2-qcheck` → `g2-check`)

## Scope

U7 per `egp-dev-logs.md:4117-4148` (Path B — start U7 while GitHub billing E0 remains
blocked): migration `034`, versioned V1 claim/renew/artifact/result contracts,
authenticated dark API endpoints, durable idempotent result inbox, external result
processor reusing existing project/document/run services,
`EGP_CRAWLER_AGENT_PROTOCOL=off|shadow|primary` (default `off`), OpenAPI + generated
TypeScript updates.

**Explicitly out of scope (belongs to U8):** Mac agent client, dual-report shadow
comparison, one-profile primary canary.

## Preconditions verified (2026-07-28)

| Check | Result |
|---|---|
| `HEAD == origin/main` | `ff1ead3a` both |
| Primary worktree dirty paths preserved | 3 paths untouched (2 coding logs + `docs/TOR KEYWORDS.md`) |
| Next migration prefix | **034** (033 is max) |
| Migration manifest baseline | verified, 35 files |
| Ruff baseline | clean |
| Test collection | 1250 tests |
| **Full local pytest baseline @ `ff1ead3a`** | **1248 passed, 2 skipped, 0 failed (178.43s)** |
| Worktree venv isolation | points at `egp-u7` sources, not primary |
| Real Postgres available for integration tests | yes — `/opt/homebrew/bin/{postgres,initdb,pg_ctl,psql}` + `egp_db.dev_postgres`; Docker also up |

Baseline matters more than usual here: with CI dead (E0), this local run is the only
evidence that `main` was green before U7, so any later failure is attributable to U7.

### E0 / CI status — material to how this lands

GitHub Actions **cannot run**: all 7 required jobs on `main @ ff1ead3a` fail with **no
logs at all** (`log not found`), i.e. the jobs never started. This is the E0 billing
block, not test failures.

Branch protection on `main`:
- `required_status_checks`: Python Lint & Format, Frontend Lint & Typecheck, Python
  Tests, Frontend Build, Database Migrations, Build Docker Images
- `required_pull_request_reviews`: **true**
- `enforce_admins`: **false**

Consequences carried through this PR:
1. Required checks can never go green while E0 holds → **admin merge is mandatory**,
   not a convenience. Explicitly authorized by the operator for U7 on 2026-07-28
   (`egp-dev-logs.md:4145` warns prior Phase 2 authorization does NOT auto-carry).
2. **Local gates are the only real gate.** Full local suite must be green and is
   recorded here.

## Repo profile — ACTUAL working commands

`uv` is **not installed on this machine**; CLAUDE.md's `uv run --frozen ...` gate
commands do not work here. The working commands are:

```bash
.venv/bin/ruff check apps/ packages/ tests/ scripts/
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/check_migration_manifest.py --check
cd apps/web && npx tsc --noEmit -p tsconfig.typecheck.json && npx eslint src tests --max-warnings=0
cd apps/web && npm run check:api-types
```

## Verified prior art (patterns copied, not invented)

| Concern | Source |
|---|---|
| Internal token auth (503/401/403, `x-egp-worker-token`, `hmac.compare_digest`) | `apps/api/src/egp_api/auth.py:188` |
| Dark internal router shape | `apps/api/src/egp_api/routes/crawler_runtime.py:17` |
| Router registration | `apps/api/src/egp_api/bootstrap/middleware.py:237` |
| Repository factory + bundle | `apps/api/src/egp_api/bootstrap/repositories.py` |
| Service `app.state` attach | `apps/api/src/egp_api/bootstrap/services.py:149` |
| Background executor loop | `apps/api/src/egp_api/bootstrap/background.py` |
| Lease claim/renew + stale rejection | `packages/db/src/egp_db/repositories/discovery_job_repo.py:566` |
| Lease columns prior art | `packages/db/src/migrations/032_discovery_job_leases.sql` |
| Result-ingest service reuse | `apps/api/src/egp_api/routes/project_ingest.py` |
| Auth matrix + route inventory oracle | `tests/phase1/test_internal_worker_auth.py:100` |

### Built-in oracles this slice must satisfy

1. `test_internal_worker_route_inventory_is_covered` asserts **every** registered
   `/internal/worker/*` path appears in `INTERNAL_ROUTE_CASES`. New endpoints must be
   added there or this existing test fails.
2. `tests/operations/test_env_template.py` AST-scans for `os.getenv("EGP_*")`; adding
   `EGP_CRAWLER_AGENT_PROTOCOL` **requires** a `deploy/.env.production.example` entry.
3. `scripts/check_migration_manifest.py --check` (CI-enforced) requires regenerating
   `manifest.sha256` after adding migration `034`.

## Codex adversarial plan review (gpt-5.6-sol, xhigh) — verdict: REJECT draft

Run: `codex exec -m gpt-5.6-sol -c model_reasoning_effort=xhigh -s read-only`.
Verdict: *"reject the draft as non-executable… 'exactly once' is unsupported, and the
proposed tenant/idempotency boundaries are unsafe."* Substantiated. Dispositions:

| # | Finding | Disposition |
|---|---|---|
| C1 | **Stale-result race.** Token A submits a result; job stays `pending`; A's lease expires; B reclaims; processor later applies A's stale result. | **ACCEPTED — critical.** Result acceptance must atomically validate the live `(tenant_id, job_id, claim_token)`, insert/replay the inbox row, AND move the job to a non-claimable `result_received` state, consuming the lease. |
| C2 | **Processor has no lease.** A consumer crash after setting `processing` strands the row forever. | **ACCEPTED.** Add processor claim token + processing lease + heartbeat + `FOR UPDATE SKIP LOCKED` reclaim. |
| C3 | `next_attempt_at` nullable → a `next_attempt_at <= now()` query never selects NULL rows. | **ACCEPTED.** `NOT NULL DEFAULT now()`. |
| C4 | **"Exactly once" is false.** `project_ingest` upserts then separately notifies; `document_ingest` stores then audits; `create_run()` always inserts and `crawl_runs.discovery_job_id` is only a non-unique index. A crash before `applied` replays effects. | **ACCEPTED.** R8 reframed: at-least-once delivery with idempotent effects; product writes + inbox transition must share one transaction or gain per-result dedupe. |
| C5 | **Idempotency key unsafe.** `UNIQUE(tenant_id, idempotency_key)` lets one reused key collide across unrelated jobs. | **ACCEPTED.** Semantic identity `UNIQUE(tenant_id, job_id, claim_token)`; transport retry `UNIQUE(tenant_id, job_id, claim_token, idempotency_key)`; canonical-JSON SHA-256 only distinguishes identical replay from conflict. |
| C6 | **Tenant-identity hole (most serious).** `/internal/worker/*` bypasses JWT; the worker token is ONE global secret establishing NO tenant identity. Trusting `envelope.tenant_id` lets any token holder write to any tenant. | **ACCEPTED — critical.** Tenant is derived from the *claimed job*; an envelope tenant is an assertion that must match or 409. Add two-tenant negative test. (`project_ingest.py` already has this defect — U7 must NOT replicate it; fixing that pre-existing route is out of U7 scope.) |
| C7 | **Vacuous test.** The auth matrix accepts *any* allowlisted status and already accepts 404 for live routes, so a route that always 404s passes even if everything is broken. | **ACCEPTED.** Added a real primary-mode Postgres end-to-end test (claim→renew→result→process→verify→replay→conflict→reclaim). |
| C8 | Legacy/agent **claim race**: the existing claimer has no execution-backend predicate, so both consumers claim the same jobs. | **ACCEPTED.** Add `execution_backend = legacy\|agent` (default `legacy`); legacy claims only legacy rows, agent only agent rows. |
| C9 | My "no contention because embedded is disabled" reasoning is **false** — PostgreSQL *requires* external mode (`config.py:29`) and Compose runs an external discovery executor. | **ACCEPTED.** Verified at `config.py:29` and `discovery_job_repo.py:474-486`. |
| C10 | My "404 hides existence" premise is **false** — `/openapi.json` and `/docs` are public and internal paths are already published there. | **ACCEPTED.** Use **404 for `off`** (after token validation); reserve 503 for enabled-but-unhealthy. |
| C11 | **Ordering hazard remains despite default-off**: unapplied 034 → `/ready` `migrations_pending`; applied 034 + old binary → `migration_history_mismatch` (exact-ledger rule). | **ACCEPTED** into §9 rollout. |
| C12 | Missed files: `main.py` `create_app` protocol override, both compose files (which enumerate env vars individually — `--env-file` only interpolates), root `.env.example`, observability metrics, docs, readiness signal. Executors build their own repos/services rather than using `app.state`. | **ACCEPTED** for compose/env/create_app/executor-construction. Observability metrics + `/ready` processor signal **DEFERRED to U8** with a note — U7 ships `off`, so a wedged-processor signal has nothing to watch yet. |
| C13 | Scope promises an **artifact** V1 contract but the endpoint list had none. | **ACCEPTED partially.** U7 defines the artifact *contract type* (descriptors inside the result envelope); the scoped artifact *upload* endpoint is explicitly U9 (`feat/crawler-agent-artifact-cutover`). Recorded so it is not silently dropped. |
| C14 | Shared-types convention forbids hardcoding lifecycle strings outside shared types (`packages/shared-types/AGENTS.md:17`). | **ACCEPTED.** All statuses/error codes live in `egp_shared_types`. |

### Consequence: U7 re-sliced into three landable PRs

The critique roughly doubles U7's true surface (~25 files incl. compose, docs, readiness).
Landing it as one giant admin-merged PR with **no CI** would be reckless, so U7 lands as
three ordered, independently-green PRs on the same branch line:

| PR | Content | Safe because |
|---|---|---|
| **U7a** (this PR) | Migration 034: `execution_backend` on `discovery_jobs` (default `legacy`) + `result_received` job status + `crawler_agent_results` inbox (processor lease, FKs, composite uniques) + manifest + SQLAlchemy tables + shared-types vocabulary + **legacy claimer gains the `execution_backend='legacy'` predicate** | Default `legacy` ⇒ zero behaviour change; closes the C8 race before any agent exists |
| **U7b** | claim/renew/result repo + service + dark endpoints (404 when `off`), tenant rebinding, idempotency, `create_app` override, auth-matrix + inventory, OpenAPI/TS | endpoints dark by default |
| **U7c** | standalone inbox processor executor + CLI + both compose files + env templates + docs | processor not deployed until enabled |

## U7a implementation (this PR)

### Files changed

| File | Change |
|---|---|
| `packages/db/src/migrations/034_crawler_agent_results.sql` | NEW — `execution_backend` on `discovery_jobs` (default `legacy`) + widened `discovery_jobs_status_check` with `result_received` + `UNIQUE (tenant_id, id)` + `crawler_agent_results` inbox table + 4 indexes |
| `packages/db/src/migrations/manifest.sha256` | regenerated (35 → 36 files) |
| `packages/shared-types/src/egp_shared_types/enums.py` | `DiscoveryJobStatus`, `ExecutionBackend`, `AgentContractVersion`, `AgentInboxStatus`, `AgentInboxErrorCode` StrEnums (C14) |
| `packages/db/src/egp_db/repositories/discovery_job_repo.py` | `execution_backend` column on `DISCOVERY_JOBS_TABLE` (`server_default 'legacy'`); `build_discovery_job_values(execution_backend=…)`; **`execution_backend == 'legacy'` predicate added to BOTH `claim_pending_discovery_jobs` and `has_claimable_discovery_jobs`** |
| `tests/phase3/test_crawler_agent_schema.py` | NEW — 10 real-Postgres schema-contract tests |
| `tests/phase3/test_crawler_agent_routing.py` | NEW — 3 repository-level routing tests |

### TDD evidence

**RED (schema), before migration 034:**
```
psycopg.errors.UndefinedColumn: column "execution_backend" of relation
"discovery_jobs" does not exist
8 failed, 1 passed
```
Failure is the predicted missing-schema cause, not a harness error (the ephemeral
cluster came up in 1.57s).

**RED (routing), before the claim predicate — this is the C8 race, demonstrated:**
```
assert ['agent-work', 'legacy-work'] == ['legacy-work']
AssertionError: the legacy claimer claimed the agent-owned job
assert repository.has_claimable_discovery_jobs() is False  →  assert True is False
2 failed, 1 passed
```

**GREEN:** 10 schema + 3 routing = 13 passed. Ruff clean.

Honest note on one test: `test_migration_034_still_rejects_unknown_job_status` **passed
before** implementation — the pre-existing CHECK already rejected the bogus value. It is a
regression guard against the CHECK degrading into free text, not a RED test. Recorded
rather than dressed up as TDD.

### Deliberately NOT in U7a

- No SQLAlchemy `Table` for `crawler_agent_results` yet — nothing reads it in U7a, so the
  definition lands in U7b with its repository. (Migration-first is intentional; the table
  is unreferenced and empty until then.)
- No `EGP_CRAWLER_AGENT_PROTOCOL` (U7b), no compose/env/docs (U7c), no OpenAPI change
  (U7a adds no routes).

## QCHECK — Tier 1 (Claude, `g2-check` on the working tree)

`/code-review` is user-triggered/billed and not invocable here, so per `g2-check`'s
documented fallback Tier 1 was performed directly.

### Q1-HIGH — queue snapshot was not backend-scoped (FOUND AND FIXED)

`get_discovery_queue_snapshot` computed `claimable` with the same predicate shape as
`has_claimable_discovery_jobs` but **without** the new `execution_backend` filter, so the
two would disagree the moment an agent-owned row existed.

Why that is HIGH rather than cosmetic — traced to the consumers:
`build_discovery_one_shot_summary` (`executors/discovery_dispatch.py:134-150`) derives the
**stable one-shot terminal contract** from these counts: `pending_count == 0` →
`queue_drained`, `claimable_count == 0` → `waiting_retry_or_lease`, else `work_remains`.
With agent rows inflating the counts, a bounded one-shot crawl would report `work_remains`
forever and any caller looping until `queue_drained` would never terminate — while the
legacy consumer correctly claimed nothing. `discovery_doctor.py:330` surfaces the same
counts as operator diagnostics, so a phantom backlog would also be reported.

**Fix:** scope `pending` in the snapshot to `execution_backend='legacy'`. All four counts
(`pending`/`claimable`/`leased`/`retry_scheduled`) derive from `pending`, so one change
corrects them consistently. TDD: two new tests proved RED (`assert 2 == 1`) first.

### Tier 1 items checked and clean

| Check | Result |
|---|---|
| Other queries needing the predicate | `count_pending_discovery_jobs` deliberately stays global — it is a tenant-facing product count ("this tenant's pending work"), not a consumer-queue metric. `get_discovery_job` / `list_discovery_jobs` are tenant-scoped lookups, backend-agnostic by design. `renew_discovery_job_lease` / `record_discovery_job_attempt` operate on an already-claimed `(tenant_id, job_id, claim_token)`, so backend is implied. |
| Callers of `build_discovery_job_values` | 4 call sites — `discovery_job_repo.py:268,292`, `recrawl_request_repo.py:383`, plus tests. All use the new defaulted kwarg ⇒ `legacy`. No caller changes needed. |
| Raw `INSERT INTO discovery_jobs` outside the repo | `test_migration_runner.py:258,581` — real Postgres with 034 applied, so the server default supplies `legacy`. Confirmed by the green full suite. |
| Operational scripts inserting discovery jobs | none found under `scripts/`. |
| Tenant isolation in this diff | no query or mutation added that touches a job or inbox row without `tenant_id`; the inbox additionally enforces it at the DB level via the composite FK. |
| SQLAlchemy ↔ SQL parity | `execution_backend` added to `DISCOVERY_JOBS_TABLE` with `server_default text("'legacy'")`, matching 034's `DEFAULT 'legacy'`; SQLite bootstrap and Postgres migration agree (both exercised — SQLite in the routing tests, Postgres in the schema tests). |
| Vacuous tests | one identified and disclosed: `test_migration_034_still_rejects_unknown_job_status` passes pre-implementation (regression guard, not RED). All others proved RED first. |

## QCHECK — Tier 2 (Codex `gpt-5.6-sol`, `model_reasoning_effort=xhigh`, read-only)

Verdict: **"reject as-is. No CRITICAL/HIGH findings, but four correctness gaps and one
material rollout hazard remain."** Independently confirmed my Tier-1 snapshot fix was
correct and complete, and found no name collisions and no broken callers.

| # | Finding | Severity | Disposition |
|---|---|---|---|
| Q2-1 | **Backend not repeated in the claim compare-and-swap.** Candidate SELECT filters `execution_backend='legacy'` but the claiming `UPDATE` omitted it, so a row rerouted between selection and update would still be leased by the legacy executor. | MEDIUM | **FIXED.** Predicate added to the CAS `WHERE`. New test `test_claim_update_rechecks_backend_after_selection` flips the row via a `before_cursor_execute` hook fired immediately before the UPDATE; **proved non-vacuous** by temporarily reverting the fix → `assert [DiscoveryJob...] == []` fails. |
| Q2-2 | **SQLAlchemy metadata lacked the backend CHECK**, so SQLite could store `execution_backend='quantum'` — a row invisible to every claimer — while PostgreSQL rejects it. My Tier-1 parity check had asserted parity and was wrong on this point. | MEDIUM | **FIXED.** `CheckConstraint` mirrored onto `DISCOVERY_JOBS_TABLE` via a new `EXECUTION_BACKEND_SQL` (same idiom as `DISCOVERY_FAILURE_CODE_SQL`), plus `test_sqlite_bootstrap_rejects_an_unknown_execution_backend`. |
| Q2-3 | **Schema permitted the stranded state it warns about**: `inbox_status='processing'` with NULL `processor_token`/`processing_expires_at` would be skipped forever by a `processing_expires_at <= now()` reclaim. | MEDIUM | **FIXED.** Added `crawler_agent_results_processing_lease_check`, plus a negative and a positive test so the constraint cannot be vacuously satisfied. Consistent with the same reasoning already applied to `next_attempt_at`. |
| Q2-4 | **`result_received` will be misreported as `queued`** by `recrawl_request_repo.py:591 _resolve_job_state()`; and admission/backpressure (`entitlement_service.py:287`), recrawl conflict detection (`recrawl_request_repo.py:247`) and the recovery script (`requeue_failed_discovery_runs.py:247`) all count only `pending`. | MEDIUM | **DEFERRED to U7b — owner: U7b, blocking.** U7a contains no producer of `result_received`, so nothing can misreport it yet. U7b introduces the producer and **must** resolve reporting/quota/duplicate-requeue semantics for the state before shipping. Recorded here so it cannot be silently lost. |
| Q2-5 | **Migration locking.** PG15 does not rewrite rows for a constant default, but the three `ALTER TABLE`s take `ACCESS EXCLUSIVE`, the unique constraint builds an index, the partial index build blocks writes, and `migration_runner.py:58` holds one transaction for the whole file — so the live queue can block for the migration's duration. | MEDIUM (rollout) | **DEFERRED as an operational requirement**, documented in the PR and below. Not fixable in-migration: `CREATE INDEX CONCURRENTLY` cannot run inside the runner's transaction. Requires a quiesce window or rehearsal at production scale. |
| Q2-6 | **Historical drift caveat**: 015 uses `CREATE TABLE IF NOT EXISTS`, so a database where SQLAlchemy metadata created `discovery_jobs` first would lack the named status constraint and 034's unconditional `DROP CONSTRAINT` would abort. | (noted in §1) | **FIXED.** Changed to `DROP CONSTRAINT IF EXISTS`. |

### Weak tests Codex identified — strengthened

- `test_inbox_next_attempt_at_is_never_null` only proved a DEFAULT, not `NOT NULL` →
  added `test_inbox_rejects_an_explicit_null_next_attempt_at` (expects `NotNullViolation`).
- `test_has_claimable_discovery_jobs_ignores_agent_owned_jobs` would pass if the method
  always returned `False` → added a legacy-positive control asserting `is True`.
- Accepted as-is with compensating coverage (documented rather than churned):
  `test_migration_034_allows_result_received_job_status`,
  `test_inbox_allows_a_fresh_claim_token_for_the_same_job`, and
  `test_queue_snapshot_reports_drained_when_only_agent_work_remains` are each individually
  weak but are covered by their paired negative test in the same file.

### Codex sandbox limitations (not findings)
Its pytest could not start (read-only sandbox had no usable temp dir) and its coding-log
append was refused. Its analysis is therefore static; all execution evidence in this log
is from local runs.

## Operational requirement for deploying migration 034

Apply during a **quiesce window** or after rehearsal at production data scale. The
migration takes `ACCESS EXCLUSIVE` on `discovery_jobs` and builds two indexes inside a
single transaction, which can block the live discovery queue for its duration. There is no
row rewrite (PG15 constant default), so duration is driven by index builds, not table
size backfill. Migration and binary must ship from the same release image (exact-ledger
readiness rule).

## Final gate evidence (local — the only gate available while E0 holds)

| Gate | Result |
|---|---|
| `ruff check apps/ packages/ tests/ scripts/` | clean |
| `check_migration_manifest.py --check` | 36 files verified |
| `pytest tests/ -q` **3× consecutive** (post-QCHECK code) | **1269 / 1269 / 1269 passed**, 2 skipped, 0 failed |
| `pytest tests/ -q` final (with the parity oracle added) | **1274 passed**, 2 skipped, 0 failed |
| Baseline for comparison (`main@ff1ead3a`) | 1248 passed, 2 skipped, 0 failed |
| OpenAPI schema vs committed | byte-identical (no routes added) ⇒ no TS regeneration |
| Frontend lint/typecheck | N/A — zero files under `apps/web` touched |

Net new tests: **26** (11 → 15 schema incl. upgrade path, 3 → 6 routing, 5 enum parity).

### Wiring verification (Phase 4b) — disclosed honestly

| New export | Non-test consumer | Where |
|---|---|---|
| `ExecutionBackend` | yes (9) | `discovery_job_repo.py` — column default, 4 query predicates, CHECK |
| `EXECUTION_BACKEND_SQL` | yes (2) | `discovery_job_repo.py` CheckConstraint |
| `DiscoveryJobStatus` | **no production consumer yet** | vocabulary for `result_received`, consumed in U7b |
| `AgentContractVersion` | **no production consumer yet** | consumed in U7b |
| `AgentInboxStatus` | **no production consumer yet** | consumed in U7b |
| `AgentInboxErrorCode` | **no production consumer yet** | consumed in U7b |

Four enums ship without a production consumer. That is a deliberate, disclosed exception
to the "no orphaned exports" rule rather than an oversight: `packages/shared-types/AGENTS.md`
requires cross-service vocabularies to live in `egp_shared_types.enums` and stay
synchronised with the database CHECK constraints, and those constraints ship in **this**
PR. To stop them being dead weight, `tests/phase3/test_crawler_agent_enum_parity.py`
parses the CHECK vocabularies directly out of migration 034 and asserts each enum matches
— which also closes a real gap noted during exploration: the repo had **no**
migration↔code vocabulary drift oracle at all.

## Progress

- [x] Worktree + branch + coding log
- [x] DREP (g2-planning §0–§10) + Codex adversarial pass (rejected v1; re-sliced into U7a/b/c)
- [x] U7a acceptance tests RED-proven
- [x] U7a implementation
- [x] Gates + 2-tier QCHECK (Tier 1 HIGH fixed; Tier 2 4 of 5 MEDIUMs fixed, 1 deferred to U7b)
- [x] PR + admin merge + local main sync
- [ ] **U7b** — claim/renew/result repo + service + dark endpoints (blocking: resolve `result_received` reporting/quota/requeue semantics per Q2-4)
- [ ] **U7c** — standalone inbox processor executor + compose + env templates + docs
