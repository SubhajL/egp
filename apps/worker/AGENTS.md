# AGENTS.md

## Package Identity

- `apps/worker` is the crawler worker service for browser-driven e-GP jobs.
- Runtime entrypoints are [`src/main.py`](src/main.py) and the packaged worker in [`src/egp_worker/main.py`](src/egp_worker/main.py).
- The worker already has extracted workflow modules under `src/egp_worker/workflows/`, although some browser behavior still remains in the legacy crawler.

## Setup & Run

```bash
cd apps/worker && python -m pip install -e ".[dev]"
cd apps/worker && ../../.venv/bin/python -m src.main
./.venv/bin/python -m compileall apps/worker/src
./.venv/bin/ruff check apps/worker packages
```

Current test status: worker behavior is covered by repo-level tests, especially `tests/phase1/test_worker_workflows.py`.

## Patterns & Conventions

- ✅ DO keep [`src/main.py`](src/main.py) and [`src/egp_worker/main.py`](src/egp_worker/main.py) as thin bootstraps; put workflow logic under `src/egp_worker/workflows/`.
- ✅ DO extract browser and parsing logic from [`egp_crawler.py`](../../egp_crawler.py) into focused worker modules instead of copying blocks inline.
- ✅ DO keep temp downloads and browser profiles outside OneDrive-synced directories; the legacy log in [`egp_crawler_runtime.log`](../../egp_crawler_runtime.log) shows why.
- ✅ DO treat the worker as event producer and artifact collector, matching the control-plane/worker-plane rule in [`CLAUDE.md`](../../CLAUDE.md).
- ✅ DO create and update durable crawl-run records through the shared repositories instead of inventing worker-local state.
- ❌ DON'T let the worker own product state transitions directly; those belong in shared/domain logic and the API layer.
- ❌ DON'T reintroduce Excel update paths from [`egp_crawler.py`](../../egp_crawler.py).
- ❌ DON'T store browser state in repo folders or synced folders.

## Touch Points / Key Files

- Compatibility wrapper: [`src/main.py`](src/main.py)
- Packaged worker entrypoint: [`src/egp_worker/main.py`](src/egp_worker/main.py)
- Workflow modules: [`src/egp_worker/workflows/`](src/egp_worker/workflows)
- Python dependencies: [`pyproject.toml`](pyproject.toml)
- Legacy crawler source: [`egp_crawler.py`](../../egp_crawler.py)
- Real failure examples: [`egp_crawler_runtime.log`](../../egp_crawler_runtime.log)
- Shared lifecycle enums: [`packages/shared-types/src/egp_shared_types/enums.py`](../../packages/shared-types/src/egp_shared_types/enums.py)

## JIT Index Hints

```bash
rg -n "^def |^async def " apps/worker/src/egp_worker egp_crawler.py
rg -n "OneDrive|download|profile|Playwright|tor_downloaded" egp_crawler.py egp_crawler_runtime.log
find apps/worker/src/egp_worker -name "*.py"
rg -n "run_.*workflow|ingest_document_artifact|evaluate_timeout_transition" apps/worker/src tests/phase1
```

## Common Gotchas

- `src/main.py` is just a wrapper; real code belongs in `src/egp_worker/`.
- The real operational constraints are documented by failures in `egp_crawler_runtime.log`, especially OneDrive permissions.
- Keep worker changes compatible with future extraction from the legacy crawler.

## Pre-PR Checks

Current worker gate:

```bash
./.venv/bin/ruff check apps/worker packages
./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q
```
