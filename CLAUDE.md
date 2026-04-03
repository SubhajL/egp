# e-GP Intelligence Platform

## Overview

- **Type**: Python + TypeScript monorepo
- **Stack**: FastAPI (Python 3.12+), React 19 + TypeScript, PostgreSQL 15+ (Supabase in managed environments), Playwright
- **Architecture**: Control-plane (API) / Worker-plane (crawler) split with event-driven document processing
- **Domain**: Thailand e-GP public procurement monitoring SaaS

This CLAUDE.md is the authoritative source for development guidelines.
Subdirectory CLAUDE.md files extend these rules with package-specific context.

---

## Universal Development Rules

### Code Quality (MUST)

- **MUST** use Python type hints on all function signatures
- **MUST** use TypeScript strict mode for all frontend code
- **MUST** include tests for all new features (TDD: test first, then implementation)
- **MUST** run linting before committing (`ruff` for Python, `eslint` for TypeScript)
- **MUST** scope all database queries by `tenant_id` — no cross-tenant data access
- **MUST** use SHA-256 hashing for all document artifacts before storage
- **MUST NOT** commit secrets, API keys, `.env` files, or credentials
- **MUST NOT** write `tor_downloaded = Yes` as a fake closure mechanism — use explicit `project_state` and `closed_reason`
- **MUST NOT** use Excel as a database — PostgreSQL is the source of truth; Excel is export-only

### Best Practices (SHOULD)

- **SHOULD** use descriptive variable/function names (no single letters except loop indices)
- **SHOULD** keep functions under 50 lines
- **SHOULD** prefer explicit lifecycle state transitions over boolean flags
- **SHOULD** preserve all document versions — never overwrite, always supersede
- **SHOULD** log every state transition to `project_status_events` for audit trail

### Anti-Patterns (MUST NOT)

- **MUST NOT** let crawler workers own product state — they emit events only; API owns state
- **MUST NOT** use `any` type in TypeScript without explicit justification
- **MUST NOT** bypass TypeScript errors with `@ts-ignore`
- **MUST NOT** push directly to `main` branch
- **MUST NOT** store browser profiles or temp downloads inside OneDrive-synced directories

---

## Core Commands

### Local Development

```bash
# Bootstrap isolated Python environment
./scripts/bootstrap_python_env.sh

# Start infrastructure (PostgreSQL + Redis)
docker compose up -d postgres redis

# Apply database migrations
./.venv/bin/python -m egp_db.migration_runner --database-url "$DATABASE_URL" --migrations-dir packages/db/src/migrations

# Dockerless document-persistence smoke (uses local PostgreSQL binaries)
./.venv/bin/python scripts/run_phase1_postgres_smoke.py

# API service
cd apps/api && ../../.venv/bin/uvicorn src.main:app --reload --port 8000

# Crawler worker
cd apps/worker && ../../.venv/bin/python -m src.main

# Frontend
cd apps/web && npm install && npm run dev

# Run existing crawler script (legacy, during migration)
cd . && ./.venv/bin/python egp_crawler.py --profile tor
```

### Testing

```bash
# Python tests (API + worker + packages)
./.venv/bin/python -m pytest apps/api/ apps/worker/ packages/ -v

# Existing crawler tests (legacy)
./.venv/bin/python -m pytest test_egp_crawler.py -v

# Frontend tests
cd apps/web && npm test

# Type checking
cd apps/web && npx tsc --noEmit
```

### Linting

```bash
# Python
./.venv/bin/python -m ruff check apps/ packages/ --fix
./.venv/bin/python -m ruff format apps/ packages/

# TypeScript
cd apps/web && npx eslint src/ --fix
```

### Quality Gates (run before PR)

```bash
./.venv/bin/python -m ruff check apps/ packages/ && ./.venv/bin/python -m pytest apps/ packages/ -v && cd apps/web && npx tsc --noEmit && npx eslint src/
```

---

## Project Structure

### Legacy (being migrated)

- **`egp_crawler.py`** — Original 2200-line monolithic crawler script (source for extraction)
- **`test_egp_crawler.py`** — Existing test suite (pure logic tests, no browser)
- **`project_list.xlsx`** — Legacy Excel state store (being replaced by PostgreSQL)
- **`USER_MANUAL_TH.md`** — Thai user manual for the original script

### Applications

- **`apps/api/`** — FastAPI backend: tenants, users, projects, documents, runs, exports
  - Routes: `src/routes/`
  - Services: `src/services/`
  - Models: `src/models/`
  - Middleware: `src/middleware/`

- **`apps/worker/`** — Playwright crawler workers: browser automation, e-GP parsing
  - Workflows: `src/workflows/` (discover, close_check, timeout_sweep)
  - Browser: `src/browser/`
  - Parsers: `src/parsers/`

- **`apps/web/`** — React + TypeScript frontend: 8 pages (dashboard, explorer, detail, compare, runs, rules, admin, login)
  - Pages: `src/pages/`
  - Components: `src/components/`
  - Hooks: `src/hooks/`
  - Lib: `src/lib/`

- **`apps/doc-processor/`** — Document hashing, text extraction, TOR phase classification, diff generation

### Packages

- **`packages/db/`** — PostgreSQL schema + migrations + repositories
  - Migrations: `src/migrations/` (numbered sequentially: `001_*.sql`, `002_*.sql`)
  - Repositories: `src/repositories/` (project_repo, document_repo, run_repo)

- **`packages/shared-types/`** — Shared Python enums and type definitions
  - `src/egp_shared_types/enums.py` — ProjectState, ClosedReason, DocumentType, DocumentPhase, etc.

- **`packages/crawler-core/`** — Core crawling logic extracted from `egp_crawler.py`
  - `src/egp_crawler_core/canonical_id.py` — Canonical project ID generation
  - `src/egp_crawler_core/project_lifecycle.py` — State transition logic
  - `src/egp_crawler_core/closure_rules.py` — Consulting timeout, winner close, stale close
  - `src/profiles.py` — Keyword profiles (TOR/TOE/LUE/custom)
  - `src/parser.py` — e-GP page parsing

- **`packages/document-classifier/`** — TOR vs invitation vs mid-price classification; public_hearing vs final phase detection

- **`packages/notification-core/`** — Alert delivery (email, webhook, in-app)

### Infrastructure

- **`infrastructure/terraform/`** — Deployment/IaC placeholders for managed hosting and worker infrastructure
- **`infrastructure/ecs-task-definitions/`** — Container definitions
- **`infrastructure/cloudwatch-dashboards/`** — Monitoring dashboards

### Documentation

- **`docs/PRD.md`** — Full product requirements (31 sections)
- **`docs/PHASE1_PLAN.md`** — Phase 1 execution plan with wiring verification

---

## Quick Find Commands

### Code Navigation

```bash
# Find Python function definition
rg -n "^def |^async def " apps/ packages/

# Find FastAPI route
rg -n "@(app|router)\.(get|post|patch|delete)" apps/api/src

# Find React component
rg -n "export (function|const) " apps/web/src/components

# Find enum value
rg -n "class.*Enum|StrEnum" packages/shared-types/src

# Find SQL migration
rg -n "CREATE TABLE|ALTER TABLE" packages/db/src/migrations

# Find TOR-related logic
rg -n "is_tor|tor_doc|TOR_DOC_MATCH" .

# Find closure rule logic
rg -n "closed_reason|project_state|consulting_timeout" .
```

### Dependency Analysis

```bash
# Python dependencies
pip list --format=columns

# Check what imports a module
rg -n "from.*import|import " apps/ packages/ --glob "*.py"

# Node dependencies
cd apps/web && npm ls --depth=0
```

---

## Key Design Decisions

1. **Control-plane / worker-plane split** — API service owns all state; crawler workers only emit events and artifacts
2. **PostgreSQL replaces Excel** — `project_list.xlsx` becomes export-only; all state in PostgreSQL
3. **Explicit project lifecycle** — No more binary `tor_downloaded = Yes/No`; uses `ProjectState` enum with 12 states
4. **Document versioning** — SHA-256 hash, never overwrite, `public_hearing` vs `final` TOR phases
5. **Supabase-managed backend** — prefer Supabase Postgres/Auth/Storage for the managed control plane
6. **Canonical project ID** — `project_number` when available; else fingerprint `(org + name + date + budget)`
7. **Multi-tenant from day one** — `tenant_id` on every table, row-level isolation

### Project Lifecycle States

```
discovered → open_invitation → open_consulting → tor_downloaded → winner_announced → contract_signed → [CLOSED]

Timeout paths:
  open_consulting ──(30d)──→ closed_timeout_consulting
  open_* ──(45d)──→ closed_stale_no_tor
  Any ──(manual)──→ closed_manual
```

Closure reasons: `winner_announced`, `contract_signed`, `consulting_timeout_30d`, `prelim_pricing`, `stale_no_tor`, `manual`, `merged_duplicate`

---

## Database

- **PostgreSQL 15+** with 13 tables (see `packages/db/src/migrations/001_initial_schema.sql`)
- Core tables: `tenants`, `users`, `crawl_profiles`, `projects`, `project_aliases`, `project_status_events`, `documents`, `document_diffs`, `crawl_runs`, `crawl_tasks`, `notifications`, `exports`
- UUIDs for all primary keys (`uuid-ossp` extension)
- `tenant_id` on every tenant-scoped table
- `created_at` / `updated_at` timestamps with auto-update triggers
- CHECK constraints on all enum-like columns (`project_state`, `closed_reason`, `document_type`, etc.)

### Schema Conventions

- Migrations numbered sequentially: `001_initial_schema.sql`, `002_add_billing.sql`
- Always add indexes for foreign keys and common query patterns
- Use `UNIQUE` constraints to enforce business rules (e.g., `documents(project_id, sha256)`)
- Row-level tenant isolation enforced in repository layer — every query includes `WHERE tenant_id = $1`

---

## Security Guidelines

### Secrets Management

- **NEVER** commit tokens, API keys, or credentials
- Use `.env.local` for local secrets (in `.gitignore`)
- Use Supabase project secrets and host-level secret managers for production secrets
- PII must be redacted in logs
- Supabase Auth is the preferred managed auth path — JWTs validated in API middleware

### Safe Operations

- Confirm before: git force push, database drops, or object-storage bucket deletes
- Signed object-storage URLs for document downloads (never expose raw storage paths)
- Webhook signature verification for payment provider callbacks
- Audit log for all admin actions and billing changes

### Crawler Security

- Only download from allowed hosts: `gprocurement.go.th` (see `ALLOWED_DOWNLOAD_HOST_SUFFIXES`)
- Browser profile directory must be outside OneDrive to avoid sync conflicts
- Validate all URLs before fetching (no `javascript:`, `data:`, `blob:` schemes)

---

## Git Workflow

- Branch from `main` for features: `feat/description`, `fix/description`
- Use Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- PRs require: passing tests, type checks, lint, and review
- Squash commits on merge
- Delete branches after merge

---

## Testing Requirements

- **T-1:** Write tests before implementation (TDD)
- **T-2:** Test business rules, not implementation details
- **T-3:** Use real database for integration tests (not mocks)
- **T-4:** Name tests descriptively: `test_consulting_project_closes_after_30_days_inactivity`
- **T-5:** Cover all 10 acceptance tests from PRD section 30

### Key Acceptance Tests

1. Same project under 3 keywords = one canonical project
2. Project number backfill merges correctly
3. Same-hash TOR versions don't create false alerts
4. Different-hash TOR versions create change alert + both preserved
5. Consulting project closes after 30 days inactivity
6. Winner announcement closes project automatically
7. Browser failure doesn't create duplicate rows
8. Managed object-storage artifact stored even on partial UI parse failure
9. Excel export matches filtered project list
10. Tenant A cannot access Tenant B's data

---

## Environment Variables

### API Service

```
DATABASE_URL=postgresql://egp:egp_dev@localhost:5432/egp
REDIS_URL=redis://localhost:6379
EGP_ARTIFACT_STORE=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_STORAGE_BUCKET=egp-documents
```

### Worker

```
DATABASE_URL=postgresql://egp:egp_dev@localhost:5432/egp
SQS_QUEUE_URL=<queue-url>
EGP_ARTIFACT_STORE=supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
SUPABASE_STORAGE_BUCKET=egp-documents
CHROME_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
CDP_PORT=9222
```

### Legacy Crawler (env vars read by `egp_crawler.py`)

```
EGP_CHROME_PATH, EGP_CDP_PORT, EGP_DOWNLOAD_DIR, EGP_EXCEL_PATH
EGP_BROWSER_PROFILE_DIR, EGP_KEYWORDS, EGP_MAX_PAGES_PER_KEYWORD
```

See `USER_MANUAL_TH.md` section 3.1 for full legacy env var reference.

---

## Available Tools

You have access to:

- Standard bash tools (`rg`, `git`, `python`, `pip`, `node`, `npm`)
- GitHub CLI (`gh`) for issues, PRs, releases
- Docker Compose for local PostgreSQL + Redis
- `psql` for database access
- `ruff` for Python linting/formatting
- `pytest` for Python testing
- Playwright for browser automation testing

### Tool Permissions

- Read any file
- Write code files in `apps/`, `packages/`, `docs/`
- Run tests, linters, type checkers
- Run `docker compose` commands
- Edit `.env` files (ask first)
- Force push (ask first)
- Delete databases (ask first)
- Run production migrations (ask first)

---

## Common Gotchas

- **12 vs 11 keywords**: `KEYWORDS_DEFAULT` has 12 entries but `test_egp_crawler.py:475` asserts 11 — fix the test
- **OneDrive permission errors**: Browser profile and temp downloads must be outside OneDrive-synced folders
- **Cloudflare/Turnstile**: e-GP site uses Cloudflare protection; real Chrome + persistent profile is required
- **Thai Buddhist dates**: e-GP uses Buddhist era (BE = CE + 543); use `parse_buddhist_date()` for conversion
- **Excel file locking**: OneDrive can lock `project_list.xlsx`; the legacy script has retry logic for this
- **Stale toast errors**: e-GP site shows error toasts that block interaction; `clear_site_error_toast()` handles this
- **pricebuild files**: Files prefixed with `pricebuild` or `pB*.pdf` are NOT TOR documents — filter them out

---

## Specialized Context

When working in specific directories, refer to their CLAUDE.md:

- API development: `apps/api/CLAUDE.md`
- Crawler workers: `apps/worker/CLAUDE.md`
- Frontend work: `apps/web/CLAUDE.md`
- Database/migrations: `packages/db/CLAUDE.md`

These files provide detailed, context-specific guidance.

---

## Current Phase: Phase 1 — Foundation and State Correctness

**Goal:** Replace fragile script-state assumptions with proper lifecycle management.

1. PostgreSQL schema + migrations (DONE: `001_initial_schema.sql`)
2. API service skeleton (FastAPI) — `apps/api/src/main.py`
3. Crawler worker refactor (extract from `egp_crawler.py`)
4. Canonical project model with alias dedup
5. Explicit lifecycle states and closure rules
6. Document SHA-256 hashing
7. Supabase Storage / object-storage artifact backend
8. Basic project list API + UI

**Exit criteria:** One canonical project per real tender; winner/consulting close rules work; no duplicate artifacts.

See `docs/PHASE1_PLAN.md` for detailed execution plan with wiring verification.
