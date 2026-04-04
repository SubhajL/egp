# AGENTS.md

## Package Identity

- `apps/api` is the FastAPI control-plane service.
- Runtime entrypoints are [`src/main.py`](src/main.py) and the packaged app in [`src/egp_api/main.py`](src/egp_api/main.py).
- The app already serves document, project, crawl-evidence, run, and export APIs via `src/egp_api/routes/` backed by `src/egp_api/services/`.

## Setup & Run

```bash
cd apps/api && python -m pip install -e ".[dev]"
cd apps/api && ../../.venv/bin/uvicorn src.main:app --reload --port 8000
./.venv/bin/python -m compileall apps/api/src
./.venv/bin/ruff check apps/api packages
```

Current test status: API behavior is covered by repo-level pytest suites under `tests/phase1/` and `tests/phase2/`.

## Patterns & Conventions

- ✅ DO keep [`src/main.py`](src/main.py) and [`src/egp_api/main.py`](src/egp_api/main.py) thin; add behavior under `src/egp_api/routes/` and `src/egp_api/services/`.
- ✅ DO keep route handlers and services aligned: auth and tenant resolution in the request layer, repository orchestration in services.
- ✅ DO keep shared state names aligned with [`packages/shared-types/src/egp_shared_types/enums.py`](../../packages/shared-types/src/egp_shared_types/enums.py) and [`packages/db/src/migrations/001_initial_schema.sql`](../../packages/db/src/migrations/001_initial_schema.sql).
- ✅ DO scope all repository queries by `tenant_id`, per [`CLAUDE.md`](../../CLAUDE.md).
- ✅ DO derive tenant context from auth middleware first; treat caller-supplied `tenant_id` as compatibility input only.
- ✅ DO add `limit`/`offset` pagination on list endpoints instead of returning unbounded rows.
- ❌ DON'T copy Excel-writing or browser-automation logic out of [`egp_crawler.py`](../../egp_crawler.py) into the API.
- ❌ DON'T bypass `resolve_request_tenant_id()` or tenant-aware repositories for convenience.
- ❌ DON'T turn either entrypoint into another monolith like [`egp_crawler.py`](../../egp_crawler.py).
- ❌ DON'T invent new lifecycle strings in route code; add them in shared enums and schema first.

## Touch Points / Key Files

- Compatibility wrapper: [`src/main.py`](src/main.py)
- Packaged app entrypoint: [`src/egp_api/main.py`](src/egp_api/main.py)
- API routes: [`src/egp_api/routes/`](src/egp_api/routes)
- API services: [`src/egp_api/services/`](src/egp_api/services)
- Python dependencies and `ruff` config: [`pyproject.toml`](pyproject.toml)
- Universal platform rules: [`CLAUDE.md`](../../CLAUDE.md)
- Shared enum source: [`packages/shared-types/src/egp_shared_types/enums.py`](../../packages/shared-types/src/egp_shared_types/enums.py)
- Schema source of truth: [`packages/db/src/migrations/001_initial_schema.sql`](../../packages/db/src/migrations/001_initial_schema.sql)

## JIT Index Hints

```bash
rg -n "^async def |^def " apps/api/src/egp_api
rg -n "APIRouter\\(|@router\\.(get|post|patch|delete)|include_router" apps/api/src/egp_api
find apps/api/src/egp_api -name "*.py"
rg -n "tenant_id|resolve_request_tenant_id|project_state|closed_reason" apps/api packages tests
```

## Common Gotchas

- `src/main.py` is only a compatibility wrapper; most real changes belong under `src/egp_api/`.
- Keep handlers async unless there is a concrete blocking reason.
- If you add database access, tenant scoping is mandatory from the first query.
- Keep list endpoints bounded; the current default contract is `limit=50`, `offset=0`, max `limit=200`.

## Pre-PR Checks

Current API gate:

```bash
./.venv/bin/ruff check apps/api packages
./.venv/bin/python -m pytest tests/phase1/test_projects_and_runs_api.py tests/phase1/test_documents_api.py tests/phase2/test_project_explorer_api.py tests/phase2/test_project_crawl_evidence_api.py tests/phase2/test_export_service.py -q
```
