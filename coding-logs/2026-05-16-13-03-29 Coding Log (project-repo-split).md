# Project Repository Split

## Plan

Split `packages/db/src/egp_db/repositories/project_repo.py` into focused repository modules while preserving the existing public compatibility import path.

### Files To Change

- `packages/db/src/egp_db/repositories/project_repo.py`: facade and factory.
- `packages/db/src/egp_db/repositories/project_models.py`: project and dashboard dataclasses.
- `packages/db/src/egp_db/repositories/project_schema.py`: SQLAlchemy table and index definitions.
- `packages/db/src/egp_db/repositories/project_utils.py`: normalization, mapping, and record-builder helpers.
- `packages/db/src/egp_db/repositories/project_aliases.py`: alias matching and status-event helper mixin.
- `packages/db/src/egp_db/repositories/project_persistence.py`: project upsert persistence.
- `packages/db/src/egp_db/repositories/project_lifecycle.py`: explicit project lifecycle transitions.
- `packages/db/src/egp_db/repositories/project_queries.py`: project detail/list queries.
- `packages/db/src/egp_db/repositories/project_dashboard.py`: dashboard project projections.
- `tests/phase1/test_project_repository_split.py`: structural facade regression test.

### Acceptance

- Public imports from `egp_db.repositories.project_repo` remain valid.
- Existing project/run/dashboard behavior tests pass unchanged.
- Tenant-scoped filters remain explicit in read/write paths.
- No schema changes or migration files are introduced.

## Implementation (2026-05-16 13:07:44 +0700)

### Goal

Deliver PR 17 by decomposing the project repository into persistence, aliases/lifecycle, queries, dashboard projections, schema/models/helpers, and a small compatibility facade.

### What Changed

- `packages/db/src/egp_db/repositories/project_repo.py`: reduced to the public facade, `SqlProjectRepository` mixin composition, public exports, and factory.
- `packages/db/src/egp_db/repositories/project_models.py`: moved public project and dashboard dataclasses.
- `packages/db/src/egp_db/repositories/project_schema.py`: moved project SQLAlchemy tables and indexes.
- `packages/db/src/egp_db/repositories/project_utils.py`: moved normalization, mapping, status-event dedupe, dashboard helper constants, and `build_project_upsert_record`.
- `packages/db/src/egp_db/repositories/project_aliases.py`: moved alias lookup/upsert and status-event insert helpers.
- `packages/db/src/egp_db/repositories/project_persistence.py`: moved upsert/schema bootstrap operations.
- `packages/db/src/egp_db/repositories/project_lifecycle.py`: moved `transition_project`.
- `packages/db/src/egp_db/repositories/project_queries.py`: moved `get_project`, `find_existing_project`, `get_project_detail`, and `list_projects`.
- `packages/db/src/egp_db/repositories/project_dashboard.py`: moved dashboard projection query logic.
- `tests/phase1/test_project_repository_split.py`: added a structural regression test that verifies the facade is composed from the expected mixins and re-exports the original model/table objects.

### TDD Evidence

- RED: `./.venv/bin/python -m pytest tests/phase1/test_project_repository_split.py -q`
  - Failed during collection because `egp_db.repositories.project_models` and `project_schema` did not exist yet.
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_project_repository_split.py tests/phase1/test_project_and_run_persistence.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_dashboard_api.py -q`
  - Passed: `28 passed in 1.18s`.

### Tests Run

- `./.venv/bin/python -m pytest tests/phase1/test_project_repository_split.py -q` - passed after implementation.
- `./.venv/bin/python -m pytest tests/phase1/test_project_and_run_persistence.py tests/phase1/test_high_risk_architecture.py tests/phase2/test_dashboard_api.py -q` - passed.
- `./.venv/bin/ruff check packages/db/src tests/phase1/test_project_repository_split.py` - passed.
- `./.venv/bin/ruff format --check packages/db/src tests/phase1/test_project_repository_split.py` - passed.
- `./.venv/bin/python -m compileall packages/db/src` - passed.

### Wiring Verification

- Existing import path remains `egp_db.repositories.project_repo`; API, worker, audit, and tests still import from that facade.
- `SqlProjectRepository` composes `ProjectPersistenceMixin`, `ProjectAliasMixin`, `ProjectLifecycleMixin`, `ProjectQueryMixin`, and `ProjectDashboardMixin`.
- `_ensure_schema()` still uses the same `DB_METADATA` table objects through `project_schema.METADATA`.
- Tenant-scoped reads/writes still normalize and filter `tenant_id` in persistence, lifecycle, query, and dashboard modules.

### Behavior And Risk Notes

- Behavior is intended to be unchanged; this is a pure repository decomposition.
- No migrations, schema changes, env flags, or runtime wiring changes were introduced.
- Auggie semantic retrieval was unavailable due to HTTP 429, so implementation and review used direct file inspection plus exact identifier searches.

### Follow-Ups / Known Gaps

- None for this PR.

## Review (2026-05-16 13:07:44 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree before Graphite packaging
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `git ls-files --others --exclude-standard`; targeted `sed`/`nl` reads of the facade and new repository modules; `rg -n "tenant_id|normalized_tenant_id|PROJECTS_TABLE\.c\.tenant_id|DOCUMENTS_TABLE\.c\.tenant_id|DOCUMENT_DIFFS_TABLE\.c\.tenant_id" packages/db/src/egp_db/repositories/project_*.py`; focused pytest/ruff/compileall commands listed above.

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

- Assumption: preserving `egp_db.repositories.project_repo` as the public compatibility path is the desired migration strategy, matching the prior document and billing repository splits.

### Recommended Tests / Validation

- Keep the focused project/run/dashboard pytest suite in the PR checks.
- CI should run the broader repository gates after submission.

### Rollout Notes

- Pure Python refactor with no schema or runtime config changes.
- Rollback is a normal PR revert.

## Submission / Landing Status (2026-05-16 13:11:21 +0700)

- Created Graphite branch `refactor/db-split-project-repository`.
- Submitted PR: https://github.com/SubhajL/egp/pull/89
- Added PR comment with local validation evidence.
- Landing is blocked by GitHub Actions infrastructure: every required workflow job failed before startup with the annotation `The job was not started because your account is locked due to a billing issue.`
- Because required CI did not run, the PR was not merged and `main` was not advanced.
