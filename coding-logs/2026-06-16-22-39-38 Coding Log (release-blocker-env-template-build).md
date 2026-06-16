# Coding Log: release-blocker-env-template-build

## Plan (2026-06-16 22:39:38 +07)

### Exploration Notes

- Root `AGENTS.md` and `apps/web/AGENTS.md` read.
- `CLAUDE.md` env-variable section read: `deploy/.env.production.example` is the authoritative production env template and frontend `NEXT_PUBLIC_*` vars normally live in Vercel, with template values used for the optional single-host Compose profile.
- Auggie semantic retrieval was attempted for the env/build blocker context and failed with `HTTP error: 402`; this plan is based on direct file inspection and exact-string searches.
- Current `main` is synced with `origin/main` but dirty with pre-existing edits in `apps/worker/src/egp_worker/browser_downloads.py`, `tests/phase1/test_worker_browser_downloads.py`, `deploy/systemd/egp-document-backfill-enqueue.service`, and coding-log files.

## Plan Draft A

### Overview

Fix the two confirmed release blockers directly in the existing runtime surfaces: normalize `NEXT_PUBLIC_SITE_URL` before any Next metadata route constructs URLs, and add `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS` to the production env template. Keep Docker smoke as a verification step once Docker/OrbStack is available.

### Files To Change

- `apps/web/src/lib/site-url.ts`: add a small shared helper for production site URL normalization.
- `apps/web/src/app/layout.tsx`: use normalized site URL for `metadataBase`.
- `apps/web/src/app/page.tsx`: use normalized site URL for metadata, canonical URLs, and JSON-LD.
- `apps/web/src/app/robots.ts`: use normalized site URL for robots host and sitemap URL.
- `apps/web/src/app/sitemap.ts`: use normalized site URL for sitemap entries.
- `apps/web/tests/unit/site-url.test.ts`: cover empty, whitespace, valid, and invalid env values.
- `deploy/.env.production.example`: add `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS=600000` beside the related Cloudflare browser settings.

### Implementation Steps

1. Add failing unit tests for a `getSiteBaseUrl()` helper.
2. Run `cd apps/web && npm run test:unit -- --run tests/unit/site-url.test.ts` and confirm missing module/failing behavior.
3. Implement `getSiteBaseUrl()` with trim + valid absolute URL check + fallback.
4. Wire metadata/robots/sitemap/page to the helper.
5. Add the missing env template variable.
6. Run focused tests and validation gates.

### Test Coverage

- `site-url.test.ts`: empty string falls back safely.
- `site-url.test.ts`: whitespace falls back safely.
- `site-url.test.ts`: valid URL is trimmed and preserved.
- `site-url.test.ts`: invalid URL falls back safely.
- `test_env_template_tracks_runtime_egp_vars`: template covers runtime EGP vars.

### Decision Completeness

- Goal: make local production build resilient to quoted-empty `NEXT_PUBLIC_SITE_URL`, make the Python env drift test green, and leave the repo in a releasable branch/PR state.
- Non-goals: change production Vercel settings, change Docker/OrbStack installation, alter crawler behavior, or rewrite unrelated dirty changes.
- Success criteria: focused frontend test passes; `npm run build` passes with the local env; env template drift test passes; relevant Python/frontend gates pass; g-check has no blocking findings; PR is created and merged; local `main` contains the merge.
- Public interfaces: `NEXT_PUBLIC_SITE_URL` empty/invalid values now fall back to `https://egp.example.com`; `deploy/.env.production.example` gains `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS`.
- Edge cases / failure modes: empty, whitespace, or invalid site URL values fail open to placeholder metadata URL; valid URLs are preserved. Runtime operator timeout defaults remain 600000 ms.
- Rollout & monitoring: frontend change auto-deploys via Vercel after merge; env template change only affects future env sync/copies. Lightsail deployment is required only if backend/runtime files included in the merged PR affect API/worker runtime.
- Acceptance checks: `cd apps/web && npm run test:unit -- --run tests/unit/site-url.test.ts`; `./.venv/bin/python -m pytest tests/operations/test_env_template.py -q`; `cd apps/web && npm run build`; `./scripts/check_main_sync.py --json`; Docker-backed smoke if Docker is running.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `getSiteBaseUrl()` | Next metadata/robots/sitemap module evaluation | imports in `layout.tsx`, `page.tsx`, `robots.ts`, `sitemap.ts` | N/A |
| `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS` template entry | `apps/api/src/egp_api/config.py` and `apps/worker/src/egp_worker/warmup.py` | env loading by config helpers and warmup settings | N/A |

## Plan Draft B

### Overview

Avoid new helper code by changing only `apps/web/.env.production.local` and `deploy/.env.production.example`. This makes the current local build pass quickly but leaves the application fragile if another environment sets an empty or invalid public site URL.

### Files To Change

- `apps/web/.env.production.local`: set a real local URL.
- `deploy/.env.production.example`: add the missing operator timeout.

### Implementation Steps

1. Edit local ignored env file to provide a valid `NEXT_PUBLIC_SITE_URL`.
2. Add missing env template entry.
3. Run `npm run build` and env drift test.

### Test Coverage

- `test_env_template_tracks_runtime_egp_vars`: template covers runtime EGP vars.
- Manual `npm run build`: local env no longer fails.

### Decision Completeness

- Goal: unblock this one local workspace.
- Non-goals: make metadata URL construction robust for other environments.
- Success criteria: current local build and env drift test pass.
- Public interfaces: env template addition only.
- Edge cases / failure modes: future empty/invalid `NEXT_PUBLIC_SITE_URL` still crashes build.
- Rollout & monitoring: no app code deployment needed for frontend resilience because none is added.
- Acceptance checks: `npm run build`; env drift test.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS` template entry | runtime env config/warmup | production env template | N/A |

## Comparative Analysis

- Draft A fixes the actual fragility in code and prevents recurrence anywhere an empty value is injected.
- Draft B is faster but only masks the local machine state and leaves a known footgun in the build path.
- Draft A has a slightly broader frontend surface but is still narrow, testable, and aligned with `apps/web` conventions.
- Both drafts add the missing env template variable, but only Draft A gives a code-level regression test for the build blocker.

## Unified Execution Plan

1. Use Draft A.
2. Add the site URL unit test first and confirm it fails before implementation.
3. Implement `getSiteBaseUrl()` and wire all metadata URL call sites to it.
4. Add `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS=600000` to `deploy/.env.production.example` next to related Cloudflare browser timeout variables.
5. Run focused frontend/Python tests, then `npm run build`.
6. Run Docker smoke only if Docker/OrbStack is available; otherwise record the external blocker.
7. Stage only this release-blocker slice plus the Coding Log, run g-check, address findings, then package through PR/merge/local-main landing.
8. Deploy to Lightsail only if the final merged PR contains backend/API/worker runtime changes; the intended slice is frontend+env-template, so Vercel frontend auto-deploy verification is expected to be sufficient unless packaging scope expands.

### Decision-Complete Checklist

- No open implementation decisions remain.
- Changed public env behavior is listed.
- Frontend empty/invalid URL behavior has direct unit tests.
- Env template drift has direct operation test coverage.
- Wiring verification covers new helper imports and env template runtime references.
- Rollout/backout is specified: revert the helper/template commit or reset Vercel env to valid URL; no DB migration involved.

## Implementation Summary (2026-06-16 23:01:00 +07)

### Goal

Clear the release blockers from the local workspace: fix the local production web build with an empty quoted `NEXT_PUBLIC_SITE_URL`, fix env-template drift for `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS`, verify the full Python suite, bring Docker/OrbStack up, and make the local Postgres smoke pass.

### What Changed

- `apps/web/src/lib/site-url.ts`: added `getSiteBaseUrl()` to trim and validate the public site URL before Next metadata routes construct `URL` objects.
- `apps/web/src/app/layout.tsx`, `apps/web/src/app/page.tsx`, `apps/web/src/app/robots.ts`, `apps/web/src/app/sitemap.ts`: routed metadata, robots, and sitemap base URLs through `getSiteBaseUrl()`.
- `apps/web/tests/unit/site-url.test.ts`: added regression coverage for empty, whitespace, invalid, and valid site URLs.
- `deploy/.env.production.example`: added `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS=600000` beside the existing Cloudflare browser timeout knobs.
- `packages/db/src/egp_db/dev_postgres.py`: added `_create_phase1_smoke_app()` so the local smoke supplies an explicit dummy payment callback secret while preserving production fail-closed behavior.
- `tests/phase1/test_dev_postgres.py`: added coverage that the local smoke app is created with `auth_required=False` and the dummy callback secret.

### TDD Evidence

- RED: `npm run test:unit -- --run tests/unit/site-url.test.ts` failed because `../../src/lib/site-url` did not exist.
- GREEN: `npm run test:unit -- --run tests/unit/site-url.test.ts` passed with 4 tests.
- RED: `./.venv/bin/python -m pytest tests/phase1/test_dev_postgres.py -q` failed importing missing `_create_phase1_smoke_app`.
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_dev_postgres.py -q` passed with 6 tests.

### Validation

- `npm run test:unit -- --run tests/unit/site-url.test.ts`: 4 passed.
- `npm run test:unit`: 44 passed.
- `npm run typecheck`: passed.
- `npm run lint`: passed.
- `npm run build`: passed with `.env.production.local` loaded.
- `./.venv/bin/python -m pytest tests/operations/test_env_template.py -q`: 15 passed.
- `./.venv/bin/python -m pytest`: 1241 passed, 106 warnings.
- `open -ga OrbStack` then `docker info`: Docker daemon healthy.
- `docker compose -f docker-compose-localdev.yml up -d postgres`: `egp-postgres` running.
- `./.venv/bin/python -m egp_db.migration_runner --database-url postgresql://egp:egp_dev@localhost:5432/egp --migrations-dir packages/db/src/migrations`: applied pending local migrations.
- `./.venv/bin/python scripts/run_phase1_postgres_smoke.py`: passed; document smoke returned status 201, listed 1 document, download 200, project-run smoke status `succeeded`.
- `./.venv/bin/python -m ruff format --check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py packages/db/src/egp_db/dev_postgres.py tests/phase1/test_dev_postgres.py`: passed.
- `./.venv/bin/python -m ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py packages/db/src/egp_db/dev_postgres.py tests/phase1/test_dev_postgres.py`: passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`: 54 passed.

### Wiring Verification

| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| `getSiteBaseUrl()` | YES | `rg -n "getSiteBaseUrl" apps/web/src` shows imports in `layout.tsx`, `page.tsx`, `robots.ts`, and `sitemap.ts`. |
| `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS` template entry | YES | `rg -n "EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS"` shows runtime reads in API config and worker warmup plus the template entry. |
| `_create_phase1_smoke_app()` | YES | `run_phase1_postgres_smoke()` calls the helper before creating `TestClient`; focused test captures the helper's `create_app()` kwargs. |

### Risk Notes

- Empty or invalid `NEXT_PUBLIC_SITE_URL` now fails open to the existing placeholder metadata URL instead of crashing the build.
- Production `payment_callback_secret` remains fail-closed; only the local smoke helper passes a deterministic dummy secret.
- Docker was not changed in code; OrbStack was started locally to unblock the smoke.
- The worktree also contains pre-existing worker/systemd document-capture changes and their coding log. Those are being packaged with this release-cleanup pass so local `main` can become clean after merge instead of leaving uncommitted runtime changes behind.

## Review (2026-06-16 22:52:24 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged working tree against `bc4ae0bd2ba1639dc1e83c0135da36f347e45860`
- Commands Run:
  - `git status -sb`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- <targeted files>`
  - `rg -n "getSiteBaseUrl|EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS|_create_phase1_smoke_app"`
  - `npm run test:unit -- --run tests/unit/site-url.test.ts`
  - `npm run test:unit`
  - `npm run typecheck`
  - `npm run lint`
  - `npm run build`
  - `./.venv/bin/python -m pytest tests/operations/test_env_template.py -q`
  - `./.venv/bin/python -m pytest`
  - `./.venv/bin/python -m ruff format --check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py packages/db/src/egp_db/dev_postgres.py tests/phase1/test_dev_postgres.py`
  - `./.venv/bin/python -m ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py packages/db/src/egp_db/dev_postgres.py tests/phase1/test_dev_postgres.py`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_dev_postgres.py -q`
  - `docker info`
  - `docker compose -f docker-compose-localdev.yml up -d postgres`
  - `./.venv/bin/python -m egp_db.migration_runner --database-url postgresql://egp:egp_dev@localhost:5432/egp --migrations-dir packages/db/src/migrations`
  - `./.venv/bin/python scripts/run_phase1_postgres_smoke.py`

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

- The staged PR intentionally includes the pre-existing worker/systemd document-capture changes so the dirty local `main` can be cleaned by landing the full worktree instead of leaving runtime changes uncommitted.
- The systemd working directory change assumes the production Lightsail checkout path is `/home/ubuntu/egp`, matching the prior verified host deployment notes.

### Recommended Tests / Validation

- Keep the current local gates as merge prerequisites: full Python suite, web unit/typecheck/lint/build, env-template drift test, local Postgres smoke.
- After merge, verify Vercel frontend production deployment for the web build fix.
- Because the staged surface includes worker and systemd runtime changes, deploy/verify Lightsail API/worker runtime if this PR lands.

### Rollout Notes

- Frontend fix is Vercel-deployed from `main`.
- API/worker/systemd changes are not auto-deployed from `main`; Lightsail needs manual update and runtime health checks after merge.
- Backout is revert of the PR plus redeploying Lightsail if the worker/systemd portion has already been deployed.
