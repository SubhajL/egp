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
