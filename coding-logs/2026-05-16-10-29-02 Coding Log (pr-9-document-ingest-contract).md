# Coding Log: PR 9 Document Ingest Contract

Started: 2026-05-16 10:29:02 +07

Goal: lock the desired document-ingest contract with parity and retry/idempotency tests, document
canonical ownership, and keep API/worker behavior coherent before PR 10 routes writes through the
canonical path.

## Review (2026-05-16 10:29:29 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted file reads with `nl -ba`; `./.venv/bin/ruff check apps/api apps/worker packages tests/phase3/test_document_ingest_contract.py`; `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py tests/phase1/test_documents_api.py tests/phase1/test_document_infrastructure.py tests/phase1/test_phase1_wiring.py::test_worker_document_ingest_wires_repository_backed_persistence -q`

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
- Assumption: PR 9 should lock parity and retry behavior while leaving the larger worker-to-canonical-service/event routing for PR 10.
- Assumption: falling back to caller-supplied worker context when project context lookup is unavailable is acceptable because it preserves existing behavior for worker-only/local metadata databases.

### Recommended Tests / Validation
- Keep the new contract tests in `tests/phase3/test_document_ingest_contract.py` as the PR 10 migration guard.
- Re-run the focused API/worker document suites before submit and after any CI failure.

### Rollout Notes
- No schema or environment changes.
- Worker direct ingestion now hydrates missing project status/state from the database when available, matching the API ingest context behavior.

## Implementation Summary (2026-05-16 10:29:54 +07)

### Goal
Lock PR 9's document-ingest contract before the PR 10 canonical-path migration.

### What Changed
- `tests/phase3/test_document_ingest_contract.py`: added parity coverage comparing API and worker document-ingest output when project context must be hydrated from stored project state/status; added a cross-path retry/idempotency test proving a worker retry of an API-ingested artifact does not create duplicate documents, diffs, or reviews.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`: resolved missing worker `source_status_text` and `project_state` from the project repository before calling `SqlDocumentRepository.store_document`, matching the API service context behavior while preserving caller-supplied context when present.
- `docs/DOCUMENT_INGEST_CONTRACT.md`: documented canonical ownership and the locked behavior that PR 10 must preserve.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py -q`
  - Result: failed both new tests. Worker ingestion classified the same public-hearing project artifact as `final` with blank `source_status_text`, and a worker retry after API ingest created a second document instead of returning `created=False`.
- GREEN: `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py -q`
  - Result: `2 passed in 0.53s`.

### Tests Run
- `./.venv/bin/ruff check apps/worker/src/egp_worker/workflows/document_ingest.py tests/phase3/test_document_ingest_contract.py` - passed.
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py tests/phase1/test_document_infrastructure.py::test_worker_document_ingest_uses_database_url_override tests/phase1/test_phase1_wiring.py::test_worker_document_ingest_wires_repository_backed_persistence -q` - `4 passed`.
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase1/test_document_infrastructure.py -q` - `43 passed`.
- `./.venv/bin/python -m compileall apps/worker/src apps/api/src packages` - passed.
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase3/test_document_ingest_contract.py` - passed.
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py tests/phase1/test_documents_api.py tests/phase1/test_document_infrastructure.py tests/phase1/test_phase1_wiring.py::test_worker_document_ingest_wires_repository_backed_persistence -q` - `46 passed`.

### Wiring Verification
- Worker entrypoints continue to call `ingest_document_artifact` through `apps/worker/src/egp_worker/main.py` and `apps/worker/src/egp_worker/browser_downloads.py`.
- The added context hydration happens inside `ingest_document_artifact`, so both direct worker command ingestion and browser-downloaded document ingestion use the same contract.
- API ingestion remains wired through `apps/api/src/egp_api/routes/documents.py` and `DocumentIngestService`.

### Behavior Changes And Risk Notes
- Worker document ingestion now uses stored project status/state when payload context is missing. This is fail-soft: if project lookup is unavailable, existing caller-supplied context behavior is preserved.
- No database schema, migration, or environment changes.

### Follow-ups / Known Gaps
- PR 10 should route worker document writes through the canonical service or event boundary instead of keeping direct worker repository writes.

## Submit / Landing Status (2026-05-16 10:32:52 +07)

- Created Graphite branch `05-16-test_documents_lock_ingest_contract` with commit `9f0570d8`.
- Submitted PR #81: https://github.com/SubhajL/egp/pull/81
- Enabled GitHub auto-merge with merge method `MERGE`.
- Attempted immediate merge with `gh pr merge 81 --merge --delete-branch=false`; GitHub blocked the merge because base branch policy requirements were not met.
- CI and Claude review did not execute any jobs. GitHub run annotations reported: `The job was not started because your account is locked due to a billing issue.`
- Added PR comment with local validation evidence and the GitHub Actions billing blocker.

Remote/main and local main were not updated because required GitHub checks could not run and branch protection blocked the merge.

## Implementation Summary (2026-05-16 11:23:35 +07)

### Goal
Implement PR 11 by removing ambiguity around the final document-ingest pipeline and adding replay/duplicate observability to the canonical path.

### What Changed
- `tests/phase3/test_document_ingest_contract.py`: extended the cross-path retry test to assert structured canonical success events, worker actor attribution, zero diff rows on replay, and a repository duplicate replay event.
- `apps/api/src/egp_api/services/document_ingest_service.py`: added canonical start/success structured logs around `DocumentIngestService.ingest_document_bytes()`.
- `packages/db/src/egp_db/repositories/document_repo.py`: added `document_store_duplicate_replay_detected` logging before returning an existing document from the duplicate idempotency branch.
- `docs/DOCUMENT_INGEST_CONTRACT.md`: documented the final API/worker -> service -> repository pipeline and the expected observability events.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py::test_cross_path_document_retry_is_idempotent -q`
  - Result: failed with `StopIteration` because no `document_store_duplicate_replay_detected` event existed yet.
- GREEN: `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py::test_cross_path_document_retry_is_idempotent -q`
  - Result: `1 passed in 0.52s`.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py::test_cross_path_document_retry_is_idempotent -q` - red, then green.
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py -q` - `3 passed`.
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py::test_ingest_document_endpoint_is_idempotent_for_duplicate_bytes tests/phase1/test_document_persistence.py::test_store_document_logs_resolved_write_plan_for_managed_storage -q` - `2 passed`.
- `./.venv/bin/ruff check apps/api/src/egp_api/services/document_ingest_service.py packages/db/src/egp_db/repositories/document_repo.py tests/phase3/test_document_ingest_contract.py` - passed.
- `./.venv/bin/python -m compileall apps/api/src packages/db/src apps/worker/src` - passed.

### Wiring Verification
- API route callers still resolve `app.state.document_ingest_service`; no route registration changed.
- Worker ingestion still enters `ingest_document_artifact()` and delegates to `DocumentIngestService.ingest_document_bytes(actor_subject="system:worker")`.
- Duplicate replay detection remains inside `SqlDocumentRepository.store_document()` before any artifact write plan is resolved, so retries return the existing document without new blob, diff, or review writes.

### Behavior Changes And Risk Notes
- No schema, migration, environment, or API response changes.
- The canonical path now emits structured start/success logs, including `document_created`, `diff_record_count`, actor, document type, document phase, and SHA-256 on success.
- Duplicate retries now emit `document_store_duplicate_replay_detected`; this is observability-only and preserves fail-closed database behavior.
- Auggie semantic retrieval was unavailable due to HTTP 429, so implementation used direct file inspection and exact identifier searches.

### Follow-ups / Known Gaps
- None for PR 11. Larger module decomposition remains planned for later PRs.

## Review (2026-05-16 11:23:35 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- <changed-files>`; focused pytest commands; targeted ruff; compileall.

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
- Assumption: structured logs are acceptable as PR 11 observability without adding schema-backed metrics or counters.
- Assumption: logging duplicate replay inside the repository is the right level because the idempotency branch is below both API and worker callers.

### Recommended Tests / Validation
- Keep the extended `test_cross_path_document_retry_is_idempotent` contract test; it now guards both replay behavior and observability.
- Let GitHub CI run the full repository gates before merge.

### Rollout Notes
- No rollout flags or migrations.
- New logs may increase ingest log volume for repeated retries, but only one event is emitted per duplicate ingest attempt.

## Additional Validation (2026-05-16 11:24:00 +07)

- `./.venv/bin/ruff check apps/api packages tests/phase3/test_document_ingest_contract.py` - passed.
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py tests/phase1/test_documents_api.py tests/phase1/test_document_persistence.py -q` - `54 passed, 14 warnings`.
- `./.venv/bin/python -m compileall apps packages` - passed. This command also traversed installed frontend dependencies under `apps/web/node_modules`, making the output noisy but not failing.

## Submit / Landing Status (2026-05-16 11:26:52 +07)

- Created Graphite branch `05-16-feat_documents_add_ingest_replay_observability`.
- Submitted PR #83: https://github.com/SubhajL/egp/pull/83
- Added PR comment with local RED/GREEN, focused test, broader test, ruff, and compileall evidence: https://github.com/SubhajL/egp/pull/83#issuecomment-4465565068
- GitHub Actions did not execute job steps. The Python Lint & Format job annotation reported: `The job was not started because your account is locked due to a billing issue.`
- `gh pr checks 83` reported all required CI jobs and `claude-review` as failed after two seconds, with `auto-approve` skipped.
- `gh pr merge 83 --merge --delete-branch=false` was blocked by base branch policy.
- Enabled auto-merge with merge method `MERGE`; it will still require CI to rerun and pass after the account/billing blocker is resolved.

Remote/main and local main were not updated because required GitHub checks could not run and branch protection blocked merge eligibility.

## Review (2026-05-16 10:52:06 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/services/document_ingest_service.py apps/worker/src/egp_worker/workflows/document_ingest.py docs/DOCUMENT_INGEST_CONTRACT.md tests/phase3/test_document_ingest_contract.py`; `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py tests/phase1/test_document_infrastructure.py tests/phase1/test_phase1_wiring.py tests/phase1/test_worker_entrypoint.py tests/phase1/test_documents_api.py -q`; `./.venv/bin/ruff check apps/api apps/worker packages tests/phase3/test_document_ingest_contract.py`; `./.venv/bin/python -m compileall apps/api/src/egp_api/services apps/worker/src/egp_worker/workflows`; exact wiring searches for `DocumentIngestService`, `ingest_document_bytes`, `store_document`, `ingest_document_artifact`, and `ingest_downloaded_documents`.

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
- Assumption: importing the API service from the worker is acceptable for PR 10 because the root package and worker Dockerfile install both app packages, and the roadmap explicitly chose the API/control-plane service as the canonical document-ingest owner.
- Assumption: preserving caller-supplied `project_state` inside `DocumentIngestService` is intentional transition compatibility for worker-collected context.

### Recommended Tests / Validation
- Keep the new service-boundary test in `tests/phase3/test_document_ingest_contract.py`; it fails if worker ingestion returns to direct repository writes.
- Let GitHub CI run the normal Python, database, frontend, and Docker gates before merge.

### Rollout Notes
- No schema or environment changes.
- Worker document ingestion now records document-created audit rows through the same service path as API ingestion when a document is newly created.

## Implementation Summary (2026-05-16 10:52:47 +07)

### Goal
Implement PR 10 by routing worker document writes through the canonical API/control-plane document-ingest service while keeping the PR 9 contract green.

### What Changed
- `tests/phase3/test_document_ingest_contract.py`: added a service-boundary contract test that monkeypatches `DocumentIngestService` and installs an exploding repository, proving worker ingestion delegates to the canonical service instead of calling `store_document()` itself.
- `apps/api/src/egp_api/services/document_ingest_service.py`: extended `DocumentIngestService.ingest_document_bytes()` to accept optional `project_state`, preserving worker-collected context while keeping project status/state hydration inside the canonical service.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`: removed worker-local project-context resolution and direct repository writes; `ingest_document_artifact()` now constructs `DocumentIngestService` with project and audit repositories and calls `ingest_document_bytes(actor_subject="system:worker")`.
- `docs/DOCUMENT_INGEST_CONTRACT.md`: updated the contract to state that PR 10 moved worker writes behind `DocumentIngestService`.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py::test_worker_document_ingest_routes_through_canonical_service_boundary -q`
  - Result: failed with `AssertionError: worker must delegate to DocumentIngestService` from `apps/worker/src/egp_worker/workflows/document_ingest.py:170`, proving the worker still called `repository.store_document()` directly.
- GREEN: `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py -q`
  - Result: `3 passed in 0.66s`.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py::test_worker_document_ingest_routes_through_canonical_service_boundary -q` - `1 passed`.
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py -q` - `3 passed`.
- `./.venv/bin/python -m pytest tests/phase1/test_document_infrastructure.py tests/phase1/test_phase1_wiring.py tests/phase1/test_worker_entrypoint.py -q` - `20 passed`.
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py tests/phase1/test_document_infrastructure.py tests/phase1/test_phase1_wiring.py tests/phase1/test_worker_entrypoint.py tests/phase1/test_documents_api.py -q` - `51 passed` on three consecutive runs.
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase3/test_document_ingest_contract.py` - passed.
- `./.venv/bin/python -m compileall apps/api/src/egp_api/services apps/worker/src/egp_worker/workflows` - passed.

### Wiring Verification
- `rg -n "DocumentIngestService|ingest_document_bytes|store_document\\(" apps/api/src apps/worker/src packages/db/src -g '*.py'` shows production `store_document()` calls only in `DocumentIngestService` and the repository implementation; worker production code calls `DocumentIngestService.ingest_document_bytes()`.
- `rg -n "ingest_document_artifact\\(|ingest_downloaded_documents\\(" apps/worker/src tests/phase3/test_document_ingest_contract.py -g '*.py'` confirms the runtime call path remains `egp_worker.main` / `browser_downloads` -> `ingest_document_artifact()` -> canonical service.

### Behavior Changes And Risk Notes
- Worker-created documents now flow through the canonical service and receive `document.created` audit events with actor `system:worker`.
- API ingest behavior is unchanged for route callers; `project_state` is optional and defaults to the stored project state when omitted.
- No schema, migration, environment, or frontend changes.
- Auggie semantic retrieval was unavailable due to HTTP 429, so context gathering used direct file inspection and exact identifier searches.

### Follow-ups / Known Gaps
- PR 11 should remove or slim remaining transition-only compatibility surfaces and add replay/duplicate observability around the now-canonical path.

## Submit / Landing Status (2026-05-16 10:55:41 +07)

- Created Graphite branch `05-16-feat_document_ingest_canonical_service` with commit `7d30574f`.
- Submitted PR #82: https://github.com/SubhajL/egp/pull/82
- Enabled GitHub auto-merge with merge method `MERGE`.
- Added PR comment with local RED/GREEN, focused test, lint, and compile evidence: https://github.com/SubhajL/egp/pull/82#issuecomment-4465459955
- GitHub Actions did not execute job steps. The Python Lint & Format check annotation reported: `The job was not started because your account is locked due to a billing issue.`
- Attempted immediate merge with `gh pr merge 82 --merge --delete-branch=false`; GitHub blocked the merge because base branch policy requirements were not met.

Remote/main and local main were not updated because required GitHub checks could not run and branch protection blocked the merge.
