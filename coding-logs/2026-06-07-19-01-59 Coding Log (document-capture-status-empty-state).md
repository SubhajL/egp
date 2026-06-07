# Document Capture Status Empty State

## Plan Draft A

### Overview
Expose the latest `document_capture_attempts` row through the existing documents API response, then let the project detail UI distinguish "still retrying" from "latest capture failed" when no documents exist. Add Prometheus instrumentation for non-success capture states so support can alert on capture health without relying on stale `project_status_events.raw_snapshot`.

### Files to Change
- `apps/api/src/egp_api/bootstrap/repositories.py`: add `document_capture_attempt_repository` to the API repository bundle.
- `apps/api/src/egp_api/bootstrap/services.py`: pass capture repository into `DocumentIngestService`.
- `packages/domain/src/egp_domain/document_ingest.py`: add latest-attempt lookup and capture-status list response shape.
- `apps/api/src/egp_api/routes/documents.py`: add response model for `capture_status`.
- `packages/observability/src/egp_observability/metrics.py`: add capture attempt non-success counter/helper.
- `tests/phase1/test_documents_api.py`: prove API returns latest attempt metadata.
- `tests/phase2/test_observability_metrics.py`: prove metric helper and alert metadata exist.
- `apps/web/src/lib/api.ts`, `apps/web/src/app/(app)/projects/[id]/page.tsx`: type and render empty-state message.
- `apps/web/tests/unit/api.test.ts`, `apps/web/tests/unit/generated-api-types.test.ts`, `apps/web/tests/e2e/projects-page.spec.ts`: update contract/UI tests.
- `infrastructure/grafana/alerts.yml`, `infrastructure/grafana/dashboard.json`: add non-success capture alert/metric reference if consistent with existing observability files.

### Implementation Steps
1. Add failing backend tests for latest attempt in `GET /v1/documents/projects/{project_id}` and capture non-success metric helper.
2. Run those tests and confirm failure from missing fields/helper.
3. Implement repository bundle wiring, domain DTO, route serialization, and metric helper.
4. Add failing frontend contract/UI tests for `capture_status` and Thai empty-state text.
5. Implement frontend copy selection from `capture_status.status`.
6. Run fast API/package/frontend gates and regenerate OpenAPI/types if required by the repo scripts.

### Test Coverage
- `test_list_documents_includes_latest_capture_attempt`: API returns latest attempt.
- `test_document_capture_non_success_metric_records_status`: metrics record non-success status.
- `generated API contract covers capture_status`: TypeScript contract accepts field.
- `projects page shows retrying empty state`: enqueued/no_documents copy.
- `projects page shows failed empty state`: failed/timeout copy.

### Decision Completeness
Goal: expose capture-attempt state for zero-document project detail views and operations metrics.
Non-goals: create the attempts table, enqueue backfill jobs, harden browser parsing, run the backlog sweep.
Success criteria: API includes latest attempt; UI shows the requested Thai states; `/metrics` includes capture non-success data; tests pass.
Public interfaces: `ListDocumentsResponse.capture_status`; Prometheus counter `egp_document_capture_attempts_total{status,outcome}`; Grafana alert using non-success statuses.
Edge cases: no attempt returns `capture_status: null`; existing documents still render normally; unknown/blank reason is optional; tenant scoping remains enforced by repository lookup.
Rollout and monitoring: backwards-compatible additive API field; no migration required because table already exists; watch capture non-success rate alert.
Acceptance checks: targeted pytest, API compile/ruff, frontend unit/e2e/typecheck/build as time permits.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Capture repository | `DocumentIngestService.list_documents_with_capture_status()` | `build_repository_bundle()` and `configure_services()` | `document_capture_attempts` |
| API field | `GET /v1/documents/projects/{project_id}` | `apps/api/src/egp_api/routes/documents.py` router included by API app | `documents`, `document_capture_attempts` |
| UI empty state | Project detail page document section | `useDocuments(id)` hook | `ListDocumentsResponse.capture_status` |
| Metric/alert | capture attempt status helper | `/metrics` via `instrument_fastapi_app()` | N/A |

## Plan Draft B

### Overview
Keep the API contract unchanged and add a separate `GET /v1/documents/projects/{project_id}/capture-status` endpoint that the frontend fetches independently. This isolates the new operational status but adds another request and another hook on every project detail page.

### Files to Change
- Same repository/service/metrics files as Draft A.
- Add a new FastAPI route and frontend fetch/hook instead of changing `ListDocumentsResponse`.

### Implementation Steps
1. Add route-specific backend tests.
2. Implement repository/service lookup and new endpoint.
3. Add frontend hook and combine loading states in the project page.
4. Add metrics/alert tests and UI tests.

### Test Coverage
- Endpoint returns latest capture status.
- Hook fetches capture status by project id.
- Empty state reacts to endpoint response.

### Decision Completeness
Goal and non-goals match Draft A.
Public interfaces: new endpoint `/v1/documents/projects/{project_id}/capture-status`; metric counter.
Edge cases: frontend must handle one request succeeding while the other fails.
Trade-off: cleaner endpoint boundary but more latency and UI state complexity.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Capture status endpoint | `GET /v1/documents/projects/{project_id}/capture-status` | documents router | `document_capture_attempts` |
| UI hook | `useDocumentCaptureStatus(id)` | project detail page | endpoint response |

## Unified Execution Plan

### Overview
Use Draft A: make `capture_status` an additive field on the existing document-list response so the UI can render a single coherent empty state without an extra request. Keep the service layer as the boundary between route and repository, and keep metrics low-cardinality.

### Files to Change
- `apps/api/src/egp_api/bootstrap/repositories.py`: bundle capture attempt repository.
- `apps/api/src/egp_api/bootstrap/services.py`: inject repository into `DocumentIngestService`.
- `packages/domain/src/egp_domain/document_ingest.py`: define `DocumentCaptureStatusSnapshot`, `DocumentListResult`, and list method.
- `apps/api/src/egp_api/routes/documents.py`: serialize `capture_status`.
- `packages/observability/src/egp_observability/metrics.py`: counter/helper for capture attempts.
- `tests/phase1/test_documents_api.py`: API behavior test.
- `tests/phase2/test_observability_metrics.py`: metrics and alert references.
- `infrastructure/grafana/alerts.yml`, `infrastructure/grafana/dashboard.json`: alert/metric references.
- `apps/web/src/lib/api.ts`: generated type usage only after OpenAPI regeneration.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`: empty-state copy.
- `apps/web/tests/unit/api.test.ts`, `apps/web/tests/unit/generated-api-types.test.ts`, `apps/web/tests/e2e/projects-page.spec.ts`: contract and UI tests.

### Implementation Steps
1. Backend RED: add tests for API `capture_status` and metric helper/alert references.
2. Backend GREEN: wire repository bundle, domain service DTOs, route response, and metric helper.
3. Frontend RED: add contract/e2e assertions for retrying and failed Thai copy.
4. Frontend GREEN: update generated API schema/types and project-page empty-state selection.
5. Refactor minimally for readable status classification.
6. Run relevant gates, then g-check, Graphite create/submit, merge PR, sync local main.

### Test Coverage
- `test_list_documents_includes_latest_capture_attempt`: API latest attempt snapshot.
- `test_list_documents_returns_null_capture_status_without_attempt`: additive null behavior.
- `test_document_capture_attempt_metric_records_non_success`: low-cardinality Prometheus helper.
- `test_grafana_alert_rules_yaml_validates`: alert includes capture non-success metric.
- `projects page shows retrying empty state`: enqueued/no_documents copy.
- `projects page shows failed empty state`: failed/timeout copy.

### Decision Completeness
Goal: replace flat zero-doc UI with attempt-driven status and add non-success observability.
Non-goals: backfill enqueuer changes, parser hardening, migration creation, production tunnel queries.
Success criteria: latest attempt drives API and UI; no attempt remains neutral; non-success metric/alert is present; targeted checks pass.
Public interfaces: additive `capture_status` on `ListDocumentsResponse`; Prometheus `egp_document_capture_attempts_total`.
Edge cases/failure modes: no attempt -> neutral empty copy; enqueued/no_documents/skipped -> retrying copy; failed/timeout -> failure copy; docs present -> document list wins; route errors still show API error. This fails open for display only and fails closed for tenant isolation through tenant-scoped repository methods.
Rollout and monitoring: additive OpenAPI field; existing clients unaffected; alert watches status labels `failed`, `timeout`, and `no_documents`.
Acceptance checks: `pytest tests/phase1/test_documents_api.py tests/phase2/test_observability_metrics.py`, `ruff check` on touched Python, `npm run test:unit`, focused Playwright if practical, `npm run typecheck`, `npm run build`.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `SqlDocumentCaptureAttemptRepository` | `DocumentIngestService.list_documents_with_capture_status()` | `RepositoryBundle.document_capture_attempt_repository` | `document_capture_attempts` |
| `capture_status` API response | `GET /v1/documents/projects/{project_id}` | documents router already included by API app | `documents`, `document_capture_attempts` |
| Project document empty state | `apps/web/src/app/(app)/projects/[id]/page.tsx` | `useDocuments(id)` in page component | generated `ListDocumentsResponse` |
| Capture attempt metric | `record_document_capture_attempt()` | Prometheus registry initialized in `instrument_fastapi_app()` | N/A |
| Grafana alert | Prometheus scrape rules | `infrastructure/grafana/alerts.yml` | metric labels |

### Cross-Language Schema Verification
The actual table is `document_capture_attempts` from `packages/db/src/migrations/027_document_capture_attempts.sql` and `packages/db/src/egp_db/repositories/document_capture_attempt_repo.py`; actual document route is `/v1/documents/projects/{project_id}` from `apps/api/src/egp_api/routes/documents.py` and generated frontend types already bind to that path.

## Implementation Summary (2026-06-07 19:07:43 +0700)

### Goal
Surface latest document capture status through the documents API/UI and add a Prometheus alertable metric for non-success capture attempts.

### What Changed
- `apps/api/src/egp_api/bootstrap/repositories.py` and `apps/api/src/egp_api/bootstrap/services.py`: wired `SqlDocumentCaptureAttemptRepository` into app state and `DocumentIngestService`.
- `packages/domain/src/egp_domain/document_ingest.py`: added `DocumentCaptureStatusSnapshot`, `DocumentListResult`, and `list_documents_with_capture_status()`.
- `apps/api/src/egp_api/routes/documents.py`: added `capture_status` to `ListDocumentsResponse` from the latest tenant-scoped attempt.
- `packages/db/src/egp_db/repositories/document_capture_attempt_repo.py`: normalized naive SQLite datetimes back to UTC and records capture-attempt metrics whenever attempts are written.
- `packages/observability/src/egp_observability/metrics.py`, compatibility exports, Grafana dashboard, and alert rules: added `egp_document_capture_attempts_total{status,outcome}` and a non-success-rate alert.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`: replaced the flat zero-document empty state with attempt-driven Thai copy.
- `apps/web/src/lib/generated/openapi.json` and `apps/web/src/lib/generated/api-types.ts`: regenerated from FastAPI.
- Tests added/updated for API behavior, metrics, generated contracts, and project-detail empty states.

### TDD Evidence
- RED backend: `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py::test_list_documents_endpoint_includes_latest_capture_attempt tests/phase2/test_observability_metrics.py::test_document_capture_attempt_metric_records_non_success_status -q` failed because `document_capture_attempt_repository` was absent from app state and `record_document_capture_attempt` did not exist.
- RED frontend: `cd apps/web && npm test -- projects-page.spec.ts -g "document capture empty state"` initially failed before assertion because the local Playwright Chromium binary was missing; installed Chromium with `npx playwright install chromium`, then used the same focused e2e as the UI behavior guard.
- GREEN backend focused: `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py::test_list_documents_endpoint_returns_persisted_documents tests/phase1/test_documents_api.py::test_list_documents_endpoint_includes_latest_capture_attempt tests/phase2/test_observability_metrics.py::test_document_capture_attempt_metric_records_non_success_status tests/phase2/test_observability_metrics.py::test_metrics_endpoint_exposes_pr01_metric_names tests/phase2/test_observability_metrics.py::test_grafana_alert_rules_yaml_validates tests/phase2/test_observability_metrics.py::test_grafana_dashboard_json_validates -q` passed.
- GREEN frontend focused: `cd apps/web && npm test -- projects-page.spec.ts -g "document capture empty state"` passed.

### Tests Run
- `./.venv/bin/ruff check packages/observability/src packages/db/src/egp_db/repositories/document_capture_attempt_repo.py packages/domain/src/egp_domain/document_ingest.py apps/api/src/egp_api/bootstrap/repositories.py apps/api/src/egp_api/bootstrap/services.py apps/api/src/egp_api/routes/documents.py tests/phase1/test_documents_api.py tests/phase2/test_observability_metrics.py` - passed.
- `./.venv/bin/python -m compileall apps/api/src packages/domain/src packages/db/src packages/observability/src` - passed.
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase1/test_document_capture_attempts.py tests/phase2/test_observability_metrics.py apps/api/tests/test_document_backfill_enqueue.py -q` - passed, 47 tests.
- `cd apps/web && npm run generate:api-types` - passed.
- `cd apps/web && npm run check:api-types` - passed.
- `cd apps/web && npm run test:unit` - passed, 33 tests.
- `cd apps/web && npm run typecheck` - passed.
- `cd apps/web && npm run lint` - passed.
- `cd apps/web && npm run build` - passed.
- `cd apps/web && npm test` - passed, 37 Playwright tests.

### Wiring Verification
- API runtime path: `GET /v1/documents/projects/{project_id}` calls `DocumentIngestService.list_documents_with_capture_status()` and serializes the latest `document_capture_attempts` row.
- Repository registration: `build_repository_bundle()` creates `document_capture_attempt_repository`; `configure_services()` stores it in app state and injects it into the domain service.
- UI runtime path: `useDocuments(id)` returns generated `ListDocumentsResponse`; project detail page renders the zero-document copy from `capture_status.status`.
- Metrics path: `SqlDocumentCaptureAttemptRepository.record_attempt()` calls `record_document_capture_attempt()`, and `/metrics` exposes the counter from the shared Prometheus registry.

### Behavior And Risk Notes
- `capture_status: null` preserves neutral copy for projects with no attempts.
- `enqueued`, `no_documents`, and `skipped` show `ยังไม่พบเอกสาร — กำลังตรวจซ้ำ`.
- `failed` and `timeout` show `ดึงเอกสารล่าสุดไม่สำเร็จ`.
- Existing document rows still take precedence over empty-state messaging.
- The API field is additive; existing clients should remain compatible.

### Follow-Ups / Known Gaps
- This does not implement parser hardening or backlog sweep; those remain P1/P2.
- The metric records process-local attempts. In multi-process deployments, Prometheus should scrape the worker/API processes that write attempts.

## Review (2026-06-07 19:10:00 +0700) - staged working tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: staged P0 document capture status API/UI/metrics changes
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --stat`; targeted staged diffs for API/domain/repository/metrics/UI/tests; `rg -n "document_capture_attempt_repository|list_documents_with_capture_status|record_document_capture_attempt|capture_status" apps/api/src packages apps/web/src/app/(app)/projects/[id]/page.tsx`; full validation commands listed in the implementation summary.
- Auggie: attempted for review context and failed with `HTTP error: 402`; review used staged diffs, exact-string wiring searches, and behavioral gates.

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
- Assumes production Prometheus scrapes the worker/API process that writes `document_capture_attempts`, since counters are process-local.
- Assumes `enqueued`, `no_documents`, and `skipped` are intentionally included in `outcome="non_success"` for the requested non-success-rate alert.

### Recommended Tests / Validation
- Already run and passing: focused API/metrics pytest, broader document/capture/observability pytest slice, ruff, compileall, OpenAPI generation/check, frontend unit, typecheck, lint, build, and full Playwright suite.

### Rollout Notes
- API change is additive (`capture_status` may be `null`); existing clients should remain compatible.
- Grafana alert can be tuned later if `enqueued` creates expected retry noise during rollout.
