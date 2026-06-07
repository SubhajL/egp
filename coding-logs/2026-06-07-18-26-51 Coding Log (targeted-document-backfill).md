# Targeted Document Backfill

## Planning (2026-06-07 18:26:51 +07)

Auggie semantic search was unavailable with HTTP 402, so this plan is based on direct file inspection and exact-string searches. Inspected files include `AGENTS.md`, `CLAUDE.md`, `packages/db/AGENTS.md`, `apps/api/AGENTS.md`, `apps/worker/AGENTS.md`, `apps/api/src/egp_api/executors/scheduled_discovery_enqueue.py`, `packages/db/src/egp_db/repositories/discovery_job_repo.py`, `packages/db/src/egp_db/repositories/project_schema.py`, `packages/db/src/egp_db/repositories/document_schema.py`, `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`, `apps/api/src/egp_api/services/discovery_dispatch.py`, `apps/worker/src/egp_worker/workflows/discover.py`, `apps/worker/src/egp_worker/browser_discovery.py`, `packages/crawler-core/src/egp_crawler_core/discovery_authorization.py`, and the existing scheduler/systemd tests and units.

### Plan Draft A

Overview: Add a durable `document_capture_attempts` table and repository, then build an API executor that scans eligible open projects with no invitation/TOR evidence and enqueues `discovery_jobs` with `trigger_type='backfill'` and `keyword=project_number`. The worker will record capture outcomes during backfill runs so retries use the attempts table rather than `project_status_events.raw_snapshot`.

Files to change:
- `packages/db/src/migrations/027_document_capture_attempts.sql`: new table, checks, indexes.
- `packages/shared-types/src/egp_shared_types/enums.py`: shared capture-attempt status values.
- `packages/db/src/egp_db/repositories/document_capture_attempt_repo.py`: candidates, enqueue/outcome recording, latest status lookup.
- `packages/db/src/egp_db/repositories/__init__.py`: export repository if the package already centralizes exports.
- `apps/api/src/egp_api/executors/document_backfill_enqueue.py`: scan and enqueue due targeted backfills.
- `apps/worker/src/egp_worker/workflows/discover.py`: allow backfill project-number authorization and record final attempt status.
- `deploy/systemd/egp-document-backfill-enqueue.service` and `.timer`: Lightsail timer wiring.
- Tests under `tests/phase1/` and `apps/api/tests/`: repository selection/backoff, enqueuer behavior, workflow outcome recording.

Implementation steps:
1. Add repository tests first for selecting due candidates: eligible states, zero invitation/TOR docs, deadline not passed, max attempts, backoff, active profile.
2. Add enqueuer tests first: creates idempotent `backfill` discovery jobs keyed by `project_number`, records enqueue attempts, skips no-profile/no-number candidates.
3. Add workflow tests first: `trigger_type='backfill'` bypasses keyword-membership authorization only for existing project numbers and records `succeeded` or `no_documents`.
4. Implement migration/schema/repository.
5. Implement enqueuer and worker hook.
6. Add systemd unit/timer.
7. Run scoped ruff, compileall, and pytest gates.

Functions:
- `list_due_document_capture_backfill_candidates(...)`: returns bounded candidates for open projects with no invitation/TOR documents and retry eligibility.
- `record_document_capture_attempt(...)`: appends an immutable attempt row with status, reason, run, doc count.
- `enqueue_document_capture_backfill_jobs(...)`: creates discovery jobs and records an `enqueued` attempt per created/enqueued target.
- `_backfill_keyword_matches_existing_project(...)`: verifies a backfill keyword is the tenant's existing project number before bypassing keyword entitlement.
- `_record_backfill_document_capture_outcome(...)`: writes run-linked outcome rows from the worker.

Test coverage:
- `test_lists_due_zero_doc_open_project` - includes eligible open project.
- `test_skips_project_with_invitation_or_tor_doc` - respects authoritative documents rows.
- `test_applies_backoff_and_attempt_cap` - prevents infinite recrawl.
- `test_skips_past_proposal_deadline` - stops after submission date.
- `test_enqueues_backfill_job_by_project_number` - uses precise project-number keyword.
- `test_backfill_authorization_allows_existing_project_number` - avoids active-keyword false rejection.
- `test_backfill_records_no_documents_outcome` - records zero-doc recrawl result.
- `test_backfill_records_success_doc_count` - records successful capture count.

Decision completeness:
- Goal: targeted Track C document backfill for zero invitation/TOR open projects.
- Non-goals: parser hardening, UI/API empty-state surfacing, backlog one-time sweep beyond recurring selection.
- Success criteria: migration exists, enqueuer queues due project-number backfills, worker records outcomes, retries are capped/backed off, scoped tests pass.
- Public interfaces: new table `document_capture_attempts`; new executor module `egp_api.executors.document_backfill_enqueue`; new systemd unit/timer; `discovery_jobs.trigger_type='backfill'` existing value.
- Edge cases/failure modes: missing project number skips; no active profile skips; no docs records `no_documents`; collection exception records `failed`; repeated timer uses pending-job idempotency plus attempt backoff; deadline passed stops. Fail closed for authorization except verified existing project-number backfills.
- Rollout/monitoring: apply migration first, install timer disabled until migration succeeds, watch attempt status counts and `discovery_jobs` failures.
- Acceptance checks: targeted pytest suites, `ruff check`, `compileall`, systemd unit file inspection.

Dependencies: existing Track C Mac runner must claim `discovery_jobs`; PostgreSQL migration must be applied; active tenant profile required to carry profile settings.

Validation: run repository/enqueuer/workflow tests, then verify SQL selection manually against local PostgreSQL if available.

Wiring verification:

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `document_capture_attempts` migration | migration runner | `packages/db/src/migrations` sorted filename | `document_capture_attempts` |
| capture attempt repository | enqueuer and worker workflow | direct imports | `projects`, `documents`, `document_capture_attempts`, `crawl_profiles` |
| document backfill enqueuer | `python -m egp_api.executors.document_backfill_enqueue` | systemd service | `discovery_jobs`, `document_capture_attempts` |
| worker outcome recorder | `run_discover_workflow(trigger_type='backfill')` | existing discovery dispatcher/worker payload | `document_capture_attempts` |
| systemd timer | `egp-document-backfill-enqueue.timer` | `timers.target` | N/A |

Cross-language schema verification: Python currently uses `projects`, `project_status_events`, `documents`, `discovery_jobs`, `crawl_runs`, `crawl_profiles`, and `crawl_profile_keywords`; no TypeScript table names are involved in this P0 slice.

### Plan Draft B

Overview: Keep the attempt table and selection repository, but do not alter worker authorization/outcome recording. The enqueuer would only record `enqueued` attempts and rely on the existing document row count after each future selection pass to infer success.

Files to change:
- Same migration/repository/enqueuer/systemd files as Draft A, excluding worker authorization/outcome hooks.

Implementation steps:
1. Add repository selection and enqueuer tests.
2. Implement attempts table and enqueuer only.
3. Use document presence on the next timer pass to stop retries.

Test coverage:
- `test_enqueued_attempt_blocks_immediate_duplicate` - queue attempt creates backoff.
- `test_document_rows_stop_future_selection` - success inferred from docs.

Decision completeness:
- Goal: cheap targeted enqueue path.
- Non-goals: accurate per-run outcomes.
- Success criteria: eligible projects are queued once per backoff window.
- Public interfaces: table, enqueuer, systemd timer.
- Edge cases/failure modes: worker authorization may reject project-number keywords; no run-linked status; failures remain indistinguishable from not-yet-claimed jobs. This is fail closed but too opaque.
- Rollout/monitoring: watch queued attempts and discovery job failures.
- Acceptance checks: repository/enqueuer tests.

Dependencies: same as Draft A.

Validation: same, but weaker because worker outcome is not asserted.

Wiring verification:

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `document_capture_attempts` migration | migration runner | migrations directory | `document_capture_attempts` |
| document backfill enqueuer | systemd oneshot | timer | `discovery_jobs`, `document_capture_attempts` |

Cross-language schema verification: same as Draft A.

### Comparative Analysis

Draft A is stronger because it records the actual browser outcome by run and fixes the project-number authorization catch before Track C dispatch. It adds a narrow worker hook, but that hook is necessary for the attempts table to be a source of truth rather than only an enqueue ledger.

Draft B is smaller, but it would likely fail in production because project-number backfill keywords are not active profile keywords. It also cannot distinguish no-doc, failure, and pending states without inference, which recreates the raw-snapshot ambiguity this work is meant to remove.

Both plans follow the repo constraints: PostgreSQL remains source of truth, tenant scoping is explicit, no Excel flags are reintroduced, and worker code remains an event/artifact collector rather than a product-state owner.

### Unified Execution Plan

Overview: Implement Draft A with a scoped schema/repository/enqueuer/worker hook. The enqueuer will scan tenant-scoped candidates, create idempotent `backfill` discovery jobs keyed by `project_number`, and append attempt rows for retry/backoff; the worker will append final outcome rows for backfill runs using actual document ingestion results.

Files to change:
- `packages/db/src/migrations/027_document_capture_attempts.sql`: table with `tenant_id`, `project_id`, nullable `run_id`, `status`, `reason`, `doc_count`, `attempted_at`, `created_at`, checks and indexes.
- `packages/shared-types/src/egp_shared_types/enums.py`: `DocumentCaptureAttemptStatus`.
- `packages/db/src/egp_db/repositories/document_capture_attempt_repo.py`: SQLAlchemy table, dataclasses, selection and record APIs.
- `apps/api/src/egp_api/executors/document_backfill_enqueue.py`: CLI/executor mirroring scheduled enqueue.
- `apps/worker/src/egp_worker/workflows/discover.py`: backfill authorization and outcome recording.
- `deploy/systemd/egp-document-backfill-enqueue.service` and `.timer`: Lightsail wiring.
- `tests/phase1/test_document_capture_attempts.py`, `apps/api/tests/test_document_backfill_enqueue.py`, and focused worker workflow tests.

TDD sequence:
1. Add repository and enqueuer tests and confirm RED on missing modules/functions.
2. Add worker workflow tests and confirm RED on authorization/outcome gaps.
3. Implement migration/schema/repository.
4. Implement enqueuer.
5. Implement worker authorization/outcome hook.
6. Add systemd unit/timer.
7. Refactor minimally, then run ruff, compileall, and scoped pytest.

Functions:
- `create_document_capture_attempt_repository(...)`: factory matching other DB repos.
- `list_due_backfill_candidates(...)`: bounded all-tenant selection with project-state, doc-count, deadline, backoff, cap, active-profile checks.
- `record_attempt(...)`: immutable insert for `enqueued`, `succeeded`, `no_documents`, `failed`, `timeout`, `skipped`.
- `count_invitation_or_tor_documents(...)`: authoritative document evidence helper.
- `get_latest_attempt_for_project(...)`: supports API/UI follow-up and tests.
- `enqueue_document_backfill_jobs(...)`: CLI-callable orchestration and summary.
- `_is_backfill_authorized_project_number(...)`: narrow bypass for existing tenant project number.
- `_record_document_capture_attempt_for_backfill(...)`: writes run outcome rows from worker.

Test coverage:
- `test_lists_due_backfill_candidate_for_zero_invitation_tor_docs` - eligible project selected.
- `test_candidate_selection_ignores_other_doc_types` - non-target docs do not block.
- `test_candidate_selection_skips_invitation_or_tor_docs` - target docs stop retry.
- `test_candidate_selection_honors_backoff_and_cap` - bounded retry state.
- `test_candidate_selection_skips_past_proposal_deadline` - deadline stop.
- `test_enqueue_creates_project_number_backfill_job` - precise discovery keyword.
- `test_enqueue_is_idempotent_for_pending_job` - no duplicate pending jobs.
- `test_main_runs_backfill_enqueue_once` - CLI executes one pass.
- `test_backfill_allows_existing_project_number_authorization` - project-number job runs.
- `test_backfill_records_success_doc_count` - success attempt persisted.
- `test_backfill_records_no_documents` - zero-doc attempt persisted.
- `test_backfill_records_failure_on_ingest_error` - failed attempt persisted.

Decision completeness:
- Goal: durable targeted document backfill on Track C for open zero invitation/TOR projects.
- Non-goals: parser changes, UI/API status surfacing, one-time historical sweep command, changing discovery job claim semantics.
- Success criteria: due projects are selected and enqueued by project number; attempts table records enqueue and final outcomes; repeat retries are capped/backed off and stop on docs/deadline; tests and lint pass; PR is created and merged if CI/permissions allow.
- Public interfaces: new migration/table; new enum; new executor module/CLI flags `--database-url`, `--limit`, `--max-attempts`, `--base-backoff-seconds`, `--max-backoff-seconds`; new systemd service/timer.
- Edge cases/failure modes: no project number skipped; no active profile skipped; pending duplicate not reinserted; project number not existing fails authorization; no documents records `no_documents`; ingestion exception records `failed`; timeout status is reserved if the collection status is `timeout`; unknown status fails closed via DB check.
- Rollout & monitoring: apply migration, deploy executor, enable timer; watch `document_capture_attempts` status mix and `discovery_jobs` failed backfill jobs; disable timer to back out without data loss.
- Acceptance checks: `./.venv/bin/python -m pytest tests/phase1/test_document_capture_attempts.py apps/api/tests/test_document_backfill_enqueue.py tests/phase1/test_worker_live_discovery.py -q`, targeted ruff, compileall.

Dependencies: existing DB URL, active profiles for tenant settings, Track C Mac runner claiming `discovery_jobs`, e-GP accepting project-number search.

Validation: inspect generated SQL/migration number, run tests, verify `python -m egp_api.executors.document_backfill_enqueue --help`, and check systemd unit references the new module.

Wiring verification:

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `027_document_capture_attempts.sql` | migration runner | `packages/db/src/migrations` | `document_capture_attempts` |
| `DocumentCaptureAttemptStatus` | DB repo/worker/enqueuer | `egp_shared_types.enums` import | status CHECK in migration/repo |
| `document_capture_attempt_repo.py` | enqueuer + worker workflow | direct imports/factory | `document_capture_attempts`, `projects`, `documents`, `crawl_profiles` |
| `document_backfill_enqueue.py` | `python -m egp_api.executors.document_backfill_enqueue` | systemd service | `discovery_jobs`, `document_capture_attempts` |
| worker backfill recorder | existing `SubprocessDiscoveryDispatcher` -> `egp_worker.main` -> `run_discover_workflow` | existing payload trigger `backfill` | `document_capture_attempts` |
| systemd timer | `egp-document-backfill-enqueue.timer` | `timers.target` | N/A |

Cross-language schema verification:
- Python uses `documents` through `DOCUMENTS_TABLE` with tenant-scoped `document_type` values `invitation`, `tor`, `other`, `mid_price`.
- Python uses `projects.project_state`, `project_number`, and `proposal_submission_date`.
- Python uses `crawl_profiles` for active profile settings and `discovery_jobs` for Track C dispatch.
- TypeScript generated API types mention runs/documents but do not reference these SQL table names in this P0 slice.

Decision-complete checklist:
- No open decisions remain for implementation.
- New public interfaces are named above.
- Each behavior change has at least one failing test target.
- Validation commands are scoped to touched Python/API/worker/db files.
- Wiring table covers migration, repo, executor, worker hook, and timer.
- Rollout/backout is specified: migration forward, timer disable for backout.

## Implementation Summary (2026-06-07 18:42:00 +07)

Goal: implement P0 targeted document backfill for Track C with durable capture attempts, bounded retry selection, project-number discovery jobs, and worker-recorded outcomes.

What changed:
- `packages/db/src/migrations/027_document_capture_attempts.sql`: added tenant-scoped `document_capture_attempts` table with status/doc-count checks and lookup indexes.
- `packages/shared-types/src/egp_shared_types/enums.py`: added `DocumentCaptureAttemptStatus`.
- `packages/db/src/egp_db/repositories/document_capture_attempt_repo.py`: added attempt records, backfill candidates, selection/backoff/cap logic, latest-attempt lookup, and project-number lookup.
- `apps/api/src/egp_api/executors/document_backfill_enqueue.py`: added no-browser enqueuer CLI that creates idempotent `backfill` discovery jobs keyed by `project_number` and records `enqueued` attempts when new jobs are created.
- `apps/worker/src/egp_worker/workflows/discover.py`: added narrow backfill authorization for existing project numbers and run-linked outcome recording (`succeeded`, `no_documents`, `failed`, `timeout`).
- `deploy/systemd/egp-document-backfill-enqueue.service` and `.timer`: added Lightsail timer wiring.
- Tests added/updated for repository candidate selection, enqueuer behavior, and worker backfill outcome recording.

TDD evidence:
- RED: `./.venv/bin/python -m pytest tests/phase1/test_document_capture_attempts.py apps/api/tests/test_document_backfill_enqueue.py tests/phase1/test_worker_live_discovery.py::test_run_worker_job_backfill_allows_existing_project_number_and_records_no_documents tests/phase1/test_worker_live_discovery.py::test_run_worker_job_backfill_records_success_doc_count -q` failed with `ModuleNotFoundError: No module named 'egp_db.repositories.document_capture_attempt_repo'`.
- GREEN: the same command passed with `10 passed in 0.63s`.

Tests run:
- `./.venv/bin/ruff check packages/db/src/egp_db/repositories/document_capture_attempt_repo.py apps/api/src/egp_api/executors/document_backfill_enqueue.py apps/worker/src/egp_worker/workflows/discover.py tests/phase1/test_document_capture_attempts.py apps/api/tests/test_document_backfill_enqueue.py tests/phase1/test_worker_live_discovery.py packages/shared-types/src/egp_shared_types/enums.py` -> passed.
- `./.venv/bin/ruff format --check ...` initially reported four files to reformat; `./.venv/bin/ruff format ...` applied formatting.
- `./.venv/bin/python -m compileall packages/db/src packages/shared-types/src apps/api/src apps/worker/src` -> passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q` -> `51 passed`.
- `./.venv/bin/python -m pytest apps/api/tests/test_document_backfill_enqueue.py apps/api/tests/test_scheduled_discovery_enqueue.py apps/api/tests/test_run_trigger_mapping.py tests/phase2/test_discovery_dispatch.py -q` -> `28 passed`.
- `./.venv/bin/python -m pytest tests/phase1/test_document_capture_attempts.py tests/phase1/test_project_and_run_persistence.py -q` -> `22 passed`.
- `./.venv/bin/python -m egp_api.executors.document_backfill_enqueue --help` -> CLI imports and renders expected flags.

Wiring verification:
- Migration is in `packages/db/src/migrations/027_document_capture_attempts.sql` and matches SQLAlchemy table names.
- Enqueuer entry point is `python -m egp_api.executors.document_backfill_enqueue`; systemd service invokes that module.
- Track C runner already claims `discovery_jobs`; new jobs use existing fields with `trigger_type='backfill'`, `keyword=<project_number>`, `live=True`.
- Worker outcome recording is wired through existing `run_worker_job(command='discover')` -> `run_discover_workflow(trigger_type='backfill')`.

Behavior/risk notes:
- Backfill keyword authorization fails closed unless the keyword is an existing tenant project number and the tenant is otherwise entitled.
- Candidate selection skips projects past `proposal_submission_date`, projects without active profiles, projects without project numbers, projects at/over attempt cap, and projects inside exponential backoff.
- The timer can be disabled to stop new retries without deleting attempt history.

Follow-ups:
- Surface latest attempt status in documents API/UI.
- Parser hardening remains P1 and is intentionally not included here.

## Review (2026-06-07 18:52:00 +07) - staged working tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feat/targeted-document-backfill`
- Scope: staged working tree
- Commands Run: `mcp__auggie_mcp.codebase_retrieval` (failed HTTP 402), `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-status`, targeted staged diffs for `document_capture_attempt_repo.py`, `document_backfill_enqueue.py`, and `discover.py`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --check`, plus the lint/compile/test commands listed in the implementation summary.

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Assumption: Track C deployments apply migration `027_document_capture_attempts.sql` before enabling `egp-document-backfill-enqueue.timer`.
- Assumption: e-GP search continues accepting exact `project_number` queries as described in the verified plan.
- Residual gap: project-number backfill is implemented; fingerprint-only fallback remains outside this P0 slice.

### Recommended Tests / Validation
- Keep the focused repository/enqueuer/worker tests in the PR.
- Run the migration runner against a Postgres environment during deployment.
- After deployment, check `document_capture_attempts` status counts and `discovery_jobs` rows with `trigger_type='backfill'`.

### Rollout Notes
- Roll out migration first.
- Deploy the executor and systemd unit/timer next.
- Disable `egp-document-backfill-enqueue.timer` to stop new retries without deleting audit/backoff history.
