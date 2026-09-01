# Coding Log: PR-CANARY Log Reconciliation and Next Path

- Created: 2026-09-01 13:33:28 +0700
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch/source baseline: `main == origin/main == 30ebdeec5665259e6495792e1f4715c630e1134e`
- Planning scope: reconcile `egp-devlogs.md`, the 2026-08-22/23 and 2026-09-01 Coding Logs, Git/GitHub PR history, current source, and the active exact-canary repair candidate; produce the optimal source-to-runtime path.
- Discovery: RepoPrompt bound to the active repository and one focused Context Builder reconciliation completed; direct Git/GitHub, source, migration, test, and worktree checks were used for exact confirmation.
- No production code, deployment, migration, browser session, or live data was changed by this planning run.

## Authoritative Reconciliation

1. PR-CANARY-01 through PR-CANARY-03 and F01-F08 are source-complete on `main`. Do not reopen them.
2. PR-CANARY-04 through PR-CANARY-07 remain incomplete future agent-promotion work.
3. The early 2026-08-22 recommendation to deploy next was superseded by the 2026-08-23 exact-canary false-success finding.
4. PRs #223-#225 completed their Track B/C acceptance/readiness/provenance source lifecycle, not exact-browser proof, deployment, runtime acceptance, or activation.
5. The exact-canary repair worktree remains based on current `main`, has no commits ahead, contains 30 staged paths plus 17 unstaged paths, and last produced `329 passed, 16 failed` in its focused test scope. It is a candidate, not accepted source.
6. Historical PR-CANARY-04 planning reserved migration `040`. The exact-canary candidate now uses `040`; after it lands, PR-CANARY-04 must use the next unused migration.

### Canonical PR-to-contract map

| Logical contract | GitHub PR evidence | Current disposition |
|---|---|---|
| PR-CANARY-01 structured/redacted/bounded process evidence | #199, #200, #201; completed by #219 and provenance #221 | Source-complete |
| PR-CANARY-02 truthful browser outcome contract | #202 only supplements fault injection; #206 is typed browser outcomes; #218/#220 harden truthful/durable failure | Source-complete |
| PR-CANARY-03 durable candidate accounting | #203-#206, #208, #218-#220 | Source-complete |
| F01-F08 | #204 F01, #205 F02, #206 F03, #219 F04/F05/F08, #208 F06, #218/#220 F07 | Source-complete |
| Governed Track B/C source acceptance | #223, #224, #225 | Source-complete for its stated contract |
| Exact-canary browser-proof repair | active `fix/exact-canary-false-success-repair` worktree | Incomplete/unmerged |
| PR-CANARY-04 through PR-CANARY-07 | original agent-promotion roadmap | Not started/completed as logical milestones |

## Plan Draft A — Evidence-Gated Continuation of the Existing Candidate

### 1. Overview

Preserve the current repair worktree and continue only those production paths whose Luna-Max ownership receipts, HEAD, allowlist, and hashes validate. Finish the already-locked observation and verifier tests, make the smallest delegated production corrections, run the complete local lifecycle, and land one exact-canary repair PR before any deployment or later PR-CANARY milestone.

### 2. Files to Change

- `tests/operations/test_diagnose_search_rows.py`: lock the read-only observation target/profile/browser-cleanup contract.
- `tests/operations/test_track_bc_verify.py`: lock v2 request, proof, artifact, freshness, custody, and bundle correlation.
- `tests/phase1/test_exact_canary_proof.py`, `test_worker_browser_discovery.py`, `test_worker_entrypoint.py`, `test_worker_live_discovery.py`: lock ordered browser/page proof and worker wiring.
- `tests/phase2/test_exact_canary_claim.py`, `test_exact_canary_contract.py`, `test_discovery_dispatch.py`, `test_discovery_executor.py`: lock atomic exact-live claim and API-to-worker propagation.
- `packages/shared-types/src/egp_shared_types/exact_canary.py`, `enums.py`: private target/receipt types and closed failure vocabulary.
- `packages/db/src/migrations/040_exact_canary_failure_codes.sql`, `manifest.sha256`: additive failure-code migration and manifest hash.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: tenant-scoped atomic exact-target claim.
- `apps/api/src/egp_api/executors/discovery_dispatch.py`, `services/discovery_dispatch.py`, `services/discovery_worker_dispatcher.py`: exact target parsing, live binding, payload propagation, and rejection.
- `apps/worker/src/egp_worker/main.py`, `browser_discovery.py`, `workflows/discover.py`: exact payload validation, real-browser selection, typed pagination, ordered proof, terminalization, and cleanup.
- `scripts/diagnose_search_rows.py`, `run_remote_crawl.sh`: private target-bound observation, native profile lock, sanitized receipt, and separate observe/crawl commands.
- `scripts/track_bc_verify.py`: strict v2 request/receipt/proof/bundle validation and byte-level evidence collection.
- `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`: exact source gates and separately authorized observation/ingestion runtime sequence.
- Repair Coding Log only: ownership receipts, RED/GREEN output, reviews, and gate evidence.

### 3. Implementation Steps

1. Capture a pre-handoff ownership snapshot: exact HEAD, staged/unstaged paths, protected files, production allowlist, and expected hashes. Reject receipt, model, effort, HEAD, allowlist, or hash mismatch.
2. TDD observation slice:
   1. Keep/add tests for `--target-file`, mode-0600 owner/effective-UID checks, pinned native profile, lock contention, typed pagination, and browser cleanup.
   2. Run and confirm the exact tests fail for those contract reasons.
   3. Delegate only the exact observation production allowlist to `luna_implementer` (`gpt-5.6-luna`, max).
   4. Refactor minimally only inside the allowlist.
   5. Primary validates receipt/diff/wiring and runs focused formatter, lint, and tests.
3. TDD ingestion/verifier slice:
   1. Keep/add tests for exact-live atomic claim, strict proof version/order, target fingerprint equality, real-clock future/stale rejection, artifact byte digest/size, private-file custody, and correlated rows.
   2. Confirm the expected RED independently.
   3. Delegate the exact verifier/claim allowlist to Luna-Max.
   4. Refactor minimally; do not weaken or remove a failing invariant.
   5. Primary validates receipt/diff/wiring and runs focused gates.
4. Integrate `ExactIngestionCanaryTarget.from_mapping()`/canonical fingerprint through API claim, worker payload, observation receipt, canary request/receipt, and bundle without exposing identifiers.
5. Make `_run_observation_canary()` acquire the native profile lock before Chrome, prove ordered pages, close every browser handle, release the lock, and write a bounded receipt only after full success.
6. Make worker proof validation require browser start, ordered page traversal, terminal page, persistence validation, and final dispatch ordering with exact proof version 1.
7. Make `collect_canary_evidence_v2()` use one tenant-scoped read-only PostgreSQL transaction and verify the retrieved artifact bytes, not metadata alone.
8. Make `_read_private_canary_request_v2()` verify regular file, owner/effective UID, and exact mode `0600` from a verified descriptor; reject v1 downgrade.
9. Make `verify_acceptance_bundle_v2()` compare actual current UTC to stage times and require `runtime <= observation <= canary <= supervised <= rollback`; delete the candidate behavior that derives a permissive reference time from evidence.
10. Update migration `040` and the manifest once; verify API/worker/shared enum vocabulary exactly matches SQL.
11. Run full quality/review/delivery gates. Do not deploy as part of source completion.

### 4. Test Coverage

- `test_observation_canary_accepts_pages_one_through_five_under_cap_fifteen`: accepts exact ordered read-only traversal.
- `test_observation_canary_closes_connected_browser_and_releases_profile_lock`: closes browser and releases native lock.
- `test_observation_canary_rejects_invalid_private_target_before_chrome`: rejects invalid target before browser launch.
- `test_observation_canary_fails_closed_when_profile_lock_is_busy`: rejects concurrent native-profile use.
- `test_exact_canary_target_round_trips_and_hashes_canonical_contract`: stable private target fingerprint.
- `test_exact_canary_claim_requires_every_pinned_field`: atomic claim requires all exact fields.
- `test_exact_canary_claim_mismatch_does_not_mutate_job`: mismatch leaves job unchanged.
- `test_live_canary_proof_rejects_page_before_browser_and_wrong_keyword`: strict browser/page/keyword ordering.
- `test_canary_request_v2_embeds_exact_target_and_run_id_without_downgrade`: exact target and run locked.
- `test_private_canary_request_v2_is_owner_only_and_rejects_v1`: strict file custody and version.
- `test_canary_proof_v2_rejects_non_strict_contract_version`: rejects booleans/coercion/wrong proof version.
- `test_canary_verification_v2_fails_each_new_exact_invariant`: every exact invariant fails closed.
- `test_bundle_v2_rejects_observation_for_different_exact_target`: cross-target evidence cannot combine.
- `test_bundle_cli_rejects_receipts_far_in_the_future`: actual UTC rejects future receipts.
- `test_migration_040_matches_new_discovery_failure_codes`: SQL and shared enum remain exact.

### 5. Decision Completeness

- Goal: land truthful, exact-target browser and persistence proof before runtime rollout.
- Non-goals: no PR-CANARY-04-07 work, broad crawler refactor, public API change, deployment, migration application, live canary, or activation.
- Success criteria: focused tests 0 failures; affected scope passes three consecutive runs; full repo/static/lock/migration/shell gates pass; QCHECK and formal g-check have no unresolved critical/high finding; reviewed PR SHA lands exactly on local/origin main.
- Public interfaces: no public endpoint or web surface change. Private interfaces are target schema v1, observation receipt schema v1, canary request/receipt schema v2, bundle schema v2; `run_remote_crawl.sh observe-canary <target> --receipt <path>` and `crawl-canary <target>`; verifier `canary` and `bundle` subcommands; additive migration `040`.
- Failure modes: invalid/private-file mismatch, lock busy, browser cleanup failure, page-order mismatch, exact claim mismatch, proof downgrade/reorder, artifact tamper, target mismatch, stale/future receipt, and open candidates all fail closed. Ordinary empty discovery remains non-error where existing contracts allow it.
- Rollout/monitoring: migration before writer; protocol disabled until source/runtime prerequisites pass; read-only observation before separately authorized ingestion; sanitized typed counters only; application rollback leaves additive schema but does not permit old receipt versions.
- Acceptance checks: the commands in Validation must exit 0; manifest must report 42 entries if `040` lands; final SHA equality and 0/0 ahead/behind are mandatory.

### 6. Dependencies

- Valid Luna-Max ownership receipt and validator for every production slice.
- Worktree-local Python 3.12 frozen environment and temporary PostgreSQL.
- SSH Git transport and explicit PR/merge authority for delivery.
- Separate runtime authority for deploy, migration, browser/write canary, supervision, and activation.

### 7. Validation

```bash
uv sync --frozen --all-packages --all-extras
uv lock --check
.venv/bin/python -m pytest tests/operations/test_diagnose_search_rows.py tests/operations/test_track_bc_verify.py tests/phase1/test_exact_canary_proof.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_entrypoint.py tests/phase1/test_worker_live_discovery.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_discovery_executor.py tests/phase2/test_exact_canary_claim.py tests/phase2/test_exact_canary_contract.py -q
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check apps packages tests scripts
.venv/bin/python -m compileall apps packages scripts
.venv/bin/python scripts/check_migration_manifest.py --check
bash -n scripts/run_remote_crawl.sh scripts/check_launch_gates.sh
git status --porcelain=v1
```

Repeat the complete affected pytest command three times after GREEN. Expected: every command exits 0; no identifiers/credentials appear in reports; only authorized paths differ from the ownership snapshot.

### 8. Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Exact target | API exact dispatch and operator target file | `discovery_dispatch.py` executor/service imports | `discovery_jobs`, profiles, keywords |
| Atomic exact-live claim | `DiscoveryDispatchProcessor.process_job()` | `discovery_job_repo.py` repository call | `discovery_jobs` tenant/job/profile inputs |
| Worker browser proof | worker `discover` command | `egp_worker.main` -> `workflows.discover` -> `browser_discovery` | run summary and JSONL evidence |
| Observation canary | `run_remote_crawl.sh observe-canary` | `diagnose_search_rows.py` CLI and native profile lock | target v1, observation receipt v1 |
| Exact verifier | `track_bc_verify.py canary` | CLI parser -> private request reader -> collector/verifier | candidates, projects, documents, captures, artifacts |
| Acceptance bundle | `track_bc_verify.py bundle` | CLI parser -> `verify_acceptance_bundle_v2()` | ordered private receipts v1/v2 |
| Failure vocabulary | migration runner before writer | migration manifest/readiness plus shared enum | migration `040` constraint values |

Each row requires one caller-level executable test and inspection of the registration site; library-only GREEN is insufficient.

### 9. Cross-Language Schema Verification

- Search migration `040`, Python enums, API, worker, scripts, shell, and runbook for every new failure code; exact set equality is required.
- Verify `discovery_jobs`, candidate-attempt, project, document, capture, and storage column names against migrations `001`, `038`, `039`, and candidate `040` plus repository SQL.
- Verify the private target/receipt contracts have no TypeScript/OpenAPI consumer and do not become a public API accidentally.
- Verify `manifest.sha256` has exactly one `040` entry and its digest matches the file.

### 10. Decision-Complete Checklist

- [x] Goal/non-goals and source/runtime boundary are locked.
- [x] Every private contract, CLI, and migration is named.
- [x] Each known failing invariant has an executable test.
- [x] Production ownership and receipt rejection rules are deterministic.
- [x] Wiring covers target, API claim, worker browser, persistence, verifier, bundle, and migration.
- [x] Validation, rollback, and monitoring are specific.
- [x] No implementer architecture decision remains.

## Plan Draft B — Preserve Tests, Reconstruct Unverifiable Production Paths

### 1. Overview

Treat the active production candidate as untrusted unless every Luna receipt validates. Preserve primary-owned tests, fixtures, plan, and evidence, then reconstruct each unverifiable production slice from clean `30ebdeec` in a fresh session-owned worktree through new bounded Luna-Max handoffs. This costs time but produces a cleaner ownership and provenance chain.

### 2. Files to Change

- Preserve the same tests, fixture, migration contract, runbook contract, and Coding Log listed in Draft A.
- Reconstruct only the production files from Draft A whose receipt, model/effort, HEAD, allowlist, or hashes fail validation.
- Do not copy opaque production hunks from the old worktree; use the tests and locked interface contract as the executable oracle.

### 3. Implementation Steps

1. Freeze and inventory the existing worktree without deleting it.
2. Validate receipts path-by-path. Mark each production path `accepted-candidate` or `reconstruct`; no partial trust.
3. Create a fresh worktree at exact `30ebdeec` if any production path is unverifiable.
4. For observation, API/claim, worker proof, and verifier/migration slices in dependency order:
   1. Apply only primary-owned tests/fixtures needed for the slice.
   2. Run and confirm the exact expected RED.
   3. Delegate one bounded allowlist to Luna-Max.
   4. Refactor minimally after GREEN.
   5. Primary validates receipt and reruns the scoped gate.
5. Integrate slices sequentially, compare behavior—not patch identity—with the preserved candidate, and reject any weakened test.
6. Run the same complete validation, QCHECK, g-check, PR, and exact-SHA landing gates as Draft A.

### 4. Test Coverage

- Use every named test in Draft A unchanged as the behavioral contract.
- Add `test_reconstructed_exact_dispatch_selects_live_browser_path`: caller reaches real browser workflow.
- Add `test_reconstructed_receipts_do_not_expose_target_identifiers`: all reports remain bounded/redacted.
- Retain the 16 current RED cases until their production slice passes; do not rewrite expectations to match the candidate.

### 5. Decision Completeness

- Goal: obtain the same truthful exact-canary behavior with a fully provable production authorship chain.
- Non-goals: no recovery of unverifiable code by manual primary editing; no new architecture; no runtime mutation.
- Success criteria: every production path has a valid new or retained Luna receipt; all Draft A gates and exact-SHA delivery criteria pass.
- Public interfaces: identical to Draft A; reconstruction must not create additional endpoints, flags, schemas, or migrations.
- Failure modes: a single invalid receipt reconstructs its whole allowlisted slice; repeated Luna failure blocks and forces replan; runtime and evidence failures remain fail closed.
- Rollout/monitoring: identical to Draft A; preserve the old worktree until new candidate and final merge are verified.
- Acceptance checks: Draft A commands plus a path/hash comparison proving protected files unchanged and no out-of-allowlist production path.

### 6. Dependencies

- Fresh worktree capacity and a clean exact-main baseline.
- Valid Luna-Max availability for every reconstructed production slice.
- Primary-owned tests and protected evidence remain recoverable from the existing worktree.

### 7. Validation

Run Draft A's validation commands plus ownership validation after every slice. Expected: exact HEAD baseline before work, model-bound receipt per slice, no out-of-allowlist changes, and identical final acceptance behavior.

### 8. Wiring Verification

Use the same component table as Draft A. Additionally, inspect every import/caller in the reconstructed worktree before accepting GREEN; no component may pass solely through a direct unit invocation.

### 9. Cross-Language Schema Verification

Repeat Draft A's checks from the reconstructed worktree. Migration `040` and the shared failure enum must be generated/validated once; no duplicate migration number or divergent vocabulary is allowed.

### 10. Decision-Complete Checklist

- [x] Reconstruction trigger is objective and path-scoped.
- [x] Tests and interfaces remain identical to the baseline contract.
- [x] No primary production edit or opaque patch transfer is permitted.
- [x] Every reconstructed component has caller-level wiring proof.
- [x] Delivery/runtime separation remains unchanged.

## Comparative Analysis and Synthesis

### Strengths

- Draft A is fastest and preserves already useful implementation evidence when receipts are valid.
- Draft B gives the strongest provenance when the mixed staged/unstaged candidate cannot be authenticated.

### Gaps and Trade-offs

- Draft A risks carrying hidden ownership or stale-hunk ambiguity unless validation is exact.
- Draft B adds worktree and implementation cost and may duplicate correct code, but it avoids accepting an unverifiable production candidate.
- Both plans deliberately avoid reopening PR-CANARY-01-03/F01-F08 and avoid starting PR-CANARY-04-07 before public-MVP acceptance.
- Both comply with repository TDD, primary ownership, Luna-only production writing, dirty-checkout preservation, and layered acceptance rules.

### Synthesis Decision

Use an evidence-gated hybrid: continue each valid path under Draft A and reconstruct only paths that fail receipt/allowlist/hash validation under Draft B. This is deterministic, minimizes duplicated work, and retains a strong production-ownership chain.

## Unified Execution Plan — Optimal Next Path

### 1. Overview

Complete the exact-canary repair before deployment and before PR-CANARY-04-07. Begin with ownership reconciliation, then close observation and verifier RED slices sequentially through Luna-Max, run the full local lifecycle, review and land one PR, and only afterward enter a separately authorized exact-SHA runtime acceptance tail.

### 2. Files to Change

- Authoritative scope is the Draft A file list.
- Continue a production file only when its existing ownership receipt validates.
- Reconstruct an invalid production slice in a fresh worktree using Draft B; tests, fixtures, plans, Coding Logs, and review artifacts remain primary-owned.
- Do not change other main-checkout user artifacts or start PR-CANARY-04-07 files.

### 3. Implementation Steps

1. Record main/worktree SHA, all changed paths, staged/unstaged state, protected hashes, and Luna receipts. Classify each production path as `continue` or `reconstruct`.
2. Observation slice TDD: retain expected RED; Luna implements target file v1, native profile lock, typed pagination, browser cleanup, and sanitized ordered receipt; primary validates receipt/diff/wiring/GREEN.
3. Exact claim/worker slice TDD: retain expected RED; Luna implements atomic `live=True` exact claim, input fingerprint binding, real browser selection, strict proof version/order, and durable terminalization; primary validates all evidence.
4. Verifier/bundle slice TDD: retain expected RED; Luna implements private file custody, tenant-scoped correlation, artifact byte integrity, observation-canary fingerprint equality, actual UTC freshness, and strict stage order; primary validates.
5. Migration/schema slice TDD: validate failure-code set and manifest RED/GREEN; Luna changes production SQL/enums if required; primary verifies exactly one `040` and cross-language equality.
6. Establish a worktree-local frozen environment. Run the focused suite until 0 failures, three affected repeats, then full repository/static/dependency/migration/shell gates.
7. Run independent QCHECK and formal g-check. Route every production remediation through a new bounded Luna slice; primary reruns all affected and final gates.
8. Commit and submit one repair PR. Verify SSH non-interactively, accepted head SHA, mergeability, and local evidence. If merge was authorized and only known zero-step billing-lock jobs are unavailable, record that distinction once and proceed under standing policy; never call those jobs passing.
9. Land exact accepted SHA to local/origin main and preserve the original dirty inventory. Clean the repair worktree only after hash/state verification.
10. Separate runtime tail: build/smoke exact merge-SHA images; refresh read-only production preflight; verify backup/stale runs/backlog/protocol/topology/authority; apply through migration `040`; deploy Track B then exact-SHA Track C; run read-only observation; only with separate authority run ingestion; supervise, rehearse rollback, verify fresh bundle v2, then activate.
11. After public-MVP runtime acceptance, refresh PR-CANARY-04-07 charters and allocate the next unused migration rather than historical `040`.

### 4. Test Coverage

- All Draft A named tests are mandatory.
- Cross-boundary oracle: observation fingerprint equals ingestion fingerprint; exact proof is strict integer version 1 and ordered browser -> pages -> terminal -> persistence validation -> dispatch finish; candidate/project/document/capture/retrieved bytes correlate to one tenant/job/profile/run.
- Stability oracle: affected suite passes three consecutive runs with no shared profile leak or browser process leak.
- Compatibility oracle: ordinary empty discovery and deterministic fault-injection paths retain their accepted behavior.

### 5. Decision Completeness

- Goal: truthful exact-target browser and persistence proof, source-accepted and ready for controlled runtime acceptance.
- Non-goals: no broad refactor, no reopening completed canary/F01-F08 work, no PR-CANARY-04-07 implementation, and no implied runtime authority.
- Success criteria: all source gates/reviews pass; exact accepted PR SHA lands on main; dirty user artifacts are preserved; runtime is described separately and remains unaccepted until executed.
- Public interfaces: no public API/web change. Private target v1, observation receipt v1, request/receipt/bundle v2, `observe-canary`/`crawl-canary`, verifier `canary`/`bundle`, and additive migration `040` are the complete changed surface.
- Edge/failure behavior: all mismatches, downgrade, reordering, stale/future timestamps, byte tamper, lock/cleanup error, wrong profile/backend/live state, and ownership failure are fail closed.
- Rollout/backout: reader/schema before writer; protocol remains off; observation precedes ingestion; application rollback keeps additive schema; old receipts cannot reactivate. Watch typed sanitized denial/failure counts, stuck jobs, candidate-attempt closure, browser cleanup, and artifact retrieval failures.
- Acceptance checks: Draft A validation commands exit 0; receipt validation and SHA reconciliation are exact; runtime gates produce fresh exact-SHA artifacts only when separately run.

### 6. Dependencies

- Same as Draft A, plus preserved access to the active candidate for evidence-gated comparison.
- Production environment access and mutation authority are not prerequisites for source completion, but are mandatory for the later runtime tail.

### 7. Validation

Run Draft A's command block, three affected repeats, ownership validation, QCHECK, formal g-check, and final:

```bash
git rev-parse HEAD
git rev-parse origin/main
.venv/bin/python scripts/check_main_sync.py --json
git status --porcelain=v1
```

Expected source result: accepted merge SHA equals local/origin main; ahead/behind is 0/0; worktree dirt is exactly the preserved user-owned baseline plus intentional lifecycle artifacts.

### 8. Wiring Verification

| Component | Runtime Caller | Registration/Authority | Schema/Evidence | Executable Oracle |
|---|---|---|---|---|
| Exact target | operator/API exact dispatch | executor/service/shared-type imports | target v1 and job/profile/keyword tuple | contract + executor tests |
| Exact live claim | `DiscoveryDispatchProcessor.process_job()` | repository CAS call | tenant-scoped `discovery_jobs` inputs | claim/dispatch tests |
| Browser/page proof | worker `discover` command | main -> workflow -> browser collector | summary plus ordered JSONL | worker/proof tests |
| Observation | guarded shell command | remote script -> diagnostic CLI -> profile lock | observation receipt v1 | observation tests |
| Persistence proof | worker repositories/artifact store | candidate/project/document workflow | attempts/projects/documents/captures/bytes | PostgreSQL verifier tests |
| Canary verifier | operator verifier command | CLI -> private reader -> v2 collector/verifier | request/receipt v2 | verifier tests |
| Acceptance bundle | operator bundle command | CLI -> v2 bundle verifier | runtime/observation/canary/supervised/rollback | bundle tests |
| Failure vocabulary | migration runner before writer | manifest/readiness/shared enum | migration `040` | migration tests |

### 9. Cross-Language Schema Verification

- Require exact SQL/Python/shell/docs vocabulary equality for every `040` failure code.
- Verify actual table/column names through migrations and repository queries across API, worker, verifier, and tests.
- Verify no public TypeScript/OpenAPI contract consumes private IDs or fingerprints.
- At future PR-CANARY-04 planning, inspect the live migration manifest and allocate the next unused number.

### 10. Decision-Complete Checklist

- [x] Current/log/PR source truth is reconciled.
- [x] Completed PR-CANARY/F01-F08 scope is protected from reopening.
- [x] Continue-versus-reconstruct is deterministic.
- [x] TDD sequence and Luna-only production ownership are locked.
- [x] Interfaces, failure modes, rollout, monitoring, and validation are explicit.
- [x] Every component has an entry point, registration site, schema/evidence source, and executable oracle.
- [x] Source delivery and runtime acceptance remain separate.
- [x] The next path contains no unresolved implementation decision.

## Execution Update (2026-09-01 14:50 +07) - ownership reconstruction through verifier GREEN

### Worktree and ownership reconciliation

- Protected primary checkout: `/Users/subhajlimanond/dev/egp`, `main` at
  `30ebdeec5665259e6495792e1f4715c630e1134e`; its pre-existing dirty logs and artifacts were not
  modified by implementation.
- Preserved candidate worktree: `/Users/subhajlimanond/dev/egp-exact-canary-false-success-repair`.
  The receipt-verified staged tree was committed as `6eccaaf9`, and the primary-owned review RED
  tests/docs were committed separately as `5ffbfebd`. Its later six unverified production edits
  remain unstaged and preserved for audit; they were not copied into the accepted candidate.
- Session-owned reconstruction worktree:
  `/Users/subhajlimanond/dev/egp-exact-canary-reconstructed`, branch
  `fix/exact-canary-reconstructed`, HEAD `5ffbfebd28ec4b82803a93e7d7439b9566b39a86`.
- Recovered the original S1-S5 receipt JSON from the prior session transcript. All fourteen staged
  production blobs matched the latest `luna_implementer` / `gpt-5.6-luna` / `max` receipt hashes.
  The six later production working copies did not match any receipt, so reconstruction began from
  the verified staged blobs plus only the primary-owned RED tests.
- Built a worktree-local frozen environment with `./scripts/bootstrap_python_env.sh`; uv 0.11.32
  synced all packages/extras into this worktree's `.venv` with editable paths rooted only here.

### Reconstructed GREEN slices

1. `EC-R1-CONTROL`
   - RED: exact cap 14 accepted and exact completed-run recovery reported dispatched: `2 failed,
     16 passed`.
   - Allowlist: `packages/shared-types/src/egp_shared_types/exact_canary.py`,
     `apps/api/src/egp_api/services/discovery_dispatch.py`.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r1-control-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r1-control-receipt.json`.
   - Primary validator: `verified=true`; primary full-file GREEN: `50 passed`.
2. `EC-R2-TRANSPORT`
   - RED: boolean proof version, pre-reservation cap mismatch, and seven worker effective-input
     mismatches: `9 failed, 33 passed`.
   - Allowlist: `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`,
     `apps/worker/src/egp_worker/main.py`.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r2-transport-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r2-transport-receipt.json`.
   - Primary validator: `verified=true`; primary GREEN: `42 passed`.
3. `EC-R3-BROWSER-PROOF`
   - RED: page event before browser start, terminal-page mismatch, and failed physical restore:
     `3 failed, 125 passed`.
   - Allowlist: `apps/worker/src/egp_worker/workflows/discover.py`,
     `apps/worker/src/egp_worker/browser_discovery.py`.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r3-browser-proof-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r3-browser-proof-receipt.json`.
   - Primary validator: `verified=true`; primary browser/proof/live GREEN: `199 passed`.
4. `EC-R3A-PHYSICAL-MARKER`
   - Primary diff inspection added a test proving that three successful clicks with a permanently
     unchanged DOM `active_page=1` cannot satisfy restore page 4. Expected RED: `1 failed`.
   - Allowlist: `apps/worker/src/egp_worker/browser_discovery.py` only.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r3a-physical-marker-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r3a-physical-marker-receipt.json`.
   - Primary validator: `verified=true`; primary focused GREEN: `3 passed`.
5. `EC-R4-OBSERVATION`
   - RED: target-file/fingerprint/profile-lock/browser-cleanup behavior missing: `7 failed,
     27 passed`.
   - Allowlist: `scripts/diagnose_search_rows.py`, `scripts/run_remote_crawl.sh`.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r4-observation-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r4-observation-receipt.json`.
   - Primary validator: `verified=true`; primary observation/remote/profile-lock GREEN: `46 passed`.
6. `EC-R5-VERIFIER-V2`
   - RED: matching non-TOR profile/job equality, byte tamper, exact custody, strict proof version,
     sanitized fingerprint propagation/equality, and actual-UTC future rejection; the pre-slice
     file reported eight production failures plus one malformed docs-only assertion.
   - Primary corrected the test-only literal patch-marker in the runbook assertion before the
     snapshot. Allowlist: `scripts/track_bc_verify.py` only.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r5-verifier-v2-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r5-verifier-v2-receipt.json`.
   - Primary validator: `verified=true`; primary complete verifier GREEN: `91 passed`.

### Wiring and remaining state

- Repository inspection confirms `_exact_canary_claim_conditions()` contains tenant/job/profile/
  keyword, `live IS TRUE`, legacy backend, profile/cap, and profile-keyword membership predicates;
  `claim_pending_discovery_jobs()` reuses the full predicate in the compare-and-swap UPDATE after
  taking the profile/job locks.
- Observation now reads the same strict private target, holds the native profile lock before
  singleton clearing, always shuts down/release-locks, and emits only the sanitized fingerprint.
- Verifier v2 keeps one tenant-scoped read-only DB transaction, validates strict proof/event order,
  compares observation/canary fingerprints, uses actual UTC, and retrieves artifact bytes to check
  stored size and SHA-256. Historical v1 report/CLI shapes remain unchanged.
- Pending: three identical affected-suite repeats, full pytest/Ruff/compileall/lock/migration/shell
  gates, wiring/schema audit, independent QCHECK, formal g-check and any Luna remediation, commit/PR,
  authorized merge, exact-SHA reconciliation, and worktree closeout.
- Explicitly not performed: deployment, production migration, browser observation, live ingestion,
  activation, or PR-CANARY-04-07 work.

## Execution Update (2026-09-01 18:45 +07) - QCHECK remediation and frozen gates

### Final reconstructed ownership slices

7. `EC-R6-CAPTURE-CORRELATION`
   - Primary wiring review found that ordinary exact-canary discovery did not write the run-linked
     successful `document_capture_attempts` row required by verifier v2. The primary added the
     exact workflow test and confirmed RED because no attempt existed.
   - Allowlist: `apps/worker/src/egp_worker/workflows/discover.py` only.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r6-capture-correlation-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r6-capture-correlation-receipt.json`.
   - Primary validator: `verified=true`; primary exact/backfill GREEN: `3 passed`.
8. `EC-R7-NATIVE-CUSTODY`
   - Independent Terra QCHECK found that exact ingestion could retain `per_run` profile mode,
     observation accepted a caller-supplied `--profile-dir`, and direct target execution accepted a
     missing or malformed release SHA. Primary RED proved reservation, Chrome launch, and runtime
     construction were reached in those invalid states.
   - Allowlist: `apps/api/src/egp_api/executors/discovery_dispatch.py`,
     `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`,
     `scripts/diagnose_search_rows.py`.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r7-native-custody-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r7-native-custody-receipt.json`.
   - Primary validator: `verified=true`; primary focused GREEN: `3 + 10 + 12 passed`.
9. `EC-R8A-INGESTION-EVIDENCE`
   - QCHECK also proved that same-project/time-window document matching was not complete custody.
     Primary locked a strict DB-private summary object connecting the exact candidate, project,
     later page, capture attempt, and exact document artifact records returned by ingestion.
   - Allowlist: `apps/worker/src/egp_worker/workflows/discover.py` only.
   - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r8a-ingestion-evidence-snapshot.json`,
     `/private/tmp/egp-exact-canary-ec-r8a-ingestion-evidence-receipt.json`.
   - Primary validator: `verified=true`; primary exact/backfill GREEN: `3 passed`.
10. `EC-R8B-VERIFIER-CORRELATION`
    - Primary PostgreSQL RED changed the evidence document ID to a nonexistent UUID while leaving a
      valid same-project document in the timestamp window. The prior collector still reported one
      retrievable artifact. The strict parser was also absent.
    - Allowlist: `scripts/track_bc_verify.py` only.
    - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r8b-verifier-correlation-snapshot.json`,
      `/private/tmp/egp-exact-canary-ec-r8b-verifier-correlation-receipt.json`.
    - Primary validator: `verified=true`; primary strict-parser plus PostgreSQL GREEN: `2 passed`.
    - Verifier v2 now requires exact candidate/project/page, capture-attempt ID/run/status/doc-count,
      document IDs/storage keys/sizes/digests, and retrieved-byte size/SHA equality in the same
      tenant-scoped read-only transaction. The broad timestamp-window query no longer exists in v2.

### Primary-owned test and environment corrections

- The first full-suite run exposed the pre-existing host-port assumption in
  `test_pg_restore_sh_rejects_system_database_target`: an unrelated OrbStack listener owned
  `localhost:5432`, producing `1 failed, 2226 passed, 4 skipped`. The primary changed only the test
  to use `TempPostgresCluster`; the next full run passed `2227 passed, 4 skipped` before the final
  exact-canary tests were added.
- Added a real-PostgreSQL race contract for exact claim. While the profile row is locked, a
  concurrent `discovery_jobs.live = FALSE` mutation is committed; the repository then rechecks the
  full exact predicate in CAS, returns no claim, and leaves the job pending with no token or
  processing timestamp. Complete claim file: `10 passed`.
- The full suite generated an untracked zero-byte `test.sqlite3` through an existing relative SQLite
  fixture. It was moved to macOS Trash after the suite so the candidate has no generated root DB
  artifact.

### Frozen final gates before final review

- Affected exact-canary suite, three consecutive runs: `416 passed`, `416 passed`, `416 passed`;
  zero failures in each run.
- Full repository suite: `2236 passed, 4 skipped, 114 warnings`; zero failures.
- `.tools/uv-0.11.32/bin/uv lock --check`: passed (`92` packages resolved from the frozen lock).
- Ruff across `apps packages tests scripts`: passed.
- `compileall apps packages scripts`: passed.
- `bash -n scripts/run_remote_crawl.sh scripts/check_launch_gates.sh`: passed.
- `git diff --check`: passed.
- Migration manifest: `42/42`, ending at migration `040`; no new migration was added.
- Pending at this point: independent QCHECK rerun, formal `g-check`, any Luna-only remediation,
  exact commit/PR/authorized merge/reconciliation and closeout.
- Still explicitly not performed: deployment, migration application to production, observation,
  live ingestion, supervision, activation, rollback, or PR-CANARY-04-07 work.

## Execution Update (2026-09-01 19:14 +07) - final QCHECK blockers remediated

### Additional Luna-Max ownership slices

11. `EC-R9A-CUSTODY-FAIL-CLOSED`
    - Independent QCHECK proved that a valid ordered five-page browser proof plus a persisted
      later-page project could still publish `succeeded` when no artifact custody graph existed.
      The primary added the exact workflow RED and a dispatcher propagation check.
    - Allowlist: `apps/worker/src/egp_worker/workflows/discover.py` only.
    - Snapshot/receipt:
      `/private/tmp/egp-exact-canary-ec-r9a-custody-fail-closed-snapshot.json`,
      `/private/tmp/egp-exact-canary-ec-r9a-custody-fail-closed-receipt.json`.
    - Primary validator: `verified=true`; primary focused GREEN: `3 passed`.
    - An exact target without `canary_ingestion_evidence` now preserves its valid browser proof but
      terminates `failed` with sanitized `canary_ingestion_evidence_missing`,
      `canary_proof_invalid`, and one error. Ordinary discovery and exact runs with full custody are
      unchanged.
12. `EC-R9B-PUBLIC-REDACTION`
    - Independent QCHECK found that the DB-private custody graph was returned verbatim by the
      generic runs endpoint and project crawl-evidence endpoint, exposing candidate/project/
      capture/document identifiers and storage keys to viewers.
    - Allowlist: `apps/api/src/egp_api/services/public_run_summary.py`,
      `apps/api/src/egp_api/routes/runs.py`, `apps/api/src/egp_api/routes/projects.py`.
    - Snapshot/receipt: `/private/tmp/egp-exact-canary-ec-r9b-public-redaction-snapshot.json`,
      `/private/tmp/egp-exact-canary-ec-r9b-public-redaction-receipt.json`.
    - Primary validator: `verified=true`; primary focused GREEN: `2 passed`.
    - Both public run-summary serializers now use one non-mutating typed sanitizer that removes the
      entire `canary_ingestion_evidence` top-level key while preserving all other summary fields.
      Database storage and the private verifier path remain unchanged.

### Deterministic race oracle and refreshed frozen gates

- The primary strengthened the PostgreSQL exact-claim race test to wait for `pg_stat_activity` to
  report the named claim connection actively blocked on the profile `FOR UPDATE` lock before
  changing `discovery_jobs.live`. The monitor uses autocommit so each poll observes fresh activity;
  the failure branch releases the held lock before joining the worker. Focused result: `1 passed`.
- Canonical affected command expanded for the new public serializer tests, three consecutive runs:
  `473 passed`, `473 passed`, `473 passed`; zero failures in every run.
- Full repository suite: `2239 passed, 4 skipped, 114 warnings`; zero failures.
- `.tools/uv-0.11.32/bin/uv lock --check`: passed (`92` packages resolved).
- Ruff across `apps packages tests scripts`: passed.
- `compileall apps packages scripts`: passed.
- `scripts/check_migration_manifest.py --check`: passed, `42/42`, ending at migration `040`.
- `bash -n scripts/run_remote_crawl.sh scripts/check_launch_gates.sh`: passed.
- `git diff --check`: passed.
- Pending: independent QCHECK rerun, formal `g-check`, any receipt-bounded Luna remediation,
  exact commit/PR/authorized merge/reconciliation, and worktree closeout.
- Still explicitly not performed: deployment, production migration, browser observation, live
  ingestion, supervision, activation, rollback, or PR-CANARY-04-07 work.

## Formal g-check (2026-09-01 19:28 +07)

### Scope and evidence

- Branch/HEAD: `fix/exact-canary-reconstructed` at
  `5ffbfebd28ec4b82803a93e7d7439b9566b39a86`; review target was the complete uncommitted
  24-path candidate (`22` modified, `2` new).
- Independent Terra QCHECK rerun: `PASS`; no unresolved critical, high, or medium findings, and no
  remaining public run-summary path was found to emit `canary_ingestion_evidence`.
- RepoPrompt deep review artifact: snapshot `2026-09-01/1922`, complete `all.patch`, relevant full
  source context for exact target, claim repository, worker workflow, verifier, sanitizer, and
  concurrency/redaction tests.
- Primary gates considered: canonical affected suite `473 passed` three consecutive times; full
  repository `2239 passed, 4 skipped, 114 warnings`; frozen lock, Ruff, compileall, migration
  manifest `42/42`, shell syntax, and diff check all passed.

### Findings

No actionable P0, P1, or P2 findings.

### Residual risks and boundaries

- Production-like end-to-end execution combining a real browser, PostgreSQL, persistent-profile
  lock, document ingest, artifact retrieval, subprocess dispatch, and final verifier acceptance is
  intentionally deferred to the separately authorized runtime tail. This review does not call that
  runtime acceptance complete.
- The deterministic PostgreSQL contention test mutates `discovery_jobs.live`; concurrent
  profile-keyword replacement is not separately contention-tested, although the exact predicate is
  repeated in CAS and downstream authorization remains fail-closed.
- Public redaction is centralized and directly tested for the current run-list and project
  crawl-evidence serializers. Any future public run-summary serializer or nested custody contract
  must reuse/extend the sanitizer and add a corresponding response test.
- The sole warning classes are pre-existing TestClient/SQLite/JWT library warnings; no warning was
  promoted into acceptance evidence.

### Disposition

`PASS` for source delivery. No review remediation is required before commit/PR delivery. This is not
deployment, production migration, browser observation, live ingestion, supervision, activation, or
PR-CANARY-04-07 authorization.
