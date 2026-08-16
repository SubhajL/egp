# Coding Log: F4 F5 F8 ledger evidence

Started: 2026-08-16 07:29:55 +0700

## Protected state and worktree ledger

- Primary checkout `/Users/subhajlimanond/dev/egp` was already dirty and remains user-owned.
- Session worktree `/Users/subhajlimanond/dev/egp-f4-f5-f8` was created from refreshed
  `origin/main` at `7b3e23f001d0d86c83130d30c7ad686f10e3d90d` on branch
  `fix/f4-f5-f8-ledger-evidence`.
- Intended disposition: remove this worktree and prune its registration after PR merge, exact-SHA
  local-main verification, and preservation audit.
- RepoPrompt was bound to the isolated worktree and one focused Context Builder discovery covered
  the dispatcher, worker workflow, candidate/run repositories, observability, migrations, and tests.
- Read-only Terra support independently examined the agent-runtime F5 seam and F8 evidence risks.
- The requested `g2-planning`, `g2-coding`, and `g2-check` skills were not exposed in this session;
  the available `g-planning`, `g-coding`, and `g-check` workflows govern this lifecycle.

## Frozen requirement source

The canonical landed reconciliation record defines the slices as follows:

- F4: wire dropped-candidate finalization, make ledger summary authoritative, derive run/keyword
  outcomes from it, forbid success with open accepted rows, and fail closed on finalization conflicts.
- F5: tenant-scoped reconciliation on every abnormal terminal path, including nonzero exit,
  missing/invalid result, generic dispatch errors, unexpected exceptions, cancellation, lease loss,
  owner restart, and agent-runtime crawl/process loss; the agent must stop at the last confirmed
  lease expiry through a cancellable child-process seam.
- F8: one ordered collector-observed stdout/stderr path, redaction before persistence, bounded
  per-run size plus age/quota retention that cannot touch profiles/manifests, and complete
  run/job/PID/backend/release correlation for native and agent runtimes.

Current `main` already contains F6/identity and F7 prerequisites: PostgreSQL-safe candidate
acceptance, pre-detail acceptance, typed detail outcomes, migration 039 tenant integrity, typed
terminal conflicts, content-based candidate keys, and truthful fault injection.

## Discovery evidence

- `run_discover_workflow()` records acceptance and then swallows `finalize_persisted` /
  `finalize_failed` conflicts and generic errors. It never calls `get_run_candidate_summary()` and
  computes success from in-memory counts.
- `browser_discovery._collect_keyword_projects()` leaves accepted rows open on terminal `None`
  detail outcomes, recovered project timeouts, and post-detail dedupe.
- `reconcile_open_candidates()` and `fail_run_if_active()` accept only `run_id`; their update/read
  predicates omit `tenant_id`.
- `SubprocessDiscoveryDispatcher.dispatch_cancellable()` reconciles only lease loss, timeout,
  signal, and special fault paths. Ordinary nonzero, missing/invalid/semantic, setup, and unexpected
  failures bypass one or both durable cleanup operations.
- `RunService.reconcile_missing_workers()` fails run rows but does not reconcile their candidates.
- Agent `_LeaseRenewer` retries transport errors without a last-confirmed deadline, and production
  agent execution is in-process, so lease loss cannot stop a blocked browser/workflow.
- Native stderr writes raw to `worker.log`; stdout is spooled and appended after completion. This
  reorders streams, persists secrets, has no file cap, omits job/tenant/backend correlation on many
  records, and leaves per-run age/quota retention unbounded.
- Existing framing is framed-first and malformed-frame fail-closed; F7 relies on process-group
  termination and exact fault outcome verification. Both contracts must remain intact.

## Plan Draft A — shared authoritative lifecycle (baseline)

### Overview

Build one shared tenant-scoped abnormal-completion service and one shared subprocess evidence
collector, then use them from both native dispatch and the agent runtime. F4 closes every normal
candidate path and makes the final ledger read the sole authority for run/keyword publication.

### Files to change

- `packages/db/src/egp_db/repositories/candidate_attempt_repo.py`: require tenant in reconciliation.
- `packages/db/src/egp_db/repositories/run_repo.py`: require tenant in active-run failure and scope
  owner-recovery writes by tenant and run.
- `packages/db/src/egp_db/abnormal_run_completion.py` (new): common completion report/helper.
- `apps/worker/src/egp_worker/browser_discovery.py`: terminal-candidate callback and dedupe drop.
- `apps/worker/src/egp_worker/workflows/discover.py`: finalization state plus ledger authority gate.
- `packages/observability/src/egp_observability/subprocess_evidence.py` (new): writer, collector,
  bounded result decoder, and exact-path retention.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: shared collector and one abnormal
  failure boundary.
- `apps/api/src/egp_api/services/discovery_dispatch.py`: correlation/backend request field and
  cleanup report propagation.
- `apps/api/src/egp_api/services/run_service.py` plus composition sites: missing-owner candidate
  reconciliation and bounded sanitized log reads.
- `apps/worker/src/egp_worker/agent_runtime.py`: last-confirmed deadline and production child runner.
- `docs/OBSERVABILITY.md`, `docs/REMOTE_LOCAL_CRAWLER.md`: evidence and agent cancellation contract.
- Focused phase1/phase2/phase3/phase4 tests listed below.

### Implementation sequence

1. Add repository tenant-isolation and abnormal-completion tests; confirm RED; implement mandatory
   tenant predicates and the common helper; run repository gates.
2. Add browser/workflow candidate tests; confirm RED; thread terminal callbacks, consolidate
   finalization, and add the final ledger authority gate; run worker gates.
3. Add evidence-writer/collector/retention tests; confirm RED; implement shared evidence primitives.
4. Add dispatcher abnormal-exit matrix; confirm RED; replace spool/direct-stderr handling and route
   every post-reservation exception through common completion; preserve F7.
5. Add agent expiry/process tests; confirm RED; implement monotonic expiry and the production
   cancellable child runner using the shared collector and common completion.
6. Update recovery wiring, log API defense, docs, and run scoped/full gates plus reviews.

### Test coverage

- `test_reconcile_open_candidates_requires_matching_tenant` — mismatched tenant mutates zero rows.
- `test_complete_abnormal_run_attempts_both_operations` — cleanup failures never mask one another.
- `test_duplicate_candidate_is_terminalized_dropped` — post-detail duplicate closes exact row.
- `test_terminal_detail_outcome_closes_candidate` — typed detail failure closes accepted row.
- `test_success_requires_zero_open_candidates` — open row forbids success and is terminalized.
- `test_finalization_conflict_fails_run_authority` — contradiction cannot publish success.
- `test_ledger_status_drives_keyword_and_run_outcome` — persisted/failed/unknown counts drive status.
- `test_every_abnormal_exit_reconciles_tenant_run` — complete dispatcher failure matrix, exactly once.
- `test_missing_owner_reconciles_each_tenant_run` — restart recovery closes candidates.
- `test_evidence_redacts_before_first_write` — split-chunk secrets never reach disk.
- `test_evidence_preserves_collector_order_and_stream` — monotonic sequence across both pipes.
- `test_evidence_caps_file_and_preserves_terminal_record` — hard cap with reserved lifecycle bytes.
- `test_evidence_retention_bounds_age_and_tenant_quota` — only exact run logs are removed.
- `test_agent_transport_failures_stop_at_deadline` — transient renewal stops at confirmed expiry.
- `test_agent_lease_loss_kills_and_reaps_child` — cancellation terminates the process group.
- `test_agent_abnormal_exit_reconciles_tenant_run` — agent loss closes only its tenant/run.
- `test_run_log_api_never_returns_raw_secret_or_over_cap` — old and new evidence are safe.

### Decision completeness

- Goal: make the durable ledger and durable evidence authoritative for all native and agent exits.
- Non-goals: no new migration or enum, no API route change, no canary activation/deployment, no V2
  agent redesign, no browser-diagnostic retention change, no legacy fallback, no Graphite stack.
- Public interfaces: internal repository signatures become tenant-required; request correlation gains
  an internal backend value. HTTP routes, CLI flags, environment variables, and schema stay stable.
- Fail closed: ledger query/finalization/conflict/open-row defects fail run/keyword publication.
- Fail open only for optional evidence storage: crawl may finish if log storage is unavailable, but
  summary status must say `unavailable`; raw output must never become the fallback.
- Rollout: source-only, no migration. Backout is a normal revert before later canary work.
- Evidence bounds: input line 16 KiB; child records 20,000; result frame 256 KiB; fallback/tails
  64 KiB; per-run log 8 MiB with 128 KiB reserved for lifecycle; 30-day age; 512 MiB per tenant.
- Retention may touch only `artifact_root/tenants/<tenant>/runs/<run>/worker.log`, skips active paths,
  and never traverses browser profiles, diagnostics, manifests, or document artifacts.

### Wiring verification

| Component | Runtime entry point | Registration/config | Schema/contract |
|---|---|---|---|
| Candidate ledger authority | `run_discover_workflow()` final publication | existing worker main and agent child | `discovery_candidate_attempts` via tenant+run |
| Candidate terminal callback | `_collect_keyword_projects()` row loop | threaded by `crawl_live_discovery()` | existing 039 terminal vocabulary |
| Abnormal completion helper | native dispatcher and agent child runner | direct imports in both runtimes | candidates + crawl_runs, tenant scoped |
| Evidence collector | native/agent `Popen` observation | direct construction per reserved run | JSONL `worker.log`, no DB schema |
| Evidence retention | evidence close/open boundary | artifact-root tenant/run path | filesystem only, exact worker.log paths |
| Missing-owner reconciliation | `RunService.reconcile_missing_workers()` | existing API startup recovery caller | crawl_runs + candidates |
| Agent deadline/cancellation | `run_once()` production executor | `_build_browser_executor()` | AgentClaim lease_expires_at |

### Dependencies and validation

- Use existing migration 039 vocabulary; recovered project timeout or final-gate leftovers use typed
  `unclassified` and force non-success. No migration number is allocated.
- Reuse existing result frame markers and F7 fault commands.
- Validate focused pytest suites, real PostgreSQL candidate tests, Ruff, compileall, migration
  manifest verification, full Python suite, then three consecutive affected-suite runs.

## Plan Draft B — dispatcher-local capture and cooperative agent cancellation (alternative)

### Overview

Keep F4 and repository tenant changes identical, but implement evidence only inside the API
dispatcher by merging stderr into stdout, and add a cancellation event to the in-process agent
executor. This changes fewer files and initially preserves more existing test fakes.

### Files and sequence

The DB/workflow files match Draft A. Evidence remains in
`discovery_worker_dispatcher.py`; `agent_runtime.py` receives only deadline/event checks; docs scope
F8 to native dispatch. Tests cover merged output and cooperative callbacks rather than a real agent
child process.

### Trade-offs and gaps

- Strength: smaller patch, simpler native output ordering, fewer shared abstractions.
- Gap: merged streams lose stdout/stderr provenance and can confuse unframed-result fallback.
- Gap: a threading event cannot interrupt Playwright/browser calls, so last-confirmed expiry can still
  leave work running and does not satisfy the frozen cancellable child-process seam.
- Gap: agent runtime lacks complete run/job/PID/backend/release evidence, violating F8's explicit
  native-and-agent scope.
- Disposition: rejected. It is easier but does not meet F5/F8 acceptance.

### Decision completeness

Draft B has no migration/API change and the same fail-closed ledger policy, but its agent and
correlation gaps remain material. It is not executable as the final plan.

## Comparative analysis

- Both drafts close F4 and tenant-scope DB mutations.
- Draft A has a single evidence and cancellation contract across native/agent runtimes; Draft B
  duplicates behavior and cannot forcibly stop an agent browser.
- Draft B's merged descriptor gives simple ordering but sacrifices stream identity and result-decoder
  separation. Draft A's selector-based single collector preserves both streams and feeds only stdout
  into the bounded decoder.
- Draft A changes more tests and production wiring, but every added component has a real runtime call
  site and directly satisfies a named requirement. Draft A is selected.

## Unified execution plan

### Overview

Execute Draft A in four TDD slices: F4 ledger authority, shared F5 tenant completion, shared F8
evidence, then agent deadline/child integration. No success/partial result may be published from
in-memory counts until the tenant/run ledger is read and proven closed.

### Locked behavior

1. Every accepted normal candidate becomes persisted, failed, dropped, or unknown. Typed detail
   outcomes finalize failed; post-detail dedupe and late stage finalize dropped; unexplained normal
   leftovers are reconciled to unknown/unclassified and force run failure.
2. Finalization returning `None`, raising a typed conflict, raising any other error, ledger query
   failure, or any accepted/unknown row forces non-success. Ledger failed/unknown counts yield
   partial only when at least one candidate persisted; otherwise failed. Dropped-only may succeed.
3. The aggregate keyword task and `keyword_scans[keyword].outcome` use the same ledger decision as
   the crawl run; a failed authority check cannot leave either succeeded/ok.
4. All post-run-reservation abnormal native exits call `complete_abnormal_run()` exactly once.
   Candidate reconciliation and run failure are attempted independently and their report is attached
   to dispatch errors/F7 evidence.
5. Agent renewal tracks the latest server-confirmed expiry using monotonic time. A 409 or transient
   failures reaching that deadline signal cancellation, kill/reap the isolated child group, reconcile
   tenant/run candidates, fail the run, and submit no result.
6. A selector-driven collector is the only writer of child output. It assigns monotonic sequences in
   collector-observed order, buffers complete lines, redacts before serialization/write, bounds all
   durable and in-memory data, and keeps raw stdout only inside the bounded result decoder.
7. Every evidence record contains explicit tenant/run/job/owner PID/child PID/backend/release fields
   (JSON null when legitimately absent). Manual native runs use null job; agent runs use the claim job.
8. Existing run-log HTTP tenancy stays unchanged; reads are additionally bounded and redacted so
   historical raw logs cannot leak.

### TDD order and functions

1. RED repository tests.
   - `SqlCandidateAttemptRepository.reconcile_open_candidates(*, tenant_id, run_id, reason)` scopes
     the update by both identifiers.
   - `SqlRunRepository.fail_run_if_active(*, tenant_id, run_id, ...)` scopes select/update/readback.
   - `complete_abnormal_run(...) -> AbnormalRunCompletionReport` attempts both writes and records
     counts/success without swallowing evidence.
2. GREEN repository helper; focused accounting/persistence/PostgreSQL tests.
3. RED F4 tests.
   - Browser terminal callback maps existing `ProjectDetailReason` to existing terminal reasons.
   - Workflow `_finalize_candidate()` records all returns/errors/conflicts.
   - Workflow `_apply_candidate_ledger_authority()` reads/reconciles/re-reads and returns one locked
     run/keyword decision.
4. GREEN F4; focused browser/workflow tests and wiring trace.
5. RED evidence tests.
   - `BoundedEvidenceWriter.write_child/write_lifecycle/close` enforces redaction and encoded caps.
   - `observe_child_process()` drains two pipes with one selector, cancellation, timeout, and reap.
   - `BoundedResultDecoder` preserves framed-first/fail-closed behavior.
   - `prune_run_evidence()` enforces exact-path age/quota limits.
6. GREEN evidence; replace native dispatcher capture, then RED/GREEN every abnormal-exit matrix.
7. RED agent deadline/real-child tests; implement `_LeaseRenewer.cancellation_event`, monotonic
   deadline, and production `AgentSubprocessExecutor.execute_cancellable()`.
8. Update missing-owner recovery, run-log defense, docs, and composition wiring.
9. Run scoped gates, three repeats, full gates, independent QCHECK, formal g-check, remediation,
   commit/PR/admin merge, exact-SHA local-main verification, and worktree closeout.

### Acceptance commands

- Focused: candidate accounting/integrity/PostgreSQL, worker browser/live workflow, API spawn,
  truthful fault injection, structured logging, run persistence/API, discovery dispatch, cancellation,
  and crawler-agent runtime suites.
- `uv run --frozen ruff check apps/ packages/ tests/ scripts/`
- `uv run --frozen python -m compileall apps packages`
- `uv run --frozen python -m pytest tests/ apps/ packages/ -q`
- Migration manifest verification and the repo's real-PostgreSQL candidate suites.
- Repeat the complete affected pytest scope three consecutive times after final remediation.

### Decision-complete checklist

- [x] Goal, non-goals, success, failure semantics, bounds, and rollout are locked.
- [x] No schema migration, HTTP route, CLI, or new environment variable is required.
- [x] Every changed internal interface and runtime call site is named.
- [x] Every named behavior has a defect-sensitive test contract.
- [x] Native and agent entry points, registration, and data contracts are wired above.
- [x] Validation commands and exact worktree closeout are specified.

## Implementation unit (2026-08-16 07:36:00 +0700) — tenant-scoped completion primitives

- Goal: make the lowest-level candidate/run abnormal mutations tenant-bound and prove the shared
  completion helper attempts both durable operations independently.
- Files: `candidate_attempt_repo.py`, `run_repo.py`, new `abnormal_run_completion.py`, and focused
  phase1 tests.
- Initial test invocation used the primary editable virtualenv without worktree `PYTHONPATH` and
  failed collection because it resolved `egp_db` from the primary checkout. This was a harness issue,
  not RED evidence.
- Exact RED: `PYTHONPATH=packages/db/src:packages/shared-types/src:packages/crawler-core/src:apps/api/src:apps/worker/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_candidate_accounting.py::test_reconcile_open_candidates_requires_matching_tenant tests/phase1/test_project_and_run_persistence.py::test_run_repository_active_failure_requires_matching_tenant tests/phase1/test_abnormal_run_completion.py -q`.
- Expected/observed RED: two tenant arguments were rejected by the old run-only signatures and both
  shared completion tests reached the deliberate `NotImplementedError` stub; 4 failed.
- GREEN: the same command passed `4 passed in 0.35s`.
- Behavior: candidate reconciliation and active-run failure normalize and predicate both tenant/run;
  `complete_abnormal_run()` catches each cleanup error separately, recognizes already failed or
  cancelled runs, and returns type-only error evidence without persisting exception text.
- Wiring still pending: native dispatcher, missing-owner recovery, and agent child runner will consume
  the helper in their F5 slices. Existing fakes/callers still require atomic signature updates.

## Implementation unit (2026-08-16 07:58:00 +0700) — F4 ledger-authoritative finalization

- Goal: terminalize post-detail exits and make the durable candidate ledger authoritative for run
  and aggregate keyword publication.
- Acceptance tests were written by the primary before production edits. Exact RED: five failures
  proved the missing browser terminal callback, accepted-row reconciliation, and conflict escalation.
- A bounded `terra_implementer` GREEN slice was assigned only
  `browser_discovery.py` and `workflows/discover.py`; its returned changed-file set stayed within that
  allowlist. The primary audited the complete patch and independently reran the locked tests.
- Audit-added RED: ledger-authority failures could publish `failed` with `error_count=0` and no
  durable failure code. Two strengthened assertions failed for that exact reason.
- GREEN behavior: detail-none and post-detail duplicate exits terminalize with existing typed reasons;
  all workflow finalization routes share one conflict/error-aware helper; the run ledger is
  read/reconciled/re-read before publication; accepted leftovers and terminal conflicts force failed;
  failed/unknown ledgers may only yield partial with persisted projects; aggregate keyword outcomes
  follow the same authority result; ledger defects contribute one error and a durable
  `WORKER_REPORTED_FAILURE` code.
- Primary exact GREEN: five locked F4 tests passed. A focused ruff pass then found one unused test
  import, which was removed; the full affected lint/gate rerun remains part of final verification.

## Implementation unit (2026-08-16 08:42:00 +0700) — F5 abnormal completion

- Added one app-agnostic `complete_abnormal_run()` boundary. Candidate reconciliation and active-run
  failure are tenant/run scoped, attempted independently, and return type-only cleanup evidence.
- The native dispatcher now invokes that boundary after every post-reservation abnormal exit:
  cancellation/lease loss, timeout, signal termination, nonzero exit, missing or invalid result,
  semantic worker failure, non-retriable error, setup/serialization failure, and unexpected error.
- Missing-worker restart reconciliation now closes accepted candidates for each failed tenant/run.
- The agent renewer derives a monotonic deadline from the latest server-confirmed expiry. Transient
  renew failures retry only until that deadline; a stale claim or expiry sets one cancellation event.
- The production agent executor is worker-owned (no worker-to-API-service dependency), reserves a
  local run, launches `egp_worker.main` in a new process session, passes the lease cancellation event
  to the shared observer, kills/reaps the process group on abnormal setup/execution, completes the
  tenant/run ledger, and submits no stale result.
- RED/GREEN evidence: a four-mode native abnormal-exit matrix proved missing, invalid, nonzero, and
  unexpected exits all change one accepted row to unknown and fail the run. A short-expiry agent test
  failed as `crawl_failed` before the cancellable seam/deadline existed, then passed as `lease_lost`.

## Implementation unit (2026-08-16 08:42:00 +0700) — F8 evidence

- Added `egp_observability.subprocess_evidence`: one selector observes stdout/stderr, one writer owns
  the monotonic sequence, complete correlation is serialized on every record, and redaction occurs
  before encoded bytes are written.
- Enforced bounds: 16 KiB line, 20,000 records, 256 KiB raw result decoder, 64 KiB diagnostic tail,
  8 MiB run log with 128 KiB lifecycle reserve, 30-day age, and 512 MiB tenant run-log quota.
- Retention enumerates only exact `tenants/<tenant>/runs/<run>/worker.log` paths; profiles and
  manifests are never candidates. Run-log reads are bounded and defensively redact historical raw
  logs.
- Native and agent subprocesses both use the shared observer/writer. Framed results remain
  framed-first and malformed frames fail closed; raw stdout exists only in the bounded decoder.
- Focused evidence RED was a missing module. GREEN passed six evidence tests including real ordered
  two-stream capture, pre-write secret redaction, caps/reserve, cancellation/reap, framed decoding,
  and retention protection.

## Verification checkpoint (2026-08-16 08:49:00 +0700)

- Repository-wide ruff: passed. Python compileall for `apps` and `packages`: passed.
- `uv lock --check` was unavailable because no `uv` executable exists on this host PATH or the
  repository virtualenv; this is recorded as unavailable, not passing.
- Broad phase/API compatibility gate initially found four issues: a forbidden worker-to-API-service
  import, SQL-ledger auto-wiring against fake non-UUID run ids, and timeout diagnostics preferring
  the structured log over returned stderr. All four focused reproductions pass after remediation.
- Three consecutive complete affected-suite runs passed: `318 passed` each (954 total executions),
  with only pre-existing FastAPI/SQLite deprecation warnings.

## Remediation and final verification (2026-08-16 08:53:49 +0700)

- Independent QCHECK initially found seven blocking gaps: long unterminated secret lines were split
  before redaction; lifecycle extras were not recursively redacted; failed abnormal-completion
  reports were discarded in agent/missing-worker paths; direct workflow exceptions could bypass
  candidate reconciliation; evidence tenant paths and retention deletion were not traversal/race
  safe; append mode reset sequence/record bounds; and agent evidence-close errors could mask a
  completed result.
- Remediation made long lines one bounded redacted record and discards their overflow, recursively
  redacts lifecycle values, requires exclusive fresh log creation, persists type-only incomplete
  completion evidence, reconciles direct workflow failures, validates evidence path segments,
  traverses and deletes retention targets with descriptor-relative `O_NOFOLLOW`, and contains close
  failures while recording their type. Adversarial credential-boundary, append-existing,
  traversal, pre-existing symlink, injected directory-swap, missing-worker cleanup failure,
  direct-workflow crash, and close-failure tests were added.
- The same independent reviewer reran 124 focused tests after the first remediation and then audited
  the descriptor-relative retention change separately. Its final disposition cleared every prior
  finding; the final evidence file passed 11/11 focused tests.
- Primary repository-wide gates after final remediation: ruff passed, compileall passed, and the
  full suite passed `1775 passed, 3 skipped` with only pre-existing dependency warnings. The three
  final affected-suite repetitions each passed `324 passed` (972 recorded executions).
- Migration manifest verification passed for all 41 SQL files. The existing primary local Postgres
  container remained healthy on port 5434 and the migration runner completed through migration 039;
  no migration files changed in this branch. A failed worktree-local Compose start created only an
  unused network/volumes due to the existing fixed container name; those exact generated resources
  were removed, while the primary `egp-postgres` container was left running and healthy.
- `uv lock --check` remains unavailable because this host has no `uv` executable on PATH or in the
  repository virtualenv; it is not reported as passing. The committed lock was not modified.

## Review (2026-08-16 08:53:49 +0700) - F4/F5/F8 working tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-f4-f5-f8`
- Branch: `fix/f4-f5-f8-ledger-evidence`
- Scope: working tree based on `7b3e23f001d0d86c83130d30c7ad686f10e3d90d`
- Commands Run: `git status --short`; staged/unstaged `git diff --stat` and `git diff --check`;
  targeted staged diffs and exact-string searches for candidate finalization, abnormal completion,
  subprocess observation/redaction/bounds, retention, agent cancellation, and runtime wiring;
  focused pytest; three affected-suite repeats; repository-wide ruff, compileall, and pytest;
  migration-manifest verification and migration runner.
- Discovery note: the required RepoPrompt Context Builder review attempt failed because the tab was
  already MCP-controlled. Per g-check fallback policy it was not retried; review used targeted
  staged diffs, exact-string searches, related tests/wiring, and the independent QCHECK evidence.

### Findings
CRITICAL
- No findings.

HIGH
- No findings. All seven initial independent QCHECK blockers were remediated and independently
  rechecked; the final retention TOCTOU finding was cleared after descriptor-relative no-follow
  deletion and its injected swap test.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Local PostgreSQL-binary fixtures remain skipped because `initdb`/`pg_ctl`/`psql` are unavailable
  on PATH. The external healthy Postgres migration gate passed, but those three self-hosted-cluster
  tests did not execute in this environment.
- `uv lock --check` is unavailable locally as recorded above; no dependency or lockfile changed.

### Recommended Tests / Validation
- Preserve the repository-wide ruff/compileall/full-pytest gates and the affected F4/F5/F8 suites as
  required PR checks. Do not classify a no-step billing-locked hosted job as passing.
- If a runner with local PostgreSQL binaries is available, execute the three skipped temporary-
  cluster tests as supplemental evidence; no source defect is currently indicated by their skip.

### Rollout Notes
- No schema migration, new HTTP route, CLI flag, or environment variable is introduced.
- Native and agent subprocesses now share the bounded observer/evidence contract. Fresh run UUID log
  paths are exclusive by design; an existing `worker.log` fails evidence creation rather than
  appending duplicate sequence space.
- Candidate-ledger authority may convert previously optimistic partial/success publication to failed
  when accepted rows remain or terminal conflicts occur. This is the intended fail-closed behavior.
