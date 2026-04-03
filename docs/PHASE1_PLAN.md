# Phase 1: Foundation and State Correctness

## Overview

Stabilize the current crawler logic by replacing the binary completion model with an explicit project lifecycle, moving from Excel to PostgreSQL, adding document hash dedup, and implementing the three missing closure rules (winner, consulting timeout, stale).

## Files to Create/Change

### New Files

| File | Purpose |
|------|---------|
| `packages/db/src/migrations/001_initial_schema.sql` | PostgreSQL schema (13 tables) |
| `packages/db/src/repositories/project_repo.py` | Project CRUD with alias dedup |
| `packages/db/src/repositories/document_repo.py` | Document CRUD with hash dedup |
| `packages/db/src/repositories/run_repo.py` | Crawl run/task tracking |
| `packages/shared-types/src/egp_shared_types/enums.py` | Shared enums (ProjectState, ClosedReason, etc.) |
| `packages/crawler-core/src/egp_crawler_core/project_lifecycle.py` | State transition logic |
| `packages/crawler-core/src/egp_crawler_core/canonical_id.py` | Canonical project ID generation |
| `packages/crawler-core/src/egp_crawler_core/document_hasher.py` | SHA-256 hashing + phase classification |
| `packages/crawler-core/src/egp_crawler_core/closure_rules.py` | Consulting timeout, winner close, stale close |
| `apps/api/src/main.py` | FastAPI entry point |
| `apps/api/src/routes/projects.py` | Project list/detail endpoints |
| `apps/api/src/routes/documents.py` | Document endpoints |
| `apps/api/src/routes/runs.py` | Run/task endpoints |
| `apps/api/src/services/project_service.py` | Project business logic |
| `apps/api/src/services/export_service.py` | Excel export (replaces Excel-as-DB) |
| `apps/worker/src/workflows/discover.py` | Workflow A: discover open projects |
| `apps/worker/src/workflows/close_check.py` | Workflow C: winner/contract closure sweep |
| `apps/worker/src/workflows/timeout_sweep.py` | Workflow D+E: consulting timeout + stale |

### Files to Refactor (from existing `egp_crawler.py`)

| Current Code | Extracted To | What Changes |
|-------------|-------------|-------------|
| `egp_crawler.py:309-374` (profiles/keywords) | `packages/crawler-core/src/profiles.py` | Load from DB instead of hardcoded |
| `egp_crawler.py:1037-1084` (load_existing_projects) | `packages/db/src/repositories/project_repo.py` | Query PostgreSQL instead of Excel |
| `egp_crawler.py:1121-1198` (update_excel) | `packages/db/src/repositories/project_repo.py` | Upsert to PostgreSQL |
| `egp_crawler.py:1699-1755` (extract_project_info) | `packages/crawler-core/src/parser.py` | Add procurement_type classification |
| `egp_crawler.py:1662-1696` (check_announcement_stale) | `packages/crawler-core/src/egp_crawler_core/closure_rules.py` | Replace with consulting/stale/winner rules |
| `egp_crawler.py:700-723` (is_tor_file, is_tor_doc_label) | `packages/document-classifier/src/classifier.py` | Add phase classification |

## Implementation Steps

### Step 1: Database + Repositories

**`canonical_id.py`** — `generate_canonical_id(project_number, org, name, date, budget)`
Generate a stable canonical ID from project_number when available, else from a normalized fingerprint of org+name+date+budget. Returns a deterministic string.

**`project_repo.py`** — `upsert_project(tenant_id, project_data) -> Project`
Find existing project by canonical_id or alias match. If found, update fields and add new aliases. If not found, create new project with all aliases. Never create duplicates.

**`project_repo.py`** — `find_by_alias(tenant_id, alias_value) -> Project | None`
Search project_aliases table for any matching value across all alias types.

**`document_repo.py`** — `store_document(project_id, file_bytes, metadata) -> Document | None`
Hash file with SHA-256. Check for existing document with same project_id + hash. If duplicate, return None. If new, store to S3, create document record, handle supersession.

### Step 2: Lifecycle + Closure Rules

**`project_lifecycle.py`** — `transition_state(project, new_state, reason=None)`
Validate state transition is legal. Update project_state and closed_reason. Create project_status_event record. Never write fake tor_downloaded=Yes.

**`closure_rules.py`** — `check_consulting_timeout(project, threshold_days=30) -> bool`
If procurement_type is consulting and last_changed_at is older than threshold, return True.

**`closure_rules.py`** — `check_winner_closure(project, observed_status) -> ClosedReason | None`
If observed status matches winner/contract patterns (ประกาศผู้ชนะ, ลงนามสัญญา), return appropriate ClosedReason.

**`closure_rules.py`** — `check_stale_closure(project, threshold_days=45) -> bool`
For non-consulting projects with no status movement and no TOR, return True.

### Step 3: Document Classification

**`document_hasher.py`** — `hash_file(data: bytes) -> str`
Return SHA-256 hex digest of file bytes.

**`classifier.py`** — `classify_document(label, status_context) -> (DocumentType, DocumentPhase)`
Classify document type (tor/invitation/mid_price/other) and phase (public_hearing/final/unknown) from label text and page context. Uses existing `TOR_DOC_MATCH_TERMS` plus new ประชาพิจารณ์ detection.

### Step 4: Crawler Worker Refactor

**`discover.py`** — `run_discover_workflow(profile, browser)`
Execute keyword search, collect eligible projects, extract info, upsert to DB, download documents with hash dedup.

**`close_check.py`** — `run_close_check_workflow(browser)`
Search for winner/contract statuses, match against existing open projects, close matched projects.

**`timeout_sweep.py`** — `run_timeout_sweep()`
Query DB for consulting projects idle > 30 days and non-consulting projects idle > 45 days. Close with appropriate reasons.

### Step 5: API Endpoints

**`routes/projects.py`** — `GET /v1/projects`, `GET /v1/projects/:id`
List projects with filters (state, type, org, keyword, budget range). Return project detail with aliases and status history.

**`services/export_service.py`** — `export_to_excel(tenant_id, filters) -> bytes`
Generate Excel file matching current `project_list.xlsx` format for backwards compatibility. This replaces Excel as database.

## Test Coverage

### Canonical ID Tests (`test_canonical_id.py`)

- `test_uses_project_number_when_available` — prefer project_number as canonical ID
- `test_generates_fingerprint_without_number` — fallback to org+name+date+budget hash
- `test_fingerprint_stable_across_calls` — same inputs produce same ID
- `test_normalizes_whitespace_in_fingerprint` — trim/collapse whitespace differences
- `test_different_projects_get_different_ids` — no collisions for distinct projects

### Project Lifecycle Tests (`test_project_lifecycle.py`)

- `test_valid_transition_from_discovered_to_open` — happy path state change
- `test_consulting_project_closes_after_30_days` — consulting timeout rule
- `test_stale_project_closes_after_45_days` — stale non-consulting rule
- `test_winner_closes_open_project` — winner announcement closure
- `test_never_writes_fake_tor_downloaded` — no fake completion flags
- `test_closed_reason_set_correctly` — reason matches closure type
- `test_status_event_created_on_transition` — audit trail created

### Document Dedup Tests (`test_document_repo.py`)

- `test_same_hash_not_stored_twice` — SHA-256 dedup works
- `test_different_hash_creates_new_version` — version supersession
- `test_superseded_doc_marked_not_current` — old version is_current=false
- `test_public_hearing_tor_classified_correctly` — phase detection
- `test_final_tor_classified_correctly` — final phase detection
- `test_diff_record_created_on_version_change` — diff metadata stored

### Project Dedup Tests (`test_project_repo.py`)

- `test_same_project_three_keywords_one_record` — alias-based dedup
- `test_project_number_backfill_merges` — day 1 no number, day 3 with number
- `test_alias_types_all_searchable` — search_name, detail_name, project_number, fingerprint

### Closure Rule Tests (`test_closure_rules.py`)

- `test_winner_announcement_closes_project` — ประกาศผู้ชนะ detection
- `test_contract_signed_closes_project` — ลงนามสัญญา detection
- `test_consulting_timeout_30_days` — consulting inactivity rule
- `test_non_consulting_not_affected_by_30d_rule` — type-specific
- `test_stale_45_days_for_non_consulting` — general stale rule

### Export Tests (`test_export_service.py`)

- `test_excel_export_matches_legacy_format` — backwards compatible columns
- `test_export_respects_filters` — filtered export works
- `test_export_includes_all_10_columns` — header parity with legacy

## Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `canonical_id.py` | `project_repo.py:upsert_project()` | import in project_repo | N/A |
| `project_lifecycle.py` | `project_service.py:close_project()` | import in project_service | `projects.project_state`, `project_status_events` |
| `closure_rules.py` | `timeout_sweep.py:run_timeout_sweep()` | import in timeout_sweep | `projects.last_changed_at`, `projects.procurement_type` |
| `document_hasher.py` | `document_repo.py:store_document()` | import in document_repo | `documents.sha256` |
| `classifier.py` | `document_repo.py:store_document()` | import in document_repo | `documents.document_type`, `documents.document_phase` |
| `project_repo.py` | `routes/projects.py` | import in route module | `projects`, `project_aliases` |
| `document_repo.py` | `routes/documents.py` | import in route module | `documents`, `document_diffs` |
| `discover.py` | Worker main loop | SQS consumer dispatch | `projects`, `documents`, `crawl_tasks` |
| `close_check.py` | Worker main loop | SQS consumer dispatch | `projects`, `project_status_events` |
| `export_service.py` | `routes/exports.py` | import in route module | `exports`, `projects` |
| Migration `001` | N/A | Applied via `psql` / migration tool | All 13 tables |

## Dependencies

- PostgreSQL 15+
- Python 3.12+
- FastAPI, SQLAlchemy 2.0, asyncpg
- Playwright (existing)
- boto3 (S3 storage)
- openpyxl (Excel export only)

## Validation

1. Run all acceptance tests from PRD section 30 (items 1-7 for Phase 1)
2. Migrate existing `project_list.xlsx` data into PostgreSQL
3. Run crawler with new lifecycle logic against live e-GP
4. Verify no fake `tor_downloaded = Yes` writes
5. Verify consulting projects close after 30 days
6. Verify Excel export matches legacy format
