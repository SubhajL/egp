# Coding Log: document-repo-split

## Plan Draft A

### Overview
Split `packages/db/src/egp_db/repositories/document_repo.py` into focused repository modules while keeping `egp_db.repositories.document_repo` as the public facade. This is a behavior-preserving refactor: no SQL schema, endpoint, CLI, env var, or storage contract changes.

### Files To Change
- `packages/db/src/egp_db/repositories/document_models.py`: document dataclasses and read error.
- `packages/db/src/egp_db/repositories/document_schema.py`: SQLAlchemy tables and indexes.
- `packages/db/src/egp_db/repositories/document_utils.py`: row mappers, normalization, content type, and `build_document_record`.
- `packages/db/src/egp_db/repositories/document_persistence.py`: document store/list/get persistence mixin.
- `packages/db/src/egp_db/repositories/document_diffs.py`: diff lookup and diff-building mixin.
- `packages/db/src/egp_db/repositories/document_reviews.py`: review lifecycle mixin.
- `packages/db/src/egp_db/repositories/document_delivery.py`: artifact read/download/streaming mixin.
- `packages/db/src/egp_db/repositories/document_repo.py`: facade, constructor, filesystem wrapper, factories, compatibility exports.
- `tests/phase1/test_document_persistence.py`: focused architecture/import test for split boundaries.

### Implementation Steps
TDD sequence:
1. Add a test proving `document_repo.py` stays a small facade and submodules are importable.
2. Run that test and confirm it fails because the split modules do not exist.
3. Move code into modules with the smallest behavior-preserving extraction.
4. Refactor imports and facade exports only after tests pass.
5. Run focused document persistence/API gates, compile, and relevant package checks.

Functions/classes:
- `SqlDocumentRepository`: remains the public repository class and composes mixins.
- `DocumentPersistenceMixin.store_document`: keeps canonical document write behavior.
- `DocumentDiffMixin._build_diff_record`: keeps old/new artifact comparison behavior.
- `DocumentReviewMixin.apply_document_review_action`: keeps review status transitions.
- `DocumentDeliveryMixin.iter_document_bytes`: keeps eager stream opening and backup fallback.
- `create_document_repository` / `create_artifact_store`: remain public factories.

### Test Coverage
- `test_document_repository_is_split_behind_compatibility_facade`: modules exist; facade exports remain stable.
- Existing `test_store_document_*`: persistence, idempotency, diff, and cleanup behavior.
- Existing review tests: pending review creation and tenant-scoped actions.
- Existing API tests: route/service imports remain wired.

### Decision Completeness
Goal: reduce the largest document repository module into coherent implementation slices.
Non-goals: change persistence semantics, add schema migrations, change API routes, or rename public imports.
Success criteria: `document_repo.py` is a small facade; existing imports from `egp_db.repositories.document_repo` keep working; focused tests pass.
Public interfaces: no endpoint/schema/env/CLI/migration changes. Python import compatibility is preserved for repository exports, tables, factories, `hash_file`, and `classify_document`.
Edge cases/failure modes: tenant isolation remains explicit; duplicate document replay remains idempotent; artifact write cleanup remains fail-closed on DB/storage errors; read fallback to managed backup remains unchanged.
Rollout/monitoring: normal PR rollout; watch document ingest logs and review creation counts after deploy.
Acceptance checks: focused pytest for document persistence/API/imports; `python -m compileall packages/db/src apps/api/src apps/worker/src`.

### Dependencies
Auggie semantic search returned HTTP 429; plan is based on direct file inspection plus exact-string searches.
Inspected files: `AGENTS.md`, `packages/AGENTS.md`, `packages/db/AGENTS.md`, `document_repo.py`, repository exports, document persistence/API/worker call sites, and document tests.

### Validation
Run the smallest relevant checks first, then broaden to compile and API import tests.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `document_repo.py` facade | Existing imports in API, worker, tests | `egp_db.repositories.__init__` and direct imports | Re-exports document tables |
| `DocumentPersistenceMixin` | `SqlDocumentRepository.store_document/list_documents/get_document` | `SqlDocumentRepository` inheritance | `documents` |
| `DocumentDiffMixin` | Store flow and document diff routes | `SqlDocumentRepository` inheritance | `document_diffs` |
| `DocumentReviewMixin` | Review list/action routes | `SqlDocumentRepository` inheritance | `document_diff_reviews`, `document_review_events` |
| `DocumentDeliveryMixin` | Download/content API and export service | `SqlDocumentRepository` inheritance | `documents` storage keys |

## Plan Draft B

### Overview
Use an even more conservative split: move only dataclasses/schema/helpers out, leaving all repository methods in `document_repo.py`. This minimizes method movement but leaves the core module still too large.

### Files To Change
- `document_models.py`, `document_schema.py`, `document_utils.py`, and `document_repo.py`.
- A small architecture test.

### Implementation Steps
TDD sequence is the same as Draft A, but only support code moves out.
Functions/classes: `SqlDocumentRepository` remains fully implemented in the facade.

### Test Coverage
Same focused imports and existing persistence/API tests.

### Decision Completeness
Goal: reduce support clutter in the file.
Non-goals/public interfaces/rollout/edge cases match Draft A.
Success criteria: lower line count, but not a full decomposition.

### Dependencies
Same Auggie 429 fallback context as Draft A.

### Validation
Same focused pytest and compile gates.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `document_models.py` | Imported by facade | Direct import in `document_repo.py` | N/A |
| `document_schema.py` | Imported by facade and other repos via facade | Direct import in `document_repo.py` | document tables |
| `document_utils.py` | Imported by facade methods | Direct import in `document_repo.py` | N/A |

## Comparative Analysis
Draft A does the actual PR 15 decomposition: persistence, diffs, reviews, delivery, and facade become separate editing surfaces. The risk is import churn and mixin cross-calls, so tests must preserve compatibility.

Draft B is safer mechanically but undershoots the planned PR: the largest behavioral methods still live together, so future document changes continue to pay the same navigation cost.

The unified plan uses Draft A, with a compatibility facade and no public behavior changes.

## Unified Execution Plan

### Overview
Implement the full focused split behind the existing `document_repo.py` import path. Keep `SqlDocumentRepository` public and stable, composed from mixins for persistence, diffs, reviews, and delivery.

### Files To Change
- Create `document_models.py`, `document_schema.py`, `document_utils.py`, `document_persistence.py`, `document_diffs.py`, `document_reviews.py`, `document_delivery.py`.
- Replace `document_repo.py` with facade/class composition/factories/compatibility exports.
- Add a focused split-boundary test in `tests/phase1/test_document_persistence.py`.

### Implementation Steps
1. Add split-boundary test and confirm RED.
2. Extract models/schema/utils.
3. Extract delivery mixin and keep backup fallback behavior.
4. Extract diff mixin and keep previous-artifact-missing behavior.
5. Extract review mixin and keep status/event behavior.
6. Extract persistence mixin and keep duplicate replay, cleanup, classification, and review creation behavior.
7. Compose `SqlDocumentRepository` in the facade and re-export compatibility names.
8. Run focused tests, compile, QCHECK/g-check review, then Graphite submit/land.

### Test Coverage
- `test_document_repository_is_split_behind_compatibility_facade`: validates split and facade.
- Existing document persistence tests: validate unchanged behavior.
- Existing document API tests: validate service/route import compatibility.

### Decision Completeness
Goal: make document repository maintenance cheaper without changing behavior.
Non-goals: no DB migration, no API change, no canonical ingest redesign, no storage provider change.
Success criteria: facade line count drops materially; focused modules exist; all prior document behavior tests pass; public imports remain valid.
Public interfaces: unchanged Python import surface from `egp_db.repositories.document_repo`; no runtime flags or schemas.
Edge cases/failure modes: fail closed on invalid tenant/document IDs and storage write failures; fallback to managed backup on read; duplicate replay remains non-creating.
Rollout & monitoring: behavior-preserving deploy; monitor document ingest failures, duplicate replay logs, and pending review creation.
Acceptance checks:
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q`
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase2/test_export_service.py -q`
- `./.venv/bin/python -m compileall packages/db/src apps/api/src apps/worker/src`

### Dependencies
Depends on Phase 2 document ingest work already present on `main`.

### Validation
Focused pytest first, compile after refactor, then PR checks before merge.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `SqlDocumentRepository` | API bootstrap and worker document ingest | `document_repo.py` facade and `repositories.__init__` | all document tables |
| `DocumentPersistenceMixin` | `store_document`, `list_documents`, `get_document` | inherited by `SqlDocumentRepository` | `documents` |
| `DocumentDiffMixin` | `store_document` and diff routes | inherited by `SqlDocumentRepository` | `document_diffs` |
| `DocumentReviewMixin` | review routes/service methods | inherited by `SqlDocumentRepository` | `document_diff_reviews`, `document_review_events` |
| `DocumentDeliveryMixin` | download/content/export paths | inherited by `SqlDocumentRepository` | `documents.storage_key`, `managed_backup_storage_key` |

## Implementation Summary (2026-05-16 12:30:59 +07)

### Goal
Implement PR 15 by splitting the large document repository module while keeping `egp_db.repositories.document_repo` as the compatibility facade.

### What Changed
- `packages/db/src/egp_db/repositories/document_repo.py`: replaced the 1,749-line implementation with a 189-line facade, public repository class composition, factories, compatibility exports, and legacy `hash_file` / `classify_document` patch targets.
- `packages/db/src/egp_db/repositories/document_models.py`: moved document dataclasses and `DocumentArtifactReadError`.
- `packages/db/src/egp_db/repositories/document_schema.py`: moved SQLAlchemy table/index definitions.
- `packages/db/src/egp_db/repositories/document_utils.py`: moved mappers, normalization helpers, content-type guessing, and `build_document_record`.
- `packages/db/src/egp_db/repositories/document_persistence.py`: moved document store/list/get and artifact-bucket persistence behavior.
- `packages/db/src/egp_db/repositories/document_diffs.py`: moved diff target lookup, diff building, and diff read APIs.
- `packages/db/src/egp_db/repositories/document_reviews.py`: moved review creation, event history, pagination, lookup, and status transitions.
- `packages/db/src/egp_db/repositories/document_delivery.py`: moved artifact store resolution, download URL, byte reads, and streaming behavior.
- `tests/phase1/test_document_persistence.py`: added `test_document_repository_is_split_behind_compatibility_facade`.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q -k split_behind_compatibility_facade`
  - Failed with `ModuleNotFoundError: No module named 'egp_db.repositories.document_models'`.
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q -k split_behind_compatibility_facade`
  - Passed after split modules and facade exports were added.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q` -> `24 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase2/test_export_service.py -q` -> `34 passed, 14 warnings`
- `./.venv/bin/python -m pytest tests/phase1/test_phase1_wiring.py tests/phase3/test_document_ingest_contract.py -q` -> `7 passed`
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py tests/phase1/test_documents_api.py tests/phase2/test_export_service.py tests/phase1/test_phase1_wiring.py tests/phase3/test_document_ingest_contract.py -q` -> `65 passed, 14 warnings`
- `./.venv/bin/python -m ruff check packages/db/src/egp_db/repositories/document_*.py tests/phase1/test_document_persistence.py` -> `All checks passed`
- `./.venv/bin/python -m compileall packages/db/src apps/api/src apps/worker/src` -> passed

### Wiring Verification Evidence
- API/worker/import compatibility remains through `egp_db.repositories.document_repo`.
- `SqlDocumentRepository` composes `DocumentPersistenceMixin`, `DocumentDiffMixin`, `DocumentReviewMixin`, and `DocumentDeliveryMixin`.
- Existing imports from `apps/api`, `apps/worker`, `project_repo.py`, `support_repo.py`, `audit_repo.py`, and tests still target the facade.
- `document_repo.py` re-exports document tables, records, factories, `hash_file`, and `classify_document`.

### Behavior Changes And Risk Notes
- Intended behavior change: none.
- Compatibility risk handled: existing monkeypatch paths for `egp_db.repositories.document_repo.hash_file` and `classify_document` remain live.
- Operational logger compatibility handled: moved code still logs on `egp_db.repositories.document_repo`.
- Failure posture unchanged: storage write cleanup remains fail-closed; reads still fall back to managed backup where configured.

### Follow-Ups / Known Gaps
- Auggie semantic search returned HTTP 429 for planning and review context, so exploration used direct file inspection and exact-string searches.

## Review (2026-05-16 12:30:59 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree before PR packaging
- Commit: `dc87f5b3`
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-status`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted reads of `document_repo.py`, `document_persistence.py`, `document_diffs.py`, `document_reviews.py`, `document_delivery.py`; focused pytest/ruff/compileall commands listed above.

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
- Assumption: `egp_db.repositories.document_repo` remains the only supported public import path for document repository consumers.
- Assumption: no schema migration is expected for PR 15.

### Recommended Tests / Validation
- Keep the focused 65-test document/API/export/wiring gate in the PR validation notes.
- CI should still run the broader repository checks after PR submission.

### Rollout Notes
- Behavior-preserving refactor; no flags or migration sequencing required.
- Watch normal document ingest/download/review logs after deployment, especially `document_store_*` and `document_diff_previous_artifact_missing`.
