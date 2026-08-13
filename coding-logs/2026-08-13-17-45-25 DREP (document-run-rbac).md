# DREP: Document and Run Route RBAC

## 0. Profile and baseline

- Worktree: `/Users/subhajlimanond/dev/egp-g2-document-run-rbac`
- Branch: `fix/document-run-rbac`
- Baseline: `0f4d24db892ac75aaab968996ac8ff3c79de2105` (`origin/main`)
- Policies: root and `apps/api/AGENTS.md`; Python 3.12+, FastAPI, SQLAlchemy, SQLite/PostgreSQL.
- Coding Log: `coding-logs/2026-08-13-17-45-25 Coding Log (document-run-rbac).md`.
- PRIMARY by g2 Q1: authentication, authorization, tenancy, and object ownership. No DeepSeek.
- No migration, schema, generated API, frontend, or internal-route change.

## 1. Goal and success

Add explicit operation-level RBAC to all eight public document routes and all five public run routes.
All canonical authenticated roles (`owner`, `admin`, `support`, `analyst`, `viewer`) retain reads;
mutations require the existing run-operator set (`owner`, `admin`, `support`, `analyst`). Preserve
401 middleware behavior, explicit supplied-tenant 403, auth-disabled compatibility, and worker
automation.

Close confirmed object-tenant gaps in the same security contract: document ingest and task creation
must reject missing/foreign projects before any side effect, run creation must reject missing/foreign
profiles, and missing/foreign run IDs must be indistinguishable 404s. Worker tokens never
authenticate or elevate public routes.

Non-goals: new roles, support tenant override, internal document/run routes, middleware changes,
service refactors, entitlements, migrations, public schemas, or other security-train items.

## 2. Requirements

- **R1** Every document/run operation has an explicit role dependency.
- **R2** Canonical roles may read; viewer and unknown roles cannot mutate/read respectively.
- **R3** Missing authentication remains 401 `missing authentication`.
- **R4** Allowed role plus explicit foreign tenant remains 403 `tenant mismatch`.
- **R5** Ingest missing/foreign project is 404 `project not found` before rows, blob, diff, review, or audit.
- **R6** Task missing/foreign project is 404 `project not found` before task/run activity.
- **R7** Task/finish/log missing and foreign run IDs are identical 404 `run not found`.
- **R8** Existing tenant-scoped document foreign-object contracts remain non-oracular.
- **R9** Worker-token-only public requests are 401; viewer JWT plus token remains 403.
- **R10** Existing internal worker route inventory and direct automation remain unchanged.
- **R11** Auth-disabled behavior, entitlement ordering after ownership, and public schemas remain.
- **R12** Run creation with a missing/foreign profile is 404 `profile not found` before run creation.
- **R13** Malformed project/profile identifiers remain client errors, never unhandled 500s.

## 3. Route matrix

Documents: ingest and review action use `require_run_operator_role`; project documents/diffs/reviews,
diff detail, download, and download-link use new `require_authenticated_role`.

Runs: create, task, and finish use `require_run_operator_role`; list and log use
`require_authenticated_role`.

Order: middleware authentication -> decorator role dependency -> handler tenant resolution ->
service object ownership -> entitlement/business work -> persistence.

## 4. Files and functions

| ID | File | Contract |
|---|---|---|
| F1 | `apps/api/src/egp_api/auth.py` | add immutable canonical-role set and no-context-compatible `require_authenticated_role` |
| F2 | `apps/api/src/egp_api/routes/documents.py` | add all 8 dependencies; authenticated ingest tenant-project lookup before service |
| F3 | `apps/api/src/egp_api/routes/runs.py` | add all 5 dependencies; project exception; remove foreign-run 403 |
| F5 | `apps/api/src/egp_api/services/run_service.py` | optional project/profile repositories; fail closed for linked writes; scoped run lookups |
| F6 | `packages/db/src/egp_db/repositories/run_repo.py` | additive `find_run_by_id_for_tenant` |
| F7 | `apps/api/src/egp_api/bootstrap/services.py` | supply existing project/profile repositories to API RunService |
| F8 | `tests/phase4/test_document_run_rbac.py` | acceptance matrix and no-side-effect oracles |

Authenticated public document ingest checks `app.state.project_repository` before entering the
shared service. This preserves auth-disabled compatibility and direct worker ingest while closing
the public cross-tenant association path. `RunService.project_repository` is optional only for trusted instances that never create a
project-linked task (the standalone discovery reconciler). `create_task(project_id != None)` fails
closed with `RunProjectNotFoundError` when it is absent. Profile-linked run creation likewise fails
closed with `RunProfileNotFoundError`. The API instance always receives both repositories.

## 5. Test contract

Primary RED suite F8 covers all 13 routes for missing auth and explicit tenant mismatch; all reads
for unknown-role denial; all mutations for viewer denial; canonical viewer reads and analyst
mutations; worker-token non-auth/elevation; document foreign-project no rows/blobs/audit; task
foreign-project no task/run mutation; and missing/foreign run equivalence for task/finish/log.

Predicted RED: current viewer mutations reach handlers, unknown roles reach reads, document ingest
may create a foreign association/blob, task creation accepts a foreign project, run creation accepts
a foreign profile, malformed project IDs escape as 500, and foreign run IDs return distinct 403.

Focused command: `./.venv/bin/python -m pytest tests/phase4/test_document_run_rbac.py -q`.

## 6. Traceability and wiring

R1-R4 -> F1-F3/F8. R5 -> F2/F8. R6-R7 -> F3/F5/F6/F7/F8. R8-R13 -> F1-F3,F5-F8 plus existing
document/run/entitlement/internal-worker suites. Bootstrap already registers unchanged routers and
repositories. Direct worker document ingest supplies a tenant-aware project repository. Direct run
workers use repositories; the standalone executor RunService only reconciles missing workers.

## 7. Slice, gates, rollout

One PRIMARY slice S1, F1-F3 and F5-F8, no implementation delegate. Confirm RED, implement, repeat focused
scope three times, run existing document/run/internal-worker/entitlement/convention suites, ruff,
compile, migration/API-type checks, full Python and frontend gates, independent QCHECK, formal
g-check, one PR, admin squash merge, exact remote/local-main landing, then remove this worktree.

Deploy all API replicas promptly; mixed versions retain viewer mutation and cross-tenant association
risk. Monitor route-level 401/403/404 and mutation errors without new sensitive identifiers.
Rollback is code-only but restores all vulnerabilities and requires immediate remediation.

## 8. Stop lines and do-not-touch

Stop if a new role, support override, worker-token public access, internal route, middleware change,
migration/schema, OpenAPI model, mutable re-tenanting, transaction redesign, or production file
outside F1-F3/F5-F7 is needed. Do not touch middleware, main, internal routes, worker/discovery production,
document/project repositories, entitlements, shared enums, migrations, or frontend/generated files.
