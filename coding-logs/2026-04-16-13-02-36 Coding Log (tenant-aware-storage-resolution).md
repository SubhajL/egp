# Coding Log: tenant-aware-storage-resolution

## Plan Draft A: Shared Resolver With Provider-Prefixed Storage Keys

### Overview
Implement PR4 by adding a shared tenant-aware artifact-store resolver that both API and worker code can use before storing document bytes. Existing managed/local/S3/Supabase storage remains the default, while connected Google Drive tenants store new artifacts in Google Drive and keep a provider-prefixed `storage_key` so downloads can dispatch to the right backend.

### Files To Change
- `packages/db/src/egp_db/storage_credentials.py`: move shared credential encryption/decryption into the shared package so API and worker can both decrypt tenant storage credentials without importing each other.
- `apps/api/src/egp_api/services/storage_credentials.py`: keep a compatibility re-export for existing API imports.
- `packages/db/src/egp_db/google_drive.py`: move Google Drive OAuth/client primitives into the shared package for API and worker runtime use.
- `apps/api/src/egp_api/services/google_drive.py`: keep a compatibility re-export for existing API imports.
- `packages/db/src/egp_db/tenant_storage_resolver.py`: add `TenantArtifactStoreResolver`, provider-key helpers, and fail-closed/fallback decisions.
- `packages/db/src/egp_db/repositories/document_repo.py`: allow `SqlDocumentRepository` to resolve artifact store per tenant for writes and by provider-prefixed storage keys for downloads.
- `apps/api/src/egp_api/main.py`: wire the resolver using admin repository, credential cipher, Google Drive config/client, and the process-managed artifact store.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`: build the same resolver for worker document ingest when a tenant config exists.
- `apps/worker/src/egp_worker/browser_downloads.py` and `apps/worker/src/egp_worker/workflows/discover.py`: pass storage resolver prerequisites through live downloaded-document ingest.
- `apps/worker/src/egp_worker/main.py`: pass optional payload/env values into worker document ingest.
- `tests/phase4/test_tenant_storage_resolver.py`: unit-test resolver decisions, token refresh, fallback, and provider-key parsing.
- `tests/phase4/test_admin_api.py` or `tests/phase1/test_document_infrastructure.py`: integration-test API-side document ingest routes to Google Drive.
- `tests/phase1/test_document_infrastructure.py`: integration-test worker-side document ingest routes to Google Drive.

### Implementation Steps
1. TDD sequence: add resolver/API/worker tests first; run them and confirm they fail because tenant resolver symbols and wiring are missing.
2. Move/re-export shared Google Drive and credential helpers with no behavior change; run existing PR3 tests to prevent regression.
3. Add `TenantArtifactStoreResolver.resolve_for_write()` and `resolve_for_storage_key()`; Google Drive refreshes tokens, builds `GoogleDriveArtifactStore`, updates encrypted credentials, and returns provider metadata.
4. Refactor document repository storage calls to use a resolved artifact store and encode new external keys as `google_drive:<file-id>`.
5. Wire API `create_app()` by creating the admin repository before document repository, building one managed artifact store, and passing the resolver to the document repository.
6. Wire worker document ingest by building an admin repository and resolver from the same DB URL plus env/payload credential settings.
7. Run scoped tests and quality gates, then run formal `g-check`.

### Function / Class Outline
- `StorageCredentialCipher`: shared existing implementation; encrypts/decrypts credential payloads from a tenant-scoped secret.
- `GoogleDriveClient`, `GoogleDriveOAuthConfig`: shared existing implementation; handles refresh/upload/download primitives.
- `ResolvedArtifactStore`: wraps provider name and `ArtifactStore`, and encodes/decodes provider-prefixed storage keys.
- `TenantArtifactStoreResolver.resolve_for_write(tenant_id)`: selects managed storage or Google Drive based on tenant config, status, credentials, folder ID, and fallback flag.
- `TenantArtifactStoreResolver.resolve_for_storage_key(tenant_id, storage_key)`: selects the backend for downloads; unprefixed keys remain managed, `google_drive:` keys use Google credentials.
- `create_artifact_store(...)`: builds the current process-managed local/S3/Supabase store without creating a repository.
- `SqlDocumentRepository._resolve_artifact_store_for_write(...)`: chooses tenant-specific storage before upload.
- `SqlDocumentRepository._resolve_artifact_store_for_storage_key(...)`: chooses storage for download URL based on stored key prefix.
- `ingest_document_artifact(...)`: worker entry point builds tenant resolver when repository is not injected.

### Test Coverage
- `test_resolver_uses_google_drive_for_connected_tenant`: refreshes token and uploads to folder.
- `test_resolver_falls_back_to_managed_when_enabled`: unsupported/misconfigured external config uses managed store.
- `test_resolver_fails_closed_without_credentials`: connected external provider missing secrets errors.
- `test_document_repository_prefixes_google_drive_storage_key`: external write stores `google_drive:<id>`.
- `test_api_document_ingest_uses_tenant_google_drive_storage`: API route uploads to fake Google client.
- `test_worker_document_ingest_uses_tenant_google_drive_storage`: worker route uploads to fake Google client.
- `test_download_url_dispatches_prefixed_google_drive_key`: download uses Google URL for prefixed key.
- Existing document infrastructure tests: managed/local/Supabase behavior unchanged.

### Decision Completeness
- Goal: runtime document artifact storage resolves per tenant in API and worker flows.
- Non-goals: OneDrive provider runtime support, Google Picker UX, provider migration/backfill for old documents, dual-write backup copies.
- Success criteria: connected Google Drive tenants store new documents via Google fake/client in API and worker tests; managed tenants still store locally/S3/Supabase; CI gates pass.
- Public interfaces: no new HTTP endpoint; no DB migration; new optional worker payload/env dependencies: `EGP_STORAGE_CREDENTIALS_SECRET`, `EGP_GOOGLE_DRIVE_CLIENT_ID`, `EGP_GOOGLE_DRIVE_CLIENT_SECRET`, `EGP_GOOGLE_DRIVE_REDIRECT_URI`, `EGP_GOOGLE_DRIVE_SCOPES`.
- Edge cases / failure modes: missing Google credentials fail closed unless `managed_fallback_enabled` is true; unprefixed old storage keys resolve to managed storage; unsupported providers fail closed unless fallback is enabled; refresh failure fails closed.
- Rollout & monitoring: deploy after PR3 migration/envs; watch document ingest failures and `tenant.storage_validation_*` audit state; rollback by disabling tenant external provider or enabling managed fallback.
- Acceptance checks: targeted pytest for phase1/phase4 document/storage tests, compileall API/worker/packages, ruff check/format.

### Dependencies
- PR3 Google Drive provider merged.
- Tenant storage config/credentials tables from migrations 018/019.
- Live Google tenants need OAuth credentials and encrypted refresh tokens.

### Validation
- Run failing tests before implementation.
- Run targeted Python tests after implementation.
- Run compileall and ruff gates.
- Run `g-check` before commit.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `TenantArtifactStoreResolver` | `SqlDocumentRepository.store_document()` / `get_download_url()` | passed from API/worker repository construction | `tenant_storage_configs`, `tenant_storage_credentials` |
| `create_artifact_store()` | API/worker repository factories | `document_repo.py` factory and API/worker setup | N/A |
| API tenant resolver | `/v1/documents/ingest` and `/v1/documents/{id}/download` | `apps/api/src/egp_api/main.py:create_app()` | `documents.storage_key` |
| Worker tenant resolver | `document_ingest` command and live discover downloaded docs | `apps/worker/src/egp_worker/workflows/document_ingest.py` | `documents.storage_key` |
| Provider-prefixed storage key | document writes/downloads | `SqlDocumentRepository` | `documents.storage_key` |

### Cross-Language Schema Verification
- Python document metadata uses table `documents` with `tenant_id`, `project_id`, `storage_key` in `packages/db/src/egp_db/repositories/document_repo.py`.
- Storage config uses `tenant_storage_configs` and credentials use `tenant_storage_credentials` in `packages/db/src/egp_db/repositories/admin_repo.py`.
- Worker and API both use the Python repositories; no TypeScript schema consumer needs update.

### Decision-Complete Checklist
- No open implementation decision remains.
- No new DB migration or HTTP endpoint is required.
- Every runtime behavior change has tests listed.
- Validation commands are scoped and concrete.
- Wiring table covers new resolver and both runtime entry points.

## Plan Draft B: Service-Level Repository Swapping Without Provider-Prefixed Keys

### Overview
Implement tenant-aware writes in API and worker by creating a tenant-specific `SqlDocumentRepository` for each document ingest call. The repository would keep the current `storage_key` semantics, with Google Drive storing raw file IDs and downloads deferred to PR7.

### Files To Change
- `apps/api/src/egp_api/services/document_ingest_service.py`: resolve tenant config before each `store_document()` and call a tenant-specific repository.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`: build a tenant-specific repository for each worker ingest call.
- `packages/db/src/egp_db/repositories/document_repo.py`: minimally expose artifact-store construction for Google Drive.
- API/worker tests for Google Drive writes only.

### Implementation Steps
1. TDD sequence: write API and worker ingest tests expecting fake Google upload.
2. Add helper to build a repository from tenant storage config.
3. Change API service and worker workflow to call the helper per ingest.
4. Leave download URL behavior unchanged for PR7.
5. Run tests and gates.

### Function / Class Outline
- `build_document_repository_for_tenant(...)`: returns a repository with a provider-specific artifact store.
- `DocumentIngestService._repository_for_tenant(...)`: chooses tenant repository for API writes.
- `ingest_document_artifact(...)`: chooses tenant repository for worker writes.

### Test Coverage
- `test_api_document_ingest_uses_google_repo`: API upload uses fake Google client.
- `test_worker_document_ingest_uses_google_repo`: worker upload uses fake Google client.
- Existing local/Supabase tests: unchanged.

### Decision Completeness
- Goal: tenant-aware writes only.
- Non-goals: provider-aware downloads, old/new key disambiguation, OneDrive, fallback/dual-write.
- Success criteria: new document writes use Google for connected tenants.
- Public interfaces: no new HTTP endpoints or migrations.
- Edge cases / failure modes: missing credentials fail closed; old documents use current process-global download behavior.
- Rollout & monitoring: same as Draft A but higher download risk.
- Acceptance checks: targeted tests and gates.

### Dependencies
- PR3 merged.
- Existing tenant storage tables.

### Validation
- TDD tests plus compile/ruff.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| tenant repository helper | API/worker ingest calls | service/workflow functions | `tenant_storage_configs`, `tenant_storage_credentials` |
| Google Drive artifact store | tenant repository helper | direct helper construction | `documents.storage_key` |

### Cross-Language Schema Verification
- Same Python-only repository schema as Draft A.

### Decision-Complete Checklist
- Open risk remains: downloads for Google Drive-created docs are deferred and may be broken until PR7.

## Comparative Analysis & Synthesis
Draft A is more complete for PR4 because it changes the repository runtime selection once, covers both writes and downloads for newly prefixed external keys, and protects old unprefixed documents by routing them to managed storage. It requires slightly more shared infrastructure, but that infrastructure keeps API and worker independent and prevents duplicated tenant-resolution logic.

Draft B is smaller but under-specifies download behavior and risks producing Google Drive `storage_key` values that cannot be safely distinguished from local/S3/Supabase keys later. That would push data-model ambiguity into PR7. Draft A follows the repo’s tenant-isolation guidance more rigorously because the shared resolver always reads config and credentials by `tenant_id`.

The unified plan uses Draft A. It keeps public API stable, avoids a new migration by encoding provider in `documents.storage_key` for new external artifacts, and leaves OneDrive/dual-write/backfill for later slices.

## Unified Execution Plan

### Overview
Implement PR4 with a shared tenant artifact-store resolver used by both API and worker document-ingest flows. Connected Google Drive tenants will store new document artifacts in Google Drive with provider-prefixed storage keys; managed tenants and old unprefixed keys keep using the existing process-managed storage backend.

### Files To Change
- `packages/db/src/egp_db/storage_credentials.py`: shared credential cipher.
- `apps/api/src/egp_api/services/storage_credentials.py`: compatibility re-export.
- `packages/db/src/egp_db/google_drive.py`: shared Google Drive client/config.
- `apps/api/src/egp_api/services/google_drive.py`: compatibility re-export.
- `packages/db/src/egp_db/tenant_storage_resolver.py`: resolver, provider-key helpers, fallback/fail-closed logic.
- `packages/db/src/egp_db/repositories/document_repo.py`: artifact-store factory and resolver-aware store/download methods.
- `apps/api/src/egp_api/main.py`: construct and inject resolver.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`: construct resolver for worker ingest.
- `apps/worker/src/egp_worker/browser_downloads.py`: pass resolver prerequisites through downloaded-document ingest.
- `apps/worker/src/egp_worker/workflows/discover.py`: pass resolver prerequisites from discover workflow.
- `apps/worker/src/egp_worker/main.py`: pass worker payload/env storage values.
- Tests in `tests/phase4` and `tests/phase1` for resolver/API/worker behavior.

### Implementation Steps
1. Add tests first for resolver decisions, repository provider-prefix behavior, API ingest, worker ingest, and download dispatch; run and capture RED.
2. Move shared Google Drive and storage cipher helpers into `egp_db` with API re-export modules.
3. Implement `TenantArtifactStoreResolver` with Google Drive token refresh and managed fallback behavior.
4. Refactor `SqlDocumentRepository` to use resolver-aware writes/downloads while preserving existing managed behavior when no resolver is supplied.
5. Wire API `create_app()` and worker workflows to build the resolver from tenant admin repository, credential cipher, Google config/client, and managed artifact store.
6. Run GREEN focused tests, then compileall, ruff check/format, and relevant existing document/API/worker tests.
7. Run formal `g-check`, fix any findings, then create/submit PR.

### Test Coverage
- `tests/phase4/test_tenant_storage_resolver.py::test_resolver_returns_google_drive_store_for_connected_tenant`: connected tenant uses Google Drive.
- `tests/phase4/test_tenant_storage_resolver.py::test_resolver_uses_managed_for_unprefixed_key`: old keys route to managed storage.
- `tests/phase4/test_tenant_storage_resolver.py::test_resolver_fails_closed_when_google_credentials_missing`: fail closed without credentials.
- `tests/phase4/test_tenant_storage_resolver.py::test_resolver_uses_managed_fallback_when_enabled`: fallback path works.
- `tests/phase1/test_document_infrastructure.py::test_api_document_ingest_uses_google_drive_for_connected_tenant`: API runtime write uses tenant storage.
- `tests/phase1/test_document_infrastructure.py::test_worker_document_ingest_uses_google_drive_for_connected_tenant`: worker runtime write uses tenant storage.
- `tests/phase1/test_document_infrastructure.py::test_document_download_url_uses_prefixed_google_drive_storage_key`: download dispatch uses provider key.

### Decision Completeness
- Goal: tenant-aware storage resolution for document artifacts in API and worker flows.
- Non-goals: OneDrive runtime provider, Google Picker, dual-write, migration/backfill of old documents, customer support diagnostics.
- Success criteria: new tests fail before implementation and pass after; existing managed/Supabase tests still pass; CI gates pass.
- Public interfaces: no HTTP schema changes; no DB migration; new runtime env/payload support for storage credentials and Google OAuth config in worker.
- Edge cases / failure modes: missing config/credentials/token/folder fail closed unless fallback enabled; unsupported provider fails closed unless fallback enabled; old unprefixed documents stay managed; Google token refresh failures fail the write/download.
- Rollout & monitoring: deploy after PR3; apply migrations 018/019; set envs; watch document ingest API/worker task failures and validation status; rollback by switching provider to managed or enabling fallback.
- Acceptance checks: targeted pytest, compileall, ruff check/format, existing document infrastructure tests.

### Dependencies
- PR3 merged and deployed.
- Tenant external storage config and credentials must exist.
- Live Google Drive requires OAuth refresh token and folder ID.

### Validation
- RED: targeted tests fail for missing shared resolver and wiring.
- GREEN: targeted tests pass.
- Gates: compileall, ruff check, ruff format check, relevant pytest suites.
- Review: formal g-check section appended before commit.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `TenantArtifactStoreResolver` | `SqlDocumentRepository.store_document()` and `get_download_url()` | injected into repository from API/worker construction | `tenant_storage_configs`, `tenant_storage_credentials` |
| `ResolvedArtifactStore` / provider key helpers | document artifact write/download | `document_repo.py` store/download methods | `documents.storage_key` |
| API resolver wiring | `/v1/documents/ingest`, `/v1/documents/{id}/download` | `apps/api/src/egp_api/main.py:create_app()` | `documents`, tenant storage tables |
| Worker resolver wiring | `document_ingest` command and live discovery downloaded docs | `apps/worker/src/egp_worker/main.py`, `workflows/document_ingest.py`, `workflows/discover.py` | `documents`, tenant storage tables |
| Shared Google/cipher modules | API settings service and worker resolver | API compatibility re-exports and worker imports | `tenant_storage_credentials.encrypted_payload` |

### Cross-Language Schema Verification
- `documents.storage_key` is the only schema field storing artifact location and is used in Python repository/download code.
- `tenant_storage_configs.provider`, `connection_status`, `provider_folder_id`, and `managed_fallback_enabled` drive routing.
- `tenant_storage_credentials.encrypted_payload` stores OAuth tokens; access remains tenant/provider scoped.
- No TypeScript schema update is needed because no API response fields change.

### Decision-Complete Checklist
- No open decisions remain for implementation.
- No new public HTTP endpoint or DB migration is introduced.
- Every behavior change has a concrete test.
- Validation commands are scoped.
- Wiring verification covers API, worker, repository, shared modules, and storage tables.


## Implementation Summary (2026-04-16 13:17:00 +07)

### Goal
- Implement PR4 tenant-aware document artifact storage resolution in both API and worker flows instead of relying only on server-global artifact storage config.

### What Changed
- `packages/db/src/egp_db/google_drive.py`
  - Moved Google Drive OAuth/client primitives into the shared DB package so both API and worker runtime code can construct Drive-backed artifact stores.
- `apps/api/src/egp_api/services/google_drive.py`
  - Replaced implementation with compatibility re-exports from `egp_db.google_drive`.
- `packages/db/src/egp_db/storage_credentials.py`
  - Moved `StorageCredentialCipher` into the shared package.
- `apps/api/src/egp_api/services/storage_credentials.py`
  - Replaced implementation with compatibility re-export from `egp_db.storage_credentials`.
- `packages/db/src/egp_db/tenant_storage_resolver.py`
  - Added `TenantArtifactStoreResolver`, `ResolvedArtifactStore`, provider-key helpers, Google Drive token refresh, fail-closed handling, and managed fallback behavior.
- `packages/db/src/egp_db/repositories/document_repo.py`
  - Added `create_artifact_store(...)` and optional `artifact_store_resolver` wiring.
  - `store_document(...)` now resolves the artifact store by tenant for writes and prefixes new Google Drive keys as `google_drive:<file-id>`.
  - `get_download_url(...)` now dispatches by provider-prefixed `storage_key`; unprefixed historical keys still use managed storage.
  - Upload cleanup now deletes from the resolved artifact store using the raw provider key on metadata insert failure.
- `apps/api/src/egp_api/main.py`
  - Constructs one tenant artifact resolver from the admin repository, managed artifact store, credential cipher, Google OAuth config, and Google client, then injects it into the document repository.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`
  - Builds the same tenant resolver for worker-side document ingestion, using explicit args or env for Google/storage credential config.
- `apps/worker/src/egp_worker/browser_downloads.py`, `apps/worker/src/egp_worker/workflows/discover.py`, `apps/worker/src/egp_worker/main.py`
  - Threaded optional storage credential and Google runtime parameters through worker downloaded-document flows and direct `document_ingest` command.
- `apps/api/pyproject.toml`, `apps/worker/pyproject.toml`, `pyproject.toml`
  - Added direct `cryptography` dependency where the shared credential cipher can be imported.
- `tests/phase4/test_tenant_storage_resolver.py`
  - Added resolver unit tests for Google Drive routing, old-key managed routing, fail-closed missing credentials, managed fallback, refresh-failure fallback, and provider-key helpers.
- `tests/phase1/test_document_infrastructure.py`
  - Added API and worker integration tests proving connected Google Drive tenant writes route to the fake Drive client and persist provider-prefixed storage keys.

### TDD Evidence
- RED command: `./.venv/bin/python -m pytest -q tests/phase4/test_tenant_storage_resolver.py tests/phase1/test_document_infrastructure.py -k 'tenant_storage_resolver or google_drive_for_connected_tenant or provider_storage_key_helpers'`
- RED result: failed during collection with `ModuleNotFoundError: No module named 'egp_db.google_drive'`, proving the shared module/resolver implementation was missing.
- GREEN command: `./.venv/bin/python -m pytest -q tests/phase4/test_tenant_storage_resolver.py tests/phase1/test_document_infrastructure.py -k 'tenant_storage_resolver or google_drive_for_connected_tenant or provider_storage_key_helpers'`
- GREEN result: `7 passed, 7 deselected` after implementing shared resolver/wiring.
- Additional fallback regression: added `test_resolver_uses_managed_fallback_on_google_refresh_failure`; focused command `./.venv/bin/python -m pytest -q tests/phase4/test_tenant_storage_resolver.py tests/phase1/test_document_infrastructure.py` -> `15 passed`.

### Tests Run
- `./.venv/bin/python -m pytest -q tests/phase1/test_document_infrastructure.py tests/phase4/test_tenant_storage_resolver.py tests/phase4/test_google_drive_artifact_store.py` -> `15 passed`.
- `./.venv/bin/python -m pytest -q tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py` -> `34 passed`.
- `./.venv/bin/python -m pytest -q tests/phase1/test_worker_workflows.py tests/phase1/test_phase1_wiring.py` -> `15 passed`.
- `./.venv/bin/python -m pytest -q tests/phase1/test_documents_api.py tests/phase1/test_document_persistence.py` -> `29 passed`.
- Final combined gate: `./.venv/bin/python -m pytest -q tests/phase1/test_document_infrastructure.py tests/phase1/test_documents_api.py tests/phase1/test_document_persistence.py tests/phase1/test_worker_workflows.py tests/phase1/test_phase1_wiring.py tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py tests/phase4/test_tenant_storage_resolver.py` -> `93 passed`.
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/db/src` -> passed.
- `./.venv/bin/ruff check apps/api/src apps/worker/src packages/db/src tests/phase1/test_document_infrastructure.py tests/phase4/test_tenant_storage_resolver.py tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py` -> passed.
- `./.venv/bin/ruff format --check apps/api/src apps/worker/src packages/db/src tests/phase1/test_document_infrastructure.py tests/phase4/test_tenant_storage_resolver.py tests/phase4/test_admin_api.py tests/phase4/test_google_drive_artifact_store.py` -> passed.

### Wiring Verification Evidence
- API route `/v1/documents/ingest` still enters `DocumentIngestService.ingest_document()`, which calls `SqlDocumentRepository.store_document()`; repository now resolves tenant artifact storage before writing bytes.
- API route `/v1/documents/{document_id}/download` still enters `DocumentIngestService.get_download_url()`, which calls repository `get_download_url()`; repository now dispatches by provider-prefixed `storage_key`.
- Worker `document_ingest` command enters `ingest_document_artifact()`, which now constructs `TenantArtifactStoreResolver` before repository creation when no repository is injected.
- Live discover downloaded-document flow enters `ingest_downloaded_documents()` and threads the optional storage config through to `ingest_document_artifact()`.
- Storage config reads are tenant scoped through `SqlAdminRepository.get_tenant_storage_config(tenant_id=...)` and credentials through `get_tenant_storage_credentials(tenant_id=..., provider='google_drive')`.

### Behavior Changes And Risk Notes
- New Google Drive artifacts are stored as `google_drive:<file-id>` in `documents.storage_key`; historical unprefixed keys continue to route to managed storage.
- Connected Google Drive tenants fail closed if credential/config/token/folder setup is incomplete, unless `managed_fallback_enabled` is true.
- Managed fallback now catches normal Google setup/refresh exceptions for writes; prefixed Google Drive downloads still require Google credentials because managed storage does not contain those external files.
- Refresh tokens are preserved when refreshed access-token payloads are persisted.
- No migration is introduced in PR4; PR4 relies on migrations 018/019 from earlier slices.

### Follow-ups / Known Gaps
- PR6 still needs OneDrive runtime provider support.
- PR7 should add richer download/support diagnostics, including clearer user-facing errors when a prefixed external key cannot be resolved because credentials were disconnected.
- Historical documents remain managed unless their `storage_key` is provider-prefixed; there is no backfill or migration in this slice.

## Review (2026-04-16 13:17:00 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at `476c0bf`, including PR4 tenant-aware storage changes and excluding pre-existing unrelated dirty files unless listed in status.
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `nl -ba ... | sed -n ...` reads for resolver, document repository, API wiring, worker wiring, and tests; `./.venv/bin/python -m pytest -q ...` final 93-test gate; `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/db/src`; `./.venv/bin/ruff check ...`; `./.venv/bin/ruff format --check ...`.

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
- Assumption: provider-prefixing `documents.storage_key` is acceptable for new external artifacts because `storage_key` is already provider-agnostic and no migration was desired in PR4.
- Assumption: unprefixed historical documents should remain managed/local/S3/Supabase and are not backfilled to external providers in this slice.
- Assumption: OneDrive remains out of scope until PR6.

### Recommended Tests / Validation
- Keep the final 93-test document/storage gate in the PR body.
- After deployment, run one live Google Drive tenant ingest with a validated folder and verify `documents.storage_key` starts with `google_drive:`.
- Verify a managed tenant still writes unprefixed keys to the configured managed backend.

### Rollout Notes
- Deploy after migrations 018/019 are applied.
- Required live envs: `EGP_STORAGE_CREDENTIALS_SECRET`, `EGP_GOOGLE_DRIVE_CLIENT_ID`, `EGP_GOOGLE_DRIVE_CLIENT_SECRET`, `EGP_GOOGLE_DRIVE_REDIRECT_URI`, and optional `EGP_GOOGLE_DRIVE_SCOPES`.
- Rollback path: set tenant provider back to `managed` or enable `managed_fallback_enabled`; prefixed Google Drive documents still require Google credentials for download until PR7 support diagnostics are added.
