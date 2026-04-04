# AGENTS.md

## Package Identity

- `apps/doc-processor` is the planned document hashing, classification, and diff service.
- Its app entrypoint is still scaffold-only in [`src/main.py`](src/main.py), while the currently implemented classification logic lives in shared packages such as [`packages/document-classifier`](../../packages/document-classifier).

## Setup & Run

```bash
cd apps/doc-processor && python -m src.main
python -m compileall apps/doc-processor/src
ruff check apps/doc-processor
```

Current test status: there are no app-local doc-processor tests yet; current document-phase logic is covered indirectly through repo-level tests.

## Patterns & Conventions

- ✅ DO keep the entrypoint thin like [`src/main.py`](src/main.py).
- ✅ DO add hashing, classification, and diff logic as separate modules under `src/`, following the plan in [`docs/PHASE1_PLAN.md`](../../docs/PHASE1_PLAN.md).
- ✅ DO preserve all document versions; this package should support the "never overwrite" rule documented in [`docs/PRD.md`](../../docs/PRD.md).
- ✅ DO align document type and phase names with [`packages/shared-types/src/egp_shared_types/enums.py`](../../packages/shared-types/src/egp_shared_types/enums.py) and the document constraints in [`packages/db/src/migrations/001_initial_schema.sql`](../../packages/db/src/migrations/001_initial_schema.sql).
- ✅ DO treat SHA-256 as the document identity mechanism; the schema already reserves `documents.sha256`.
- ✅ DO reuse shared document-classifier and repository code where possible instead of duplicating logic inside the app.
- ❌ DON'T stuff pipeline logic into [`src/main.py`](src/main.py).
- ❌ DON'T resurrect file-system-only tracking from [`egp_crawler.py`](../../egp_crawler.py) when document metadata belongs in the database.
- ❌ DON'T change document lifecycle strings locally without updating shared enums and schema.

## Touch Points / Key Files

- Entrypoint scaffold: [`src/main.py`](src/main.py)
- Current classifier implementation: [`packages/document-classifier/src/egp_document_classifier/classifier.py`](../../packages/document-classifier/src/egp_document_classifier/classifier.py)
- Planned extractor/classifier modules: [`docs/PHASE1_PLAN.md`](../../docs/PHASE1_PLAN.md)
- Product rules for document versioning: [`docs/PRD.md`](../../docs/PRD.md)
- Shared enum values: [`packages/shared-types/src/egp_shared_types/enums.py`](../../packages/shared-types/src/egp_shared_types/enums.py)
- Schema for documents and diffs: [`packages/db/src/migrations/001_initial_schema.sql`](../../packages/db/src/migrations/001_initial_schema.sql)

## JIT Index Hints

```bash
find apps/doc-processor -name "*.py"
rg -n "sha256|document_type|document_phase|diff" apps/doc-processor packages/document-classifier packages/db docs
rg -n "public_hearing|final|TOR|document" docs/PRD.md docs/PHASE1_PLAN.md
```

## Common Gotchas

- There is no `pyproject.toml` here yet; add one before introducing package-specific dependencies.
- Keep enum names synchronized with `packages/shared-types` and `packages/db`.
- This package should preserve versions, not overwrite artifacts in place.

## Pre-PR Checks

Current gate until packaging and tests exist:

```bash
./.venv/bin/ruff check apps/doc-processor packages/document-classifier
./.venv/bin/python -m pytest tests/phase1/test_phase1_domain_logic.py -q
```
