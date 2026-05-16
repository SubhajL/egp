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
