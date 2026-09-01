# Coding Log: track-bc-runtime-campaign

- Started: 2026-09-01 21:21:33 +0700
- Lifecycle branch: `ops/track-bc-runtime-campaign`
- Frozen runtime release: `ab19e43ee66018dcab15412cd2e48a2db27ca56e`
- Lifecycle worktree: `/Users/subhajlimanond/dev/egp-track-bc-runtime-campaign`
- Detached release worktree: `/Users/subhajlimanond/dev/egp-track-bc-release-ab19e43e`
- Private evidence: external to Git; exact path and sensitive values are not recorded here
- Prior goal-turn classification: no progress; this continuation revalidated current Git and began execution

## Planning evidence

- Root policy: `AGENTS.md`
- Governing operator contract: `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`
- Prior runtime-tail plan: user-owned untracked primary artifact
  `coding-logs/2026-09-01-19-48-54 Coding Log (post-merge-runtime-tail-pickup).md`
- Compact numbered contract: user-owned untracked primary artifact `egp-devlogs.md`, items 3-15
- RepoPrompt was bound to `/Users/subhajlimanond/dev/egp`; one focused Context Builder pass traced
  release, migration, backup, Track B, native Mac, receipt, supervision, rollback, and launchd wiring.
- An attempted Context Builder pass against the old receipt worktree failed because its workspace
  projection was stale; direct Git and file inspection replaced that pass without retrying blindly.
- Independent read-only audits confirmed that the old exact-canary branch is already merged and its
  later dirty production files are unreceipted historical residue. It is preserved and excluded.

## Locked scope

Implement compact items 3-15 only:

3. create and validate an exact-SHA release worktree and frozen environment;
4. qualify source/web/images at that SHA;
5. collect fresh read-only production preflight;
6. record distinct maintenance, observation, ingestion, and activation authorities;
7. quiesce writers and create verified database/artifact backups;
8. migrate once through 040 and attest postflight, ledger, constraint, and readiness;
9. deploy Track B with Linux discovery zero, protocol off, and exact legacy routing;
10. prepare the same-SHA native Mac Track C runtime;
11. perform the read-only browser observation;
12. perform exactly one separately authorized live ingestion and verify schema-2 proof;
13. supervise for 120 seconds with process-group cleanup and fresh postflight;
14. rehearse rollback and accept a chronological bundle v2;
15. activate launchd from accepted evidence and record completion.

Items 1-2 are already delivered by PRs #226 and #227. Item 16 (PR-CANARY-04-07) is a non-goal.

# Plan Draft A - One contiguous governed campaign

## 1. Overview

Qualify the frozen release before the maintenance window, then execute production quiescence through
activation as one contiguous campaign with all owners present. This minimizes receipt drift and
makes chronological bundle acceptance straightforward, but concentrates operational coordination.

## 2. Files to change

- `coding-logs/2026-09-01-21-21-33 Coding Log (track-bc-runtime-campaign).md`: planning,
  sanitized gate outcomes, review, delivery, and closeout.
- `.codex/coding-log.current`: local ignored pointer to this log.

No application source, runtime configuration, migration, schema, infrastructure-as-code, generated
runtime asset, registration, or wiring change is planned. Private evidence is created outside Git.

## 3. Implementation steps

### TDD and executable-oracle sequence

1. Run existing contract tests and exact-SHA qualification gates as locked characterization oracles.
2. Treat any failing gate as RED and identify whether it exposes drift or a source defect.
3. If a source defect exists, the primary writes the smallest acceptance test, confirms expected
   RED, snapshots an exact production allowlist, and delegates GREEN only to `luna_implementer`.
4. Refactor production only through a new Luna-Max slice and verified receipt.
5. Independently rerun scoped GREEN, full gates, three repeats, wiring review, QCHECK, and g-check.

### Operational order

1. Validate lifecycle and detached release worktrees and the frozen SHA.
2. Bootstrap frozen dependencies; run compile, manifest, Ruff, format, full pytest, web typecheck/build.
3. Build five release roles; smoke API/worker images; attest immutable role identities.
4. Collect fresh bounded production and Mac preflight facts without mutation.
5. Complete a private authority record naming environments, owners, window, migration/deletion
   scope, restore ownership, exact target, and approved bundle freshness.
6. Stop watchers and writers, activate the approved write fence, prove zero active runs/leases and
   resolve any inbox backlog before mutation.
7. Create local and off-host database backup evidence plus non-destructive artifact-copy evidence;
   independently retrieve and checksum the database archive.
8. Run candidate preflight twice from stable quiescence; require identical counts and explicit
   approval of the exact deletion count, including zero.
9. Run exactly one governed migrator; verify 038/039 postflight, separate 040 digest/constraint
   attestation, and exact-SHA readiness with no pending/unexpected migrations.
10. Deploy API, webhook executor, inbox executor, and governed web; keep discovery executor zero.
11. Prove five-role identity, protocol `off`, legacy profile/target routing, no pending agent jobs,
   safe inbox state, `/live`, and `/ready`.
12. Prepare native Mac same-SHA worktree and external 0600 env; establish only the approved tunnel,
   warm profile, run doctor, and accept runtime schema 1.
13. Run observation under browser authority; require contiguous page proof, typed terminal,
   persistence disabled, and sanitized target fingerprint.
14. Pause for the distinct ingestion authority, revalidate the unchanged target, claim exactly one
   live legacy job, and accept the full correlated schema-2 chain.
15. Collect fresh supervision input and run 120 seconds; require deadline, reaping, and postflight.
16. Uninstall/stop runtime components, prove absence, rehearse tunnel restore/close, and record
   rollback schema 1 while Track B discovery remains zero.
17. Verify chronological bundle v2 under the approved tighter window, reconfirm activation
   authority, install launchd using raw bundle input, and rerun status/doctor.
18. Create the private completion record and append only sanitized results to this log.

### Existing functions and commands

- `release_compose.sh`: derives clean exact SHA and governs five-role build/deploy operations.
- `check_migration_manifest.py:main()`: verifies every tracked migration byte before DB access.
- `migration_runner.apply_migrations()`: verifies bytes, locks, reads ledger, applies in order.
- `candidate_integrity_preflight.py:main()`: produces 038/039 pre/post count evidence.
- `track_bc_verify.py`: verifies runtime, observation, canary, supervision, rollback, and bundle.
- `run_remote_crawl.sh`: guards Mac environment and dispatches tunnel/doctor/observation/canary.
- `supervise_remote_crawl.py:main()`: supervises, terminates, reaps, and re-verifies runtime.
- `install_launchd.sh`: re-verifies bundle input before install and rolls back on install failure.

## 4. Test coverage

- `test_remote_crawl_assets.py`: release/runner/runbook/launchd structural contract.
- `test_track_bc_verify.py`: receipt schema, chronology, freshness, fingerprint, artifact integrity.
- exact-canary API/worker suites: atomic exact claim and browser proof contract.
- full Python suite: cross-package source regression coverage.
- web typecheck/build: governed web release integrity.
- image smoke: non-root runtime, Chrome, source separation, exact SHA, size bounds.
- three repeated affected suites: detect acceptance-oracle flakiness.

## 5. Decision completeness

### Goal

Achieve evidence-backed Track B/C public-MVP runtime acceptance and reversible activation at exact
SHA `ab19e43ee66018dcab15412cd2e48a2db27ca56e`.

### Non-goals

No Linux discovery execution, crawler-agent protocol activation, broad routing rewrite,
multi-browser concurrency, fault injection, PR-CANARY-04-07, applied-migration rewrite, or broader
production-readiness claim.

### Success criteria

- Source/web/full/image gates pass at the exact SHA.
- Fresh preflight, quiescence, backup custody, migration 040, Track B, Mac, observation, ingestion,
  supervision, rollback, bundle v2, launchd, and final doctor evidence are all accepted.
- Receipt order is `runtime <= observation <= canary <= supervised <= rollback`.
- Linux discovery remains zero and protocol remains off throughout.
- Lifecycle log passes g-check, is merged by authorized admin merge, local main lands exact merge,
  and every session worktree is safely removed.

### Public/private interfaces

No public API, endpoint, schema, environment variable, CLI flag, Compose service, or migration
changes. Existing private target v1, runtime/observation/supervised/rollback schema 1, canary/bundle
schema 2, migration 040, and launchd installer interfaces are consumed unchanged.

### Edge cases and failure modes

- Wrong/dirty SHA or image mismatch: fail closed before production.
- Active writers/runs/leases or backlog ambiguity: remain quiesced or stop before migration.
- Backup checksum/retrieval failure: do not migrate; release fence only under stop-owner decision.
- Preflight count drift or unapproved deletion count: do not migrate.
- Migration lock/digest/constraint/readiness failure: keep writers fenced; fix forward after 040.
- Discovery nonzero, protocol not off, wrong routing: stop before Mac ingestion.
- Stale heartbeat, locked profile, old queue, target drift: fail closed.
- Observation proof/fingerprint failure: no ingestion.
- Canary failure: no automatic retry and no activation.
- Supervision leak, rollback failure, stale/reordered bundle: no activation.
- Installer cleanup uncertainty: activation failed; rollback owner intervenes.

### Rollout and monitoring

Use exact images and one maintenance window; monitor `/live`, `/ready`, active runs, leases, inbox,
executor count, protocol, routing, doctor, heartbeat, profile lock, queue age, browser/process group,
bundle age, and launchd labels. Backout is pre-migration unfence, post-040 pause/fix-forward or
separately authorized restore, topology-compatible Track B rollback, and launchd uninstall.

### Acceptance checks

The governing commands are enumerated under Unified Plan validation. Each command must produce a
fresh bounded artifact or accepted sanitized receipt; command exit alone is insufficient.

## 6. Dependencies

Exact Git SHA, frozen Python/npm dependencies, Docker/Compose, production deployment access,
PostgreSQL and artifact backup credentials, off-host retrieval, governed web control, native Mac
Chrome/profile/tunnel access, private target/job, and named maintenance/restore/browser/activation
owners. Secrets remain outside prompts, Git, receipts, and shared logs.

## 7. Validation

Validate every stage separately and preserve its exact timestamp, identity, accepted status, and
rollback state. A narrow health check never substitutes for a broader source/image/runtime gate.

## 8. Wiring verification

See the Unified Plan table; every new runtime output is created by an already-wired operator entry
point and validated by a named receipt/schema contract.

## 9. Cross-language schema verification

Highest migration is 040 and the manifest contains 42 entries. Migration 040 changes the PostgreSQL
failure-code constraint consumed by Python shared enums/worker/API logic; no TypeScript/OpenAPI
surface changes. Fresh inspection must prove the ledger digest, constraint vocabulary, readiness
set, and Python enum remain identical.

## 10. Decision-complete checklist

- [x] Goal, non-goals, exact SHA, authorities, stop behavior, and backout are locked.
- [x] No public or private interface change is delegated to the operator.
- [x] Every behavior has an executable gate or live receipt oracle.
- [x] Validation is staged and scope-matched.
- [x] Wiring and schema verification cover every component.

# Plan Draft B - Preparation phase plus contiguous runtime tail

## 1. Overview

Separate stable preparation from the time-sensitive runtime tail. Run exact-SHA source/image gates
and read-only discovery first; at the authorized window, revalidate all drift-prone facts and execute
quiescence through activation without unrelated pauses.

## 2. Files to change

The same lifecycle log and ignored pointer as Draft A; no production repository file changes.

## 3. Implementation steps

### TDD and executable-oracle sequence

Use the same characterization-first and Luna-only defect-remediation sequence as Draft A.

### Phase B1 - stable preparation

1. Validate worktrees, exact SHA, pointer/log, external private evidence boundary, and owners.
2. Complete source/web/full gates, image build/smoke, and immutable identity capture.
3. Collect read-only production/Mac inventory and resolve every command placeholder privately.
4. Stop without mutation if access, owner, topology, backlog policy, or backup destination is unclear.

### Phase B2 - contiguous runtime window

1. Revalidate SHA, image identities, production state, writers, runs, leases, inbox, backup targets,
   Mac/profile/tunnel state, authority, and bundle window.
2. Execute Draft A steps from quiescence through launchd activation without promoting B1 facts into
   fresh acceptance evidence.
3. Record sanitized stage results and exact rollback state.

## 4. Test coverage

Same tests as Draft A, plus explicit revalidation of every B1 drift-prone fact at B2 entry.

## 5. Decision completeness

### Goal and non-goals

Same as Draft A.

### Success criteria

Same accepted evidence chain as Draft A, plus proof that B2 refreshed every time-sensitive B1 fact.

### Public/private interfaces

No changes; consume the same frozen interfaces and private receipt versions.

### Edge cases and failure modes

Any SHA/image/topology/authority drift between B1 and B2 invalidates the affected qualification.
Do not relabel B1 evidence as fresh; rerun the natural stage or stop.

### Rollout and monitoring

Preparation is read-only. Runtime rollout/backout matches Draft A after B2 begins.

### Acceptance checks

Require a B2 revalidation manifest that maps each drift-prone fact to its fresh evidence artifact.

## 6. Dependencies

Same as Draft A, but not all mutation owners must be present during B1.

## 7. Validation

Use B1 outputs as qualification inputs only; use B2 outputs as acceptance evidence.

## 8. Wiring verification

Same Unified Plan table.

## 9. Cross-language schema verification

Same 040/42-entry contract; revalidate immediately before migration.

## 10. Decision-complete checklist

- [x] Preparation and runtime evidence cannot be conflated.
- [x] Drift forces revalidation.
- [x] The mutation tail remains contiguous and fail closed.
- [x] All Draft A safety and ownership boundaries remain intact.

# Comparative analysis

Draft A minimizes chronology drift but spends more coordinated operator time and may discover
missing access late. Draft B discovers missing access and expensive qualification failures early,
but requires disciplined revalidation. Both preserve the same exact SHA, evidence custody,
authority separation, stop behavior, and no-source-change boundary.

# Unified Execution Plan - prepare early, run one contiguous governed tail

## 1. Overview

Adopt Draft B for safe preparation, then Draft A from quiescence through activation. This provides
early evidence and command resolution without allowing stale preparation facts to masquerade as
runtime acceptance.

## 2. Files to change

- This Coding Log: primary-owned plan, sanitized execution state, review, delivery, and closeout.
- `.codex/coding-log.current`: ignored local pointer.

No production code change is planned. If an executable gate proves a source defect, pause the
campaign and open a decision-complete TDD slice with an exact allowlist and Luna-Max ownership.

## 3. Implementation steps

1. Validate the two new worktrees, exact SHA, baseline worktree ledger, and protected user state.
2. Create an external 0700 evidence directory and mode-0600 authority/target/request templates.
3. Run source, web, manifest, full test, image build/smoke, and role-identity qualification.
4. Collect fresh bounded production and Mac preflight; privately resolve environment-specific
   deploy, web, write-fence, SQL, backup, restore, tunnel, browser, and activation commands.
5. Revalidate all drift-prone facts at the runtime window.
6. Quiesce, fence writers, prove zero runs/leases and safe inbox, back up DB/artifacts, retrieve and
   checksum the DB backup, and confirm restore ownership.
7. Run two identical preflights, explicitly approve deletion count, migrate once through 040, and
   accept postflight, separate 040 attestation, and readiness.
8. Deploy Track B/web without starting another migrator; accept five-role identity, discovery zero,
   protocol off, legacy routing, inbox state, `/live`, and `/ready`.
9. Prepare native Mac same-SHA environment and accept doctor/runtime receipt.
10. Accept read-only observation, then separately authorize and execute one exact live ingestion.
11. Accept schema-2 canary proof, fresh 120-second supervision, rollback rehearsal, and bundle v2.
12. Reconfirm activation authority, install launchd from raw bundle input, accept status/doctor, and
    complete the private record.
13. Run full review and delivery: QCHECK, formal g-check, commit only the sanitized Coding Log,
    push one branch, open one PR, admin-merge under the standing billing-lock policy if applicable,
    fetch/land exact merge on local main without changing protected dirt, post-merge verify, and
    remove both session-owned worktrees under the closeout protocol.

## 4. Test coverage

- `tests/operations/test_remote_crawl_assets.py`: structural release/runtime contracts.
- `tests/operations/test_track_bc_verify.py`: all receipt and bundle invariants.
- relevant exact-canary API/worker tests: exact target, claim, browser, proof, persistence.
- `pytest tests apps packages -q`: full Python acceptance.
- `npm run typecheck` and `npm run build`: web acceptance.
- `smoke_runtime_images.sh`: exact runtime image acceptance.
- affected operational suites repeated three times before delivery.

## 5. Decision completeness

### Goal

Complete compact items 3-15 and land their sanitized lifecycle record.

### Non-goals

Compact item 16 and all Draft A non-goals.

### Success criteria

All stage criteria in Draft A pass, the private completion packet is complete, the sanitized log is
reviewed and merged, main lands the exact merge SHA, and session worktrees are removed.

### Public/private interfaces

No changes. Existing interface names and versions remain locked.

### Edge cases and failure modes

All Draft A failure modes apply. Fail closed; do not retry live canaries merely to obtain success.

### Rollout and monitoring

Draft B preparation, Draft A runtime tail, and explicit rollback ownership.

### Acceptance checks

See validation commands below and the governing runbook. Each live step must emit the named private
artifact or accepted receipt before the next step.

## 6. Dependencies

All Draft A dependencies plus a clean exact-SHA Mac worktree and an operator-approved tighter
bundle age in `1..86399` seconds.

## 7. Validation commands

From the detached release worktree, with private environment/evidence paths supplied out-of-band:

```bash
./scripts/bootstrap_python_env.sh
.venv/bin/python -m compileall apps packages scripts
.venv/bin/python scripts/check_migration_manifest.py --check
.venv/bin/python -m ruff check apps packages tests scripts
.venv/bin/python -m pytest tests apps packages -q
(cd apps/web && npm ci && npm run typecheck && npm run build)
./scripts/release_compose.sh build migrate api webhook-executor \
  crawler-agent-inbox-executor discovery-executor
EGP_EXPECTED_RELEASE_SHA="$TRACK_BC_SHA" \
  ./scripts/smoke_runtime_images.sh "$API_IMAGE" "$WORKER_IMAGE"
.venv/bin/python scripts/candidate_integrity_preflight.py --phase pre
./scripts/release_compose.sh run --rm migrate
.venv/bin/python scripts/candidate_integrity_preflight.py --phase post \
  --expected-pre-candidate-count "$APPROVED_PRE_COUNT" \
  --expected-deleted-orphan-run-count "$APPROVED_DELETE_COUNT"
.venv/bin/python scripts/track_bc_verify.py runtime --evidence "$RUNTIME_INPUT" \
  --expected-release-sha "$TRACK_BC_SHA" --output "$RUNTIME_RECEIPT"
scripts/run_remote_crawl.sh observe-canary "$TARGET" --receipt "$OBSERVATION_RECEIPT"
scripts/run_remote_crawl.sh crawl-canary "$TARGET"
.venv/bin/python scripts/track_bc_verify.py canary --request "$CANARY_REQUEST" \
  --expected-release-sha "$TRACK_BC_SHA" --output "$CANARY_RECEIPT"
scripts/run_remote_crawl.sh supervise 120 --evidence "$SUPERVISION_INPUT"
.venv/bin/python scripts/track_bc_verify.py bundle --evidence "$BUNDLE_INPUT" \
  --expected-release-sha "$TRACK_BC_SHA" --max-age-seconds "$APPROVED_WINDOW" \
  --output "$BUNDLE_RECEIPT"
scripts/install_launchd.sh install --acceptance-evidence "$BUNDLE_INPUT"
scripts/install_launchd.sh status
scripts/run_remote_crawl.sh doctor
```

Before deployment, add the exact `--env-file` required by `release_compose.sh`; never place its
path or values in Git. Use the runbook's exact frozen migration-040 attestation rather than an
invented query. Run affected operational tests three consecutive times before g-check.

## 8. Wiring verification

| Component | Runtime entry point | Registration/config load | Schema/table/contract |
|---|---|---|---|
| Release wrapper | operator `release_compose.sh` | tracked base + release Compose only | five named roles; exact SHA |
| Manifest/migrator | `check_migration_manifest.py`; Compose `migrate` | `migration_runner` package | `schema_migrations`; manifest 42/42 through 040 |
| Candidate preflight | `candidate_integrity_preflight.py` | direct PostgreSQL read-only snapshot | candidate attempts/runs; 038/039 |
| Readiness | API `/ready` | middleware -> readiness service | filesystem migrations vs ledger |
| Track B | Compose `api`, webhook, inbox | `release_compose.sh up --no-deps` | protocol off; inbox and legacy routing |
| Native Track C | `run_remote_crawl.sh` | external 0600 env -> guard | exact target v1; legacy profile/job |
| Observation | `observe-canary` | guarded diagnostic/browser path | observation schema 1; fingerprint |
| Live canary | `crawl-canary` then verifier | exact atomic dispatcher/worker | canary schema 2; run/candidate/document/artifact |
| Supervision | `supervise 120` | supervisor fixed argv + verifier | supervised schema 1 |
| Rollback/bundle | verifier `bundle` | ordered receipt inputs | rollback schema 1; bundle schema 2 |
| Activation | `install_launchd.sh install` | three tracked launchd plists | raw accepted bundle; exact SHA |

Every row requires fresh non-test call-site evidence, config identity, and schema/contract match.

## 9. Cross-language schema verification

- Python migration runner, readiness service, preflight, shared enum, verifier, and PostgreSQL
  manifest must agree on 038-040 and the eight failure codes.
- Compose roles must agree on baked/OCI SHA and use the same migration set.
- TypeScript/OpenAPI are unaffected; verify no public diff before delivery.
- No migration 041 is allocated by this campaign.

## 10. Decision-complete checklist

- [x] No open architecture, contract, migration, security, tenancy, concurrency, or rollback choice.
- [x] Environment-specific values stay private and must be resolved before mutation.
- [x] Every changed repository file is listed; no production file change is planned.
- [x] Every runtime stage has a named executable oracle and fail-closed stop condition.
- [x] Wiring covers release, DB, Track B, Mac, observation, ingestion, supervision, bundle, activation.
- [x] Full lifecycle includes g-check, PR, admin merge, exact local-main landing, and cleanup.

## Execution status

- Planning: complete.
- Source/image qualification: pending.
- Fresh production preflight: pending.
- Mutation/runtime campaign: pending.
- Review/delivery/closeout: pending.

## Qualification RED and remediation contract (2026-09-01 21:26 +0700)

- Frozen release bootstrap succeeded with repo-local `uv==0.11.32`; the correct lock gate is
  `.tools/uv-0.11.32/bin/uv lock --check`, which passed. The earlier bare `uv` failure was a command
  invocation error, not lock drift.
- Compileall, migration manifest `42/42`, and Ruff lint passed at `ab19e43e`.
- Exact changed-file formatter oracle:
  `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only -z --diff-filter=ACMR
  846f82869945fb742eeba3c78ec5c52ece16b6b6..HEAD -- '*.py' | xargs -0
  .venv/bin/python -m ruff format --check`.
- Observed expected static RED: 21 files required formatting. The primary mechanically formatted
  the 12 test files only; rerunning the oracle left exactly nine production/runtime files RED.
- Locked behavior: formatting-only; no semantic, signature, schema, migration, configuration,
  dependency, public contract, or wiring change.
- Production allowlist:
  `apps/api/src/egp_api/executors/discovery_dispatch.py`,
  `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`,
  `apps/api/src/egp_api/services/public_run_summary.py`,
  `apps/worker/src/egp_worker/browser_discovery.py`,
  `apps/worker/src/egp_worker/main.py`,
  `apps/worker/src/egp_worker/workflows/discover.py`,
  `packages/db/src/egp_db/repositories/discovery_job_repo.py`,
  `scripts/diagnose_search_rows.py`, and `scripts/track_bc_verify.py`.
- Scoped GREEN is the same exact changed-file formatter command. The delegate must also run Ruff
  lint and focused operational/exact-canary tests as supporting evidence; the primary will rerun all
  gates independently.

## TBCRC-S1-FORMAT GREEN and primary verification (2026-09-01 21:38 +0700)

- Sole production writer: `luna_implementer`, model `gpt-5.6-luna`, effort `max`.
- Ownership snapshot: `/private/tmp/egp-track-bc-format-s1-20260901T2127-snapshot.json`.
- Receipt: `/private/tmp/egp-track-bc-format-s1-20260901T2127-receipt.json`.
- Ownership validator: `verified=true`; exact nine-file changed set, SHA-256 values, role/model/
  effort/slice, HEAD, allowlist, and protected-file state accepted.
- Complete primary diff inspection: 21 files total (nine Luna-owned production/runtime files and 12
  primary-owned test files), all changes mechanical Ruff 0.15.9 formatting; no semantic or wiring
  change found. Diff check passed.
- Primary scoped GREEN: exact changed-file formatter oracle passed, `39 files already formatted`.
- Primary gates: frozen lock passed; manifest `42/42`; compileall passed; Ruff full scope passed.
- Affected suite: `478 passed` in 72.36 seconds.
- Full Python suite: `2085 passed, 4 skipped` in 237.10 seconds; warnings were existing dependency/
  SQLite deprecations plus one test-only HMAC key warning.
- Web: `npm ci`, TypeScript strict typecheck, and Next.js production build passed; audit reported zero
  vulnerabilities. Existing build warnings were install-script allowlist notices, Node module API
  deprecation, and edge-runtime static-generation behavior.
- Three consecutive affected repeats: `478 passed` in 67.21s, 64.38s, and 65.48s.

### Wiring verification after formatting

| Component | Non-test call site | Registration/config load | Schema/contract match |
|---|---|---|---|
| Discovery executor | `discovery_dispatch.py:1129` uses `build_discovery_dispatch_runtime` | Compose role invokes module entry point | exact target v1; job/profile/legacy/cap contract unchanged |
| Worker dispatcher | `discovery_worker_dispatcher.py:1196` validates before spawn | API dispatch service constructs worker payload | exact target and browser settings equality unchanged |
| Public summary sanitizer | `routes/runs.py:109`; `routes/projects.py:183` | routers registered in `bootstrap/middleware.py:261-263` | private canary evidence remains excluded |
| Browser/workflow | `workflows/discover.py:1284` calls `crawl_live_discovery` | worker `main.py:235` calls `run_discover_workflow` | browser/page/terminal proof unchanged |
| Exact claim | `discovery_job_repo.py:666,734,862` | repository used by dispatcher processor | `discovery_jobs` and crawl-profile predicates unchanged |
| Observation | `run_remote_crawl.sh:185,239` invokes diagnostic | guarded external env and exact target | observation schema 1/fingerprint unchanged |
| Canary/bundle verifier | runbook runtime/canary/bundle commands; installer line 67 | CLI and launchd installer entry points | runtime/observation schema 1; canary/bundle schema 2 unchanged |
| Failure vocabulary | worker/diagnostic/verifier emit shared values | migration 040 recreates DB check | shared enum and 040 eight-value constraint remain aligned |

No new or moved symbol, caller, registration, configuration, table, column, CLI, receipt schema, or
runtime component exists in the diff. Every wiring cell is therefore an unchanged verified path.

## Independent QCHECK (2026-09-01 21:41 +0700)

### Findings and disposition

- P2 delivery hygiene: full tests created an untracked, non-ignored, zero-byte `test.sqlite3` in the
  session worktree. Disposition: valid and resolved before staging. The primary verified the exact
  file was zero bytes and session-generated, then removed only that file. No user-owned primary or
  historical-worktree artifact was touched.
- No correctness, behavioral, test-integrity, formatter-contract, ownership, schema, or wiring
  findings in the intended tracked diff.

### Independent evidence

- Exactly 21 modified Python files: nine Luna-owned production/runtime and 12 primary-owned tests.
- Ruff format/lint and diff check passed independently.
- Baseline/current ASTs were equivalent after excluding only shifted `TypeIgnore.lineno` metadata
  caused by line wrapping. Manual complete review found no changed literal, condition, import, call,
  assertion, signature, registration, or schema.
- Residual risk: the independent reviewer reused, but did not rerun, primary-owned expensive test
  and web gate evidence. The primary results above remain authoritative.

## Review (2026-09-01 21:45:47 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-track-bc-runtime-campaign`
- Branch: `ops/track-bc-runtime-campaign`
- Scope: staged working tree against `ab19e43ee66018dcab15412cd2e48a2db27ca56e`
- Commands Run: `git status --porcelain=v1`; staged name/stat/check; complete targeted diff reads;
  Ruff 0.15.9 format/lint; frozen lock; compileall; manifest 42/42; affected pytest; full pytest;
  web npm/typecheck/build; three affected repeats; wiring exact-string searches.
- RepoPrompt: the exact new worktree had no existing workspace and binding failed. Per g-check
  fallback policy, review used direct full diff inspection, exact-string wiring searches, policies,
  related tests, and executable gate evidence without retrying or creating a workspace.

### Findings

CRITICAL

- None.

HIGH

- None.

MEDIUM

- None.

LOW

- None. No findings in the intended formatter-only source/test diff or lifecycle record.

### Open Questions / Assumptions

- Assumption: the runtime release identity must advance to this remediation PR's eventual merge SHA;
  the old `ab19e43e` identity must not be used after merge.
- Environment-specific production values, owners, private target IDs, backup destinations, and web
  deploy controls remain intentionally outside Git and must be resolved by the authorized campaign.

### Recommended Tests / Validation

- Before commit: retain current formatter/lint/lock/manifest/compile/full Python/web/repeat evidence.
- After commit: verify clean branch candidate and exact intended file set.
- After merge: land exact merge on local main, recreate a clean detached release worktree at that
  SHA, rerun complete source/web/image qualification, then continue compact items 5-15.
- Before runtime activation: require every private receipt and rollback/bundle/doctor criterion in
  the Unified Plan; do not use this source review as runtime acceptance evidence.

### Rollout Notes

- The Python changes are Ruff-only and preserve executable AST, wiring, schemas, interfaces, and
  migrations. Risk is limited to release identity churn and operator evidence freshness.
- No feature flag or compatibility shim is added. Linux discovery remains zero and protocol remains
  off in the later runtime campaign.
- Hosted billing-locked no-step jobs, if encountered after authorized delivery, are unavailable and
  ignored under standing policy; they are never called passing.

### Formal disposition

- No findings. The staged candidate is accepted for commit subject to preserving the exact changed
  set and rerunning post-commit identity/status checks.

## Delivery update - formatter prerequisite (2026-09-01 21:48 +0700)

- Candidate commit: `473a851637a9bb458f7381e91f601cae1d184f87`.
- PR: `#228`; accepted head matched the candidate and was mergeable.
- GitHub Actions jobs failed before useful execution in 2-4 seconds under the standing billing-lock
  condition. They were recorded once as unavailable, not passing, and were not investigated or
  retried. The separate Vercel preview was pending and was not a source/security/conflict failure.
- Authorized admin merge result: `f64af80acda28b7ad331c30740fb5a8503ec3bee`.
- Local dirty `main` fast-forwarded exactly to `origin/main` at that SHA without changing its
  protected pre-existing modified/untracked inventory.
- The stale session release worktree at `ab19e43e` was tracked-clean; only session-generated ignored
  virtualenv/tool/cache files remained. It was force-removed under the closeout protocol and pruned.
- New detached release gate worktree:
  `/Users/subhajlimanond/dev/egp-track-bc-release-f64af80a` at the exact merge SHA.
- Post-merge source gates: identity/ancestry/cleanliness, frozen lock, compileall, manifest `42/42`,
  Ruff lint, changed-Python format, full Python `2085 passed, 4 skipped`, web npm/typecheck/build,
  and zero npm vulnerabilities passed.

## Qualification RED - release wrapper versus generated cache (2026-09-01 22:02 +0700)

- Exact image-build command failed before Docker with:
  `ignored runtime source detected; refusing release Compose`.
- Root cause: the governing runbook bootstrapped and ran `compileall` in the same checkout later
  used as the Docker/Compose source. Those mandated gates create ignored `.pyc` files; the release
  wrapper intentionally rejects them, and the Docker context does not exclude them.
- Security decision: do not weaken the production wrapper and do not clean caches with broad or
  destructive commands. Keep a pristine exact-SHA release worktree for all Compose operations and
  a distinct exact-SHA gate worktree for bootstrap/compile/tests.
- Primary-owned RED:
  `test_public_mvp_runbook_isolates_release_compose_from_generated_python_bytecode` failed because
  the build followed bootstrap/compile and no distinct worktree contract existed.
- Primary-owned GREEN: updated only
  `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md` and
  `tests/operations/test_track_bc_verify.py`; the named regression now passes.
- No production source, shell implementation, runtime configuration, schema, migration, or wiring
  changed; therefore no Luna production slice was required.

### Two-worktree contract validation

- Focused operational suite: `145 passed`.
- Three consecutive repeats: `145 passed` in 12.92s, 11.88s, and 11.61s.
- Full Python: `2086 passed, 4 skipped` in 229.43s.
- Ruff format/check for the changed test, release-wrapper shell syntax, and diff check passed.
- Full tests again created an untracked zero-byte `test.sqlite3`; the primary verified exact size and
  removed only that session-generated file before review/staging.
- Wiring impact: documentation commands now address the pristine release source and generated-cache
  gate source explicitly. Existing wrapper, Compose roles, verifier, migration, and runtime entry
  points are unchanged.

## Independent QCHECK remediation - two-worktree contract (2026-09-01 22:15 +0700)

The first independent review found two valid gaps in the initial documentation/test repair:

- P1: candidate pre/postflight, migration-040 attestation, and runtime/canary/bundle verifier
  commands remained relative to the operator's parent shell despite the new gate-worktree rule.
- P2: the initial checks did not prove detached HEAD or inspect ignored executable runtime inputs;
  `git status --untracked-files=all` does not include ignored files.

Primary-owned contract expansion and expected RED:

- Extended
  `test_public_mvp_runbook_isolates_release_compose_from_generated_python_bytecode` to require two
  detached-head assertions, explicit ignored-runtime executable inspection for both roots, two
  gate-rooted candidate-preflight commands, the gate-rooted migration-040 heredoc, and gate-rooted
  runtime/canary/bundle verifier commands.
- The named test failed on the pre-remediation runbook at the first detached-head assertion:
  expected two `symbolic-ref --quiet HEAD` checks, found zero.

GREEN remediation:

- Added detached-head and ignored executable runtime-input checks for both initial worktrees. The
  ignored-input filter mirrors the unchanged fail-closed release wrapper's runtime path and suffix
  contract.
- Rooted every later local Python/verifier command in `TRACK_BC_GATE_ROOT`; all five release Compose
  invocations remain rooted in the pristine `TRACK_BC_RELEASE_ROOT`.
- No production source, runtime shell implementation, configuration, migration, schema, or wiring
  changed; this remained primary-owned documentation and acceptance-test work.

Final primary gates for the remediated candidate:

- Named regression: passed.
- Complete `test_track_bc_verify.py`: `93 passed` on three consecutive runs.
- Full Python: `2086 passed, 4 skipped` in 233.09 seconds.
- Changed-test Ruff format/check and complete diff check passed.
- Full tests recreated only the known session-generated zero-byte `test.sqlite3`; exact size was
  verified and that one file was removed before review.

Follow-up QCHECK confirmed both operational defects fixed and found one remaining test-coverage
gap: the later migration and deploy release-wrapper calls were correctly release-rooted but not
protected by an assertion. The primary extended the same regression to require exactly five
release-rooted wrapper calls and the exact later `run --rm migrate` and zero-discovery `up -d`
forms. The complete verifier test file then passed three consecutive times (`93 passed` each),
with changed-test Ruff format/check and diff check passing.

Final independent QCHECK reported no findings. It confirmed all five release-wrapper calls are
release-rooted and protected, all five later local verifier operations are gate-rooted, and the
detached/ignored-runtime checks remain present. The primary's final complete Python rerun passed
`2086 passed, 4 skipped` in 228.86 seconds. It recreated only the known zero-byte `test.sqlite3`;
the exact file was verified and removed again before formal review.

## Review (2026-09-01 22:23:19 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-track-bc-runtime-campaign`
- Branch: `fix/release-qualification-order`
- Scope: staged documentation, acceptance-test, and lifecycle-log candidate against
  `f64af80acda28b7ad331c30740fb5a8503ec3bee`.
- Complete diff inspected for the runbook and test; lifecycle-log delta inspected for evidence and
  scope accuracy. No production source, shell implementation, configuration, migration, schema,
  generated runtime asset, signature, seam, registration, or wiring file is changed.
- RepoPrompt: no workspace exists for this exact session-owned worktree and the earlier binding
  attempt failed. Per `g-check` fallback policy, the formal review used the complete staged diff,
  relevant unchanged wrapper implementation, exact-string wiring/rooting searches, Bash syntax,
  test evidence, and independent QCHECK without retrying the unavailable binding.

### Findings

CRITICAL

- None.

HIGH

- None.

MEDIUM

- None.

LOW

- None. The two-worktree fail-closed contract and its regression coverage are accepted.

### Open Questions / Assumptions

- Assumption: after this prerequisite merges, both release and gate worktrees will be recreated as
  detached exact-SHA checkouts at the new merge result. The release root will remain unbootstrapped
  and pristine for every wrapper call.
- Production identities, secret-backed authority values, evidence directory, target IDs, backup
  destinations, and activation window remain private runtime inputs and are not represented by
  this source review.

### Recommended Tests / Validation

- Preserve the current `93 passed` x3 verifier repeats, final `2086 passed, 4 skipped` full Python
  gate, Ruff format/lint, Bash syntax, diff check, and no-findings independent QCHECK.
- After merge, create two new detached worktrees at the exact merge SHA and execute image build and
  identity resolution from the pristine release root before bootstrapping the gate root.
- Continue only through the runbook's separately authorized, fresh production evidence sequence;
  this review is source acceptance, not runtime or activation proof.

### Rollout Notes

- No runtime behavior changes in this candidate. The change prevents generated Python cache files
  from contaminating the Docker build context while retaining the wrapper's fail-closed checks.
- Rollback is source-only: revert this documentation/test commit if the operator contract is found
  incorrect before the production campaign. Do not weaken the unchanged wrapper as a workaround.
- Billing-locked no-step hosted jobs remain unavailable, not passing, under the standing policy.

### Formal disposition

- No findings. The staged candidate is accepted for commit and delivery with the exact three-file
  scope above.

## Delivery update - two-worktree prerequisite (2026-09-01 22:30 +0700)

- Candidate commit: `faf18eaade8d676ee3cd57cd475c1b8c929a1dc6`.
- PR: `#229`; accepted head matched the candidate and was mergeable.
- Hosted GitHub Actions jobs again failed before useful execution under the standing billing-lock
  condition. They were unavailable, not passing, and were neither investigated nor retried. The
  Vercel preview was pending and was not a source/security/conflict failure.
- Authorized admin merge result: `82c4a4cf701a5fd32a64b58f9d205e85f882fba7`.
- Dirty local `main` fast-forwarded exactly to `origin/main` at that SHA without changing its
  protected modified/untracked inventory.
- The stale session gate checkout at `f64af80a` had no tracked changes; only session-generated
  virtualenv, tool, Python/web/test caches, test worker logs, and a verified zero-byte
  `test.sqlite3` remained. It was force-removed under the worktree closeout protocol and pruned.
- Fresh detached exact-SHA worktrees were created at the merge result:
  `/Users/subhajlimanond/dev/egp-track-bc-release-82c4a4cf` (pristine release source) and
  `/Users/subhajlimanond/dev/egp-track-bc-gates-82c4a4cf` (local gates).

## Qualification RED - built-image resolver (2026-09-01 22:30 +0700)

- The pristine release wrapper passed source checks. An initial build without an operator
  interpolation environment failed safely before Docker; a nonsecret qualification-only set of
  required Compose values was then used, and all five Python-role images built successfully.
- Every built image label and baked `EGP_RELEASE_SHA` equaled
  `82c4a4cf701a5fd32a64b58f9d205e85f882fba7`.
- The next documented command, `release_compose.sh images -q <service>`, returned an empty result
  for every service because Compose `images` reports images for created service containers, not
  merely built images. No container had yet been created, as intended at this qualification stage.
- Primary-owned acceptance RED: the two runbook image-resolution tests failed because they still
  required the false `images -q` path and five old rooted call sites.
- Primary-owned GREEN: replace the false resolver with a fail-closed portable-AWK helper over the
  nonmutating `release_compose.sh config --images` output. It requires exactly one image suffix
  match for each requested service and preserves the pristine release root.
- Executable proof against the already-built images resolved all five service image references.
  Docker inspection confirmed exact immutable image IDs, OCI revision labels, and baked release
  SHAs for migrate, API, webhook executor, crawler-agent inbox executor, and discovery executor.
- Scope remains documentation, acceptance test, and lifecycle log only. The release wrapper,
  Compose configuration, Dockerfiles, runtime code, migrations, schemas, and wiring are unchanged.

Resolver-remediation primary gates:

- Named resolver/isolation tests passed after the expected RED.
- Complete `test_track_bc_verify.py`: `93 passed` on three consecutive runs.
- Full Python: `2086 passed, 4 skipped` in 229.13 seconds.
- Changed-test Ruff format/check, the complete source-gate Bash snippet syntax, and diff check
  passed.
- Full tests created only the known zero-byte `test.sqlite3`; the primary verified its exact size
  and removed that one session-generated file before review.

### QCHECK remediation - upstream pipeline failure

- Independent QCHECK found a P1 fail-closed bug: without `pipefail`, AWK could accept exactly one
  emitted image name even if the upstream release-wrapper/config producer then failed. Its bounded
  reproduction returned the false-success image.
- Primary-owned executable RED extracted the exact helper from the runbook, replaced only its image
  producer with a controlled Bash function, and exercised success, zero-match, duplicate-match,
  and one-valid-line-then-exit-7 cases. The exit-7 case incorrectly returned zero before repair.
- GREEN added `set -o pipefail` inside only the resolver command substitution. The extracted exact
  helper now accepts the one/success case and rejects zero, duplicate, and upstream-failure cases.
- Static tests also require the exactly-one AWK predicate and fail-closed diagnostic.
- Final complete verifier suite: `97 passed` on three consecutive runs.
- Final full Python: `2090 passed, 4 skipped` in 229.34 seconds. Ruff format/lint, Bash syntax, and
  diff check passed. The known zero-byte `test.sqlite3` was verified and removed again.

## Review (2026-09-01 22:43:18 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-track-bc-runtime-campaign`
- Branch: `ops/track-bc-runtime-execution`
- Scope: staged documentation, acceptance-test, and lifecycle-log candidate against
  `82c4a4cf701a5fd32a64b58f9d205e85f882fba7`.
- Complete runbook/test diff, unchanged release wrapper, Compose build/config behavior, executable
  five-image resolution evidence, extracted-helper failure matrix, and lifecycle evidence reviewed.
- RepoPrompt: no workspace exists for this exact session-owned worktree and the earlier binding
  attempt failed. Per `g-check` fallback policy, review used the complete staged diff, direct
  source/wiring inspection, executable tests, and independent QCHECK without retrying the binding.

### Findings

CRITICAL

- None.

HIGH

- None.

MEDIUM

- None.

LOW

- None. The post-build, pre-container image resolver is fail-closed and accepted.

### Open Questions / Assumptions

- Assumption: after merge, image qualification will be repeated at the new merge SHA; the already
  built `82c4a4cf` images are defect-discovery evidence, not final release candidates.
- The operator environment used for a real deployment remains private and separate from the
  nonsecret Compose interpolation values used only for local image qualification.

### Recommended Tests / Validation

- Preserve `97 passed` x3, final `2090 passed, 4 skipped`, Ruff, Bash syntax, diff check, and the
  no-findings independent QCHECK.
- After merge, rebuild from a fresh pristine release root, resolve exact image refs through
  `config --images`, run the image smoke from the separate gate root, and require exact merge-SHA
  labels/baked revisions.

### Rollout Notes

- No runtime implementation or Compose topology changed. The correction affects only operator
  resolution of already-built image names before containers exist.
- The helper rejects wrapper/config failure, zero match, and duplicate match; it does not silently
  select the first of multiple candidates.
- Rollback is source-only: revert this docs/test commit before runtime use if its resolver contract
  is invalid. Do not reintroduce `images -q` at the pre-container stage.

### Formal disposition

- No findings. The staged exact three-file candidate is accepted for commit and delivery.
