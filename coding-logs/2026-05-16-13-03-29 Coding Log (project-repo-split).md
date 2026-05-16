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


## Review (2026-05-16 14:28:28 +0700) - system

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: entire system after PR 1-17 train, currently merged and synced to origin/main at 905e8d3a
- Commands Run: git status/log/sync checks; docs and AGENTS inspection; targeted pytest suites; web lint; exact searches for runtime/config hygiene
- Sources: AGENTS.md, CLAUDE.md, docs/PHASE1_PLAN.md, docs/DOCUMENT_INGEST_CONTRACT.md, docs/OPENAPI_CONTRACTS.md, docs/PRICING_AND_ENTITLEMENTS.md, docker-compose*.yml, API bootstrap/services/routes, worker workflows, DB repositories, frontend API client/types, phase tests
- Validation: `./.venv/bin/python scripts/check_main_sync.py --json` passed; `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py tests/phase4/test_entitlements.py -q` passed; `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py tests/phase2/test_discovery_dispatch.py tests/phase2/test_background_runtime_mode.py -q` passed; `(cd apps/web && npm run lint)` passed with a Next.js lint deprecation warning

### High-Level Assessment
- The PR train landed in a coherent direction. The system is now closer to the intended control-plane / worker-plane split, with API service wiring extracted from `create_app`, external background executors, a documented canonical document-ingest contract, generated OpenAPI type footholds, and decomposed repository modules.
- The strongest implementation wins are the explicit runtime mode, the central `DocumentIngestService`, the repository facades after splitting large files, and the tests that lock several contracts before/after refactors.
- The main remaining risk is that some architectural boundaries are semantic rather than mechanically enforced. The worker can still execute DB-backed service code, and discovery dispatch is still a synchronous subprocess orchestration model behind a cleaner abstraction.
- The most urgent product correctness gap is entitlement enforcement. The system computes capability flags but key service boundaries still check only for an active subscription.

### As-Is Pipeline Diagram
- HTTP requests enter FastAPI through the extracted bootstrap pipeline, auth resolves user/tenant context, services use repository facades backed by PostgreSQL, and document writes are intended to flow through `DocumentIngestService`. Discovery work is claimed by a background executor that uses `DiscoveryDispatchProcessor`, which delegates to `SubprocessDiscoveryDispatcher`; that launches worker subprocesses and waits for completion. Webhook delivery can run as an external executor. The web app calls the API through a mixed generated/manual TypeScript contract layer.

### Strengths
- `create_app` is now a facade around repository, service, middleware, and background builders, which makes startup behavior inspectable.
- The document-ingest contract is clearly documented, and the worker path now reuses the canonical ingest service instead of duplicating all semantics.
- Runtime mode separation is real enough for local/prod-like deployment: embedded loops can be disabled and external executors are first-class compose services.
- Repository splits reduce review blast radius while preserving stable facades for callers.
- OpenAPI generation is present and used by several frontend domains, which is the right path away from hand-maintained mirror contracts.

### Key Risks / Gaps (severity ordered)
CRITICAL
- No critical findings from the targeted review.

HIGH
- Capability flags are computed but not enforced at export/download service boundaries. `apps/api/src/egp_api/services/entitlement_service.py:119` marks active free trials as not export/download/notification eligible, but `require_active_subscription` at `apps/api/src/egp_api/services/entitlement_service.py:140` only checks that the tenant has an active subscription. `apps/api/src/egp_api/services/export_service.py:153` and `apps/api/src/egp_api/services/document_ingest_service.py:285` use that active-only gate for exports and document downloads. Observable risk: an active free-trial tenant can likely export or download documents despite `docs/PRICING_AND_ENTITLEMENTS.md` saying those features are disallowed.

MEDIUM
- Discovery runtime separation stops at process placement, not workload architecture. `apps/api/src/egp_api/services/discovery_dispatch.py:49` claims jobs, then processes them serially; `apps/api/src/egp_api/services/discovery_worker_dispatcher.py:200` launches a subprocess and `proc.communicate` can block up to three hours. Impact: one executor can become a long-lived blocking runner, throughput is bounded by process count, and failure isolation/observability remain limited.
- The worker/API ownership boundary is still partly enforceable only by convention. `apps/worker/src/egp_worker/workflows/document_ingest.py` imports the API `DocumentIngestService`, and the worker event-sink design still supports service-backed/direct-DB behavior when no internal API base URL is configured. This preserves local practicality but keeps architectural drift possible.
- OpenAPI adoption is real but incomplete. `apps/web/src/lib/api.ts` imports generated types for projects/documents/rules, while many high-change domains remain manual: auth/session, runs, dashboard, billing, admin, support, webhooks, storage settings, and payment flows. Drift risk is reduced, not removed.
- Latest main was admin-merged after remote GitHub checks were unavailable due to billing before job startup. Local targeted checks passed and main is synced, but the final tree has not had a normal remote CI signal.

LOW
- `next lint` currently passes but is deprecated and will be removed in Next.js 16. The web lint command should move to direct ESLint CLI before the framework upgrade makes this operationally noisy.
- Redis appears in both compose files and service dependency wiring, but exact search found no app/package runtime usage beyond compose and setup docs. Either document it as reserved for the next queue-backed worker step or remove it until it is actually used.
- There is no root README. The repo has useful docs, but a short root README would reduce onboarding friction and point developers to AGENTS, setup commands, and the current architecture docs.

### Drift Matrix
- Intended: free trial has no exports/downloads/notifications. Implemented: snapshot flags say that, service gates check active subscription only. Impact: monetization and data-access policy can be bypassed. Fix direction: add capability-specific entitlement guards and route export/download/notification call sites through them.
- Intended: background work decoupled from API process. Implemented: external executor exists, but discovery still blocks inside a subprocess dispatch loop. Impact: scaling and stuck-job behavior remain fragile. Fix direction: introduce queue/lease-based worker pool with bounded concurrency.
- Intended: API/control plane owns document-ingest semantics. Implemented: semantics are centralized, but worker imports API service and may run DB-backed service code. Impact: ownership is clearer but deployment boundary remains porous. Fix direction: prefer internal API/event transport in production or extract domain service into a deliberately shared package with strict interfaces.
- Intended: backend OpenAPI schema is the frontend contract source of truth. Implemented: generated types are used for first domains, but much of the client remains manual. Impact: contract drift remains in important workflows. Fix direction: migrate domains in priority order and add a CI drift check.
- Intended: production-like runtime is explicit. Implemented: compose mode is explicit, but Redis is provisioned without app usage. Impact: operators may infer a queue exists when it does not. Fix direction: either wire Redis into the dispatch architecture or remove/document it as future-only.

### Nit-Picks / Nitty Gritty
- Add negative service tests for free-trial export and document download attempts. The current entitlement tests prove snapshot values but do not appear to prove enforcement at the service/API boundary.
- Add a small executor-health view that reports last loop tick, claimed job id, in-flight duration, and last failure for webhook and discovery executors. Current externalization is useful, but operational visibility is still mostly logs and DB state.
- Consider a lightweight protocol/base context for split repository mixins if cross-mixin private helper assumptions grow. The current facade pattern is workable, but implicit inheritance contracts get harder to reason about as modules split further.
- Continue keeping migrations append-only and avoid renumbering historic duplicates; the migration policy now makes that clear.

### Tactical Improvements (1-3 days)
1. Add `require_capability` or equivalent methods to `TenantEntitlementService`, with explicit checks for `exports_allowed`, `document_download_allowed`, and `notifications_allowed`; update `ExportService`, `DocumentIngestService`, and notification dispatch gates; add free-trial-denied tests.
2. Replace `apps/web` lint script with direct ESLint CLI config before Next.js 16 removes `next lint`.
3. Add a root README that links AGENTS, setup commands, migration policy, runtime modes, document-ingest contract, and OpenAPI generation.
4. Decide whether Redis is future-reserved or active infrastructure; remove it from compose if unused, or document it as intentionally reserved for the worker queue migration.
5. Re-run or re-enable remote CI on latest main once GitHub billing/check execution is restored.

### Strategic Improvements (1-6 weeks)
1. Move discovery execution to a real queue-backed or lease-backed worker pool. Why now: PR 5-8 made the abstraction boundary; this is the moment to swap the engine before more features depend on subprocess semantics. Why not now: if production volume is tiny and operational incidents are low, the subprocess model buys time.
2. Finish OpenAPI migration by domain. Suggested order: runs/dashboard, billing/payment, admin/support, storage/webhooks, auth/session. Keep wrappers stable so page code changes stay small.
3. Decide the worker/API boundary explicitly. Either production workers call internal API/event endpoints and never write product state directly, or domain services move to a shared package with a narrow repository interface and both API/worker are legitimate hosts. The current hybrid is pragmatic but ambiguous.
4. Add operational health endpoints or CLI checks for external executors, including stuck job detection, backlog depth, and last successful dispatch/delivery timestamps.

### Big Architectural Changes (only if justified)
- Proposal: Replace synchronous subprocess discovery dispatch with queue/lease-backed workers.
  - Pros: bounded concurrency, safer retries, clearer stuck-job handling, better observability, horizontal scaling, less API-package coupling inside worker execution.
  - Cons: introduces queue/lease semantics, deployment complexity, migration work, and more explicit idempotency requirements.
  - Migration Plan: first add a dispatch-job interface and persist enqueue/claim state; run queue mode behind a runtime flag next to current subprocess mode; port one worker path; add stuck-job reconciliation and metrics; switch local compose; then switch production-like compose; finally delete blocking subprocess dispatch.
  - Tests/Rollout: keep existing dispatch tests as compatibility tests, add concurrent-claim tests, timeout/retry tests, idempotent completion tests, and a rollback flag to return to subprocess mode during the transition.
- Proposal: Complete the canonical frontend contract by moving from generated types only to generated typed client wrappers.
  - Pros: removes hand-maintained request/response shapes, makes schema drift visible, reduces frontend breakage during API refactors.
  - Cons: can create large noisy diffs if done all at once, and generated client ergonomics may need wrapper adaptation.
  - Migration Plan: keep `api.ts` public function names stable, replace internals domain by domain, add generated-type coverage tests per domain, then add CI drift check as required.
  - Tests/Rollout: domain unit tests for wrappers, backend OpenAPI determinism tests, and a CI step that fails on uncommitted generated output.

### Open Questions / Assumptions
- I reviewed the merged state on `main`, not each PR diff individually.
- I assume the pricing docs are authoritative for free-trial restrictions.
- I assume production intent is stronger separation than local-dev convenience; if direct DB-backed workers are acceptable in production, the worker-boundary concern becomes mostly a documentation issue.
