## Plan Draft A

### Overview
Finish the unfinished platform layer under the external-storage initiative without pretending provider OAuth is already live. This slice adds a proper split between tenant storage configuration and tenant storage credentials, encrypts stored provider secrets, adds explicit connect/disconnect/test-write API actions, and upgrades the `/admin/storage` page to drive those actions.

### Files to Change
- `packages/db/src/migrations/018_tenant_storage_configs_and_credentials.sql`: additive schema for `tenant_storage_configs` and `tenant_storage_credentials`, with backfill from the already-landed `tenant_storage_settings` table.
- `packages/db/src/egp_db/repositories/admin_repo.py`: new config/credential tables, dataclasses, CRUD helpers, and summary readers that replace direct use of `tenant_storage_settings`.
- `apps/api/src/egp_api/config.py`: env helper for the storage-credential encryption secret.
- `apps/api/src/egp_api/services/storage_credentials.py`: encrypt/decrypt provider credential payloads using a repo-standard secret-derived Fernet key.
- `apps/api/src/egp_api/services/storage_settings_service.py`: tenant-scoped storage config, connect/disconnect, masked credential summary, and configuration test-write logic.
- `apps/api/src/egp_api/routes/admin.py`: add storage connect/disconnect/test-write endpoints and return richer storage integration summaries.
- `apps/api/src/egp_api/services/audit_service.py`: include new audit entity type if needed.
- `apps/api/src/egp_api/main.py`: wire `StorageSettingsService` into app state.
- `apps/web/src/lib/api.ts`: richer storage DTOs plus connect/disconnect/test-write helpers.
- `apps/web/src/lib/hooks.ts`: storage settings hook updates.
- `apps/web/src/app/(app)/admin/storage/page.tsx`: connect/disconnect/test-write UX, masked credential state, validation feedback.
- `tests/phase4/test_admin_api.py`: API/service regressions for config split, encrypted credential storage, connect/disconnect, and test-write behavior.

### Implementation Steps
1. TDD sequence:
   1) Add failing admin API tests for masked credential summaries, encrypted storage, disconnect clearing, and test-write status updates.
   2) Run the focused `tests/phase4/test_admin_api.py` subset and confirm failures are due to missing schema/service/routes.
   3) Implement additive schema and repository helpers.
   4) Implement encryption helper and storage settings service.
   5) Wire routes, then update the web page and client helpers.
   6) Run focused API tests, then broader API/web gates.
2. Add `tenant_storage_configs` for non-secret destination/configuration state and `tenant_storage_credentials` for encrypted provider secrets.
3. Backfill the existing `tenant_storage_settings` rows into `tenant_storage_configs` so the migration is safe on current production/main.
4. Implement `StorageCredentialCipher` with a config secret from env, failing closed if a caller attempts credential mutation without a configured secret.
5. Introduce `StorageSettingsService` so storage integration logic is not piled into `AdminService`.
6. Add API actions:
   - `GET /v1/admin/storage`
   - `PATCH /v1/admin/storage`
   - `POST /v1/admin/storage/connect`
   - `POST /v1/admin/storage/disconnect`
   - `POST /v1/admin/storage/test-write`
7. Keep `test-write` honest for this slice: validate config + encrypted credentials presence and update status/last validation fields, but do not claim a real remote provider upload happened.
8. Update `/admin/storage` to separate:
   - destination config
   - credential connection
   - validation/disconnect actions

### Test Coverage
- `test_storage_settings_default_to_managed_storage`
  - default config remains managed and credential-free.
- `test_storage_connect_stores_encrypted_credentials_and_masks_response`
  - secrets are encrypted at rest and not returned raw.
- `test_storage_disconnect_clears_credentials_and_marks_disconnected`
  - provider disconnect removes secrets and resets state.
- `test_storage_test_write_marks_pending_config_as_connected_when_inputs_complete`
  - server-side validation can transition to connected.
- `test_storage_test_write_marks_error_when_credentials_missing`
  - incomplete setup fails closed and records validation error.
- `test_storage_settings_switching_back_to_managed_clears_provider_metadata`
  - managed mode continues clearing provider fields.

### Decision Completeness
- Goal:
  - finish the next platform slice for external storage by adding config/credential separation, encrypted secret storage, and real storage admin actions.
- Non-goals:
  - Google OAuth callbacks
  - Microsoft OAuth
  - runtime document storage cutover
  - provider-backed download URLs
- Success criteria:
  - schema is additive and backfills previous storage settings rows
  - credentials are encrypted at rest and never exposed via GET responses
  - admins can connect/disconnect/test-write from `/admin/storage`
  - focused API tests and web gates pass
- Public interfaces:
  - new migration `018`
  - new env var for storage credential secret
  - new admin endpoints for connect/disconnect/test-write
- Edge cases / failure modes:
  - no encryption secret configured -> fail closed on connect
  - provider config incomplete -> test-write sets error, not connected
  - disconnect -> credentials removed and state reset
  - existing tenants with `tenant_storage_settings` rows -> backfill migration preserves visible state
- Rollout & monitoring:
  - additive migration first
  - no runtime artifact storage change yet
  - watch audit events and validation-error fields
- Acceptance checks:
  - `./.venv/bin/ruff check ...`
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run build`

### Dependencies
- Existing admin auth and audit infrastructure
- `python-jose[cryptography]` transitively bringing `cryptography`
- current `/admin/storage` page and merged migration `017`

### Validation
- Prove DB rows store encrypted credential payloads rather than raw tokens.
- Prove GET responses return `has_credentials` and metadata only, not decrypted secrets.
- Prove test-write can set `connected` only through server-side validation logic.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `018_tenant_storage_configs_and_credentials.sql` | migration runner / bootstrap | `packages/db/src/migrations/018_tenant_storage_configs_and_credentials.sql` | `tenant_storage_configs`, `tenant_storage_credentials` |
| `StorageCredentialCipher` | `StorageSettingsService.connect_provider()` | imported into `apps/api/src/egp_api/services/storage_settings_service.py` | `tenant_storage_credentials.encrypted_payload` |
| `StorageSettingsService` | admin storage routes | `apps/api/src/egp_api/main.py` app state | `tenant_storage_configs`, `tenant_storage_credentials`, `audit_log_events` |
| storage connect/disconnect/test-write routes | `/v1/admin/storage/*` | `apps/api/src/egp_api/routes/admin.py` | same as above |
| `/admin/storage` UI actions | page form/buttons | `apps/web/src/app/(app)/admin/storage/page.tsx` | consumes `/v1/admin/storage*` |

## Plan Draft B

### Overview
Keep the current `tenant_storage_settings` table as the single source of config state for now and add only a separate encrypted `tenant_storage_credentials` table plus connect/disconnect/test-write APIs. This minimizes schema churn and avoids immediate read-path refactoring.

### Files to Change
- `packages/db/src/migrations/018_tenant_storage_credentials.sql`
- `packages/db/src/egp_db/repositories/admin_repo.py`
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/services/storage_credentials.py`
- `apps/api/src/egp_api/services/storage_settings_service.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/api/src/egp_api/main.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/app/(app)/admin/storage/page.tsx`
- `tests/phase4/test_admin_api.py`

### Implementation Steps
1. Add only a credentials table and keep `tenant_storage_settings` for config state.
2. Encrypt credential blobs and expose only masked summaries.
3. Add connect/disconnect/test-write service and routes.
4. Upgrade the storage page with explicit credential actions.

### Test Coverage
- credential encryption at rest
- masked GET responses
- disconnect clears credential row
- test-write updates validation state using current settings row

### Decision Completeness
- Goal:
  - deliver connect/disconnect/test-write and encrypted credentials fast.
- Non-goals:
  - config-table split
  - provider OAuth
  - runtime storage cutover
- Success criteria:
  - encrypted secrets and working admin actions
  - no regression in current storage settings page
- Public interfaces:
  - one new migration
  - one new env var
  - three new endpoints
- Edge cases / failure modes:
  - same as Draft A, but relies on old merged settings table
- Rollout & monitoring:
  - simpler rollout, lower schema risk
- Acceptance checks:
  - same as Draft A

### Dependencies
- Existing `tenant_storage_settings` table from migration `017`

### Validation
- same as Draft A, minus config-table split verification

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `018_tenant_storage_credentials.sql` | migration runner / bootstrap | new migration | `tenant_storage_credentials` |
| `StorageCredentialCipher` | storage connect/disconnect | `storage_settings_service.py` | `tenant_storage_credentials` |
| `StorageSettingsService` | admin storage routes | `main.py` app state | `tenant_storage_settings`, `tenant_storage_credentials` |
| `/admin/storage` UI actions | page buttons/forms | Next route page | `/v1/admin/storage*` |

## Comparative Analysis & Synthesis

### Strengths
- Draft A fixes the original planning gap directly by introducing the intended config/credential split.
- Draft B is smaller and lower-risk in the short term.

### Gaps
- Draft A is a larger refactor because it replaces the current read path after `017`.
- Draft B leaves the schema in a halfway state and makes the future PR1 cleanup harder.

### Trade-offs
- Draft A costs one extra migration/backfill step now, but it aligns better with the intended architecture and avoids carrying forward a provisional table design.
- Draft B ships faster but preserves technical debt from the previously merged partial slice.

### Compliance Check
- Both drafts keep runtime storage behavior unchanged and stay within PR1/PR2/PR5 territory.
- Draft A better matches the user’s stated PR breakdown and the repo’s preference for explicit schema/repository contracts.

## Unified Execution Plan

### Overview
Implement the next platform slice by replacing the provisional single-table storage state with the intended `tenant_storage_configs` + `tenant_storage_credentials` model, adding encrypted credential handling, and wiring explicit connect/disconnect/test-write admin actions into the dedicated storage subpage. Keep this slice honest by validating configuration locally and not claiming real provider OAuth or live remote uploads yet.

### Files to Change
- `packages/db/src/migrations/018_tenant_storage_configs_and_credentials.sql`
- `packages/db/src/egp_db/repositories/admin_repo.py`
- `apps/api/src/egp_api/config.py`
- `apps/api/src/egp_api/services/storage_credentials.py`
- `apps/api/src/egp_api/services/storage_settings_service.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/api/src/egp_api/services/audit_service.py`
- `apps/api/src/egp_api/main.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/app/(app)/admin/storage/page.tsx`
- `tests/phase4/test_admin_api.py`

### Implementation Steps
1. Tests first:
   1) add failing API tests for encrypted credential storage, masked GET responses, disconnect behavior, and test-write validation
   2) run the focused test subset and confirm failure on missing routes/schema/service
   3) implement schema/repository/service/routes
   4) update the web page and helpers
   5) run focused API tests, then full admin API and web gates
2. Add migration `018` with:
   - `tenant_storage_configs`
   - `tenant_storage_credentials`
   - backfill from `tenant_storage_settings`
3. Update `admin_repo.py` to:
   - read/write config rows from `tenant_storage_configs`
   - read/write encrypted credential rows from `tenant_storage_credentials`
   - return an integration summary that includes `has_credentials`
4. Add `get_storage_credentials_secret()` to API config.
5. Implement `StorageCredentialCipher` using a secret-derived Fernet key and JSON payload encryption/decryption.
6. Add `StorageSettingsService` with methods:
   - `get_integration()`
   - `update_config()`
   - `connect_provider()`
   - `disconnect_provider()`
   - `test_write()`
7. Wire service in `main.py` and update admin routes to use it.
8. Upgrade `/admin/storage` with:
   - destination config save
   - credential connect/disconnect form
   - validation/test-write action
   - masked credential/connection status messaging

### Test Coverage
- `test_storage_settings_default_to_managed_storage`
  - default managed summary with no credentials.
- `test_storage_connect_stores_encrypted_credentials_and_masks_response`
  - encrypted credential row and masked API response.
- `test_storage_disconnect_clears_credentials_and_marks_disconnected`
  - disconnect removes secret material and resets state.
- `test_storage_test_write_marks_pending_config_as_connected_when_inputs_complete`
  - server-side validation can mark the integration connected.
- `test_storage_test_write_marks_error_when_credentials_missing`
  - missing secrets fail closed and set validation error.
- `test_storage_settings_switching_back_to_managed_clears_provider_metadata`
  - managed-mode clearing remains correct.

### Decision Completeness
- Goal:
  - finish the next mergeable platform slice for PR1/PR2/PR5.
- Non-goals:
  - Google OAuth callbacks
  - OneDrive
  - runtime per-tenant artifact store selection
  - provider-backed downloads
- Success criteria:
  - intended config/credential split is live
  - secrets are encrypted at rest
  - admins can connect/disconnect/test-write from `/admin/storage`
  - no raw credentials are exposed via API
  - local + GitHub gates pass
- Public interfaces:
  - migration `018`
  - env var for storage credential secret
  - new POST admin storage actions
- Edge cases / failure modes:
  - missing encryption secret -> `422` or `500` fail closed during connect
  - incomplete config or missing credentials -> test-write returns error and keeps integration out of connected state
  - disconnect -> credentials deleted, config retained or reset depending on provider
  - legacy row exists in `tenant_storage_settings` -> backfilled into new config table
- Rollout & monitoring:
  - additive migration
  - no runtime storage behavior change
  - audit every connect/disconnect/test-write
  - watch validation failures
- Acceptance checks:
  - `./.venv/bin/ruff check apps/api/src/egp_api/routes/admin.py apps/api/src/egp_api/services/admin_service.py apps/api/src/egp_api/services/audit_service.py apps/api/src/egp_api/services/storage_credentials.py apps/api/src/egp_api/services/storage_settings_service.py apps/api/src/egp_api/config.py packages/db/src/egp_db/repositories/admin_repo.py tests/phase4/test_admin_api.py`
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run build`

### Dependencies
- Existing merged storage settings slice (`017`)
- `cryptography` availability via existing API dependencies
- admin auth/audit infrastructure

### Validation
- inspect DB rows to confirm encrypted credential payloads are not plaintext
- confirm GET `/v1/admin/storage` returns `has_credentials` and summary metadata only
- confirm POST `/v1/admin/storage/test-write` controls the only supported path to `connected`

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| migration `018_tenant_storage_configs_and_credentials.sql` | migration runner / bootstrap | `packages/db/src/migrations/018_tenant_storage_configs_and_credentials.sql` | `tenant_storage_configs`, `tenant_storage_credentials` |
| `StorageCredentialCipher` | `StorageSettingsService.connect_provider()` | `apps/api/src/egp_api/services/storage_credentials.py` | `tenant_storage_credentials.encrypted_payload` |
| `StorageSettingsService` | admin storage routes | `apps/api/src/egp_api/main.py` app state | `tenant_storage_configs`, `tenant_storage_credentials`, `audit_log_events` |
| admin storage POST actions | `/v1/admin/storage/connect`, `/disconnect`, `/test-write` | `apps/api/src/egp_api/routes/admin.py` | same as above |
| `/admin/storage` UI | page actions/buttons | `apps/web/src/app/(app)/admin/storage/page.tsx` | consumes `/v1/admin/storage*` |


## Implementation (2026-04-14 12:19:45 +07) - storage platform credentials/validation

### Goal
Finish the next PR1/PR2/PR5 slice by adding encrypted tenant storage credentials, explicit connect/disconnect/test-write admin actions, and a more functional `/admin/storage` page without pretending provider OAuth is already live.

### What Changed
- `packages/db/src/migrations/018_tenant_storage_configs_and_credentials.sql`
  - Added `tenant_storage_configs` and `tenant_storage_credentials` with additive backfill from `tenant_storage_settings`.
- `packages/db/src/egp_db/repositories/admin_repo.py`
  - Added split config/credential table models and CRUD helpers, plus combined storage-setting summaries that expose masked credential metadata only.
- `apps/api/src/egp_api/config.py`
  - Added `get_storage_credentials_secret()` for the tenant storage credential secret.
- `apps/api/src/egp_api/services/storage_credentials.py`
  - Added Fernet-based encryption/decryption for stored credential payloads.
- `apps/api/src/egp_api/services/storage_settings_service.py`
  - Added tenant-scoped storage config updates, credential connect/disconnect, validation/test-write flow, audit recording, provider mismatch protection, and fail-closed handling when the secret is not configured.
- `apps/api/src/egp_api/main.py`
  - Wired `StorageSettingsService` onto app state and resolved the credential secret without falling back to an insecure static key.
- `apps/api/src/egp_api/routes/admin.py`
  - Extended storage response payloads and added `POST /v1/admin/storage/connect`, `POST /v1/admin/storage/disconnect`, and `POST /v1/admin/storage/test-write`.
- `apps/web/src/lib/api.ts`
  - Added richer storage DTOs and client helpers for connect/disconnect/test-write.
- `apps/web/src/app/(app)/admin/storage/page.tsx`
  - Split destination configuration from credential actions and validation, surfaced masked credential status, and kept the page honest about OAuth/runtime-upload scope.
- `tests/phase4/test_admin_api.py`
  - Added coverage for encrypted credential storage, disconnect behavior, validation success/failure, and provider-mismatch protection.

### TDD Evidence
- RED command:
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'storage_connect_stores_encrypted_credentials_and_masks_response or storage_disconnect_clears_credentials_and_marks_disconnected or storage_test_write_marks_pending_config_as_connected_when_inputs_complete or storage_test_write_marks_error_when_credentials_missing'`
  - Failure reason: `create_app()` did not accept `storage_credentials_secret`, proving the app/config/service wiring was still missing.
- GREEN command:
  - `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py -k 'storage_disconnect_rejects_provider_mismatch or storage_connect_stores_encrypted_credentials_and_masks_response or storage_disconnect_clears_credentials_and_marks_disconnected or storage_test_write_marks_pending_config_as_connected_when_inputs_complete or storage_test_write_marks_error_when_credentials_missing'`
  - Result: `5 passed, 21 deselected`.

### Tests Run
- `./.venv/bin/python -m compileall apps/api/src packages/db/src`
- `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase4/test_admin_api.py`
- `./.venv/bin/ruff format --check apps/api/src packages/db/src tests/phase4/test_admin_api.py`
- `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py`
- `cd apps/web && npm run lint`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run build`

### Wiring Verification Evidence
- `apps/api/src/egp_api/main.py`
  - `create_app(...)` now accepts `storage_credentials_secret` and registers `app.state.storage_settings_service`.
- `apps/api/src/egp_api/routes/admin.py`
  - `/v1/admin/storage`, `/v1/admin/storage/connect`, `/v1/admin/storage/disconnect`, and `/v1/admin/storage/test-write` all resolve the tenant through the request layer and call `StorageSettingsService`.
- `apps/web/src/app/(app)/admin/storage/page.tsx`
  - The storage page calls `updateTenantStorageSettings`, `connectTenantStorage`, `disconnectTenantStorage`, and `testTenantStorageWrite` through the shared client layer.
- `packages/db/src/migrations/018_tenant_storage_configs_and_credentials.sql`
  - Runtime schema now includes `tenant_storage_configs` and `tenant_storage_credentials` while leaving the earlier table in place for additive rollout safety.

### Behavior Changes / Risk Notes
- Credential payloads are encrypted at rest and never returned raw from the API.
- External storage validation still remains local/server-side for this slice; it validates config plus decryptable credentials, not a live provider upload.
- Missing storage-credential secret now fails closed for connect/validation operations instead of silently using an insecure default key.
- Disconnect now rejects provider mismatches instead of silently mutating the configured provider.

### Follow-ups / Known Gaps
- Real Google Drive OAuth, token refresh, and folder picker flows are not implemented yet.
- Runtime document ingest still uses the process-wide artifact store; per-tenant provider-backed storage resolution remains for the next slice.
- OneDrive provider support and local-agent integration remain future work.

## Review (2026-04-14 12:19:45 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only -- ...`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat -- ...`; targeted `git diff -- ...`; `./.venv/bin/ruff check apps/api/src packages/db/src tests/phase4/test_admin_api.py`; `./.venv/bin/ruff format --check apps/api/src packages/db/src tests/phase4/test_admin_api.py`; `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run build`

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
- This slice intentionally stops at encrypted credential handling plus server-side validation and does not claim live provider OAuth or provider-backed uploads yet.
- Production/staging environments that want to use connect/test-write must set `EGP_STORAGE_CREDENTIALS_SECRET` or reuse `EGP_JWT_SECRET`.

### Recommended Tests / Validation
- Apply migration `018` on a real Postgres environment and verify backfilled rows in `tenant_storage_configs` for tenants that already used `tenant_storage_settings`.
- In the next slice, add integration tests around real OAuth callbacks and provider-specific test-write behavior.

### Rollout Notes
- Rollout remains additive: the new tables can be created before any runtime storage cutover.
- Support should watch audit events `tenant.storage_credentials_connected`, `tenant.storage_credentials_disconnected`, `tenant.storage_validation_succeeded`, and `tenant.storage_validation_failed` while operators start using the new page.
