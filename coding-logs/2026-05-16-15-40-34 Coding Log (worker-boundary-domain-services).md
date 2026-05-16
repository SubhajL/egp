# Worker Boundary Domain Services

## Planning Notes

Auggie semantic search was attempted first for worker/API boundary details and returned HTTP 429, so this plan is based on direct file inspection plus exact-string searches. Inspected files include `AGENTS.md`, `CLAUDE.md`, `apps/worker/AGENTS.md`, `apps/api/AGENTS.md`, `packages/AGENTS.md`, `apps/worker/src/egp_worker/project_event_sink.py`, `apps/worker/src/egp_worker/workflows/document_ingest.py`, `apps/worker/src/egp_worker/workflows/discover.py`, `apps/worker/src/egp_worker/workflows/close_check.py`, `apps/api/src/egp_api/services/project_ingest_service.py`, `apps/api/src/egp_api/services/document_ingest_service.py`, `apps/api/src/egp_api/routes/project_ingest.py`, `apps/api/src/egp_api/routes/documents.py`, `apps/api/src/egp_api/bootstrap/services.py`, and related tests.

## Plan Draft A - Shared Domain Services Package

### Overview

Extract project ingest and document ingest services from `egp_api.services` into a shared package. The API remains the control-plane HTTP owner, while workers depend only on the shared domain package plus repository interfaces for local persistence paths.

### Files to Change

- `packages/domain/src/egp_domain/project_ingest.py`: shared project ingest service and factory.
- `packages/domain/src/egp_domain/document_ingest.py`: shared document ingest service and download link model.
- `packages/domain/src/egp_domain/__init__.py`: side-effect-free package marker.
- `pyproject.toml`: include `egp_domain` in monorepo package discovery.
- `apps/api/src/egp_api/services/project_ingest_service.py`: compatibility re-export.
- `apps/api/src/egp_api/services/document_ingest_service.py`: compatibility re-export.
- `apps/api/src/egp_api/bootstrap/services.py`: import shared services directly.
- `apps/api/src/egp_api/routes/project_ingest.py`: import shared project ingest service directly.
- `apps/api/src/egp_api/routes/documents.py`: import shared document ingest service directly.
- `apps/worker/src/egp_worker/project_event_sink.py`: remove API service imports; use shared project ingest.
- `apps/worker/src/egp_worker/workflows/document_ingest.py`: use shared document ingest.
- Tests under `tests/phase1` / `tests/phase3`: lock the worker boundary and monkeypatch target.

### Implementation Steps

TDD sequence:
1. Add tests that fail while worker imports `egp_api.services.*`.
2. Run focused tests and confirm failure identifies the ambiguous boundary.
3. Add `egp_domain` package and move shared service implementations.
4. Update API and worker imports to the shared package.
5. Keep compatibility wrappers for current external imports.
6. Run focused tests, ruff, compileall, and g-check.

Functions/classes:
- `egp_domain.project_ingest.ProjectIngestService`: accepts worker-emitted project events and owns repository state transitions.
- `egp_domain.project_ingest.create_project_ingest_service`: builds a service from a database URL and optional dispatcher.
- `egp_domain.document_ingest.DocumentIngestService`: owns canonical document ingest/review/download operations through repository interfaces.
- `egp_domain.document_ingest.DocumentDownloadLink`: carries direct download metadata.

Expected behavior and edge cases:
- Worker imports no `egp_api.services` modules.
- API still exposes the same public endpoints and app state names.
- Existing imports from old API service modules continue via compatibility wrappers.
- Tenant scoping remains delegated to existing repository calls.

### Test Coverage

- `test_worker_boundary_imports_no_api_services`: worker code avoids API service imports.
- `test_worker_document_ingest_routes_through_canonical_service_boundary`: worker delegates through shared canonical service.
- Existing `test_project_ingest_*_endpoint_*`: API routes still use same contracts.
- Existing worker workflow tests: project ingest sink still persists events.

### Decision Completeness

Goal: make the worker boundary explicit by choosing shared domain services with narrow interfaces.

Non-goals: no DB schema changes, no new production HTTP endpoints, no Graphite stack refactor, no legacy crawler changes.

Success criteria: no worker import references to `egp_api.services`; API and worker tests pass; package discovery includes `egp_domain`; existing HTTP contracts remain unchanged.

Public interfaces: Python import surface adds `egp_domain.document_ingest` and `egp_domain.project_ingest`; existing API service module imports remain compatibility surfaces. No endpoint, env var, CLI, or migration changes.

Failure modes: missing package discovery fails import closed at compile/test time; missing repository dependencies fail closed via existing constructor/runtime errors; invalid project transitions keep existing ValueError/KeyError behavior; transport errors on internal API sink remain unchanged.

Rollout and monitoring: Python-only refactor with no migration. Watch existing document ingest logs (`document_ingest_canonical_*`) and project status event persistence. Backout is reverting imports/wrappers because runtime contracts remain unchanged.

Acceptance checks: focused pytest for boundary, project ingest, worker workflows, document contract; `ruff check`; `python -m compileall apps packages`.

### Dependencies

Existing package paths from root `pyproject.toml`; no new third-party dependency.

### Validation

Run focused tests first, then relevant API/worker package gates.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `egp_domain.project_ingest.ProjectIngestService` | API internal worker routes and worker service-backed sink | `apps/api/bootstrap/services.py`, `apps/worker/project_event_sink.py` | `projects`, `project_status_events`, `notifications` through repositories |
| `egp_domain.document_ingest.DocumentIngestService` | API document routes and worker document ingest workflow | `apps/api/bootstrap/services.py`, `apps/worker/workflows/document_ingest.py` | `documents`, `document_diffs`, `document_reviews`, `audit_log` through repositories |
| Compatibility wrappers | Existing imports from `egp_api.services.*` | module-level re-export files | N/A |

### Cross-Language Schema Verification

No migration or schema rename is planned. Existing references use repository constants and tables; no SQL literals are changed.

### Decision-Complete Checklist

- No open decisions remain.
- Public interfaces are listed.
- Behavior change has a boundary test.
- Validation commands are scoped.
- Wiring table covers new package modules and wrappers.
- Rollout/backout is specified.

## Plan Draft B - Production API-Only Worker Transport

### Overview

Require production workers to post all state-changing events to internal API endpoints. Add explicit transport config and fail when API transport is required but not configured.

### Files to Change

- `apps/worker/src/egp_worker/project_event_sink.py`: make API transport required by default.
- `apps/worker/src/egp_worker/config.py`: add transport mode parsing.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: pass worker transport settings.
- API routes: add missing internal document ingest endpoint.
- Tests: update worker and API contract tests.

### Implementation Steps

TDD sequence: add failing tests for missing API URL in production mode, implement config, add document endpoint, update dispatcher payload, run gates.

Functions/classes:
- `get_worker_event_transport_mode`: resolve `api` or `direct`.
- `ApiDocumentIngestSink`: posts document artifacts or metadata to internal API.

Expected behavior and edge cases:
- Missing URL/token fails closed in API mode.
- Direct mode is explicit local/test-only.
- Large documents need upload semantics, not naive JSON payloads.

### Test Coverage

- API mode requires base URL.
- Direct mode remains explicit.
- Document ingest endpoint handles existing document contract.

### Decision Completeness

Goal: force worker writes through API/event endpoints.

Non-goals: shared service extraction.

Success criteria: worker state writes use HTTP in production; no silent DB fallback.

Public interfaces: new env vars/transport mode and likely new internal document endpoint.

Failure modes: endpoint/network downtime blocks worker writes; large payload transport must avoid memory spikes.

Rollout and monitoring: deploy API endpoint before worker config flips; monitor 401/5xx internal worker route rates.

### Dependencies

Needs careful document upload design and secret/token deployment.

### Validation

API internal endpoint tests, worker HTTP sink tests, dispatch payload tests.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| API project endpoints | worker sink HTTP POST | `configure_http_pipeline` includes router | `projects` |
| API document endpoint | worker document sink HTTP POST | new router registration | `documents` |

### Cross-Language Schema Verification

No migration if implemented as endpoint refactor only.

### Decision-Complete Checklist

Draft has a clear public surface, but document transport details remain higher risk.

## Comparative Analysis

Draft A is smaller, handles both current ambiguous imports, and matches the repo's existing package layer guidance. It avoids adding a large binary-document internal API before the artifact transport design is ready.

Draft B is stricter operationally, but it expands public/internal HTTP surface and needs a careful large artifact upload contract. It is more work and risk for this request.

Both preserve tenant-scoped repository access and avoid schema changes. Draft A best addresses the current hybrid ambiguity by making the hybrid a deliberate shared-domain package boundary.

## Unified Execution Plan

Use Draft A. The explicit decision is: workers and API may both use shared domain services from `egp_domain`; packages remain app-agnostic and must not import API or worker entrypoints. Internal API endpoints continue to exist as one transport option for project events, but the shared service package is the source of the domain write logic.

Implementation:
1. Add a boundary test proving worker modules do not import `egp_api.services`.
2. Run it red against current worker imports.
3. Create `packages/domain/src/egp_domain` and move service implementations there.
4. Convert old API service modules to compatibility re-exports.
5. Update API bootstrap/routes and worker modules to import from `egp_domain`.
6. Update monkeypatch tests to patch `egp_domain.document_ingest.DocumentIngestService` through the worker module import.
7. Run focused tests and gates.
8. Run g-check, fix findings if any, then create and submit the Graphite PR.
9. After CI is green, land the PR and sync local `main` to `origin/main`.

Acceptance commands:
- `./.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py tests/phase3/test_document_ingest_contract.py -q`
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase1/test_high_risk_architecture.py tests/phase3/test_document_ingest_contract.py`
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages`

## Implementation (2026-05-16 15:44:34 +07)

Goal: decide and implement the worker boundary by extracting shared domain services.

What changed:
- Added `packages/domain/src/egp_domain/project_ingest.py` and `packages/domain/src/egp_domain/document_ingest.py` as the shared domain package used by API and worker code.
- Converted `apps/api/src/egp_api/services/project_ingest_service.py` and `apps/api/src/egp_api/services/document_ingest_service.py` into compatibility re-exports.
- Updated API bootstrap/routes and worker workflows/sinks to import shared services from `egp_domain`.
- Added `test_worker_boundary_imports_no_api_services` to lock the worker away from `egp_api.services` imports.
- Updated root package discovery to include `packages/domain/src`.

TDD evidence:
- RED: `./.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py::test_worker_boundary_imports_no_api_services -q` failed because worker files imported `egp_api.services`.
- GREEN: same command passed after extraction.

Tests run:
- `./.venv/bin/python -m pip install -e .` passed to refresh editable package discovery.
- `./.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py::test_worker_boundary_imports_no_api_services -q` passed.
- `./.venv/bin/python -m pytest tests/phase1/test_high_risk_architecture.py tests/phase1/test_worker_workflows.py tests/phase1/test_projects_and_runs_api.py tests/phase3/test_document_ingest_contract.py -q` passed, 35 tests.
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase1/test_high_risk_architecture.py tests/phase3/test_document_ingest_contract.py` passed.
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages` passed.

Wiring verification:
- API app state still registers `DocumentIngestService` and `ProjectIngestService`, now imported from `egp_domain`.
- API document and internal worker project routes use shared services directly.
- Worker project event sinks and document ingest workflow use shared services directly.
- Existing internal project API transport remains wired through `/internal/worker/projects/discover` and `/internal/worker/projects/close-check`.

Behavior changes and risk notes:
- Public HTTP contracts are unchanged.
- Python import surface adds `egp_domain`; old API service module imports remain compatible.
- Failure mode is fail-closed: missing package discovery fails import/compile/tests instead of silently using API-local services.

Follow-ups / known gaps:
- A future change can still choose API-only worker transport for large deployments, but this change explicitly makes the current boundary shared-domain-services-first.

## Review (2026-05-16 15:45:42 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at base `44355524`
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `git diff` on API/worker/package/test files; targeted reads of new `egp_domain` files; `rg` for Docker/package copy wiring; focused pytest, ruff, and compileall gates listed above.

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings. During review, a Lambda Dockerfile packaging gap was found and fixed before finalizing review: `apps/api/Dockerfile.lambda-opn-webhook` now copies `packages/domain/src`.

LOW
- No findings.

### Open Questions / Assumptions
- Assumption: compatibility re-exports from `egp_api.services.*_ingest_service` should remain for existing callers while new code imports `egp_domain` directly.

### Recommended Tests / Validation
- Keep the focused pytest suite, ruff, and compileall commands as the pre-PR gate.
- A full Docker image build was not run locally; wiring was checked by inspecting the Dockerfile copy paths.

### Rollout Notes
- No migration or endpoint rollout is required.
- Deploy artifacts must include `packages/domain/src`; root Dockerfiles copy `packages/` wholesale and the Lambda Dockerfile now copies the package explicitly.
