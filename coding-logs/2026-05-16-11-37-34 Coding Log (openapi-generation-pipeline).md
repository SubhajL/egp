# Coding Log: OpenAPI Generation Pipeline

## Implementation Summary (2026-05-16 11:37:34 +07)

### Goal

Implement PR 12: add a deterministic OpenAPI generation pipeline so the backend schema can produce
frontend TypeScript API types, with committed artifacts and drift detection.

### What Changed

- `.github/workflows/ci.yml`
  - Added Python setup and backend dependency installation to the frontend lint/typecheck job.
  - Added `npm run check:api-types` as the CI drift gate.
- `scripts/export_openapi_schema.py`
  - Added a CLI and public helpers to build the packaged FastAPI OpenAPI schema without local
    secrets or a live database.
- `tests/phase2/test_openapi_generation_pipeline.py`
  - Added tests for schema metadata/path coverage and deterministic file output.
- `apps/web/package.json` and `apps/web/package-lock.json`
  - Added `openapi-typescript`.
  - Added `generate:openapi`, `generate:api-types`, and `check:api-types` scripts.
- `apps/web/scripts/generate-openapi-schema.sh`
  - Added deterministic schema export command.
- `apps/web/scripts/generate-api-types.sh`
  - Added schema plus TypeScript type generation command.
- `apps/web/scripts/check-api-types.sh`
  - Added temp-dir regeneration and committed artifact comparison.
- `apps/web/src/lib/generated/openapi.json`
  - Added committed generated OpenAPI schema.
- `apps/web/src/lib/generated/api-types.ts`
  - Added committed `openapi-typescript` output.
- `apps/web/tests/unit/generated-api-types.test.ts`
  - Added a frontend contract test that imports the committed schema and type-checks a generated
    project-list response type.
- `docs/OPENAPI_CONTRACTS.md`
  - Documented committed artifacts, generation commands, and drift checking.

### TDD Evidence

- RED:
  - `./.venv/bin/python -m pytest tests/phase2/test_openapi_generation_pipeline.py -q`
  - Failed with `ModuleNotFoundError: No module named 'scripts.export_openapi_schema'`.
- RED:
  - `npm run check:api-types`
  - Failed with `OpenAPI schema is out of date` before generated artifacts were committed.
- GREEN:
  - `./.venv/bin/python -m pytest tests/phase2/test_openapi_generation_pipeline.py -q`
  - Passed: `2 passed`.
- GREEN:
  - `npm run check:api-types`
  - Passed: `OpenAPI schema and generated API types are current.`

### Tests Run

- `./.venv/bin/python -m pytest tests/phase2/test_openapi_generation_pipeline.py -q` - passed
- `./.venv/bin/ruff check scripts/export_openapi_schema.py tests/phase2/test_openapi_generation_pipeline.py` - passed
- `npm run check:api-types` - passed
- `npm run test:unit` - passed
- `npm run typecheck` - passed
- `npm run lint` - passed
- `npm run build` - passed
- `./.venv/bin/python -m compileall scripts/export_openapi_schema.py tests/phase2/test_openapi_generation_pipeline.py` - passed

### Wiring Verification

- Backend schema source: `scripts/export_openapi_schema.py` imports `egp_api.main.create_app`.
- Frontend generation command: `apps/web/package.json` `generate:api-types`.
- Drift gate: `apps/web/package.json` `check:api-types`.
- CI registration: `.github/workflows/ci.yml` frontend lint/typecheck job.
- Committed artifacts consumed by TypeScript: `apps/web/src/lib/generated/api-types.ts`.
- Contract test registration: `apps/web/vitest.config.ts` already includes `tests/unit/**/*.test.ts`.

### Behavior Changes And Risk Notes

- No runtime API behavior changes.
- CI now fails if backend OpenAPI output and committed frontend generated types drift.
- The schema exporter uses SQLite, disables auth, supplies an explicit payment callback secret, and
  runs background mode as `external` to avoid local runtime dependencies during generation.

### Follow-Ups / Known Gaps

- PR 13 should migrate first frontend domains to the generated types instead of the manual
  `src/lib/api.ts` declarations.


## Review (2026-05-16 11:40:00 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main working tree before Graphite branch creation
- Scope: working-tree
- Commands Run: `git status --porcelain=v1`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff` / `nl -ba` inspections, `npm run check:api-types`, and the local gates listed above.

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings. A CI dependency risk was identified during review before this report was finalized: the OpenAPI exporter imports the packaged API and therefore needs full API dependencies, not only `fastapi`. The CI install step was corrected to install `-e .` plus `-e "apps/api[dev]"` before running `npm run check:api-types`.

LOW
- No findings.

### Open Questions / Assumptions
- Assumes CI runners can install editable local packages from the repo root and `apps/api`, matching existing Python CI behavior.
- Assumes committing generated OpenAPI JSON and generated TypeScript is the intended PR12 contract posture; this is documented in `docs/OPENAPI_CONTRACTS.md`.

### Recommended Tests / Validation
- Keep `npm run check:api-types` in CI as the source drift gate.
- PR 13 should add focused contract assertions around the first migrated frontend domains.

### Rollout Notes
- No runtime rollout risk. This change adds generated files, local scripts, and CI enforcement only.


## Submission / Landing Status (2026-05-16 11:43:00 +07)

- Created Graphite branch: `05-16-feat_add_openapi_type_generation_pipeline`.
- Submitted PR: https://github.com/SubhajL/egp/pull/84
- Remote CI did not execute because GitHub reported a repository/account billing blocker.
- Evidence: check-run annotation for `Frontend Lint & Typecheck` reported `The job was not started because your account is locked due to a billing issue.` The same immediate failure pattern applied across CI jobs.
- Added PR comment documenting the blocker: https://github.com/SubhajL/egp/pull/84#issuecomment-4465619367
- Landing is blocked until GitHub billing/check execution is restored. I did not bypass branch protection or push directly to `main`.
