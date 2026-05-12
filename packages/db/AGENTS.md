# AGENTS.md

## Package Identity

- `packages/db` is the database package for schema and repository code targeting PostgreSQL, locally or via Supabase-managed Postgres.
- The current source of truth is the initial SQL migration in [`src/migrations/001_initial_schema.sql`](src/migrations/001_initial_schema.sql).

## Setup & Run

```bash
docker compose -f docker-compose-localdev.yml up -d postgres redis
python -m egp_db.migration_runner --database-url postgresql://egp:egp_dev@localhost:5432/egp --migrations-dir packages/db/src/migrations
python -m compileall packages/db/src
```

Current code status: repository modules, storage adapters, and a lightweight migration runner are checked in.

## Patterns & Conventions

- ✅ DO number migrations sequentially, copying the style of [`src/migrations/001_initial_schema.sql`](src/migrations/001_initial_schema.sql).
- ✅ DO include `tenant_id` on tenant-scoped tables, as shown throughout [`src/migrations/001_initial_schema.sql`](src/migrations/001_initial_schema.sql).
- ✅ DO keep lifecycle, document, and notification fields constrained with explicit `CHECK` rules, matching the current migration style.
- ✅ DO add indexes for foreign keys and common query patterns, copying the `CREATE INDEX` sections in [`src/migrations/001_initial_schema.sql`](src/migrations/001_initial_schema.sql).
- ✅ DO keep enum-like database values synchronized with [`packages/shared-types/src/egp_shared_types/enums.py`](../shared-types/src/egp_shared_types/enums.py).
- ✅ DO keep `storage_key` provider-agnostic; it may point at local storage, S3, or Supabase Storage.
- ❌ DON'T reintroduce Excel-backed state from [`egp_crawler.py`](../../egp_crawler.py); the database is the system of record.
- ❌ DON'T add tenant-scoped queries or tables without tenant isolation.
- ❌ DON'T change enum values in SQL without updating shared Python enums in the same change.

## Touch Points / Key Files

- Initial schema: [`src/migrations/001_initial_schema.sql`](src/migrations/001_initial_schema.sql)
- Package marker: [`src/__init__.py`](src/__init__.py)
- Shared enum definitions: [`packages/shared-types/src/egp_shared_types/enums.py`](../shared-types/src/egp_shared_types/enums.py)
- Migration/extraction plan: [`docs/PHASE1_PLAN.md`](../../docs/PHASE1_PLAN.md)
- Universal database rules: [`CLAUDE.md`](../../CLAUDE.md)

## JIT Index Hints

```bash
find packages/db -name "*.sql" -o -name "*.py"
rg -n "CREATE TABLE|CREATE INDEX|CONSTRAINT" packages/db/src/migrations
rg -n "tenant_id|project_state|closed_reason|sha256" packages/db/src/migrations
```

## Common Gotchas

- `docker-compose-localdev.yml` is the local development stack; it mounts `packages/db/src/migrations` into the dev flow only after the explicit migration runner command above, so a fresh volume is still the safest path for testing init-time behavior.
- `docker-compose.yml` is now the production-oriented single-host stack and should not be treated as the local default.
- The checked-in migration already encodes business rules for project states, closed reasons, and document hashing.
- Supabase keeps PostgreSQL semantics; schema work should still look like normal Postgres DDL, not document-store modeling.
- When repository modules are added, they must keep `tenant_id` filtering explicit.

## Pre-PR Checks

```bash
python -m compileall packages/db/src && rg -n "tenant_id|project_state|closed_reason|sha256" packages/db/src/migrations/001_initial_schema.sql
```
