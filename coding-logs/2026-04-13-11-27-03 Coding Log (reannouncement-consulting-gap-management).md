## Plan Draft A

### Overview
Audit the legacy crawler failure modes around re-announcements, consultant projects, and workbook/file drift. Propose a phased cleanup that fixes identity first, then closure rules, then observability.

### Files to Change
- `egp_crawler.py`: stop alias-based false closure and misleading Excel updates
- `test_egp_crawler.py`: add regressions for re-announcement and consultant cases
- `apps/worker/src/egp_worker/workflows/discover.py`: align worker ingestion with canonical identity
- `packages/db/src/egp_db/repositories/project_repo.py`: use alias/canonical-id storage as source of truth

### Implementation Steps
1. Add tests for re-announcement rows where `search_name` contains a new project number but `project_name` matches an old row.
2. Confirm the tests fail because `update_excel()` currently matches by `project_number` then `project_name`.
3. Replace legacy “done” semantics with explicit lifecycle states for stale, prelim-pricing, consultant-timeout, and final-TOR-ready.
4. Refactor Excel export so it mirrors canonical project identity instead of deciding crawler behavior.
5. Run focused tests on Excel update, stale cleanup, and consultant handling.

### Test Coverage
- `test_update_excel_does_not_merge_reannouncement_into_old_name_row`
- `test_stale_cleanup_does_not_mark_final_tor_downloaded`
- `test_consulting_project_invitation_only_stays_open`
- `test_manual_artifact_folder_does_not_imply_crawler_download`

### Decision Completeness
- Goal: separate project identity from closure state
- Non-goals: redesign the whole UI/export pipeline
- Success criteria: re-announcements create or update the correct project row; consultant projects remain open until timeout/winner/final evidence
- Public interfaces: Excel export semantics, worker project upsert behavior
- Edge cases: reused titles, new project number with same title, manual downloads outside crawler path
- Rollout: fix root crawler first, then mirror into worker/export path
- Acceptance checks: targeted pytest cases and one bounded live replay

### Validation
- Verify workbook rows no longer mismatch `search_name` and `project_number`
- Verify stale/manual consultant cases remain distinguishable

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| legacy Excel dedupe fix | `egp_crawler.py:update_excel()` | direct call from `_process_one_project()` | Excel columns A-J |
| canonical identity | worker discover upsert | `discover.py -> SqlProjectRepository.upsert_project()` | `projects`, `project_aliases` |
| closure rules | close/timeout workflows | `packages/crawler-core` imports | DB state, not Excel |

## Plan Draft B

### Overview
Leave the legacy crawler mostly unchanged for collection, but stop using the workbook as a decision store. Move all revisit/closure logic to canonical DB state and treat Excel as export-only.

### Files to Change
- `egp_crawler.py`
- `packages/crawler-core/src/egp_crawler_core/canonical_id.py`
- `packages/crawler-core/src/egp_crawler_core/closure_rules.py`
- `packages/db/src/egp_db/repositories/project_repo.py`

### Implementation Steps
1. Add an export adapter that writes workbook rows from canonical DB records.
2. Remove legacy `load_existing_projects()` from the decision loop for the worker path.
3. Backfill aliases for `search_name`, `detail_name`, and `project_number`.
4. Add explicit closure reasons for `CONSULTING_TIMEOUT_30D`, `STALE_NO_TOR`, and winner/contract closure.

### Trade-offs
- Stronger long-term correctness
- Slower to finish because it pushes more behavior into the DB-backed path

## Unified Execution Plan

### Overview
Use a two-stage approach. First, patch the legacy crawler to stop corrupting identity and closure state. Second, move operational truth to canonical DB-backed identity/closure rules and relegate Excel to reporting.

### Files to Change
- `egp_crawler.py`
- `test_egp_crawler.py`
- `packages/crawler-core/src/egp_crawler_core/canonical_id.py`
- `packages/crawler-core/src/egp_crawler_core/closure_rules.py`
- `packages/db/src/egp_db/repositories/project_repo.py`
- `apps/worker/src/egp_worker/workflows/discover.py`

### Implementation Steps
1. Tests first for re-announcement row collision, consultant invitation-only incompleteness, and stale/manual deletion semantics.
2. Stop treating `tor_downloaded = Yes` as a generic “do not revisit” bit in the legacy workbook path.
3. Change re-announcement matching to prefer exact `project_number`; if `search_name` embeds a different project number than the row, create a new row instead of reusing by `project_name`.
4. Track consultant projects separately: invitation/pricing saves are evidence, not closure.
5. Add explicit artifact provenance markers so manual folder copies are not misread as crawler downloads.
6. Port equivalent behavior into the worker/codebase path using canonical IDs and closure rules.

### Validation
- `pytest test_egp_crawler.py -q`
- worker discovery/closure tests
- one bounded live replay for a re-announcement and one consultant project

## Implementation Progress

### Completed In This Slice
- Branched from the dirty recovery base into `codex/reannouncement-consulting-gap-management` so the existing crawler fixes remain intact.
- Added shared `ArtifactBucket` values and a reusable `derive_artifact_bucket(...)` helper in `packages/document-classifier`.
- Updated the legacy crawler to:
  - record `tracking_status`, `closed_reason`, and `artifact_bucket` in Excel exports,
  - stop using fake `tor_downloaded = Yes` for prelim-pricing and stale closures,
  - write per-project `crawler_manifest.json` provenance files,
  - resume the same keyword/page after browser restarts,
  - avoid merging re-announcements by title while still backfilling truly number-less rows.
- Updated worker discovery to:
  - emit `artifact_bucket`,
  - promote `project_state` from downloaded artifact evidence,
  - resume the same keyword/page after browser restarts.
- Added a DB-facing `SqlDocumentRepository.get_artifact_bucket(...)` helper so canonical storage can derive the same artifact bucket from stored document metadata.

### Focused Validation
- `./.venv/bin/python -m pytest test_egp_crawler.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_browser_downloads.py tests/phase1/test_phase1_domain_logic.py -q`
  - `193 passed`
- `./.venv/bin/ruff check egp_crawler.py test_egp_crawler.py apps/worker/src/egp_worker/browser_discovery.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_browser_downloads.py tests/phase1/test_phase1_domain_logic.py packages/shared-types/src/egp_shared_types/enums.py packages/document-classifier/src/egp_document_classifier/classifier.py packages/document-classifier/src/egp_document_classifier/__init__.py packages/db/src/egp_db/repositories/document_repo.py tests/phase1/test_document_persistence.py`
  - passed

### Known Validation Gap
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q`
  - fails during metadata bootstrap with `discovery_jobs.profile_id -> crawl_profiles` unresolved. This appears broader than this slice; the new `get_artifact_bucket(...)` method itself is import-safe and lint-clean, but that isolated file is not a reliable gate right now.

## g-check Review

### Findings
- No blocking correctness findings in the modified crawler/worker/domain files after the focused test pass.

### Residual Risks
- `derive_artifact_bucket(...)` intentionally collapses draft evidence into the `draft_plus_pricing` bucket even if pricing was not observed in the same run, because the agreed export vocabulary has no separate `draft_only` state.
- The legacy script still uses Excel as an operational fallback store. This slice makes it less lossy, but the full “DB is source of truth / Excel is export-only” migration remains incomplete.


## Implementation (2026-04-13 14:02:34 +07) - DB-backed legacy Excel export

### Goal
Finish the remaining export slice so the API-backed Excel download matches the legacy `project_list.xlsx` contract and derives `tracking_status`, `closed_reason`, and `artifact_bucket` from canonical DB state instead of workbook-local logic.

### What Changed
- `apps/api/src/egp_api/services/export_service.py`
  - Replaced the Thai summary sheet layout with the 13-column legacy workbook shape: `download_date`, `project_name`, `organization`, `project_number`, `budget`, `proposal_submission_date`, `keyword`, `tor_downloaded`, `prelim_pricing`, `search_name`, `tracking_status`, `closed_reason`, `artifact_bucket`.
  - Added export-time derivation for `keyword` from the latest project status-event snapshot, `search_name` from stored project aliases, `tor_downloaded` / `prelim_pricing` from canonical state plus document evidence, and `artifact_bucket` from the document repository.
- `apps/api/src/egp_api/main.py`
  - Wired the shared `document_repository` into `ExportService` so API exports use the same stored document metadata as the rest of the control plane.
- `tests/phase2/test_export_service.py`
  - Updated the baseline export contract assertions to the legacy workbook format.
  - Added regression coverage proving DB-backed export derives `keyword`, `search_name`, `tracking_status`, `closed_reason`, and `artifact_bucket` from canonical persistence plus stored documents.

### TDD Evidence
- Tests added/changed:
  - `test_export_to_excel_produces_valid_xlsx_with_headers`
  - `test_export_to_excel_derives_legacy_state_columns_from_db_and_documents`
  - updated export-column index assertions in the existing filter/route helpers
- RED command:
  - `./.venv/bin/python -m pytest tests/phase2/test_export_service.py -q`
  - Failed because the export still emitted the old Thai 10-column summary format, and `ExportService` did not accept a `document_repository` for DB-derived artifact buckets.
- GREEN command:
  - `./.venv/bin/python -m pytest tests/phase2/test_export_service.py -q`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase2/test_export_service.py -q`
  - `6 passed`
- `./.venv/bin/ruff check apps/api/src/egp_api/services/export_service.py apps/api/src/egp_api/main.py tests/phase2/test_export_service.py`
  - passed

### Wiring Verification
- Runtime wiring: `apps/api/src/egp_api/main.py` now constructs `ExportService(project_repository, document_repository=repository, ...)`.
- Request path: `apps/api/src/egp_api/routes/exports.py` still funnels `/v1/exports/excel` into `ExportService.export_to_excel(...)`.
- Evidence path: `ExportService.export_to_excel(...)` now combines `project_repository.list_projects(...)`, `project_repository.get_project_detail(...)`, and `document_repository.get_artifact_bucket(...)` to reconstruct the legacy workbook row from canonical persistence.
- Route contract: `tests/phase2/test_export_service.py::test_export_route_matches_explorer_filter_contract` still confirms export filtering matches `/v1/projects` for the same query.

### Behavior Changes And Risks
- API Excel exports now match the legacy workbook column order and field names instead of the Thai summary-only layout.
- `tracking_status` and `closed_reason` now come directly from canonical project state, while `artifact_bucket` and `tor_downloaded` are derived from stored document metadata when the document repository is wired.
- `prelim_pricing` remains a state-derived export field, which preserves the legacy behavior for prelim-pricing closures that intentionally have no document evidence.

### Follow-ups / Known Gaps
- Export currently performs per-project detail and artifact-bucket lookups (`N+1` style). That is acceptable for this slice, but if export volume grows materially, it should be replaced with a bulk export query/helper in the repositories.
- The broader `tests/phase1/test_document_persistence.py` schema-bootstrap failure around `discovery_jobs.profile_id -> crawl_profiles` remains outside this slice.

## Review (2026-04-13 14:02:34 +07) - working-tree export slice

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: codex/reannouncement-consulting-gap-management
- Scope: working tree (export-service related files only)
- Commit: dd64e02
- Commands Run: `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat -- apps/api/src/egp_api/services/export_service.py apps/api/src/egp_api/main.py tests/phase2/test_export_service.py`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/services/export_service.py apps/api/src/egp_api/main.py tests/phase2/test_export_service.py`; `./.venv/bin/python -m pytest tests/phase2/test_export_service.py -q`; `./.venv/bin/ruff check apps/api/src/egp_api/services/export_service.py apps/api/src/egp_api/main.py tests/phase2/test_export_service.py`

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings.

LOW
- `apps/api/src/egp_api/services/export_service.py` now does per-project detail and artifact-bucket lookups during export. This is acceptable at current scope, but it is a scale risk rather than a correctness bug.

### Open Questions / Assumptions
- Assumed that the legacy workbook contract should prefer exact legacy column names/order over the newer Thai summary presentation, because the project plan and the “Excel is export-only” goal both require drop-in compatibility.
- Assumed that `keyword` should come from the latest stored discovery/raw snapshot when available, with blank fallback when a project has no recorded keyword evidence.

### Recommended Tests / Validation
- Re-run `tests/phase2/test_export_service.py -q` after any follow-on export query optimization.
- When the repo-wide schema bootstrap issue is fixed, add a persistence-to-export test that seeds project and document rows through the shared Postgres bootstrap path rather than the lightweight SQLite fixtures.

### Rollout Notes
- Backwards compatibility improved: API export now matches the legacy workbook schema expected by existing consumers.
- No migration or env-var changes required for this slice; the new behavior is active wherever `create_app(...)` wires the shared document repository into `ExportService`.
