# Coding Log — U7c: crawler-agent result-inbox processor

**Date:** 2026-07-28
**Branch:** `feat/crawler-agent-inbox-processor` from `origin/main @ 35b43529`
**Lifecycle:** g2

## Scope and the two constraints it was built under

The operator reaffirmed the directive to implement U7c after I flagged two
blockers, so it is built with both stated explicitly rather than papered over.

**1. Document envelopes are rejected, not applied.** Document ingestion requires
the actual file bytes (`document_ingest.py:125-169`) and scoped artifact upload is
U9. A descriptor-only envelope cannot reproduce real document ingestion, so the
processor refuses `document` results as a permanent failure. Rejecting loudly beats
writing a document row with no artifact behind it.

**2. Delivery is at-least-once; effects are only PARTIALLY idempotent.** This is
stated in the module docstring rather than claimed away:
- `discovery` applies through `ingest_discovered_project`, which upserts on
  canonical project identity — re-application converges. Genuinely idempotent.
- `status` applies a convergent state transition.
- Everything downstream — notification dispatch, audit rows, run creation — is a
  separate effect in a separate transaction. A crash after those but before
  `inbox_status='applied'` re-runs them on retry, so a duplicate notification is
  possible. Closing that needs an effect ledger / transactional outbox keyed by
  inbox result id, which is NOT attempted here.

## Design

- **Processor lease.** `claim_next_result` takes a row under
  `processor_token` + `processing_expires_at`. Select-then-CAS rather than
  `FOR UPDATE SKIP LOCKED` so the same path works on the SQLite bootstrap; the
  repeated predicates in the UPDATE are what guarantee exclusivity.
- **Reclaim.** `reclaim_expired_processing` returns rows whose processor died to
  the retry queue with `processor_lease_lost`. Without it a crash after setting
  `processing` strands the row: the drain query only looks at pending/failed.
- **The job must leave `result_received`.** `mark_result_applied` also transitions
  the job to `dispatched` (and `mark_result_rejected` to `failed`). A job left in
  `result_received` counts as in-flight forever, so its tenant's dedupe and quota
  paths would never free it — that is the whole point of PR #187.
- **Bounded retries.** Transient failures re-queue with a backoff and an
  incremented attempt count; at `max_attempts` the row is rejected so a
  permanently-failing envelope cannot loop forever.
- **Tenant from the inbox row, never the envelope.** The row's tenant is bound to
  the claimed job by a composite FK, so it is the only trustworthy source.
- **Standalone.** Own repositories and services, argparse CLI, `--once` mode;
  does not read `app.state`, matching the existing executors.
- **Drains even when the protocol is `off`.** Turning ingress off must not strand
  results already accepted while it was on; stopping the container is the
  emergency control.

## Deployment wiring

Service `crawler-agent-inbox-executor` in **both** compose files (compose does not
pass the env file wholesale, so every variable is enumerated), resource bounds +
log rotation + read-only/tmpfs per the runtime-hardening contract, `depends_on`
migrate (the inbox table arrives in 034). Env template gained the two runtime
tuning vars; the three compose-only resource vars went into `TEMPLATE_ONLY_VARS`.
Docs: DEPLOYMENT, LIGHTSAIL, and a REMOTE_LOCAL_CRAWLER warning that this service
must NOT be scaled to zero alongside `discovery-executor` — it never claims
discovery jobs and cannot contend with the Mac crawler.

## QCHECK — Tier 2 (Codex gpt-5.6-sol, xhigh) — verdict: REFUTED, then fixed

| # | Finding | Sev | Disposition |
|---|---|---|---|
| C1 | **A malformed discovery batch is partially applied, then permanently rejected.** Validation happened while iterating, so leading projects persisted, a later bad entry raised, and the whole row was rejected — trailing entries lost forever, and a rejected row is never retried. Codex reproduced it. | HIGH | **FIXED.** Two-phase: build every event first, apply only after the whole batch validates. New test; proved non-vacuous by mutation (restoring apply-while-validating fails exactly it). |
| C2 | **The standalone runtime silently disabled NEW_PROJECT notifications** — the API wires an entitlement-aware dispatcher, the executor did not. It also contradicted my own docstring, which listed notification duplication as a risk. | HIGH | **ACCEPTED + MADE LOUD, not wired.** The gated dispatcher needs the entitlement/notification/SMTP stack; building it into a standalone executor is U8-sized. Now an explicit docstring section, a startup log line, and a corrected duplicate-delivery claim. Silent behavioural drift became a stated, logged gap. |
| C3 | **Rollback instructions were broken both ways** — DEPLOYMENT named the new service in a restart against a SHA that does not define it (Compose rejects the whole command); LIGHTSAIL omitted it entirely (orphan container against an older schema). | HIGH | **FIXED.** Stop before checkout, restart with `--remove-orphans`, and an explicit "rolling back past U7c" note in both runbooks. |
| C4 | **An expired-but-unreclaimed processor could still terminalize a row** — the three mark guards checked token + `processing` but not lease liveness. | MEDIUM | **FIXED.** All three now require `processing_expires_at > now`. New test asserts an expired lease cannot mark applied. Lost-lease outcomes are surfaced instead of ignored. |
| C5 | **Repeated hard crashes bypassed the retry budget forever.** Reclaim reset to `pending` without incrementing `attempt_count`, so a poison row that OOM-kills the process cycles endlessly, holds its job in `result_received`, and — being the oldest due row — keeps killing the executor before later rows are reached. | MEDIUM | **FIXED.** Reclaim now consumes a retry attempt, so crash loops are covered by the same budget. |
| C6 | **The local Compose stack no longer rendered** — I copied the production `${EGP_POSTGRES_PASSWORD:?}` form into the localdev file, breaking *every* local compose command. | MEDIUM | **FIXED** (`:-egp_dev`), verified empirically with `env -u EGP_POSTGRES_PASSWORD docker compose config -q`, and pinned by a test that asserts the interpolation form — YAML parsing alone could not catch it. |
| C7 | SQLite bootstrap lacks the composite FK and indexes PostgreSQL has; both terminal methods ignored the job update's `rowcount`. | MEDIUM | **PARTIALLY FIXED.** The ignored rowcount is now a `JobReleaseFailedError` — a terminal inbox row must never commit while its job stays in-flight. Full SQLite DDL parity is still not modelled; recorded, as in U7b. |

### Vacuous tests Codex identified — all four strengthened
- Tenant test asserted only "not the attacker UUID" → now asserts **equality** with the job's owning tenant.
- Backoff test never checked `next_attempt_at` → now asserts the retry is genuinely in the future (zero backoff would have passed).
- Reclaim test permitted a final status of `processing` → now requires a terminal `applied`, plus the incremented attempt count.
- Compose test only parsed YAML → added a direct assertion on the interpolation form.

Codex's pytest could not run (read-only sandbox, no writable temp dir), so its analysis is
static; all execution evidence here is local.

## Gates (local only — CI dead, E0)

| Gate | Result |
|---|---|
| ruff | clean |
| pytest **3× consecutive** (clean run, no edits mid-gate) | **1320 / 1320 / 1320 passed**, 2 skipped, 0 failed |
| baseline `main@35b43529` | 1307 passed, 2 skipped |
| `docker compose -f docker-compose-localdev.yml config -q` without `EGP_POSTGRES_PASSWORD` | renders (C6 verified empirically) |
| env-template drift + runtime-image-hardening + compose topology | green |

Net new tests: 13 (11 processor + compose topology + localdev interpolation).

Note: an earlier 3× attempt showed 1319/1320/1320 because a test was added while run 1
was executing. That is an edit-during-gate artefact, not flakiness — the gate was re-run
clean on frozen code and is the result recorded above.
