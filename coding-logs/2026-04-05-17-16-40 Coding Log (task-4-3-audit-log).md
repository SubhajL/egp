# Task 4.3 Planning: Full Audit Log

## Plan Draft A

### Overview
Add a tenant-scoped audit log read model in the API/admin surface by aggregating existing durable event streams for projects, billing, and document reviews, while adding new persisted audit entries for admin actions and document-ingest events that are not currently represented as event rows. Expose the unified feed through a bounded `/v1/admin/audit-log` endpoint and a minimal admin tab so operators can investigate changes without leaving the product.

### Files to Change
- `packages/db/src/migrations/009_audit_log.sql`: add additive tenant-scoped `audit_log_events` table for admin and document lifecycle events not already modeled elsewhere.
- `packages/db/src/egp_db/repositories/audit_repo.py`: new unified audit repository that writes new audit entries and lists a merged tenant feed across project, document, review, billing, and admin sources.
- `packages/db/src/egp_db/repositories/__init__.py`: export the audit repository factory and records.
- `apps/api/src/egp_api/services/audit_service.py`: add API-facing filter/pagination logic for the audit feed.
- `apps/api/src/egp_api/services/admin_service.py`: emit admin audit entries for user, preference, and settings mutations.
- `apps/api/src/egp_api/services/webhook_service.py`: emit admin audit entries for webhook create/delete operations.
- `apps/api/src/egp_api/services/document_ingest_service.py`: emit audit entries for document ingest and route document-review actions into the unified audit layer.
- `apps/api/src/egp_api/routes/admin.py`: add `GET /v1/admin/audit-log` response models and endpoint.
- `apps/api/src/egp_api/main.py`: wire the audit repository/service into app state and dependent services.
- `apps/web/src/lib/api.ts`: add audit DTOs and fetch helper.
- `apps/web/src/lib/hooks.ts`: add `useAuditLog`.
- `apps/web/src/app/(app)/admin/page.tsx`: add an audit log tab with filters and recent event list.
- `tests/phase4/test_admin_api.py`: cover audit log endpoint, tenant scoping, filters, and admin-generated events.
- `tests/phase1/test_documents_api.py`: cover document-ingest audit entries if surfaced via API behavior.
- `tests/phase1/test_document_persistence.py`: cover durable document event persistence when needed at repository level.
- `tests/phase3/test_invoice_lifecycle.py`: cover billing events appearing in the unified audit feed.

### Implementation Steps
#### TDD sequence
1. Add/stub audit-log API tests for representative project, billing, review, document, and admin events.
2. Run the focused pytest command and confirm failure because audit repository/service/endpoint do not exist.
3. Implement the additive schema, repository aggregation, and API endpoint with the smallest logic needed to pass.
4. Add admin and document-ingest emitters, then refactor shared audit serialization only if needed.
5. Run fast gates: targeted pytest, `ruff`, and web typecheck for touched slices.

#### Functions and behavior
- `SqlAuditRepository.record_event(...)`: persist tenant-scoped audit entries for admin and document lifecycle actions with actor, entity ids, event type, summary, and metadata JSON.
- `SqlAuditRepository.list_events(...)`: merge rows from `audit_log_events`, `project_status_events` + `projects`, `document_review_events`, and `billing_events` into a single reverse-chronological tenant feed.
- `_project_audit_select(...)`: normalize crawler/API project transitions into audit entries with `actor_subject='system:worker'`.
- `_billing_audit_select(...)`: normalize billing lifecycle events using existing `billing_events`.
- `_document_review_audit_select(...)`: normalize document-review actions from `document_review_events`.
- `_direct_audit_select(...)`: return newly persisted admin/document audit rows.
- `AuditService.list_events(...)`: enforce bounded pagination and optional source/entity filters for API consumers.
- `AdminService.* mutation methods`: record audit events for create user, update user, update notification preferences, and update settings after successful writes.
- `WebhookService.create_webhook/delete_webhook(...)`: record admin audit events after successful webhook mutations.
- `DocumentIngestService.ingest_document_bytes(...)`: persist a document audit event only when a new document row is created; actor defaults to `system:api` or request subject when available.
- `DocumentIngestService.apply_document_review_action(...)`: continue using repository review events, with the unified audit feed consuming them.

### Test Coverage
- `tests/phase4/test_admin_api.py::test_admin_audit_log_returns_project_billing_review_document_and_admin_events`
  - Unified audit feed includes representative cross-domain events.
- `tests/phase4/test_admin_api.py::test_admin_audit_log_applies_source_and_entity_filters`
  - Filters restrict rows without breaking pagination totals.
- `tests/phase4/test_admin_api.py::test_admin_audit_log_is_tenant_scoped`
  - Other-tenant events never leak.
- `tests/phase4/test_admin_api.py::test_admin_mutations_append_admin_audit_entries`
  - User/settings/webhook mutations create audit rows.
- `tests/phase1/test_documents_api.py::test_document_ingest_writes_audit_entry_for_new_document`
  - New document ingestion emits durable audit metadata.
- `tests/phase3/test_invoice_lifecycle.py::test_billing_events_surface_in_admin_audit_log`
  - Existing billing events appear in unified feed.

### Decision Completeness
- Goal:
  - Deliver a tenant-scoped, queryable audit log that covers project, document, billing, review, and admin actions.
- Non-goals:
  - Backfilling historical admin/document events before this migration.
  - Introducing a new worker-side event bus or background processing pipeline.
  - Full frontend search/export beyond simple list filters.
- Success criteria:
  - `GET /v1/admin/audit-log` returns bounded, reverse-chronological rows for at least one event from each required domain.
  - Admin/user/settings/webhook mutations create durable audit entries with actor and timestamp.
  - Existing project status, billing, and review history appear in the unified feed without tenant leakage.
  - Admin page renders the audit tab and typechecks.
- Public interfaces:
  - New DB migration `009_audit_log.sql`.
  - New API endpoint `GET /v1/admin/audit-log?source=&entity_type=&limit=&offset=`.
  - New web DTO/hook/admin tab.
- Edge cases / failure modes:
  - Missing actor subject: fail open with deterministic system/manual fallback string.
  - Unsupported filters: fail closed with `422`.
  - Empty audit feed: return empty list with `200`.
  - Existing-domain event source unavailable due missing joins: fail closed in tests and fix query wiring.
- Rollout & monitoring:
  - Additive migration first; no destructive changes.
  - Backout by ignoring the new endpoint/table if needed.
  - Watch API errors on `/v1/admin/audit-log` and row counts for admin/document writes.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase1/test_documents_api.py -q`
  - `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase1/test_documents_api.py tests/phase3/test_invoice_lifecycle.py tests/phase4/test_admin_api.py`
  - `(cd apps/web && npm run typecheck)`

### Dependencies
- Existing `billing_events`, `document_review_events`, and `project_status_events` remain source-of-truth for those domains.
- Admin and document lifecycle gaps require the new `audit_log_events` table.

### Validation
- Seed representative data through existing APIs and confirm the audit feed returns stable source/entity labels, actor subjects, and timestamps in descending order.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `audit_repo.py` | `AdminService`, `WebhookService`, `DocumentIngestService`, `AuditService` method calls | `apps/api/src/egp_api/main.py` app state wiring | `audit_log_events`, `project_status_events`, `document_review_events`, `billing_events` |
| `audit_service.py` | `GET /v1/admin/audit-log` | `apps/api/src/egp_api/main.py` + `apps/api/src/egp_api/routes/admin.py` | read-only over merged audit sources |
| Migration `009_audit_log.sql` | N/A | migration runner / repository metadata import | `audit_log_events` |
| Admin UI audit tab | `apps/web/src/app/(app)/admin/page.tsx` | `apps/web/src/lib/api.ts` + `apps/web/src/lib/hooks.ts` | API response only |

## Plan Draft B

### Overview
Implement a single canonical `audit_log_events` table and write every new project, document, billing, review, and admin event into it directly, while keeping older per-domain event tables for backward compatibility. Serve the admin feed exclusively from this table and incrementally mirror existing domain writes into it at mutation time.

### Files to Change
- `packages/db/src/migrations/009_audit_log.sql`: add `audit_log_events`.
- `packages/db/src/egp_db/repositories/audit_repo.py`: write/list direct audit rows.
- `packages/db/src/egp_db/repositories/project_repo.py`: mirror project status writes into audit log.
- `packages/db/src/egp_db/repositories/document_repo.py`: mirror review action writes into audit log.
- `packages/db/src/egp_db/repositories/billing_repo.py`: mirror billing lifecycle writes into audit log.
- `apps/api/src/egp_api/services/admin_service.py`: write admin audit rows.
- `apps/api/src/egp_api/services/webhook_service.py`: write webhook audit rows.
- `apps/api/src/egp_api/services/document_ingest_service.py`: write document ingest audit rows.
- `apps/api/src/egp_api/services/audit_service.py`: list direct audit rows.
- `apps/api/src/egp_api/routes/admin.py`: expose audit endpoint.
- `apps/api/src/egp_api/main.py`: wire repository/service dependencies.
- `apps/web/src/lib/api.ts`: add audit DTO/fetch helper.
- `apps/web/src/lib/hooks.ts`: add `useAuditLog`.
- `apps/web/src/app/(app)/admin/page.tsx`: add tab and list UI.
- `tests/phase4/test_admin_api.py`, `tests/phase1/test_document_persistence.py`, `tests/phase3/test_invoice_lifecycle.py`: update coverage around mirrored writes.

### Implementation Steps
#### TDD sequence
1. Add failing tests asserting unified audit rows are created as a side effect of project, billing, review, document, and admin mutations.
2. Run the targeted tests and confirm failures due to missing audit writes.
3. Implement `audit_log_events` and mirror writes at each mutation site.
4. Refactor shared payload builders and serialization to reduce repetition.
5. Run fast gates, then broader regression tests around affected flows.

#### Functions and behavior
- `SqlAuditRepository.record_event(...)`: canonical persistence path for all audit entries.
- `SqlProjectRepository._insert_status_event(...)`: also write a project audit row.
- `SqlDocumentRepository._insert_review_event(...)` or equivalent: also write a review audit row.
- Billing repository event writers: also write billing audit rows as part of the same transaction.
- `DocumentIngestService.ingest_document_bytes(...)`: write document-created audit rows.
- `AdminService` and `WebhookService`: write admin audit rows.
- `AuditService.list_events(...)`: read only from `audit_log_events`.

### Test Coverage
- `tests/phase4/test_admin_api.py::test_admin_audit_log_lists_mirrored_rows`
  - Canonical audit table backs API response.
- `tests/phase1/test_document_persistence.py::test_document_review_action_writes_audit_row`
  - Review mutation mirrors into audit table.
- `tests/phase3/test_invoice_lifecycle.py::test_billing_lifecycle_writes_audit_rows`
  - Billing events mirror into audit table.
- `tests/phase4/test_admin_api.py::test_admin_mutations_write_audit_rows`
  - Admin actions persist actor and metadata.

### Decision Completeness
- Goal:
  - Establish one canonical audit table for future auditability.
- Non-goals:
  - Replacing existing domain-specific history endpoints.
  - Historical backfill.
- Success criteria:
  - Every touched mutation path writes an `audit_log_events` row.
  - Admin API serves audit entries entirely from `audit_log_events`.
- Public interfaces:
  - New DB table and API endpoint as in Draft A.
- Edge cases / failure modes:
  - Any mirror write failure should fail closed and roll back the parent mutation transaction.
  - Missing actor subject falls back to deterministic system/manual identifiers.
- Rollout & monitoring:
  - Additive schema with stronger future consistency, but more mutation-path touch points.
- Acceptance checks:
  - Same command set as Draft A plus extra repository tests for mirrored writes.

### Dependencies
- Requires touching more mutation sites in low-level repositories.

### Validation
- Verify every representative mutation creates exactly one audit row in the canonical table.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `audit_repo.py` | repository mutation helpers and `AuditService` | imports into repositories + `apps/api/src/egp_api/main.py` | `audit_log_events` |
| repository mirror writes | project/document/billing mutation methods | direct repository code paths | `audit_log_events` |
| admin audit API | `GET /v1/admin/audit-log` | `apps/api/src/egp_api/routes/admin.py` + `main.py` | `audit_log_events` |
| admin UI audit tab | admin page fetch hook | `apps/web/src/lib/api.ts` + `hooks.ts` | API response only |

## Comparative Analysis & Synthesis

### Strengths
- Draft A minimizes invasive changes by reusing existing durable event tables where they already exist.
- Draft B creates a cleaner long-term single-source audit table for all future work.

### Gaps
- Draft A needs careful query normalization so the merged feed is stable across heterogeneous source schemas.
- Draft B touches many transactional mutation paths and risks larger regressions for a single task.

### Trade-offs
- Draft A is smaller, safer, and matches the task wording about reusing `project_status_events` patterns.
- Draft B is architecturally purer but too broad for the current phase-4 slice because it duplicates existing history systems everywhere.

### Compliance
- Both drafts preserve tenant isolation and additive migrations.
- Draft A aligns better with the repo’s preference for thin API wiring and minimal, focused changes.

## Unified Execution Plan

### Overview
Implement a unified tenant-scoped audit feed that reads from existing project, billing, and review history tables, plus a new additive `audit_log_events` table for admin and document lifecycle actions that currently lack dedicated event history. Expose the feed in `GET /v1/admin/audit-log`, wire it into the admin page as a new audit tab, and keep mutation changes narrowly scoped so existing phase-1 through phase-4 behavior remains stable.

### Files to Change
- `packages/db/src/migrations/009_audit_log.sql`
  - Add `audit_log_events` with `tenant_id`, `source`, `entity_type`, `entity_id`, optional `project_id`, optional `document_id`, `actor_subject`, `event_type`, `summary`, `metadata_json`, `occurred_at`, `created_at`, and filter-friendly indexes.
- `packages/db/src/egp_db/repositories/audit_repo.py`
  - New repository with `AuditLogEventRecord`, `AuditLogPage`, `record_event`, and `list_events`.
- `packages/db/src/egp_db/repositories/__init__.py`
  - Export the new audit repository symbols/factory.
- `apps/api/src/egp_api/services/audit_service.py`
  - Thin service wrapper for pagination/filter validation.
- `apps/api/src/egp_api/services/admin_service.py`
  - Inject audit repository and append admin audit rows on successful mutations.
- `apps/api/src/egp_api/services/webhook_service.py`
  - Inject audit repository and append webhook/admin audit rows.
- `apps/api/src/egp_api/services/document_ingest_service.py`
  - Inject audit repository; write document-created audit entries only when a new document is persisted.
- `apps/api/src/egp_api/routes/admin.py`
  - Add response/request models for audit rows and `GET /v1/admin/audit-log`.
- `apps/api/src/egp_api/main.py`
  - Create the audit repository/service and pass them to dependent services.
- `apps/web/src/lib/api.ts`
  - Add audit feed DTOs, filter types, and `fetchAuditLog`.
- `apps/web/src/lib/hooks.ts`
  - Add `useAuditLog`.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Add the audit-log tab with compact filters and reverse-chronological list rendering.
- `tests/phase4/test_admin_api.py`
  - Main integration coverage for endpoint behavior and admin mutation auditing.
- `tests/phase3/test_invoice_lifecycle.py`
  - Verify billing event aggregation reaches the audit feed.
- `tests/phase1/test_documents_api.py`
  - Verify new-document ingestion produces a unified audit entry when surfaced through the admin API.

### Implementation Steps
#### TDD sequence
1. Add focused API tests in `tests/phase4/test_admin_api.py` for:
   - cross-domain feed aggregation
   - source/entity filters
   - tenant scoping
   - admin mutation audit emission
2. Add one focused document-ingest test and one billing aggregation test.
3. Run the failing test set and confirm the failure is due to the missing audit endpoint/repository.
4. Implement `009_audit_log.sql`, `audit_repo.py`, and `audit_service.py`.
5. Wire `create_app` to instantiate the audit repository/service and inject dependencies.
6. Add admin/document audit emitters after successful writes.
7. Implement the admin route and serialization.
8. Add web API types/hooks and the admin audit tab.
9. Run focused tests, `ruff`, and web typecheck/build; expand test scope if regressions appear.

#### Functions and expected behavior
- `SqlAuditRepository.record_event(...)`
  - Persist only the gaps: admin actions and document-ingest lifecycle entries. Normalize timestamps and actor fallback strings in one place.
- `SqlAuditRepository.list_events(...)`
  - Return a reverse-chronological merged page over four sources:
    - `audit_log_events`
    - `project_status_events` joined to `projects` for tenant/project metadata
    - `document_review_events`
    - `billing_events`
  - Support optional `source` and `entity_type` filters plus bounded `limit`/`offset`.
- `AuditService.list_events(...)`
  - Validate filter values, clamp pagination, and delegate to the repository.
- `AdminService.create_user/update_user/update_user_notification_preferences/update_settings(...)`
  - Write an audit row after the mutation succeeds, including actor subject, target user/settings entity, and changed fields in metadata.
- `WebhookService.create_webhook/delete_webhook(...)`
  - Write admin audit rows after successful create/delete operations.
- `DocumentIngestService.ingest_document_bytes(...)`
  - Write a `document.created` audit row only when `StoreDocumentResult.created` is `True`.
- `routes/admin.py:get_admin_audit_log(...)`
  - Require admin role, resolve tenant from auth/request, and return serialized audit entries.

### Test Coverage
- `tests/phase4/test_admin_api.py::test_admin_audit_log_returns_cross_domain_feed`
  - Includes project, billing, review, document, and admin entries.
- `tests/phase4/test_admin_api.py::test_admin_audit_log_filters_by_source_and_entity_type`
  - Returns only requested slices.
- `tests/phase4/test_admin_api.py::test_admin_audit_log_is_tenant_scoped`
  - Prevents cross-tenant leakage.
- `tests/phase4/test_admin_api.py::test_admin_mutations_append_audit_entries`
  - User, preference, settings, and webhook changes persist audit rows.
- `tests/phase1/test_documents_api.py::test_document_ingest_surfaces_audit_entry_in_admin_feed`
  - New documents appear in unified audit results.
- `tests/phase3/test_invoice_lifecycle.py::test_invoice_lifecycle_events_surface_in_admin_audit_log`
  - Existing billing events are visible through the feed.

### Decision Completeness
- Goal:
  - Deliver an operator-visible, tenant-scoped audit log that captures critical state changes and actions across the product.
- Non-goals:
  - Historical backfill for already-existing admin/document changes.
  - Export/search/reporting beyond list filters.
  - Replacing existing domain-specific history tables.
- Success criteria:
  - Admin API returns a unified feed with representative entries for all required domains.
  - Admin/document mutations create durable rows in `audit_log_events`.
  - Existing project, billing, and review history appear without duplicate tenant leakage.
  - Admin UI renders the new audit tab and passes typecheck.
- Public interfaces:
  - Migration `009_audit_log.sql`
  - `GET /v1/admin/audit-log`
  - New frontend types/hooks for audit feed
- Edge cases / failure modes:
  - Missing auth subject: fallback to `manual-operator` or `system:api` depending on entry source.
  - Invalid filter strings: `422`.
  - Empty feed or offset past end: `200` with empty `items`.
  - Audit write failure on admin/document mutations: fail closed so the mutation does not silently bypass audit.
  - Aggregated read issue from existing event tables: fail closed in tests and fix joins before merge.
- Rollout & monitoring:
  - Apply additive migration before deploying the endpoint.
  - No feature flag required; endpoint/UI can safely show an empty feed.
  - Monitor API errors and confirm new `audit_log_events` rows appear for admin/document actions.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py tests/phase3/test_invoice_lifecycle.py tests/phase1/test_documents_api.py -q`
  - `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase4/test_admin_api.py tests/phase3/test_invoice_lifecycle.py tests/phase1/test_documents_api.py`
  - `./.venv/bin/python -m compileall apps packages`
  - `(cd apps/web && npm run typecheck)`

### Dependencies
- Existing domain event tables remain authoritative for project, billing, and review history.
- New `audit_log_events` covers admin and document lifecycle gaps.

### Validation
- Seed/admin-mutate data through existing APIs, query `/v1/admin/audit-log`, and verify ordering, actor strings, filters, and tenant isolation.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `packages/db/src/egp_db/repositories/audit_repo.py` | `AuditService.list_events`, `AdminService` mutations, `WebhookService` mutations, `DocumentIngestService.ingest_document_bytes` | `apps/api/src/egp_api/main.py` creates repository and passes it into services | `audit_log_events`, reads `project_status_events`, `billing_events`, `document_review_events` |
| `apps/api/src/egp_api/services/audit_service.py` | `GET /v1/admin/audit-log` | stored at `app.state.audit_service` in `apps/api/src/egp_api/main.py` | read-only over merged audit sources |
| `apps/api/src/egp_api/routes/admin.py` audit endpoint | FastAPI admin router | `app.include_router(admin_router)` in `apps/api/src/egp_api/main.py` | N/A |
| `apps/web/src/lib/api.ts` + `apps/web/src/lib/hooks.ts` audit client | `apps/web/src/app/(app)/admin/page.tsx` | direct imports in admin page | N/A |
| Migration `packages/db/src/migrations/009_audit_log.sql` | migration runner | repo bootstrap/migration commands | `audit_log_events` |

## Implementation (2026-04-05 17:26:55 +0700)

### Goal
Implement Task 4.3 as a tenant-scoped, operator-visible audit log that aggregates existing project/billing/review histories and persists new admin/document lifecycle events.

### What Changed
- `packages/db/src/migrations/009_audit_log.sql`
  - Added additive `audit_log_events` schema for direct admin/document audit entries with tenant-scoped indexes.
- `packages/db/src/egp_db/repositories/audit_repo.py`
  - Added unified audit repository with direct-write support plus merged reads over `audit_log_events`, `project_status_events`, `billing_events`, and `document_review_events`.
- `packages/db/src/egp_db/repositories/__init__.py`
  - Exported audit repository symbols.
- `apps/api/src/egp_api/services/audit_service.py`
  - Added filter validation and pagination wrapper for the audit feed.
- `apps/api/src/egp_api/main.py`
  - Wired the audit repository/service into app state and injected it into admin, webhook, and document services.
- `apps/api/src/egp_api/routes/admin.py`
  - Added `GET /v1/admin/audit-log` plus response serialization and actor extraction for admin mutations.
- `apps/api/src/egp_api/services/admin_service.py`
  - Persisted audit entries for user creation/updates, notification preference changes, and tenant settings updates.
- `apps/api/src/egp_api/services/webhook_service.py`
  - Persisted audit entries for webhook create/delete operations.
- `apps/api/src/egp_api/routes/webhooks.py`
  - Passed actor subjects into webhook mutations.
- `apps/api/src/egp_api/services/document_ingest_service.py`
  - Persisted audit entries for newly stored documents.
- `apps/api/src/egp_api/routes/documents.py`
  - Passed actor subject into document ingest.
- `apps/web/src/lib/api.ts`
  - Added audit DTOs, fetch params, and `fetchAuditLog`.
- `apps/web/src/lib/hooks.ts`
  - Added `useAuditLog`.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Added an Audit Log tab with source/entity filters and live mutation invalidation.
- `tests/phase4/test_admin_api.py`
  - Added cross-domain audit feed and tenant-scope coverage.

### TDD Evidence
- RED command:
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q`
  - Failed with `404 Not Found` for `GET /v1/admin/audit-log`.
- GREEN command:
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q`
  - Passed with `6 passed`.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q`
  - Passed: `6 passed`
- `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py tests/phase4/test_webhooks_api.py tests/phase1/test_documents_api.py tests/phase3/test_invoice_lifecycle.py -q`
  - Passed: `29 passed`
- `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase4/test_admin_api.py tests/phase4/test_webhooks_api.py tests/phase1/test_documents_api.py tests/phase3/test_invoice_lifecycle.py`
  - Passed
- `./.venv/bin/python -m compileall apps packages`
  - Passed
- `cd apps/web && npm run typecheck`
  - Passed
- `cd apps/web && npm run lint`
  - Passed
- `cd apps/web && npm run build`
  - Passed

### Wiring Verification Evidence
- `apps/api/src/egp_api/main.py`
  - `create_audit_repository(...)` is constructed once and stored at `app.state.audit_repository`.
  - `AuditService(audit_repository)` is stored at `app.state.audit_service`.
  - `AdminService`, `WebhookService`, and `DocumentIngestService` now receive the audit repository dependency.
- `apps/api/src/egp_api/routes/admin.py`
  - `GET /v1/admin/audit-log` is registered on the existing admin router and uses `app.state.audit_service`.
- `apps/web/src/app/(app)/admin/page.tsx`
  - The new `audit` tab reads through `useAuditLog`, which calls `fetchAuditLog` in `apps/web/src/lib/api.ts`.

### Behavior Changes / Risk Notes
- Existing project status, billing, and document-review history remain source-of-truth and are read into the unified feed rather than duplicated.
- Admin and document-created entries now fail closed with the parent mutation if the direct audit write fails.
- Historical admin/document actions before migration `009_audit_log.sql` are not backfilled.

### Follow-ups / Known Gaps
- Audit feed pagination is offset-based only; no cursor or export flow yet.
- The admin UI exposes basic source/entity filtering but not free-text search.

## Review (2026-04-05 17:27:22 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: `working-tree`
- Commands Run:
  - `git status --porcelain=v1`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - targeted `git diff -- <path>` on API, DB, web, and test files
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py tests/phase4/test_webhooks_api.py tests/phase1/test_documents_api.py tests/phase3/test_invoice_lifecycle.py -q`
  - `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase4/test_admin_api.py tests/phase4/test_webhooks_api.py tests/phase1/test_documents_api.py tests/phase3/test_invoice_lifecycle.py`
  - `./.venv/bin/python -m compileall apps packages`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run lint`
  - `cd apps/web && npm run build`

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
- Assumed Task 4.3 does not require historical backfill for admin/document events that predate migration `009_audit_log.sql`.
- Assumed the generated `apps/web/next-env.d.ts` diff is acceptable because it came from the local Next.js build/typecheck flow and all frontend gates passed.

### Recommended Tests / Validation
- `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py tests/phase4/test_webhooks_api.py tests/phase1/test_documents_api.py tests/phase3/test_invoice_lifecycle.py -q`
- `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase4/test_admin_api.py tests/phase4/test_webhooks_api.py tests/phase1/test_documents_api.py tests/phase3/test_invoice_lifecycle.py`
- `cd apps/web && npm run typecheck && npm run lint && npm run build`

### Rollout Notes
- Apply migration `009_audit_log.sql` before calling `/v1/admin/audit-log` in deployed environments.
- Existing project/billing/review history reads are backward-compatible because they still use the current domain tables as source-of-truth.
