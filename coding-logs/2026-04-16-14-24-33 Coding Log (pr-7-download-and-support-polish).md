# PR7 Download And Support Polish

Auggie semantic search unavailable; plan is based on direct file inspection + exact-string searches.

Inspected files:
- `AGENTS.md`
- `apps/api/AGENTS.md`
- `apps/web/AGENTS.md`
- `packages/db/AGENTS.md`
- `packages/db/src/egp_db/repositories/document_repo.py`
- `apps/api/src/egp_api/services/document_ingest_service.py`
- `apps/api/src/egp_api/routes/documents.py`
- `packages/db/src/egp_db/repositories/support_repo.py`
- `apps/api/src/egp_api/services/support_service.py`
- `apps/api/src/egp_api/routes/admin.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/hooks.ts`
- `apps/web/src/app/(app)/projects/[id]/page.tsx`
- `apps/web/src/app/(app)/admin/page.tsx`
- `apps/web/tests/e2e/admin-page.spec.ts`
- `tests/phase1/test_documents_api.py`
- `tests/phase4/test_admin_api.py`

## Plan Draft A

### Overview
PR7 will tighten the user-facing and support-facing edges around external document storage without changing the underlying storage-selection model. The implementation will normalize external-provider download failures into explicit API errors, add storage-health diagnostics to support summary, and expose clearer alerts in the project detail and admin support UIs.

### Files to Change
- `apps/api/src/egp_api/routes/documents.py`: translate provider/runtime download failures into stable HTTP responses.
- `packages/db/src/egp_db/repositories/support_repo.py`: add tenant storage diagnostic summary and alert records to support output.
- `apps/api/src/egp_api/routes/admin.py`: expose the new support summary fields in the API contract.
- `apps/web/src/lib/api.ts`: extend support-summary types for storage diagnostics and alerts.
- `apps/web/src/app/(app)/admin/page.tsx`: render support storage health cards and alert callouts.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`: improve download error state messaging and retry guidance.
- `tests/phase1/test_documents_api.py`: cover external-provider download success and normalized failure behavior.
- `tests/phase4/test_admin_api.py`: cover support summary storage diagnostics and alerts.
- `apps/web/tests/e2e/admin-page.spec.ts`: optionally cover support storage alert rendering if the existing mock-driven harness stays lightweight.

### Implementation Steps
TDD sequence:
1. Add API tests for external-provider downloads and support-summary diagnostics.
2. Run those tests and confirm they fail for the right reason.
3. Implement the smallest backend changes to pass.
4. Add/update frontend rendering against the new API shape.
5. Run targeted fast gates, then broader impacted gates.

Functions and changes:
- `get_document_download_url()`: catch provider/runtime validation failures and return a 422 with a stable message instead of leaking a 500.
- `SqlSupportRepository.get_support_summary()`: join tenant storage config/credentials state into support output and compute storage-health alerts.
- `_serialize_support_summary()`: include the new diagnostics payload.
- `ProjectDetailPage.handleDownload()`: keep the current fetch flow but render stronger UI feedback when downloads fail.
- `AdminPage` support tab rendering: show storage provider, connection status, fallback posture, last validation error, and alert chips.

Expected behavior and edge cases:
- External-provider download lookup should still return provider-native URLs when the tenant configuration is healthy.
- Misconfigured or disconnected external-provider documents should fail closed with a user-visible, non-500 API error.
- Managed storage should not create noise in support alerts.
- Support diagnostics should highlight `error`, `pending_setup`, `disconnected`, and stale validation-error states.

### Test Coverage
- `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_google_drive_url_for_prefixed_storage_key`
  - Google Drive downloads resolve through provider URL.
- `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_onedrive_url_for_prefixed_storage_key`
  - OneDrive downloads resolve through provider URL.
- `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_422_when_external_provider_download_is_misconfigured`
  - Provider config failures return stable API error.
- `tests/phase4/test_admin_api.py::test_admin_support_summary_includes_storage_diagnostics_and_alerts`
  - Support summary exposes storage health payload.
- `apps/web/tests/e2e/admin-page.spec.ts::test_support_tab_shows_storage_alerts`
  - Support UI renders diagnostic alert text.

### Decision Completeness
- Goal: finish PR7 polish for download correctness, UI error states, and support diagnostics.
- Non-goals: dual-write, backup copies, provider picker UX, storage schema changes.
- Success criteria:
  - External-provider documents return correct provider download URLs.
  - Provider misconfiguration no longer surfaces as an unhandled 500.
  - Support summary exposes storage-health diagnostics and alerts.
  - Admin/project UI renders actionable storage/download error states.
- Public interfaces:
  - `GET /v1/documents/{document_id}/download` error semantics
  - `GET /v1/admin/support/tenants/{tenant_id}/summary` response schema
  - Frontend support-summary TypeScript contract
- Edge cases / failure modes:
  - Missing credentials: fail closed with 422.
  - Provider refresh/download error: fail closed with 422.
  - Managed provider: no alert unless explicitly invalid state appears.
  - No storage config row: treat as managed/healthy default.
- Rollout & monitoring:
  - No flag required; backwards-compatible additive support-summary schema.
  - Watch support tenants with `error`/`pending_setup` diagnostics after deploy.
  - Backout is code rollback only.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q -k download`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k support`
  - `cd apps/web && npm run build`

### Dependencies
- Existing tenant storage config/credential tables and resolver.
- Existing support summary endpoint and admin support page.

### Validation
- Verify API tests pass for local, Supabase, Google Drive, and OneDrive download paths.
- Verify support summary JSON includes storage diagnostics.
- Verify admin support UI and project detail build cleanly.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Download error normalization | `GET /v1/documents/{document_id}/download` | `apps/api/src/egp_api/routes/documents.py` router import in `apps/api/src/egp_api/main.py` | `documents` |
| Support storage diagnostics | `GET /v1/admin/support/tenants/{tenant_id}/summary` | `apps/api/src/egp_api/routes/admin.py` via `SupportService.get_summary()` | `tenant_storage_configs`, `tenant_storage_credentials` |
| Support storage alert UI | `AdminPage` support tab | `apps/web/src/app/(app)/admin/page.tsx` with `useSupportSummary()` | N/A |
| Project download error UI | `ProjectDetailPage.handleDownload()` | `apps/web/src/app/(app)/projects/[id]/page.tsx` calling `fetchDocumentDownloadUrl()` | N/A |

### Cross-Language Schema Verification
- Python uses `documents`, `tenant_storage_configs`, and `tenant_storage_credentials`.
- Web consumes those only through API contracts; no direct schema coupling.

### Decision-Complete Checklist
- No open implementation decisions remain.
- Public API changes are additive except for explicit 422 handling on download failures.
- Each behavior change has at least one test.
- Validation commands are scoped.
- Wiring is documented for each changed runtime path.
- Rollout/backout is specified.

## Plan Draft B

### Overview
PR7 can also be implemented as a narrower backend contract change with very thin UI updates. This version prioritizes shipping the support signal into the API with minimal frontend branching by centralizing alert generation in the backend and limiting the project page to a single stronger error banner.

### Files to Change
- `packages/db/src/egp_db/repositories/support_repo.py`: compute a preformatted alert list and a compact storage diagnostic object.
- `apps/api/src/egp_api/routes/admin.py`: expose those support summary additions.
- `apps/api/src/egp_api/routes/documents.py`: normalize download failures.
- `apps/web/src/lib/api.ts`: accept the additive support-summary shape.
- `apps/web/src/app/(app)/admin/page.tsx`: render backend-provided alerts verbatim.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`: convert inline error text into a more visible callout with retry text.
- `tests/phase1/test_documents_api.py`
- `tests/phase4/test_admin_api.py`

### Implementation Steps
TDD sequence:
1. Add the API-level red tests first.
2. Make support-summary and document-download backend changes pass.
3. Update frontend type consumers and rendering.
4. Run targeted frontend build/type gates.
5. Run formal review before commit.

Functions and changes:
- Keep `SupportService` thin and enrich `SqlSupportRepository`.
- Add small dataclasses for `storage_diagnostics` and `alerts`.
- Avoid adding frontend-only logic for alert severity derivation.

Expected behavior and edge cases:
- Backend owns alert wording and severity.
- Frontend remains mostly declarative.
- Download failures still fail closed.

### Test Coverage
- `test_document_download_endpoint_returns_google_drive_url_for_prefixed_storage_key`
  - Google Drive provider URL preserved.
- `test_document_download_endpoint_returns_onedrive_url_for_prefixed_storage_key`
  - OneDrive provider URL preserved.
- `test_document_download_endpoint_returns_422_when_external_provider_download_is_misconfigured`
  - Provider resolver errors are normalized.
- `test_admin_support_summary_includes_storage_alerts`
  - API returns storage diagnostics and alert list.

### Decision Completeness
- Goal: ship support-ready storage diagnostics with minimal frontend logic.
- Non-goals: redesign support page layout, introduce storage metrics history, dual-write.
- Success criteria:
  - API contract contains support-ready storage diagnostics and alerts.
  - Project downloads do not 500 on provider misconfiguration.
  - Frontend renders new support alerts and clearer project download failure state.
- Public interfaces:
  - Additive fields to support-summary JSON
  - 422 response path for document download failures
- Edge cases / failure modes:
  - Unknown provider state becomes warning alert.
  - Empty validation error still allows pending/disconnected alerts.
  - Managed storage stays quiet by default.
- Rollout & monitoring:
  - Backwards compatible support-summary additions.
  - Support team watches new alerts after deploy.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q -k download`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k support`
  - `cd apps/web && npm run typecheck && npm run build`

### Dependencies
- Existing support summary endpoint and tenant storage config persistence.

### Validation
- Confirm PR7 APIs remain additive and build stays green.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Download 422 normalization | document download route | `apps/api/src/egp_api/routes/documents.py` | `documents` |
| Storage diagnostics dataclasses | support summary query path | `packages/db/src/egp_db/repositories/support_repo.py` through `SupportService` and admin router | `tenant_storage_configs`, `tenant_storage_credentials` |
| Support alerts UI | admin support tab | `apps/web/src/app/(app)/admin/page.tsx` via `useSupportSummary()` | N/A |

### Cross-Language Schema Verification
- No migration needed; reuse existing storage tables and `documents`.

### Decision-Complete Checklist
- Alert generation ownership is explicit.
- Tests cover both download and support-summary changes.
- Validation commands are concrete.
- Wiring is explicit.

## Comparative Analysis & Synthesis

### Strengths
- Draft A is stronger on frontend specificity and makes the project-page UX expectations explicit.
- Draft B is leaner and keeps most alert interpretation in the backend, reducing UI branching.

### Gaps
- Draft A risks spending too much scope on frontend test harness work.
- Draft B underspecifies how the admin support page should expose raw storage metadata beyond alert text.

### Trade-offs
- Draft A favors richer UI state with more frontend logic.
- Draft B favors backend-owned support signals and a thinner UI.

### Compliance
- Both drafts follow the repo’s thin-route/service/repository layering and additive contract pattern.
- Both preserve TDD and avoid schema changes.

## Unified Execution Plan

### Overview
Implement PR7 as a backend-led polish slice: normalize external-provider download failures into stable API errors, enrich support summary with storage diagnostics plus backend-generated alerts, and update the project/admin UIs to render those signals clearly. Keep the change additive, no migration, no dual-write, and no redesign outside the affected surfaces.

### Files to Change
- `apps/api/src/egp_api/routes/documents.py`: catch provider/runtime download failures and return 422.
- `packages/db/src/egp_db/repositories/support_repo.py`: add storage diagnostics dataclasses, query tenant storage config/credential state, and emit support alerts.
- `apps/api/src/egp_api/routes/admin.py`: serialize the new support summary fields.
- `apps/web/src/lib/api.ts`: add TypeScript types for support storage diagnostics and alerts.
- `apps/web/src/app/(app)/admin/page.tsx`: render support storage diagnostics and alert banners/cards.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`: make download failures more actionable and visible while preserving the existing interaction.
- `tests/phase1/test_documents_api.py`: add external-provider download success/failure tests.
- `tests/phase4/test_admin_api.py`: add support summary storage diagnostics/alerts coverage.
- `apps/web/tests/e2e/admin-page.spec.ts`: add a lightweight mocked support-tab assertion only if the existing mock harness can cover the new UI cheaply; otherwise rely on API tests plus build/typecheck.

### Implementation Steps
TDD sequence:
1. Add `tests/phase1/test_documents_api.py` coverage for Google Drive, OneDrive, and normalized provider failure.
2. Run the focused document-download tests and confirm RED.
3. Add `tests/phase4/test_admin_api.py` coverage for support summary storage diagnostics/alerts and confirm RED.
4. Implement backend changes in `documents.py`, `support_repo.py`, and `admin.py` to pass those tests.
5. Update `apps/web/src/lib/api.ts`, `admin/page.tsx`, and `projects/[id]/page.tsx` to consume/render the new data.
6. Run targeted frontend gates and only add/update a Playwright test if the mock-driven e2e path stays narrow.
7. Run formal review, submit PR, merge, and fast-forward local `main`.

Functions and changes:
- `get_document_download_url()`: catch `ValueError` from provider-backed download resolution and map it to 422.
- `SqlSupportRepository.get_support_summary()`: query `tenant_storage_configs` plus credential presence, compute a storage diagnostic record, and synthesize alert entries for actionable support issues.
- `_serialize_support_summary()`: expose `storage_diagnostics` and `alerts`.
- `ProjectDetailPage.handleDownload()`: preserve download flow, but improve the visible failure callout text and retry guidance.
- `AdminPage` support rendering: add a storage health section showing provider, connection status, fallback enabled, credential presence, last validation error, and alert severity.

Expected behavior and edge cases:
- Provider-prefixed document keys still resolve to provider URLs.
- Bad external storage config returns 422 with a message instead of 500.
- Managed provider returns no support alerts unless data is unexpectedly inconsistent.
- Support alerts should distinguish warning vs error states and avoid duplicate noise.

### Test Coverage
- `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_google_drive_url_for_prefixed_storage_key`
  - Google Drive download URLs resolve correctly.
- `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_onedrive_url_for_prefixed_storage_key`
  - OneDrive download URLs resolve correctly.
- `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_422_when_external_provider_download_is_misconfigured`
  - External-provider resolver failures become 422s.
- `tests/phase4/test_admin_api.py::test_admin_support_summary_includes_storage_diagnostics_and_alerts`
  - Support summary exposes storage diagnostic payload.
- `apps/web/tests/e2e/admin-page.spec.ts::test_support_tab_shows_storage_alerts`
  - Optional lightweight mock-based UI coverage.

### Decision Completeness
- Goal: finish PR7 polish for external downloads, UI error states, and support diagnostics/alerts.
- Non-goals:
  - PR8 fallback/dual-write behavior
  - folder picker redesign
  - new storage metrics history or background remediation jobs
- Success criteria:
  - Google Drive and OneDrive document downloads return provider-native URLs via the API.
  - Misconfigured external-provider downloads return 422, not 500.
  - Support summary API includes storage diagnostics and alert records.
  - Admin support UI renders storage health and alerts.
  - Project detail page shows stronger actionable download failure state.
- Public interfaces:
  - `GET /v1/documents/{document_id}/download`: new 422 error path for provider misconfiguration/runtime failures.
  - `GET /v1/admin/support/tenants/{tenant_id}/summary`: additive `storage_diagnostics` and `alerts` fields.
  - `apps/web/src/lib/api.ts` support summary types updated to match.
- Edge cases / failure modes:
  - Missing credential row: fail closed with 422 on download and error alert in support.
  - Missing refresh token / OAuth config / client: fail closed with 422 and error alert.
  - `pending_setup` / `disconnected`: support warning or error alert depending on context.
  - Managed storage: no alert unless contradictory state exists.
- Rollout & monitoring:
  - No migration or flag required.
  - Watch support summary for tenants with external provider plus `error`/`pending_setup`.
  - Backout is standard code rollback.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q -k download`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k support`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run build`

### Dependencies
- Existing tenant storage settings/credentials tables and resolver behavior.
- Existing support summary endpoint and admin/project pages.

### Validation
- Verify RED then GREEN for new targeted API tests.
- Verify frontend typecheck and build pass.
- Verify `g-check` review on the staged PR7 scope before commit.
- Verify GitHub checks pass before merge.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Download failure normalization | `GET /v1/documents/{document_id}/download` | `apps/api/src/egp_api/routes/documents.py` included by `apps/api/src/egp_api/main.py` | `documents` |
| Storage diagnostics query | support summary read path | `packages/db/src/egp_db/repositories/support_repo.py` called by `apps/api/src/egp_api/services/support_service.py` | `tenant_storage_configs`, `tenant_storage_credentials` |
| Support summary serialization | `/v1/admin/support/tenants/{tenant_id}/summary` | `apps/api/src/egp_api/routes/admin.py` | additive JSON contract only |
| Support storage alerts UI | admin support tab render | `apps/web/src/app/(app)/admin/page.tsx` via `useSupportSummary()` and `fetchSupportSummary()` | N/A |
| Project download error UI | document action button | `apps/web/src/app/(app)/projects/[id]/page.tsx` via `fetchDocumentDownloadUrl()` | N/A |

### Cross-Language Schema Verification
- Verified storage/document identifiers through direct inspection:
  - `documents` in `packages/db/src/egp_db/repositories/document_repo.py`
  - `tenant_storage_configs` and `tenant_storage_credentials` already referenced by admin/storage code and tests
- No migration required.

### Decision-Complete Checklist
- No open design decisions remain for implementation.
- Every public interface change is listed.
- Every behavior change has at least one test.
- Validation commands are scoped and concrete.
- Wiring table covers each changed component.
- Rollout/backout is specified.

## Implementation Summary (2026-04-16 14:48:01 +07)

### Goal
- Finish PR7 polish for external document downloads, support diagnostics/alerts, and clearer UI error handling.

### What Changed
- `apps/api/src/egp_api/routes/documents.py`
  - Normalized provider-backed download resolution failures from `ValueError` to HTTP 422 so external storage misconfiguration no longer leaks a 500.
- `packages/db/src/egp_db/repositories/support_repo.py`
  - Added `SupportStorageDiagnostics` and `SupportAlert` records.
  - Queried tenant storage config/credential state inside `get_support_summary()`.
  - Synthesized backend-owned alert records for `error`, `disconnected`, `pending_setup`, and missing-credentials cases.
- `apps/api/src/egp_api/routes/admin.py`
  - Extended the support summary response contract with additive `storage_diagnostics` and `alerts` fields.
- `apps/web/src/lib/api.ts`
  - Added TypeScript types for support storage diagnostics and alerts.
  - Added download/storage-related error localization strings for clearer Thai UI messages.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Rendered a support-facing storage health card and alert list.
  - Polished managed-storage copy so it does not imply missing credentials for managed tenants.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`
  - Replaced the plain inline download failure text with a stronger alert callout and corrected the support guidance to the Admin `Support` tab.
  - Added explicit download button `aria-label` state.
- `apps/web/tests/e2e/admin-page.spec.ts`
  - Added a mocked support-tab browser test covering the new diagnostics and alert surfaces.
- `tests/phase1/test_documents_api.py`
  - Added provider-backed Google Drive and OneDrive download coverage.
  - Added the misconfigured external-provider download failure test.
  - Added test helpers for seeding provider config/credentials and fake provider clients.
- `tests/phase4/test_admin_api.py`
  - Added support summary coverage for `storage_diagnostics` and synthesized `alerts`.

### TDD Evidence
- Added/changed tests:
  - `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_google_drive_url_for_prefixed_storage_key`
  - `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_onedrive_url_for_prefixed_storage_key`
  - `tests/phase1/test_documents_api.py::test_document_download_endpoint_returns_422_when_external_provider_download_is_misconfigured`
  - `tests/phase4/test_admin_api.py::test_admin_support_summary_includes_storage_diagnostics_and_alerts`
  - `apps/web/tests/e2e/admin-page.spec.ts`
- RED:
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q -k 'storage_diagnostics_and_alerts'`
    - Failed because support summary did not include `storage_diagnostics` or `alerts`.
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q -k 'google_drive_url or onedrive_url or misconfigured'`
    - After fixing the new test helper, the remaining red case showed misconfigured provider-backed downloads were still surfacing as server errors instead of the desired 422 contract.
- GREEN:
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase4/test_admin_api.py -q -k 'download or storage_diagnostics_and_alerts'`
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q`
  - `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run lint`
  - `cd apps/web && npm run build`
  - `cd apps/web && npx playwright test tests/e2e/admin-page.spec.ts`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase4/test_admin_api.py -q -k 'download or storage_diagnostics_and_alerts'` -> passed
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q` -> `18 passed`
- `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q` -> `40 passed`
- `./.venv/bin/ruff check apps/api/src/egp_api/routes/documents.py apps/api/src/egp_api/routes/admin.py packages/db/src/egp_db/repositories/support_repo.py tests/phase1/test_documents_api.py tests/phase4/test_admin_api.py` -> passed
- `./.venv/bin/ruff format packages/db/src/egp_db/repositories/support_repo.py tests/phase1/test_documents_api.py tests/phase4/test_admin_api.py` -> reformatted targeted files
- `./.venv/bin/ruff format --check apps/api/src/egp_api/routes/documents.py apps/api/src/egp_api/routes/admin.py packages/db/src/egp_db/repositories/support_repo.py tests/phase1/test_documents_api.py tests/phase4/test_admin_api.py` -> passed
- `cd apps/web && npm run typecheck` -> passed
- `cd apps/web && npm run lint` -> passed
- `cd apps/web && npm run build` -> passed
- `cd apps/web && npx playwright test tests/e2e/admin-page.spec.ts` -> `2 passed`

### Wiring Verification Evidence
- `GET /v1/documents/{document_id}/download` in `apps/api/src/egp_api/routes/documents.py` still delegates through `DocumentIngestService.get_download_url()` to `SqlDocumentRepository.get_download_url()`, which resolves the provider-backed storage key before producing the final download URL.
- `GET /v1/admin/support/tenants/{tenant_id}/summary` in `apps/api/src/egp_api/routes/admin.py` still serializes the `SupportService.get_summary()` result; the new storage diagnostics and alerts are additive fields on the same runtime path.
- `apps/web/src/app/(app)/admin/page.tsx` consumes the additive support summary data only through `useSupportSummary()` / `fetchSupportSummary()`.
- `apps/web/src/app/(app)/projects/[id]/page.tsx` keeps the existing `fetchDocumentDownloadUrl()` flow and only changes the visible error state and guidance copy.

### Behavior Changes And Risks
- External-provider download failures now fail closed with 422 instead of surfacing a 500.
- Support can see storage provider state, credential presence, validation error text, and synthesized alerts from the summary endpoint.
- Managed storage remains quiet in the alert list, and the support UI copy no longer implies that managed tenants are missing credentials.
- Risk remains limited to additive support-summary consumers and provider-backed download failure semantics.

### Follow-ups / Known Gaps
- Auggie semantic search was unavailable during implementation due repeated `429 Too Many Requests`; work was completed from direct file inspection plus exact-string searches.
- Remote PR checks and merge were not yet performed in this log section; those happen in the Graphite submission phase.

## Review (2026-04-16 14:48:01 +07) - working-tree (staged PR7 scope)

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: `working-tree`
- Commands Run: `git status --short`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; targeted `git diff --staged -- <path>` for API/db/web/test files; `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q`; `./.venv/bin/python -m pytest tests/phase4/test_admin_api.py -q`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run lint`; `cd apps/web && npm run build`; `cd apps/web && npx playwright test tests/e2e/admin-page.spec.ts`

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
- Assumed the staged PR7 files are the intended review scope and unrelated local modifications outside that set remain out of scope.
- Assumed additive `storage_diagnostics` and `alerts` fields are acceptable for synchronized API/web rollout within the same PR.

### Recommended Tests / Validation
- Remote CI on the submitted PR should rerun the impacted Python and web gates before merge.
- After deploy, spot-check one tenant with external storage and one managed tenant through the admin support summary path.

### Rollout Notes
- Backwards-compatible additive support summary contract; no migration or feature flag required.
- Document download behavior changes only on provider-backed misconfiguration/runtime failure, now returning 422 instead of 500.
