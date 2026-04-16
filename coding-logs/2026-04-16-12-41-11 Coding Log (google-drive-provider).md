## Plan Draft A

### Overview
Implement PR3 as a provider-ready Google Drive integration slice. This adds server-side OAuth start/callback support, token refresh, Google Drive upload/download adapter code, folder selection persistence, and admin UI actions while keeping runtime document-ingest cutover out of scope for PR4.

### Files to Change
- `packages/db/src/migrations/019_google_drive_storage_metadata.sql`: add folder ID and URL metadata for selected external folders.
- `packages/db/src/egp_db/repositories/admin_repo.py`: extend storage config records with provider folder metadata and persistence methods.
- `packages/db/src/egp_db/artifact_store.py`: add `GoogleDriveArtifactStore` and small Google Drive REST client helpers.
- `apps/api/src/egp_api/config.py`: add Google OAuth client ID/secret, redirect URI, and scope helpers.
- `apps/api/src/egp_api/main.py`: wire Google provider config and factory into `StorageSettingsService`.
- `apps/api/src/egp_api/services/storage_settings_service.py`: add Google OAuth start/callback, token refresh-backed test-write, and folder selection persistence.
- `apps/api/src/egp_api/routes/admin.py`: add Google Drive OAuth, callback, and folder-selection endpoints.
- `apps/web/src/lib/api.ts`: add Google Drive connect/folder APIs and DTO fields.
- `apps/web/src/app/(app)/admin/storage/page.tsx`: replace manual Google token entry with OAuth connect and folder ID/label save controls.
- `tests/phase4/test_admin_api.py`: add Google OAuth/folder/test-write coverage with fake HTTP clients.

### Implementation Steps
1. TDD sequence:
   1) Add focused failing tests for OAuth start URL, callback token exchange, folder persistence, token refresh, and Google test-write upload.
   2) Run the focused subset and confirm failures are missing routes/service/provider logic.
   3) Implement config/repository/schema fields.
   4) Implement Google OAuth/client/store helpers.
   5) Wire admin routes and update UI.
   6) Run focused tests, full admin API tests, ruff, web typecheck/build, and formal g-check review.
2. Add `StorageGoogleConfig` and `GoogleDriveClient` with explicit dependency injection so tests do not call Google.
3. Add `GoogleDriveArtifactStore` to use Drive `files.create` multipart uploads, `files.get?alt=media`, `files.delete`, and Drive web download links.
4. Persist folder ID in a dedicated DB field instead of overloading `folder_path_hint`.
5. Keep OAuth callback state tenant-scoped and signed/encrypted using the existing credential cipher pattern.

### Test Coverage
- `test_google_drive_oauth_start_returns_google_authorization_url`: validates OAuth URL parameters.
- `test_google_drive_oauth_callback_exchanges_code_and_stores_tokens`: validates callback persistence.
- `test_google_drive_folder_selection_persists_folder_metadata`: validates folder ID/label storage.
- `test_google_drive_test_write_refreshes_token_and_uploads_validation_file`: validates refresh + upload path.
- `test_google_drive_test_write_marks_error_on_upload_failure`: validates fail-closed errors.
- `test_google_drive_artifact_store_put_get_delete_download_url`: validates adapter behavior with fake client.

### Decision Completeness
- Goal: ship the Google Drive provider platform slice needed before tenant-aware storage resolution.
- Non-goals: OneDrive, PR4 runtime artifact-store cutover, provider-backed document downloads from real project rows, broad Drive scopes, arbitrary local filesystem writes.
- Success criteria: OAuth start/callback works with fake Google transport, encrypted tokens are stored, folder ID is persisted, test-write performs provider-backed upload through injected Google client, and UI exposes connect/select/validate actions.
- Public interfaces: new migration `019`; new env vars `EGP_GOOGLE_DRIVE_CLIENT_ID`, `EGP_GOOGLE_DRIVE_CLIENT_SECRET`, `EGP_GOOGLE_DRIVE_REDIRECT_URI`, optional `EGP_GOOGLE_DRIVE_SCOPES`; new `/v1/admin/storage/google-drive/*` endpoints.
- Edge cases/failure modes: missing OAuth config fails closed; invalid state fails 400/422; callback token exchange failure does not mark connected; missing refresh token prevents test-write; Google upload failure records validation error.
- Rollout/monitoring: additive migration; no live artifact routing change; audit events for OAuth connected, folder selected, validation success/failure.
- Acceptance checks: focused pytest, full `tests/phase4/test_admin_api.py`, ruff format/check, web typecheck/build.

### Dependencies
- Official Google OAuth web-server flow guidance: use `access_type=offline` for refresh tokens and validate redirect/state.
- Official Google Drive scope guidance: prefer `https://www.googleapis.com/auth/drive.file` for app-created/app-opened files.
- Official Google Drive upload guidance: `files.create` supports multipart and resumable upload; this slice uses multipart for validation/small artifacts and leaves resumable large-file upload optimization for follow-up.

### Validation
Use fake Google HTTP clients in unit/API tests to prove behavior deterministically without network calls. Verify no raw token is returned to the browser and encrypted token payloads do not contain the plaintext refresh token.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Migration `019` | migration runner | `packages/db/src/migrations` | `tenant_storage_configs.provider_folder_id`, `provider_folder_url` |
| `GoogleDriveClient` | `StorageSettingsService.handle_google_drive_callback()` and `test_write()` | `apps/api/src/egp_api/main.py` factory injection | `tenant_storage_credentials.encrypted_payload` |
| `GoogleDriveArtifactStore` | provider test-write and later PR4 storage resolver | `packages/db/src/egp_db/artifact_store.py` | N/A |
| Google OAuth routes | `/v1/admin/storage/google-drive/*` | `apps/api/src/egp_api/routes/admin.py` | `tenant_storage_configs`, `tenant_storage_credentials` |
| Storage page Google controls | `/admin/storage` | `apps/web/src/app/(app)/admin/storage/page.tsx` | consumes admin storage APIs |

## Plan Draft B

### Overview
Implement a smaller Google OAuth-only slice that starts/callbacks OAuth, stores encrypted tokens, and keeps the current manual folder/path UI. Defer Google Drive client upload and artifact adapter until PR4.

### Files to Change
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/main.py`
- `apps/api/src/egp_api/services/storage_settings_service.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/(app)/admin/storage/page.tsx`
- `tests/phase4/test_admin_api.py`

### Implementation Steps
1. Add OAuth URL/callback tests first.
2. Add config and state signing.
3. Exchange callback code and store encrypted tokens.
4. Update the page with a Google OAuth connect button.
5. Leave validation as credential-presence-only.

### Test Coverage
- OAuth start URL generation.
- OAuth callback encrypted token storage.
- Missing OAuth config fails closed.
- Invalid state rejected.

### Decision Completeness
- Goal: de-risk OAuth only.
- Non-goals: folder selection, Drive upload, artifact adapter, PR4 runtime storage.
- Success criteria: admins can complete OAuth callback in tests and see credential metadata.
- Public interfaces: OAuth env vars and two routes.
- Edge cases/failure modes: missing config and invalid state fail closed.
- Rollout/monitoring: minimal additive API/UI change, no migration.
- Acceptance checks: same local gates.

### Dependencies
- Google OAuth web-server flow docs.

### Validation
Fake token-exchange client proves no network dependency.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| OAuth routes | `/v1/admin/storage/google-drive/*` | `routes/admin.py` | `tenant_storage_credentials` |
| OAuth service logic | admin routes | `main.py` app state | `tenant_storage_credentials` |
| Google connect UI | `/admin/storage` | web storage page | N/A |

## Comparative Analysis & Synthesis

Draft A matches the requested PR3 scope: OAuth start/callback, token refresh, `GoogleDriveArtifactStore`, folder selection persistence, and validation tests. Draft B is safer and smaller but does not actually complete PR3 because it defers folder selection and provider-backed validation.

The main risk in Draft A is scope size. The mitigation is to keep runtime document storage resolution out of scope, use injected fake Google clients for deterministic tests, and implement the artifact adapter without wiring it into document ingest until PR4.

## Unified Execution Plan

### Overview
Proceed with Draft A but constrain the runtime blast radius: implement real Google provider primitives and admin controls, but do not change document ingest/download routing yet. This leaves PR4 cleanly responsible for choosing tenant storage at runtime.

### Files to Change
- `packages/db/src/migrations/019_google_drive_storage_metadata.sql`: additive folder metadata columns.
- `packages/db/src/egp_db/repositories/admin_repo.py`: folder ID/URL fields and update plumbing.
- `packages/db/src/egp_db/artifact_store.py`: `GoogleDriveClientProtocol`, `GoogleDriveArtifactStore`.
- `apps/api/src/egp_api/config.py`: Google Drive OAuth config helpers.
- `apps/api/src/egp_api/main.py`: inject Google OAuth config/provider factory into storage service.
- `apps/api/src/egp_api/services/google_drive.py`: OAuth URL/token exchange/refresh and Drive REST client.
- `apps/api/src/egp_api/services/storage_settings_service.py`: Google OAuth, folder selection, and provider test-write.
- `apps/api/src/egp_api/routes/admin.py`: Google Drive admin endpoints and response fields.
- `apps/web/src/lib/api.ts`: DTO/helper updates.
- `apps/web/src/app/(app)/admin/storage/page.tsx`: OAuth connect, folder save, and validation UX.
- `tests/phase4/test_admin_api.py`: API/service tests.
- `tests/phase4/test_google_drive_artifact_store.py`: adapter tests.

### Implementation Steps
1. Add RED tests for OAuth URL, callback token storage, folder selection, refresh/test-write, upload failure, and artifact store behavior.
2. Implement the smallest provider/config/schema changes to make RED tests pass.
3. Update the UI/API helpers after backend tests are green.
4. Run focused tests, full admin API tests, ruff format/check, web typecheck/build.
5. Run formal g-check, fix findings, create PR, wait for CI, merge, and fast-forward local `main` if the slice is clean.

### Test Coverage
- `test_google_drive_oauth_start_returns_google_authorization_url`: OAuth params and state.
- `test_google_drive_oauth_callback_exchanges_code_and_stores_tokens`: token exchange + encryption.
- `test_google_drive_oauth_callback_rejects_invalid_state`: tenant/state safety.
- `test_google_drive_folder_selection_persists_folder_metadata`: selected folder metadata.
- `test_google_drive_test_write_refreshes_token_and_uploads_validation_file`: refresh and upload.
- `test_google_drive_test_write_marks_error_on_upload_failure`: fail-closed validation error.
- `test_google_drive_artifact_store_put_get_delete_download_url`: adapter contract.

### Decision Completeness
- Goal: complete PR3 provider primitives and admin setup for Google Drive.
- Non-goals: OneDrive, tenant-aware storage resolution for document ingest, retroactive migration of stored documents, real browser Google Picker SDK, large-file resumable upload optimization.
- Success criteria: Google OAuth and Drive client behavior are tested with fakes; admin UI exposes Google OAuth/folder/validate controls; storage metadata and encrypted credentials remain tenant-scoped; all gates pass.
- Public interfaces: migration `019`; Google OAuth env vars; admin endpoints `/v1/admin/storage/google-drive/oauth/start`, `/v1/admin/storage/google-drive/oauth/callback`, `/v1/admin/storage/google-drive/folder`.
- Edge cases/failure modes: missing config, bad state, token exchange failure, missing refresh token, refresh failure, upload failure, and provider mismatch all fail closed and do not leak credentials.
- Rollout/monitoring: deploy migration first; configure OAuth env vars; watch storage audit events and validation errors.
- Acceptance checks: `pytest` focused/full, `ruff check`, `ruff format --check`, `npm run typecheck`, `npm run build`, GitHub CI.

### Dependencies
- Google OAuth web-server flow.
- Google Drive `drive.file` scope.
- Google Drive `files.create` multipart upload endpoint.

### Validation
Use fake Google HTTP/Drive clients in tests. Confirm encrypted DB payloads do not contain plaintext tokens and GET responses remain masked.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `019_google_drive_storage_metadata.sql` | migration runner | migrations directory | `tenant_storage_configs` |
| `google_drive.py` | storage service OAuth/test-write methods | imported by `main.py` / service injection | `tenant_storage_credentials` |
| `GoogleDriveArtifactStore` | provider validation and future PR4 resolver | `artifact_store.py` | N/A |
| Google Drive routes | `/v1/admin/storage/google-drive/*` | `routes/admin.py` router | storage config/credentials |
| Web storage controls | `/admin/storage` | Next route page and `lib/api.ts` | API-backed |


## Implementation Summary (2026-04-16 12:52:11 +07)

### Goal
- Implement PR3 Google Drive provider primitives: OAuth start/callback, encrypted token persistence, token refresh validation, folder selection persistence, GoogleDriveArtifactStore, admin storage UI controls, and validation tests.

### What Changed
- `apps/api/src/egp_api/config.py`: added Google Drive OAuth env helpers for client ID, client secret, redirect URI, and scopes.
- `apps/api/src/egp_api/main.py`: wires Google OAuth config and `GoogleDriveClient` into `StorageSettingsService`, and exposes `app.state.web_base_url` for browser OAuth callback redirects.
- `apps/api/src/egp_api/services/google_drive.py`: added stdlib Google OAuth/Drive REST helper with authorization URL, token exchange, refresh, upload/download/delete helpers, and scope normalization.
- `apps/api/src/egp_api/services/storage_settings_service.py`: added encrypted Google OAuth state, callback token storage, folder selection, refresh-token validation upload, audit events, and folder metadata updates.
- `apps/api/src/egp_api/routes/admin.py`: added Google Drive OAuth start/callback/folder routes, folder metadata DTO fields, and browser callback redirect behavior back to `/admin/storage`.
- `packages/db/src/migrations/019_google_drive_storage_metadata.sql`: added Google provider folder ID/URL columns and provider-folder index on `tenant_storage_configs`.
- `packages/db/src/egp_db/repositories/admin_repo.py`: added folder metadata fields to storage config records, defaults, update plumbing, and composed settings responses.
- `packages/db/src/egp_db/artifact_store.py`: added `GoogleDriveClientProtocol` and `GoogleDriveArtifactStore` for Drive-backed artifact operations.
- `apps/web/src/lib/api.ts`: added Google Drive OAuth/folder API DTOs and client helpers.
- `apps/web/src/app/(app)/admin/storage/page.tsx`: added Google Drive OAuth button, folder ID/URL controls, validation affordances, and copy that DB/status tracking remains server-side.
- `tests/phase4/test_admin_api.py`: added Google Drive OAuth, callback, browser redirect, folder selection, validation success, validation failure, and encrypted-token assertions.
- `tests/phase4/test_google_drive_artifact_store.py`: added fake-client tests for upload/get/delete/download URL behavior.

### TDD Evidence
- RED command: `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'google_drive_oauth_start_returns_google_authorization_url or google_drive_oauth_callback_exchanges_code_and_stores_tokens or google_drive_oauth_callback_rejects_invalid_state or google_drive_folder_selection_persists_folder_metadata or google_drive_test_write_refreshes_token_and_uploads_validation_file or google_drive_test_write_marks_error_on_upload_failure' tests/phase4/test_google_drive_artifact_store.py`
- RED result: failed with `ModuleNotFoundError: No module named 'egp_api.services.google_drive'` and `ImportError: cannot import name 'GoogleDriveArtifactStore' from 'egp_db.artifact_store'`.
- Intermediate RED result after partial implementation: failed with `sqlalchemy.exc.CompileError: Unconsumed column names: provider_folder_id, provider_folder_url`; fixed by attaching the new fields to `TENANT_STORAGE_CONFIGS_TABLE` instead of the legacy settings table.
- GREEN focused command: same focused pytest command, result `6 passed, 27 deselected`.
- Added redirect regression command after review gap fix: `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'google_drive_oauth_callback' tests/phase4/test_google_drive_artifact_store.py`, result `3 passed, 31 deselected`.

### Tests Run
- `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py` -> `34 passed`.
- `./.venv/bin/python -m compileall apps/api/src packages/db/src` -> passed.
- `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py` -> passed.
- `./.venv/bin/ruff format --check apps/api/src packages/db/src tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py` -> passed after formatting API/admin/test files.
- `cd apps/web && npm run typecheck` -> passed.
- `cd apps/web && npm run lint` -> passed with existing Next.js `next lint` deprecation notice.
- `cd apps/web && npm run build` -> passed with existing edge-runtime static-generation warning.

### Wiring Verification Evidence
- `create_app()` constructs `GoogleDriveOAuthConfig` from env helpers and injects it plus `GoogleDriveClient` into `StorageSettingsService`.
- `admin_router` already mounts under `/v1/admin`; new routes are registered in `apps/api/src/egp_api/routes/admin.py`.
- `StorageSettingsService` writes tenant-scoped credentials through `upsert_tenant_storage_credentials(tenant_id=..., provider='google_drive')` and tenant-scoped config through `update_tenant_storage_settings(tenant_id=...)`.
- `tenant_storage_configs.provider_folder_id` and `provider_folder_url` are present in migration `019` and in the SQLAlchemy table metadata used by sqlite test bootstrap.
- Web storage page calls shared API helpers in `apps/web/src/lib/api.ts`; no route-local fetch logic was added.

### Behavior Changes And Risk Notes
- Google OAuth callback stores encrypted OAuth token payloads and preserves an existing refresh token if Google omits one on a later consent flow.
- Browser OAuth callbacks redirect back to `/admin/storage?provider=google_drive&status=connected`; API clients still receive JSON.
- Validation for Google Drive now refreshes access tokens and uploads a small validation file to the configured folder before marking the provider connected.
- Runtime document artifact routing remains intentionally deferred to PR4; this slice prepares provider setup and validation only.
- Real deployment requires Google OAuth client env vars and a Google console redirect URI matching `/v1/admin/storage/google-drive/oauth/callback`.

### Follow-ups / Known Gaps
- PR4 must resolve per-tenant document storage in API and worker artifact flows.
- PR6 must add OneDrive OAuth/upload-session behavior.
- PR7 should polish external-provider downloads, support diagnostics, and customer-facing error states.

## Review (2026-04-16 12:52:11 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at `c3ea537`, including untracked Google Drive provider files and excluding unrelated pre-existing dirty files unless listed in status.
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `git ls-files --others --exclude-standard`; targeted `nl -ba ... | sed -n ...` reads for API routes/service/config, repository/migration/artifact store, web page/client, and tests; `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py`; `./.venv/bin/python -m compileall apps/api/src packages/db/src`; `./.venv/bin/ruff check ...`; `./.venv/bin/ruff format --check ...`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run lint`; `cd apps/web && npm run build`.

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
- Assumption: PR3 is setup/validation only; runtime tenant-aware artifact resolution remains scheduled for PR4.
- Assumption: `drive.file` scope is sufficient for app-created or user-selected folders where the app has access; broader Drive scopes are intentionally avoided unless a later Picker/provider UX requires them.
- Assumption: ID-token email parsing is display metadata only, not authentication or authorization.

### Recommended Tests / Validation
- Re-run the current local gate list before submission if any further file changes occur.
- After deploy envs exist, perform one manual Google OAuth round-trip against a real Google OAuth client and selected Drive folder.
- In PR4, add end-to-end artifact upload/download tests proving tenant storage resolution chooses Google Drive only for the configured tenant.

### Rollout Notes
- Required env vars for live Google OAuth: `EGP_GOOGLE_DRIVE_CLIENT_ID`, `EGP_GOOGLE_DRIVE_CLIENT_SECRET`, `EGP_GOOGLE_DRIVE_REDIRECT_URI`, and optionally `EGP_GOOGLE_DRIVE_SCOPES`.
- `EGP_STORAGE_CREDENTIALS_SECRET` remains required for OAuth state encryption and credential storage.
- Migration `019_google_drive_storage_metadata.sql` is additive and should be applied after `018_tenant_storage_configs_and_credentials.sql`.
- Local build output warnings observed were existing tool/runtime notices: `next lint` deprecation and edge-runtime static-generation warning.
