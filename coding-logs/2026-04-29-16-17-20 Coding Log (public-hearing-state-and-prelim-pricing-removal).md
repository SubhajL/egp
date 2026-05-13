## Plan Draft A

### Overview
Fix project-state qualification so first-issue ZIP bundles that contain TOR files are treated as public-hearing evidence instead of invitation-only evidence. Remove the unused `prelim_pricing_seen` state from the web filter/badge surface without breaking backend compatibility or older rows.

### Files to Change
- `packages/document-classifier/src/egp_document_classifier/classifier.py`: add archive-aware artifact classification and adjust phase precedence.
- `apps/worker/src/egp_worker/browser_discovery.py`: classify downloaded artifacts before deriving project state; make public hearing outrank invitation/consulting.
- `packages/db/src/egp_db/repositories/document_repo.py`: persist worker-provided document classifications and/or reuse archive-aware classification when bytes are available.
- `packages/crawler-core/src/egp_crawler_core/project_lifecycle.py`: reorder lifecycle precedence so `open_public_hearing` comes before invitation/consulting.
- `apps/web/src/lib/constants.ts`: remove the `prelim_pricing_seen` badge label from the operator-facing surface.
- `apps/web/src/app/(app)/projects/page.tsx`: remove the `เห็นราคากลาง` filter chip and active-state membership.
- `tests/phase1/test_phase1_domain_logic.py`: add archive-aware classification tests and lifecycle-order tests.
- `tests/phase1/test_worker_browser_discovery.py`: add a failing worker-state test for first-issue ZIP/TOR bundles.
- `tests/phase1/test_document_persistence.py`: add persistence tests for ZIP bundle classification.
- `tests/phase1/test_projects_and_runs_api.py` or `apps/web` tests as needed: cover filter-surface removal if existing API/UI tests need updates.

### Implementation Steps
- TDD sequence:
  1. Add classifier tests for first-issue ZIP bundles with `Attach_TOR_*.pdf` members and confirm they currently fail.
  2. Add a worker discovery test showing such bundles currently persist `open_invitation` instead of `open_public_hearing`.
  3. Add a web projects-page expectation that `prelim_pricing_seen` is no longer exposed in filters.
  4. Implement archive-aware classification and state-priority changes.
  5. Refactor minimally to keep classification logic in shared packages, not worker-only code.
  6. Run focused fast gates, then broader touched-surface gates.
- Function outline:
  - `classify_document_details(...)`: extend to accept archive-member hints or bytes-derived markers so ZIP bundles can classify as TOR/public hearing.
  - New helper such as `_classify_archive_members(...)`: inspect ZIP entry names for TOR/hearing markers and return a stronger classification than page status text alone.
  - `open_and_extract_project(...)`: annotate downloaded documents with shared classification results before `derive_artifact_bucket(...)`.
  - `transition_state(...)` consumers: keep compatibility while allowing hearing -> invitation/consulting progression.
- Edge cases:
  - Non-ZIP files keep current behavior.
  - ZIP files with no TOR-like members fail open to current label/status logic.
  - Consulting projects with first-issue TOR bundles should still land in `open_public_hearing` when hearing evidence exists.

### Test Coverage
- `test_classify_document_detects_public_hearing_from_first_issue_zip_members`
  Public-hearing ZIP bundle outranks invitation status text.
- `test_classify_document_falls_back_when_zip_has_no_tor_members`
  Unknown ZIP members do not misclassify as hearing.
- `test_transition_state_allows_public_hearing_to_open_invitation`
  Lifecycle order reflects hearing before invitation.
- `test_open_and_extract_project_promotes_first_issue_tor_zip_to_public_hearing`
  Worker persists hearing state from classified downloads.
- `test_store_document_classifies_first_issue_tor_zip_as_public_hearing_tor`
  Persisted document metadata matches archive evidence.
- `test_projects_page_does_not_expose_prelim_pricing_filter`
  Removed filter cannot be selected from UI state.

### Decision Completeness
- Goal:
  - Make first-issue ZIP bundles with TOR members qualify projects as `open_public_hearing`.
  - Make public hearing precede invitation and consulting in lifecycle ordering.
  - Remove `เห็นราคากลาง` from the operator-facing filter/badge surface.
- Non-goals:
  - No DB migration to delete `prelim_pricing_seen` enum rows/constraints yet.
  - No attempt to infer hearing from remote web lookups outside existing artifacts.
  - No redesign of winner/close-check behavior.
- Success criteria:
  - Sample ZIP bundles like `69049117648_20042569.zip` classify as TOR/public-hearing evidence in tests.
  - Worker discovery test persists `open_public_hearing` for first-issue TOR bundles.
  - Projects page no longer offers the `เห็นราคากลาง` filter/badge.
- Public interfaces:
  - No new API endpoints or env vars.
  - Shared classification behavior changes for artifact ingestion.
  - Web status filter list changes by removing one option.
- Edge cases / failure modes:
  - Fail open for unreadable/corrupt ZIPs by keeping old label/status-based classification.
  - Preserve backend compatibility for old `prelim_pricing_seen` rows even though the UI stops exposing them.
- Rollout & monitoring:
  - No feature flag; behavior changes are internal and deterministic.
  - Watch for projects flipping from `open_invitation` to `open_public_hearing` on recrawl.
  - Check document metadata for ZIP bundles after reruns.
- Acceptance checks:
  - `pytest` focused suites pass with new classification expectations.
  - Web typecheck/lint/build pass with removed filter option.

### Dependencies
- Python stdlib `zipfile` for archive-member inspection.
- Existing shared classifier and worker discovery tests.

### Validation
- Re-run the four sample project artifacts through classification-oriented tests.
- Optionally manual-recrawl one matching keyword and confirm projects land in `ประชาพิจารณ์`.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Archive-aware classifier | `build_document_record()` and worker discovery pre-persist path | imports in `document_repo.py` and `browser_discovery.py` | `documents.document_type`, `documents.document_phase` |
| Public-hearing project-state promotion | `open_and_extract_project()` discovery payload | worker discovery payload passed through `DiscoveredProjectEvent` to `ProjectIngestService` | `projects.project_state`, `project_status_events.normalized_status` |
| Web filter removal | Projects page render/query state | `apps/web/src/app/(app)/projects/page.tsx` using `fetchProjects()` | none |

### Cross-Language Schema Verification
- Python uses `projects.project_state` and `documents.document_type/document_phase` in `packages/db/src/egp_db/repositories/project_repo.py` and `document_repo.py`.
- SQL constraint source is `packages/db/src/migrations/001_initial_schema.sql`.
- No Go/other runtime schema consumers in this repo slice.

### Decision-Complete Checklist
- No open interface decisions remain.
- Each behavior change has explicit tests.
- Validation commands are scoped to worker/classifier/web changes.
- Wiring points are named.

## Plan Draft B

### Overview
Apply the minimal product fix by recognizing `ฉบับแรก ...zip` as public-hearing evidence directly from source labels/file names, then remove the unused `prelim_pricing_seen` web surface. This is less general than full archive inspection but faster to land.

### Files to Change
- `packages/document-classifier/src/egp_document_classifier/classifier.py`
- `apps/worker/src/egp_worker/browser_discovery.py`
- `packages/crawler-core/src/egp_crawler_core/project_lifecycle.py`
- `apps/web/src/lib/constants.ts`
- `apps/web/src/app/(app)/projects/page.tsx`
- Targeted tests in `tests/phase1`

### Implementation Steps
- TDD sequence:
  1. Add failing tests for `ฉบับแรก ...zip` labels.
  2. Promote those labels to public-hearing TOR classification.
  3. Remove `prelim_pricing_seen` from web filters and rerun frontend gates.
- Function outline:
  - Extend classifier markers to treat `ฉบับแรก` ZIP labels as public hearing.
  - Update worker state promotion to rely on classified documents rather than raw status-first fallback.
- Edge cases:
  - Might miss ZIP bundles whose labels are not `ฉบับแรก`.
  - Avoids ZIP byte inspection, so implementation is simpler but less complete.

### Test Coverage
- `test_classify_document_treats_first_issue_zip_as_public_hearing`
- `test_open_and_extract_project_promotes_first_issue_zip_to_public_hearing`
- `test_projects_page_does_not_expose_prelim_pricing_filter`

### Decision Completeness
- Goal:
  - Fix the known misclassification pattern from the sample projects.
- Non-goals:
  - General archive-member inspection.
- Success criteria:
  - Sample labels classify as hearing.
- Public interfaces:
  - Web filter list change only.
- Edge cases / failure modes:
  - Fail open for labels outside the `ฉบับแรก` pattern.
- Rollout & monitoring:
  - Lightweight release; validate with sample projects.
- Acceptance checks:
  - Focused tests and frontend gates pass.

### Dependencies
- No new dependencies.

### Validation
- Re-run focused classifier and worker discovery tests.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| First-issue ZIP classifier rule | shared classifier calls | `document_repo.py`, worker callers | `documents`, `projects` |
| Web filter removal | projects page state/query build | `projects/page.tsx` | none |

### Cross-Language Schema Verification
- No schema changes.

### Decision-Complete Checklist
- Minimal but incomplete for non-`ฉบับแรก` bundles.

## Comparative Analysis & Synthesis

### Strengths
- Draft A is more robust because it uses real ZIP member evidence and fixes the exact root cause shown by the sample artifacts.
- Draft B is faster but depends on a label convention that may not hold for all bundles.

### Gaps
- Draft B would still miss TOR bundles whose labels are generic but whose contents clearly contain TOR files.
- Draft A needs slightly more implementation effort because classification must accept archive-member evidence.

### Trade-offs
- Draft A adds shared artifact-intelligence but keeps logic centralized and reusable.
- Draft B minimizes code churn but bakes business meaning into one Thai label pattern.

### Compliance
- Draft A better matches the repo guidance to keep shared/domain logic in shared packages and avoid worker-only product-state ownership.

## Unified Execution Plan

### Overview
Implement the robust fix from Draft A: teach shared classification to understand ZIP member names, use that classification in worker discovery before project persistence, reorder lifecycle precedence so hearing can precede invitation/consulting, and remove the unused `prelim_pricing_seen` operator surface from the web app. Keep backend compatibility for old rows by not deleting enum values or changing SQL constraints in this pass.

### Files to Change
- `packages/document-classifier/src/egp_document_classifier/classifier.py`
  Add archive-aware classification helpers and prefer ZIP/TOR evidence over page invitation status.
- `packages/db/src/egp_db/repositories/document_repo.py`
  Thread archive-aware classification through persisted document creation.
- `apps/worker/src/egp_worker/browser_discovery.py`
  Pre-classify downloaded documents and derive project artifact bucket/state from typed documents, not labels only.
- `packages/crawler-core/src/egp_crawler_core/project_lifecycle.py`
  Reorder `OPEN_PUBLIC_HEARING` before invitation/consulting.
- `apps/web/src/lib/constants.ts`
  Remove `prelim_pricing_seen` badge label.
- `apps/web/src/app/(app)/projects/page.tsx`
  Remove `prelim_pricing_seen` from active/filter state.
- `tests/phase1/test_phase1_domain_logic.py`
- `tests/phase1/test_document_persistence.py`
- `tests/phase1/test_worker_browser_discovery.py`
- `apps/web` tests only if existing assertions need updates.

### Implementation Steps
- TDD sequence:
  1. Add failing shared-classifier tests for first-issue ZIP bundles containing `Attach_TOR_*.pdf`, `TOR*.pdf`, or other TOR member names.
  2. Add a failing worker discovery test proving such downloads currently persist `open_invitation`.
  3. Add a failing lifecycle-order test for hearing -> invitation progression.
  4. Add/update a frontend test or direct state assertion that the `เห็นราคากลาง` filter is gone.
  5. Implement archive-aware classification in the shared classifier.
  6. Annotate worker downloaded documents with `document_type` / `document_phase` before artifact-bucket derivation.
  7. Update worker promotion to derive state from typed documents.
  8. Reorder lifecycle precedence to allow hearing to come first.
  9. Remove `prelim_pricing_seen` from the web filter/badge surface.
  10. Run focused then broader gates.
- Function names / behavior:
  - `classify_document_details(...)`
    Accept archive-member-derived evidence and return public-hearing TOR when ZIP contents show TOR artifacts that should seed the baseline state.
  - New archive helper such as `_classify_archive_member_names(...)`
    Inspect ZIP filenames only; no PDF text extraction required.
  - `open_and_extract_project(...)`
    Convert raw downloaded-doc payloads into classified payloads before `derive_artifact_bucket`.
  - `transition_state(...)`
    Respect new ordering with hearing before invitation/consulting.
- Expected behavior:
  - First-issue ZIP bundles containing TOR members become public-hearing evidence.
  - Projects like `69049117648`, `69049270918`, `69029348057`, and `68129320155` will qualify as `ประชาพิจารณ์` after recrawl/reprocessing.
  - `เห็นราคากลาง` disappears from the UI filter set.

### Test Coverage
- `test_classify_document_detects_public_hearing_from_zip_tor_members`
  ZIP member names imply public-hearing TOR.
- `test_classify_document_zip_invitation_status_does_not_override_tor_members`
  Invitation page status loses to hearing/TOR bundle evidence.
- `test_transition_state_allows_public_hearing_before_open_invitation`
  Lifecycle order changed correctly.

## 2026-04-29 17:40:21 +07

### Goal
Implement the public-hearing fix so first-issue ZIP bundles with TOR members promote projects to `open_public_hearing`, reorder lifecycle precedence to put public hearing before invitation/consulting, and remove the stale `เห็นราคากลาง` filter from the web projects page.

### What Changed
- `packages/document-classifier/src/egp_document_classifier/classifier.py`
  Added ZIP-aware classification using archive member names, added first-issue markers, and threaded `file_bytes` through `classify_document_details()` / `classify_document()`. A bundle like `ฉบับแรก ...zip` with TOR members now classifies as `DocumentType.TOR` + `DocumentPhase.PUBLIC_HEARING` even when the source status text still says invitation.
- `packages/db/src/egp_db/repositories/document_repo.py`
  Passed `file_bytes` into shared classification during both draft record construction and persisted document storage, so DB metadata now reflects the same archive-aware rule as live discovery.
- `packages/crawler-core/src/egp_crawler_core/project_lifecycle.py`
  Reordered `_STATE_ORDER` so `open_public_hearing` precedes `open_invitation` and `open_consulting`, allowing hearing -> invitation progression without tripping the lifecycle guard.
- `apps/worker/src/egp_worker/browser_discovery.py`
  Added `_classify_downloaded_documents()`, annotated downloaded document payloads with `document_type` / `document_phase`, switched artifact-bucket derivation to `derive_artifact_bucket(documents=...)`, and carried typed document snapshots into the raw payload. This moves project-state promotion off raw labels and onto shared document evidence.
- `apps/web/src/app/(app)/projects/page.tsx`
  Removed `prelim_pricing_seen` from the active-state set and from the rendered status filters, so `เห็นราคากลาง` is no longer selectable in the projects UI.
- `tests/phase1/test_phase1_domain_logic.py`
  Added RED/GREEN coverage for hearing-before-invitation lifecycle ordering and first-issue ZIP/TOR classification.
- `tests/phase1/test_document_persistence.py`
  Added persistence coverage proving ZIP bundles classify as public-hearing TOR during storage.
- `tests/phase1/test_worker_browser_discovery.py`
  Added worker coverage proving first-issue TOR ZIP bundles promote the project to `open_public_hearing`, and updated an older expectation because downloaded-document payloads now carry typed evidence.

### TDD Evidence
- Added/changed tests:
  - `test_transition_state_accepts_public_hearing_to_open_invitation`
  - `test_classify_document_detects_public_hearing_from_first_issue_zip_members`
  - `test_open_and_extract_project_promotes_first_issue_tor_zip_to_public_hearing`
  - `test_store_document_classifies_first_issue_tor_zip_as_public_hearing`
  - `projects page does not expose the prelim pricing filter`
- RED commands and key failures:
  - `./.venv/bin/python -m pytest tests/phase1/test_phase1_domain_logic.py -q -k 'public_hearing_to_open_invitation or first_issue_zip_members'`
    Failed because `transition_state()` rejected `open_public_hearing -> open_invitation` and `classify_document()` had no `file_bytes` support.
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'first_issue_tor_zip_to_public_hearing'`
    Failed because the worker derived `ArtifactBucket.NO_ARTIFACT_EVIDENCE` from raw labels and left the project in `open_invitation`.
  - `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q -k 'first_issue_tor_zip_as_public_hearing'`
    Failed because persisted ZIP documents classified as `invitation/unknown` instead of `tor/public_hearing`.
  - `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts --grep 'prelim pricing filter'`
    No useful RED signal was available here; the targeted UI test already passed before the source edit, so the web-side change was validated with a passing check rather than a failing-to-passing transition.
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase1/test_phase1_domain_logic.py -q -k 'public_hearing_to_open_invitation or first_issue_zip_members'`
  - `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q -k 'first_issue_tor_zip_as_public_hearing'`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'first_issue_tor_zip_to_public_hearing or does_not_use_signal_timeout_wrapper or no_documents'`
  - `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts --grep 'prelim pricing filter'`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase1/test_phase1_domain_logic.py tests/phase1/test_document_persistence.py tests/phase1/test_worker_browser_discovery.py -q`
  Result: `119 passed`
- `./.venv/bin/python -m ruff check packages/document-classifier/src/egp_document_classifier/classifier.py packages/db/src/egp_db/repositories/document_repo.py packages/crawler-core/src/egp_crawler_core/project_lifecycle.py apps/worker/src/egp_worker/browser_discovery.py tests/phase1/test_phase1_domain_logic.py tests/phase1/test_document_persistence.py tests/phase1/test_worker_browser_discovery.py`
  Result: passed
- `cd apps/web && npm run typecheck`
  Result: passed
- `cd apps/web && npm run lint`
  Result: passed
- `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts --grep 'prelim pricing filter'`
  Result: `1 passed`

### Wiring Verification
- Archive-aware classification now flows through `build_document_record()` and `SqlDocumentRepository.store_document()` via the new `file_bytes` argument at `packages/db/src/egp_db/repositories/document_repo.py:424` and `packages/db/src/egp_db/repositories/document_repo.py:887`.
- Live discovery now classifies downloaded documents before project promotion in `apps/worker/src/egp_worker/browser_discovery.py:895`, uses typed evidence for artifact-bucket derivation at `apps/worker/src/egp_worker/browser_discovery.py:926`, and reuses the same path for late document collection at `apps/worker/src/egp_worker/browser_discovery.py:1065` and `apps/worker/src/egp_worker/browser_discovery.py:1100`.
- The stale UI filter was removed from the project list source-of-truth in `apps/web/src/app/(app)/projects/page.tsx`.

### Behavior Changes And Risk Notes
- First-issue ZIP bundles with TOR member names now outrank invitation-page status and classify as public-hearing evidence. This is fail-open for unreadable ZIPs: corrupt or non-ZIP bytes still fall back to the old label/status behavior.
- Project-state promotion is now more evidence-driven and may cause recrawled projects previously stored as `open_invitation` to move to `open_public_hearing`.
- `prelim_pricing_seen` remains in backend enums/schema for compatibility, but the operator-facing filter surface no longer exposes it.

### Follow-Ups / Known Gaps
- Existing persisted rows will only change after recrawl or explicit reprocessing; this patch does not backfill historical project states.
- Auggie semantic search was unavailable during implementation (`HTTP 429 Too Many Requests`), so the work used direct file inspection plus exact-string searches.
- `test_store_document_classifies_first_issue_zip_as_public_hearing_tor`
  Persisted metadata follows archive evidence.
- `test_open_and_extract_project_promotes_zip_tor_bundle_to_open_public_hearing`
  Worker payload state is corrected pre-persist.
- `test_projects_page_does_not_list_prelim_pricing_seen_filter`
  Web surface is simplified.

### Decision Completeness
- Goal:
  - Correct misclassified sample projects by recognizing TOR ZIP bundles as public-hearing evidence.
  - Move public hearing earlier than invitation/consulting in lifecycle precedence.
  - Remove the unused prelim-pricing operator surface.
- Non-goals:
  - No SQL migration to remove the enum/constraint this pass.
  - No bulk backfill job in this change.
  - No new artifact text extraction pipeline.
- Success criteria:
  - New RED tests fail before implementation and pass after.
  - Worker and persistence tests classify sample-shaped ZIP bundles as public hearing.
  - `prelim_pricing_seen` is absent from projects page filters/badges.
- Public interfaces:
  - No new endpoint/schema/env var.
  - Shared artifact classification semantics change.
  - Web filter options change.
- Edge cases / failure modes:
  - Corrupt ZIPs: fail open to old classifier behavior.
  - ZIPs with no TOR-like member names: keep old behavior.
  - Existing stored `prelim_pricing_seen` rows remain queryable via API if directly requested, but the main UI no longer exposes that path.
- Rollout & monitoring:
  - No feature flag.
  - Reprocess via future recrawls; no destructive data migration.
  - Watch project-state distribution and document classification in worker logs for hearing promotions.
- Acceptance checks:
  - `./.venv/bin/python -m pytest ...` focused suites pass.
  - `./.venv/bin/python -m ruff check ...`
  - `cd apps/web && npm run typecheck && npm run lint && npm run build`

### Dependencies
- Python stdlib `zipfile`.
- Existing shared classifier / worker / persistence test harnesses.

### Validation
- Automated tests for shared classification, worker discovery, and persistence.
- Optional manual spot-check: recrawl the `ระบบสารสนเทศ` keyword and verify the four sample projects render `ประชาพิจารณ์`.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| Archive-aware document classifier | `build_document_record()` and worker discovery download processing | `packages/db/src/egp_db/repositories/document_repo.py`, `apps/worker/src/egp_worker/browser_discovery.py` | `documents.document_type`, `documents.document_phase` |
| Hearing-first project-state promotion | `open_and_extract_project()` -> `DiscoveredProjectEvent` -> `ProjectIngestService.ingest_discovered_project()` | `apps/worker/src/egp_worker/workflows/discover.py`, `apps/api/src/egp_api/services/project_ingest_service.py` | `projects.project_state`, `project_status_events.normalized_status` |
| Web prelim-pricing removal | Projects filter render and query builder | `apps/web/src/app/(app)/projects/page.tsx`, `apps/web/src/lib/constants.ts` | none |

### Cross-Language Schema Verification
- Python schema consumers:
  - `packages/db/src/egp_db/repositories/project_repo.py` uses `projects.project_state`.
  - `packages/db/src/egp_db/repositories/document_repo.py` uses `documents.document_type` and `documents.document_phase`.
- SQL constraint source:
  - `packages/db/src/migrations/001_initial_schema.sql`
- No additional language runtimes to sync in this repo slice.

### Decision-Complete Checklist
- No open decisions remain for implementation.
- Public behavior changes are listed.
- Each behavior change has a concrete failing test path.
- Validation commands are scoped.
- Wiring points are explicit.


## 2026-05-01 19:27:09 +0700 - Forgot password delivery failure visibility

### Goal
- Fix the forgot-password flow so it no longer reports success when reset email delivery is impossible in the current environment.

### What Changed
- `apps/api/src/egp_api/services/auth_service.py`
  - Added a delivery-capability guard before creating password-reset tokens.
  - Logged a warning and raised `RuntimeError("email delivery is not configured")` when reset email delivery is unavailable.
  - Reused a public notification-service capability check instead of introspecting private fields.
- `apps/api/src/egp_api/routes/auth.py`
  - Updated `POST /v1/auth/password/forgot` to translate missing email-delivery configuration into `503` with `code=email_delivery_not_configured`, matching the email-verification route behavior.
- `packages/notification-core/src/egp_notifications/service.py`
  - Added `email_delivery_configured()` to expose whether SMTP or an injected sender is available.
- `tests/phase4/test_auth_api.py`
  - Added regression coverage proving forgot-password now fails closed with `503` and does not create unusable `password_reset` tokens when delivery is unavailable.
- `apps/web/tests/e2e/auth-pages.spec.ts`
  - Added a browser test proving the forgot-password page surfaces the localized delivery-configuration error instead of the generic success banner.

### TDD Evidence
- Added/changed tests:
  - `test_forgot_password_returns_503_when_email_delivery_is_not_configured`
  - `forgot-password page shows email delivery configuration errors`
- RED command:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
- RED failure reason:
  - `test_forgot_password_returns_503_when_email_delivery_is_not_configured` failed because the route still returned `202` instead of `503`.
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
  - `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts --grep 'forgot-password page (submits a generic reset request|shows email delivery configuration errors)'`

### Tests Run
- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q` → passed (`25 passed`)
- `./.venv/bin/python -m ruff check apps/api/src/egp_api/routes/auth.py apps/api/src/egp_api/services/auth_service.py packages/notification-core/src/egp_notifications/service.py tests/phase4/test_auth_api.py` → passed
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts --grep 'forgot-password page (submits a generic reset request|shows email delivery configuration errors)'` → passed (`2 passed`)
- `cd apps/web && npm run typecheck` → passed
- `cd apps/web && npm run lint` → passed

### Wiring Verification Evidence
- Frontend submit path remains `apps/web/src/app/forgot-password/page.tsx` → `requestPasswordReset()` in `apps/web/src/lib/api.ts`.
- API route `POST /v1/auth/password/forgot` in `apps/api/src/egp_api/routes/auth.py` now catches delivery-configuration errors and returns `503`.
- Service path `AuthService.request_password_reset()` in `apps/api/src/egp_api/services/auth_service.py` now refuses to mint reset tokens when `NotificationService.email_delivery_configured()` is false.
- App wiring still injects `NotificationService` into `AuthService` from `apps/api/src/egp_api/main.py`.

### Behavior Changes and Risk Notes
- Behavior change:
  - Forgot-password now fails closed with `503` when email delivery is not configured, instead of returning a misleading generic success response.
- Safety improvement:
  - No unusable `password_reset` tokens are stored when delivery cannot happen.
- Risk note:
  - In local/dev environments without SMTP or an injected email sender, password resets will now surface an explicit configuration error until mail delivery is configured.
- Discovery note:
  - Auggie semantic search was unavailable due to `429 Too Many Requests`; implementation used direct file inspection plus targeted tests.

### Follow-ups / Known Gaps
- This fix makes the failure explicit; it does not configure SMTP for the local environment.
- If local password-reset testing needs to work without SMTP, a separate dev-only outbox/preview mechanism should be added intentionally rather than silently dropping mail.

## Review (2026-05-01 19:27:09 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree (forgot-password delivery visibility changes only)
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/routes/auth.py apps/api/src/egp_api/services/auth_service.py packages/notification-core/src/egp_notifications/service.py tests/phase4/test_auth_api.py apps/web/tests/e2e/auth-pages.spec.ts`; `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`; `./.venv/bin/python -m ruff check apps/api/src/egp_api/routes/auth.py apps/api/src/egp_api/services/auth_service.py packages/notification-core/src/egp_notifications/service.py tests/phase4/test_auth_api.py`; `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts --grep 'forgot-password page (submits a generic reset request|shows email delivery configuration errors)'`; `cd apps/web && npm run typecheck`; `cd apps/web && npm run lint`

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
- Assumed the desired product behavior is to fail closed when SMTP/email sending is unavailable, matching the existing email-verification route.
- Assumed existing unrelated working-tree changes are out of scope for this review.

### Recommended Tests / Validation
- Configure SMTP (or inject a test sender) and verify `POST /v1/auth/password/forgot` returns `202` and delivers a real reset email.
- Manual UI check: submit `/forgot-password` in the current local environment and confirm the Thai configuration error renders.

### Rollout Notes
- No schema or migration changes.
- Existing local environments without email delivery configured will now show a clear operator-facing error instead of a false success banner.

## 2026-05-01 20:00:09 +07 - SMTP environment wiring

### Goal of the change
- Make the API process able to receive SMTP configuration from local runtime environment setup, especially the Docker Compose `api` service used in development.

### What changed (by file) and why
- `docker-compose.yml`
  Added `EGP_SMTP_HOST`, `EGP_SMTP_PORT`, `EGP_SMTP_USERNAME`, `EGP_SMTP_PASSWORD`, `EGP_SMTP_FROM`, and `EGP_SMTP_USE_TLS` to the `api` service environment so the container can consume SMTP settings already expected by `apps/api/src/egp_api/config.py`.
- `.env.example`
  Added a checked-in example showing the exact SMTP keys and Gmail-compatible defaults for `vbs.pod@gmail.com`, while keeping the actual secret out of git.

### TDD evidence
- RED command:
  Not produced. This was a runtime wiring/configuration change with no existing automated harness around local env-file propagation.
- GREEN command:
  `docker compose config | rg -n "EGP_SMTP_(HOST|PORT|USERNAME|PASSWORD|FROM|USE_TLS)" -C 1`

### Tests run (exact commands) and results
- `docker compose config | rg -n "EGP_SMTP_(HOST|PORT|USERNAME|PASSWORD|FROM|USE_TLS)" -C 1`
  Passed. Verified the `api` service now includes all SMTP environment variables in resolved Compose config.
- `sed -n '1,120p' .env.example`
  Passed. Verified the example file contains the expected SMTP keys and values.

### Wiring verification evidence
- `apps/api/src/egp_api/config.py:get_smtp_config()` reads `EGP_SMTP_HOST`, `EGP_SMTP_PORT`, `EGP_SMTP_USERNAME`, `EGP_SMTP_PASSWORD`, `EGP_SMTP_FROM`, and `EGP_SMTP_USE_TLS` directly from process environment.
- `apps/api/src/egp_api/main.py:create_app()` constructs `NotificationService(smtp_config=get_smtp_config(...))`, so once the API process sees those variables, password-reset and verification email paths use them automatically.
- `docker-compose.yml` now forwards those variables into the `api` container, closing the previous gap where Compose-based API runs could not see SMTP settings.

### Behavior changes and risk notes
- Compose-based local API runs can now send email once valid SMTP credentials are provided in the environment.
- Actual delivery still depends on a valid Gmail app password; leaving `EGP_SMTP_PASSWORD` as a placeholder will fail authentication at send time.
- Local bare-`uvicorn` runs still require the shell environment to be populated before launch.

### Follow-ups / known gaps
- No `.env` file was created with secrets, by design.
- If the local workflow should auto-load `.env` for bare-`uvicorn` runs, that should be added explicitly in a separate change rather than assumed.

## Review (2026-05-01 20:00:09 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree (`docker-compose.yml` and `.env.example` SMTP wiring only)
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- docker-compose.yml`; `nl -ba docker-compose.yml | sed -n '50,90p'`; `nl -ba .env.example | sed -n '1,40p'`; `docker compose config | rg -n "EGP_SMTP_(HOST|PORT|USERNAME|PASSWORD|FROM|USE_TLS)" -C 1`

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
- Assumed local development uses either Docker Compose or shell-exported env vars and that documenting both paths is sufficient for this turn.
- Assumed `vbs.pod@gmail.com` is intended to authenticate directly against Gmail SMTP using an app password.

### Recommended Tests / Validation
- Create a local ignored `.env` with the real Gmail app password, restart the API, and submit a password-reset request for `vbs.pod@gmail.com`.
- If running the API outside Docker Compose, launch with `set -a; source .env; set +a` before starting `uvicorn`.

### Rollout Notes
- No code-path or schema changes beyond environment wiring.
- Gmail delivery depends on Google account settings: 2-Step Verification enabled and an app password generated for SMTP use.
