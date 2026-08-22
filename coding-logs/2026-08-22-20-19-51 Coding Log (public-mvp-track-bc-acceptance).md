# Coding Log: Public MVP Track B + Track C Acceptance

Created: 2026-08-22 20:19:51 Asia/Bangkok
Baseline: `846f82869945fb742eeba3c78ec5c52ece16b6b6` (`origin/main`)
Branch: `feat/public-mvp-track-bc-acceptance`
Worktree: `/Users/subhajlimanond/dev/egp-public-mvp-track-bc`

## Requirements and current-state reconciliation

The authoritative request is the 19-item public-MVP sequence in
`/Users/subhajlimanond/.codex/attachments/91d1f39c-b421-49d1-8704-9db09f604d7d/pasted-text-1.txt`.
Its goal is Track B public control plane plus Track C native Mac legacy crawler, not the HTTP
crawler-agent backend. The source baseline already contains the F01-F08 correctness train and PR
#221 release provenance. The prior operational record proves only that the target was older, at
migration 037, with the Mac profile blocked; it is not current acceptance.

Items already source-supported but still requiring governed execution: clean exact-SHA release
worktree; source gates; DB/artifact backups; immutable Track B images; OCI/baked-SHA smoke;
`discovery-executor=0`; protocol off; legacy routing; Mac clean-SHA stamping; profile doctor and
warm recovery; one-shot `crawl 1`.

Source gaps that must close before the campaign can be truthfully completed:

1. migration application has no PostgreSQL advisory lock;
2. migration 039's seven repair counts are prose, not a reusable read-only evidence command;
3. the legacy queue snapshot has no oldest-claimable age;
4. there is no one-command, sanitized verifier for the complete canary chain and cross-plane SHA;
5. there is no bounded supervised interval or launchd prerequisite tied to accepted evidence.

RepoPrompt was bound to this exact worktree. Its Context Builder was unavailable because the tab
was already MCP-controlled, so repository discovery used RepoPrompt tree/search/read plus targeted
exact-string inspection. Inspected paths include `scripts/release_compose.sh`,
`scripts/smoke_runtime_images.sh`, `scripts/run_remote_crawl.sh`,
`scripts/remote_crawl_guard.py`, `scripts/install_launchd.sh`,
`apps/api/src/egp_api/executors/discovery_dispatch.py`,
`apps/api/src/egp_api/executors/discovery_doctor.py`,
`packages/db/src/egp_db/migration_runner.py`,
`packages/db/src/egp_db/repositories/discovery_job_repo.py`, migrations 038/039,
`tests/operations`, `tests/phase1`, `tests/phase2`, `TRACKS.md`,
`docs/DEPLOYMENT.md`, `docs/BACKUP_AND_RESTORE.md`,
`docs/REMOTE_LOCAL_CRAWLER.md`, and the prior Paths 1-4 acceptance record.

## Plan Draft A: unified acceptance controller

### Overview

Create one Python acceptance controller that owns preflight, migration evidence, runtime parity,
canary verification, supervised observation, and the launchd acceptance receipt. Add migration
locking and queue-age support beneath it. This gives operators one state machine and one JSON
evidence format.

### Files to change

- `packages/db/src/egp_db/migration_runner.py`: nonblocking PostgreSQL advisory lock.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: oldest claimable queue age.
- `scripts/track_bc_acceptance.py`: integrated preflight/verify/supervise/evidence CLI.
- `scripts/run_remote_crawl.sh`: expose bounded supervision.
- `scripts/install_launchd.sh`: require accepted exact-SHA evidence before install.
- `tests/phase1/test_migration_runner.py` and a real-PostgreSQL operations test: lock behavior.
- `tests/phase2/test_discovery_doctor.py`: queue-age serialization.
- `tests/operations/test_track_bc_acceptance.py`: campaign contracts and no-secret output.
- `tests/operations/test_remote_crawl_assets.py`: runner/install wiring.
- `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`: governed execution and rollback.

### Implementation steps

1. Add lock contention tests; confirm the second PostgreSQL migrator fails before SQL execution.
2. Add migration-039 preflight fixture/tests; confirm missing command/import RED.
3. Add queue-age repository/doctor tests; confirm missing field RED.
4. Add controller contract tests for runtime parity, routing, canary chain, and evidence schema.
5. Add supervised interval and install-gate tests; confirm unsupported command/evidence RED.
6. Delegate each sequential production GREEN slice to Luna-Max, verify ownership receipt, rerun
   scoped GREEN, and trace wiring before proceeding.
7. Run full gates, three affected repeats, QCHECK, formal g-check, and remediation.

Functions:

- `acquire_migration_lock(cursor)`: obtain one stable, nonblocking session advisory lock.
- `collect_candidate_integrity_preflight(connection, now)`: seven repair counts, active-run count,
  ledger state, manifest digests; never writes.
- `get_discovery_queue_snapshot(now)`: include `oldest_claimable_age_seconds` for legacy jobs only.
- `verify_runtime_topology(inputs)`: require identical exact SHA, protocol off, executor zero, and
  legacy-only target rows.
- `verify_canary_chain(inputs)`: correlate tenant/job/run, terminal state, zero open accepted
  candidates, artifact retrieval, redacted evidence, dead child, and free profile lock.
- `run_supervised_interval(seconds)`: start the normal watcher in its own process group, terminate
  cleanly at the deadline, and emit a bounded receipt.
- `validate_launchd_evidence(path)`: require exact current SHA, complete stages, freshness, and a
  recorded rollback rehearsal.

### Test coverage

- `test_second_migration_runner_fails_while_lock_held`: serializes real PostgreSQL migration.
- `test_migration_lock_released_after_failure`: later runner succeeds after exception.
- `test_preflight_reports_all_seven_repair_categories`: mirrors migration 039 exactly.
- `test_preflight_absent_038_table_is_zero_and_read_only`: supports 037 target safely.
- `test_preflight_blocks_active_runs`: refuses migration during queued/running work.
- `test_queue_snapshot_reports_oldest_claimable_age`: legacy age is deterministic.
- `test_doctor_json_includes_oldest_claimable_age`: operator contract exposes backlog age.
- `test_runtime_topology_rejects_sha_mismatch`: cross-plane provenance fails closed.
- `test_runtime_topology_rejects_agent_or_executor_enabled`: preserves MVP topology.
- `test_canary_verifier_requires_terminal_correlated_job_and_run`: rejects partial completion.
- `test_canary_verifier_requires_zero_open_candidates`: ledger authority is observable.
- `test_canary_verifier_rejects_unretrievable_artifact`: product evidence must be served.
- `test_canary_verifier_rejects_live_child_or_busy_profile`: cleanup must be complete.
- `test_canary_evidence_is_bounded_redacted_and_sha_correlated`: F8 evidence contract.
- `test_supervised_interval_terminates_process_group`: bounded watcher leaves no child.
- `test_launchd_install_requires_fresh_accepted_receipt`: unattended mode cannot start early.

### Decision completeness

- Goal: make all 19 steps executable, fail-closed, and auditable at one exact merged SHA.
- Non-goals: crawler-agent activation, profile routing to `agent`, F7 production fault injection,
  microservices, RLS rollout, or multiple Mac browser workers.
- Success: source gates and PostgreSQL tests pass; the merged SHA is deployed to Track B and Mac;
  migrations through 039 are recorded; a bounded canary and supervised interval produce accepted
  evidence; launchd is installed only from that evidence.
- Public interfaces: new CLI subcommands and JSON evidence schema; additive queue JSON field;
  no new HTTP endpoint and no database migration.
- Failure mode: every missing/mismatched/unknown input is blocking; telemetry delivery remains
  fail-open only for crawler execution, never for acceptance verdicts.
- Rollout: source merge first; quiesce/back up; count-only preflight; single migrator; immutable
  Track B deploy; Mac cutover; doctor/warm; one-shot; supervised interval; launchd.
- Backout: before migration, restore prior images/process; after 039, never edit history—pause
  writers and fix forward. Keep `discovery-executor=0` during Track C rollback.
- Acceptance commands: scoped pytest per slice; real PostgreSQL lock/preflight tests; Ruff,
  format, compileall, migration manifest, full pytest, three affected repeats, image smoke, then
  the exact runbook commands.

### Dependencies and validation

Requires a real PostgreSQL test target, Docker/Compose for image gates, Mac Chrome/profile for
runtime acceptance, protected production DB/artifact credentials, and explicit deployment/write
authority. Validate JSON against a versioned schema and keep credentials/URLs/tenant payload out
of output.

### Wiring verification

| Component | Entry point | Registration/config load | Schema/contract |
|---|---|---|---|
| migration advisory lock | `egp_db.migration_runner.apply_migrations()` | migrate Compose command/module CLI | `schema_migrations`; session advisory lock |
| 039 preflight | `track_bc_acceptance.py migration-preflight` | controller subparser | 038/039 filenames and seven 039 predicates |
| legacy queue age | `SqlDiscoveryJobRepository.get_discovery_queue_snapshot()` | doctor and one-shot processor imports | `discovery_jobs.created_at`, legacy/pending/lease filters |
| runtime topology verifier | `track_bc_acceptance.py verify-runtime` | controller subparser | OCI/env SHA, protocol, Compose replica count, profile/job backend |
| canary verifier | `track_bc_acceptance.py verify-canary` | controller subparser | discovery job/run/candidate/document/evidence contracts |
| supervised interval | `run_remote_crawl.sh supervise` | shell case dispatch to controller | versioned supervised receipt |
| launchd gate | `install_launchd.sh install --acceptance-evidence` | installer calls controller verifier | exact SHA, timestamps, required accepted stages |

### Comparative risk

Draft A gives a strong operator surface but risks a large, highly privileged script with too many
responsibilities and tests that mock away cross-system behavior.

## Plan Draft B: composable evidence tools and manual governed runbook

### Overview

Add small domain-specific tools: migration preflight, queue age, canary verifier, and bounded
supervisor. Keep deployment commands in a strict runbook and make launchd consume a small evidence
bundle instead of building a monolithic orchestrator.

### Files to change

- `packages/db/src/egp_db/migration_runner.py`: advisory lock.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: queue age.
- `scripts/candidate_integrity_preflight.py`: read-only 039 report.
- `scripts/track_bc_verify.py`: runtime/canary/evidence verification only.
- `scripts/supervise_remote_crawl.py`: bounded process supervision.
- `scripts/run_remote_crawl.sh`, `scripts/install_launchd.sh`: thin wiring.
- Focused tests matching each tool; a new public-MVP operations runbook.

### Implementation steps

Use the same primary-owned RED → Luna-Max GREEN sequence as Draft A, but keep each slice's
allowlist and executable oracle independent. The runbook composes immutable release wrapper,
backup scripts, preflight, migration runner, image smoke, doctor, crawl, verifier, supervisor, and
installer without letting a new tool execute deployment or migration automatically.

Functions and contracts:

- `try_acquire_migration_lock()` and `release_migration_lock()` serialize apply.
- `build_preflight_report()` emits only counts/digests/status.
- `_oldest_claimable_age_seconds()` extends the legacy queue snapshot.
- `verify_runtime_evidence()` and `verify_canary_evidence()` consume explicit sanitized inputs and
  read-only repositories/storage probes.
- `supervise()` owns child process group and emits a versioned receipt.
- `verify_install_prerequisites()` accepts only fresh exact-SHA evidence.

### Test coverage

Use the same named tests as Draft A, split across domain-specific files. Add one integration test
that composes fixture outputs from all tools into an accepted launchd receipt, and mutation tests
for missing stage, wrong SHA, stale timestamp, enabled agent protocol, executor replica, open
candidate, live child, and locked profile.

### Decision completeness

- Goal/non-goals/success criteria and fail-closed policy match Draft A.
- Public interfaces are smaller CLIs and a versioned evidence bundle; no deployment mutation is
  hidden inside Python.
- Operators retain explicit control over backups, migrations, deploy, warm interaction, and canary
  execution; verifiers are read-only except the bounded supervisor and launchd installer.
- Rollout/backout and monitoring thresholds are written once in the runbook.

### Dependencies and validation

Same external dependencies as Draft A. The composable approach enables real PostgreSQL tests for
DB logic, subprocess tests for supervision, and pure fixture tests for evidence validation.

### Wiring verification

| Component | Entry point | Registration/config load | Schema/contract |
|---|---|---|---|
| advisory lock | migration runner CLI/Compose migrate | `apply_migrations()` | `schema_migrations` + advisory key |
| 039 preflight | `candidate_integrity_preflight.py` | direct runbook command | migration 039 predicates |
| queue age | repository snapshot | discovery doctor | legacy discovery queue |
| runtime/canary verifier | `track_bc_verify.py` | direct runbook command | versioned sanitized evidence |
| bounded supervisor | `run_remote_crawl.sh supervise` | shell → supervisor | child exit/heartbeat/queue evidence |
| launchd gate | installer `--acceptance-evidence` | shell → verifier | accepted exact-SHA evidence bundle |

### Comparative risk

Draft B has more files and explicit operator steps, but it keeps privileged deployment and
migration mutation visible, makes each test oracle sharper, and reduces the blast radius of one
buggy controller.

## Comparative analysis and synthesis

Draft A is easier to invoke and produces one state machine, but it conflates read-only proof with
high-impact mutation. Draft B has clearer trust boundaries and aligns better with existing small
scripts, explicit operator authority, and the repository rule that readiness evidence must not
silently perform deployment. Both plans cover all five source gaps and all nineteen operational
steps. Draft B's main weakness—fragmented evidence—is solved by a small common evidence module and
one final verifier, without allowing it to perform deploy or migration.

## Unified Execution Plan

### Overview

Use composable fail-closed tools with one versioned evidence contract. Close the five source gaps
through sequential TDD/Luna slices, deliver and merge one PR, then freeze the merged SHA and execute
the nineteen-step production campaign explicitly from the runbook. Mutation remains visible:
backup, migration, deploy, crawler, and launchd commands are never hidden in an all-powerful
orchestrator.

### Files to change

- `packages/db/src/egp_db/migration_runner.py`: stable nonblocking advisory lock and typed lock
  contention error.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: additive
  `oldest_claimable_age_seconds` field calculated from the exact legacy claimable predicate.
- `scripts/candidate_integrity_preflight.py`: credential-safe, read-only JSON pre/post report.
- `scripts/track_bc_verify.py`: sanitized runtime topology and canary-chain verifier plus evidence
  bundle validator.
- `scripts/supervise_remote_crawl.py`: deadline-based watcher supervision with process-group cleanup.
- `scripts/run_remote_crawl.sh`: `supervise <seconds> --evidence <path>` dispatch.
- `scripts/install_launchd.sh`: require a fresh accepted evidence bundle for install; status and
  uninstall remain available without it.
- `tests/phase1/test_migration_runner.py` and
  `tests/operations/test_migration_runner_postgres.py`: unit and real-PG locking.
- `tests/operations/test_candidate_integrity_preflight.py`: 037/038 states, seven counts,
  active-run block, no writes, postcondition.
- `tests/phase2/test_discovery_doctor.py` and relevant repository tests: oldest age.
- `tests/operations/test_track_bc_verify.py`: runtime/canary/evidence matrix.
- `tests/operations/test_remote_crawl_assets.py`: supervisor and installer wiring.
- `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`: exact commands, authority record, evidence paths,
  monitoring thresholds, backout, and the item 1–19 checklist.

### TDD implementation sequence

#### S1: one PostgreSQL migrator

1. Primary adds contention/release tests and confirms expected RED.
2. Snapshot allowlist: migration runner only.
3. Luna implements `MigrationLockUnavailableError`, stable advisory-key acquisition before ledger
   creation/read, and release in `finally` on the same session.
4. Primary reruns unit + real-PG GREEN and wiring.

#### S2: migration-039 count-only evidence

1. Primary writes tests seeded with every repair category, 037-only absence, active run, and
   post-039 zero-state; confirm command missing RED.
2. Luna adds preflight script only. It uses `DATABASE_URL` from environment, starts `BEGIN READ
   ONLY`, never prints URLs/identifiers, mirrors all seven predicates, records 038/039 ledger and
   manifest digests, and blocks active queued/running runs.
3. Pre-report may contain transform counts; orphan-run deletion requires an exact recorded count
   and explicit authority in the runbook. Post-report requires all seven counts zero and survivor
   delta equal the recorded deletion count.

#### S3: actionable legacy backlog age

1. Primary adds repository and doctor serialization tests with fixed `now`; confirm missing field
   RED.
2. Luna extends `DiscoveryQueueSnapshot` and the aggregate query using the exact claimable legacy
   predicate. No tenant/keyword payload is exposed.
3. Primary reruns repository/doctor/one-shot tests and verifies all constructor consumers.

#### S4: runtime and canary verifier

1. Primary adds pure evidence-validation tests and read-only PostgreSQL/storage-probe integration
   tests for every required chain invariant; confirm missing module RED.
2. Luna adds a thin verifier with explicit subcommands:
   - `runtime`: require exact 40-char SHA equality across merged source, Track B image label/env,
     and Mac; `discovery-executor` replicas zero; protocol `off`; selected profile and all target
     pending jobs `legacy`; doctor ready; heartbeat fresh; oldest age below configured threshold.
   - `canary`: require intended tenant/job/run correlation; terminal job/run; zero open accepted
     candidates; at least one expected artifact record and successful retrieval; bounded/redacted
     JSONL evidence with job/run/release correlation; recorded child PID absent; profile lock free.
   - `bundle`: merge only sanitized stage receipts, reject duplicate/stale/mismatched SHA and any
     missing required invariant.
3. Secrets and raw tenant/business payload never appear in stdout or evidence.

#### S5: supervised interval and unattended gate

1. Primary adds subprocess/process-group, stale receipt, wrong SHA, missing rollback proof, and
   shell-wiring tests; confirm unsupported command RED.
2. Luna implements a supervisor that starts the existing guarded runner's continuous dispatcher,
   observes for a configured 5–60 minute interval, sends TERM to the process group, escalates only
   after a bounded grace period, verifies doctor/heartbeat/queue after exit, and writes a sanitized
   receipt. It never installs launchd.
3. Luna wires `run_remote_crawl.sh supervise` and makes `install_launchd.sh install` require the
   final accepted bundle. `status`/`uninstall` remain recovery-safe.
4. Primary verifies the complete shell/Python runtime chain.

### Test coverage

The named tests from both drafts are mandatory. Every new behavior has a defect-sensitive test;
real PostgreSQL proves lock and SQL semantics, subprocess tests prove cleanup, and pure validators
prove evidence fail-closed behavior. The affected scope runs three consecutive times after final
remediation.

### Decision completeness

- Goal: complete items 1–19 at one exact merged SHA with durable, sanitized evidence.
- Non-goals: agent backend, fault injection, multi-browser concurrency, RLS, migration checksum
  ledger redesign, or changing historical migrations.
- Interfaces: three new Python CLIs, one runner subcommand, one installer option, additive doctor
  JSON field, versioned JSON receipts. No new HTTP API, DB table, migration, or frontend contract.
- High-risk decisions: PostgreSQL migrations serialize with a nonblocking session advisory lock;
  acceptance tools are read-only; pre-039 transform counts are evidence, active runs block; any
  delete count requires exact explicit acknowledgement; only final merged SHA may deploy; unknown
  topology/evidence fails closed.
- Monitoring: heartbeat online and within configured staleness; typed blocker list empty; profile
  ready/free; oldest claimable age threshold initially 6 hours warning/12 hours block for launchd;
  one worker; executor zero; protocol off.
- Rollout/backout: merge first, freeze merge SHA, run exact-SHA gates, record authority, quiesce,
  back up/checksum, preflight, migrate once, postflight, deploy Track B, prove images, cut over Mac,
  warm/doctor, canary, verify, supervise, rehearse uninstall/stop rollback, then install launchd.
- Failure: stop without deleting audit rows or requeueing automatically; retain backups/evidence;
  keep control plane available and crawler paused.
- Completion evidence: PR merge SHA, local/origin equality, gate logs, backup checksums, pre/post
  migration receipts, container/Mac provenance receipts, doctor output, canary receipt, supervised
  receipt, rollback rehearsal, launchd status, and updated operations acceptance record.

### Wiring verification

| Component | Non-test call site | Registration/config load | Schema/contract evidence |
|---|---|---|---|
| advisory lock | Compose `migrate` → module CLI → `apply_migrations()` | existing Docker command | session lock surrounds `schema_migrations` read/apply |
| 039 preflight | runbook direct command | argparse in new script | exact 038/039 names + seven unchanged 039 predicates |
| oldest claimable age | doctor → discovery job repository | existing doctor factory | legacy pending, due retry, expired/unleased predicate + `created_at` |
| runtime verifier | runbook before canary | new CLI `runtime` subparser | SHA/replicas/protocol/backend/doctor evidence schema v1 |
| canary verifier | runbook after `crawl 1` | new CLI `canary` subparser | discovery_jobs, crawl_runs, candidate attempts, documents/storage, JSONL evidence |
| bundle verifier | runbook and installer | new CLI `bundle` subparser | exact SHA, required stages, freshness, rollback rehearsal |
| supervisor | runner `supervise` case | shell execs new script | watcher process group + doctor receipts |
| launchd gate | installer `install --acceptance-evidence` | installer invokes bundle verifier | accepted bundle before plist mutation |

### Cross-language/schema verification

No migration or frontend schema is added. Before S2/S4 tests are locked, exact searches must verify
the live SQL names and fields in Python and migrations: `discovery_jobs` backend/status/lease/run
correlation, `crawl_runs` status/summary, `discovery_candidate_attempts` status/run/project,
`documents` storage key/task relationship, and the storage adapter retrieval method. Generated web
contracts remain untouched because doctor is a CLI contract, not an HTTP response.

### Validation commands

- `./.venv/bin/python -m pytest <each scoped RED/GREEN target> -q`
- real PostgreSQL lock and preflight tests with skips forbidden
- `./.venv/bin/python scripts/check_migration_manifest.py`
- `./.venv/bin/python -m ruff check apps/ packages/ tests/ scripts/`
- `./.venv/bin/python -m ruff format --check apps/ packages/ tests/ scripts/`
- `./.venv/bin/python -m compileall apps packages scripts`
- `bash -n scripts/release_compose.sh scripts/run_remote_crawl.sh scripts/install_launchd.sh`
- affected scope three consecutive times
- full `./.venv/bin/python -m pytest tests/ apps/ packages/ -q`
- trusted-wrapper API/worker image build and `scripts/smoke_runtime_images.sh`
- formal g-check after independent QCHECK

### Operational item 1–19 execution after merge

1. Freeze the exact merge SHA; reject the earlier baseline as deployment identity.
2. Use a clean release worktree at that SHA; preserve dirty primary and old ops worktrees.
3. Run all source/release/image gates and save sanitized receipts.
4. Record the user's explicit deployment/migration/production-write authority in the private
   operations evidence record; never commit credentials or production identifiers.
5. Stop all discovery writers, prove zero active work, back up DB/artifacts, checksum both.
6. Run 039 preflight in read-only mode and explicitly acknowledge exact delete count if nonzero.
7. Run exactly one advisory-locked migrator through 039; run postflight and readiness.
8. Deploy Track B API, webhook executor, and crawler-agent inbox executor from the exact SHA.
9. Verify each image's OCI label and baked env against the merge SHA.
10. Prove Lightsail discovery executor has zero replicas.
11. Prove API protocol is `off`.
12. Prove canary profile and target pending jobs are `legacy`.
13. Stop the old Mac watcher and start from the exact merged-SHA clean worktree.
14. Warm/repair Chrome interactively until doctor is `ready` and profile lock free.
15. Record fresh heartbeat, oldest claimable age, queue counts, and empty typed blocker list.
16. Run exactly one bounded `crawl 1` against the intended low-volume profile/job.
17. Run canary verifier and require every chain invariant accepted.
18. Run one bounded supervised interval and record accepted receipt.
19. Rehearse rollback, build the final evidence bundle, then install and verify launchd.

### Decision-complete checklist

- No public-contract, migration, tenancy, concurrency, or failure-policy decision is left to Luna.
- Every production file will be placed in an exact per-slice allowlist after RED.
- Every behavior has a named defect-sensitive test.
- Every component has a runtime entry point and registration site.
- No historical migration is edited and no new schema is needed.
- Deployment and production mutation occur only after merge at the exact merged SHA.
- The primary owns all tests, receipts, gates, review, PR, merge, landing, deployment, evidence,
  and worktree removal.

## Implementation S1: single PostgreSQL migrator

- Goal: prevent concurrent migration runners from reading the same pending set and racing DDL.
- Primary RED: added real-PostgreSQL contention and failure-release tests in
  `tests/phase1/test_migration_runner.py`.
- Exact RED command used the worktree source through an explicit `PYTHONPATH` and the frozen
  primary virtual environment; result: one expected failure because
  `MIGRATION_ADVISORY_LOCK_KEY` was absent.
- Production allowlist: `packages/db/src/egp_db/migration_runner.py` only.
- Ownership snapshot: `/tmp/egp-trackbc-s1.tGuTmd/snapshot.json`.
- Sole GREEN writer: logical role `luna_implementer`, model `gpt-5.6-luna`, effort `max`.
- Receipt: `/tmp/egp-trackbc-s1.tGuTmd/receipt.json`; SHA-256
  `0b7bbc037d3f6ad00ef442af86ef1516018b2feb9f67156bff34fa9b0bf124f1` for the sole changed
  production file.
- Ownership validator: verified true; exact changed production file set matched the allowlist.
- Primary diff audit: stable integer session lock; nonblocking acquire before ledger creation;
  held on the same connection across commits; rollback plus unlock in `finally`; cleanup does not
  mask a primary migration exception; no schema/migration/CLI change.
- Primary GREEN: three scoped tests passed in 3.62s (one dependency deprecation warning).
- Wiring: existing Compose `migrate` command invokes module `main()` then `apply_migrations()`;
  the lock now encloses the existing `schema_migrations` read/apply path.
- Remaining: S2-S5, full gates, repeats, review, delivery, and runtime campaign.

## Implementation S2: migration-039 count-only pre/postflight

- Goal: replace the manual seven-count procedure with a reusable read-only, sanitized JSON
  evidence command that also supports the current 037 target.
- Primary RED: new `tests/operations/test_candidate_integrity_preflight.py`; the first real-PG
  oracle failed with `ModuleNotFoundError` for the missing script.
- Locked scenarios: candidate table absent at 037; exact seven repair predicates at 038; active
  queued/running crawl blocks; post-039 counts zero and survivor delta equals orphan deletion;
  CLI never prints `DATABASE_URL`; reason vocabulary stays synchronized with the shared enum.
- Production allowlist: `scripts/candidate_integrity_preflight.py` only.
- Snapshot `/tmp/egp-trackbc-s2.5GoE1i/snapshot.json`; receipt
  `/tmp/egp-trackbc-s2.5GoE1i/receipt.json`.
- Sole GREEN writer: `luna_implementer`, `gpt-5.6-luna`, effort `max`.
- Ownership verification: true; sole production file SHA-256
  `5a9c37ab4f6615234d83d11655466ac39d6b87363923a4a912d3f7aaa658cdb8`.
- Primary audit: explicit `BEGIN READ ONLY` and rollback; no mutations; exact manifest digests;
  sanitized error surface; preflight allows visible repairs but blocks active runs; postflight
  requires migration 039, zero violations, and optional exact survivor delta.
- Primary GREEN: 5 passed in 4.09s (one dependency deprecation warning).
- Wiring: governed runbook will call this directly before and after the existing advisory-locked
  migration runner. No runtime registration or database schema change.

## Implementation S3: oldest claimable legacy-job age

- Goal: make backlog staleness actionable without exposing tenant/job/keyword payloads.
- Primary RED: repository snapshot test raised `AttributeError`; doctor caught the incompatible
  snapshot constructor and degraded to blocked `queue_unavailable`.
- Production allowlist: `packages/db/src/egp_db/repositories/discovery_job_repo.py` only.
- Snapshot `/tmp/egp-trackbc-s3.hEwaM4/snapshot.json`; receipt
  `/tmp/egp-trackbc-s3.hEwaM4/receipt.json`.
- The initial receipt was rejected because its changed-file path was absolute. One receipt-only
  correction was issued; no repository file changed. The corrected receipt verified true for
  `luna_implementer`, `gpt-5.6-luna`, effort `max`, file SHA-256
  `30805834efe098e82be968c8b72ac1314f8302a31c2bbc0d94eac2a514fc86a3`.
- Primary diff audit: additive default-`None` field; aggregate `MIN(created_at)` uses the exact
  existing claimable legacy predicate in the same query; nonnegative integer age; no identifiers;
  agent snapshot constructors remain compatible.
- Primary GREEN: 31 passed in 1.67s.
- Wiring: existing doctor `asdict()` serialization exposes the field automatically; one-shot logic
  still consumes counts only; no route/schema/generated-contract change.

## Implementation S4A: exact-SHA runtime topology verifier

- Goal: fail closed unless Track B and the native Mac Track C executor prove one exact release,
  Linux discovery execution is zero, agent routing is dark, and doctor/queue/profile health is
  acceptable without echoing credentials or business identifiers.
- Primary RED: new `tests/operations/test_track_bc_verify.py`; 25 expected failures, all caused by
  the missing `scripts.track_bc_verify` module.
- Production allowlist: `scripts/track_bc_verify.py` only.
- Snapshot `/tmp/egp-trackbc-s4a.4MMFwP/snapshot.json`; receipt
  `/tmp/egp-trackbc-s4a.4MMFwP/receipt.json`.
- Sole GREEN writer: `luna_implementer`, `gpt-5.6-luna`, effort `max`; ownership verified true;
  sole production file SHA-256
  `8e263b1bad2c9893a1bc41c5b4f25812c7efc81ae4661d1a2411446fb1338d94`.
- Primary diff audit: strict 40-character lowercase SHA; five Python roles require matching OCI and
  baked revisions; Mac SHA equality; executor zero; protocol off; legacy profile; zero agent jobs;
  doctor ready/unblocked; heartbeat/profile/backlog thresholds; whitelist-only JSON output and
  sanitized malformed-input behavior.
- Primary GREEN: 25 passed; Ruff passed.
- Wiring: the governed runbook will call the `runtime` subcommand before any canary. The same file
  remains the locked target for the separate canary and bundle slices.

## Implementation S4B: read-only full-chain canary verifier

- Goal: prove the bounded `crawl 1` result through the actual PostgreSQL, artifact, evidence,
  process, and profile-lock chain without emitting tenant, job, run, storage, or credential data.
- Primary RED: 18 expected failures for missing `collect_canary_evidence()` and
  `verify_canary_evidence()`, plus locked runtime edge cases for empty queues, legacy counts, and
  configurable thresholds.
- Production allowlist: `scripts/track_bc_verify.py` only.
- Snapshot `/tmp/egp-trackbc-s4b.7k4hCw/snapshot.json`; receipt
  `/tmp/egp-trackbc-s4b.7k4hCw/receipt.json`.
- A primary-owned S5 test file was briefly added after handoff, so the first ownership validation
  correctly failed on protected-file drift. The primary removed that uncommitted owned file,
  restored the exact snapshot boundary, and then verified the S4B receipt true. No production
  ownership exception was granted.
- Sole GREEN writer: `luna_implementer`, `gpt-5.6-luna`, effort `max`; sole production file SHA-256
  `b5c4c0074b71c1311b928e549ab73614276238c81a0ef4c40e499ff48ebe5a4d`.
- Primary diff audit: one PostgreSQL `BEGIN READ ONLY`/rollback transaction; exact tenant/job/run
  legacy correlation; dispatched/succeeded terminal gate; zero accepted and positive persisted
  candidates; persisted-project document lookup and artifact `exists`; bounded ordered JSONL with
  redaction, exact correlation/SHA, terminal event, dead child PID; real profile-lock probe; all
  exceptions fail closed into a sanitized evidence mapping.
- Primary GREEN: 46 passed including the real PostgreSQL through-039 and local artifact/evidence
  integration fixture; Ruff passed.
- Wiring: the collector uses the existing DB schema, artifact protocol, evidence writer contract,
  and profile-lock primitive. The CLI/bundle surface remains for S4C/S5 wiring.

## Implementation S5A: bounded supervised Track C interval

- Goal: make the continuous Mac dispatcher observable for a bounded 5–60 minute acceptance
  interval, then stop and reap its entire process group before accepting a fresh doctor postflight.
- Primary RED: new `tests/operations/test_supervise_remote_crawl.py`; 8 expected
  `ModuleNotFoundError` failures for the missing supervisor.
- Production allowlist: `scripts/supervise_remote_crawl.py` only.
- Snapshot `/tmp/egp-trackbc-s5a.jsnFMu/snapshot.json`; receipt
  `/tmp/egp-trackbc-s5a.jsnFMu/receipt.json`.
- Sole GREEN writer: `luna_implementer`, `gpt-5.6-luna`, effort `max`; ownership verified true;
  sole production file SHA-256
  `1836c920fa860d907df2a44fe0348f96f6906ff707f488cd3273eae56eb2558a`.
- Primary diff audit: new session/process group; monotonic deadline; early exit rejection; TERM then
  bounded KILL; direct-process reap plus process-group absence; bounded doctor subprocess/output;
  fresh doctor replaces stale input before reusing the runtime verifier; strict 300–3600 second
  production interval; whitelist-only receipt and sanitized CLI errors.
- Primary GREEN: 8 passed including a real descendant process-group cleanup test; Ruff passed.
- Wiring: S5B will add only fixed runner commands and the launchd evidence gate; operators cannot
  supply arbitrary supervision commands through that shell surface.
- Freshness correction S5A2: primary added a deterministic timestamp contract and confirmed the
  expected `TypeError` RED. Luna added UTC `observed_at` to the supervised receipt only; snapshot
  `/tmp/egp-trackbc-s5a2.TD1obO/snapshot.json`, receipt
  `/tmp/egp-trackbc-s5a2.TD1obO/receipt.json`, ownership verified true, production SHA-256
  `c8c25895f500db4720d173d893b150e4f3ba6aebfce6a9e1645737550266fea5`; 8 tests passed.

## Implementation S4C: canary CLI and final acceptance bundle

- Goal: make the actual read-only canary collector operable from a private request file and gate
  unattended operation on fresh, exact-SHA runtime/canary/supervised plus rollback evidence.
- Primary RED: 10 expected failures—unsupported `canary`/`bundle` subcommands and missing
  `verify_acceptance_bundle()`—while the prior 45 verifier tests remained GREEN.
- Production allowlist: `scripts/track_bc_verify.py` only.
- Snapshot `/tmp/egp-trackbc-s4c.pzoJYu/snapshot.json`; receipt
  `/tmp/egp-trackbc-s4c.pzoJYu/receipt.json`.
- Sole GREEN writer: `luna_implementer`, `gpt-5.6-luna`, effort `max`; ownership verified true;
  sole production file SHA-256
  `5ac6f4d2d599805c094e1aa268bc7334d24a75bf7c0c6efb5910459870df1`.
- Primary diff audit: private exact-field canary request; existing DB/artifact configuration;
  collector-to-verifier wiring; strict sanitized report. Bundle requires exactly runtime, canary,
  and supervised stages, schema/status/SHA/freshness validation, duplicate/unknown rejection, and
  an exact fresh rollback receipt whose four required checks are all true.
- Primary GREEN: 55 passed, including the real PostgreSQL canary CLI; Ruff passed.
- Wiring: S5B will pass the supervised receipt into this bundle contract and require an accepted
  bundle before any launchd mutation.

## Implementation S5B: fixed runner wiring and launchd evidence gate

- Goal: expose the bounded supervisor through the guarded Track C runner and refuse unattended
  launchd installation until the complete exact-SHA acceptance bundle is still fresh.
- Primary RED: expanded `tests/operations/test_remote_crawl_assets.py`; the runner had no
  `supervise` command and the installer accepted `install` without acceptance evidence.
- Production allowlist: `scripts/run_remote_crawl.sh` and `scripts/install_launchd.sh` only.
- Snapshot `/tmp/egp-trackbc-s5b.p2bGUJ/snapshot.json`; receipt verified true for the sole GREEN
  writer `luna_implementer`, `gpt-5.6-luna`, effort `max`.
- Production SHA-256: runner
  `405e43ec8b8d2e80fa5759bed95537e7e1e49124f3248ac43c7adf69ec5c95b8`; installer
  `a9fef633471221603999375f6267667969b92147fe4150d0167b363da5304995`.
- Primary diff audit: fixed watcher/doctor argv; exact clean release derivation; supervisor receives
  only duration and an evidence path; installer requires and re-verifies the private bundle input
  before any launchctl or filesystem mutation; `status` and `uninstall` remain recovery-safe.
- Primary GREEN: 16 tests passed; both shell scripts passed `bash -n`.
- Wiring: the governed runbook calls `supervise` only after the runtime and canary receipts, then
  builds the final bundle and passes the same private bundle input to `install --acceptance-evidence`.

## Governed operations runbook

- Added `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`, mapping all 19 requested items into one
  fail-closed Track B + Track C campaign with explicit stop conditions, authority, backup,
  migration pre/postflight, exact-SHA topology, one-job canary, supervised interval, rollback, and
  activation evidence.
- Corrected the runtime-image smoke invocation during primary review: the executable accepts API
  and worker image references as positional arguments and the SHA via `EGP_EXPECTED_RELEASE_SHA`.
  A documentation contract test now locks that exact operator interface.
- The runbook deliberately keeps crawler-agent protocol off and every selected job/profile on the
  legacy backend. This campaign does not claim HTTP-only agent isolation or multi-browser scale.

## Implementation S6: scoped formatter remediation

- The full-tree Ruff format check exposed broad pre-existing formatter drift plus five changed
  production Python files and five changed tests. The existing drift is outside this PR; the
  changed-file gate remains mandatory.
- Primary executable oracle: scoped `ruff format --check` reported the five production files would
  reformat. Production allowlist: `migration_runner.py`, `discovery_job_repo.py`, and the three new
  operations Python scripts only.
- Snapshot `/tmp/egp-trackbc-s6.T4DM63/snapshot.json`; receipt
  `/tmp/egp-trackbc-s6.T4DM63/receipt.json`; ownership validator verified true for
  `luna_implementer`, `gpt-5.6-luna`, effort `max`.
- Luna mechanically formatted four files; `migration_runner.py` was already compliant and stayed
  unchanged. The primary mechanically formatted the five changed test files after receipt
  verification.
- Scoped changed-file Ruff format and lint gates now pass. No behavior, schema, shell, wiring, or
  documentation contract changed in this slice.

## Wiring verification

| Component | Non-test call site | Registration/config load | Schema/contract match |
|---|---|---|---|
| Migration advisory lock | `packages/db/src/egp_db/migration_runner.py:34` wraps the entire migration ledger/apply sequence | `docker-compose.yml:46-53` runs `python -m egp_db.migration_runner`; runbook step 7 uses the release wrapper | real-PostgreSQL lock contention/release tests in `tests/phase1/test_migration_runner.py` |
| Migration-039 pre/postflight | `scripts/candidate_integrity_preflight.py:205` opens `BEGIN READ ONLY` and calculates exact repair/survivor evidence | runbook steps 6-7 invoke the CLI around the sole migrator | exact table/repair predicates mirror migrations 038/039; real-PostgreSQL matrix in `tests/operations/test_candidate_integrity_preflight.py` |
| Oldest legacy claimable age | `discovery_job_repo.py:500` computes the aggregate from the same claimable predicate | `discovery_doctor.py:215` consumes the repository snapshot and serializes the dataclass | legacy backend/status/lease/run predicates are shared with claim eligibility; repository/doctor tests lock empty and nonempty values |
| Runtime/canary/bundle verifier | `scripts/track_bc_verify.py:941` registers all three CLI stages; canary collector begins at line 727 | runbook steps 15, 17, 19 and `install_launchd.sh:65` invoke it | exact five-role SHA/topology contract; real PostgreSQL through 039, artifact, JSONL, PID, and profile-lock tests in `test_track_bc_verify.py` |
| Bounded Track C supervisor | `scripts/supervise_remote_crawl.py:255` owns process-group lifetime and fresh doctor postflight | `run_remote_crawl.sh:112-146` supplies fixed watcher/doctor commands; runbook step 18 invokes `supervise` | runtime verifier receipt contract reused after doctor replacement; descendant-reaping tests in `test_supervise_remote_crawl.py` |
| Launchd activation gate | `scripts/install_launchd.sh:73` validates the complete bundle before install mutation | `deploy/launchd/com.egp.pg-tunnel.plist` and `com.egp.remote-crawl.plist` call the guarded runner | exact current SHA, clean worktree, fresh bundle, and fixed rollback checks are exercised in `test_remote_crawl_assets.py` and `test_track_bc_verify.py` |

All required wiring cells are populated. No HTTP route, generated OpenAPI contract, environment
template, or database migration was added by this PR.

## Implementation S7: strict-audit dependency lock refresh

- The first frozen runtime audit was a legitimate RED: `cryptography==49.0.0` matched
  `PYSEC-2026-3552` (fixed in 50.0.0) and `h2==4.4.0` matched `PYSEC-2026-3628` (fixed in 4.4.1).
- Locked decision: upgrade exactly those two packages in `uv.lock`; no audit suppression,
  constraint change, broad dependency upgrade, or application source change.
- Production allowlist: `uv.lock` only. Snapshot `/tmp/egp-trackbc-s7.2dOzqP/snapshot.json`;
  receipt `/tmp/egp-trackbc-s7.2dOzqP/receipt.json`; ownership validator verified true for
  `luna_implementer`, `gpt-5.6-luna`, effort `max`.
- Result: `cryptography 49.0.0 -> 50.0.0` and `h2 4.4.0 -> 4.4.1`; frozen lock check, strict
  exported-runtime `pip-audit`, and `pip check` pass with no known vulnerabilities.
- Post-refresh full regression: 2,068 passed / 4 skipped in 251.75 seconds.

## Final source-gate record before QCHECK

- Frozen bootstrap: passed with repository-pinned uv 0.11.32.
- Affected Python suite: 132 passed / 1 skipped, three consecutive runs.
- Full Python suite before dependency refresh: 2,068 passed / 4 skipped in 256.57 seconds.
- Full Python suite after dependency refresh: 2,068 passed / 4 skipped in 251.75 seconds.
- Frontend: `npm ci`, generated API type drift, TypeScript, 83 unit tests, ESLint, production and
  critical dependency audits, and Next.js production build all passed.
- Python dependency integrity: `uv lock --check`, strict exported-runtime audit, and `pip check`
  passed after S7.
- Migration manifest: 41 files verified. Compileall and changed shell syntax passed.
- Ruff lint passes across the full tree. Ruff format passes for every file changed by this PR.
  The full-tree format check still reports the same 39 pre-existing files as clean `HEAD`; a
  `git archive HEAD` baseline check independently proves this is unchanged pre-existing drift,
  not a new PR regression.
- Release-wrapper image build/smoke remains intentionally deferred until the candidate is committed
  and the worktree is clean, because the wrapper correctly rejects tracked working-tree changes.

## Independent QCHECK and remediation

An independent read-only `terra_support` QCHECK reviewed the complete candidate after the first
full gate. It reported eight actionable findings; no production edits or lifecycle decisions were
delegated to the reviewer.

1. Critical: runtime verification used invented doctor fields instead of the actual doctor
   dataclass schema. Remediated in S8A using `asdict(build_discovery_doctor_snapshot(...))` as the
   test fixture; actual heartbeat/profile/defer fields now fail closed correctly.
2. Critical: `crawl 1` could claim an older unrelated legacy job. Remediated in S9 with an exact
   private-file target, non-live requirement, protocol-off/one-shot/limit-one gate, and a processor
   proof that the older unrelated row remains pending.
3. High: acceptance bundle trusted a top-level accepted status without validating the internal
   checks. Remediated in S8B; each runtime/canary check must be exactly present and true with empty
   errors, and the supervised lifecycle booleans must be true.
4. High: an old document on a persisted project could satisfy canary artifact evidence. Remediated
   in S8C; evidence requires a positive successful document capture for the exact run/project and
   a run age no greater than 3,600 seconds.
5. High: external SIGTERM/SIGHUP could orphan the watcher/browser group. Remediated in S10 with
   minimal event-setting handlers, a sanitized interrupted receipt, and real descendant cleanup
   tests for both signals.
6. Medium: postflight allowed missing survivor inputs and manifest evidence did not recompute
   migration bytes. Remediated in S11; postflight requires an exact true survivor delta and both
   manifest entries are unique and byte-verified. The preflight-to-migrate interval remains a
   procedural boundary, so the runbook requires an immediate matching recheck while quiesced.
7. Medium: caller `--project-directory` could weaken the release wrapper's provenance root.
   Remediated in S12 for both Compose spellings. Existing overlay source-mount and ignored/untracked
   executable guards remain in force.
8. Low: a restored manual tunnel could masquerade as readiness during launchd cutover. Remediated
   in S13; the manual tunnel must be closed again and the installer proves the managed tunnel label
   is running before and after database readiness, before bootstrapping the watcher.

### S8A-S8C verifier corrections

- S8A snapshot `/tmp/egp-trackbc-s8a.OMAGqX/snapshot.json`, receipt
  `/tmp/egp-trackbc-s8a.OMAGqX/receipt.json`; ownership verified true.
- S8B snapshot `/tmp/egp-trackbc-s8b.oXjrfL/snapshot.json`, receipt
  `/tmp/egp-trackbc-s8b.oXjrfL/receipt.json`; ownership verified true.
- S8C snapshot `/tmp/egp-trackbc-s8c.T758uS/snapshot.json`, receipt
  `/tmp/egp-trackbc-s8c.T758uS/receipt.json`; ownership verified true; production verifier SHA-256
  `f7acbe19a1eff7358075ae69bf07441ac7a9c07cd43b37b32b8fd4b962032720` at handoff.
- Sole GREEN writer for every correction: `luna_implementer`, `gpt-5.6-luna`, effort `max`.
- Primary final S8 verifier gate: 61 passed; Ruff lint and format passed.

### S9 exact regular canary target

- Primary RED: seven executor failures for missing `--target-file`; the static runner test failed
  for missing `crawl-canary`; the existing exact processor path remained GREEN.
- Snapshot `/tmp/egp-trackbc-s9.rKZGG1/snapshot.json`; receipt
  `/tmp/egp-trackbc-s9.rKZGG1/receipt.json`.
- A primary-owned S10/S11 test edit after the snapshot initially caused protected-file drift. The
  primary temporarily restored those two files to their exact snapshot hashes, verified the S9
  receipt true, and reapplied the primary-owned RED tests. No ownership exception was granted.
- Production allowlist: `discovery_dispatch.py` and `run_remote_crawl.sh`; sole writer
  `luna_implementer`, `gpt-5.6-luna`, effort `max`.
- Primary audit: current-user private regular non-symlink JSON; exact tenant/job UUID schema;
  audit output excludes identifiers; regular and fault targets mutually exclusive; normal
  failure semantics; non-live exact processor filters; fault-job exclusion retained.
- Primary GREEN: 83 passed; Ruff and shell syntax passed.

### S10 signal-safe supervision

- Primary RED: SIGTERM and SIGHUP killed the CLI directly and left two exact test process groups
  alive; the primary terminated those test-only groups before handoff.
- Snapshot `/tmp/egp-trackbc-s10.qD2n0G/snapshot.json`; receipt
  `/tmp/egp-trackbc-s10.qD2n0G/receipt.json`; ownership verified true.
- Production allowlist: `supervise_remote_crawl.py`; sole writer `luna_implementer`,
  `gpt-5.6-luna`, effort `max`.
- Primary GREEN: 10 passed for both signals, deadline behavior, bounded doctor, and full process
  cleanup; Ruff passed; post-test process inventory found no orphan.

### S11 migration evidence integrity

- Primary RED: three failures for absent survivor proof, byte mismatch acceptance, and duplicate
  manifest entry acceptance.
- Snapshot `/tmp/egp-trackbc-s11.NYhUlj/snapshot.json`; receipt
  `/tmp/egp-trackbc-s11.NYhUlj/receipt.json`; ownership verified true.
- Production allowlist: `candidate_integrity_preflight.py`; sole writer `luna_implementer`,
  `gpt-5.6-luna`, effort `max`.
- Primary GREEN: seven real-PostgreSQL/static tests passed; Ruff passed after the primary
  mechanically formatted the test file.

### S12-S13 provenance and activation safety

- S12 RED: both caller project-directory spellings reached Docker. Snapshot
  `/tmp/egp-trackbc-s12.i39pCV/snapshot.json`, receipt
  `/tmp/egp-trackbc-s12.i39pCV/receipt.json`; ownership verified true. Sole production change was
  `release_compose.sh`; 21 tests and shell syntax passed.
- S13 RED: installer lacked a managed-tunnel state gate and printed an unusable warm opt-in
  command. Snapshot `/tmp/egp-trackbc-s13.PBGkN8/snapshot.json`, receipt
  `/tmp/egp-trackbc-s13.PBGkN8/receipt.json`; ownership verified true. Sole production change was
  `install_launchd.sh`; 18 tests and shell syntax passed.
- Both sole writers were `luna_implementer`, `gpt-5.6-luna`, effort `max`.

## Updated wiring verification after QCHECK

| Entry point | Production path | Safety effect | Executable oracle |
|---|---|---|---|
| Exact canary | `run_remote_crawl.sh crawl-canary` -> `discovery_dispatch.main()` -> exact processor target | Cannot claim an unrelated, live, agent-backed, or fault job | executor gate matrix plus older-job-pending processor test |
| Canary receipt | `track_bc_verify.py canary` -> read-only PostgreSQL collector -> artifact store | Fresh run and same-run successful document capture required | real PostgreSQL/artifact integration and negative capture correlation |
| Interrupted supervision | supervisor CLI signal handler -> event -> process-group reaper | Receipt rejected and watcher/browser group reaped | real SIGTERM/SIGHUP subprocess tests |
| Migration evidence | pre/postflight CLI -> manifest byte verification + read-only counts | No missing survivor proof or stale manifest digest can pass | real PostgreSQL survivor test and tampered/duplicate manifest tests |
| Release root | release wrapper caller parser -> internal fixed project directory | Caller cannot redirect Compose provenance root | both Compose option spellings rejected before Docker |
| Launchd activation | installer -> managed tunnel running -> DB ready -> managed tunnel recheck -> watcher | Manual tunnel cannot masquerade as the installed tunnel | ordered static asset contract plus shell syntax |

The implementation is now ready for final repeat gates and formal `g-check`. Image build/smoke
still waits for a clean committed candidate. Deployment and activation remain separate, authorized
post-merge lifecycle phases and are not claimed by these source results.

### S14 changed-file formatter closure

- A final changed-file formatter check found one delegated production file requiring mechanical
  Ruff formatting: `apps/api/src/egp_api/executors/discovery_dispatch.py`.
- Snapshot `/tmp/egp-trackbc-s14.JtYCwN/snapshot.json`; receipt
  `/tmp/egp-trackbc-s14.JtYCwN/receipt.json`; ownership verified true.
- Production allowlist: `discovery_dispatch.py` only; sole writer `luna_implementer`,
  `gpt-5.6-luna`, effort `max`.
- Primary verification: changed-file Ruff format and lint passed; the expanded affected suite
  passed 210 tests / 2 skipped three consecutive times. Full repository tests passed
  1,932 / 4 skipped for the scoped tree and 2,089 / 4 skipped from the repository root.

## Review (2026-08-22 23:31:08 +07) - working-tree formal pre-commit review

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-public-mvp-track-bc`
- Branch: `feat/public-mvp-track-bc-acceptance`
- Scope: working tree at baseline `846f82869945fb742eeba3c78ec5c52ece16b6b6`
- Commands run: bounded status/diff inventory, affected/full pytest gates, Ruff lint/format,
  compileall, migration-manifest verification, shell syntax, frontend install/type/lint/unit/audit/
  build, strict frozen Python dependency audit, and a RepoPrompt working-tree review covering
  runtime entry points, consumers, tests, environment wiring, and rollout contracts.

### Findings

CRITICAL

- `scripts/release_compose.sh` still permits executable Compose overlays: the implicit root
  `docker-compose.override.yml` and caller-supplied `-f`/`--file` inputs can replace image,
  command, environment, or other runtime behavior while the release identity continues to report
  the clean source SHA. The existing source-mount guard is too narrow. Fix direction: production
  release mode must use the fixed tracked Compose topology only and reject caller file/project-root
  substitution before invoking Docker. Required tests: implicit override is ignored and both file
  option spellings fail before Docker.

HIGH

- `scripts/track_bc_verify.py` can re-stamp stale caller evidence with a new `observed_at`, and
  role evidence lacks immutable image/container identity. Old runtime facts can therefore pass a
  later acceptance. Require a bounded `collected_at`, validate absolute heartbeat time, and bind
  each container role to matching immutable digest/image identity. Add stale/future/mismatch tests.
- `scripts/supervise_remote_crawl.py` starts the watcher before proving all safety evidence and its
  postflight replaces only the doctor payload. Validate all preflight evidence before spawn and
  make the postflight fail once the runtime evidence freshness window expires; record the bounded
  limitation that external runtime recollection remains an operator input.
- Native Track-C execution is not process-enforced single-flight. Manual, supervised, and launchd
  invocations can overlap despite the one-worker configuration. Add one shared non-blocking
  process lock at the dispatcher runtime boundary and a real competing-process test.
- Canary artifact proof permits a document from an earlier crawl of the same project. Until a
  direct capture-to-document foreign key exists, require the document timestamp to fall inside the
  exact run/capture window and add an old-document/current-capture negative test.
- Profile-lock evidence trusts a caller-selected directory rather than the configured crawler
  profile. Resolve the inspected lock target from the same production configuration used by the
  browser runtime and reject caller substitution.
- `packages/db/src/egp_db/migration_runner.py` serializes migrators but does not attest migration
  bytes at runtime or retain applied digests. Validate the tracked manifest and persist/verify a
  SHA-256 digest per migration under the advisory lock; add mismatch and legacy-ledger tests.
- Candidate-integrity preflight evidence is not protected against all intervening application
  writers. Strengthen the read transaction and preserve the operational requirement that all
  writers remain quiesced through the immediate recheck and migration; do not claim the advisory
  lock alone fences applications.
- Launchd install/uninstall does not yet prove crawler heartbeat convergence, rollback a partial
  activation, or prove all managed labels are absent after removal. Add bounded state/doctor gates,
  rollback-on-failure, and a fake-launchctl state-machine test.
- Acceptance bundle validation does not enforce chronological stage ordering or exact rollback
  survivor/schema assertions. Require monotonic receipt timestamps and exact rollback evidence.

MEDIUM

- Oldest-queue age currently mixes database-created timestamps with the application clock. Compute
  both timestamps from the database result and test a deliberately skewed application clock.
- Launchd coverage is primarily static asset inspection. Add behavioral fake-launchctl coverage as
  part of the high-severity launchd remediation.

LOW

- No independent low-severity finding beyond the items above.

### Open Questions / Assumptions

- A schema-level capture-to-document identifier is outside this bounded release-acceptance PR. The
  locked near-term contract will use exact run-time bounds plus single-flight execution and will
  state this residual limitation explicitly.
- Compose release overlays are not required by the Track B+C production runbook; release mode can
  safely reject them rather than attempting to validate an open-ended Compose merge.
- Application writers are operationally quiesced during migration. The candidate preflight and
  migration lock will not be described as a substitute for that deployment gate.

### Recommended Tests / Validation

- Add focused expected-RED tests for each finding, then route production GREEN work through
  sequential Luna-Max ownership slices and verify every receipt.
- Rerun the expanded affected scope three times, both full Python suites, strict dependency and
  manifest gates, frontend gates, shell syntax, and formal `g-check` after remediation.
- Commit only after the review is clean; then run the release-wrapper immutable image build/smoke
  from that clean exact candidate.

### Rollout Notes

- Keep `EGP_CRAWLER_AGENT_PROTOCOL=off`, all public-MVP profiles on `execution_backend=legacy`,
  Track-B `discovery-executor=0`, and the Mac as the sole external legacy claimer.
- Source acceptance, image provenance, deployment, migration, Track-C browser canary, launchd
  activation, and rollback evidence remain distinct gates. No runtime acceptance is claimed yet.

## Formal-review remediation S15-S24 (2026-08-23)

The primary converted every blocking formal-review finding into a focused executable RED before
delegating a single production allowlist to `luna_implementer` (`gpt-5.6-luna`, effort `max`). All
receipts passed the ownership validator; the primary independently inspected each complete diff and
reran the locked tests.

### S15-S19: provenance, freshness, canary, and bundle integrity

- S15 fixed release-topology injection: the trusted wrapper ignores an implicit untracked Compose
  override and rejects `-f`, `--file`, and `--file=...` before Docker. Snapshot/receipt:
  `/tmp/egp-trackbc-s15.IY7OQ6/{snapshot,receipt}.json`; 24 tests passed plus shell syntax.
- S16 added one nonblocking native dispatcher lock for the configured browser-profile resource.
  Contention exits before runtime creation with a sanitized event/status. Snapshot/receipt:
  `/tmp/egp-trackbc-s16.y5QBE7/{snapshot,receipt}.json`; 37 tests passed.
- S17 made runtime evidence independently fresh and image-bound: top-level `collected_at`, absolute
  heartbeat `reported_at`, and matching immutable `image_id`/`container_image_id` for every Python
  role. Snapshot/receipt: `/tmp/egp-trackbc-s17.2wTHsr/{snapshot,receipt}.json`; 76 tests passed.
- S18 removed caller control of the canary profile directory and tightened artifact correlation to
  the exact run window and successful capture time. Snapshot/receipt:
  `/tmp/egp-trackbc-s18.sjcgDf/{snapshot,receipt}.json`; 67 tests passed.
- S19 requires chronological `runtime <= canary <= supervised <= rollback` receipts and exact
  rollback schema/check names. Snapshot/receipt:
  `/tmp/egp-trackbc-s19.eRfv22/{snapshot,receipt}.json`; 70 tests passed.

### S20-S24: migration, supervision, queue-clock, and launchd integrity

- S20 makes the migration runner validate raw migration bytes against `manifest.sha256` under the
  advisory lock and persist/verify one SHA-256 per applied version. A legacy null digest is
  backfilled only after manifest agreement. Snapshot/receipt:
  `/tmp/egp-trackbc-s20.GAydT9/{snapshot,receipt}.json`; 17 passed / 1 skipped.
- S21 makes bounded supervision reject invalid/stale runtime evidence before spawning and recheck
  it after the doctor postflight. Snapshot/receipt:
  `/tmp/egp-trackbc-s21.XsjVjq/{snapshot,receipt}.json`; 82 tests passed.
- S22 computes oldest claimable queue age using PostgreSQL/SQLite current time from the same
  aggregate query while preserving the caller timestamp for eligibility classification.
  Snapshot/receipt: `/tmp/egp-trackbc-s22.L6RjZL/{snapshot,receipt}.json`; 37 tests passed.
- S23 runs all migration-039 preflight counts in one PostgreSQL
  `REPEATABLE READ READ ONLY` snapshot. Snapshot/receipt:
  `/tmp/egp-trackbc-s23.mCg1nx/{snapshot,receipt}.json`; 8 tests passed.
- S24 makes launchd activation transactional. It proves tunnel and watcher running state, requires
  database and guarded-doctor success, rolls back every partially loaded label/rendered plist, and
  waits for absence on uninstall. A fake-launchctl state-machine test executes success, uninstall,
  and partial-failure paths without touching real LaunchAgents. Snapshot/receipt:
  `/tmp/egp-trackbc-s24.lRnKRx/{snapshot,receipt}.json`; 21 tests passed plus shell syntax.

## Primary post-remediation gate record

- Expanded affected scope: 226 passed / 1 skipped, three consecutive runs.
- Full scoped repository suite: 1,957 passed / 4 skipped in 257.30 seconds.
- Full root suite including the legacy crawler tests: 2,114 passed / 4 skipped in 261.92 seconds.
- Full-tree Ruff lint, changed-file Ruff format, compileall, 41-file migration manifest, and changed
  shell syntax passed.
- Frozen bootstrap and lock check passed with repository-pinned uv 0.11.32; strict exported-runtime
  audit reported no known vulnerabilities; `pip check` reported no broken requirements.
- Frontend clean install, generated API drift, strict TypeScript, 47 Playwright tests, ESLint,
  production dependency audit, and Next.js production build passed.
- The test-created `test.sqlite3` was moved to macOS Trash. No primary-checkout or user-owned file
  was removed or modified.

The source candidate is ready for a fresh formal `g-check`. Immutable release image build/smoke is
still correctly deferred until the accepted candidate is committed and the release worktree is
clean. Deployment and activation are not yet claimed.

## Formal g-check (2026-08-23 01:02 +07) and final remediation

RepoPrompt reviewed the complete staged 21-file deep snapshot `2026-08-23/0054` and confirmed the
earlier Compose, runtime identity/freshness, native single-flight, artifact/profile correlation,
migration digest ledger, repeatable-read/quiescence, chronological bundle, and database-clock
findings closed. It reported one critical, two high, and three medium residual findings; all were
treated as blocking:

1. Critical: the five-minute supervision minimum equaled the five-minute evidence lifetime, so no
   production interval could pass postflight.
2. High: launchd did not recheck the watcher after doctor; doctor could succeed against a recent
   heartbeat while the newly started watcher had already died.
3. High: the runbook required a known-failing full-tree Ruff formatter gate despite unchanged
   baseline drift.
4. Medium: launchd rollback/uninstall removed the database tunnel before dependent watcher/warm
   processes.
5. Medium: negative/boolean/impossible survivor-count inputs could make a nonsensical migration
   postflight equation true.
6. Medium/security: the canary verification request did not enforce its documented private regular
   file, ownership, permissions, or UUID boundary.

### S25-S29 disposition

- S25 gives supervision a truthful 120-180 second production window, caps grace at 30 seconds, and
  rejects before spawn unless the original unmodified evidence has enough remaining freshness for
  duration, two cleanup intervals, doctor timeout, and safety margin. Snapshot/receipt:
  `/tmp/egp-trackbc-s25.BUTFW3/{snapshot,receipt}.json`; 14 tests passed.
- S26 rechecks the exact watcher launchd label after doctor and tears down in reverse dependency
  order (`warm -> watcher -> tunnel`) for normal uninstall and partial rollback. The fake-launchctl
  harness proves a watcher death during doctor is rejected and fully rolled back. Snapshot/receipt:
  `/tmp/egp-trackbc-s26.FWbVlE/{snapshot,receipt}.json`; 22 tests passed plus shell syntax.
- S27 is a primary-owned runbook/test correction: freeze the exact pre-campaign main SHA, prove it
  is an ancestor, and apply Ruff formatting only to campaign-changed Python files via a null-safe
  Git diff. Full-tree lint and both full test suites remain mandatory; 71 verifier tests passed.
- S28 rejects partial, boolean, negative, or deleted-greater-than-pre survivor inputs before any
  manifest read or database connection. Snapshot/receipt:
  `/tmp/egp-trackbc-s28.QuQQB0/{snapshot,receipt}.json`; 13 tests passed.
- S29 secures canary request ingress using symlink rejection, `O_NOFOLLOW`, descriptor `fstat`,
  regular/current-owner/private-mode checks, exact schema, and canonical UUID parsing before any
  runtime dependency is built. Snapshot/receipt:
  `/tmp/egp-trackbc-s29.JhNKJN/{snapshot,receipt}.json`; ownership verified and 73 verifier tests
  passed after the primary updated the existing valid fixture to mode 0600.

Every S25/S26/S28/S29 production change was written only by `luna_implementer`, model
`gpt-5.6-luna`, effort `max`, within its one-file allowlist. No deployment or runtime acceptance is
claimed from these source changes.

### Post-formal-remediation gates

- Expanded affected scope: 237 passed / 1 skipped, three consecutive runs.
- Full scoped repository suite: 1,968 passed / 4 skipped in 256.19 seconds.
- Full root suite including legacy crawler tests: 2,125 passed / 4 skipped in 269.85 seconds.
- Full-tree Ruff lint, changed-file Ruff format, compileall, 41-file manifest, and shell syntax
  passed.
- Frozen uv lock, `pip check`, and strict exported-runtime dependency audit passed with no known
  vulnerabilities.
- The final production changes did not touch the web tree; the earlier same-candidate frontend
  clean install, generated-contract check, TypeScript, 47 Playwright tests, ESLint, zero production
  vulnerabilities, and production build remain applicable.

The candidate now requires one clean formal re-review of S25-S29 and the updated runbook before
commit.

### S30 non-finite supervision input closure

The formal re-review confirmed all six prior findings closed, then identified one new high-severity
numeric edge: `NaN` bypasses ordinary Python range comparisons and could make the bounded watcher
deadline unreachable. The primary added finite/NaN/infinity RED coverage. S30 changed only
`scripts/supervise_remote_crawl.py`, adding standard-library finite checks to duration and cleanup
grace validation before range comparisons. Snapshot/receipt:
`/tmp/egp-trackbc-s30.NPisoX/{snapshot,receipt}.json`; ownership verified for
`luna_implementer`, `gpt-5.6-luna`, effort `max`; 17 tests plus Ruff passed. No deployment or
runtime claim is made.

### S31 postflight interruption closure

A final focused review confirmed S30 and identified a postflight signal race: SIGTERM/SIGHUP could
arrive while the doctor subprocess was running, delay shutdown until its timeout, and potentially
leave an accepted receipt. The primary added real SIGTERM/SIGHUP subprocess RED tests with a
blocking doctor descendant tree and verified cleanup after the RED. S31 threads the existing
interruption event through postflight/doctor collection, promptly terminates and reaps the doctor
process group, and rechecks interruption before receipt construction. Snapshot/receipt:
`/tmp/egp-trackbc-s31.y6xBoi/{snapshot,receipt}.json`; ownership verified for
`luna_implementer`, `gpt-5.6-luna`, effort `max`; 19 tests plus Ruff passed; post-test process
inventory was clean. No deployment or runtime claim is made.

### Final source acceptance

- Focused formal review after S31: clean, no actionable findings.
- Expanded affected scope after S31: 242 passed / 1 skipped, three consecutive runs.
- Definitive root suite: 2,130 passed / 4 skipped in 258.70 seconds.
- Final Ruff, changed-file format, compileall, 41-file manifest, shell syntax, frozen lock, and
  installed dependency integrity checks passed.
- The suite-created `test.sqlite3` was moved to macOS Trash; no untracked release input remains.

Source/local acceptance is complete. Immutable image build/smoke, PR delivery, deployment,
migration, Track-C canary, supervision, rollback rehearsal, and launchd activation remain separate
later lifecycle gates and are not claimed here.
- This review is blocking. Every production correction must use a new bounded Luna-Max slice; the
  primary will not edit production code.
