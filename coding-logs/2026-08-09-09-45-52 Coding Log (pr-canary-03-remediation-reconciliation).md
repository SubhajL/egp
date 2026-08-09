# Coding Log: PR-CANARY-03 Remediation Reconciliation (F1-F8)

Started: 2026-08-09 09:45:52 +0700

## Source request

Steps 2-3 of the correctness-first remediation sequence: reconcile the scattered
PR-CANARY remediation records into ONE canonical F1-F8 status/ownership table, and
resolve the migration-number collision, before any further slice is planned. This log
is documentation only; it changes no production code.

## Why reconciliation is needed

The F-numbering was introduced by the consolidated PR-CANARY-01..03 review
(Findings 2026-08-06 07:48:44 +07, reviewed at `main == origin/main == 5e34e3ac`),
which lives in an **untracked** file in the `egp-ops-main` worktree:
`coding-logs/2026-08-05-17-58-04 Coding Log (crawler-completeness-parity-canary-hardening).md`.
The slice charters were then scattered across four tracked logs/DREPs (F1, F2, F3,
and the #203 candidate-accounting log), each defining its own non-goals by pointing
at other F-numbers. No single tracked file stated what F1-F8 are, which have landed,
and what still blocks the canary. This log is now that canonical record; the
condensed charters below restate the review obligations so the numbering survives
even if the untracked source is lost.

## Sources reconciled

- Consolidated review findings 2026-08-06 07:48:44 +07 (untracked, `egp-ops-main`
  worktree, appended to the 2026-08-05-17-58-04 Coding Log) — authoritative
  F-numbering source: 8 HIGH + 4 MEDIUM findings across logical PR-CANARY-01..03.
- `coding-logs/2026-08-06-14-00-00 Coding Log (pr-canary-03-candidate-accounting).md` (#203)
- `coding-logs/2026-08-06-16-00-00 {DREP,Coding Log} (pr-canary-03-f1-postgres-dialect).md` (#204)
- `coding-logs/2026-08-06-18-00-00 {DREP,Coding Log} (pr-canary-03-f2-pre-detail-ledger).md` (#205)
- `coding-logs/2026-08-06-12-53-19 {DREP,Coding Log} (pr-canary-03-f3-typed-browser).md` (#206)
- `docs/MIGRATION_POLICY.md` and the landed migration set (maximum prefix `038`).

## Canonical logical-PR mapping

| Logical unit | GitHub PRs | Merge SHAs | Notes |
|---|---|---|---|
| PR-CANARY-01 | #199, #200, #201 | `0f277d29`, `15bf2f94`, `73a44e66` | structured logging, framing, redaction + remediation + hardening |
| PR-CANARY-01 fault-injection supplement | #202 | `c9b9676b` | **Relabeled** by the 07:48:44 review: #202 implements dispatcher `fault_mode` only, NOT the frozen PR-CANARY-02 typed-browser contract |
| PR-CANARY-02 (frozen typed-browser contract) | #206 | `98509f92` | Implemented as slice **F3** in the remediation numbering |
| PR-CANARY-03 | #203, #204, #205 + pending F4/F5/F6/identity | `5e34e3ac`, `561200ba`, `7a6586f6` | durable candidate accounting + dialect fix + pre-detail ledger |

## Canonical F1-F8 status/ownership table

| Slice | Charter (condensed from source finding) | Source | Status | Order | Migration |
|---|---|---|---|---|---|
| F1 | `record_accepted` must use dialect-correct idempotency: PostgreSQL `ON CONFLICT DO NOTHING` with an explicit SQLite branch, replacing SQLite-only `OR IGNORE` that PostgreSQL rejects | 07:48:44 HIGH 1 | **LANDED** #204 `561200ba` | done | none |
| F2 | Durable `accepted` write BEFORE detail navigation so timeout/browser-death/invalid-detail/`payload is None`/recovery failure after row selection still leaves queryable evidence; fail closed (stop the crawl) if the durable write fails | 07:48:44 HIGH 2 | **LANDED** #205 `7a6586f6` | done | none |
| F3 | Frozen typed-browser contract: typed detail-outcome vocabulary, bounded single classification-specific retry, private redacted diagnostics (screenshot/manifest/SHA), document-evidence-only | 07:48:44 HIGH 3 | **LANDED** #206 `98509f92` | done | none |
| F6 | Candidate-attempt integrity: composite tenant foreign keys `(tenant_id, run_id)` / `(tenant_id, project_id)` with required unique parent keys, typed `terminal_reason` vocabulary (shared enums, not truncated exception text), status/reason/project CHECK combinations, and a typed conflict (REJECTED distinctly) when a terminal row is rewritten to a different state/reason/project — per the F1 log deferral | 07:48:44 HIGH 6 + F1 log line 37 | **PENDING** | 1 (with identity) | **`039`** |
| identity | Content-based `candidate_key` (row-marker/project-number identity, normalized keyword), page/eligible-ordinal/row-marker propagated at acceptance (no `0,0` defaults), identical-terminal replay returns the existing record while contradiction raises the F6 typed conflict; eliminates resume re-keying duplicates | 07:48:44 MEDIUM 3 + F2 DREP §9-D | **PENDING** | 1 (with F6) | shares `039` |
| F7 | Fault injection must be truthful: every injected/unknown mode leaves the reserved run terminal (or injection moves before run reservation), injected faults exercise the REAL cleanup branches (timeout kill/drain/reconciliation, nonzero/missing-result handlers), and the entry point is operator/test-gated with production-default denial and audit evidence | 07:48:44 HIGH 7 + MEDIUM 4 | **PENDING** | 2 | none |
| F4 | Ledger finalization becomes run authority: wire `finalize_dropped` at the post-detail dedup seam — at `98509f92` this is `browser_discovery.py:787-799`, where a payload whose `dedupe_key` is already in `seen_keys` is silently skipped and its `accepted` row never terminalizes (the F2 log cited `:610`; the line drifted after F3) — make `finalize_persisted`/`finalize_failed` fail closed, derive run final summary and keyword `ok/partial/failed` outcomes from the ledger (`get_run_candidate_summary`, `candidate_attempt_repo.py:368`, currently has no production caller), and forbid `succeeded` with open `accepted` rows | 07:48:44 HIGH 4 + F2 log deferral 1 | **PENDING** | 3 | none |
| F5 | Tenant-scoped reconciliation on EVERY abnormal terminal path — positive nonzero exit, missing/invalid result, generic `DiscoverySpawnError`, unexpected exception, cancellation — plus agent-runtime crawl/process loss; canonical `worker_lost`/`cancelled` reasons; prove agent lease expiry/retry cannot leave open rows | 07:48:44 HIGH 5 + F2 log deferral 2 | **PENDING** | 4 | none |
| F8 | Observability architecture: one ordered sequence-preserving child stdout/stderr capture path, persisted-stream secret redaction (not preview-only), bounded per-run evidence size/age/quota retention that protects profiles/manifests, and complete lifecycle correlation (run/job/PID/backend) with deploy-injected release identity for native and agent runtimes | 07:48:44 HIGH 8 + MEDIUM 1 + MEDIUM 2 | **PENDING** | 5 | none |

Latent known defect carried by F2 (explicitly chartered, not a new finding): the
`accepted` ledger can over-count on healthy runs via post-detail dedup and
browser-closed resume re-keying (F2 DREP §9-D). It is closed jointly by the
identity slice (collision-free key), F4 (`finalize_dropped` + run authority), and
F5 (reconciliation of leftover rows).

Out of F1-F8 scope, recorded but unscheduled: **PR-07** dispatcher/API plumbing
(diagnostics payload propagation to the API, diagnostic retention, metrics/alerts/
health/docs), noted as follow-ups in the F3 DREP.

## Ordering rationale (correctness-first)

1. **F6 + identity before F4.** F4 cannot safely forbid open `accepted` rows while
   position-based resume re-keying can create *legitimate* orphans: a
   browser-closed resume re-scans the row with the logical page reset, creating a
   second position-keyed `accepted` row whose original can never terminalize. The
   content-based key removes the orphan class; F6's typed replay/conflict semantics
   are the API surface F4's fail-closed finalization consumes.
2. **F7 before F4/F5.** Corrected fault injection is the oracle for F4/F5: it must
   reach (or faithfully exercise) the real cleanup boundaries so the F4 run-authority
   and F5 reconciliation tests can prove terminal run/job state instead of asserting
   against simulated exceptions that bypass cleanup.
3. **F4 then F5 then F8**, then step 9: a fresh exact-SHA review of logical
   PR-CANARY-01..03 with real PostgreSQL, browser-failure, fault-injection, and full
   local gates.

## Migration-number resolution

- Landed maximum prefix is `038` (`038_discovery_candidate_attempts.sql`, PR #203).
- Historical duplicate prefixes `002` and `008` are applied history and stay
  untouched per `docs/MIGRATION_POLICY.md`.
- **`039` is hereby allocated to F6** (candidate-attempt integrity + identity
  storage). Verified 2026-08-09: no branch, worktree, or coding log claims `039`.
- **Superseded stale allocations** (the collision): the 2026-07-27
  soft-launch-architecture-hardening plan allocated `034` → U7 (landed as
  `034_crawler_agent_results.sql`, consistent), `035_core_tenant_rls.sql` → U11 and
  `036_remaining_tenant_rls.sql` → U12. Prefixes `035`-`037` were subsequently
  consumed by U8 (`035_crawler_agent_inbox_heartbeats.sql`,
  `036_crawler_agent_shadow_delivery.sql`, `037_crawl_profile_execution_backend.sql`)
  and `038` by PR-CANARY-03. The U11/U12 RLS migrations therefore MUST NOT use
  `035`/`036`; they take the next globally unused prefixes at their own planning
  time (`040`+, after F6's `039`). Plan documents are historical records and are not
  edited retroactively; this log is the canonical allocation record going forward.
- Migration `038` is treated as potentially applied (shipped at `5e34e3ac`; the
  07:48:44 review makes no claim about production application). F6 therefore ships
  `039` as additive/repair DDL and never amends `038` in place.

## Blocking disposition (unchanged)

The 07:48:44 review disposition **BLOCK** stands: PR-CANARY-01/-02/-03 are not
complete; no PR-CANARY-04, no crawler deploy/restart beyond `5e34e3ac`, no shadow
qualification evidence, and no canary flip until F4-F8 land and the step-9
exact-SHA re-review passes.

## Working arrangement for the remediation train

- All slices are implemented in an isolated worktree created from exact `98509f92`
  (`/Users/subhajlimanond/dev/egp-canary03`, detached; frozen env bootstrapped and
  smoke-verified: `tests/phase1/test_candidate_accounting.py` 7/7). The dirty
  primary checkout (two in-progress coding logs, `docs/TOR KEYWORDS.md`,
  `test.sqlite3`) is preserved untouched.
- Each slice follows the g2 lifecycle: g2-planning DREP → g2-coding → g2-qcheck /
  g2-check → PR → admin merge → exact local-main landing, one PR at a time from
  exact new `main`.

## QCHECK record (this slice)

- Change class: documentation only — one new coding-log file; no production code,
  config, schema, or migration file touched.
- Tier 1: direct factual-verification review (docs-only; `/code-review`'s code-bug
  finder angles are inapplicable to a markdown log). Every checkable claim was
  verified against the repo: all eight merge SHAs (`git log`), migration filenames
  and their landing PRs (`034` U7 #186, `035`-`037` U8 #191/#192/#193, `038`
  #203), `finalize_dropped` at `candidate_attempt_repo.py:326` with no production
  caller, `get_run_candidate_summary` at `:368` with test-only callers, the
  `039`-is-unclaimed sweep across branches/worktrees/logs, the MIGRATION_POLICY
  002/008 duplicate record, and the F2 DREP §9-D resume re-key deferral.
- Tier 1 findings: 1 — the F2 log's post-detail dedup seam reference
  (`browser_discovery.py:610`) had drifted after F3; the seam at `98509f92` is
  `:787-799`. **Disposition: fixed** (charter updated with the drift note).
- Tier 2: not triggered — no domain code, contract, security, config, schema, or
  data-model change; the log records a migration-number allocation but ships no
  DDL. Recorded per protocol.
