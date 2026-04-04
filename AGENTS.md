# AGENTS.md

## Project Snapshot

- Repo type: lightweight polyglot monorepo without a workspace orchestrator.
- Primary stack: Python 3.12 services/packages, FastAPI, PostgreSQL SQL migrations targeting Supabase-managed Postgres, Next.js 15 + React 19 + TypeScript.
- Current state: the repo now has working API, worker, database, shared-package, and web slices for Phases 1 and 2, while the legacy crawler (`egp_crawler.py`) remains as an extraction reference and operational fallback.
- Closest-file wins: check the nearest `AGENTS.md` before editing. Root guidance is universal; app/package files are more specific.

## Root Setup Commands

```bash
./scripts/bootstrap_python_env.sh
docker compose up -d postgres redis
./.venv/bin/python -m egp_db.migration_runner --database-url postgresql://egp:egp_dev@localhost:5432/egp --migrations-dir packages/db/src/migrations
./.venv/bin/python scripts/run_phase1_postgres_smoke.py
(cd apps/web && npm install)
./.venv/bin/python -m compileall apps packages
(cd apps/web && npm run build)
(cd apps/web && npm run typecheck)
./.venv/bin/python -m pytest test_egp_crawler.py -v
```

## Universal Conventions

- Python uses 3.12+. Add type hints on all public functions.
- Frontend code uses TypeScript strict mode; `@/*` imports are configured in `apps/web/tsconfig.json`.
- Keep `ruff` line length at 100 for Python changes.
- Do not push directly to `main`; use a feature branch and open a PR with passing checks.
- Do not reintroduce Excel as the system of record. PostgreSQL is the source of truth; Excel is export-only.
- Do not use fake closure flags like `tor_downloaded = Yes` to end project tracking.

## Security & Secrets

- Never commit credentials, tokens, `.env`, `.env.local`, or `.env.*.local`.
- Local secrets belong in ignored env files; production secrets belong outside git.
- Managed target uses Supabase secrets and service-role keys; keep them out of git.
- Keep browser profiles and temp download directories outside OneDrive-synced paths.
- Preserve tenant isolation: new database access must stay scoped by `tenant_id`.

## JIT Index

### Package Structure

- API service: `apps/api/` → [see `apps/api/AGENTS.md`](apps/api/AGENTS.md)
- Worker service: `apps/worker/` → [see `apps/worker/AGENTS.md`](apps/worker/AGENTS.md)
- Document processor: `apps/doc-processor/` → [see `apps/doc-processor/AGENTS.md`](apps/doc-processor/AGENTS.md)
- Web app: `apps/web/` → [see `apps/web/AGENTS.md`](apps/web/AGENTS.md)
- Shared Python packages: `packages/` → [see `packages/AGENTS.md`](packages/AGENTS.md)
- Database package: `packages/db/` → [see `packages/db/AGENTS.md`](packages/db/AGENTS.md)
- Shared enums/types: `packages/shared-types/` → [see `packages/shared-types/AGENTS.md`](packages/shared-types/AGENTS.md)
- Legacy crawler: `egp_crawler.py` and `test_egp_crawler.py` stay useful as extraction references and anti-pattern warnings.

### Quick Find Commands

```bash
rg -n "^def |^async def " apps packages .
rg -n "APIRouter\\(|@router\\.(get|post|patch|delete)|include_router" apps/api/src
rg -n "CREATE TABLE|CREATE INDEX|ALTER TABLE" packages/db/src/migrations
rg -n "^class .*\\(StrEnum\\):" packages/shared-types/src
rg -n "tor_downloaded|update_excel|OneDrive" egp_crawler.py test_egp_crawler.py
find apps packages -name "*.py" -o -name "*.ts" -o -name "*.tsx"
```

## Definition Of Done

- Run the smallest relevant checks for the directories you touched.
- Update or add tests when behavior changes; if no test harness exists yet, say so in the PR.
- Keep docs, enums, and schema changes consistent across packages.
- Sanity-check the nearest `AGENTS.md` links and examples after structural edits.
