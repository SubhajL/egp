## Implementation Plan

### Overview
Reduce our artifact-storage infrastructure cost by letting each tenant choose a customer-owned storage target for downloaded documents. The codebase already centralizes document writes behind `ArtifactStore` and `SqlDocumentRepository`, so the practical path is to add tenant-configured cloud-drive backends for OneDrive and Google Drive. True "save directly to a customer PC/notebook folder" is not achievable from the current web/backend architecture alone; that requires a local sync agent or reliance on the customer's existing OneDrive/Google Drive desktop sync client.

### Current Codebase State
- `packages/db/src/egp_db/artifact_store.py`
  - Storage abstraction exists with `LocalArtifactStore`, `S3ArtifactStore`, and `SupabaseArtifactStore`.
- `packages/db/src/egp_db/repositories/document_repo.py`
  - `create_document_repository(...)` supports only `local`, `s3`, and `supabase`.
  - Stored document metadata keeps a `storage_key`, not a filesystem-only path, which is compatible with provider-backed keys.
- `apps/api/src/egp_api/services/document_ingest_service.py`
  - All API-side document ingestion funnels through `SqlDocumentRepository.store_document(...)`.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`
  - Worker-side document ingestion also funnels through the same repository factory.
- `apps/api/src/egp_api/routes/documents.py`
  - Download flow returns a provider-generated `download_url`; this is the right seam for provider-specific links.
- `apps/api/src/egp_api/routes/admin.py`
  - Existing tenant settings CRUD already exists and is the most natural place to hang storage settings and provider connection management.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Existing admin settings UI can host storage-provider connection and folder-selection controls.

### Recommendation
Build this in two product phases:

1. Phase 1: customer-owned cloud storage
   - Support OneDrive and Google Drive as tenant-configurable storage backends.
   - Store downloaded TOR/documents in the customer's own drive folder using delegated OAuth credentials.
   - Let customers optionally sync those folders down to their PC/notebook with the standard OneDrive/Google Drive desktop client.

2. Phase 2: true customer-local filesystem destination
   - Separate product surface.
   - Requires a local desktop/agent process on the customer device to pull artifacts from our system or receive jobs and write to a local path.

### Why Phase 1 Fits Better
- It matches the existing backend-driven scheduled crawler architecture.
- It can work unattended because the backend can upload using refresh tokens.
- It meaningfully cuts our storage bill because the canonical document copy can live in the customer's drive.
- It avoids the complexity of device enrollment, agent upgrades, offline handling, and local path permissions.

### Hard Constraint
- The current web app and backend cannot directly write files into an arbitrary path on a customer's laptop from the cloud.
- If the requirement is "save to `C:\\...` or `/Users/...` on the user's device", that is a new desktop/agent system, not just a storage-backend addition.

### External Integration Notes
- Google Drive:
  - Prefer `drive.file` plus Picker-based folder/file selection where possible, because Google recommends narrow scopes and notes that `drive.file` works with Google Picker for per-file access.
  - Refresh tokens must be stored securely for long-term access.
- OneDrive:
  - `Files.ReadWrite.AppFolder` is safer but only gives the app its own special folder.
  - If we want a visible customer-chosen folder, we should expect broader delegated permissions plus a folder picker flow. This is an inference from Microsoft's app-folder and file-picker docs plus upload-session permissions.
  - Large files should use upload sessions.

### Files To Change
- `packages/db/src/egp_db/artifact_store.py`
  - Add `GoogleDriveArtifactStore` and `OneDriveArtifactStore`.
- `packages/db/src/egp_db/repositories/document_repo.py`
  - Extend `create_document_repository(...)` or add a tenant-aware resolver that can instantiate provider-backed artifact stores per tenant.
- `apps/api/src/egp_api/services/document_ingest_service.py`
  - Inject a tenant-aware document repository or storage resolver instead of relying only on process-wide storage config.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`
  - Resolve the tenant's configured provider when the worker stores artifacts.
- `apps/api/src/egp_api/routes/admin.py`
  - Add storage-provider CRUD/connect/disconnect/select-folder endpoints or include a dedicated router if the route surface becomes large.
- `apps/api/src/egp_api/services/admin_service.py`
  - Add orchestration for tenant storage settings and audit logging.
- `apps/api/src/egp_api/main.py`
  - Wire provider services, OAuth client configuration, and new routes into app state.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Add storage settings UI, provider connection controls, folder selection, and status/error messaging.
- `apps/web/src/lib/api.ts`
  - Add storage-provider DTOs and mutation helpers.
- `apps/web/src/lib/hooks.ts`
  - Add queries/mutations for tenant storage settings and provider connection state.
- `packages/db/src/migrations/`
  - Add tenant storage configuration tables and encrypted credential/token metadata storage.
- `packages/db/src/egp_db/repositories/admin_repo.py`
  - Add read/write methods for tenant storage settings and external provider connections.

### Proposed Data Model Tasks
1. Add `tenant_storage_configs`
   - `tenant_id`
   - `provider` (`local`, `s3`, `supabase`, `google_drive`, `onedrive`)
   - `mode` (`managed`, `customer_cloud`, later `customer_agent`)
   - `is_enabled`
   - `folder_id` / `drive_id` / `site_id` as provider-specific metadata
   - `folder_name`
   - `path_hint`
   - `created_at`, `updated_at`
2. Add `tenant_storage_credentials`
   - `tenant_id`
   - `provider`
   - encrypted `access_token` or preferably only refresh-token material where appropriate
   - `refresh_token`
   - expiry metadata
   - external account identifiers
   - revocation / last validation timestamps
3. Add optional audit/history table
   - connection created
   - folder changed
   - token refresh failed
   - provider disconnected

### API Tasks
1. Add `GET /v1/admin/storage`
   - Returns tenant storage configuration, provider status, selected folder, validation status.
2. Add `POST /v1/admin/storage/provider/{provider}/connect`
   - Starts OAuth flow.
3. Add `GET /v1/admin/storage/provider/{provider}/callback`
   - Handles OAuth callback and persists tokens/metadata.
4. Add `POST /v1/admin/storage/provider/{provider}/folder`
   - Saves selected folder metadata after picker flow.
5. Add `POST /v1/admin/storage/provider/{provider}/disconnect`
   - Removes credentials or disables the integration.
6. Add `POST /v1/admin/storage/test-write`
   - Uploads a small validation artifact and reports success/failure.
7. Update document download handling
   - Ensure `download_url` generation returns a provider-backed link for customer-owned cloud storage.

### Worker/Repository Tasks
1. Replace process-global storage selection with tenant-aware storage resolution.
2. Make repository creation capable of using provider credentials fetched per tenant.
3. Preserve current storage-key convention (`tenants/{tenant_id}/projects/...`) as the logical provider key/path.
4. Add retry/refresh-token handling for provider upload failures.
5. Add provider-specific content type handling and large-file upload support.
6. Define fallback behavior:
   - strict failure and task error
   - or optional temporary managed-storage fallback if product policy allows it

### Web UI Tasks
1. Add a "Storage" section/tab in the admin page.
2. Show current mode:
   - Managed storage
   - Customer Google Drive
   - Customer OneDrive
   - later Customer local agent
3. Add provider connect/disconnect controls.
4. Add folder selection UX:
   - Google Picker or provider-approved folder selection flow
   - OneDrive picker flow or folder-input flow based on final permissions design
5. Show validation state:
   - connected
   - token expired
   - folder missing
   - test upload failed
6. Show operational guidance:
   - "To have files on your PC, sync this drive folder with the OneDrive/Google Drive desktop app."

### Security Tasks
1. Store refresh tokens encrypted at rest.
2. Keep tokens tenant-scoped and never expose them to the browser after the callback exchange.
3. Minimize requested scopes:
   - Google: prefer `drive.file` if the folder-selection UX can be built within that model.
   - OneDrive: prefer narrow delegated permissions when product UX allows it.
4. Add token refresh, revocation, and validation jobs.
5. Add audit events for connect/disconnect/folder-change operations.

### Product Decision Tasks
1. Decide canonical-copy policy:
   - customer cloud only
   - or dual-write to managed storage for backup
2. Decide failure policy:
   - block crawl success if artifact upload fails
   - or mark project updated but document unavailable
3. Decide whether one tenant can connect multiple destinations.
4. Decide whether exported Excel/download links should point to provider URLs directly or to our API as a proxy.
5. Decide whether provider setup is self-service for admins only or support-assisted.

### Tests
1. `packages/db` unit tests
   - provider store put/get/delete/download-url contract
   - key normalization and provider path handling
2. API tests
   - tenant admin authorization
   - OAuth callback state validation
   - token persistence
   - folder selection persistence
   - test-write success/failure
3. Worker tests
   - per-tenant storage resolution
   - retry on transient provider errors
   - correct error surfacing on auth expiry
4. Web tests
   - admin storage page rendering
   - connect/disconnect flows
   - validation banners and failure states

### Phase Breakdown
#### Phase 1A: architecture and schema
- migrations
- repository methods
- storage config models
- audit events

#### Phase 1B: Google Drive integration
- OAuth
- token storage
- folder selection
- upload/download URL support
- admin UI

#### Phase 1C: OneDrive integration
- Microsoft OAuth
- token storage
- folder selection
- upload session support
- admin UI

#### Phase 1D: worker cutover
- tenant-aware storage resolution
- validation and fallback rules
- rollout tooling

#### Phase 2: local agent
- desktop app or background agent
- local path selection
- secure registration with tenant
- job pull/sync protocol
- offline queueing and observability

### Open Questions
1. Do we accept customer-owned cloud storage as the primary meaning of "customer local space" for the first release?
2. Must customers browse an arbitrary visible folder, or is an app-managed provider folder acceptable initially?
3. Are we comfortable storing long-lived delegated refresh tokens for unattended scheduled runs?
4. Do we require backup retention on our side for support/debugging, or is customer cloud storage the only retained artifact copy?
5. What is the maximum artifact size we must support for initial launch?

### Sources
- Microsoft Graph OneDrive app folder docs:
  - https://learn.microsoft.com/en-us/graph/onedrive-sharepoint-appfolder
- Microsoft Graph upload session docs:
  - https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0
- Microsoft OneDrive file picker docs:
  - https://learn.microsoft.com/en-us/onedrive/developer/controls/file-pickers/?view=odsp-graph-online
- Google Drive API scopes docs:
  - https://developers.google.com/workspace/drive/api/guides/api-specific-auth

## Backlog Addendum

### Separate Settings Page Recommendation
- Use a dedicated settings subpage for external storage integrations rather than keeping the entire flow inline on the current admin page.
- Recommended route shape:
  - `apps/web/src/app/(app)/settings/storage/page.tsx`
  - or `apps/web/src/app/(app)/admin/storage/page.tsx` if you want to keep tenant-management features under admin-only navigation
- Reason:
  - connect/disconnect flows, OAuth callbacks, folder selection, validation, and future fallback/retention controls will grow beyond a simple settings form

### Clarified Persistence Boundary
- Data that stays in our PostgreSQL:
  - `projects`
  - `project_status_events`
  - `crawl_runs`
  - `crawl_tasks`
  - `documents` metadata
  - `document_diffs`
  - `tenant_settings`
  - notifications / exports / audit history
- Data that can move to customer-owned storage:
  - the binary document artifact itself
- Resulting model:
  - our DB remains the system of record for project lifecycle and tracking
  - external storage becomes the blob store for document contents
  - `documents.storage_key` continues to point at the logical provider key

### PR-Sized Execution Backlog
#### PR 1: tenant storage schema
- Add `tenant_storage_configs`
- Add `tenant_storage_credentials`
- Add repository dataclasses and CRUD methods
- Add audit event support for storage integration changes

#### PR 2: storage settings API service
- Add `StorageSettingsService` or extend `AdminService`
- Add encrypted credential persistence helpers
- Add provider status/read/update logic
- Wire services in `apps/api/src/egp_api/main.py`

#### PR 3: Google Drive provider
- Add OAuth start/callback endpoints
- Add token refresh handling
- Add `GoogleDriveArtifactStore`
- Add folder selection persistence
- Add test-write validation and tests

#### PR 4: tenant-aware storage resolution
- Refactor document repository construction to resolve backend per tenant
- Update API ingest flow
- Update worker ingest flow
- Preserve the current logical key convention
- Add failure/fallback behavior

#### PR 5: storage settings subpage
- Add dedicated web route/page
- Add navigation entry
- Add provider connect/disconnect UX
- Add folder selection UX
- Add validation/test-write UX
- Add customer guidance for desktop sync clients

#### PR 6: OneDrive provider
- Add Microsoft OAuth start/callback endpoints
- Add token refresh handling
- Add `OneDriveArtifactStore`
- Add upload-session support
- Add folder selection persistence
- Add validation and tests

#### PR 7: download and support polish
- Ensure document download endpoint returns correct provider-backed URL behavior
- Add provider failure messaging in UI
- Add support/admin diagnostics
- Add alerts for expired or revoked credentials

#### PR 8: optional fallback/dual-write
- Add policy toggle for managed backup copy
- Add retention/cleanup behavior
- Add visibility for failed external writes

### Recommended Delivery Sequence
1. PR 1
2. PR 2
3. PR 3
4. PR 4
5. PR 5
6. PR 6
7. PR 7
8. PR 8 only if product wants backup/fallback

## Implementation Summary - 2026-04-14 11:41:15 +0700

### Goal
Implement the first coherent slice of tenant-managed external storage support: persist tenant storage settings in our system, expose admin APIs for those settings, and add a dedicated `/admin/storage` subpage so external storage configuration is separated from the general admin form.

### What Changed
- `packages/db/src/migrations/017_tenant_storage_settings.sql`
  - Added `tenant_storage_settings` with tenant-scoped provider, connection status, destination metadata, fallback flag, and validation fields.
- `packages/db/src/egp_db/repositories/admin_repo.py`
  - Added `TENANT_STORAGE_SETTINGS_TABLE`, `TenantStorageSettingsRecord`, plus `get_tenant_storage_settings()` and `update_tenant_storage_settings()` with managed-storage defaults.
- `apps/api/src/egp_api/services/admin_service.py`
  - Added `get_storage_settings()` and `update_storage_settings()` and wrote admin audit events for storage-setting changes.
- `apps/api/src/egp_api/routes/admin.py`
  - Added `GET /v1/admin/storage` and `PATCH /v1/admin/storage` with tenant/admin auth patterns matching the existing admin routes.
- `apps/api/src/egp_api/services/audit_service.py`
  - Added `tenant_storage_settings` as a valid audit entity filter.
- `tests/phase4/test_admin_api.py`
  - Added storage settings API tests for default managed state and update + audit-log persistence.
- `apps/web/src/lib/api.ts`
  - Added storage-settings DTOs plus fetch/update helpers.
- `apps/web/src/lib/hooks.ts`
  - Added `useTenantStorageSettings()`.
- `apps/web/src/app/(app)/admin/storage/page.tsx`
  - Added the dedicated storage settings subpage.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Added a link from the admin page to the storage subpage.

### TDD Evidence
- Added/changed tests:
  - `test_storage_settings_default_to_managed_storage`
  - `test_storage_settings_can_be_updated_and_written_to_audit_log`
- RED command:
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'storage_settings_default_to_managed_storage or storage_settings_can_be_updated_and_written_to_audit_log'`
- RED failure reason:
  - both tests failed with `404 Not Found` because `/v1/admin/storage` did not exist yet
- GREEN command:
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'storage_settings_default_to_managed_storage or storage_settings_can_be_updated_and_written_to_audit_log'`
- GREEN result:
  - `2 passed`
- No frontend RED test was added because the repo currently has no page-level automated test harness for this route; verification for the web slice used typecheck/lint/build gates.

### Tests Run
- `./.venv/bin/ruff format apps/api/src/egp_api/routes/admin.py apps/api/src/egp_api/services/admin_service.py apps/api/src/egp_api/services/audit_service.py packages/db/src/egp_db/repositories/admin_repo.py tests/phase4/test_admin_api.py`
- `./.venv/bin/ruff check apps/api/src/egp_api/routes/admin.py apps/api/src/egp_api/services/admin_service.py apps/api/src/egp_api/services/audit_service.py packages/db/src/egp_db/repositories/admin_repo.py tests/phase4/test_admin_api.py`
- `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run lint`
- `cd apps/web && npm run build`

### Wiring Verification
- `tenant_storage_settings` migration
  - Entry point: applied by the repo migration runner / schema bootstrap
  - Registration location: `packages/db/src/migrations/017_tenant_storage_settings.sql`
  - Schema/table: `tenant_storage_settings`
- repository storage settings methods
  - Entry point: `AdminService.get_storage_settings()` and `AdminService.update_storage_settings()`
  - Registration location: `packages/db/src/egp_db/repositories/admin_repo.py`
  - Schema/table: `tenant_storage_settings`
- API storage settings endpoints
  - Entry point: `GET /v1/admin/storage`, `PATCH /v1/admin/storage`
  - Registration location: `apps/api/src/egp_api/routes/admin.py`, already included through `admin_router` in `apps/api/src/egp_api/main.py`
  - Schema/table: `tenant_storage_settings`, `audit_log_events`
- web storage settings page
  - Entry point: `/admin/storage`
  - Registration location: Next route file `apps/web/src/app/(app)/admin/storage/page.tsx`
  - Schema/table: consumes `/v1/admin/storage`
- web navigation link
  - Entry point: admin page action button
  - Registration location: `apps/web/src/app/(app)/admin/page.tsx`
  - Schema/table: N/A

### Behavior Changes and Risk Notes
- This slice does **not** change runtime document storage yet.
- Project lifecycle, runs/tasks, audit history, and document metadata remain in our PostgreSQL and continue to be the system of record.
- The new table/API stores only the tenant’s desired storage destination profile and operational status.
- The storage page explicitly communicates that real Google Drive / OneDrive OAuth and local-agent support are still follow-up slices.
- Current clear/reset behavior for text fields stores empty strings when the user clears fields from the UI; this is acceptable for this slice but could be normalized to `NULL` in a follow-up if needed.

### Follow-ups / Known Gaps
- Implement Google Drive OAuth, token storage, and provider-specific artifact store.
- Implement OneDrive OAuth, upload sessions, and provider-specific artifact store.
- Refactor document ingestion to resolve artifact storage per tenant instead of only from process-wide config.
- Add real validation/test-write flows instead of placeholder pending-setup messaging.

## Review (2026-04-14 11:49:43 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat -- ...`; targeted `git diff -- <path>`; `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'storage_settings_default_to_managed_storage or storage_settings_can_be_updated_and_written_to_audit_log'`; `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'switching_back_to_managed or reject_connected_status'`; `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py`; `./.venv/bin/ruff check apps/api/src/egp_api/routes/admin.py apps/api/src/egp_api/services/admin_service.py apps/api/src/egp_api/services/audit_service.py packages/db/src/egp_db/repositories/admin_repo.py tests/phase4/test_admin_api.py`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run build`

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
- This review covers the current working tree after follow-up fixes, not the earlier pre-fix state.
- Google Drive / OneDrive OAuth, validation callbacks, and tenant-aware runtime artifact storage cutover are intentionally out of scope for this slice.
- The new storage settings API is currently a configuration surface only; it does not yet drive live artifact uploads.

### Recommended Tests / Validation
- Add frontend page-level tests for `/admin/storage` once there is a route test harness.
- When provider OAuth is implemented, add integration tests that prove only validated callbacks can transition a tenant to `connected`.
- When tenant-aware storage cutover lands, add end-to-end tests covering document ingest -> storage provider resolution -> document download URL generation.

### Rollout Notes
- This slice is additive and fail-closed: it introduces a new table and admin routes without changing the current managed artifact storage path.
- Current runtime document storage remains on the existing managed backend until the follow-up provider cutover work is implemented.
- The review surfaced and the implementation fixed two correctness issues before closing: switching back to `managed` now clears stale provider metadata, and API callers can no longer self-mark a provider as `connected` before real validation exists.

## Implementation Summary - 2026-04-14 11:49:59 +0700

### Goal
Fix the concrete gaps surfaced by the formal `g-check` review of the storage-settings working tree.

### What Changed
- `apps/api/src/egp_api/services/admin_service.py`
  - Normalized `managed` mode updates so they fail closed: managed mode now clears provider-only metadata and rejects premature `connected` / `error` status writes from manual clients.
- `packages/db/src/egp_db/repositories/admin_repo.py`
  - Added optional-text normalization so explicit clear operations become real `NULL`s in persisted storage settings instead of leaving stale values behind.
- `apps/api/src/egp_api/routes/admin.py`
  - Added `422` translation for invalid storage-settings updates.
- `apps/web/src/app/(app)/admin/storage/page.tsx`
  - Cleared provider-specific form fields immediately when the user switches back to `managed`.
- `tests/phase4/test_admin_api.py`
  - Added regression coverage for managed-mode clearing and reserved connection statuses.

### TDD Evidence
- Added/changed tests:
  - `test_storage_settings_switching_back_to_managed_clears_provider_metadata`
  - `test_storage_settings_reject_connected_status_before_real_validation_exists`
- RED command:
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'switching_back_to_managed or reject_connected_status'`
- RED failure reason:
  - managed mode kept stale provider metadata, and the API accepted `connection_status="connected"` before real validation existed
- GREEN command:
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'switching_back_to_managed or reject_connected_status'`
- GREEN result:
  - `2 passed`

### Tests Run
- `./.venv/bin/ruff check apps/api/src/egp_api/routes/admin.py apps/api/src/egp_api/services/admin_service.py apps/api/src/egp_api/services/audit_service.py packages/db/src/egp_db/repositories/admin_repo.py tests/phase4/test_admin_api.py`
- `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run build`

### Wiring Verification Evidence
- Managed-mode normalization entry point:
  - `AdminService.update_storage_settings()` in `apps/api/src/egp_api/services/admin_service.py`
- Persistence clearing behavior:
  - `SqlAdminRepository.update_tenant_storage_settings()` in `packages/db/src/egp_db/repositories/admin_repo.py`
- Runtime route using the validation path:
  - `PATCH /v1/admin/storage` in `apps/api/src/egp_api/routes/admin.py`
- UI reset behavior:
  - provider `<select>` change handler in `apps/web/src/app/(app)/admin/storage/page.tsx`

### Behavior Changes and Risk Notes
- Storage settings now fail closed more cleanly:
  - switching back to managed storage removes stale provider metadata
  - only future validated integration flows should be allowed to mark a provider `connected`
- This keeps the current slice from accidentally encoding false “fully connected” state before OAuth/validation exists.
