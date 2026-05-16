# Capability Entitlement Guards

## Plan Draft A

### Overview
Add a canonical `TenantEntitlementService.require_capability()` guard for plan capabilities and update export, document download, and notification paths to use it. Free-trial tenants already expose false capability flags, so this plan reuses that snapshot source and fails closed at protected boundaries.

### Files To Change
- `apps/api/src/egp_api/services/entitlement_service.py`: add capability key mapping and guard.
- `apps/api/src/egp_api/services/export_service.py`: require `exports`.
- `apps/api/src/egp_api/services/document_ingest_service.py`: require `document_downloads`.
- `apps/api/src/egp_api/services/webhook_service.py`: optionally enforce notification entitlement in service methods.
- `apps/api/src/egp_api/bootstrap/services.py`: wire entitlement service into notification-boundary services if service-layer enforcement is chosen.
- `tests/phase4/test_entitlements.py`: add free-trial negative tests for export/download/notification dispatch.
- `tests/phase4/test_webhooks_api.py`: add free-trial negative test for webhook creation if route/service boundary is guarded.

### Implementation Steps
1. Add tests first:
   1. Add free-trial export denial test.
   2. Add free-trial document download and download-link denial tests.
   3. Add free-trial webhook create denial test.
   4. Run the targeted tests and confirm they fail because current guards only check active subscription.
2. Implement `TenantEntitlementService.require_capability(tenant_id, capability)`:
   - Accept keys `exports`, `document_downloads`, `notifications`.
   - Reuse `get_snapshot()`.
   - If no active subscription, raise `active subscription required for <label>`.
   - If active but capability flag is false, raise `<label> capability is not included in current plan`.
   - Raise `ValueError` for unknown capability keys.
3. Replace export and document download `require_active_subscription()` calls with `require_capability()`.
4. Route notification boundaries through the same guard:
   - `EntitlementAwareNotificationDispatcher.dispatch()` uses `require_capability("notifications")` and suppresses denied notifications.
   - `WebhookService.create_webhook()` rejects free-trial configuration attempts when wired with the entitlement service.
5. Run formatting/lint/targeted tests.

### Test Coverage
- `test_free_trial_export_is_denied_by_exports_capability`: blocks export.
- `test_free_trial_document_download_is_denied_by_download_capability`: blocks proxied download.
- `test_free_trial_document_download_link_is_denied_by_download_capability`: blocks signed link.
- `test_free_trial_webhook_creation_is_denied_by_notifications_capability`: blocks notification config.
- Existing notification suppression test: validates dispatch remains suppressed.

### Decision Completeness
- Goal: enforce capability-specific plan gates for exports, document downloads, and notifications.
- Non-goals: add DB schema, change billing plan catalog, alter run/discovery entitlement behavior, or change frontend UI.
- Success criteria: all protected free-trial operations return 403 or suppress dispatch; monthly plans continue passing existing tests.
- Public interfaces: no new endpoints; error detail changes only for active-but-not-included capabilities.
- Edge cases / failure modes: missing subscription fails closed as before; unknown capability raises programmer error; free-trial active subscription fails closed for gated features.
- Rollout & monitoring: pure application-layer guard; watch 403 rates on export/download/webhook endpoints and notification dispatch counts.
- Acceptance checks: targeted pytest for phase4 entitlements/webhooks and phase2 export route; ruff for API/package files.

### Dependencies
No new dependencies.

### Validation
Run targeted pytest first, then ruff.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `require_capability()` | service calls from export/download/notification paths | `TenantEntitlementService` is attached to `app.state.entitlement_service` in `bootstrap/services.py` | `billing_subscriptions`, `crawl_profile_keywords` |
| Export guard | `GET /v1/exports/excel` | `app.state.export_service = ExportService(... entitlement_service=...)` | reads subscription snapshot |
| Document download guard | `GET /v1/documents/{id}/download`, `/download-link` | `app.state.document_ingest_service = DocumentIngestService(... entitlement_service=...)` | reads subscription snapshot |
| Notification guard | `POST /v1/webhooks`, notification dispatcher dispatch calls | `app.state.webhook_service`, `app.state.notification_dispatcher` | reads subscription snapshot |

## Plan Draft B

### Overview
Keep route handlers responsible for capability checks and leave lower-level services as-is. This makes the HTTP boundaries explicit but risks future internal callers bypassing entitlement checks.

### Files To Change
- `apps/api/src/egp_api/services/entitlement_service.py`: add `require_capability()`.
- `apps/api/src/egp_api/routes/exports.py`: call guard before export service.
- `apps/api/src/egp_api/routes/documents.py`: call guard before download and download-link service calls.
- `apps/api/src/egp_api/routes/webhooks.py`: call guard before webhook creation.
- Tests under `tests/phase4/`.

### Implementation Steps
1. Add the same negative free-trial tests.
2. Add route helper to fetch `app.state.entitlement_service`.
3. Call `require_capability()` in HTTP handlers before service calls.
4. Run targeted tests and ruff.

### Test Coverage
- Same negative free-trial test names as Draft A.

### Decision Completeness
- Goal: enforce capability checks at HTTP boundaries.
- Non-goals: protect service-level direct calls.
- Success criteria: HTTP free-trial operations fail with 403.
- Public interfaces: same endpoints; same error status.
- Edge cases / failure modes: route-only checks can be bypassed by future background/internal callers.
- Rollout & monitoring: same as Draft A.
- Acceptance checks: targeted pytest and ruff.

### Dependencies
No new dependencies.

### Validation
Run targeted pytest and ruff.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `require_capability()` | route handlers | FastAPI routers included by `egp_api.routes` | `billing_subscriptions`, `crawl_profile_keywords` |
| Export route guard | `GET /v1/exports/excel` | router registration | reads subscription snapshot |
| Document route guards | `GET /v1/documents/{id}/download`, `/download-link` | router registration | reads subscription snapshot |
| Webhook route guard | `POST /v1/webhooks` | router registration | reads subscription snapshot |

## Comparative Analysis
Draft A protects both HTTP entry points and internal service callers, which better matches existing run/export/document entitlement patterns. Draft B is smaller in surface area, but it leaves direct service usage vulnerable and duplicates guard wiring across routes.

Draft A is the stronger fit because export and document download entitlement checks already live in services, and notification dispatch is already wrapped by an entitlement-aware dispatcher. The only added service wiring is `WebhookService`, which keeps notification configuration consistent with notification dispatch.

## Unified Execution Plan

### Overview
Implement Draft A with narrowly scoped service-layer guards and a notification configuration guard in `WebhookService`. Keep existing inactive-subscription error text, add a clear active-plan-denied error for free-trial capability exclusions, and preserve current monthly-plan behavior.

### Files To Change
- `apps/api/src/egp_api/services/entitlement_service.py`: canonical capability registry and guard.
- `apps/api/src/egp_api/services/export_service.py`: export guard swap.
- `apps/api/src/egp_api/services/document_ingest_service.py`: download guard swaps.
- `apps/api/src/egp_api/services/webhook_service.py`: notification capability guard for create.
- `apps/api/src/egp_api/bootstrap/services.py`: pass entitlement service into webhook service.
- `tests/phase4/test_entitlements.py`: free-trial export/download/download-link tests and dispatch assertion.
- `tests/phase4/test_webhooks_api.py`: free-trial webhook creation denial.

### Implementation Steps
1. Add/stub tests.
2. Run the targeted tests and confirm RED:
   - `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py -q`
3. Implement guard and wiring:
   - `TenantEntitlementService.require_capability()`: canonical capability decision.
   - `ExportService.export_to_excel()`: call `require_capability("exports")`.
   - `DocumentIngestService` download helpers: call `require_capability("document_downloads")`.
   - `EntitlementAwareNotificationDispatcher.dispatch()`: call `require_capability("notifications")` and suppress `EntitlementError`.
   - `WebhookService.create_webhook()`: call `require_capability("notifications")`.
4. Run GREEN targeted pytest.
5. Run `./.venv/bin/ruff check apps/api packages tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py`.
6. Run g-check on the working tree before commit.

### Test Coverage
- `test_free_trial_export_is_denied_by_exports_capability`: active trial cannot export.
- `test_free_trial_document_download_is_denied_by_download_capability`: active trial cannot stream.
- `test_free_trial_document_download_link_is_denied_by_download_capability`: active trial cannot request link.
- `test_free_trial_webhook_creation_is_denied_by_notifications_capability`: active trial cannot configure webhooks.
- `test_notifications_are_suppressed_when_entitlement_inactive`: unchanged suppression behavior.

### Decision Completeness
- Goal: capability-specific guards for exports, document downloads, and notifications.
- Non-goals: schema changes, frontend changes, payment-plan changes, discovery/run behavior changes.
- Success criteria: targeted tests fail before implementation and pass after; ruff passes; g-check has no blocking findings.
- Public interfaces: no endpoint additions/removals; 403 detail for active but excluded capabilities is `<label> capability is not included in current plan`.
- Edge cases / failure modes: inactive tenants keep existing `active subscription required for <label>` message; active free-trial tenants are denied; dispatch suppression remains non-throwing.
- Rollout & monitoring: deploy as app-only change; watch export/download/webhook 403s and notification volume.
- Acceptance checks: targeted pytest, ruff, g-check, PR CI.

### Dependencies
No new dependencies.

### Validation
Use the targeted pytest set that covers all changed API/service boundaries, plus ruff for touched Python surfaces.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `TenantEntitlementService.require_capability()` | Export, document, webhook, notification dispatcher service calls | `configure_services()` creates one service and passes it to consumers | `billing_subscriptions`, `crawl_profile_keywords` |
| Export capability guard | `GET /v1/exports/excel` | `app.state.export_service` in `bootstrap/services.py` | subscription snapshot |
| Document download capability guard | `GET /v1/documents/{id}/download`, `/download-link` | `app.state.document_ingest_service` in `bootstrap/services.py` | subscription snapshot |
| Notification capability guard | `POST /v1/webhooks`; dispatcher calls from project/run/export/document services | `app.state.webhook_service`, `app.state.notification_dispatcher` in `bootstrap/services.py` | subscription snapshot |

### Cross-Language Schema Verification
No migration or schema change is planned.

## Exploration Notes
- Auggie semantic search was attempted first and returned HTTP 429, so this plan is based on direct file inspection plus exact-string searches.
- Inspected: `AGENTS.md`, `apps/api/AGENTS.md`, entitlement/export/document/webhook/admin services and routes, bootstrap wiring, and phase1/phase2/phase4 tests.

## Implementation Summary (2026-05-16 14:59:30 +07)

### Goal
Enforce capability-specific entitlement guards for exports, document downloads, and notifications, with free-trial negative coverage.

### What Changed
- `apps/api/src/egp_api/services/entitlement_service.py`: added `require_capability()` for `exports`, `document_downloads`, and `notifications`; notification dispatch now routes through the same guard while preserving suppression semantics.
- `apps/api/src/egp_api/services/export_service.py`: export generation now requires the `exports` capability.
- `apps/api/src/egp_api/services/document_ingest_service.py`: download URL, proxied download, metadata, streaming, and download-link paths now require `document_downloads`.
- `apps/api/src/egp_api/services/webhook_service.py`: webhook creation now requires the `notifications` capability.
- `apps/api/src/egp_api/routes/webhooks.py`: maps notification entitlement denial to HTTP 403.
- `apps/api/src/egp_api/routes/admin/settings.py`: notification preference updates now require the `notifications` capability.
- `apps/api/src/egp_api/bootstrap/services.py`: wires the entitlement service into `WebhookService`.
- `tests/phase4/test_entitlements.py`: added active free-trial negative tests for export, document download, document download link, and notification dispatch suppression.
- `tests/phase4/test_webhooks_api.py`: added active free-trial webhook creation denial and seeded active paid subscriptions for positive webhook creation tests.
- `tests/phase4/test_admin_api.py`: added active free-trial notification-preference denial and seeded an active paid subscription for the positive preference update test.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py -q`
  - Result: 4 failed, 18 passed.
  - Failure reason: free-trial export/download/download-link/webhook creation returned 200/201 because current guards only required active subscriptions.
- GREEN: `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py -q`
  - Result after implementation and positive fixture repair: 22 passed.
- Expanded GREEN: `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase2/test_export_service.py tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py tests/phase4/test_admin_api.py -q`
  - Result: 100 passed, 14 sqlite datetime adapter warnings.
- Lint GREEN: `./.venv/bin/ruff check apps/api packages tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py tests/phase4/test_admin_api.py`
  - Result: all checks passed.

### Wiring Verification Evidence
- Export: `GET /v1/exports/excel` uses `app.state.export_service`, wired with `entitlement_service` in `configure_services()`.
- Document downloads: `GET /v1/documents/{document_id}/download` and `/download-link` use `app.state.document_ingest_service`, wired with `entitlement_service`.
- Webhooks: `POST /v1/webhooks` uses `app.state.webhook_service`, now wired with `entitlement_service`.
- Admin notification preferences: `PUT /v1/admin/users/{user_id}/notification-preferences` calls `app.state.entitlement_service.require_capability("notifications")`.
- Notification dispatch: `app.state.notification_dispatcher` is `EntitlementAwareNotificationDispatcher`, and dispatch now calls `require_capability("notifications")`.

### Behavior And Risk Notes
- Inactive tenants keep the existing `active subscription required for <label>` behavior.
- Active free-trial tenants now fail closed for export, document download, webhook creation, and notification preference updates.
- Notification dispatch still suppresses denied notifications instead of surfacing exceptions to project/run/document/export workflows.

### Follow-Ups / Known Gaps
- No schema changes or frontend changes were needed.

## Review (2026-05-16 15:00:22 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at base `e849f243`
- Commands Run:
  - `git status --porcelain=v1`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`
  - `nl -ba` targeted inspections for entitlement, export, document, webhook, admin route, and tests
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase2/test_export_service.py tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/ruff check apps/api packages tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py tests/phase4/test_admin_api.py`

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
- Assumption: notification configuration boundaries are webhook creation and admin notification-preference updates; listing/deleting existing notification configuration remains allowed.
- Assumption: inactive subscription errors should preserve the existing `active subscription required for <label>` detail, while active-but-excluded plan errors use the new capability message.

### Recommended Tests / Validation
- Already run targeted API tests for document download, export, entitlement, webhook, and admin notification preference behavior.
- Already run ruff for API, packages, and touched phase4 tests.

### Rollout Notes
- Application-only change; no migration or env flag.
- Watch 403 rates for `/v1/exports/excel`, `/v1/documents/*/download`, `/v1/documents/*/download-link`, `/v1/webhooks`, and `/v1/admin/users/*/notification-preferences` after deploy.

## PR / Merge Status (2026-05-16 15:03:58 +07)

- Created Graphite branch: `feat/capability-entitlement-guards`
- Commit: `cbc49fa9 feat(api): add capability entitlement guards`
- PR: `https://github.com/SubhajL/egp/pull/91`
- Auto-merge: enabled with merge method `MERGE`.
- Normal merge attempt: blocked by base branch policy.
- CI state: failed before runner steps/logs were available; GitHub API reported failed jobs with empty step lists and no runner name for CI jobs.
- Rerun: failed the same way.
- Local validation remains green:
  - `./.venv/bin/python -m compileall apps/api/src packages`
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase2/test_export_service.py tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/ruff check apps/api packages tests/phase4/test_entitlements.py tests/phase4/test_webhooks_api.py tests/phase4/test_admin_api.py`
