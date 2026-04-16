# PR8 Managed Backup Dual Write

Auggie semantic search unavailable; plan is based on direct file inspection + exact-string searches.

Assumption locked for implementation: product wants opt-in backup copies on our managed storage in addition to the external primary copy, so PR8 will implement dual-write rather than deferring the feature.

Inspected files:
- `AGENTS.md`
- `packages/db/AGENTS.md`
- `apps/api/AGENTS.md`
- `apps/web/AGENTS.md`
- `apps/worker/AGENTS.md`
- `packages/db/src/egp_db/artifact_store.py`
- `packages/db/src/egp_db/tenant_storage_resolver.py`
- `packages/db/src/egp_db/repositories/document_repo.py`
- `packages/db/src/egp_db/repositories/admin_repo.py`
- `packages/db/src/migrations/018_tenant_storage_configs_and_credentials.sql`
- `packages/db/src/migrations/019_google_drive_storage_metadata.sql`
- `apps/api/src/egp_api/main.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/api/src/egp_api/routes/documents.py`
- `apps/api/src/egp_api/services/document_ingest_service.py`
- `apps/api/src/egp_api/services/storage_settings_service.py`
- `apps/worker/src/egp_worker/workflows/document_ingest.py`
- `apps/worker/src/egp_worker/browser_downloads.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/app/(app)/admin/storage/page.tsx`
- `apps/web/src/app/(app)/admin/page.tsx`
- `tests/phase1/test_document_persistence.py`
- `tests/phase1/test_document_infrastructure.py`
- `tests/phase4/test_tenant_storage_resolver.py`
- `tests/phase4/test_admin_api.py`

## Plan Draft A

### Overview
PR8 will add an opt-in managed backup mode for externally stored documents. When a tenant uses Google Drive or OneDrive and enables backup copies, the system will keep the provider-native primary artifact while also writing a managed backup copy, persist that backup key in document metadata, and use it for internal reads plus download fallback if the external provider later fails.

### Files to Change
- `packages/db/src/migrations/020_managed_storage_backup_dual_write.sql`: add additive schema for backup config and per-document managed backup key.
- `packages/db/src/egp_db/repositories/admin_repo.py`: add `managed_backup_enabled` to storage config/settings records and update paths.
- `packages/db/src/egp_db/tenant_storage_resolver.py`: add a write-plan API that exposes primary resolved store plus managed-backup intent.
- `packages/db/src/egp_db/repositories/document_repo.py`: dual-write artifacts, persist managed backup key, use backup-aware internal reads, and fallback downloads to managed backup.
- `apps/api/src/egp_api/services/storage_settings_service.py`: accept and normalize the new backup toggle.
- `apps/api/src/egp_api/routes/admin.py`: expose `managed_backup_enabled` in admin storage settings and support diagnostics contracts.
- `packages/db/src/egp_db/repositories/support_repo.py`: include the backup toggle in support storage diagnostics.
- `apps/web/src/lib/api.ts`: extend admin/support storage types and storage update payloads with the backup toggle.
- `apps/web/src/app/(app)/admin/storage/page.tsx`: add the backup-copy toggle and explanatory copy.
- `apps/web/src/app/(app)/admin/page.tsx`: show the backup-copy state in support diagnostics.
- `tests/phase1/test_document_persistence.py`: cover dual-write persistence and backup-aware diff/download reads.
- `tests/phase1/test_document_infrastructure.py`: cover API/worker ingest storing both external and managed backup copies.
- `tests/phase4/test_admin_api.py`: cover the new storage setting field plus support diagnostics exposure.
- `apps/web/tests/e2e/admin-page.spec.ts`: optionally extend mocked support diagnostics coverage if the new support field is rendered there.

### Implementation Steps
TDD sequence:
1. Add repository/infrastructure tests for dual-write storage and managed-backup download fallback.
2. Run those tests and confirm RED on missing schema/behavior.
3. Add admin storage API tests for the new backup toggle and support diagnostics field.
4. Run those tests and confirm RED on the missing contract.
5. Implement the smallest DB/repository changes to pass backend tests.
6. Update admin storage/support web types and UI to consume the new field.
7. Run focused fast gates, then broader impacted gates, then formal review.

Functions and changes:
- `TenantArtifactStoreResolver.resolve_write_plan()`
  - Return the primary resolved artifact store plus whether managed backup should also be written. This keeps backup policy in the tenant-storage layer instead of duplicating config reads inside the repository.
- `SqlDocumentRepository.store_document()`
  - Write the primary artifact as today, then optionally write a managed backup copy when the tenant is using external primary storage with backup enabled. Persist the new managed backup key in document metadata and clean up both writes on failure.
- `SqlDocumentRepository._get_document_bytes()`
  - Prefer the managed backup copy when present; otherwise resolve bytes through the provider-aware storage-key path. This fixes internal diff/read behavior for externally stored historical documents.
- `SqlDocumentRepository.get_download_url()`
  - Try the primary storage key first; if provider URL resolution fails and a managed backup exists, return the managed download URL instead of failing closed.
- `StorageSettingsService.update_config()`
  - Accept `managed_backup_enabled`, clear it when switching back to managed primary storage, and preserve current validation behavior.
- `_serialize_storage_settings()` / support-summary serialization
  - Add the new field to the admin and support API contracts.
- `AdminStoragePage`
  - Add a separate opt-in checkbox for “keep backup copies on managed storage too” with copy that makes it distinct from `managed_fallback_enabled`.

Expected behavior and edge cases:
- Managed primary storage should never write a duplicate managed backup copy.
- External primary storage with `managed_backup_enabled=false` should keep today’s single-write behavior.
- External primary storage with `managed_backup_enabled=true` should fail closed if the managed backup write fails, and should clean up the already-written primary artifact.
- Download fallback should only use the managed backup when a managed backup key exists; otherwise it should preserve PR7’s explicit failure behavior.
- Old external documents created before PR8 with no backup key should still work through provider resolution; internal diff reads should stop assuming every external doc is directly readable from the managed store.

### Test Coverage
- `tests/phase1/test_document_persistence.py::test_store_document_dual_writes_managed_backup_for_external_primary`
  - External primary also writes managed backup.
- `tests/phase1/test_document_persistence.py::test_store_document_cleans_up_primary_when_backup_write_fails`
  - Dual-write fails closed with cleanup.
- `tests/phase1/test_document_persistence.py::test_get_download_url_falls_back_to_managed_backup_when_external_resolution_fails`
  - Backup download URL used on provider failure.
- `tests/phase1/test_document_persistence.py::test_store_document_uses_backup_copy_for_diff_reads_with_external_primary`
  - Internal diff reads prefer managed backup.
- `tests/phase1/test_document_infrastructure.py::test_api_document_ingest_dual_writes_managed_backup_for_google_drive_tenant`
  - API ingest persists both copies.
- `tests/phase1/test_document_infrastructure.py::test_worker_document_ingest_dual_writes_managed_backup_for_onedrive_tenant`
  - Worker ingest persists both copies.
- `tests/phase4/test_admin_api.py::test_storage_settings_can_toggle_managed_backup`
  - Admin storage API exposes and persists backup toggle.
- `tests/phase4/test_admin_api.py::test_admin_support_summary_includes_managed_backup_flag`
  - Support diagnostics expose backup toggle.
- `apps/web/tests/e2e/admin-page.spec.ts::test_admin_support_tab_shows_managed_backup_state`
  - Optional mocked browser coverage for support diagnostics.

### Decision Completeness
- Goal:
  - Add opt-in managed backup copies for externally stored tenant documents and wire the backup state through admin/support surfaces.
- Non-goals:
  - PR8 will not redesign artifact metadata into a multi-row artifact inventory system.
  - PR8 will not backfill old documents into managed storage.
  - PR8 will not change the primary-provider selection model or add background replication jobs.
- Success criteria:
  - External-primary tenants can enable a `managed_backup_enabled` setting.
  - New documents for those tenants persist both the external primary key and a managed backup key.
  - Internal diff/download paths can use the managed backup when present.
  - Admin storage API and UI expose the backup toggle.
  - Support diagnostics show whether backup mode is enabled.
- Public interfaces:
  - `PATCH /v1/admin/storage` request/response adds `managed_backup_enabled`.
  - `GET /v1/admin/storage` response adds `managed_backup_enabled`.
  - `GET /v1/admin/support/tenants/{tenant_id}/summary` storage diagnostics add `managed_backup_enabled`.
  - Database schema adds additive `tenant_storage_configs.managed_backup_enabled` and `documents.managed_backup_storage_key`.
- Edge cases / failure modes:
  - Fail closed on backup write failure when backup mode is enabled.
  - Fail open to current behavior when backup mode is disabled.
  - Old documents without a backup key still resolve through primary provider logic.
  - Managed primary storage ignores backup mode and stores only one managed copy.
- Rollout & monitoring:
  - Additive migration only; no flag required beyond the tenant setting itself.
  - Backout is code rollback plus leaving nullable columns unused.
  - Watch support diagnostics and document-ingest failures for backup-write errors after deploy.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_document_infrastructure.py -q`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k storage`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run build`

### Dependencies
- Existing tenant storage config/credential model from migrations `018` and `019`.
- Existing managed artifact store configuration in API and worker bootstraps.

### Validation
- Verify new documents record both keys when backup mode is enabled.
- Verify provider-backed download fallback uses the managed backup only when it exists.
- Verify admin storage settings and support diagnostics remain additive and build cleanly.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Migration `020_managed_storage_backup_dual_write.sql` | N/A | `egp_db.migration_runner` / app bootstrap migrations | `documents`, `tenant_storage_configs` |
| Resolver write plan | `SqlDocumentRepository.store_document()` | `TenantArtifactStoreResolver` created in `apps/api/src/egp_api/main.py` and `apps/worker/src/egp_worker/workflows/document_ingest.py` | `tenant_storage_configs`, `tenant_storage_credentials` |
| Managed backup persistence | API `/v1/documents/ingest` and worker `ingest_document_artifact()` | `create_document_repository(..., artifact_store_resolver=...)` in API/worker bootstraps | `documents` |
| Managed backup download fallback | `GET /v1/documents/{document_id}/download` | `DocumentIngestService.get_download_url()` -> `SqlDocumentRepository.get_download_url()` | `documents` |
| Admin backup toggle | `/v1/admin/storage` GET/PATCH | `apps/api/src/egp_api/routes/admin.py` -> `StorageSettingsService` | `tenant_storage_configs` |
| Web backup toggle UI | `/admin/storage` | `apps/web/src/app/(app)/admin/storage/page.tsx` via `useTenantStorageSettings()` | N/A |
| Support diagnostics backup flag | `/v1/admin/support/tenants/{tenant_id}/summary` | `SupportService` -> `support_repo.py` -> admin support UI | `tenant_storage_configs` |

### Cross-Language Schema Verification
- Verified `documents.storage_key` is the only current artifact reference in Python repository code and API serializers.
- Verified tenant storage settings currently live in `tenant_storage_configs` / `tenant_storage_credentials`.
- No TypeScript direct DB coupling; web consumes the new fields only via API contracts.

### Decision-Complete Checklist
- Scope is locked to opt-in managed backups for new writes.
- Public API/schema changes are additive.
- Failure posture is explicit for backup-enabled vs backup-disabled writes.
- Validation commands are concrete.
- Wiring is documented for each changed runtime path.

## Plan Draft B

### Overview
PR8 can also be implemented with a normalized artifact-copies table instead of additive columns on `documents`. That design would model each stored replica explicitly and make future multi-copy backfills cleaner, but it is a larger change than the current product slice likely needs.

### Files to Change
- `packages/db/src/migrations/020_document_artifact_copies.sql`: create a new per-document replica table and add the backup config field.
- `packages/db/src/egp_db/repositories/admin_repo.py`: add `managed_backup_enabled`.
- `packages/db/src/egp_db/repositories/document_repo.py`: write/read document copies through a new artifact-copy abstraction.
- `packages/db/src/egp_db/tenant_storage_resolver.py`: expose the primary write target and backup intent.
- `apps/api/src/egp_api/services/storage_settings_service.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/(app)/admin/storage/page.tsx`
- `tests/phase1/test_document_persistence.py`
- `tests/phase1/test_document_infrastructure.py`
- `tests/phase4/test_admin_api.py`

### Implementation Steps
TDD sequence:
1. Add schema/repository tests that expect a primary copy row plus optional managed backup copy row.
2. Run RED and confirm missing table/model failures.
3. Add the new artifact-copy persistence abstraction.
4. Update admin storage settings contract and UI.
5. Run fast gates and review.

Functions and changes:
- Add a `DocumentArtifactCopyRecord` model and copy-loading helpers.
- Keep `documents.storage_key` for compatibility while also writing detailed copy rows.
- Drive fallback and internal reads from the new copy inventory instead of a nullable backup column.

Expected behavior and edge cases:
- Supports future multiple replicas or backfills cleanly.
- Requires more repository churn and more schema/tests today.

### Test Coverage
- `test_store_document_creates_primary_and_backup_artifact_copy_rows`
  - Copy table records both replicas.
- `test_get_download_url_prefers_primary_copy_then_managed_backup_copy`
  - Fallback uses managed copy row.
- `test_storage_settings_can_toggle_managed_backup`
  - Backup toggle persists through admin API.

### Decision Completeness
- Goal:
  - Add opt-in backup-copy support with a normalized artifact inventory model.
- Non-goals:
  - No background replication or backfill jobs.
  - No provider-selection redesign.
- Success criteria:
  - New replica rows exist for primary and backup copies when enabled.
  - Admin/UI contract exposes the backup toggle.
- Public interfaces:
  - Additive `managed_backup_enabled` on admin storage endpoints.
  - New `document_artifact_copies` table plus migration.
- Edge cases / failure modes:
  - Fail closed if any required copy row cannot be persisted.
  - Preserve current behavior when backup mode is off.
- Rollout & monitoring:
  - Bigger migration blast radius than Draft A.
  - Backout requires leaving an extra unused table.
- Acceptance checks:
  - Same focused pytest and web gates as Draft A.

### Dependencies
- Same dependencies as Draft A, plus a larger schema and repository refactor.

### Validation
- Verify copy table rows, fallback behavior, and additive admin contract.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Artifact copy table | `SqlDocumentRepository.store_document()` | repository bootstrap in API/worker | `document_artifact_copies` |
| Backup toggle | `/v1/admin/storage` | admin router + storage service | `tenant_storage_configs` |
| Web storage toggle | `/admin/storage` | storage page via API hooks | N/A |

### Cross-Language Schema Verification
- Would require broader repository and serializer changes because current code assumes one storage key per document.

### Decision-Complete Checklist
- The alternative is decision-complete but intentionally broader.
- Additional abstraction is justified only if product now needs multi-replica inventory beyond PR8.

## Comparative Analysis & Synthesis

### Strengths
- Draft A is much closer to the current code shape and minimizes repository/API churn.
- Draft B is more normalized and future-friendly if the product later needs explicit replica inventory or backfills.

### Gaps
- Draft A is less flexible if the system eventually needs more than one backup target.
- Draft B is too large for the stated PR8 scope and would spend time on generalized modeling instead of shipping backup copies quickly.

### Trade-offs
- Draft A trades some future extensibility for a smaller, safer implementation with additive columns.
- Draft B trades current delivery speed for a more general artifact model that the product has not asked for yet.

### Compliance
- Both drafts preserve tenant scoping and additive contracts.
- Draft A is the better fit for repo conventions that prefer thin, incremental changes over premature generalization.

## Unified Execution Plan

### Overview
Implement PR8 as an additive dual-write slice: add a tenant-level `managed_backup_enabled` toggle, persist a nullable managed backup key on each new document, dual-write new external-primary documents into managed storage when the toggle is on, and use that backup for internal bytes reads plus download fallback. Keep the primary provider model intact and expose the new setting in admin storage plus support diagnostics.

### Files to Change
- `packages/db/src/migrations/020_managed_storage_backup_dual_write.sql`: add `tenant_storage_configs.managed_backup_enabled` and `documents.managed_backup_storage_key`.
- `packages/db/src/egp_db/repositories/admin_repo.py`: extend storage config/settings dataclasses and updates with `managed_backup_enabled`.
- `packages/db/src/egp_db/tenant_storage_resolver.py`: add a write-plan dataclass/method exposing primary store plus backup intent.
- `packages/db/src/egp_db/repositories/document_repo.py`: add `managed_backup_storage_key` to `DocumentRecord`, dual-write logic, backup-aware internal reads, and download fallback.
- `apps/api/src/egp_api/services/storage_settings_service.py`: accept and normalize the new toggle.
- `apps/api/src/egp_api/routes/admin.py`: add the new field to admin storage request/response models and support diagnostics.
- `packages/db/src/egp_db/repositories/support_repo.py`: include the new backup flag in support diagnostics.
- `apps/web/src/lib/api.ts`: extend admin/support storage types and update payloads with the backup field.
- `apps/web/src/app/(app)/admin/storage/page.tsx`: render the new backup-copy toggle and copy.
- `apps/web/src/app/(app)/admin/page.tsx`: show backup state in support diagnostics.
- `tests/phase1/test_document_persistence.py`: add direct repository dual-write/fallback coverage.
- `tests/phase1/test_document_infrastructure.py`: add API/worker external-primary dual-write coverage.
- `tests/phase4/test_admin_api.py`: add storage settings + support diagnostics coverage for the backup flag.
- `apps/web/tests/e2e/admin-page.spec.ts`: extend mocked support diagnostics coverage only if the field is rendered there cheaply; otherwise rely on API tests plus web gates.

### Implementation Steps
TDD sequence:
1. Add repository red tests in `tests/phase1/test_document_persistence.py` for dual-write persistence, cleanup on backup failure, and managed-backup download fallback.
2. Run the focused repository tests and confirm RED on missing schema/behavior.
3. Add infrastructure red tests in `tests/phase1/test_document_infrastructure.py` for API/worker external-primary dual-write behavior.
4. Add admin API red tests in `tests/phase4/test_admin_api.py` for `managed_backup_enabled` persistence and support diagnostics exposure.
5. Implement the migration plus DB models first, then repository write/read behavior, then API/admin contract updates, then web UI wiring.
6. Run focused fast gates after each change set, then the impacted broader suites, then formal review before commit.

Functions and changes:
- `TenantArtifactStoreResolver.resolve_write_plan()`
  - Return a new plan object containing the primary `ResolvedArtifactStore` and whether the tenant config requires a managed backup for this write.
- `SqlDocumentRepository.store_document()`
  - Use the write plan to persist the primary copy, optionally persist a managed backup, and clean up both artifacts if anything after the writes fails.
- `SqlDocumentRepository._get_document_bytes()`
  - Read from `managed_backup_storage_key` when present; otherwise resolve provider-aware bytes from `storage_key`.
- `SqlDocumentRepository.get_download_url()`
  - Resolve the external/native URL first; on provider failure, use the managed backup URL if one exists.
- `StorageSettingsService.update_config()`
  - Persist `managed_backup_enabled`, but force it off when provider is `managed`.
- `_serialize_storage_settings()` / `AdminTenantStorageSettingsResponse` / `UpdateTenantStorageSettingsRequest`
  - Expose the new field through the admin API contract.
- `SupportStorageDiagnostics` serialization
  - Expose the backup-enabled state in support summary so operators can see whether a tenant should have managed backups.
- `AdminStoragePage`
  - Add a second checkbox that clearly separates temporary managed fallback from permanent backup-copy dual-write.

Expected behavior and edge cases:
- External-primary + backup enabled: primary stays provider-native, managed backup is also written, and writes fail closed if the backup copy cannot be stored.
- External-primary + backup disabled: behavior is unchanged from PR7.
- Managed primary: no duplicate backup is written and backup toggle is forced off.
- Old external documents with no backup key continue to download through provider-native logic and only use backup fallback when a backup key exists.
- Internal diff reads stop assuming provider-prefixed keys are readable directly from the managed store.

### Test Coverage
- `tests/phase1/test_document_persistence.py::test_store_document_dual_writes_managed_backup_for_external_primary`
  - External-primary documents persist backup key.
- `tests/phase1/test_document_persistence.py::test_store_document_cleans_up_primary_when_backup_write_fails`
  - Backup-required writes fail closed cleanly.
- `tests/phase1/test_document_persistence.py::test_get_download_url_falls_back_to_managed_backup_when_primary_download_resolution_fails`
  - Download falls back to managed backup.
- `tests/phase1/test_document_persistence.py::test_store_document_uses_backup_copy_for_diff_reads_with_external_primary`
  - Internal diff reads use managed backup.
- `tests/phase1/test_document_infrastructure.py::test_api_document_ingest_dual_writes_managed_backup_for_google_drive_tenant`
  - API ingest writes external primary plus backup.
- `tests/phase1/test_document_infrastructure.py::test_worker_document_ingest_dual_writes_managed_backup_for_onedrive_tenant`
  - Worker ingest writes external primary plus backup.
- `tests/phase4/test_admin_api.py::test_storage_settings_can_toggle_managed_backup`
  - Admin storage setting persists new flag.
- `tests/phase4/test_admin_api.py::test_admin_support_summary_includes_managed_backup_flag`
  - Support diagnostics expose the backup flag.
- `apps/web/tests/e2e/admin-page.spec.ts::test_admin_support_tab_shows_managed_backup_state`
  - Optional mock-based support UI coverage.

### Decision Completeness
- Goal:
  - Ship opt-in managed backup copies for new externally stored documents and surface the setting through admin/support tooling.
- Non-goals:
  - No backfill of old documents.
  - No generalized multi-replica artifact model.
  - No background sync job or backup repair workflow.
- Success criteria:
  - New `managed_backup_enabled` setting is configurable through admin storage.
  - External-primary documents created while the setting is on persist a nullable managed backup key.
  - Internal bytes reads and download fallback can use that backup when present.
  - Support diagnostics and admin storage UI expose the setting clearly.
- Public interfaces:
  - Additive `managed_backup_enabled` on `/v1/admin/storage` request/response.
  - Additive `managed_backup_enabled` inside support `storage_diagnostics`.
  - Additive DB fields: `tenant_storage_configs.managed_backup_enabled`, `documents.managed_backup_storage_key`.
  - No new env vars.
- Edge cases / failure modes:
  - Backup enabled + backup write failure: fail closed and clean up primary write.
  - Backup disabled: keep current fail-open/fail-closed posture from the primary path only.
  - Managed provider: backup toggle forced false, one managed copy only.
  - Legacy documents without backup key: continue through primary path.
- Rollout & monitoring:
  - Standard additive migration and code rollout.
  - Backout is code rollback; new nullable columns can remain unused.
  - Watch document-ingest failures and support diagnostics for tenants with backup enabled.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_document_infrastructure.py -q`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k storage`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run lint`
  - `cd apps/web && npm run build`

### Dependencies
- Existing managed artifact store configuration in API/worker bootstraps.
- Existing tenant storage settings + credential persistence in `tenant_storage_configs` / `tenant_storage_credentials`.

### Validation
- Confirm RED then GREEN for the new repository, infrastructure, and admin storage tests.
- Confirm admin storage page builds and typechecks with the new toggle.
- Confirm the staged PR8 scope passes formal review before commit.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Migration `020_managed_storage_backup_dual_write.sql` | N/A | migration runner / deploy migrations | `documents`, `tenant_storage_configs` |
| Resolver write plan | `SqlDocumentRepository.store_document()` | `TenantArtifactStoreResolver` instantiated in API `main.py` and worker `document_ingest.py` | `tenant_storage_configs`, `tenant_storage_credentials` |
| Dual-write persistence | `/v1/documents/ingest` and worker `ingest_document_artifact()` | `create_document_repository(...artifact_store_resolver=...)` in API/worker bootstraps | `documents` |
| Backup-aware internal reads | diff generation during `store_document()` | `SqlDocumentRepository._build_diff_record()` via new `_get_document_bytes()` helper | `documents` |
| Download fallback | `GET /v1/documents/{document_id}/download` | document route -> `DocumentIngestService.get_download_url()` -> repository | `documents` |
| Admin backup toggle | `/v1/admin/storage` GET/PATCH | admin router -> `StorageSettingsService.update_config()` | `tenant_storage_configs` |
| Support backup diagnostics | `/v1/admin/support/tenants/{tenant_id}/summary` | support repo -> support service -> admin router/support UI | `tenant_storage_configs` |
| Web storage toggle UI | `/admin/storage` | `useTenantStorageSettings()` / `updateTenantStorageSettings()` | N/A |

### Cross-Language Schema Verification
- Verified the current document metadata model only has `storage_key`; backup persistence needs an additive schema extension.
- Verified tenant storage configuration already uses additive settings fields in both Python repo and web API contracts.
- No direct frontend DB coupling exists; the web change is API-contract only.

### Decision-Complete Checklist
- Design choice is locked to additive dual-write, not a generalized artifact inventory.
- Public interfaces and schema changes are enumerated.
- Failure posture for backup-enabled writes is explicit.
- Validation commands and runtime wiring are concrete.


## Implementation Summary (2026-04-16 15:14:45 +07)

### Goal
Implement PR8 managed backup / dual-write so external-provider documents can optionally keep a backup copy in managed storage, while preserving support/admin visibility into the setting.

### What Changed
- `packages/db/src/egp_db/repositories/document_repo.py`
  - Added `managed_backup_storage_key` to document records and inserts.
  - Added backup-aware byte reads for diff generation.
  - Added dual-write support via resolver write plans and managed-backup fallback for download URLs.
  - Added cleanup of uploaded primary artifacts when backup writes fail.
- `packages/db/src/egp_db/tenant_storage_resolver.py`
  - Added `ResolvedDocumentWritePlan` and `resolve_write_plan()` so write-time storage decisions can return primary plus optional managed backup.
- `packages/db/src/egp_db/repositories/admin_repo.py`
  - Added `managed_backup_enabled` to tenant storage settings/config tables, dataclasses, mappers, defaults, and update flows.
- `apps/api/src/egp_api/services/storage_settings_service.py`
  - Threaded `managed_backup_enabled` through storage settings updates and reset it when switching back to fully managed storage.
- `apps/api/src/egp_api/routes/admin.py`
  - Extended storage settings/admin support response/request models with `managed_backup_enabled`.
- `packages/db/src/egp_db/repositories/support_repo.py`
  - Added `managed_backup_enabled` to support storage diagnostics.
- `apps/web/src/lib/api.ts`
  - Extended admin/support storage typings and update payloads with `managed_backup_enabled`.
- `apps/web/src/app/(app)/admin/storage/page.tsx`
  - Added the managed-backup checkbox and surfaced the saved backup status in the integration summary card.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Added managed-backup visibility to support storage diagnostics.
- `apps/web/tests/e2e/admin-page.spec.ts`
  - Updated mocked support data shape to include the new backup flag.
- `packages/db/src/migrations/020_managed_storage_backup_dual_write.sql`
  - Added schema changes for `managed_backup_enabled` and `managed_backup_storage_key`.
- `tests/phase1/test_document_persistence.py`
  - Added repository-level tests for dual-write, cleanup on backup failure, backup download fallback, and backup-based diff reads.
- `tests/phase1/test_document_infrastructure.py`
  - Added API/worker coverage for dual-write on Google Drive and OneDrive tenants.
- `tests/phase4/test_admin_api.py`
  - Added storage-settings/support-summary coverage for `managed_backup_enabled`.

### TDD Evidence
- RED command:
  - `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q -k 'dual_writes or backup_write_fails or falls_back_to_managed_backup or uses_backup_copy_for_diff_reads'`
  - Initial key failure reason: missing `managed_backup_enabled` / `managed_backup_storage_key` schema and repository support.
- RED command:
  - `./.venv/bin/python -m pytest tests/phase1/test_document_infrastructure.py -q -k 'dual_writes_managed_backup'`
  - Initial key failure reason: `tenant_storage_configs` missing `managed_backup_enabled` column.
- RED command:
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k 'managed_backup or storage_diagnostics_and_alerts'`
  - Initial key failure reason: storage/admin responses missing `managed_backup_enabled`.
- GREEN command:
  - `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py tests/phase1/test_document_infrastructure.py tests/phase4/test_admin_api.py -q -k 'managed_backup or dual_writes or backup_write_fails or falls_back_to_managed_backup or uses_backup_copy_for_diff_reads or storage_diagnostics_and_alerts'`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q -k 'dual_writes or backup_write_fails or falls_back_to_managed_backup or uses_backup_copy_for_diff_reads'` -> passed
- `./.venv/bin/python -m pytest tests/phase1/test_document_infrastructure.py -q -k 'dual_writes_managed_backup'` -> passed
- `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k 'managed_backup or storage_diagnostics_and_alerts'` -> passed
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py tests/phase1/test_document_infrastructure.py tests/phase4/test_admin_api.py -q -k 'managed_backup or dual_writes or backup_write_fails or falls_back_to_managed_backup or uses_backup_copy_for_diff_reads or storage_diagnostics_and_alerts'` -> passed
- `./.venv/bin/ruff check apps/api/src/egp_api/routes/admin.py apps/api/src/egp_api/services/storage_settings_service.py packages/db/src/egp_db/repositories/admin_repo.py packages/db/src/egp_db/repositories/document_repo.py packages/db/src/egp_db/repositories/support_repo.py packages/db/src/egp_db/tenant_storage_resolver.py tests/phase1/test_document_persistence.py tests/phase1/test_document_infrastructure.py tests/phase4/test_admin_api.py` -> passed
- `./.venv/bin/ruff format --check apps/api/src/egp_api/routes/admin.py apps/api/src/egp_api/services/storage_settings_service.py packages/db/src/egp_db/repositories/admin_repo.py packages/db/src/egp_db/repositories/document_repo.py packages/db/src/egp_db/repositories/support_repo.py packages/db/src/egp_db/tenant_storage_resolver.py tests/phase1/test_document_persistence.py tests/phase1/test_document_infrastructure.py tests/phase4/test_admin_api.py` -> passed
- `cd apps/web && npm run typecheck` -> passed
- `cd apps/web && npm run lint` -> passed
- `cd apps/web && npm run build` -> passed
- `cd apps/web && npx playwright test tests/e2e/admin-page.spec.ts` -> passed

### Wiring Verification Evidence
- Managed backup settings are read/written through `StorageSettingsService.update_config()` and `apps/api/src/egp_api/routes/admin.py:/v1/admin/storage`.
- Runtime document writes call `SqlDocumentRepository.store_document()`, which now uses `TenantArtifactStoreResolver.resolve_write_plan()` for primary plus optional backup storage.
- Download fallback remains on `SqlDocumentRepository.get_download_url()` and uses `managed_backup_storage_key` when provider resolution fails.
- Support/admin rendering consumes the new field through `packages/db/src/egp_db/repositories/support_repo.py -> apps/api/src/egp_api/routes/admin.py -> apps/web/src/lib/api.ts -> apps/web/src/app/(app)/admin/page.tsx`.
- Admin storage UI sends the new flag through `apps/web/src/app/(app)/admin/storage/page.tsx -> apps/web/src/lib/api.ts:updateTenantStorageSettings() -> /v1/admin/storage`.

### Behavior Changes / Risk Notes
- External-provider tenants can now opt into a managed backup copy while keeping the provider copy as primary.
- If backup writing fails, document creation fails closed and the already-uploaded external primary is cleaned up.
- If provider download resolution fails later and a backup exists, downloads fail open to the managed backup path.
- Diff generation now prefers the managed backup copy when available, which avoids provider runtime reads for internal comparison work.

### Follow-ups / Known Gaps
- No dedicated Playwright coverage was added yet for the `/admin/storage` toggle flow; current frontend verification relies on typecheck/build plus the existing admin mocked e2e spec.
- Migration `020_managed_storage_backup_dual_write.sql` still needs remote CI validation against the production-like Postgres migration runner.


## Review (2026-04-16 15:18:40 +07) - staged working tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree (staged PR8 scope)
- Commands Run: `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- packages/db/src/egp_db/repositories/document_repo.py packages/db/src/egp_db/tenant_storage_resolver.py packages/db/src/migrations/020_managed_storage_backup_dual_write.sql`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- packages/db/src/egp_db/repositories/admin_repo.py apps/api/src/egp_api/services/storage_settings_service.py apps/api/src/egp_api/routes/admin.py packages/db/src/egp_db/repositories/support_repo.py`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- apps/web/src/app/(app)/admin/storage/page.tsx apps/web/src/app/(app)/admin/page.tsx apps/web/src/lib/api.ts apps/web/tests/e2e/admin-page.spec.ts`; `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k 'managed_backup or storage_settings'`

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
- Assumed product wants the backup flag stored even for pending external-provider setups, but not for the fully managed provider.
- Assumed download fallback should only activate when a managed backup copy already exists for the document.

### Recommended Tests / Validation
- Run the full Python test suite in CI to catch any untouched storage/document interactions outside the focused slices.
- Run the migration runner against a Postgres instance and verify migration `020_managed_storage_backup_dual_write.sql` applies cleanly after migrations `017-019`.
- Consider a future mocked browser spec for `/admin/storage` if the toggle flow becomes more complex.

### Rollout Notes
- Schema change is additive: new nullable document backup key plus boolean backup flags.
- Backout is standard code rollback plus leaving the additive columns unused.
- Primary operational watch item is storage volume growth when tenants enable managed backup alongside external providers.


## CI Follow-up (2026-04-16 15:27:10 +07)

### Goal
Fix remote `Python Tests` failures caused by older storage-config test fixtures that were still inserting rows without the new `managed_backup_enabled` column.

### What Changed
- `tests/phase4/test_tenant_storage_resolver.py`
  - Updated `_seed_tenant_storage()` to insert `managed_backup_enabled` with a default false value.
- `tests/phase1/test_documents_api.py`
  - Updated `seed_external_storage()` to insert `managed_backup_enabled` with a default false value.

### TDD / Reproduction
- Remote failing signal:
  - `gh pr checks 49` showed `Python Tests` failed.
  - `CODEX_ALLOW_LARGE_OUTPUT=1 gh run view 24499806953 --job 71603376578 --log-failed` showed sqlite `NOT NULL constraint failed: tenant_storage_configs.managed_backup_enabled` in the two helpers above.
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase4/test_tenant_storage_resolver.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q -k 'google_drive_url or onedrive_url or misconfigured'`
  - `./.venv/bin/python -m pytest tests/ apps/ packages/ -v --tb=short`

### Risk Notes
- This follow-up only adjusts test fixtures to match the new schema; no runtime behavior changed.
