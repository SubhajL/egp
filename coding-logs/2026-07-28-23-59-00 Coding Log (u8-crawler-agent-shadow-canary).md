# Coding Log — U8 `feat/crawler-agent-shadow-canary`

**Started:** 2026-07-28
**Worktree:** `/Users/subhajlimanond/dev/egp-u8`
**Base:** exact `origin/main` @ `2ed856c9` (post-U7c, PR #189)
**Lifecycle:** g2 (`g2-planning` → `g2-coding` → `g2-qcheck` → `g2-check`)

## Scope

U8 per `egp-dev-logs.md:4486` and the roadmap entry at `egp-dev-logs.md:3560`
(`feat/crawler-agent-shadow-canary`): the worker API client, dual-report results in
shadow mode, compare durable outcomes, then canary one profile. It additionally owns
the three items U7 explicitly deferred:

1. **Routing** — nothing creates `execution_backend='agent'` jobs, so the V1 endpoints
   claim nothing even when the protocol is enabled (`U7b` finding P8).
2. **The suppressed `NEW_PROJECT` notification** for agent-sourced projects
   (`U7c` finding C2).
3. **Observability** — a running PID is not proof the inbox processor can drain
   (`U7a` finding C12, deferred).

**Out of scope (U9):** scoped artifact upload, document result envelopes, removing
DB/storage-master/SSH credentials from the Mac.

## Preconditions verified (2026-07-28)

| Check | Result |
|---|---|
| `HEAD == origin/main` | `2ed856c9` both |
| Primary worktree dirty paths preserved | 3 paths untouched (2 coding logs + `docs/TOR KEYWORDS.md`) |
| Next migration prefix | **035** (034 is max) |
| Worktree venv isolation | `egp-u8` sources, verified via `egp_api.__file__` |
| Test collection | 1322 tests |
| `uv` on PATH | **no** — reused `egp-phase2-u5/.tools/uv-0.11.32/bin/uv` with the warm cache |

## Repo profile — ACTUAL working commands

`uv` is not on PATH; CLAUDE.md's `uv run --frozen …` gate commands do not work here.

```bash
.venv/bin/ruff check apps/ packages/ tests/ scripts/
.venv/bin/python -m pytest tests/ -q
.venv/bin/python scripts/check_migration_manifest.py --check
cd apps/web && npx tsc --noEmit -p tsconfig.typecheck.json && npx eslint src tests --max-warnings=0
cd apps/web && npm run check:api-types
```

## Codex adversarial plan review (gpt-5.6-sol, xhigh, read-only) — verdict: REJECT

> *"Reject. The plan is non-executable as written."* Two release-safety blockers, one
> literal self-contradiction, and one slice built on a function that does not exist.
> Substantiated in every case I checked. Full output kept in the session scratchpad.

| # | Finding | Sev | Disposition |
|---|---|---|---|
| C1 | §10 froze the very test files §3 creates — the plan forbade its own work | blocker | **ACCEPTED.** §10 now lists only *pre-existing* files; files a slice authors are frozen after authoring. Same fix covers C21. |
| C2 | `docs/SOC_INCIDENT_RESPONSE.md:163` is a **fourth** operational `discovery_jobs` insert, hardcoding `'legacy'` | MED | **ACCEPTED** → routing slice. |
| C3 | Routing tests covered 2 of 4 indirect producers (both `rules_service` paths + `requeue_failed_discovery_runs.py:164` uncovered) | MED | **ACCEPTED** → routing slice. |
| C4 | `CrawlProfileRecord` + mapper + create/update/list/detail all need the field (`profile_repo.py:32,63,107,345,400`) | MED | **ACCEPTED** → routing slice. |
| C5 | The notification plan omits `WebhookDeliveryService`; "construct from env" is wrong because entitlement/notification behaviour is **repository**-driven | **HIGH** | **ACCEPTED — became S1a's centerpiece.** Verified: `dispatcher.py:26` makes `webhook_delivery_service` optional and default `None`, so my stack would have written in-app rows while silently dropping configured webhook delivery. |
| C6 | `apps/web/src/lib/generated/api-types.ts` is also compared (`check-api-types.sh:20`), and §10 forbade touching it | MED | **ACCEPTED.** Verified. |
| C7 | Metrics need `EXPECTED_METRIC_NAMES` + package re-exports; gauges set from a route are stale between operator visits | MED | **ACCEPTED.** Verified the oracle at `tests/phase2/test_observability_metrics.py:18`. **Design changed** to a scrape-time collector. |
| C8 | The API process derives health and needs its own stale-threshold env block | MED | **ACCEPTED** → S1b. |
| C10 | The `drain_status` truth table was internally contradictory (missing heartbeat is both `wedged` and `unknown`; `draining` never defined; no multi-processor aggregation; backlog undefined), and `process_once` returns before any telemetry on an empty iteration (`crawler_agent_results.py:127`) | **HIGH** | **ACCEPTED in full.** Explicit precedence written; the processor must heartbeat on **every** iteration — the empty one is exactly the case the feature exists to detect. |
| C11 | Queue-snapshot contract promised 4 counts; the test asserted 1 | MED | **ACCEPTED.** |
| C12 | Routing failed **open** on a missing profile. `discovery_jobs.profile_id`'s FK is not composite with `tenant_id` (`015_discovery_jobs_outbox.sql:4`), so tenant A + tenant B's profile satisfies both FKs independently ⇒ **cross-tenant job/profile association** | **CRITICAL** | **ACCEPTED.** Must fail closed with a typed error, and resolve inside the insert transaction (both methods currently build values before opening it). |
| C13 | Shadow acceptance via a plain guard read is a TOCTOU under READ COMMITTED; needs row locking, **server-derived** delivery mode, mode-aware replay, a shadow terminal method, and submission while the lease keeper is still live | **CRITICAL** | **ACCEPTED in full.** Caller-supplied `delivery_mode` removed from the design — a global-token holder could otherwise submit `primary` during shadow. |
| C14 | The parity oracle does not exist | **HIGH** | **ACCEPTED** → promoted to its own slice. See below. |
| C15 | The client contract promised HTTPS but the test used ASGI transport | MED | **ACCEPTED** → scheme validation. |
| C16 | The agent runtime had no deployable entry point; must use the **worker** image (`apps/api/Dockerfile:19` excludes `egp_worker`), and the real runtime is the Mac (`.env.remotecrawl.example`, `scripts/run_remote_crawl.sh`) | **HIGH** | **ACCEPTED.** |
| C17 | `/abandon` had no repository or service method | MED | **ACCEPTED.** |
| C18 | **My rollback story was factually false.** Flipping a profile back to `legacy` does not recover stranded jobs: per-job `execution_backend` is immutable, and the backend-agnostic in-flight dedupe (`discovery_job_repo.py:314`) then *blocks* creation of a replacement legacy job | **CRITICAL** | **ACCEPTED.** Routing must ship a guarded pending-job reroute or the canary is one-way. |
| C19 | "Everything before the flip is dark" is false | MED | **ACCEPTED** — I no longer claim any U8 slice is inert. |
| C20 | Migration 037 was listed in two slices | LOW | **ACCEPTED.** |
| C22 | Test-vacuity table across all 34 planned tests | MED | **ACCEPTED**; each entry travels with its slice. |
| — | "`/v1/rules/...` does not belong in the internal-worker route inventory" | — | **Not a finding** — Codex confirms my conditional conclusion. Independently verified: that inventory filters on `/internal/worker/` (`test_internal_worker_auth.py:131`). |

Nothing was silently dropped.

### My own independent findings (found before Codex returned)

- **V1** `project_status_events` suppresses an event when the status signature is
  unchanged (`project_aliases.py:122-133`), so it is not a complete per-run ledger.
  I moved the parity oracle to `projects.last_run_id`; Codex then showed that is *also*
  wrong (latest-writer state, overwritten by any later run). Both of us landed on the
  same conclusion from different directions: the oracle must be built from
  `crawl_runs.discovery_job_id` + successful discovery `crawl_tasks.result_json.project_id`.
- **V2** The parent dispatcher never sees the discovered-project payloads
  (`discovery_worker_dispatcher.py:929` decodes then discards; `dispatch()` returns
  `None`), so a shadow envelope cannot be assembled there.
- **V3** Production `discovery_jobs` inserts are exactly three in Python; the rest are tests.
- **V4** The inbox-executor compose service receives **no SMTP/notification env**
  (`docker-compose.yml:177-183`), so compose + the env template are in scope for S1a.

## Consequence: U8 re-sliced into five landable PRs, reordered

Codex's recommended ordering is better than mine and is adopted: build the notification
stack and processor health first, then the durable parity oracle, then shadow, and make
**routing the last activation step** rather than the first.

| Slice | Branch | Content |
|---|---|---|
| **S1a** | `feat/crawler-agent-notification-parity` | one shared notification-stack builder used by BOTH the API bootstrap and the standalone inbox executor; wire it in. No migration. |
| **S1b** | `feat/crawler-agent-inbox-health` | heartbeat migration, `get_inbox_health` with an explicit truth table, agent queue snapshot, operator route, scrape-time metrics collector |
| **S2** | `feat/discovery-dispatch-outcome` | typed dispatch outcome across the subprocess boundary + the durable run→projects parity oracle |
| **S3** | `feat/crawler-agent-shadow-parity` | shadow observational recording (locked acceptance, server-derived mode, shadow terminals) + comparison |
| **S4** | `feat/crawler-agent-job-routing` | profile `execution_backend`, **fail-closed** resolution in-transaction, guarded pending-job reroute, SOC runbook SQL, canary CLI |
| **S5** | `feat/crawler-agent-runtime-canary` | HTTPS-only agent client, agent runtime on the worker image + Mac wiring, renew/abandon state machine, canary runbook |

---

# S1a — `feat/crawler-agent-notification-parity`

## Stop line: **none — Q0 fired, nothing delegated**

Walking `g2-coding`'s Q0–Q3 tree, the first question wins: S1a changes a
customer-visible effect (email and webhook delivery) and wires the entitlement
capability check, which is an authorization boundary. **Q0 → do not delegate.**
Claude implemented the whole slice; no stop line applies and there was no brief,
no shim and no diff audit against a delegate.

Because Q0 removes the handoff it also removes the machinery that *forces*
test-first, so Phase 2c-ter applied as a rule rather than a consequence: every
unit of behaviour here was written test → RED → implement → GREEN. No layer was
written seams-first, so 2c-bis mutation was not required as a substitute — it was
still run, deliberately, on the two properties I *asserted* rather than observed
(below).

## Files

| File | Change |
|---|---|
| `apps/api/src/egp_api/bootstrap/notifications.py` | **NEW** — `NotificationStack` + `build_notification_stack()`: the single construction path |
| `apps/api/src/egp_api/bootstrap/services.py` | delegates to the builder; 6 now-unused imports and 2 unused locals removed |
| `apps/api/src/egp_api/executors/crawler_agent_results.py` | builds the six repositories on its own shared engine, wires the gated dispatcher, corrected delivery-semantics docstring |
| `docker-compose.yml`, `docker-compose-localdev.yml` | `EGP_SMTP_*` (6 vars) for `crawler-agent-inbox-executor` |
| `docs/DEPLOYMENT.md`, `docs/LIGHTSAIL_LOW_COST_LAUNCH.md` | backlog preflight before the first U8a deploy |
| `tests/phase3/test_crawler_agent_notification_parity.py` | **NEW** — 8 acceptance tests |

## TDD evidence

RED, before implementation — each failure matched its planned RED-proof, and the
ephemeral Postgres cluster came up in ~2s, so none of these are harness errors:

```
assert [] == [('new_project', 'in_app')]          # no dispatcher at all (U7c)
assert 0 == 1                                      # webhook delivery row absent
ImportError: cannot import name 'notifications' from 'egp_api.bootstrap'
assert None is not None                            # ProjectIngestService._notification_dispatcher
```

`test_..._is_withheld_without_the_entitlement` **passed before** implementation and
is declared a control, not a RED test — see the mutation evidence for why it is
still load-bearing.

GREEN: 8/8.

## Mutation evidence (for the two properties I asserted rather than observed)

| Mutation | Predicted | Observed |
|---|---|---|
| Drop `webhook_delivery_service=` from the dispatcher | only the webhook tests fail | **exactly** `test_..._enqueues_webhook_delivery` + the stack-assembly test; 5 others pass |
| Return the raw (ungated) dispatcher as `gated_dispatcher` | only the entitlement control fails | **exactly** `test_..._is_withheld_without_the_entitlement` + the stack-assembly test |

The second mutation is what makes the declared control honest: a raw dispatcher
does fail it, so it genuinely distinguishes gated from ungated wiring.

A first attempt at mutation 1 was too broad (it also removed the dataclass field,
producing a `TypeError` and 6 failures). That proves nothing, so it was redone with
a precise anchor. Recorded because a sloppy mutation that "fails a lot" is easy to
mistake for evidence.

## QCHECK — Tier 2 (Codex `gpt-5.6-sol`, xhigh, read-only)

Verdict: **no CRITICAL; one HIGH, three MEDIUM.** It independently confirmed the
API refactor is behaviour-preserving (construction order, distinct objects,
`app.state.notification_dispatcher` still the gated wrapper) and that the
executor's repository stack is complete and consistently on its shared engine.

| # | Finding | Sev | Disposition |
|---|---|---|---|
| Q1 | **Retry permanently LOSES the notification — my docstring claimed duplication, which is the wrong risk.** `ingest_discovered_project` dispatches only when the pre-upsert lookup found no project (`project_ingest.py:68,79`) and the project commits *before* dispatch. A dispatch failure → retry → project now exists → dispatch skipped → row marked `applied`. Notification gone, silently. | **HIGH** | **ACCEPTED; documentation fixed, behaviour pinned, fix deferred with reason.** The docstring now states the loss window precisely. Added `test_a_dispatch_failure_after_project_commit_currently_loses_the_notification`, which **empirically confirms it**: after a successful apply, `dispatcher.calls == 1` and zero notification rows exist. Codex proposed a test asserting the *correct* behaviour that "fails today"; I deliberately inverted it into a passing test asserting the *actual* behaviour, because a failing test cannot land and an `xfail` hides the fact. The test name and docstring say it must be **inverted** by the effect-ledger work. That ledger is the separately-scoped task and is explicitly out of S1a. |
| Q2 | Duplicates are reachable, but only via a genuine race: two processors both observing `existing is None` before either upsert commits. | MED | **ACCEPTED as documented, not tested.** Pre-existing and shared with the API path. Recorded in the module docstring. A synchronised two-processor harness is real work; recording the gap beats faking coverage for it. |
| Q3 | A routine deploy can notify a pre-U8a backlog, because the executor always installs the dispatcher and drains **regardless of** `EGP_CRAWLER_AGENT_PROTOCOL`. `off` is not the emergency stop. | MED | **ACCEPTED and FIXED.** Backlog preflight added to `DEPLOYMENT.md` (stop the service, count non-terminal rows, decide deliberately) and cross-referenced from `LIGHTSAIL_LOW_COST_LAUNCH.md`. Sent messages survive a rollback — stated. |
| Q4 | **The recipient-isolation test was vacuous for its own claim** — it left SMTP unconfigured and counted in-app rows, which do not carry the recipient list. It would pass even if another tenant's address were emailed. | MED | **ACCEPTED and FIXED.** Rewritten to drive the shared stack with a capturing email sender and assert the exact delivered address set (`== ["owner@example.com"]`). |
| Q5 | The stack test uses `inspect.getsource` string matching, which an import or comment could satisfy. | vacuity | **ACCEPTED as partially mitigated.** It also builds a real stack and asserts the assembled properties — and both mutations above fail it, so it is not inert. The source-match half remains weak; recorded rather than dressed up. |
| Q6 | The no-dispatcher test reaches into two private attributes and accepts any non-None object. | vacuity | **ACCEPTED as noted.** It catches exactly the U7c regression (`None`) and nothing more; that is what it is for. |
| Q7 | The compose test checks key presence, not interpolation values. | vacuity | **ACCEPTED as noted.** |

Codex again could not append its review to the coding log (read-only sandbox), so
its analysis is static; all execution evidence here is from local runs.

## Gates (local only — CI dead, E0)

| Gate | Result |
|---|---|
| `ruff check apps/ packages/ tests/ scripts/` | clean |
| `pytest tests/ -q` **3× consecutive on frozen code** | **1328 / 1328 / 1328 passed**, 2 skipped, 0 failed |
| Baseline `main @ 2ed856c9` | 1320 passed, 2 skipped, 0 failed |
| OpenAPI vs committed | byte-identical (no routes added) ⇒ no TS regeneration |
| Frontend lint/typecheck | N/A — zero files under `apps/web` touched |
| env-template drift + compose topology | green |

Net new tests: **8**.

### One unexplained failure, and what I actually know about it

An **earlier** 3× attempt returned `1327 / 1327 / 1 failed, 1326 passed`. I did not
capture the failing test's name — the loop only kept the summary line — so I cannot
name it. Rather than quietly re-run until green and report only that, here is the
evidence:

- That run overlapped with other processes I had started against the same worktree:
  a separate `pytest` invocation, an OpenAPI export, and the Codex review.
- The clean 3× above, with nothing else running, is 3/3 green; the suite has since
  been fully green on every subsequent run.
- **A concrete mechanism exists.** `dev_postgres._find_free_port()`
  (`dev_postgres.py:58-62`) binds a socket to port 0, **closes it**, and returns the
  number — a time-of-check/time-of-use race. The port is free when returned and can
  be taken before PostgreSQL binds it. The suite starts **11** module-scoped
  ephemeral clusters; this slice adds a 12th, so it marginally widens an existing
  window.

So: pre-existing test-infrastructure flakiness, not a product defect, and not
introduced here — but this slice does add one more cluster to the pool. Worth its
own fix (hold the socket until the postmaster is up, or allocate from a reserved
range); deliberately not done in S1a, and recorded so it is not rediscovered from
scratch.

### A do-not-touch decision worth recording

The existing compose-topology oracle
(`tests/phase2/test_background_runtime_mode.py`) asserts a **fixed list** of
environment variables and would not have caught the missing `EGP_SMTP_*`. It is on
the Do-Not-Touch list, so rather than edit it I asserted the new requirement in
the slice's own test file and left the frozen oracle byte-identical.

---

# S1b — `feat/crawler-agent-inbox-health`

## Stop line: **none — Q0 fired again** (this slice carries migration 035)

## What it closes

The `crawler-agent-inbox-executor` compose block already stated the gap:
*"A running PID is not proof the processor can drain; that signal belongs with the
U8 observability work."* This is that work.

The design decision worth recording is **why a backlog gauge is not enough**: with
an empty queue, a dead processor and a healthy idle one are indistinguishable from
the queue side. So liveness must come from the processor itself, and the heartbeat
has to be written on *every* iteration — the idle one is precisely the one that
carries information. `process_once` therefore reports from a `try/finally`, and
`drain_status` treats `idle` as requiring a **fresh heartbeat**, never merely an
empty queue.

Aggregation across replicas takes the **freshest** heartbeat. Taking the oldest
would leave the fleet permanently `wedged` after any replica is scaled down and
its final heartbeat is left behind.

## Files

| File | Change |
|---|---|
| `packages/db/src/migrations/035_crawler_agent_inbox_heartbeats.sql` | **NEW** — global liveness table, bounded vocabularies, no free-form error payload |
| `packages/db/src/migrations/manifest.sha256` | regenerated (36 → 37) |
| `packages/shared-types/…/enums.py` | `AgentInboxProcessorStatus`, `AgentInboxDrainOutcome`, `AgentInboxDrainStatus` |
| `packages/db/…/crawler_agent_repo.py` | heartbeat table + `record_inbox_heartbeat`, `get_inbox_health`, `get_agent_queue_snapshot`, `_derive_drain_status` |
| `apps/api/…/executors/crawler_agent_results.py` | heartbeat on every exit path; `processor_id` |
| `apps/api/…/routes/crawler_agent.py` | operator router + `GET /v1/rules/crawler-agent-inbox` |
| `apps/api/…/bootstrap/{middleware,services}.py`, `config.py` | registration + staleness threshold |
| `deploy/.env.production.example`, both compose files | 2 new vars, in the services that actually read them |
| `docs/OBSERVABILITY.md` | how to read `drain_status`, and the two rules that are easy to misread |
| `apps/web/src/lib/generated/{openapi.json,api-types.ts}` | regenerated for the new route |
| `tests/phase3/test_crawler_agent_inbox_health.py` | **NEW** — 17 tests |

## TDD evidence

RED: `psycopg.errors.UndefinedTable: relation "crawler_agent_inbox_heartbeats" does
not exist` — the predicted missing-schema cause, cluster up in ~2s, no harness
error. GREEN: 17/17.

## A real defect the gate caught in my own migration

The full suite failed on an **existing** test,
`test_migration_034_upgrades_a_database_that_already_has_jobs`. Cause: my 035 added
an index on `crawler_agent_results`, a table 034 creates — and that test stages
every migration **except** 034, so 035 ran first and hit `UndefinedTable`.

The fix belonged in my migration, not the test: the index I added was an exact
duplicate of `idx_crawler_agent_results_processing_lease` from 034
(`034_crawler_agent_results.sql:129`). Removing it fixed the failure *and* deleted a
redundant index. Recorded because the tempting move — editing the frozen test to
accommodate a duplicate index — would have been wrong twice over.

## QCHECK — Tier 2 (Codex `gpt-5.6-sol`, xhigh, read-only)

Verdict: **no CRITICAL; two HIGH, four MEDIUM, two LOW.** Both HIGHs were real, and
the first would have defeated the entire feature.

| # | Finding | Sev | Disposition |
|---|---|---|---|
| Q1 | **A crash loop reports false health.** The heartbeat fired from a blanket `finally` with a hardcoded `status="running"`, so a processor raising on every iteration would write a fresh `running`/`idle` heartbeat, die, be restarted by Compose, and refresh it again — the operator route reads `idle` forever while nothing drains. | **HIGH** | **FIXED.** The exception path now reports `status=error`/`last_outcome=error` and re-raises; telemetry stays fail-open but no longer describes a processing failure as healthy. New test `test_a_crashing_processor_reports_error_not_health`; **mutation-proved** — restoring the blanket `finally` fails exactly that test and nothing else. |
| Q2 | **The heartbeat ran a whole-table aggregate every iteration.** `_report_heartbeat` called `get_inbox_health()` (SUM/MIN/MAX over `crawler_agent_results` with no WHERE) once per idle poll *and* once per drained row — so the observability feature would make draining progressively slower as applied history grew. The stored `backlog_depth` was not even consumed by the health response, which recomputes it. | **HIGH** | **FIXED.** New `count_queued_results()` — a COUNT matching the partial `idx_crawler_agent_results_drain` index. New test asserts the heartbeat path calls `get_inbox_health` **zero** times. The rich aggregate stays on the operator-request path, where it is paid for once per human. |
| Q3 | **"Freshest heartbeat wins" is not valid fleet aggregation.** A `stopping` replica heartbeating one second after a healthy `running` one reported the fleet `wedged`. | MED | **FIXED.** `_select_fleet_heartbeat` picks the freshest *usable* row — availability means "at least one fresh running processor". New test. |
| Q4 | **Future clock skew can mask a dead fleet.** The executor stamps its own clock, the API compares against its own, and negative age was clamped to zero — so a heartbeat an hour ahead stays "fresh" for an hour *and* sorts first. | MED | **FIXED.** Heartbeats more than 60s in the future are not usable. New test. |
| Q5 | **Future-scheduled work reported as `draining`.** `_derive_drain_status` took total backlog while `due_backlog_depth` was computed and unused, so an all-far-future retry schedule read `draining` with `last_outcome=idle` — self-contradictory, and it hid an accidental far-future schedule. | MED | **FIXED.** Derived from `due_backlog_depth`. New test. |
| Q6 | **The operator-role test never reached the role guard** — auth middleware answers 401 first, so deleting `require_run_operator_role` would leave it green and the route open to any authenticated viewer. | MED | **FIXED.** Added viewer→403 / analyst→200, mirroring the crawler-runtime test. |
| Q7 | The claimed UPSERT was racy (UPDATE-then-INSERT: two first writers both see zero rows and race the primary key). | LOW | **FIXED.** Atomic `ON CONFLICT DO UPDATE` via the `_dialect_insert` idiom already used by `project_aliases.py`. |
| Q8 | `backlog_depth` had a PostgreSQL server default but only a client-side SQLAlchemy default. | LOW | **FIXED.** `server_default=text("0")` mirrored onto the metadata. |

Vacuous tests Codex named — strengthened: the upsert test now asserts every field
moves (not just the row count); the heartbeat-failure test now asserts reporting was
**attempted** (it would previously have passed with reporting deleted outright); the
compose check now asserts both new variables in the services that read them.

Accepted-as-noted rather than fixed: `test_processor_heartbeats_even_when_it_claims_nothing`
covers only the idle exit, and the route test seeds no agent jobs. Both are covered
by neighbours in the same file; recorded rather than churned.

Codex again could not append to the coding log (read-only sandbox); its analysis is
static and all execution evidence here is local.

## Deliberately deferred, with the reason

**No Prometheus metric.** A gauge refreshed only when an operator hits the route is
stale between visits, so the correct shape is a scrape-time collector; inventing a
per-scrape database query at the end of a long session is how that becomes a new
failure mode. The durable signal and the operator route land now; alert wiring is
its own slice. Stated in `docs/OBSERVABILITY.md` rather than left implied.

**Env template edit was operator-approved.** A `protect-files.sh` hook blocks
`deploy/.env.production.example`; the repo's AST drift test requires the new var to
be listed there. Asked, approved, applied.

## Gates (local only — CI dead, E0)

| Gate | Result |
|---|---|
| ruff | clean |
| `check_migration_manifest.py --check` | 37 files verified |
| `pytest tests/ -q` **3× consecutive on frozen code** | **1352 / 1352 / 1352** passed, 2 skipped, 0 failed |
| Baseline (this branch's base, `51c7f8c1`) | 1328 passed, 2 skipped |
| OpenAPI + `api-types.ts` | regenerated for the new operator route |

Net new tests: **24**.

## Progress

- [x] Worktree + branch + coding log + pointer
- [x] DREP v1 (g2-planning §0–§10)
- [x] Codex adversarial plan pass — **rejected v1**; re-sliced into S1a…S5
- [x] **S1a** — notification parity (PR #190, `51c7f8c1`)
- [x] **S1b** — inbox drain health
- [ ] S2 — typed dispatch outcome + durable run→projects parity oracle
- [ ] S3 — shadow observational recording + comparison
- [ ] S4 — routing + guarded reroute + canary CLI (activation step)
- [ ] S5 — agent runtime on the worker image + Mac wiring + canary
- [ ] S1b — inbox health
- [ ] S2 — dispatch outcome + parity oracle
- [ ] S3 — shadow parity
- [ ] S4 — routing (activation step; needs the reroute rollback)
- [ ] S5 — agent runtime + canary
