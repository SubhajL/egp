# Plan Draft A

0. Write The Plan To The Coding Log

- Coding log path: `coding-logs/2026-06-16-18-49-02 Coding Log (document-capture-modal-path-debug).md`
- Auggie semantic search unavailable; plan is based on direct file inspection + exact-string searches.
- Inspected files:
  - `apps/worker/src/egp_worker/browser_downloads.py`
  - `apps/worker/src/egp_worker/browser_discovery.py`
  - `apps/worker/src/egp_worker/workflows/discover.py`
  - `tests/phase1/test_worker_browser_downloads.py`
  - `scripts/diagnose_search_rows.py`

1. Overview

The next optimal move is to stop broad heuristic changes and instrument the invitation-detail flow as a first-class modal workflow. Live evidence now shows that the source page has documents, the current backfill run still lands on `tag=td` for the invitation row, and the real downloadable artifact sits behind a nested modal table with a final download icon.

2. Files to Change

- `apps/worker/src/egp_worker/browser_downloads.py`: split invitation-row handling into an explicit modal/detail-table traversal path.
- `tests/phase1/test_worker_browser_downloads.py`: add regression coverage for invitation row -> modal -> nested download icon traversal.
- `scripts/diagnose_search_rows.py` or a new read-only diagnostic script: optional one-off DOM dump after opening the invitation row modal.

3. Implementation Steps

- TDD sequence:
  1. Add/stub invitation-modal tests.
  2. Run and confirm they fail because current code stops at the outer row/td.
  3. Implement the smallest change to open the modal and collect the nested icon click target.
  4. Refactor minimally only if helper boundaries become clearer.
  5. Run fast gates: Ruff + targeted pytest, then full browser-download pytest file.

- Functions:
  - `_handle_invitation_detail_row(...)`:
    Open the matched invitation row using the current outer action, then inspect the resulting modal content for nested table rows and terminal download controls.
  - `_collect_nested_modal_documents(...)`:
    Traverse the modal table by row label and prefer the final download column icon/button over parent cells.
  - `_modal_terminal_clickable(...)`:
    Resolve the authoritative nested download control from the modal row.

- Expected behavior and edge cases:
  - If the outer row click only opens a modal, the worker must continue into the modal instead of treating the outer row as the final download surface.
  - If the modal shows a known-missing-file message, return `[]` not timeout.
  - If the modal layout differs by document type, fail closed for that row and continue other document targets.

4. Test Coverage

- `tests/phase1/test_worker_browser_downloads.py`
  - `test_invitation_row_opens_modal_and_uses_nested_download_icon`
    Validates modal traversal to final icon control.
  - `test_invitation_modal_missing_file_returns_empty_without_timeout`
    Validates known-missing-file modal handling.
  - `test_invitation_modal_prefers_last_column_icon_over_parent_td`
    Validates terminal nested control selection.

5. Decision Completeness

- Goal:
  Make invitation-stage detail-page document capture follow the real nested modal path so production backfills stop recording false `no_documents`.
- Non-goals:
  - No frontend changes.
  - No search-results column/filter changes.
  - No broad refactor of every document type in one pass.
- Success criteria:
  - A live targeted run for project `69069247778` ingests at least one document.
  - `document_collection_status` is not `no_documents` for that run.
  - The invitation-modal regression tests pass locally.
- Public interfaces:
  - No API changes.
  - No schema/migration changes.
  - No env var changes.
- Edge cases / failure modes:
  - Outer row opens modal but no nested rows appear: fail closed for that target and log modal structure.
  - Nested row exists but terminal icon absent: fail closed and continue other targets.
  - Nested click opens a new modal/tab/download: existing direct/new-tab/content handlers remain the terminal save path.
- Rollout & monitoring:
  - Local worker change only until committed/pushed.
  - Watch `DOCUMENT_PROGRESS` for invitation rows, especially `direct_handler_metadata`, modal entry, nested row match, and final save.
  - Backout is revert of worker changes only.
- Acceptance checks:
  - `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
  - One live targeted discover run for `69069247778`

6. Dependencies

- Production tunnel on `127.0.0.1:15432`
- Valid `.env.remotecrawl`
- Real Chrome profile not concurrently held by another crawler process

7. Validation

Confirm the targeted run logs a modal traversal stage for the invitation document and finishes with non-zero `document_count`.

8. Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Invitation modal handler in `browser_downloads.py` | `_download_one_document()` | direct function call inside worker document collection | N/A |
| Nested modal row selector helper | `_handle_invitation_detail_row()` | called only for invitation-stage row path | N/A |
| Live run verification | `run_worker_job(command='discover')` | `apps/worker/src/egp_worker/main.py` | `projects`, `document_capture_attempts`, `runs` |

# Plan Draft B

1. Overview

An alternate path is to capture the exact live modal DOM first, then patch with a narrower, evidence-locked selector instead of implementing the modal traversal immediately. This is slower but reduces the chance of overfitting the wrong invitation-page variant.

2. Files to Change

- `scripts/diagnose_search_rows.py` or a new diagnostic script: open the project, click invitation row, dump modal HTML/metadata.
- `apps/worker/src/egp_worker/browser_downloads.py`: patch only after the modal DOM is recorded.
- `tests/phase1/test_worker_browser_downloads.py`: add fixtures from that modal HTML.

3. Implementation Steps

- TDD sequence:
  1. Build the read-only diagnostic script.
  2. Capture modal DOM for `69069247778`.
  3. Add fixture-backed failing test from the captured structure.
  4. Patch the worker to satisfy the fixture.
  5. Run local gates and one live targeted retry.

- Functions:
  - `_dump_open_modal_structure(...)`:
    Read-only utility that records nested rows, onclick handlers, and terminal icon metadata.
  - Reuse existing save handlers once the terminal target is known.

4. Test Coverage

- `test_invitation_modal_fixture_uses_real_nested_icon_target`
  Validates captured DOM shape.
- `test_invitation_modal_fixture_handles_nested_download_column`
  Validates final-column target resolution.

5. Decision Completeness

- Goal:
  Reduce ambiguity before patching the invitation modal path.
- Non-goals:
  Same as Draft A.
- Success criteria:
  - Captured modal DOM explains why the live run still resolves to `td`.
  - Worker patch based on that capture succeeds live.
- Public interfaces:
  None.
- Edge cases / failure modes:
  - Diagnostic capture may fail to reproduce the exact modal state outside the full crawl path.
  - Slower path delays the production fix.
- Rollout & monitoring:
  Same as Draft A.
- Acceptance checks:
  Same local gates, plus saved modal dump artifact.

6. Dependencies

- Same as Draft A.

7. Validation

Compare the captured modal dump against the live screenshots before patching.

8. Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Diagnostic modal dumper | standalone script | manual operator invocation only | N/A |
| Later worker patch | `_download_one_document()` | `run_worker_job -> run_discover_workflow` | `projects`, `document_capture_attempts`, `runs` |

# Comparative Analysis & Synthesis

- Draft A strengths:
  - Fastest path to fixing the real production failure.
  - Aligned with current evidence: source exists, outer click is not terminal.
- Draft A gaps:
  - Risks one more wrong guess if the invitation modal differs from the screenshot in subtle ways.
- Draft B strengths:
  - Highest confidence in selector correctness before changing behavior.
  - Better if there are multiple invitation modal variants.
- Draft B gaps:
  - Slower.
  - We already have enough evidence that nested modal traversal is the missing behavior class.

The best synthesis is: implement Draft A, but keep one small diagnostic hook ready if the first modal-specific patch still misses.

# Unified Execution Plan

1. Overview

The next optimal option is a modal-specific worker fix for invitation-stage document rows. The live run proved the problem is not empty source data and not search-column drift; it is that the worker stops at the outer invitation row while the real file sits behind a nested modal download control.

2. Files to Change

- `apps/worker/src/egp_worker/browser_downloads.py`: add invitation-modal traversal and nested-terminal-control selection.
- `tests/phase1/test_worker_browser_downloads.py`: add modal-flow regressions with nested download icon coverage.
- Optional: a tiny diagnostic helper script only if the first modal patch still misses live.

3. Implementation Steps

- TDD sequence:
  1. Add invitation-modal failing tests.
  2. Confirm failure against current outer-row behavior.
  3. Implement invitation-modal traversal in `browser_downloads.py`.
  4. Run Ruff and the browser-download test file.
  5. Run one live targeted backfill/discover for `69069247778`.

- Function names and responsibilities:
  - `_download_one_document(...)`:
    Route invitation-stage matched rows into a dedicated modal-aware branch instead of generic direct-click handling.
  - `_handle_invitation_detail_row(...)`:
    Click outer invitation row action, wait for modal, then resolve nested rows and terminal controls.
  - `_collect_nested_modal_documents(...)`:
    Apply existing save machinery after resolving the nested icon/button.

- Expected behavior:
  - Invitation rows that open a modal must continue to the nested download icon.
  - Terminal nested click can still end as direct download, inline viewer, modal, or new tab; existing terminal save logic remains reused.
  - If no nested terminal control exists, return no document for that row and keep the log explicit.

4. Test Coverage

- `test_invitation_row_opens_modal_and_uses_nested_download_icon`
  Uses nested modal icon as authoritative action.
- `test_invitation_modal_missing_file_returns_empty_without_timeout`
  Handles missing source without long timeout.
- `test_invitation_modal_prefers_last_column_icon_over_parent_td`
  Prevents fallback to generic td click.

5. Decision Completeness

- Goal:
  Fix false `no_documents` on invitation-stage project detail pages with nested modal downloads.
- Non-goals:
  - No API/web changes.
  - No broad multi-page crawler rewrite.
  - No schema/backfill policy changes.
- Success criteria:
  - Project `69069247778` yields at least one ingested document in a live targeted run.
  - Latest attempt reason for that project is not `no_documents`.
  - Local regression suite passes.
- Public interfaces:
  None.
- Edge cases / failure modes:
  - Modal never opens: fail closed for that row, log it, continue others.
  - Nested icon absent: fail closed for that row.
  - Known missing source modal: treat as empty, not timeout.
- Rollout & monitoring:
  - Local worker-only change until landed.
  - Watch `DOCUMENT_PROGRESS` for new modal traversal stages and final save outcome.
  - Backout is revert of worker file only.
- Acceptance checks:
  - `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
  - One live discover run for `69069247778`
  - Query latest `document_capture_attempts` for that project afterward

6. Dependencies

- Existing remote tunnel
- Valid `.env.remotecrawl`
- Exclusive access to the persistent Chrome profile

7. Validation

Local green tests plus one live targeted run are enough to decide whether to proceed to broader backlog replay.

8. Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Invitation modal traversal helper | `_download_one_document()` | `apps/worker/src/egp_worker/browser_downloads.py` direct call path | N/A |
| Live discover workflow | `run_worker_job(command='discover')` | `apps/worker/src/egp_worker/main.py` -> `run_discover_workflow()` | `projects`, `runs`, `document_capture_attempts` |
| Live document collection result | `crawl_live_discovery(include_documents=True)` | `apps/worker/src/egp_worker/workflows/discover.py` | persisted attempt/result rows |
