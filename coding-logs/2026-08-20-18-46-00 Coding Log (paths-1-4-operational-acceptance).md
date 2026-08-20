# Coding Log: Paths 1-4 Operational Acceptance

- Started: 2026-08-20 18:46:00 +0700
- Branch: `ops/paths-1-4-acceptance`
- Baseline: `f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a`
- Worktree: `/Users/subhajlimanond/dev/egp-paths-1-4`
- Requested lifecycle: Path 1 -> Path 2 -> Path 3 -> Path 4 -> g-check -> PR -> admin merge -> exact-SHA local-main landing -> lifecycle-worktree removal

## Protected baseline

The primary checkout `/Users/subhajlimanond/dev/egp` is `main` at the exact PR #220 merge
SHA and has seven protected dirty paths. This lifecycle must not stage, edit, stash, reset,
clean, reformat, delete, or overwrite them:

1. `coding-logs/2026-07-22-13-39-00 Coding Log (crawl-result-retry-and-recrawl-batches).md`
2. `coding-logs/2026-08-06-10-00-00 Coding Log (pr-canary-01-remediation).md`
3. `coding-logs/2026-07-27-07-14-32 Coding Log (soft-launch-architecture-hardening).md`
4. `coding-logs/2026-08-13-09-35-59 Coding Log (senior-review-reconciled-drep).md`
5. `coding-logs/2026-08-13-09-35-59 DREP (senior-review-reconciled-hardening).md`
6. `docs/TOR KEYWORDS.md`
7. `test.sqlite3`

Pre-existing worktrees are user-owned and outside cleanup authority:

- `/Users/subhajlimanond/dev/egp`
- `/Users/subhajlimanond/dev/egp-ops-main`

The only lifecycle-created worktree at planning time is
`/Users/subhajlimanond/dev/egp-paths-1-4`. It must be removed after merge and safe landing.

## Planning discovery and corrected facts

RepoPromptCE was bound to the exact lifecycle worktree and one focused Context Builder pass
covered F7 runtime wiring, claim/run/candidate invariants, Compose/launchd topology, migration
identity, release provenance, staging oracles, tests, maintenance inputs, and cleanup.

Two bounded read-only Terra support passes collected current host evidence without editing Git,
files, services, containers, profile state, or database rows.

Confirmed facts that control this plan:

- Local `main`, local `origin/main`, remote `origin/main`, and PR #220's merge commit all equal
  `f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a`.
- The active Mac discovery executor PID runs editable source from the pre-existing
  `egp-ops-main` worktree at `722b1e0ece9571bddc710c5dc69c9ac45a14c066` (PR #198), not
  the target SHA.
- The local Docker API and stopped Docker discovery executor are older still. They expose no
  immutable revision label or target release stamp; the old API lacks current `/live` and
  `/ready` routes.
- The connected target database has 39 applied migrations ending at prefix 037.
  `discovery_candidate_attempts` does not exist, so migrations 038/039 and the candidate-ledger
  invariants required by F7 acceptance are absent.
- Read-only doctor evidence reports pending=13, claimable=13, leased=0 and blocks crawling on
  `profile_operator_action_required`; the persistent-profile lock is free.
- Read-only aggregates found zero active correlated runs, zero active runs without a current
  lease, and zero stale metadata-less reservations. Candidate backlog cannot be queried on the
  old schema.
- `EGP_CRAWLER_AGENT_PROTOCOL` is effectively off by source default, and the executor has one
  worker. No target release, fault-gate, lease, or heartbeat override is stamped in the running
  environment. Defaults are evidence only where that old source implements them.
- The supplied `signal_crash` name is stale. Current modes include `worker_crash`; that fixed
  operator mode proves run/job terminalization but does not spawn a descendant, so it cannot by
  itself prove the descendant process-group contract.
- Path 1 cannot accept the target runtime. No deployment, migration, restart, production
  mutation, or fault activation is authorized. Path 2 will therefore provide isolated
  staging-only evidence and cannot convert production into accepted state.

# Plan Draft A - Evidence-First Acceptance and Minimal Delivery

## Overview

Record the failed Path 1 production qualification truthfully, run exact-SHA F7 acceptance in an
isolated local PostgreSQL/process staging environment, then perform a current Path 3 security and
topology re-audit. Default to no product-code change unless that evidence proves a narrow defect.
Complete Path 4 as separate maintenance decisions and deliver a sanitized acceptance report; use
a separate dependency PR only if the npm audit graph has a safe, evidence-backed remediation.

## Files to change

Base lifecycle, primary-owned documentation only:

- `docs/operations/EGP_PATHS_1_4_ACCEPTANCE.md` - sanitized Path 1-4 evidence, outcomes,
  non-actions, operational gaps, and next-authority requirements.
- `coding-logs/2026-08-20-18-46-00 Coding Log (paths-1-4-operational-acceptance).md` - this
  plan, evidence, gates, reviews, PR/merge/landing, and cleanup record.
- `.codex/coding-log.current` - repository-relative pointer to this lifecycle log.

Conditional files only after an evidence-backed supplemental TDD slice:

- `tests/**` - primary-authored defect-sensitive acceptance test.
- Exact production allowlist named by the supplemental plan - Luna-Max GREEN only.
- `apps/web/package.json` and `apps/web/package-lock.json` - Luna-Max only, and only when a
  non-breaking direct-dependency remediation is proven necessary.

No migration, Compose, Caddy, launchd, executor, repository, or crawler file is planned to change.

## Implementation steps

### A1. Path 1 read-only production qualification

1. Preserve the four independent provenance dimensions: host checkout SHA, executable/import
   source, image digest/revision label, and runtime release event/env.
2. Record actual Compose/launchd sources and checksums without printing secrets.
3. Compare the source migration manifest with read-only `schema_migrations` filenames.
4. Run one read-only repeatable PostgreSQL snapshot for queue/run/candidate aggregates supported
   by the deployed schema.
5. Sample executor/worker/browser PIDs, descendants, PGIDs, CWDs, profile locks, and bounded
   artifact metadata twice.
6. Record `PATH_1_FAILED_TARGET_NOT_DEPLOYED`; do not deploy or repair production.

### A2. Path 2 isolated staging acceptance

1. Create a unique external evidence directory and an ephemeral PostgreSQL 15 cluster/database.
2. Explicitly prove the target is local staging and unset production DB, remote-crawl, token,
   artifact, Supabase, payment, and SSH variables.
3. At exact target SHA, verify the migration manifest and apply all 41 migrations through 039.
4. Run `tests/operations/test_f7_terminalization_postgres.py`, including the explicit
   `EGP_CI_POSTGRES_CONTRACT=1` wrapper against the isolated URL.
5. Run the real leader-plus-descendant process test; do not mislabel fixed `worker_crash` as a
   descendant-producing canary.
6. Query post-test zero-violation run/job/candidate invariants and verify no tracked files changed.
7. Archive sanitized outputs/checksums, then destroy only the uniquely identified ephemeral
   staging resources.

### A3. Path 3 current roadmap re-audit

1. Reconcile current source and remote Git history; F4/F5/F7/F8 remain merged and prohibited from
   reimplementation.
2. Inspect launch gates, source/runtime provenance, credential presence/mode/age, application DB
   role privileges, RLS promises versus actual policies, and legacy/agent/inbox topology.
3. Apply this selector in order: live incident -> stop; reproducible current-source defect ->
   narrow TDD slice; missing release provenance -> focused provenance slice; privileged DB/RLS
   contract gap -> separate hardening plan; config topology drift -> authorization request; false
   diagnostic -> focused oracle slice; otherwise `PATH_3_NO_CODE_GAP`.
4. Do not code around the known old deployment. Exact-SHA deployment/migrations remain a separate
   authority boundary.

### A4. Conditional TDD/Luna sequence

For each independently verified development behavior:

1. Primary writes the smallest meaningful test or static executable oracle.
2. Primary runs it and confirms expected RED for the missing behavior.
3. Primary locks public contract, failure policy, runtime wiring, production-file allowlist, and
   scoped GREEN command.
4. Primary creates a `green-ownership.py snapshot` after test changes.
5. Exactly one `luna_implementer` (`gpt-5.6-luna`, effort `max`) changes only allowlisted
   production files and returns the required receipt.
6. Primary validates the receipt, audits the complete diff, independently reruns GREEN, verifies
   wiring, and runs all affected/full gates plus three affected repeats.
7. Every production remediation from QCHECK or formal g-check is a new sequential Luna slice.

### A5. Path 4 maintenance

1. Run `npm ci`, `npm audit --json`, and `npm audit --omit=dev --json`; classify all four known
   advisories by direct/transitive path, runtime reachability, fix availability, and semver risk.
2. Do not use `npm audit fix --force`. Put a safe dependency remediation in a separate PR; record
   breaking/no-fix advisories with compensating controls and a future upgrade plan.
3. Inspect remote F7 branch reachability, unique commits, open-PR use, and ownership. Delete only
   when every safe-retirement predicate passes.
4. Point `.codex/coding-log.current` to this lifecycle log and include it only if tracked by the
   accepted candidate.
5. Hash and classify the seven protected primary paths without copying secret-bearing content
   into Git and without deleting any path.
6. Retire only session-created worktrees after merge, preservation, clean-state proof, and
   reachability proof. Pre-existing worktrees remain untouched.

### A6. Review and delivery

1. Run scope-appropriate local gates and independent QCHECK.
2. Run formal g-check on the staged candidate and disposition every finding.
3. Commit, push `ops/paths-1-4-acceptance`, open a standard GitHub PR, and confirm the exact head.
4. Ignore only known zero-step billing-lock hosted failures under standing policy; never label
   them passing or ignore a source/security/conflict failure.
5. Admin merge the accepted head, confirm exact remote merge SHA, safely fast-forward dirty local
   `main`, and rehash all protected paths.
6. Remove every lifecycle-created worktree and prune only verified stale registrations.

## Test coverage

Path 2 existing tests:

- `test_f7_postgres_terminalization_write_failure_recovers` - durable recovery after rejected run failure write.
- `test_f7_postgres_repairs_legacy_divergent_run_tenant_safely` - repairs only tenant-correlated legacy divergence.
- `test_f7_postgres_signal_crash_reaps_descendant_group` - kills real descendant after leader exit.
- `test_f7_postgres_concurrent_success_is_not_overwritten` - terminal success survives concurrent failure attempt.
- `test_f7_ci_postgres_contract` - explicit service-PostgreSQL wrapper runs same helpers.

Path 3 and Path 4 tests are evidence-dependent. Any selected slice must add a named test with a
5-10 word behavioral description before production implementation. Dependency remediation must
run web unit tests, typecheck, production build, critical Playwright smoke, and both audit views.

## Decision completeness

- Goal: produce honest operational/staging acceptance, current roadmap disposition, completed
  maintenance decisions, reviewed PR delivery, exact landing, and full lifecycle-worktree cleanup.
- Non-goals: production deployment/restart/migration/mutation; fault activation; agent-protocol
  activation; F4/F5/F7/F8 reimplementation; microservice refactor; RLS toggle without role design;
  force dependency upgrade; deletion of protected or pre-existing work.
- Success: Path 1 contradiction is recorded; Path 2 real PostgreSQL/process evidence passes or an
  actual defect is remediated via TDD/Luna; Path 3 decision follows current evidence; all four
  maintenance items are dispositioned; g-check is clean; PR merged; local and remote main equal;
  seven protected hashes unchanged; all lifecycle-created worktrees removed.
- Public interfaces: none planned. Conditional changes must amend this log before RED. No API,
  status, env, CLI, schema, or migration change may be inferred.
- Fail closed: uncertain production state remains failed/inconclusive; staging never counts as
  production; secret-bearing evidence is excluded from Git; DB/role access denial is
  `NOT_AUTHORIZED`; dirty-worktree ambiguity blocks cleanup; landing overlap blocks fast-forward.
- Rollout/backout: documentation-only base PR has no runtime rollout. Conditional code/dependency
  PRs carry their own rollout and backout. Production activation always requires separate authority.
- Monitoring: release identity dimensions, pending/claimable/leased counts, active correlated
  runs, candidate backlog age, worker/profile health, protocol/backend counts, RLS/role posture,
  advisory reachability, and worktree/protected-hash integrity.

## Dependencies

- Exact target Git SHA and clean lifecycle worktree.
- Local PostgreSQL 15 test support or Docker-based isolated service.
- Existing F7 operations contracts, migration manifest checker, uv lock checker, and web toolchain.
- Read-only host/database access already used for Path 1 discovery.
- GitHub CLI authentication and standing admin-merge authority.

## Validation

- `./.venv/bin/python scripts/check_migration_manifest.py --check`
- isolated `DATABASE_URL=... EGP_CI_POSTGRES_CONTRACT=1 ./.venv/bin/python -m pytest tests/operations/test_f7_terminalization_postgres.py -q`
- `./.tools/uv-0.11.32/bin/uv lock --check`
- `./.venv/bin/ruff check apps packages tests scripts`
- `./.venv/bin/python -m compileall -q apps packages`
- scope-appropriate Python/web suites and three repeats after production changes
- `./.venv/bin/python scripts/check_main_sync.py --no-fetch --json`
- exact PR head, merged SHA, origin/main, local main, and protected-path hash equality

## Wiring verification

| Component | Entry point | Registration/config load | Schema/contract |
|---|---|---|---|
| Read-only doctor | `egp_api.executors.discovery_doctor:main()` | operator CLI only | queue/profile/database diagnostics |
| F7 staging contract | operations pytest module | pytest + PostgreSQL selector | migrated `discovery_jobs`, `crawl_runs`, `discovery_candidate_attempts` |
| Manifest proof | `scripts/check_migration_manifest.py --check` | direct read-only command | 41 SQL files through 039 |
| Process cleanup | `SubprocessDiscoveryDispatcher.dispatch_cancellable()` | API/standalone dispatcher factories | POSIX session/PGID contract |
| Roadmap selector | sanitized acceptance report | lifecycle decision record | current source/runtime evidence |
| npm classification | npm audit commands | `apps/web/package-lock.json` graph | runtime/dev dependency reachability |

## Cross-language/schema verification

Python repositories and SQL migrations use `discovery_jobs`, `crawl_runs`, and
`discovery_candidate_attempts`, correlated by both `tenant_id` and job/run identifiers. No
TypeScript consumer writes these internal lifecycle fields. Before any conditional migration,
search all Python/TypeScript/SQL consumers and allocate the next prefix only after re-reading the
current migration policy and remote main; no migration is planned here.

# Plan Draft B - Build a Reusable Operational Acceptance Harness First

## Overview

Create a new repository-owned read-only acceptance CLI that collects release/config, migration,
database invariant, process/profile, and topology evidence into one sanitized JSON document, then
use it for Paths 1-3 and deliver it with Path 4 maintenance. This improves repeatability but makes
a new production-adjacent tool and test surface before current evidence shows the existing
commands are insufficient.

## Files to change

- New `scripts/check_f7_operational_acceptance.py` - read-only orchestrator and JSON schema.
- New `tests/operations/test_f7_operational_acceptance.py` - redaction, read-only SQL, and
  classification contracts.
- Existing documentation/Coding Log/pointer from Draft A.
- Conditional web dependency files under the same Path 4 rules.

## Implementation steps

1. Primary writes tests proving the harness rejects non-read-only DB sessions, redacts identifiers
   and secrets, distinguishes missing authority from contradictions, and never invokes mutation.
2. Confirm RED because no harness exists; lock the JSON schema, probe registry, and exit codes.
3. Snapshot ownership and delegate the new production script to Luna-Max only.
4. Validate receipt, run unit tests, exercise against isolated staging, and compare results with
   independent direct queries.
5. Use the harness for the current Paths 1-3, then complete Path 4 and delivery as in Draft A.

## Test coverage

- `test_acceptance_harness_requires_read_only_transaction` - refuses database session lacking read-only mode.
- `test_acceptance_harness_redacts_sensitive_identifiers` - emits aggregates without tenant or job values.
- `test_acceptance_harness_separates_unavailable_from_failed` - preserves authority versus contradiction distinction.
- `test_acceptance_harness_never_calls_mutating_repository_methods` - registry contains read-only probes only.
- `test_acceptance_harness_records_independent_release_dimensions` - does not substitute checkout for runtime SHA.

## Decision completeness

- Goal: make operational acceptance reproducible through one versioned, safe CLI.
- Non-goals: deployment, remediation, data mutation, secrets archiving, F7 implementation, or
  automatic cleanup.
- Success: direct-query parity, schema-valid sanitized output, staging acceptance, clean g-check,
  merged CLI/docs, exact landing, and lifecycle cleanup.
- Public surface: new operator CLI `scripts/check_f7_operational_acceptance.py`; no API/env/schema
  change. Exit 0=accepted, 2=failed, 3=inconclusive, 4=not authorized.
- Fail closed: any unknown probe, schema drift, DB non-read-only state, redaction failure, or
  provenance mismatch stops and emits no raw payload.
- Rollout/backout: tool is opt-in and read-only; backout removes the CLI/tests/docs. It is never
  wired into service startup.
- Monitoring: operator use only; no service metrics added.

## Dependencies

Draft A dependencies plus a locked JSON schema and approved sanitized evidence format.

## Validation

Draft A gates plus direct-query parity on isolated PostgreSQL and static inspection proving no
mutation-capable SQL/repository registration.

## Wiring verification

| Component | Entry point | Registration/config load | Schema/contract |
|---|---|---|---|
| Acceptance CLI | direct operator invocation | no service registration | sanitized JSON v1 |
| Probe registry | CLI `main()` | explicit immutable registry | read-only SQL and host probes |
| Evidence serializer | CLI result writer | called only after redaction | no tenant/job/secret fields |

## Cross-language/schema verification

Same tables and correlations as Draft A. The CLI would introspect required relation/column
presence and stop on drift; it would never adapt queries silently.

# Comparative Analysis

Draft A is the smallest path aligned with current evidence: it uses existing doctor, manifest,
repository queries, F7 PostgreSQL/process tests, and Git tooling. It avoids introducing a new
operator surface during an acceptance exercise and preserves the rule that a missing deployment is
an operational authority issue, not a code bug.

Draft B improves repeatability and could become valuable after repeated acceptance campaigns, but
it delays the requested evidence, creates a security-sensitive redaction surface, and would require
Luna production ownership plus its own formal review before it can be trusted. One campaign does
not yet justify that cost.

Both drafts preserve tenant scoping, production read-only constraints, exact-SHA evidence,
TDD/Luna ownership, standard GitHub delivery, protected dirty state, and lifecycle worktree
closeout. Draft A is selected. A future dedicated harness may be planned only after this lifecycle
demonstrates repeated manual-oracle drift.

# Unified Execution Plan

## Overview

Use Draft A's evidence-first lifecycle and Draft B's explicit result taxonomy/redaction rules,
without creating a new runtime or operator CLI. Record Path 1 as failed because the target SHA and
schema are not deployed, execute isolated exact-SHA Path 2, then perform the evidence-driven Path 3
selector and separate Path 4 maintenance. Deliver only sanitized documentation unless a current,
reproducible gap or safely remediable npm advisory creates a supplemental TDD/Luna slice.

## Files to change

- This Coding Log and `.codex/coding-log.current`.
- New `docs/operations/EGP_PATHS_1_4_ACCEPTANCE.md`.
- Tests and exact Luna-owned production files only after a supplemental plan and expected RED.
- Web manifest/lockfile only in a separate dependency slice/PR when audit evidence permits.

## Implementation steps

1. Freeze primary protected-path hashes and the lifecycle worktree ledger outside Git.
2. Finish sanitized Path 1 evidence and classify `PATH_1_FAILED_TARGET_NOT_DEPLOYED`.
3. Bootstrap exact-SHA isolated staging, migrate through 039, run real PostgreSQL/process F7
   contracts, query invariants, archive sanitized evidence, and remove staging resources.
4. Re-audit current source/runtime/launch gates/credential posture/RLS/agent topology.
5. Apply the locked Path 3 selector. Do not choose F4/F5/F7/F8.
6. For a proven gap only: primary test -> expected RED -> ownership snapshot -> one Luna-Max GREEN
   -> receipt verification -> independent gates/wiring -> QCHECK/g-check remediation via Luna.
7. Classify npm advisories and use a separate dependency PR only for safe remediation.
8. Disposition the remote F7 branch, current-log pointer, seven protected dirty paths, and all
   worktrees without destructive assumptions.
9. Write the sanitized acceptance report, run formal g-check, deliver the accepted candidate,
   admin merge, exact-SHA land local main, rehash protected files, and remove all lifecycle-created
   worktrees.

## Test coverage

The required Path 2 PostgreSQL/process tests and all conditional test rules from Draft A apply.
No new base production behavior means no artificial RED is created for documentation-only work.
Any production or dependency change requires a defect-sensitive RED and the full g-coding ownership
workflow before it enters the candidate.

## Decision completeness

- Goal, non-goals, success, public surfaces, failure behavior, rollout, monitoring, and acceptance
  commands are locked as in Draft A.
- Path 1 outcome is already evidence-backed and cannot be relabelled accepted.
- Path 2 is staging-only, and passing it does not authorize deployment.
- Path 3 defaults to no code gap; F4/F5/F7/F8 are closed.
- Path 4 cannot delete user-owned dirty files or pre-existing worktrees.
- No implementation decision is delegated to Luna; every selected slice requires an amended,
  decision-complete contract first.

## Dependencies

Draft A dependencies apply. Production deployment authority is intentionally not a dependency of
this lifecycle because Path 2 supplies staging-only evidence and the report records the production
gap honestly.

## Validation

Run Draft A validation commands, then formal g-check, Git/PR exact-head checks, admin merge,
origin/local-main SHA equality, protected hash equality, and worktree-ledger closeout.

## Wiring verification

| Component | Runtime/evidence entry | Registration | Schema/contract |
|---|---|---|---|
| Path 1 provenance | Docker/launchd/process/import inspection | external read-only evidence record | four independent SHA dimensions |
| Path 1 invariants | one read-only PostgreSQL snapshot | direct SQL only | tenant-scoped job/run/candidate joins |
| Path 2 F7 acceptance | existing operations pytest module | pytest PostgreSQL selector | migrations through 039 |
| Path 3 selector | acceptance report decision table | primary lifecycle decision | current runtime/source facts |
| Path 4 audit | npm/Git/status/hash evidence | separate maintenance section | dependency graph and ownership ledger |
| Conditional GREEN | runtime call site named in amended plan | exact existing/new registration | verified across all consumers |

## Cross-language/schema verification

The base lifecycle changes no schema. Path 2 verifies source migrations and actual repository
names against the isolated database. Any later SQL change requires a new exact search across
Python, TypeScript, migrations, tests, and runtime factories before a migration prefix is allocated.

## Acceptance checklist

- [x] Exact baseline and PR #220 merge identity confirmed.
- [x] Seven protected primary paths and pre-existing worktrees identified.
- [x] RepoPrompt discovery and two independent read-only support passes completed.
- [x] Path 1 target-runtime contradiction confirmed without mutation.
- [x] External evidence ledger and protected hashes recorded.
- [x] Path 2 isolated PostgreSQL/process acceptance completed.
- [x] Path 3 current source/security/topology decision recorded.
- [x] Four Path 4 maintenance items dispositioned.
- [x] Conditional slices completed through primary RED and verified Luna-Max receipts.
- [x] Formal g-check clean and all findings dispositioned.
- [ ] Accepted PR head merged and exact origin/local main landed.
- [ ] Protected hashes unchanged and all lifecycle-created worktrees removed.

## Path 1 Evidence (2026-08-20 18:50 +0700)

### Outcome

`PATH_1_FAILED_TARGET_NOT_DEPLOYED`

This is a verified production/target-runtime contradiction, not an access denial and not a
passing acceptance. Staging may provide source confidence but cannot convert this outcome into
production acceptance.

### Primary-owned verification

- `./scripts/run_remote_crawl.sh doctor` from the active runtime checkout connected read-only and
  returned `status=blocked`, blocker `profile_operator_action_required`, queue pending/claimable
  `13/13`, leased `0`, persistent profile lock free, two warm failures, and no recorded warm
  success.
- PID 42578 runs `egp_api.executors.discovery_dispatch --poll-interval-seconds 2` with CWD
  `/Users/subhajlimanond/dev/egp-ops-main`; that checkout is exact SHA
  `722b1e0ece9571bddc710c5dc69c9ac45a14c066`. Its only source-state differences are pre-existing
  untracked `.data` and one Coding Log.
- Docker `egp-api` is an old running localdev image sourced from the protected primary
  `docker-compose-localdev.yml`; it exposes only `EGP_BACKGROUND_RUNTIME_MODE=external` from the
  safe env allowlist and has no OCI revision label.
- Docker `egp-discovery-executor` is exited, uses another old image, exposes only worker count 1
  from the safe allowlist, and has no OCI revision label.
- A direct SQLAlchemy `psycopg` transaction used
  `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY DEFERRABLE`. It found 39 migration ledger rows,
  last version `037_crawl_profile_execution_backend.sql`, no
  `public.discovery_candidate_attempts`, zero active correlated runs, zero active correlated runs
  lacking a current lease, and zero stale metadata-less reservations.
- The initial direct SQL attempt failed before connection because the legacy URL selected missing
  `psycopg2`; rerunning with the installed `postgresql+psycopg` dialect succeeded without changing
  the env file or database.

### Disposition

- Do not run a production fault canary on this runtime.
- Do not claim PR #220/F7 deployment or operational acceptance.
- Do not deploy, migrate, restart, modify profile state, mutate queue/run/candidate rows, or change
  protocol/fault settings without separate authority.
- Proceed to isolated Path 2 at exact source SHA and label all results staging-only.

## Path 2 Evidence (2026-08-20 18:55 +0700)

### Outcome

`PATH_2_STAGING_ACCEPTED`

The result proves exact-source F7 behavior on isolated real PostgreSQL and real POSIX child
processes. It does not prove deployment, production schema, production process cleanup, or
production activation.

### Primary-owned verification

- Lifecycle worktree HEAD remained exact target SHA
  `f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a`; worktree imports were forced ahead of the shared
  dependency environment through an explicit worktree `PYTHONPATH`.
- Source manifest check passed with 41 migration files.
- PostgreSQL binaries were available locally.
- Full `tests/operations/test_f7_terminalization_postgres.py` result: `9 passed, 1 skipped`.
  The only skip was the intentionally disabled external-URL CI wrapper.
- A separate uniquely named `TempPostgresCluster` database received all 41 migrations and ran
  `test_f7_ci_postgres_contract` with `EGP_CI_POSTGRES_CONTRACT=1`: `1 passed`.
- That wrapper used a minimal child environment containing only safe process basics, the isolated
  database URL, explicit worktree import roots, and the CI selector. It received no production
  token, storage, Supabase, remote-crawl, payment, or SSH variables.
- A fresh separate invariant database verified 41 ledger rows ending at
  `039_candidate_attempt_integrity.sql`, candidate table present, zero active runs, and zero
  accepted candidates.
- The first invariant query used the incorrect generic column `status`; PostgreSQL rejected it
  read-only. Inspection confirmed the migration-defined name `candidate_status`, and the corrected
  query passed against a fresh database. No schema or data was adapted to hide the mismatch.
- Process sampling after cluster teardown found no staging PostgreSQL, F7 child, or signal
  descendant; only the sampling shell and `rg` process matched the search expression.
- Worktree status contained only this Coding Log; no tracked runtime, test, migration, lock, or
  generated source changed.

### Disposition

- Exact-source F7 implementation remains accepted for staging.
- Production remains unaccepted and demonstrably pre-target.
- Proceed to Path 3 current-state re-audit; do not create an F4/F5/F7/F8 slice.

## Path 3 Re-audit and Selected Slice (2026-08-20 19:05 +0700)

### Current security/topology evidence

- `.env.remotecrawl` is mode 0600 and contains the required database, worker-token, and artifact
  credential names without printing their values. It does not stamp protocol, fault, lease,
  heartbeat, or release-SHA overrides.
- The connected application database role is superuser, `BYPASSRLS`, `CREATEROLE`, and
  `CREATEDB`. It owns all 34 tenant-bearing public tables. `row_security` is on globally, but zero
  tenant tables enable or force RLS and `pg_policies` contains zero public policies.
- Repository migrations likewise contain no `ENABLE ROW LEVEL SECURITY` or `CREATE POLICY`.
  Current architecture relies on tenant-scoped repository SQL, not RLS.
- Queue aggregates are legacy-only: 144 dispatched, 6 failed, 13 pending. The agent inbox has 16
  applied historical results and a fresh idle inbox heartbeat, but no agent runtime process is
  active and the protocol is effectively off.
- The only live crawler claimer is the old native legacy executor. Docker discovery is exited;
  no Docker inbox executor is active on this host.

The privileged database credential is a high-priority least-privilege finding, but remediation
requires a separately approved role/grant/credential rollout. Enabling RLS without a role,
connection-pool tenant-context, owner/bypass, and rollback design would be unsafe. This lifecycle
will document that separate operational/security plan and will not mutate production roles,
grants, policies, credentials, or schema.

### Deterministic selector

The first evidence-backed development rule is missing runtime provenance: current API and worker
images have neither revision labels nor baked release env; only the discovery executor receives an
optional runtime env, which can be blank; CI/publish builds do not pass the Git SHA; and the native
runner accepts a stale/missing release value from its env file. Select one narrow
`PATH_3_RELEASE_PROVENANCE` slice. Do not reimplement F4/F5/F7/F8.

### Supplemental decision-complete mini-plan: S1 release provenance

#### Goal and non-goals

Goal: make API/worker container images and the native remote crawler expose an exact source
revision that an operator can verify independently from host checkout state.

Non-goals: API response changes, deployment, restart, migration, role/RLS changes, protocol/fault
activation, new release service, web-image changes, dependency changes, or production mutation.

#### Public/operational contract

- Reuse existing `EGP_RELEASE_SHA`; add Docker build arg of the same name.
- API and worker runtime images bake `EGP_RELEASE_SHA` and OCI label
  `org.opencontainers.image.revision` from the build arg.
- Production Compose requires explicit `EGP_RELEASE_SHA` for every Python image build. Localdev
  uses literal non-production fallback `localdev`.
- Compose must not override the baked image env with an empty runtime value.
- CI and publish workflows pass the exact `${GITHUB_SHA}` / `${{ github.sha }}`.
- Runtime image smoke requires `EGP_EXPECTED_RELEASE_SHA` and fails if either image label or baked
  env differs.
- Native `run_remote_crawl.sh` derives a 40-character lowercase Git HEAD after validated env load,
  refuses tracked index/worktree drift, overrides any stale env-file value, and exports the exact
  SHA before the Python module exec. Untracked operational artifacts are not classified or removed.

#### Failure behavior

- Missing/malformed Git revision: fail closed before runtime exec.
- Tracked staged or unstaged source drift: fail closed before runtime exec.
- Image label/env mismatch or missing expected SHA: CI smoke fails closed.
- Production Compose missing release SHA: interpolation fails before build.
- No fallback to host checkout inference after a container starts.

#### Primary-authored tests and RED

New `tests/operations/test_release_provenance.py`:

- `test_python_runtime_images_embed_release_revision` - both Python images label and bake revision.
- `test_compose_builds_every_python_image_with_release_sha` - every Python build receives correct production/local value.
- `test_ci_and_publish_workflows_stamp_exact_commit_sha` - build and publish use exact workflow commit.
- `test_runtime_image_smoke_rejects_release_mismatch` - smoke checks label and baked environment.
- `test_remote_runner_stamps_checkout_sha_before_runtime` - derived checkout SHA overrides stale env.
- `test_remote_runner_refuses_tracked_source_drift` - tracked dirty checkout cannot start runtime.

Exact RED command:

`/Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/operations/test_release_provenance.py -q`

Observed expected RED: `7 failed`; Dockerfiles lacked arg/label/env, Compose lacked build args and
still overrode discovery runtime env, workflows omitted build args, smoke omitted revision checks,
and the native runner emitted stale env SHA and accepted tracked drift.

#### Production ownership allowlist

- `apps/api/Dockerfile`
- `apps/worker/Dockerfile`
- `docker-compose.yml`
- `docker-compose-localdev.yml`
- `.github/workflows/ci.yml`
- `.github/workflows/publish-images.yml`
- `scripts/smoke_runtime_images.sh`
- `scripts/run_remote_crawl.sh`

Tests, Coding Logs, docs, Git state, deployment state, migrations, manifests, env files, secrets,
and every other path are protected. Luna must stop rather than expand scope.

#### Wiring verification

| Component | Runtime entry point | Registration/config | Contract |
|---|---|---|---|
| API image revision | all API-image containers | API Dockerfile + Compose build args + publish workflow | OCI label and baked env equal build SHA |
| Worker image revision | discovery executor/worker/agent | worker Dockerfile + Compose build args + publish workflow | OCI label and baked env equal build SHA |
| CI identity gate | runtime image smoke step | CI build commands and expected-SHA env | mismatches fail before accepted image |
| Native watcher revision | `run_remote_crawl.sh run_module()` | launchd calls existing runner | exact clean tracked checkout SHA exported before exec |

#### Acceptance

1. Scoped test GREEN and three consecutive passes.
2. Existing runtime-image hardening, reproducible-release, env-template, and remote-crawl tests pass.
3. Ruff/format for tests, YAML parse, `bash -n`/`sh -n`, and compileall pass.
4. Build both images with an explicit target SHA; `docker image inspect` proves exact label/env.
5. Modified smoke script passes those images and rejects a deliberately mismatched expected SHA.
6. Complete diff and ownership receipt validate; QCHECK and formal g-check find no unresolved issue.

## Path 4 Read-only Maintenance Evidence (2026-08-20 19:15 +0700)

### npm advisories

- Full audit: four high, zero critical. Packages are transitive
  `@redocly/openapi-core`, `js-yaml`, `brace-expansion`, and `nanoid`.
- Runtime-only audit: one high, `nanoid@3.3.16`, reached through
  `postcss@8.5.23 -> nanoid ^3.3.16`.
- Development-only paths include `openapi-typescript -> @redocly/openapi-core@1.34.17 ->
  js-yaml@4.2.0/minimatch -> brace-expansion`, plus ESLint/minimatch brace-expansion copies.
- Current fixed releases exist within declared transitive ranges: `nanoid@3.3.18`,
  `@redocly/openapi-core@1.34.19` (uses `js-yaml@4.3.1`), and brace-expansion
  `1.1.18`/`2.1.4`/`5.0.9`.
- `npm audit fix --package-lock-only --dry-run` reported zero changes and retained all four
  advisories, so it is not accepted evidence of remediation.
- Decision: after S1 completes, run a separate lockfile-only TDD/oracle slice. The failing oracle
  is both full and runtime `npm audit`. Luna may update only `apps/web/package-lock.json` within
  existing semver ranges. If package.json overrides or breaking upgrades are required, stop and
  write a separate upgrade plan; never use `npm audit fix --force`.

### Retained F7 branch

- PR #220 is merged and its remote head remains
  `07651816b7591246b909ba54edb6f8fe5e28646a` on
  `origin/fix/f7-durable-terminalization`.
- No open PR uses the branch.
- Because PR #220 was squash-merged, the branch head is not an ancestor of `origin/main`; it has
  unique commits under the conservative reachability rule.
- Decision: retain the remote branch. Do not delete or rewrite it in this lifecycle.

### Coding-log pointer

- The lifecycle worktree pointer now references this log as required by g-planning/g-coding.
- The protected primary pointer remains on the August 13 review log until the lifecycle log is
  merged. At final local-main landing, update the local-only pointer to the merged lifecycle log;
  do not include or delete an ignored pointer through Git.

### Seven protected paths

- Six Markdown paths are classified as user-owned lifecycle/review/domain artifacts; preserve.
- `docs/TOR KEYWORDS.md` may contain domain-sensitive user notes; preserve and do not quote it in
  the acceptance report.
- Empty `test.sqlite3` is classified as a generated/test artifact but is still user-owned;
  preserve because classification is not deletion authority.
- Exact baseline sizes, modes, states, and SHA-256 values are held in the external lifecycle
  ledger. Rehash before and after landing.

### Worktrees

- `/Users/subhajlimanond/dev/egp` and `/Users/subhajlimanond/dev/egp-ops-main` predate this
  lifecycle and remain outside cleanup scope.
- `/Users/subhajlimanond/dev/egp-paths-1-4` is lifecycle-owned and must be removed after merge,
  exact-SHA landing, artifact preservation, and clean/reachability proof.

## Path 3 S1 GREEN Ownership and Primary Verification (2026-08-20 20:10 +0700)

### Luna ownership

- `P3-S1-release-provenance`: Luna-Max completed the eight-path production allowlist. The external
  receipt records role `luna_implementer`, model `gpt-5.6-luna`, effort `max`, and exact file
  hashes. Primary ownership verification passed with no HEAD drift, protected-path drift, or
  out-of-allowlist production change.
- The extended env-template gate then exposed one legitimate contract mismatch: the production
  template still described `EGP_RELEASE_SHA` as an optional runtime value. Primary replaced the
  stale test with the locked build-time contract and observed the expected focused RED (`1 failed,
  1 passed`).
- `P3-S1b-release-template`: a second sequential Luna-Max handoff changed only
  `deploy/.env.production.example`. Its ownership receipt verified cleanly. The template now
  requires a literal `<40-character Git commit SHA>` and explains immutable image provenance.

### Primary verification

- Release/config/remote-crawl operations suite: `143 passed`.
- Release-provenance test repeated three times: `7 passed` on every run.
- `bash -n scripts/run_remote_crawl.sh`: passed.
- `sh -n scripts/smoke_runtime_images.sh`: passed.
- `git diff --check`: passed.
- Exact-SHA API and worker image builds: passed for
  `f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a`.
- Runtime smoke against both images: passed and proved exact OCI revision label plus baked
  `EGP_RELEASE_SHA`.
- Deliberate all-zero expected SHA: failed closed on the API label mismatch as required.

The image-build Playwright dependency-install stage emitted its existing pre-install host-library
warning before the runtime stage installed the required libraries; the final worker image built
successfully and passed the runtime smoke. No image was published or deployed.

### Independent QCHECK finding and remediation

The first independent QCHECK rejected S1 acceptance with two findings:

- P1: production Compose accepted any nonempty caller-supplied SHA, so label/env agreement alone
  could attest a value unrelated to the build context; the persistent template also supplied a
  dangerous nonempty placeholder.
- P2: deployment and observability documentation still described optional runtime injection and
  direct `docker compose --build` commands.

Primary locked a stronger trusted-entrypoint contract and authored the expected RED (`6 failed,
6 passed`). `P3-S1c-trusted-release-entrypoint` then went through a third sequential Luna-Max
handoff. Ownership verification passed for exactly:

- `scripts/release_compose.sh`
- `docker-compose.yml`
- `deploy/.env.production.example`

The wrapper derives an exact 40-character lowercase Git `HEAD`, rejects staged or unstaged tracked
drift, overwrites a caller value, and execs production Compose with an explicit project root and
base file. The production template now contains no persisted release SHA, and Compose's required
message directs operators to the wrapper. Primary updated all production/rollback build runbooks;
CI, publish, and native runner retain their separate trusted derivations.

Post-remediation evidence:

- Related operations suite: `147 passed`.
- Bash/sh syntax and `git diff --check`: passed.
- Full repository suite from the isolated worktree: `1986 passed, 4 skipped` in 241.50 seconds.
- The first full-suite attempt's sole failure was an isolated-worktree environment issue: the
  backup test expected `.venv` under the worktree. An ignored temporary symlink to the existing
  validated environment made that exact test pass; the symlink and generated worktree SQLite file
  were removed from the repository after the final run.

The original QCHECK findings are resolved. A fresh independent QCHECK is still required on the
complete candidate before formal g-check.

## Review (2026-08-20 20:42 +0700) - working-tree formal g-check

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-paths-1-4`
- Branch: `ops/paths-1-4-acceptance`
- Scope: complete working tree against `f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a`
- Commands Run: RepoPrompt Context Builder review over published uncommitted diff; targeted source,
  test, Compose, shell, workflow, and runbook inspection; related pytest; full pytest; shell syntax;
  Docker image build/smoke; ownership validators; `git diff --check`.

### Findings

CRITICAL

- Base production Compose required `EGP_RELEASE_SHA` during interpolation for every command, not
  only builds. Removing it from the persistent template therefore broke ordinary `stop`, `run`,
  `up`, `ps`, `logs`, and `config` operations after the wrapper process exited. Changed config
  tests masked the issue by injecting an all-zero SHA. Fix direction: move release-only build args
  to a wrapper-supplied Compose overlay and keep the base file independently parseable; remove
  synthetic test injection and execute representative base config commands without release env.

HIGH

- `release_compose.sh` and `run_remote_crawl.sh` checked only tracked diffs; untracked Python under
  runtime import/build roots could be executed or copied while the runtime claimed clean `HEAD`.
  Fix direction: reject untracked runtime-source inputs while preserving unrelated untracked
  operational artifacts and approved Compose overrides.
- Explicit base `-f` suppressed automatic `docker-compose.override.yml`, conflicting with the
  host-local override procedure and lifecycle preservation requirement; forwarded relative overlay
  paths also depended on caller cwd. Fix direction: wrapper must run from repository root, include
  release overlay, explicitly include an existing host override, then forward caller overlays.

MEDIUM

- Runtime smoke accepted any nonempty expected value, including `unknown`; require exact lowercase
  40-hex expected and observed revisions and executable negative coverage.
- Local development used `${EGP_RELEASE_SHA:-localdev}`, allowing inherited input to appear as
  source identity; make the marker literal `localdev`.
- The public acceptance report called Path 3 accepted before final review and carried stale related
  test counts; keep it provisional until remediation and final clean review complete.

LOW

- No unrelated F4/F5/F7/F8 reimplementation was found.

### Open Questions / Assumptions

- Untracked runtime rejection is intentionally scoped to actual Python/dependency build and import
  roots so user-owned logs, evidence, and approved host Compose overrides remain usable.
- Production manual builds are supported only through the trusted wrapper; plain base Compose stays
  supported for non-build operations.

### Recommended Tests / Validation

- RED/GREEN coverage for release overlay composition, base Compose without release env, clean-HEAD
  wrapper, host override/relative overlay ordering, untracked runtime inputs, literal localdev, and
  malformed smoke revisions.
- Rerun related operations tests, full pytest, syntax/static gates, exact-SHA image builds through
  the final wrapper, positive smoke, and deliberate mismatch/malformed negatives.

### Rollout Notes

- Do not publish, deploy, or claim Path 3 accepted until all CRITICAL/HIGH/MEDIUM findings are
  remediated through a new bounded Luna handoff and a fresh formal review is clean.

## Formal Review Remediation S1d/S1e (2026-08-20 21:18 +0700)

Two sequential Luna-Max remediation slices completed with valid external receipts and clean primary
ownership verification.

### P3-S1d release overlay hardening

- Added a release-only Compose overlay and removed release interpolation from the base stack, so
  ordinary production `config`, `stop`, `run`, `up`, `ps`, and `logs` remain parseable without a
  persistent SHA.
- Wrapper order became base -> approved host override -> caller overlays -> release overlay.
- Local development uses literal `localdev`; smoke requires exact 40-lowercase-hex expected and
  observed values.
- Both trusted entrypoints began rejecting untracked executable runtime inputs.

### P3-S1e provenance finalization

- Release overlay is last and pins build context, Dockerfile, build SHA, and runtime SHA for all
  five Python-image services.
- API and worker Dockerfiles reject missing, `unknown`, uppercase, or malformed revisions; only
  exact lowercase 40-hex or explicit `localdev` is accepted.
- `release_compose.sh --source-root` lets the current trusted driver build a detached prior-release
  worktree only when that target retains the current five-service topology; older incompatible
  topologies fail closed and require a separately approved historical image/digest procedure.
- SOC recovery now builds `migrate` and routes build/migrate/up/ps through the wrapper.
- Native remote crawler rejects ignored/untracked executable source inputs and changes to neutral
  `/` before module execution.

### Current primary gates

- S1e scoped: `28 passed`.
- Complete related operations suite: `151 passed`.
- Full repository suite after S1d: `1989 passed, 4 skipped`; S1e is limited to release wrapper,
  overlay, Dockerfile guard, and native-entrypoint hardening and is covered by the related suite.
- Ruff check/format, Bash/POSIX shell syntax, YAML parsing, and `git diff --check`: passed after
  formatting the primary-owned test.

Path 3 remains a candidate until the final independent QCHECK and formal g-check are clean, then a
clean committed checkout must build/smoke both images through the final wrapper.

## Final QCHECK Remediation S1f (2026-08-20 21:42 +0700)

The last independent QCHECK identified two concrete bypasses: ignored executable artifacts were
not queried, and the current release overlay could add services to a historical topology that did
not define them. Primary added four expected RED cases; `P3-S1f-fail-closed-overrides` completed via
Luna-Max with an ownership-valid two-file receipt.

- Both trusted entrypoints now query ordinary untracked and ignored files separately and reject
  executable Python/native/dependency inputs with distinct sanitized errors.
- The release wrapper verifies all five current Python services exist in the target base Compose
  file before adding the release overlay. Pre-U7c targets fail closed as incompatible instead of
  reintroducing the inbox executor.
- Approved host/caller overlays remain supported, but any mount targeting `/app` or a subpath is
  rejected before Docker so it cannot replace the image's runtime source.
- Scoped oracle: `32 passed`; ownership verification and Bash syntax passed.

The supported rollback wrapper path is therefore limited to topology-compatible releases. Older
topologies require an approved historical image/digest procedure; the runbook now says so.

## Review (2026-08-20 20:24:56 +0700) - working-tree final Path 3 candidate

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-paths-1-4`
- Branch: `ops/paths-1-4-acceptance`
- Scope: working tree based on `f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a`
- Commands Run: targeted and full diff inspection; `pytest tests/operations -q`; scoped Ruff
  check/format; Bash syntax; `git diff --check`; independent Terra QCHECK

### Findings

CRITICAL

- No findings.

HIGH

- No findings.

MEDIUM

- No findings. The prior ignored-input, runtime-source-mount, additive rollback topology, and
  contradictory rollback-runbook findings are resolved and covered by executable tests.

LOW

- No findings.

### Open Questions / Assumptions

- The wrapper attests tracked runtime source and the exact image revision; it does not claim that
  arbitrary operational environment values are themselves source-controlled or attested.
- Pre-U7c rollback is intentionally outside the generic wrapper. It requires separately approved
  historical image/digest recovery rather than weakening the topology guard.
- Database-role/RLS hardening remains a separate, migration-bearing security program and is not
  silently folded into this provenance slice.

### Recommended Tests / Validation

- Passed: `pytest tests/operations -q` -> 319 passed, 2 skipped.
- Passed: scoped Ruff check/format for all changed Python tests.
- Passed: Bash syntax and `git diff --check`.
- Previously passed after the production-source change set: full repository suite -> 1,989 passed,
  4 skipped.
- Before PR delivery, build API and discovery images through `release_compose.sh` from a clean
  committed validation worktree, smoke both against that exact commit SHA, and prove a deliberate
  mismatch fails closed.

### Rollout Notes

- No deployment, service restart, database mutation, fault injection, image publication, or
  crawler-agent activation is authorized or performed by this review.
- Local development retains the explicit `localdev` marker. Production release identity must be
  exact lowercase 40-hex and derived by the trusted wrapper or CI workflow.
- Path 3 is accepted for source/local gates. Runtime acceptance remains distinct and requires a
  separately authorized exact-SHA deployment and post-start evidence.
