# DREP: F7 Truthful Fault Injection

## Section 0: Repository profile

- DREP ID: `EGP-F7-TRUTHFUL-FAULT-INJECTION-20260815`
- Repository root: `/Users/subhajlimanond/dev/egp-f7-truthful-fault-injection`
- Branch: `fix/f7-truthful-fault-injection`
- Baseline SHA: `d2bc0d807a6806ba54ec802c6b02f2cc2b5bf82e`
- Verified main: local `main`, local `origin/main`, and GitHub `refs/heads/main` all equal the baseline.
- Baseline status: clean in this isolated worktree.
- Protected dirty primary paths: the two modified Coding Logs, three untracked Coding
  Log/DREP files, `docs/TOR KEYWORDS.md`, and `test.sqlite3` recorded in the session Coding Log.
- Pre-existing worktrees: all six baseline registrations recorded in the session Coding Log are
  user-owned and outside cleanup scope.
- Applicable policy: root `AGENTS.md`, root `CLAUDE.md`, `apps/api/AGENTS.md`,
  `apps/worker/AGENTS.md`, `packages/AGENTS.md`, `packages/db/AGENTS.md`, and
  `packages/shared-types/AGENTS.md`. Tests-first, Python 3.12+, typed public functions, Ruff line
  length 100, PostgreSQL system of record, tenant isolation, no secrets, no direct push to main,
  no deployment, and no crawler-agent activation are mandatory.
- Languages/versions: Python `>=3.12`; Ruff `0.15.9`; PostgreSQL 15+ runtime semantics.
- Migration policy: no migration is permitted or required.
- Coding Log pointer: this worktree's ignored `.codex/coding-log.current` resolves to the new F7
  Coding Log. The dirty primary pointer was read but not changed.
- External-model mode: g2 stateless proposal route was inspected, and the local-only `g2-doctor`
  passed with zero failures. This DREP's actual DeepSeek budget is zero, so no bundle or external
  request is permitted.
- Scoped gate:
  `./.venv/bin/python -m pytest tests/phase1/test_truthful_fault_injection.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_structured_logging.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_persistent_browser_profile.py -q`.
- Full gates: `uv lock --check`; Ruff check and format-check for `apps/ packages/ tests/ scripts/`;
  Python compileall; full `pytest tests/ apps/ packages/ -v --tb=short`; affected scope repeated
  three times. Use the verified primary `.venv` interpreter with worktree-first `PYTHONPATH` if
  the clean worktree has no virtual environment.

## Section 1: Goal, non-goals, and success

Canonical F7 replaces PR #202's synthetic pre-spawn exceptions with an operator/test-only harness
whose accepted modes produce real child-process timeout, positive nonzero, missing-result, and
signal outcomes. Every reserved injected run, including an internally supplied unknown mode, must
be terminalized through the real dispatcher cleanup path while normal discovery behavior remains
unchanged.

Non-goals: do not recreate PR #202; do not modify F6/PR #208, migrations, candidate vocabulary,
F4 ledger authority, F5 all-path abnormal reconciliation, F8 evidence retention, API routes,
deployment, activation, or crawler-agent delivery. `EGP_CRAWLER_AGENT_PROTOCOL` remains `off`.

Success criteria:

- `test_every_injected_fault_terminalizes_run` observes real subprocesses for every accepted mode,
  a terminal failed run with the exact failure reason, a reaped child/process group, and bounded
  structured audit evidence.
- Operator injection requires the explicit environment gate, `--fault-mode`, `--once`, `--limit
  1`, and crawler-agent protocol `off`; denial happens before runtime construction or job claim.
- An internal unknown mode is rejected after reservation without spawning and still terminalizes
  that run with `dispatch_exception`.
- Disabled production dispatch still invokes `python -m egp_worker.main` with the configured
  timeout, existing lease handling, result framing, profile cleanup, and retry disposition.
- No public API or database schema changes. The internal request seam remains optional and defaults
  to `None`.
- Audit records contain mode, source, run id/PIDs where available, release SHA, and failure code;
  they contain no payload, database URL, token, or secret.
- Rollout is source-only merge. Rollback is a normal revert of the F7 commit before any later F4/F5
  dependency lands. No runtime rollout is authorized in this lifecycle.

## Section 2: Requirements (`R1..Rn`)

- `R1`: Each accepted mode (`worker_timeout`, `nonzero_exit`, `missing_result`,
  `entitlement_denied`, `worker_crash`) launches the fixed `egp_worker.fault_injection` child after
  run reservation and reaches the existing real process-result handler.
- `R2`: Every accepted injected mode terminalizes the reserved run as failed with `finished_at` and
  its exact stable `DiscoveryFailureCode` value. Audit may say `terminalized` only after the run
  repository confirms the active-to-failed transition; persistence failure is a distinct event.
- `R3`: Timeout kills and drains the real process group before run terminalization; every accepted
  child and every unexpectedly surviving child is killed and explicitly reaped before temporary
  profile cleanup. Injected setup failures after reservation also terminalize the run.
- `R4`: An internally supplied unknown mode reserves exactly one run, spawns no child, fails the
  run with `dispatch_exception`, and emits invalid-mode audit evidence.
- `R5`: Operator injection is denied before log rotation, runtime construction, or job claim unless
  the explicit environment flag is `true`, execution is one-shot, limit is exactly one, an exact
  pre-created non-live canary discovery-job UUID and its expected tenant UUID are supplied, and
  `EGP_CRAWLER_AGENT_PROTOCOL` is `off`.
- `R6`: Authorized operator injection passes exactly one validated mode, non-live canary job UUID,
  and expected tenant UUID into the standalone discovery runtime; claims only the row carrying the
  reserved `fault_injection` trigger; terminally fails the queue row even for normally retriable
  outcomes; emits bounded authorization evidence; and exits nonzero unless the disposition belongs
  to that exact canary and durable run/candidate cleanup plus the exact mode-specific child return
  code and failure code are all verified.
- `R7`: Normal dispatch with no fault mode preserves its command, timeout, result, lease,
  process-group, profile, and job-disposition behavior.
- `R8`: Candidate reconciliation remains the existing best-effort, injection-only call; this slice
  does not claim F5 all-path or transactional reconciliation closure.
- `R9`: Compose/example wiring defaults the new authorization flag to false and the discovery
  executor's crawler-agent protocol to off; no mode is persisted in environment configuration.
- `R10`: No DeepSeek request occurs; all code, tests, integration, reviews, and lifecycle work are
  primary-owned.

## Section 3: File contract (`F1..Fn`)

| ID | Path | Action | Anchor | Exports/contracts | Purpose |
|---|---|---|---|---|---|
| `F1` | `apps/api/src/egp_api/services/discovery_worker_dispatcher.py` | MODIFY | `_simulate_fault()` / `SubprocessDiscoveryDispatcher.dispatch_cancellable()` | internal request signature unchanged | fixed child command, injected timeout, terminalization/audit |
| `F2` | `apps/api/src/egp_api/executors/discovery_dispatch.py` | MODIFY | `build_discovery_dispatch_runtime()`, `_build_parser()`, `main()` | optional runtime kwarg and CLI flag | operator gate and runtime wiring |
| `F3` | `apps/api/src/egp_api/services/discovery_dispatch.py` | MODIFY | `DiscoveryDispatchRequest.fault_mode` | optional field remains | truthful test seam documentation |
| `F4` | `apps/worker/src/egp_worker/fault_injection.py` | CREATE | module `main()` | fixed internal module only | produce real child outcomes without browser/DB access |
| `F5` | `tests/phase1/test_truthful_fault_injection.py` | CREATE | named F7 acceptance test | test only | real subprocess/run terminalization oracle |
| `F6` | `tests/phase1/test_structured_logging.py` | MODIFY | PR #202 fault tests | generic logging tests retained | remove contradictory synthetic/no-spawn contract |
| `F7` | `tests/phase2/test_discovery_executor.py` | MODIFY | standalone executor main tests | test only | operator gate/default denial/wiring |
| `F8` | `docker-compose.yml` | MODIFY | discovery executor environment | default false/off only | production-default denial wiring |
| `F9` | `docker-compose-localdev.yml` | MODIFY | discovery executor environment | default false/off only | local-default denial wiring |
| `F10` | `.env.remotecrawl.example` | MODIFY | discovery settings | example only | explicit false authorization flag |
| `F11` | `coding-logs/2026-08-15-10-10-39 DREP (f7-truthful-fault-injection).md` | CREATE | whole file | lifecycle artifact | locked plan |
| `F12` | `coding-logs/2026-08-15-10-10-39 Coding Log (f7-truthful-fault-injection).md` | CREATE | whole file | lifecycle artifact | evidence/review/landing ledger |
| `F13` | `deploy/.env.production.example` | MODIFY | discovery lease settings | default false only | production template parity for the authorization gate |
| `F14` | `packages/db/src/egp_db/repositories/discovery_job_repo.py` | MODIFY | claimable/claim queries | optional job/tenant/live/trigger include and exclude selectors | isolate the reserved canary row from both fault and ordinary executors |
| `F15` | `tests/phase2/test_discovery_dispatch.py` | MODIFY | processor/repository claim tests | test only | prove exact canary-job targeting and preserve normal claims |

Primary-owned seams: every file above. DeepSeek production allowlist: none.

## Section 4: Function contract (`FN1..FNn`)

`FN1 _fault_worker_command(fault_mode: str) -> list[str]`
File: `F1`. Does: returns a fixed harness command for an accepted mode or raises a non-retriable
`dispatch_exception` for an unknown internal mode. Pre: run already reserved. Post: no child has
been spawned. Errors: unknown modes fail closed. Invariant: user text is never interpolated into
code or shell. Caller: `SubprocessDiscoveryDispatcher.dispatch_cancellable()`.

`FN2 SubprocessDiscoveryDispatcher.dispatch_cancellable(request, *, cancellation_event) -> None`
File: `F1`. Does: reserves the run, resolves the injected/normal child, launches it in a new
session, passes the normal bounded payload, and maps the observed real result. Post: every injected
failure run is failed before return/raise; child cleanup and profile cleanup complete. Errors:
existing typed dispatcher errors are preserved. Invariant: non-injected semantics are unchanged.
Caller: `DiscoveryDispatchProcessor.process_job()`.

`FN3 _terminalize_injected_run(...) -> None`
File: `F1`. Does: for an injected-only failure, invokes existing candidate reconciliation and
`fail_run_if_active`, then appends bounded terminalization audit evidence. Post: best-effort
idempotent cleanup was attempted once for handlers that did not already terminalize. Errors:
cleanup failures are logged and never replace the original dispatcher exception. Caller:
`dispatch_cancellable()` exception handlers.

`FN4 build_discovery_dispatch_runtime(..., fault_mode: str | None = None, fault_job_id: str | None = None, fault_tenant_id: str | None = None) -> DiscoveryDispatchRuntime`
File: `F2`. Does: constructs the normal runtime, pins one validated operator mode into the
authorized dispatcher, and constrains the processor to the exact non-live tenant/canary job while
requiring the reserved trigger, excluding that trigger from normal processors, and forcing terminal
queue disposition. Pre: `main()` already authorized all values. Post:
processor/runtime wiring unchanged otherwise. Caller: standalone
executor `main()`.

`FN5 _authorize_fault_injection(args, environ) -> str | None`
File: `F2`. Does: returns `None` when no injection was requested; otherwise requires flag `true`,
one-shot, limit one, valid canary-job and tenant UUIDs, and protocol off, emits no secrets, and
returns the validated mode. Errors: raises a bounded configuration error before log
rotation/runtime construction. Caller: executor `main()`.

`FN6 main(argv: list[str] | None = None) -> int`
File: `F4`. Does: reads the parent payload fully, then implements one of five fixed outcomes:
timeout wait, positive nonzero, zero/no result, entitlement JSON/nonzero, or self-SIGTERM. Pre:
module receives one accepted mode. Post: never accesses DB/browser/artifact/e-GP. Errors: unknown
mode exits nonzero. Caller: dispatcher subprocess command.

## Section 5: Test contract (`T1..Tn`)

`T1 test_every_injected_fault_terminalizes_run`
File: `F5`. Covers: `R1,R2,R3,R8`. Type: subprocess integration with an in-memory run-repository
spy. Arrange: real child module, fixed short timeout, temporary artifact/profile roots, recorded
Popen kwargs and reconciliation calls. Act: dispatch all accepted modes. Assert: real Popen,
`start_new_session=True`, harness module command, exact error/failure reason, failed terminal run,
reaped child, timeout kill/drain, profile cleanup, and bounded audit events. RED command:
`./.venv/bin/python -m pytest tests/phase1/test_truthful_fault_injection.py::test_every_injected_fault_terminalizes_run -q`.
RED proof: file/test is absent before acceptance authorship; after authorship, current synthetic
pre-spawn behavior violates the Popen and terminal-run assertions.

`T2 test_unknown_injected_fault_terminalizes_reserved_run_without_spawning`
File: `F5`. Covers: `R4`. Type: integration/spy. Assert: one reservation, zero Popen calls,
`dispatch_exception` terminalization, non-retriable error, invalid-mode event.

`T3 test_fault_injection_operator_gate_denies_before_runtime_build`
File: `F7`. Covers: `R5,R9`. Type: unit. Matrix: missing/false flag, non-once, wrong/missing limit,
missing/invalid canary job or tenant, and non-off crawler-agent protocol. Assert: exit 2, log
rotation and runtime factory untouched, denied audit, and arbitrary invalid mode text absent from
logs under both default-disabled and enabled gates.

`T4 test_fault_injection_operator_gate_wires_authorized_mode`
File: `F7`. Covers: `R6`. Type: unit. Arrange exact authorized inputs. Assert validated mode reaches
runtime factory, authorization audit is emitted, and exit zero requires `fault_verified` plus the
exact failure code on the authorized canary job; a matching code without verified evidence or on a
different job returns 4.

`T5 test_normal_dispatch_preserves_worker_command_and_timeout`
File: `F5` plus existing suites. Covers: `R7`. Type: regression. Assert normal worker module,
configured timeout, result framing, existing lease/process/profile behavior.

`T6 existing dispatcher/executor/profile suites`
Files: `F6,F7` and unchanged adjacent tests. Covers: `R7`. Type: regression. Exact GREEN command is
the scoped gate in Section 0. Edge cases: nonzero, missing result, signal, lease cancellation,
malformed result, persistent/ephemeral profile behavior, retries, and one-shot summaries.

`T7 test_env_template_tracks_runtime_egp_vars / test_env_template_covers_all_compose_required_vars`
File: existing `tests/operations/test_env_template.py`. Covers: `R9`. Type: configuration wiring.
RED proof: the full gate reported both tests failing because
`EGP_DISCOVERY_FAULT_INJECTION_ENABLED` was absent from `deploy/.env.production.example`.
GREEN command: `./.venv/bin/python -m pytest tests/operations/test_env_template.py -q`.

`T8 test_fault_target_claims_only_explicit_canary_job`
File: `F15`. Covers: `R5,R6`. Type: SQLite repository/processor integration. Arrange two pending
jobs and target the second non-live row with its tenant UUID. Assert exactly the target is claimed,
its injected failure is terminal, and the unrelated live job remains pending. Negative cases prove
the exact job is rejected independently for wrong tenant, live state, or non-reserved trigger.

`T9 test_normal_processor_excludes_fault_injection_canary`
File: `F15`. Covers: `R5,R6`. Type: SQLite repository/processor integration. Assert an ordinary
processor excludes the reserved `fault_injection` trigger, dispatches only the normal row, and
computes its returned queue snapshot with the same exclusion so a canary-only queue drains instead
of falsely reporting `work_remains`.

`T10 injected exceptional-path terminalization tests`
File: `F5`. Covers: `R2,R3`. Type: negative subprocess/integration. Force post-reservation spool
setup failure, worker-log resolution failure, unexpected communication failure, timeout diagnostic
drain failure, run-repository failure, and a timeout leader with a real long-lived descendant.
Assert every child/process group is terminated and reaped, every reachable run write is attempted,
false terminalization/evidence is never reported, and expected verified modes retain their exact
code.

`T11 test_persisted_fault_canary_traverses_real_child_and_terminalizes_queue`
File: `F15`. Covers: `R1,R2,R5,R6`. Type: SQLite plus real-subprocess integration. Assert a
persisted reserved canary is selected by the production processor, maps to a schema-valid run
trigger, launches the fixed child, produces verified failure evidence, and terminalizes both run
and queue row.

## Section 6: Traceability

| Requirement | Realized by function and call/statement | Tests | Files | Slice |
|---|---|---|---|---|
| `R1` | `FN1` command -> `FN2` Popen/result handlers | `T1,T11` | `F1,F4,F5,F15` | `S1` |
| `R2` | `FN3` -> `_mark_active_run_failed()` -> repository `fail_run_if_active()` | `T1,T10` | `F1,F5` | `S1` |
| `R3` | existing `_kill_process_group()`/drain/finally reap -> profile cleanup | `T1,T6,T10` | `F1,F5` | `S1` |
| `R4` | `FN1` rejection -> `FN3` | `T2` | `F1,F5` | `S1` |
| `R5` | `FN5` before rotation/runtime -> exact canary predicates | `T3,T8,T9,T11` | `F2,F7,F14,F15` | `S2` |
| `R6` | `FN5` -> `FN4` -> isolated processor -> exact job/cleanup/child/code match | `T4,T8,T9,T11` | `F1,F2,F7,F14,F15` | `S2` |
| `R7` | unset-mode branch in `FN1/FN2` | `T5,T6` | `F1,F5,F6,F7` | `S1` |
| `R8` | injected-only call to existing `_reconcile_candidate_attempts()` | `T1` | `F1,F5` | `S1` |
| `R9` | default-false/off environment entries | `T3,T7` plus compose render gate | `F8,F9,F10,F13` | `S2` |
| `R10` | DREP budget and lifecycle evidence | Coding Log review | `F11,F12` | `S1,S2` |

## Section 7: Wiring

| Component | Non-test runtime caller | Registration/config load | Schema/contract evidence |
|---|---|---|---|
| fault harness `FN6` | `FN2` fixed Popen command | packaged `egp_worker` module on existing worker/API image path | no DB/schema access; fixed mode vocabulary |
| injected dispatcher path | `DiscoveryDispatchProcessor.process_job()` -> `dispatch_cancellable()` | `FN4` injects operator mode; request seam supports tests | existing `DiscoveryFailureCode` and `crawl_runs.failure_reason` vocabulary |
| operator gate `FN5` | standalone executor `main()` | CLI mode + canary UUID + strict env flag + protocol loader | denial precedes log rotation/runtime/job claim |
| exact canary claim | `DiscoveryDispatchProcessor._process_pending()` | target job/tenant/non-live/trigger predicates; normal trigger exclusion; forced terminal disposition | injected and ordinary executors cannot race for or misclassify the reserved row |
| run terminalization | `FN3` -> `_mark_active_run_failed()` | existing run repository instance | `fail_run_if_active()` handles queued/running and sets `finished_at` |
| discovery executor defaults | Compose discovery-executor service | explicit false/off values; example env false | no fault mode persisted; agent protocol remains off |

## Section 8: Slice plan (`S1..Sn`)

DeepSeek budget: `0`

Selected DeepSeek slice: `NONE`

| ID | Requirements/files/tests | Mode | Q0-Q3 result | Stop line | Production path/range allowlist | Oracle | Done when |
|---|---|---|---|---|---|---|---|
| `S1` | `R1-R4,R7,R8,R10; F1,F3-F6,F11,F12; T1,T2,T5,T6` | `PRIMARY` | Q0 route healthy; Q1 decisive: persistent process lifecycle/run terminalization is judgment-bound | `PRIMARY` | none | `T1,T2,T5,T6` | primary verifies cleanup, terminalization, gates |
| `S2` | `R5,R6,R9,R10; F2,F7-F10,F12-F15; T3,T4,T7,T8` | `PRIMARY` | Q0 route healthy; Q1 gate/public operator semantics remain primary-owned | `PRIMARY` | none | `T3,T4,T7,T8`, compose render | primary verifies default denial, exact target, and wiring |

No DeepSeek excerpt manifest exists because the budget is zero. Stop if implementation requires a
migration, new failure/candidate vocabulary, public API, F4/F5/F8 behavior, deployment, activation,
or any file outside this contract without first revising the primary-owned DREP.

## Section 9: Gates, review, rollout, and rollback

1. Author/lock `T1-T5`; run exact RED and confirm current pre-spawn/non-terminal behavior.
2. Implement minimal GREEN in `S1`, then `S2`; audit all changed files against this DREP.
3. Run scoped GREEN and the affected scope three consecutive times.
4. Run compileall, Ruff check, Ruff format-check, lock check, full Python suite, and Compose config
   rendering with `EGP_CRAWLER_AGENT_PROTOCOL=off`.
5. Trace runtime wiring with concrete file:line evidence.
6. Perform independent non-DeepSeek QCHECK, then formal `g-check`; disposition every finding and
   rerun material gates after remediation.
7. Commit one Conventional Commit, push one branch, open one PR, inspect required checks, and merge
   only under the user's standing authorized lifecycle. Hosted unavailable/zero-step evidence stays
   distinct from local qualification.
8. Land exact merged SHA on local main without touching protected dirt, verify local/GitHub main,
   and safely close only the session-created worktree.
9. No deployment, activation, crawler restart, protocol flip, rollback execution, or canary claim.

Rollback: before downstream F4/F5 depends on F7, revert the F7 commit/PR. The disabled default
means merely omitting the operator CLI mode leaves the legacy normal path unchanged, but that is a
gate, not a substitute for a source revert if a regression is found.

Known blockers: hosted checks may be GitHub billing/zero-step unavailable; classify them honestly.
No implementation blocker is known at DREP lock time.

## Section 10: Do-not-touch and baseline

- Do not touch F6/PR #208 or migration 039, PR #202 history, migrations, candidate-terminal
  vocabulary, API routes, auth/tenancy, agent-runtime code, F4/F5/F8, deployment, or activation.
- Do not touch the dirty primary checkout, its Coding Log pointer, its seven protected dirty/untracked
  paths, or any of the six pre-existing worktree registrations.
- Tests, fixtures, seams, DREP, Coding Log, Git state, and all production files are primary-owned.
- Baseline SHA/status: `d2bc0d807a6806ba54ec802c6b02f2cc2b5bf82e`, clean isolated worktree.
- After implementation, compare the complete changed-file set to `F1-F15`, inspect every hunk,
  verify acceptance-test hashes, and reject any unexplained file.

## Decision-complete checklist

- All `R`, `F`, `FN`, `T`, and `S` references resolve.
- Every requirement maps to a runtime call site and test/evidence.
- All new wiring has a caller and configuration/contract row.
- Exact RED commands and predicted failures are executable.
- DeepSeek budget is honestly zero; selected slice is none; all slices are primary.
- No architecture, contract, test, review, lifecycle, delivery, or irreversible action is delegated.
