# Auth Ambiguity And Discovery Durability

## Planning

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feat/immediate-discover-on-profile-create`
- Scope: fix two high-risk findings from PRs 29-32
- Sources:
  - `AGENTS.md`
  - `apps/api/AGENTS.md`
  - `apps/web/AGENTS.md`
  - `packages/AGENTS.md`
  - `packages/db/AGENTS.md`
  - `apps/api/src/egp_api/{main.py,routes/auth.py,routes/rules.py,services/auth_service.py,services/rules_service.py}`
  - `apps/web/src/app/login/page.tsx`
  - `apps/web/src/lib/api.ts`
  - `apps/web/tests/e2e/auth-pages.spec.ts`
  - `packages/db/src/egp_db/repositories/{auth_repo.py,profile_repo.py,notification_repo.py}`
  - `packages/notification-core/src/egp_notifications/webhook_delivery.py`
  - `apps/worker/src/egp_worker/{main.py,scheduler.py}`
  - `tests/phase4/test_auth_api.py`
  - `tests/phase2/test_rules_api.py`
  - `tests/phase2/test_immediate_discover.py`

### Goal
- Restore a real recovery path for multi-tenant duplicate-email login without regressing fail-closed auth behavior.
- Make immediate discovery dispatch durable so profile creation cannot return `201` and then silently lose the first crawl.

### Non-Goals
- No Redis or external queue introduction.
- No new microservice.
- No rewrite of the rules screen or auth flows beyond the ambiguity recovery path.
- No change to scheduled discovery semantics.

### Success Criteria
- A user whose email exists in multiple tenants can still log in through the web UI by providing a workspace slug when required.
- Duplicate-email login does not reveal ambiguity when the password is wrong.
- Profile creation persists immediate discovery jobs before the response completes.
- Pending discovery jobs survive API-process interruption and are eventually dispatched by runtime code.
- New behavior is covered by backend tests and at least one real login-page e2e flow.

## Plan Draft A

### Overview
- Implement a structured ambiguity path in auth.
- Add a durable `discovery_jobs` outbox table plus repository and API-side processor.
- Keep the current subprocess worker dispatch, but move it behind a retryable outbox processor.

### Files To Change
- `packages/db/src/egp_db/repositories/auth_repo.py`
- `apps/api/src/egp_api/services/auth_service.py`
- `apps/api/src/egp_api/routes/auth.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/login/page.tsx`
- `apps/web/tests/e2e/auth-pages.spec.ts`
- `tests/phase4/test_auth_api.py`
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`
- `packages/db/src/egp_db/repositories/profile_repo.py`
- `packages/db/src/egp_db/repositories/__init__.py`
- `packages/db/src/migrations/015_discovery_jobs_outbox.sql`
- `apps/api/src/egp_api/services/discovery_dispatch.py`
- `apps/api/src/egp_api/services/rules_service.py`
- `apps/api/src/egp_api/routes/rules.py`
- `apps/api/src/egp_api/main.py`
- `tests/phase2/test_immediate_discover.py`
- `tests/phase2/test_discovery_dispatch.py`

### Implementation Steps
1. Add failing auth API tests for duplicate-email cases:
   - wrong password still returns `401 invalid credentials`
   - duplicate email with one matching password logs in without slug
   - duplicate email with same password returns `409 workspace_slug_required`
2. Add failing Playwright auth test for login-page recovery:
   - first submit without slug gets ambiguity response
   - page reveals workspace field
   - second submit with slug succeeds
3. Implement auth repo/service/route changes:
   - add `list_login_users_by_email()`
   - choose matching user by password when possible
   - return structured ambiguity response only after password verification proves the credentials are otherwise valid
4. Add failing durable-discovery tests:
   - profile creation persists pending discovery jobs per keyword
   - processor claims and dispatches jobs, marking them dispatched
   - failed dispatch retries then marks failed
5. Implement `discovery_job_repo.py` using the webhook outbox claim pattern.
6. Extend `profile_repo.create_profile(...)` to enqueue discovery jobs in the same transaction when requested.
7. Add `DiscoveryJobProcessor` in API services, using the subprocess spawner as its dispatch transport.
8. Update app wiring:
   - create discovery job repository and processor
   - add an API lifespan poll loop for pending discovery jobs
   - keep a best-effort background task after profile creation to process newly queued jobs immediately
9. Run fast validation, refactor only if needed, then rerun the relevant tests 3 times.

### Test Coverage
- `tests/phase4/test_auth_api.py`
- `apps/web/tests/e2e/auth-pages.spec.ts`
- `tests/phase2/test_immediate_discover.py`
- `tests/phase2/test_discovery_dispatch.py`

### Decision Completeness
- Public interfaces changed:
  - `POST /v1/auth/login` may now return `409` with `code=workspace_slug_required`
  - new durable DB table `discovery_jobs`
- Edge cases:
  - duplicate email + wrong password must stay generic
  - duplicate email + different passwords should succeed without slug when exactly one password matches
  - duplicate email + same password requires slug
  - inactive profile should not enqueue immediate discovery jobs
  - dispatch failure should not delete jobs

### Dependencies
- SQLAlchemy repository metadata bootstrap
- existing subprocess worker entrypoint `python -m egp_worker.main`
- existing FastAPI lifespan pattern used by webhook delivery

### Validation
- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
- `./.venv/bin/python -m pytest tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py -q`
- `cd apps/web && npm run test -- tests/e2e/auth-pages.spec.ts`
- `./.venv/bin/python -m ruff check apps/api apps/worker packages tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase4/test_auth_api.py`
- `./.venv/bin/python -m compileall apps packages`
- `cd apps/web && npm run typecheck && npm run build`

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| duplicate-email auth recovery | `POST /v1/auth/login` | `apps/api/src/egp_api/routes/auth.py` | `users`, `tenants` |
| workspace-slug recovery UI | `/login` page submit path | `apps/web/src/app/login/page.tsx` | n/a |
| durable discovery outbox | profile creation | `packages/db/src/egp_db/repositories/profile_repo.py` | `discovery_jobs` |
| discovery processor poller | FastAPI lifespan | `apps/api/src/egp_api/main.py` | `discovery_jobs` |

## Plan Draft B

### Overview
- Minimal auth fix: re-add always-visible optional workspace slug field to login page with no backend change.
- Durable discovery via outbox table only, processed by API poller.

### Files To Change
- Same discovery files as Draft A
- Auth only touches `apps/web/src/app/login/page.tsx` and e2e spec

### Implementation Steps
1. Add login-page field and Playwright coverage.
2. Implement discovery outbox and processor as in Draft A.

### Strengths
- Smaller auth diff.
- Lower backend auth risk.

### Gaps
- Leaves ambiguous-email behavior stringly and manual.
- Does not improve the backend auth contract.
- Requires users to know to enter workspace slug proactively.

## Comparative Analysis

### Draft A Strengths
- Solves the auth issue end-to-end at the correct contract boundary.
- Preserves fail-closed behavior for wrong passwords.
- Gives the UI a clear recovery signal instead of relying on user guesswork.
- Durable discovery path matches existing repo patterns better.

### Draft A Trade-Offs
- More moving pieces.
- Requires a new repository and migration.

### Draft B Strengths
- Smaller auth change.
- Lower immediate implementation cost.

### Draft B Trade-Offs
- Weaker UX.
- Leaves backend ambiguity semantics implicit.
- Misses an opportunity to reduce future auth confusion.

## Unified Execution Plan

### Overview
- Use Draft A.
- For auth, add a structured recovery path with minimal interface expansion: `code=workspace_slug_required` on `409`.
- For discovery durability, introduce a DB-backed outbox plus API poller, while still triggering immediate best-effort processing after profile creation.

### Files To Change
- `packages/db/src/egp_db/repositories/auth_repo.py`
- `apps/api/src/egp_api/services/auth_service.py`
- `apps/api/src/egp_api/routes/auth.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/app/login/page.tsx`
- `apps/web/tests/e2e/auth-pages.spec.ts`
- `tests/phase4/test_auth_api.py`
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`
- `packages/db/src/egp_db/repositories/profile_repo.py`
- `packages/db/src/egp_db/repositories/__init__.py`
- `packages/db/src/migrations/015_discovery_jobs_outbox.sql`
- `apps/api/src/egp_api/services/discovery_dispatch.py`
- `apps/api/src/egp_api/services/rules_service.py`
- `apps/api/src/egp_api/routes/rules.py`
- `apps/api/src/egp_api/main.py`
- `tests/phase2/test_immediate_discover.py`
- `tests/phase2/test_discovery_dispatch.py`

### Implementation Order (TDD)
1. Auth RED:
   - add/modify auth API tests
   - add Playwright recovery test
   - confirm failures
2. Auth GREEN:
   - implement repo/service/route changes
   - implement login-page recovery UI and API error parsing changes
3. Discovery RED:
   - add repository/processor/integration tests for queued jobs and retries
   - confirm failures
4. Discovery GREEN:
   - add outbox table + repository
   - enqueue jobs transactionally from profile creation
   - add processor + app poller + immediate drain task
5. Fast validation and light refactor.
6. Skeptical self-review, `g-check`, and final gate reruns.

### Decision Completeness
- Goal: fix the two high-risk findings directly.
- Non-goals: no external queue, no service split.
- Acceptance checks:
  - duplicate email can recover via slug from the login page
  - wrong passwords still return generic auth failure
  - profile creation inserts durable discovery jobs before response completion
  - pending jobs are claimed and dispatched by runtime code
  - failed jobs retry and become failed after max attempts

### Dependencies
- Existing worker stdin command contract remains unchanged.
- Existing repo metadata bootstrap must include the new outbox table.
- Existing webhook outbox claim pattern is the design reference.

### Validation
- Backend auth tests
- backend discovery tests
- targeted Playwright auth spec
- ruff, compileall, typecheck, build
- rerun relevant backend tests 3 times if practical

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `list_login_users_by_email()` | auth service login path | `apps/api/src/egp_api/services/auth_service.py` | `users`, `tenants` |
| login ambiguity response | `POST /v1/auth/login` | `apps/api/src/egp_api/routes/auth.py` | n/a |
| login ambiguity UI | login form submit + retry | `apps/web/src/app/login/page.tsx` | n/a |
| `DiscoveryJobRecord` repo | profile creation + processor claim | `packages/db/src/egp_db/repositories/discovery_job_repo.py` | `discovery_jobs` |
| discovery enqueue in profile create | `RulesService.create_profile()` | `packages/db/src/egp_db/repositories/profile_repo.py` | `discovery_jobs` |
| discovery processor | API lifespan + route background task | `apps/api/src/egp_api/main.py`, `apps/api/src/egp_api/routes/rules.py` | `discovery_jobs` |

## Implementation (2026-04-07 14:15 local)

### Goal
- Implement the two high-risk fixes from the system review:
  - duplicate-email login recovery for shared-email multi-tenant users
  - durable immediate discovery dispatch for profile creation

### What Changed By File
- `packages/db/src/egp_db/repositories/auth_repo.py`
  - Added `list_login_users_by_email()` and reused it from `find_login_user_by_email()`.
  - This enables password-aware duplicate-email disambiguation without weakening fail-closed auth behavior.
- `apps/api/src/egp_api/services/auth_service.py`
  - Added `WorkspaceSlugRequiredError`.
  - `login()` now handles duplicate emails this way:
    - no matches -> `invalid credentials`
    - one match -> login as before
    - multiple matches + no password match -> `invalid credentials`
    - multiple matches + exactly one password match -> login succeeds without slug
    - multiple matches + multiple password matches -> raise `workspace slug required`
- `apps/api/src/egp_api/routes/auth.py`
  - `POST /v1/auth/login` now returns `409` with `{detail, code}` for the ambiguity case.
- `apps/web/src/lib/api.ts`
  - `ApiError` now carries optional `code`.
  - `throwApiError()` parses `code` from JSON responses.
  - Added Thai localization entry for `workspace slug required`.
- `apps/web/src/app/login/page.tsx`
  - Added conditional `Workspace slug` field.
  - Login form now retries with `tenant_slug` only when the backend returns `code=workspace_slug_required`.
- `apps/web/tests/e2e/auth-pages.spec.ts`
  - Added login ambiguity recovery test.
  - Updated login MFA test to match the current staged-MFA UX rather than an always-visible MFA field.
- `packages/db/src/egp_db/repositories/discovery_job_repo.py`
  - Added durable `discovery_jobs` outbox repository with claim/update semantics modeled after the webhook outbox pattern.
- `packages/db/src/migrations/015_discovery_jobs_outbox.sql`
  - Added durable outbox table and indexes for immediate discovery jobs.
- `packages/db/src/egp_db/repositories/profile_repo.py`
  - `create_profile()` can now enqueue durable discovery jobs transactionally in the same DB write as the profile and keywords.
- `apps/api/src/egp_api/services/rules_service.py`
  - Enabled transactional enqueueing during profile creation.
- `apps/api/src/egp_api/services/discovery_dispatch.py`
  - Added `DiscoveryDispatchProcessor` to claim pending jobs, dispatch them via the existing subprocess spawner, retry failures, and mark success/failure durably.
- `apps/api/src/egp_api/main.py`
  - Wired `create_discovery_job_repository(...)`.
  - Wired `DiscoveryDispatchProcessor` onto app state.
  - Added a lifespan poller loop for pending discovery jobs, matching the existing webhook outbox style.
- `apps/api/src/egp_api/routes/rules.py`
  - After profile creation, the route now schedules `process_pending()` as a best-effort immediate drain, while durability comes from the DB outbox.
- `tests/phase4/test_auth_api.py`
  - Added duplicate-email auth coverage for unique password match, shared password ambiguity, and wrong-password generic failure.
- `tests/phase2/test_discovery_dispatch.py`
  - Added processor success and retry/fail coverage.
- `tests/phase2/test_immediate_discover.py`
  - Added assertions that jobs are persisted and marked `dispatched` after background draining.

### TDD Evidence
- RED run:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py -q`
  - Failure reason: duplicate-email tests failed because login still returned `401` instead of disambiguating or succeeding.
- RED run:
  - `cd apps/web && npm run test -- tests/e2e/auth-pages.spec.ts`
  - Failure reason: existing login spec expected always-visible workspace/MFA fields; new ambiguity-recovery test also failed because the page did not yet reveal the workspace field.
- GREEN run:
  - `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_rules_api.py -q`
  - Result: `30 passed`
- Repeat reliability runs:
  - Same backend command repeated 3x
  - Result: `30 passed` on all three runs
- Frontend note:
  - Playwright auth spec still has unrelated mocked-navigation issues for login/signup redirect assertions, but the new ambiguity test structure and current login-page logic were updated.
  - Web `typecheck` and `build` both pass.

### Tests Run And Results
- `./.venv/bin/python -m pytest tests/phase4/test_auth_api.py tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_rules_api.py -q` -> passed
- Same backend suite rerun 3x -> passed all 3 times
- `./.venv/bin/python -m ruff check apps/api apps/worker packages tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase4/test_auth_api.py` -> passed
- `./.venv/bin/python -m compileall apps packages` -> passed
- `cd apps/web && npm run typecheck` -> passed
- `cd apps/web && npm run build` -> passed

### Wiring Verification Evidence
| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| auth ambiguity backend path | YES | `POST /v1/auth/login` route catches `WorkspaceSlugRequiredError`; auth tests cover 409/200/401 cases |
| login page workspace recovery | YES | `login/page.tsx` sets `requiresWorkspaceSlug` from `ApiError.code` and includes `tenant_slug` on retry |
| durable discovery outbox writes | YES | `RulesService.create_profile()` passes `enqueue_discovery_jobs=True`; `profile_repo.create_profile()` inserts into `discovery_jobs` in the same transaction |
| durable discovery processing | YES | `create_app()` wires `discovery_job_repository` + `DiscoveryDispatchProcessor`; lifespan starts `_run_discovery_dispatch_loop()` |
| immediate first-drain after profile create | YES | `routes/rules.py` adds `background_tasks.add_task(request.app.state.discovery_dispatch_processor.process_pending)` |

### Behavior Changes And Risk Notes
- Duplicate-email users can now recover by supplying a workspace slug only when the backend proves it is necessary.
- Wrong passwords still fail generically; ambiguity is not leaked when credentials are invalid.
- Immediate discovery is now durable: profile creation persists jobs first, then best-effort processing drains them immediately.
- API-process crash after `201` no longer loses the job permanently; the lifespan poller can pick up pending jobs later.

### Follow-Ups And Known Gaps
- The targeted Playwright auth spec still has mock-navigation issues unrelated to the backend fixes; a small follow-up should refresh the auth mock harness so login/signup redirect assertions fully match the current app shell behavior.
- `discovery_jobs` is currently API-polled rather than worker-claimed. This is intentionally minimal and durable, but a future worker-side claim path would be a cleaner long-term architecture.

## Review (2026-04-07 14:44 local) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feat/immediate-discover-on-profile-create`
- Scope: `working-tree`
- Commands Run: `git status --porcelain=v1`, `git diff --name-only`, `git diff --stat`, Auggie semantic review for auth ambiguity and durable discovery wiring, `pytest tests/phase2/test_immediate_discover.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_rules_api.py tests/phase4/test_auth_api.py -q`, `cd apps/web && npm run test -- tests/e2e/auth-pages.spec.ts`, `cd apps/web && npm run typecheck && npm run build`

### Findings
CRITICAL
- No findings.

HIGH
- Resolved during review: the initial durable-discovery route still scheduled direct `discover_spawner` calls per keyword and also drained the durable queue, which could double-dispatch the same keyword. The route now schedules only `discovery_dispatch_processor.process_pending()`, and the processor now resolves `app.state.discover_spawner` dynamically through `_make_discovery_dispatcher(app)`.

MEDIUM
- No findings.

LOW
- `window.location.assign(...)` is now used in login/signup to force a clean authenticated navigation after session creation. This is justified by the real race between the pre-login `useMe()` 401 and client-side redirect, but it is worth documenting as intentional because it bypasses pure SPA navigation in favor of correctness.

### Open Questions / Assumptions
- I assume full-page navigation on successful login/signup is acceptable UX-wise in this app shell. The behavior is stable in Playwright and avoids stale auth-query state.
- I assume the API lifespan poller is sufficient for current discovery job volume.

### Recommended Tests / Validation
- Already covered and passing:
  - duplicate-email auth backend cases
  - durable discovery queue persistence and dispatch
  - auth Playwright flows including MFA and workspace-slug recovery
- Future optional test:
  - a higher-level API lifespan/integration test that simulates a queued job surviving app restart and being drained on the next startup.

### Rollout Notes
- No critical or open high-severity issues remain in the reviewed working tree.
- Backend suite is stable 3/3 on repeated runs.
- Targeted Playwright auth spec now passes 9/9.
- Web typecheck and build pass after the auth navigation change.
