# AGENTS.md

## Package Identity

- `packages/shared-types` holds shared Python enums and type-level constants.
- The key file is [`src/egp_shared_types/enums.py`](src/egp_shared_types/enums.py), which must stay aligned with database constraints.

## Setup & Run

```bash
python -m compileall packages/shared-types/src
ruff check packages/shared-types
```

Current test status: no enum-specific tests are checked in yet.

## Patterns & Conventions

- ✅ DO define shared status vocabularies as `StrEnum`, matching the style in [`src/egp_shared_types/enums.py`](src/egp_shared_types/enums.py).
- ✅ DO add new cross-service literals here instead of hardcoding strings in apps.
- ✅ DO keep enum values synchronized with the `CHECK` constraints in [`packages/db/src/migrations/001_initial_schema.sql`](../db/src/migrations/001_initial_schema.sql).
- ✅ DO group related values by domain, following the existing `ProjectState`, `ClosedReason`, and `DocumentType` classes in [`src/egp_shared_types/enums.py`](src/egp_shared_types/enums.py).
- ❌ DON'T duplicate lifecycle strings from [`src/egp_shared_types/enums.py`](src/egp_shared_types/enums.py) in route handlers, workers, or document processors.
- ❌ DON'T change an enum value here without updating database constraints in [`packages/db/src/migrations/001_initial_schema.sql`](../db/src/migrations/001_initial_schema.sql).
- ❌ DON'T reuse legacy booleans like `tor_downloaded` from [`egp_crawler.py`](../../egp_crawler.py) as if they were shared state models.

## Touch Points / Key Files

- Shared enums: [`src/egp_shared_types/enums.py`](src/egp_shared_types/enums.py)
- Package marker: [`src/__init__.py`](src/__init__.py)
- Database constraints to keep in sync: [`packages/db/src/migrations/001_initial_schema.sql`](../db/src/migrations/001_initial_schema.sql)
- State model reference: [`docs/PRD.md`](../../docs/PRD.md)
- Migration plan: [`docs/PHASE1_PLAN.md`](../../docs/PHASE1_PLAN.md)

## JIT Index Hints

```bash
find packages/shared-types -name "*.py"
rg -n "^class .*\\(StrEnum\\):" packages/shared-types/src
rg -n "DISCOVERED|CLOSED_|PUBLIC_HEARING|FINAL|RUN_FAILED" packages/shared-types/src/egp_shared_types/enums.py
rg -n "project_state|closed_reason|document_type|document_phase" packages/shared-types/src/egp_shared_types/enums.py packages/db/src/migrations/001_initial_schema.sql
```

## Common Gotchas

- This package is the safest place for cross-service literals, but only if SQL stays in sync.
- Enum changes can be breaking even when they look small; check every consumer path before renaming values.
- Keep values storage-friendly; database rows already rely on these exact strings.

## Pre-PR Checks

```bash
python -m compileall packages/shared-types/src && rg -n "project_state|closed_reason|document_type|document_phase" packages/shared-types/src/egp_shared_types/enums.py packages/db/src/migrations/001_initial_schema.sql
```
