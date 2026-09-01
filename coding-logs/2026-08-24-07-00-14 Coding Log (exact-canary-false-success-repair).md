# Coding Log: exact-canary-false-success-repair

- Created: 2026-08-24 07:00:14 +07
- Baseline: `origin/main` / `30ebdeec5665259e6495792e1f4715c630e1134e`
- Branch: `fix/exact-canary-false-success-repair`
- Worktree: `/Users/subhajlimanond/dev/egp-exact-canary-false-success-repair`
- Lifecycle: `g-planning` -> `g-coding` -> QCHECK -> `g-check` -> PR -> authorized admin merge -> exact local-main landing -> worktree cleanup

## Planning evidence

- Root cause supplied by the user: exact-target execution forces `live=False`, so the worker never launches Chrome and an empty non-browser input can appear successful.
- RepoPrompt was bound to this isolated worktree and traced target parsing, claim filters, worker subprocess dispatch, browser discovery, pagination, diagnostics, verifier receipts, migrations, and focused tests.
- Current source confirms `require_non_live_target=(target_job_id is not None or fault_mode is not None)` in the executor and `only_live=False` in the processor exact-claim scope.
- Current source confirms silent pagination exits for max-pages, absent/hidden/disabled next control, failed click, page-change timeout, and unexpected no-results after advance.
- Current diagnostics hard-code row indexes and default to seven pages; the production parser uses header-derived columns.
- Current verifier emits canary schema v1 and correlates job/run/candidate/project/document/artifact/process evidence, but it does not correlate the full operator target or ordered browser proof.
- Migration `039` is current maximum. The next migration is `040`; the existing constraint name is `discovery_jobs_last_error_code_check`.
- Plan correction against the first RepoPrompt draft: do not hard-code a five-page maximum. The target pins the configured cap (15 for the current canary), while acceptance requires contiguous proof through at least pages 1-5 and full termination under that cap.

# Plan Draft A - Atomic cross-layer proof contract

## Overview

Implement the observation and ingestion canaries as one atomic cross-layer release. Introduce a strict target contract, shared parser and typed pagination state machine, thread browser proof through the worker result, and upgrade the verifier to canary receipt v2 in the same PR.

## Files to change

- `packages/shared-types/src/egp_shared_types/exact_canary.py`: versioned target/proof contract and canonical digest.
- `packages/shared-types/src/egp_shared_types/enums.py`: pagination outcomes and new persisted failure codes.
- `packages/db/src/migrations/040_exact_canary_failure_codes.sql`: widen the discovery failure-code check constraint.
- `packages/db/src/migrations/manifest.sha256`: register migration 040 without changing historical hashes.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`: exact multi-field claim predicates.
- `packages/db/src/egp_db/repositories/candidate_attempt_repo.py`: later-page persisted-candidate evidence.
- `packages/db/src/egp_db/repositories/profile_repo.py`: expose the persisted page cap/backend needed for defense-in-depth checks.
- `apps/api/src/egp_api/executors/discovery_dispatch.py`: parse/authorize target v1 and reject zero/mismatched dispositions.
- `apps/api/src/egp_api/services/discovery_dispatch.py`: separate exact live ingestion targeting from non-live fault injection.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: pin target settings and validate worker proof.
- `apps/worker/src/egp_worker/main.py`: parse the internal target and return bounded proof.
- `apps/worker/src/egp_worker/browser_discovery.py`: shared page parser, typed pagination, ordered proof events, browser-start event.
- `apps/worker/src/egp_worker/workflows/discover.py`: proof accumulator, legitimate zero-result handling, precise failure mapping.
- `packages/observability/src/egp_observability/subprocess_evidence.py`: optional target digest/version evidence correlation.
- `scripts/diagnose_search_rows.py`: observation mode using production parser/pagination with no persistence.
- `scripts/run_remote_crawl.sh`: separate `observe-canary` and `crawl-canary` commands.
- `scripts/track_bc_verify.py`: private request v2, canary receipt v2, observation receipt, bundle v2.
- `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`: two-stage canary procedure and rollback.
- Focused tests and `tests/fixtures/discovery/sanitized_five_page_results.json`.

## Implementation steps

1. Add target/enums/migration tests; confirm RED; implement shared contracts and migration 040; run enum/migration gates.
2. Add exact-claim and executor authorization tests; confirm RED; implement exact live claim and nonzero no-work behavior.
3. Add shared-parser and typed-pagination tests over the five-page fixture; confirm RED; implement parser/state machine and convert production discovery.
4. Add workflow proof and ordinary-zero tests; confirm RED; implement proof accumulation and precise failures.
5. Add subprocess/worker proof tests; confirm RED; thread and validate bounded proof atomically.
6. Add observation tests; confirm RED; convert diagnostics and shell routing.
7. Add receipt-v2/bundle tests; confirm RED; upgrade verifier and runbook.
8. For every slice: smallest GREEN, minimal refactor, scoped lint/compile/tests, wiring verification.

## Function outlines

- `ExactIngestionCanaryTarget.from_mapping()`: validate the strict v1 JSON shape and normalized values.
- `ExactIngestionCanaryTarget.canonical_digest()`: hash canonical private correlation fields without logging them.
- `claim_next_job(... exact_canary_target=...)`: repeat all target predicates in select and CAS update.
- `_report_exact_canary_outcome()`: return success only for one exact dispatched job with no failure.
- `parse_results_page()`: resolve header-derived columns once and return immutable sanitized row values.
- `advance_results_page()`: return a typed terminal, advanced, or failed outcome; never silently break.
- `LiveScanProofAccumulator.observe()`: enforce browser-before-page, contiguous pages, one terminal event, and no late events.
- `_validate_canary_proof()`: compare worker proof with the exact target and fail closed.
- `run_observation_canary()`: launch real Chrome, scan read-only, emit sanitized proof, and always clean up.
- `collect_canary_evidence()`: correlate exact target, ordered proof, candidate/project/document/artifact, and evidence log in one read-only transaction.

## Test coverage

- `test_exact_target_rejects_missing_or_extra_fields`: strict private schema fails closed.
- `test_exact_target_digest_is_canonical_and_private`: normalized stable digest without disclosure.
- `test_exact_claim_requires_live_legacy_profile_keyword_and_cap`: every pinned mismatch prevents mutation.
- `test_exact_dispatch_zero_claim_returns_nonzero`: empty input cannot pass canary.
- `test_fault_injection_remains_non_live_and_separate`: prior fault semantics remain unchanged.
- `test_parser_handles_shifted_headers_from_five_page_fixture`: shared parser resists column drift.
- `test_pagination_emits_contiguous_pages_one_through_five`: ordered traversal is explicit.
- `test_each_former_silent_break_has_typed_outcome`: no unclassified pagination termination.
- `test_initial_keyword_no_results_is_ordinary_success`: legitimate zero-result jobs remain valid.
- `test_exact_canary_rejects_zero_result_proof`: stricter canary does not weaken globally.
- `test_browser_start_precedes_page_events`: proof requires real Chrome connection.
- `test_worker_proof_rejects_digest_or_page_mismatch`: subprocess correlation fails closed.
- `test_observation_canary_has_no_persistence_dependencies`: read-only architecture is enforced.
- `test_observation_receipt_proves_pages_one_through_five_under_cap_fifteen`: current acceptance contract.
- `test_canary_receipt_v2_correlates_full_chain`: candidate/project/document/artifact proof is exact.
- `test_bundle_v2_requires_observation_before_ingestion`: acceptance order is enforced.
- `test_migration_040_matches_discovery_failure_enum`: SQL/SQLAlchemy/shared vocabulary cannot drift.

## Decision completeness

- Goal: prevent non-browser/partial-pagination false success and produce exact correlated browser evidence.
- Non-goals: deploy or activate a crawler, change ordinary scheduling, replace candidate ledger, or rework the HTTP agent backend.
- Success: observation proves real Chrome plus contiguous pages 1-5 with pinned cap 15 and no DB persistence; ingestion proves one exact live legacy job plus correlated candidate/project/document/artifact evidence; every old silent pagination exit is typed; zero claimed work is nonzero; ordinary genuine zero results still succeed.
- Public/private interfaces: target JSON contract v1; internal worker proof object; observation receipt v1; canary receipt v2; acceptance bundle v2; `observe-canary` shell command; migration 040.
- Fail closed: invalid target, wrong job/profile/keyword/backend/live/cap, missing browser proof, page gaps/reordering, click/timeouts/site errors, no exact disposition, receipt mismatch.
- Fail open only for ordinary semantics: initial legitimate no-results, all-skipped, and all-deduplicated scans complete successfully with typed terminal summaries.
- Rollout: apply migration 040, deploy application atomically, run observation, then separately authorize ingestion. Backout application while leaving widened constraint in place; old canary receipts are not accepted as new evidence.
- Monitoring: typed failure code counts, executor exact-target denial/mismatch events, pagination terminal/failure outcome, proof validation event order, run/job/candidate terminality.

## Dependencies

- Real macOS Chrome and warmed persistent profile for operational observation/ingestion.
- PostgreSQL for exact claim/verifier integration tests.
- Existing candidate ledger, document capture attempts, artifact store, bounded evidence writer.

## Validation

- Focused pytest files for shared types, migration, repository claim, executor, browser, workflow, dispatcher, diagnostics, verifier.
- `uv run --frozen ruff check apps packages tests scripts`
- `uv run --frozen python -m compileall apps packages scripts`
- migration manifest checker and migrated temporary PostgreSQL tests.
- Full `uv run --frozen python -m pytest tests apps packages -q`.
- Repeat affected scope three times.

## Wiring verification

| Component | Entry point | Registration/config load | Schema/contract |
|---|---|---|---|
| Target v1 | executor `main()` / `--target-file` | `_authorize_exact_canary_target()` | exact job/profile/keyword/live/backend/cap |
| Exact claim | `DiscoveryDispatchProcessor.process_pending_jobs()` | runtime processor construction | `discovery_jobs`, `crawl_profiles`, `crawl_profile_keywords` |
| Shared parser | `crawl_live_discovery()` and diagnostic observation | direct imports in worker/diagnostic | page headers/rows |
| Typed pagination | `_collect_keyword_projects()` | worker browser loop | `DiscoveryPaginationOutcome` |
| Worker proof | `egp_worker.main` framed result | subprocess JSON payload | target digest + ordered pages |
| Migration 040 | migration runner | manifest checksum | `discovery_jobs.last_error_code` constraint |
| Observation | `run_remote_crawl.sh observe-canary` | diagnostic CLI | receipt v1, no DB/artifact state |
| Canary verifier | `track_bc_verify.py canary` | private request v2 | exact DB and artifact correlation |
| Bundle verifier | `track_bc_verify.py bundle` | ordered receipt list | bundle schema v2 |

## Cross-language schema verification

- Python repository and PostgreSQL migration both use `discovery_jobs.last_error_code` and constraint `discovery_jobs_last_error_code_check`.
- Exact correlation uses `discovery_jobs`, `crawl_profiles`, `crawl_profile_keywords`, `crawl_runs`, `discovery_candidate_attempts`, `projects`, `documents`, and `document_capture_attempts`.
- No Go service consumes these tables. The web app consumes run progress stages only; existing unknown-stage fallback remains compatible, with optional display labels added only if tests require them.

# Plan Draft B - Compatibility-first staged internals

## Overview

Keep one PR but structure the internals as two compatibility phases: first land the shared parser, typed pagination, observation canary, ordinary-zero correction, and migration; then enable exact live ingestion proof and receipt v2 behind strict target-file presence. This reduces simultaneous protocol changes but temporarily carries compatibility adapters inside the branch.

## Files to change

The same files as Draft A, but `browser_discovery.py`, diagnostics, enums/migration, and observation tests form phase 1; executor/claim/worker/verifier changes form phase 2. Compatibility adapters accept old non-canary worker payloads while requiring proof only when exact target data is present.

## Implementation steps

1. Test and implement shared parser without changing observable production decisions.
2. Test and implement typed pagination plus ordinary-zero semantics.
3. Test and implement observation canary and sanitized observation receipt.
4. Test and implement target v1, exact live claim, and worker proof with optional fields for ordinary jobs.
5. Test and implement canary receipt v2 and bundle v2, rejecting old canary acceptance only at verifier boundary.
6. Run cross-phase integration and full gates.

## Function outlines

- `parse_results_page()` and `advance_results_page()`: stable shared browser boundary first.
- `run_observation_canary()`: operational proof before ingestion mutation is possible.
- `ExactIngestionCanaryTarget` and exact claim predicates: phase-2 authorization.
- `validate_optional_canary_proof()`: no behavior change for ordinary worker payloads; strict for exact mode.
- `verify_canary_evidence()`: schema-v2-only acceptance for exact canary.

## Test coverage

- `test_ordinary_worker_result_without_canary_proof_stays_compatible`: non-canary protocol remains valid.
- `test_exact_worker_result_requires_canary_proof`: strictness is mode-scoped.
- All parser, pagination, observation, claim, receipt, migration, and bundle cases from Draft A.

## Decision completeness

- Goal/non-goals/success criteria match Draft A.
- Compatibility decision: ordinary dispatch and fault injection never require new target/proof fields; only exact ingestion does.
- Rollout/backout: one deployed release, but implementation can be tested in compatibility phases. Migration remains forward-compatible.
- Failure behavior: compatibility applies only when exact mode is absent; exact mode always fails closed.

## Dependencies

Same as Draft A. Phase 2 depends on phase-1 parser/pagination event contracts.

## Validation

Run phase-1 browser/diagnostic tests before phase-2 executor/worker/verifier tests, then the same final gates and three repeats as Draft A.

## Wiring verification

| Component | Entry point | Registration/config load | Schema/contract |
|---|---|---|---|
| Phase-1 observation | diagnostic CLI | shell subcommand | observation receipt v1 |
| Phase-2 ingestion | executor target CLI | exact-target runtime branch | target v1 + canary receipt v2 |
| Compatibility | ordinary/fault dispatch | target absent | existing worker/fault contracts unchanged |

## Cross-language schema verification

Same table/constraint inventory as Draft A; compatibility does not alter schema names.

# Comparative analysis

## Strengths

- Draft A minimizes intermediate adapters and makes the new proof contract easy to reason about as one atomic change.
- Draft B reduces diagnostic uncertainty by stabilizing parser/pagination behavior before threading exact-ingestion proof.

## Gaps and trade-offs

- Draft A creates a very large first GREEN handoff and makes failures harder to isolate.
- Draft B risks retaining compatibility code longer than needed and could accidentally make exact proof optional if mode checks are weak.
- Both must preserve ordinary zero-result and fault-injection behavior, validate PostgreSQL constraints, and keep the observation path persistence-free.

## Compliance

- Both follow tests-first sequencing, shared enums/schema alignment, tenant-scoped repository access, thin entrypoints, PostgreSQL as source of truth, and no primary-authored production code under `g-coding`.

# Unified Execution Plan

## Overview

Use Draft B's bounded internal slices but Draft A's single strict delivered contract. The final PR contains no feature flag: ordinary/fault paths remain backward compatible by mode, while exact ingestion always requires target v1 and proof; canary acceptance always requires observation plus canary receipt v2.

## Files to change

### Shared contract and schema

- `packages/shared-types/src/egp_shared_types/exact_canary.py`
- `packages/shared-types/src/egp_shared_types/enums.py`
- `packages/db/src/migrations/040_exact_canary_failure_codes.sql`
- `packages/db/src/migrations/manifest.sha256`
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`
- `packages/db/src/egp_db/repositories/profile_repo.py`
- `packages/db/src/egp_db/repositories/candidate_attempt_repo.py`

### Browser, worker, and dispatcher

- `apps/worker/src/egp_worker/browser_discovery.py`
- `apps/worker/src/egp_worker/workflows/discover.py`
- `apps/worker/src/egp_worker/main.py`
- `apps/api/src/egp_api/services/discovery_dispatch.py`
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
- `apps/api/src/egp_api/executors/discovery_dispatch.py`
- `packages/observability/src/egp_observability/subprocess_evidence.py`

### Operations and evidence

- `scripts/diagnose_search_rows.py`
- `scripts/run_remote_crawl.sh`
- `scripts/track_bc_verify.py`
- `docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md`

### Tests and fixture

- `tests/fixtures/discovery/sanitized_five_page_results.json`
- `tests/phase1/test_worker_browser_discovery.py`
- `tests/phase1/test_worker_live_discovery.py`
- `tests/phase1/test_worker_entrypoint.py`
- `tests/phase1/test_api_discovery_spawn.py`
- `tests/phase1/test_migration_runner.py`
- `tests/phase2/test_discovery_executor.py`
- `tests/phase2/test_discovery_dispatch.py`
- `tests/phase2/test_exact_canary_claim.py`
- `tests/operations/test_diagnose_search_rows.py`
- `tests/operations/test_track_bc_verify.py`
- Existing fault-injection tests for regression.

## TDD implementation sequence

### S1 - Target contract, schema, and exact claim

1. Add contract, migration-vocabulary, exact-claim, executor authorization, and zero-disposition tests.
2. Run exact focused commands and confirm missing contract/claim behavior RED.
3. Snapshot production ownership and delegate only shared type, enum, migration, manifest, repository, processor, and executor files to Luna-Max.
4. Verify receipt; run GREEN; verify target predicates at select and CAS; run lint/compile.

### S2 - Shared parser, typed pagination, and observation

1. Add the sanitized fixture and parser/pagination/ordinary-zero/observation tests.
2. Confirm RED for duplicated parser, silent exits, no browser proof, and false ordinary-zero failure.
3. Delegate browser/workflow/diagnostic/shell files to Luna-Max.
4. Verify receipt; run GREEN; confirm no observation code constructs DB/artifact repositories; run lint/compile.

### S3 - End-to-end ingestion proof

1. Add worker-entrypoint, subprocess validation, proof-order, later-page persistence, and evidence correlation tests.
2. Confirm RED for missing/mismatched proof.
3. Delegate worker main, workflow proof accumulator, dispatcher, candidate query, and evidence fields to Luna-Max.
4. Verify receipt; run GREEN; trace target -> claim -> subprocess -> browser -> run summary/evidence.

### S4 - Receipt v2, bundle, and runbook

1. Add verifier request-v2, target/profile/page/digest/candidate/project/document/artifact, observation, sanitization, and bundle-order tests.
2. Confirm RED for schema-v1 acceptance and missing observation/order proof.
3. Delegate verifier production script to Luna-Max; primary updates documentation after the CLI contract is green.
4. Verify receipt; run GREEN; execute migration/verifier/operations tests and docs checks.

### Finalization

1. Run focused affected gates and full repository gates.
2. Run the affected pytest scope three consecutive times.
3. Verify every wiring-table cell with source locations and executable tests.
4. Perform skeptical QCHECK and formal `g-check`; route production remediation through a new bounded Luna slice.
5. Commit intended files, push the feature branch, open one PR to `main`, inspect compact required-check state, and apply standing billing-lock policy only to known zero-step billing failures.
6. Admin-merge after local gates/review/head/mergeability pass; fetch; land exact merged SHA onto local main without disturbing pre-existing dirty files.
7. Preserve the Coding Log on landed main, verify primary checkout state matches its baseline dirty inventory plus this merged log, remove the session worktree, and prune only verified stale worktree metadata.

## Locked contract details

- Target v1 exact keys: `contract_version`, `kind`, `tenant_id`, `job_id`, `profile_id`, `keyword`, `live`, `execution_backend`, `browser_required`, `max_pages_per_keyword`.
- Fixed values: version `1`, kind `exact_ingestion_canary`, `live=true`, backend `legacy`, browser required `true`.
- `max_pages_per_keyword` is a positive integer bounded by the platform limit; current authorized target must pin `15`.
- Keyword is trimmed, NFC-normalized, non-empty, bounded, and control-character-free.
- Private target/request files are regular, owner-only, exact mode `0600`, opened with no-follow semantics.
- Exact claim matches tenant/job/profile/keyword/live/backend/profile backend/profile cap/profile keyword membership in both selection and CAS update.
- Observation and ingestion require real Chrome launch/connect before page events.
- Ordered proof is contiguous from page 1, includes at least pages 1-5 for current acceptance, and ends exactly once with a typed terminal outcome.
- Successful terminal outcomes: next absent, next disabled, or max-pages reached exactly at the pinned cap. Hidden control, click failure, page-change timeout, unexpected no-results after advance, and site error fail closed.
- Initial post-recovery no-results is a legitimate ordinary success with zero pages/candidates, but it never satisfies observation or exact-ingestion canary acceptance.
- Canary proof contains only version/digest/browser boolean/page sequence/cap/terminal outcome/later-page persistence boolean; no tenant/job/profile/keyword/path/PID.
- Canary request schema v2 embeds the exact target plus run ID; sanitized canary receipt schema v2 never exposes identifiers or target digest.
- Receipt v2 requires exact target/job/run/candidate/project/document/artifact correlation, zero open candidates, at least one persisted candidate from page 2 or later, retrievable artifact, stopped child, unlocked profile, bounded/redacted ordered evidence, exact release SHA.
- Bundle v2 requires ordered runtime(v1), observation(v1), canary(v2), supervised(v1), and rollback(v1) evidence.

## Test coverage

Use the named tests from Draft A plus:

- `test_exact_claim_rechecks_target_predicates_during_cas`: profile/job mutation cannot race authorization.
- `test_pagination_max_reached_only_accepts_pinned_cap`: early cap mismatch fails proof.
- `test_resume_preserves_logical_page_number`: browser recovery cannot duplicate page one.
- `test_events_after_terminal_invalidate_proof`: no post-terminal success laundering.
- `test_receipt_v2_redacts_target_digest_and_identifiers`: private fields never escape.
- `test_candidate_project_document_artifact_share_run_and_tenant`: correlation cannot cross runs/tenants.

## Decision completeness

- Goal: exact browser-backed evidence with no false success.
- Non-goals: runtime deployment/activation, live canary execution during this code lifecycle, changes to agent backend, or broad crawler redesign.
- Measurable success: all named tests and gates pass; every former silent exit is typed; current policy proves pages 1-5 under cap 15; exact zero-work exits nonzero; receipt v2 and bundle v2 reject missing/mismatched proof; ordinary zero-result and fault tests remain green.
- Interfaces: locked above; no new environment variable is required. `observe-canary` is new; `crawl-canary` changes to target-v1 live ingestion.
- Edge/failure modes: fail closed on all exact-target/proof/correlation ambiguity; ordinary no-results remains fail open as a successful typed empty scan.
- Rollout/backout: migration then atomic app release; observation before ingestion; application rollback leaves widened constraint; no migration rollback that could reject already-written new codes.
- Monitoring: count typed pagination failures and proof denials; audit exact target authorization without identifiers; inspect terminal event order and candidate terminality.
- Acceptance commands: focused pytest, migration manifest, temporary PostgreSQL migration/claim tests, ruff, compileall, full pytest, three repeats.

## Dependencies

- Python 3.12 environment from `uv.lock`.
- Temporary PostgreSQL binaries or Docker Postgres for real-schema tests.
- Operational acceptance later requires Mac Chrome/persistent profile, but code delivery does not execute a live production canary.

## Validation commands

```bash
uv run --frozen python -m pytest \
  tests/phase1/test_worker_browser_discovery.py \
  tests/phase1/test_worker_live_discovery.py \
  tests/phase1/test_worker_entrypoint.py \
  tests/phase1/test_api_discovery_spawn.py \
  tests/phase1/test_migration_runner.py \
  tests/phase2/test_discovery_executor.py \
  tests/phase2/test_discovery_dispatch.py \
  tests/phase2/test_exact_canary_claim.py \
  tests/operations/test_diagnose_search_rows.py \
  tests/operations/test_track_bc_verify.py -q
uv run --frozen python scripts/check_migration_manifest.py
uv run --frozen ruff check apps packages tests scripts
uv run --frozen python -m compileall apps packages scripts
uv run --frozen python -m pytest tests apps packages -q
```

Run the affected pytest command three consecutive times after the full gate.

## Wiring verification

| Component | Non-test call site | Registration/config load | Schema/contract match |
|---|---|---|---|
| Exact target v1 | executor `main()` | `--target-file` authorization | job/profile/keyword/live/backend/cap |
| Exact claim | dispatch processor | executor runtime factory | tenant-scoped three-table predicates |
| Shared parser | worker scan + observation diagnostic | direct import | header-derived row contract |
| Pagination state machine | `_collect_keyword_projects()` | browser settings cap | typed outcome enum |
| Browser proof | live crawl progress callback | workflow accumulator | target digest/page contract |
| Worker proof | framed worker result | subprocess dispatcher | exact target request |
| Failure codes | workflow/dispatcher | shared enum | migration 040 + SQLAlchemy check |
| Observation receipt | diagnostic observation CLI | shell `observe-canary` | schema v1, no persistence |
| Canary receipt | verifier canary CLI | private request v2 | exact DB/evidence/artifact chain |
| Bundle v2 | verifier bundle CLI | ordered receipt input | stage schemas/order |

## Cross-language schema verification

- Python SQLAlchemy: `DISCOVERY_FAILURE_CODE_VALUES` feeds `discovery_jobs_last_error_code_check`.
- PostgreSQL: migration 032 created the same named constraint; migration 040 drops/recreates it with the complete enum vocabulary.
- Verifier query paths: `discovery_jobs` -> `crawl_runs` -> `discovery_candidate_attempts` -> `projects` -> `documents` plus `document_capture_attempts`; all joins include `tenant_id` and run correlation.
- Profile correlation: `crawl_profiles` and `crawl_profile_keywords` match exact target and job fields.
- No non-Python schema consumer is changed; TypeScript only renders progress stages and keeps its default fallback.

## Decision-complete checklist

- [x] No open architecture or public-contract decisions remain.
- [x] New/changed private interfaces and receipt versions are named consistently.
- [x] Every behavior change has a failing test listed.
- [x] Validation commands are specific and scoped.
- [x] Wiring table covers each component, migration, and CLI.
- [x] Rollout and backout distinguish source delivery from later runtime acceptance.

## S1 implementation - target, schema, exact claim, executor

- Goal: replace the two-field non-live exact target with a strict versioned live legacy-browser target and make zero/mismatched execution fail closed.
- Primary-owned RED: `/Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase2/test_exact_canary_contract.py tests/phase2/test_exact_canary_claim.py tests/phase2/test_discovery_executor.py -q` -> 27 failed, 36 passed. Expected failures were missing target module/migration/codes/claim API, old target schema rejection, and old zero-work semantics.
- Ownership snapshot: `/private/tmp/egp-exact-canary-s1-snapshot.json`.
- Production owner: logical `luna_implementer`, model `gpt-5.6-luna`, reasoning effort `max`.
- Receipt: `/private/tmp/egp-exact-canary-s1-receipt.json`.
- Ownership validator: passed; exact seven-file allowlist; no protected-file drift; hashes matched.
- Production files: target module, failure enum, migration 040/manifest, discovery job repository, dispatch service, executor.
- Primary-owned GREEN: explicit worktree-source `PYTHONPATH` plus the S1 pytest command -> 63 passed in 2.22s.
- Environment note: the existing shared `.venv` has editable installs resolving to `/Users/subhajlimanond/dev/egp`; worktree gates must prepend this worktree's app/package `src` paths.
- Primary fast gates: Ruff passed; compileall passed; `check_migration_manifest.py --check` passed for 42 files.
- Wiring: target file -> executor authorization -> runtime exact target -> processor exact claim -> tenant-scoped profile/keyword/job select and CAS -> dispatch request. Exact failures terminalize; fault injection remains separate and non-live.
- Remaining: browser/parser/pagination/observation, end-to-end proof, verifier receipt v2, full gates/review/delivery.

## S2A implementation - shared parser and typed pagination

- Goal: eliminate silent pagination exits, share one header-derived row parser, preserve logical page numbers across browser recovery, and make ordinary initial no-results an explicit successful empty scan without satisfying canary acceptance.
- Primary-owned RED: the nine-test browser selection failed as expected for missing parser/outcome/advance/error/resume/browser-start semantics; the ordinary-zero-result workflow test failed under the legacy anomaly behavior.
- Ownership snapshot: `/private/tmp/egp-exact-canary-s2a-snapshot.json`.
- Production owner: logical `luna_implementer`, model `gpt-5.6-luna`, reasoning effort `max`.
- Receipt: `/private/tmp/egp-exact-canary-s2a-receipt.json`.
- Ownership validator: passed; exact three-file allowlist (`browser_discovery.py`, `workflows/discover.py`, shared enum); no production-file drift; hashes matched.
- Delegate GREEN: eight new browser tests and the zero-result workflow test passed; broader worker scope passed 189 tests; Ruff and compileall passed.
- Harness correction: the primary-owned browser-resume test patched `wait_for_cloudflare` but not the production `wait_for_cloudflare_or_operator` wrapper, causing an unbounded fake-page wait. The stuck pytest was terminated, the ownership receipt was validated first, then the primary added the missing monkeypatch.
- Primary-owned GREEN after harness correction: `test_worker_browser_discovery.py` plus `test_worker_live_discovery.py` -> 189 passed in 55.35s.
- Primary fast gates: Ruff passed; compileall passed.
- Contract evidence: `DiscoveryPaginationOutcome` distinguishes advanced, initial no-results, absent/disabled/hidden next control, max cap, click failure, page-change timeout, unexpected no-results, and site error. `max_pages_reached` is emitted only at the configured cap; the five-page fixture terminates through the page-5 control state while retaining cap 15.
- Wiring: `parse_results_page()` supplies DOM-free sanitized rows to `_collect_keyword_projects()`; `advance_results_page()` supplies one typed outcome; pagination failures raise `PaginationScanError` with migration-backed failure codes; workflow converts them to failed runs; browser start and ordered terminal events are emitted for later proof validation.
- Remaining: observation canary, end-to-end ingestion proof, verifier receipt/bundle v2, full gates/review/delivery.

## S2B implementation - read-only observation canary

- Goal: add a real-Chrome, no-persistence observation path that proves the exact search/parser/pagination behavior separately from ingestion.
- Primary-owned RED: `test_diagnose_search_rows.py` plus `test_remote_crawl_assets.py` -> 5 failed, 25 passed for the missing observation CLI/receipt/shell branch.
- Ownership snapshot: `/private/tmp/egp-exact-canary-s2b-snapshot.json`.
- Production owner: logical `luna_implementer`, model `gpt-5.6-luna`, reasoning effort `max`.
- Receipt: `/private/tmp/egp-exact-canary-s2b-receipt.json`; ownership validator passed the two-file allowlist.
- Production files: `scripts/diagnose_search_rows.py`, `scripts/run_remote_crawl.sh`.
- Contract: observation rejects attach, requires exact cap 15 and release SHA, launches/connects real Chrome, reuses `parse_results_page()` and `advance_results_page()`, accepts contiguous pages 1-5 plus an invitation on page 2 or later and a successful terminal, and writes a sanitized schema-v1 receipt. The guarded shell path strips database, Supabase, S3, and R2 credentials before execution.
- Primary review found a post-success shutdown false exit: the receipt became rejected but a pre-finally return remained 0. Added an executable RED regression.
- Remediation snapshot/receipt: `/private/tmp/egp-exact-canary-s2b-r1-snapshot.json`, `/private/tmp/egp-exact-canary-s2b-r1-receipt.json`; one-file allowlist validated with Luna-Max ownership.
- Primary-owned GREEN: 31 focused tests passed. Ruff on Python files, `bash -n`, and compileall passed.
- Environment note: a broader delegate operations sweep encountered the known isolated-worktree `.venv/bin/python` absence in an unrelated backup-script test; focused scope uses the repository venv with explicit worktree `PYTHONPATH` and is green.
- Remaining: end-to-end ingestion proof, verifier receipt/bundle v2, full gates/review/delivery.

## S3 implementation - exact ingestion proof

- Goal: carry the exact target into the worker, build a bounded browser/page/persistence proof, validate it in the parent before terminal success evidence, and fail exact runs closed on any mismatch.
- Primary-owned RED: proof accumulator missing at collection; worker/API focused scope -> 8 failed, 24 passed for missing target forwarding, proof return, proof validator, payload field, and validation event.
- Ownership snapshot/receipt: `/private/tmp/egp-exact-canary-s3-snapshot.json`, `/private/tmp/egp-exact-canary-s3-receipt.json`; exact three-file allowlist validated for Luna-Max.
- Production files: worker workflow, worker entrypoint, API subprocess dispatcher.
- Contract: proof exact keys are version, target digest, browser-start boolean, contiguous page sequence, pinned cap, successful terminal outcome, and later-page persistence boolean. Exact success requires pages 1-5 under cap 15 and one persisted candidate from page 2 or later. Parent validation precedes `canary_proof_validated`, which precedes `dispatch_finished`.
- Delegate GREEN: 38 focused tests; 221 complete browser/live/spawn/entrypoint tests; Ruff and compileall passed.
- Primary review found that a page-1 persisted candidate incorrectly poisoned proof even when a later candidate persisted. Added a regression; RED reproduced.
- Remediation snapshot/receipt: `/private/tmp/egp-exact-canary-s3-r1-snapshot.json`, `/private/tmp/egp-exact-canary-s3-r1-receipt.json`; one-file Luna-Max ownership validated. Page 1 is now neutral, page 2+ satisfies the existential later-page requirement, and malformed/nonpositive pages remain invalid.
- Primary-owned GREEN: 39 focused S3 tests passed.
- Remaining: verifier receipt/bundle v2, runbook update, full gates/review/delivery.

## S4 implementation - verifier and acceptance bundle v2

- Goal: authorize the complete exact target at verification time, correlate the later-page ingestion chain and ordered proof, preserve explicit historical v1 APIs, and require observation plus schema-2 canary evidence in the final bundle.
- Primary-owned RED: expanded `test_track_bc_verify.py` covered strict request-v2 parsing/private-file authorization, one-transaction target/run/candidate/project/document/capture collection, proof/event invariants, redaction, historical v1 acceptance, schema-2 receipt generation, and bundle downgrade/order rejection.
- Ownership snapshot: `/private/tmp/egp-exact-canary-s4-snapshot.json`.
- Production owner: logical `luna_implementer`, model `gpt-5.6-luna`, reasoning effort `max`.
- Receipt: `/private/tmp/egp-exact-canary-s4-receipt.json`.
- Ownership validator: passed; exact one-file allowlist (`scripts/track_bc_verify.py`), no protected-file drift, hash matched.
- Production contract: the canary CLI is v2-only; the request contains exactly schema version, the unchanged exact target, and canonical run ID. Collection uses one tenant-scoped PostgreSQL read-only transaction and requires the exact live legacy TOR profile/job/keyword/cap plus a persisted page-2-or-later candidate joined to project, positive capture attempt, and document. The summary proof and JSONL `canary_proof_validated` event must match the target digest and precede the unique final `dispatch_finished` event.
- Receipt/bundle contract: canary receipt schema 2 exposes only sanitized checks. Bundle schema 2 requires ordered runtime-v1, observation-v1, canary-v2, supervised-v1 receipts followed by rollback-v1; missing observation, schema downgrade, duplicate/reordered stage, stale evidence, or SHA mismatch rejects.
- Primary-owned GREEN: complete verifier file -> 86 passed. Ruff, compileall, receipt validation, `git diff --check`, and independent focused rerun passed.
- Runbook: replaced the impossible non-live ingestion contract with separate read-only observation and authorized exact live ingestion steps; pinned real cap 15 while requiring pages 1-5; documented request v2, proof/correlation requirements, ordered bundle v2, and the source-versus-runtime boundary.
- Remaining: full affected and repository gates, three consecutive affected repeats, independent QCHECK, formal g-check, delivery, exact-main landing, and cleanup.

## S5 remediation - preserve non-live fault-injection retry semantics

- Integrated affected RED exposed that `force_terminal_failures=True` had been applied to `DiscoveryRunTerminalizationIncompleteError`, changing the established non-live fault-injection behavior from retrying to failed.
- Primary locked both executable sides: ordinary/non-live fault-injection terminalization gaps remain pending/retrying regardless of the terminal-attempt flag, while an exact ingestion target terminalization gap fails closed.
- Ownership snapshot/receipt: `/private/tmp/egp-exact-canary-s5-snapshot.json`, `/private/tmp/egp-exact-canary-s5-receipt.json`.
- Production owner: logical `luna_implementer`, model `gpt-5.6-luna`, reasoning effort `max`; exact one-file allowlist (`discovery_dispatch.py`) validated.
- Primary-owned GREEN: the three contract cases passed; complete discovery-dispatch suite passed 32 tests; Ruff and compileall passed.
- The same integrated pass also found a stale historical-migration assertion. The primary updated it to validate that every current failure code occurs across immutable migration 032 plus additive migration 040, without rewriting migration history.

## Final gate evidence before review

- Integrated affected scope after remediation: 458 passed, 1 skipped in 78.59s.
- Stability repeats: the identical 458-test scope passed two more consecutive times (78.27s and 78.15s), each with the same one intentional skip.
- Repository-wide pytest: 2042 passed, 4 skipped, 5 setup failures in 260.92s. The failures are isolated-worktree environment mismatches, not product or changed-scope failures: `pg_backup.sh` expects a worktree-local `.venv/bin/python`, and four supervisor subprocess tests replace `PYTHONPATH` with the worktree root so the shared primary editable environment cannot resolve the new worktree-only `egp_shared_types.exact_canary` module. Re-run these after exact-main landing, where `.venv` and landed source align.
- Repository-wide `ruff check`: passed.
- Migration manifest: passed for 42 files.
- `compileall apps packages scripts`: passed.
- `bash -n scripts/run_remote_crawl.sh`: passed.
- `git diff --check`: passed.
- Repository-wide `ruff format --check` diagnostic is not a clean baseline: it reports 53 files across untouched areas and existing modified areas. No formatter mutation was performed; root required gates use Ruff lint plus compileall.
- `uv lock --check` could not run because `uv` is unavailable in the host PATH; dependency files were not changed.
