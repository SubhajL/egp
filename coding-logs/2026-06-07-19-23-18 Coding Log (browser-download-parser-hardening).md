# Browser Download Parser Hardening

## Plan Draft A - Focused parser helpers

### Overview

Harden `apps/worker/src/egp_worker/browser_downloads.py` so document rows are found after the DOM is actually ready, even when the document table is identified by row download controls rather than header wording. Add fixture-backed regressions for the `69049163846` detail-page layout and keep the behavior local to worker document extraction.

Auggie semantic search unavailable; plan is based on direct file inspection plus exact-string searches. Inspected paths: `AGENTS.md`, `apps/worker/AGENTS.md`, `apps/worker/src/egp_worker/browser_downloads.py`, `tests/phase1/test_worker_browser_downloads.py`, `artifacts/tenants/1bea353a-eb9a-4da8-b7f8-3c46adabcf28/runs/7863f6d2-9383-49fd-a739-d8a0189a0b92/worker.log`.

### Files to Change

- `apps/worker/src/egp_worker/browser_downloads.py`: replace fixed pre-scan sleep with a bounded table wait, add row-level document table detection, relax targeted row cell-count assumptions, and classify labels using filename fallback.
- `tests/phase1/test_worker_browser_downloads.py`: add TDD regressions for delayed table readiness, row-level download controls, two-cell rows, and OTHER label fallback.
- `tests/fixtures/browser_downloads/detail_69049163846.html`: capture the failing detail-page table layout as a stable regression fixture.
- `.codex/coding-log.current`: point to this Coding Log.

### Implementation Steps

TDD sequence:
1. Add fixture and failing parser tests.
2. Run the focused pytest command and confirm failures map to current parser gaps.
3. Implement the smallest helper changes in `browser_downloads.py`.
4. Refactor only to keep row/table detection readable.
5. Run focused pytest, compileall for worker, and ruff on touched Python.

Functions:
- `_wait_for_downloadable_detail_rows(page)`: wait briefly for tables/rows with document download controls instead of sleeping blindly.
- `_table_has_downloadable_document_rows(table)`: accept tables when rows expose download links/buttons, regardless of headers.
- `_iter_downloadable_document_rows(page)`: return rows from header-matched or row-control-matched tables.
- `_row_download_clickable(row, cells)`: find download action in the row, not only the last cell.
- `_label_matches_target_or_filename(target_doc, label, file_name)`: preserve successful files whose row label classifies as OTHER when filename proves the target.

### Test Coverage

- `test_download_one_document_waits_until_downloadable_rows_exist`: polls until table appears.
- `test_download_one_document_detects_row_level_download_table_fixture`: fixture row links beat header absence.
- `test_download_one_document_accepts_two_cell_rows`: no three-cell minimum.
- `test_final_tor_filter_falls_back_to_download_filename`: OTHER label does not discard TOR file.

### Decision Completeness

Goal: make browser document extraction robust for the observed `69049163846` detail-page layout.

Non-goals: no DB migrations, API changes, web changes, storage changes, or broad crawler rewrite.

Success criteria: new fixture-backed tests fail before the implementation and pass after; existing worker browser download tests remain green; compile and lint gates pass.

Public interfaces: no endpoint, CLI, env var, schema, or migration changes.

Edge cases / failure modes:
- Delayed tables: fail open after bounded wait by returning no rows rather than hanging.
- Headerless document table: accept rows only when they contain target labels and actionable download controls.
- Sparse rows: accept two-cell rows but still require a matching target label and click action.
- OTHER label classification: fall back to filename for retention; still filter unrelated files.

Rollout & monitoring: no flag or migration. Watch existing `DOCUMENT_PROGRESS table_scan_finished`, `row_matched`, and ingest logs for recovered document counts.

Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
- `./.venv/bin/python -m compileall apps/worker/src`
- `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py`

### Dependencies

Uses existing pytest, worker package imports, and Playwright-compatible fake page objects. No new runtime dependency.

### Validation

The fixture exercises the failing detail layout and synthetic tests pin the helper behavior around timing and fallback classification.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Parser hardening helpers | `collect_downloaded_documents()` -> `_download_one_document()` | Same module imports already used by worker | N/A |
| Fixture regression | `pytest tests/phase1/test_worker_browser_downloads.py` | Test imports from `egp_worker.browser_downloads` | N/A |

## Plan Draft B - Add broad fallback scanner first

### Overview

Instead of changing the targeted scanner first, add a broader detail-page scan when targeted collection returns nothing. This would reduce the risk of disrupting existing target-row flows but might leave slow sleeps and brittle row detection in place.

### Files to Change

- `apps/worker/src/egp_worker/browser_downloads.py`: add a fallback branch after each failed target scan.
- `tests/phase1/test_worker_browser_downloads.py`: test fallback recovery from fixture.
- `tests/fixtures/browser_downloads/detail_69049163846.html`: fixture for real layout.

### Implementation Steps

TDD sequence:
1. Add fixture-driven fallback test.
2. Confirm current code returns no documents from the fixture.
3. Implement fallback detail scan reuse.
4. Run focused tests and minimal gates.

Functions:
- `_collect_any_available_detail_documents(page)`: scan all rows and download matching artifacts.
- `_download_one_document(...)`: call fallback when targeted rows are absent.

### Test Coverage

- `test_fixture_detail_page_fallback_collects_documents`: broad fallback recovers rows.
- `test_fallback_dedupes_targeted_results`: avoids duplicate documents.

### Decision Completeness

Goal: recover documents missed by targeted table detection.

Non-goals: no timing rewrite or classifier behavior changes.

Success criteria: fixture recovers at least invitation/TOR document.

Public interfaces: none.

Edge cases / failure modes:
- Broad fallback may click unrelated links; fail closed by requiring file-like or known-label rows.
- Existing targeted flow unchanged, but current sleep remains.

Rollout & monitoring: existing document-count logs.

Acceptance checks: same focused pytest, compileall, and ruff commands.

### Dependencies

No new dependencies.

### Validation

Fixture test verifies recovery, but timing behavior remains less directly tested.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Broad detail fallback | `_download_one_document()` | Same module runtime path | N/A |

## Comparative Analysis

Draft A fixes the root parser assumptions: timing, table detection, row shape, and filename fallback. It has a smaller runtime blast radius because rows still need target labels and actionable controls.

Draft B is faster to add but treats the symptom by introducing another collection path. It risks extra clicks and does not remove the brittle `_sleep(0.5)` or header-only table assumption.

Both plans avoid DB/API/frontend changes and follow the worker AGENTS guidance to keep browser parsing in `egp_worker`. Draft A better matches P1 and TDD T-1 because each reported parser gap gets a direct regression.

## Unified Execution Plan

### Overview

Use Draft A. Add fixture-backed failing tests first, then harden the targeted scanner with small helpers that wait for actionable rows and match documents from row content plus filenames.

### Files to Change

- `apps/worker/src/egp_worker/browser_downloads.py`: parser helpers and targeted scanner updates.
- `tests/phase1/test_worker_browser_downloads.py`: focused regressions.
- `tests/fixtures/browser_downloads/detail_69049163846.html`: fixture for the failing layout.
- `.codex/coding-log.current`: current Coding Log pointer.

### Implementation Steps

TDD sequence:
1. Add/stub the regression tests and fixture.
2. Run `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q` and record RED.
3. Implement bounded wait, row-level table detection, relaxed cell handling, and filename fallback.
4. Refactor minimally for helper clarity.
5. Run focused pytest, compileall, ruff, then formal `g-check`.

Functions:
- `_wait_for_downloadable_detail_rows(page)`: bounded poll replacing the fixed pre-scan sleep.
- `_iter_downloadable_document_rows(page)`: central table/row discovery for `_download_one_document`.
- `_table_has_downloadable_document_rows(table)`: true for header matches or row-level download controls.
- `_row_download_clickable(row, cells)`: find actionable links/buttons from the row.
- `_downloaded_document_matches_target(target_doc, document, fallback_label)`: retain successful downloads using source label or filename.

### Test Coverage

- `test_download_one_document_waits_until_downloadable_rows_exist`: wait loop replaces blind sleep.
- `test_download_one_document_detects_row_level_download_table_fixture`: real layout row controls detected.
- `test_download_one_document_accepts_two_cell_rows`: sparse rows are valid.
- `test_final_tor_filter_falls_back_to_download_filename`: OTHER labels retained by filename.

### Decision Completeness

Goal: make `browser_downloads.py` correctly collect documents from the `69049163846` detail-page layout and adjacent table variants.

Non-goals: no live crawl smoke unless local gates require it, no schema/API/frontend changes, no broad collection rewrite, and no Excel/system-of-record work.

Success criteria:
- RED and GREEN test evidence captured in this log.
- Worker browser download tests pass.
- Worker source compiles.
- Ruff passes for touched files.
- Formal `g-check` has no unresolved findings before PR creation.

Public interfaces:
- APIs/endpoints: unchanged.
- Schemas/contracts: unchanged.
- Env vars/CLI flags: unchanged.
- Migrations: unchanged.

Edge cases / failure modes:
- If no table appears before timeout, return `[]` and continue to existing fallback collection.
- If a table has no headers but rows contain document labels and download actions, scan it.
- If rows have only label plus action cells, process them.
- If a successful final-TOR download has an unhelpful source label, classify by filename before discarding.

Rollout & monitoring:
- No flag or migration.
- Backout is reverting the parser/test commit.
- Watch `DOCUMENT_PROGRESS` counts and document ingest success logs for recovered capture counts.

Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
- `./.venv/bin/python -m compileall apps/worker/src`
- `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py`

### Dependencies

Existing local Python environment only.

### Validation

Fixture plus fakes verify the parser without live e-GP dependence; logs provide observed runtime evidence for the failing project.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Parser helpers | `collect_downloaded_documents()` -> `_download_one_document()` | Existing `egp_worker.browser_downloads` module path used by discovery/close-check workers | N/A |
| Tests/fixture | `pytest tests/phase1/test_worker_browser_downloads.py` | Direct test import of `egp_worker.browser_downloads` | N/A |

## Implementation Summary (2026-06-07 19:35 +07)

### Goal

Harden worker browser document parsing for the `69049163846` detail-page layout and adjacent parser gaps.

### What Changed

- `apps/worker/src/egp_worker/browser_downloads.py`: replaced the fixed pre-scan `_sleep(0.5)` with `_wait_for_downloadable_detail_rows()`, added row-level document table/action detection, allowed two-cell rows, and made final TOR retention check source label, filename, and matched row label before discarding a successful download.
- `tests/phase1/test_worker_browser_downloads.py`: added fake delayed-table and fixture-backed regressions for polling, row-level download tables, sparse rows, and filename fallback.
- `tests/fixtures/browser_downloads/detail_69049163846.html`: added a stable fixture representing the observed detail-page document table layout from the failing run evidence.

### TDD Evidence

RED:

`/Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q -k "waits_until_downloadable_rows_exist or detects_row_level_download_table_fixture or accepts_two_cell_rows or final_tor_filter_falls_back_to_download_filename"`

Result: 4 failed. Key reasons: one table query only, no row-level headerless table detection, two-cell row skipped, and final TOR result discarded when source label classified as OTHER.

GREEN:

`PYTHONPATH=apps/worker/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/shared-types/src:packages/db/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q -k "waits_until_downloadable_rows_exist or detects_row_level_download_table_fixture or accepts_two_cell_rows or final_tor_filter_falls_back_to_download_filename"`

Result: 4 passed.

### Tests Run

- `PYTHONPATH=apps/worker/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/shared-types/src:packages/db/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q` -> 46 passed.
- `/Users/subhajlimanond/dev/egp/.venv/bin/python -m compileall apps/worker/src` -> passed.
- `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py` -> passed.
- `PYTHONPATH=apps/worker/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/shared-types/src:packages/db/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q` -> 12 passed.
- `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check apps/worker packages` -> passed.

### Wiring Verification

Runtime path remains `collect_downloaded_documents()` -> `_download_one_document()` in `egp_worker.browser_downloads`; discovery/close-check worker callers already import this module. No new API route, CLI flag, env var, migration, or schema wiring was added.

### Behavior Changes And Risks

- Delayed table rendering now gets a bounded poll before returning no rows.
- Headerless document tables are accepted only if rows contain actionable download controls, reducing the chance of clicking unrelated tables.
- Successful final TOR downloads are no longer discarded solely because the downloaded document source label classified as OTHER.
- Fail-open behavior is preserved: if no rows appear within the bounded attempts, existing fallback collection still runs through `collect_downloaded_documents()`.

### Follow-ups / Known Gaps

- A live browser smoke against e-GP remains useful but is not required for this TDD regression slice.

## Review (2026-06-07 19:28 +0700) - working tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp-browser-download-parser-hardening`
- Branch: `fix/browser-download-parser-hardening`
- Scope: working tree at base `c51618a0`
- Commands Run:
  - `git status -sb`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/worker/src/egp_worker/browser_downloads.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- tests/phase1/test_worker_browser_downloads.py`
  - `nl -ba apps/worker/src/egp_worker/browser_downloads.py | sed -n '380,520p'`
  - `nl -ba tests/phase1/test_worker_browser_downloads.py | sed -n '1,760p'`
  - `sed -n '1,140p' tests/fixtures/browser_downloads/detail_69049163846.html`
  - `PYTHONPATH=apps/worker/src:packages/crawler-core/src:packages/domain/src:packages/document-classifier/src:packages/shared-types/src:packages/db/src:packages/observability/src /Users/subhajlimanond/dev/egp/.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
  - `/Users/subhajlimanond/dev/egp/.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py`

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

- Auggie semantic search was unavailable with HTTP 402, so this review used targeted diff/file inspection plus local test evidence.
- The fixture is based on captured failing-run evidence and a stable representative DOM shape; no live e-GP browser smoke was run.

### Recommended Tests / Validation

- Already run: focused browser download parser tests, worker workflow tests, compileall, targeted ruff, and broader worker/package ruff.
- Optional later validation: live targeted document backfill for project `69049163846`.

### Rollout Notes

- No feature flag, migration, API change, env var, or schema change.
- Backout is a single parser/test revert if document capture behavior regresses.
