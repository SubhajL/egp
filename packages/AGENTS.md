# AGENTS.md

## Package Identity

- `packages/` holds shared Python modules used by the apps.
- `packages/db` and `packages/shared-types` already contain real implementation details; `crawler-core`, `document-classifier`, and `notification-core` are still scaffolds.

## Setup & Run

```bash
python -m compileall packages
ruff check packages
```

Current test status: no package-local test files are checked in yet.

## Patterns & Conventions

- ✅ DO keep package code reusable and app-agnostic; packages should not depend on app entrypoints.
- ✅ DO keep `__init__.py` files side-effect free, following [`packages/crawler-core/src/__init__.py`](crawler-core/src/__init__.py) and peers.
- ✅ DO extract shared logic out of [`egp_crawler.py`](../egp_crawler.py) into packages instead of copying logic into multiple apps.
- ✅ DO put schema work in [`packages/db`](db/AGENTS.md) and shared lifecycle/status names in [`packages/shared-types`](shared-types/AGENTS.md).
- ✅ DO add new modules beside the existing `src/__init__.py` files so imports stay package-scoped.
- ❌ DON'T import app `main.py` modules from packages.
- ❌ DON'T duplicate enums or lifecycle literals across packages and apps.
- ❌ DON'T treat scaffold packages as dumping grounds; add focused modules with one responsibility each.

## Touch Points / Key Files

- DB package overview: [`db/AGENTS.md`](db/AGENTS.md)
- Shared enums package: [`shared-types/AGENTS.md`](shared-types/AGENTS.md)
- Crawler-core scaffold: [`crawler-core/src/__init__.py`](crawler-core/src/__init__.py)
- Document-classifier scaffold: [`document-classifier/src/__init__.py`](document-classifier/src/__init__.py)
- Notification-core scaffold: [`notification-core/src/__init__.py`](notification-core/src/__init__.py)
- Shared-types enum source: [`shared-types/src/egp_shared_types/enums.py`](shared-types/src/egp_shared_types/enums.py)
- Migration plan for future modules: [`docs/PHASE1_PLAN.md`](../docs/PHASE1_PLAN.md)

## JIT Index Hints

```bash
find packages -name "*.py" -o -name "*.sql"
rg -n "^class .*\\(StrEnum\\):" packages/shared-types/src
rg -n "CREATE TABLE|CREATE INDEX|ALTER TABLE" packages/db/src/migrations
rg -n "canonical_id|closure_rules|classifier|notification" docs/PHASE1_PLAN.md packages
```

## Common Gotchas

- Only `db` and `shared-types` have meaningful checked-in content today.
- If you add new package dependencies, do not hide them in apps; create the right package-level config first.
- Keep future extractions aligned with `docs/PHASE1_PLAN.md`, not with ad hoc imports from the legacy crawler.

## Pre-PR Checks

```bash
ruff check packages && python -m compileall packages
```
