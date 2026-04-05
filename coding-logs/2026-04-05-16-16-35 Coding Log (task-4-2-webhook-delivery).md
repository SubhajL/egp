# Task 4.2 Planning: Webhook Notification Delivery

## Plan Draft A

### Overview
Add tenant-scoped webhook subscriptions and outbound delivery on top of the existing notification pipeline. Reuse the current `NotificationDispatcher` event entry point, persist webhook configuration and delivery state in the notification repository, expose PRD-aligned `/v1/webhooks` management endpoints, and add a minimal admin UI tab for create/list/delete.

### Files to Change
- `packages/db/src/migrations/008_webhook_notifications.sql`: additive schema for webhook subscriptions and delivery audit rows.
- `packages/db/src/egp_db/repositories/notification_repo.py`: webhook subscription persistence, filtering, soft delete, and delivery audit updates.
- `packages/notification-core/src/egp_notifications/webhook_delivery.py`: new outbound webhook delivery component with signing and retry handling.
- `packages/notification-core/src/egp_notifications/dispatcher.py`: invoke webhook delivery after in-app/email notification creation.
- `packages/notification-core/src/egp_notifications/__init__.py`: export new webhook delivery types if needed by callers/tests.
- `apps/api/src/egp_api/services/webhook_service.py`: create/list/delete webhook subscriptions for tenant admins.
- `apps/api/src/egp_api/routes/webhooks.py`: `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{id}`.
- `apps/api/src/egp_api/main.py`: wire webhook service and router into the app state.
- `apps/api/src/egp_api/services/rules_service.py`: update supported notification channels to include `webhook`.
- `apps/web/src/lib/api.ts`: webhook DTOs and fetch/create/delete helpers.
- `apps/web/src/lib/hooks.ts`: `useWebhooks` query hook.
- `apps/web/src/app/(app)/admin/page.tsx`: new webhook tab and create/list/delete UI.
- `tests/phase2/test_notification_dispatch.py`: webhook dispatch contract, retry, and tenant/type filtering tests.
- `tests/phase4/test_webhooks_api.py`: API auth, tenant isolation, CRUD, and UI-facing shape tests.

### Implementation Steps
- TDD sequence:
  1. Add repository and dispatch tests for webhook subscription filtering, signature headers, and retry semantics.
  2. Run those tests and confirm they fail because webhook storage/delivery does not exist.
  3. Implement the schema and repository methods.
  4. Implement delivery service and wire it into `NotificationDispatcher`.
  5. Add API route tests for `/v1/webhooks`.
  6. Run them and confirm they fail because routes/service are missing.
  7. Implement API service/routes and app wiring.
  8. Add frontend types/hooks and admin page integration.
  9. Run relevant fast gates and refactor only if needed.

- Function names and behavior:
  - `SqlNotificationRepository.create_webhook_subscription(...)`: insert tenant-scoped webhook configuration with subscribed notification types and signing secret.
  - `SqlNotificationRepository.list_webhook_subscriptions(...)`: return active subscriptions plus last delivery summary for admin/API listing.
  - `SqlNotificationRepository.deactivate_webhook_subscription(...)`: soft-delete a webhook so audit rows remain intact.
  - `SqlNotificationRepository.list_active_webhook_subscriptions(...)`: runtime resolver for `NotificationDispatcher`, filtered by tenant, active status, and notification type.
  - `SqlNotificationRepository.create_or_get_webhook_delivery(...)`: persist one auditable delivery row per `(subscription, notification/event)` pair for retry-safe dispatch.
  - `SqlNotificationRepository.record_webhook_delivery_attempt(...)`: update attempt count, status, response metadata, and delivered timestamp.
  - `WebhookDeliveryService.deliver(...)`: build the webhook payload, sign it, POST it, and retry retryable failures using a bounded attempt loop.
  - `_build_webhook_payload(...)`: produce a machine-consumable event envelope using existing `NotificationType` and runtime event data.
  - `_build_webhook_signature(...)`: produce deterministic HMAC-SHA256 signature over the JSON payload.
  - `WebhookService.list_webhooks(...)`: admin-facing read of tenant webhook configuration.
  - `WebhookService.create_webhook(...)`: validate types and URL, then create a new subscription.
  - `WebhookService.delete_webhook(...)`: tenant-scoped soft delete.
  - `list_webhooks`, `create_webhook`, `delete_webhook`: FastAPI handlers matching PRD endpoints and admin auth rules.
  - `fetchWebhooks`, `createWebhook`, `deleteWebhook`: frontend API helpers.
  - `useWebhooks()`: React Query hook for the admin webhooks tab.

- Expected behavior and edge cases:
  - Webhooks only receive events for their own tenant and subscribed notification types.
  - Delivery errors must not fail primary notification producers; dispatch fails open for webhook transport.
  - Retry only on retryable failures: network exception, timeout, HTTP `429`, and HTTP `5xx`.
  - Do not retry `2xx` or non-retryable `4xx`.
  - Use a stable event id per notification so repeated attempts are dedupable by receivers.
  - Deleted/inactive subscriptions must stop receiving future events immediately.

### Test Coverage
- `tests/phase2/test_notification_dispatch.py`
  - `test_dispatch_delivers_webhook_for_matching_tenant_and_type`: matching subscription receives event payload.
  - `test_dispatch_skips_webhook_for_other_tenant_or_unsubscribed_type`: tenant/type filtering is enforced.
  - `test_dispatch_retries_retryable_webhook_failures_with_same_event_id`: retries preserve stable idempotency key.
  - `test_dispatch_does_not_retry_non_retryable_4xx_webhook_failure`: permanent client errors stop after one attempt.
  - `test_dispatch_webhook_failure_does_not_block_in_app_or_email`: fail-open delivery behavior.

- `tests/phase4/test_webhooks_api.py`
  - `test_create_and_list_webhooks_returns_tenant_scoped_configuration`: CRUD read path is tenant-safe.
  - `test_delete_webhook_soft_disables_subscription`: delete stops future deliveries.
  - `test_webhook_routes_require_admin_role`: admin auth gating is enforced.
  - `test_webhook_routes_reject_invalid_notification_types`: request validation guards contract.

- `apps/web` manual/typecheck coverage
  - admin page webhook tab renders existing subscriptions.
  - create/delete interactions invalidate and refresh the query.

### Decision Completeness
- Goal:
  - Deliver machine-consumable webhook notifications with tenant-managed subscriptions, auditable payloads, and bounded retry-safe semantics.
- Non-goals:
  - Background job queue for delayed retries.
  - Webhook secret rotation endpoint.
  - Delivery-history page beyond latest summary on the subscription list.
- Success criteria:
  - A tenant admin can create/list/delete webhook subscriptions.
  - Matching platform notifications POST signed JSON payloads to subscribed endpoints.
  - Retryable failures retry a bounded number of times without duplicating event ids.
  - Delivery attempts are persisted with payload and final status.
  - Existing notification behavior for in-app/email remains intact.
- Public interfaces:
  - New API endpoints: `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{id}`.
  - New DB objects: `webhook_subscriptions`, `webhook_deliveries`.
  - Frontend admin page gains webhook configuration tab and API helpers.
  - No new env vars in Draft A.
- Edge cases / failure modes:
  - Invalid URL or invalid notification types: fail closed with `422`/`400`.
  - Tenant mismatch or cross-tenant delete attempt: fail closed with `403`/`404`.
  - Delivery timeout / `429` / `5xx`: retry, then persist `failed`.
  - Delivery `4xx`: persist `failed` without retry.
  - Duplicate retries: same `event_id` header for receiver dedupe.
- Rollout & monitoring:
  - Additive migration only.
  - Backout: disable by deleting subscriptions or reverting runtime wiring; tables can remain safely unused.
  - Monitor failed deliveries by inspecting `webhook_deliveries.delivery_status` and `last_response_status_code`.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py -q`
  - `./.venv/bin/python -m ruff check apps/api/src packages/db/src packages/notification-core/src tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py`
  - `./.venv/bin/python -m compileall apps/api/src packages/db/src packages/notification-core/src`
  - `cd apps/web && npm run typecheck`

### Dependencies
- Existing notification event producers in API and worker.
- `httpx` as synchronous webhook transport.
- Existing admin auth/tenant resolution flow.

### Validation
- Use fake webhook transport in unit tests to validate payload shape, headers, and retry behavior.
- Use FastAPI API tests to confirm admin-only route behavior and tenant scoping.
- Use frontend typecheck plus manual page smoke for the new admin tab.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `webhook_delivery.py` | `NotificationDispatcher.dispatch()` | `packages/notification-core/src/egp_notifications/dispatcher.py` import + call | `webhook_subscriptions`, `webhook_deliveries` |
| `WebhookService` | `/v1/webhooks` handlers | `apps/api/src/egp_api/main.py` app state | `webhook_subscriptions` |
| `routes/webhooks.py` | FastAPI HTTP requests | `apps/api/src/egp_api/main.py:include_router()` | N/A |
| `008_webhook_notifications.sql` | migration runner / deployment | `packages/db/src/migrations` | `webhook_subscriptions`, `webhook_deliveries` |
| Admin webhooks tab | `/admin` page render + mutations | `apps/web/src/app/(app)/admin/page.tsx`, `apps/web/src/lib/hooks.ts`, `apps/web/src/lib/api.ts` | N/A |

### Cross-Language Schema Verification
- Python currently uses `notifications`, `notification_preferences`, `users`, `tenants`, `tenant_settings`, `billing_records`, and `billing_subscriptions`.
- TypeScript consumes API contracts only and does not embed DB names.
- No existing Python or TS references use `webhook_subscriptions` or `webhook_deliveries`, so the new names are additive and conflict-free.

### Decision-Complete Checklist
- No open decisions remain for the implementer.
- Every new/changed public interface is listed.
- Every behavior change has tests.
- Validation commands are concrete.
- Wiring verification covers every new component.
- Rollout/backout is specified.

## Plan Draft B

### Overview
Keep the change surface smaller by placing webhook CRUD under the existing admin API/service and keeping webhook delivery persistence minimal. This draft still adds signed payload delivery and retries, but reduces new services/routes by treating webhooks as an admin-owned subresource instead of a top-level API.

### Files to Change
- `packages/db/src/migrations/008_webhook_notifications.sql`: webhook tables.
- `packages/db/src/egp_db/repositories/notification_repo.py`: subscription + delivery state.
- `packages/notification-core/src/egp_notifications/webhook_delivery.py`: delivery logic.
- `packages/notification-core/src/egp_notifications/dispatcher.py`: webhook invocation.
- `apps/api/src/egp_api/services/admin_service.py`: add webhook CRUD methods.
- `apps/api/src/egp_api/routes/admin.py`: add `/v1/admin/webhooks` endpoints.
- `apps/api/src/egp_api/main.py`: no new app state service beyond admin service wiring.
- `apps/api/src/egp_api/services/rules_service.py`: report `webhook` as a supported channel.
- `apps/web/src/lib/api.ts`: webhook DTOs and admin-webhook helpers.
- `apps/web/src/lib/hooks.ts`: webhook query hook.
- `apps/web/src/app/(app)/admin/page.tsx`: admin tab additions.
- `tests/phase2/test_notification_dispatch.py`: delivery behavior tests.
- `tests/phase4/test_admin_api.py`: webhook CRUD tests folded into existing admin coverage.

### Implementation Steps
- TDD sequence:
  1. Extend `tests/phase2/test_notification_dispatch.py` with webhook delivery tests.
  2. Extend `tests/phase4/test_admin_api.py` with webhook CRUD tests.
  3. Confirm both fail because the repo and admin API do not support webhook storage/delivery.
  4. Add webhook schema and repo methods.
  5. Implement `WebhookDeliveryService` and wire it into the dispatcher.
  6. Extend admin service/routes and frontend admin page.
  7. Run targeted gates and refactor minimally.

- Function names and behavior:
  - `AdminService.list_webhooks`, `create_webhook`, `delete_webhook`: tenant-scoped configuration operations inside the existing admin service.
  - `create_admin_webhook`, `list_admin_webhooks`, `delete_admin_webhook`: admin route handlers.
  - Repository and delivery functions match Draft A.

- Expected behavior and edge cases:
  - Same delivery semantics as Draft A.
  - API stays under the admin namespace rather than PRD top-level `/v1/webhooks`.
  - Admin snapshot can optionally remain unchanged; webhook config uses a separate list query.

### Test Coverage
- `tests/phase2/test_notification_dispatch.py`
  - Matching endpoint delivery.
  - Retry behavior on `5xx`/timeout.
  - No retry on `4xx`.
  - Tenant/type filtering.

- `tests/phase4/test_admin_api.py`
  - Admin webhook create/list/delete.
  - Tenant scoping.
  - Admin role enforcement.

### Decision Completeness
- Goal:
  - Same as Draft A.
- Non-goals:
  - Same as Draft A plus no standalone `/v1/webhooks` route.
- Success criteria:
  - Same delivery and audit criteria as Draft A, but through admin endpoints.
- Public interfaces:
  - API endpoints would be `/v1/admin/webhooks` instead of PRD top-level endpoints.
  - Same new DB tables.
  - Same admin UI tab.
- Edge cases / failure modes:
  - Same as Draft A.
- Rollout & monitoring:
  - Same as Draft A.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_admin_api.py -q`
  - `./.venv/bin/python -m ruff check apps/api/src packages/db/src packages/notification-core/src tests/phase2/test_notification_dispatch.py tests/phase4/test_admin_api.py`
  - `cd apps/web && npm run typecheck`

### Dependencies
- Same as Draft A.

### Validation
- Same as Draft A, but webhook CRUD is validated through admin API tests instead of a dedicated test file.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `webhook_delivery.py` | `NotificationDispatcher.dispatch()` | `dispatcher.py` import + call | `webhook_subscriptions`, `webhook_deliveries` |
| Admin webhook CRUD | `/v1/admin/webhooks` handlers | existing admin router in `apps/api/src/egp_api/main.py` | `webhook_subscriptions` |
| `008_webhook_notifications.sql` | migration runner | `packages/db/src/migrations` | `webhook_subscriptions`, `webhook_deliveries` |
| Admin webhooks tab | `/admin` page | `admin/page.tsx`, `hooks.ts`, `api.ts` | N/A |

### Cross-Language Schema Verification
- Same additive schema finding as Draft A.

### Decision-Complete Checklist
- No open decisions remain for the implementer.
- Every new/changed public interface is listed.
- Every behavior change has tests.
- Validation commands are concrete.
- Wiring verification covers every new component.
- Rollout/backout is specified.

## Comparative Analysis & Synthesis

### Strengths
- Draft A matches the PRD API contract exactly and keeps webhook management conceptually separate from broader admin snapshot logic.
- Draft B touches fewer API files and keeps the change localized to existing admin infrastructure.

### Gaps
- Draft A adds one extra service and route file, which is slightly more work.
- Draft B deviates from the PRD endpoint shape and makes the admin route/service continue growing into a catch-all surface.

### Trade-offs
- Draft A favors correct public API boundaries and future extensibility.
- Draft B favors slightly lower implementation cost now, but at the expense of route cohesion and PRD alignment.

### Compliance Check
- Both drafts keep `main.py` thin, use tenant-scoped repositories, and follow the existing service/route split.
- Draft A better matches the documented API endpoints and keeps webhook delivery concerns out of admin snapshot serialization.

## Unified Execution Plan

### Overview
Implement webhook delivery as a first-class notification channel that reuses the current `NotificationDispatcher` event entry point. The final design keeps CRUD at PRD-aligned `/v1/webhooks` routes, stores configuration and auditable delivery state in the notification repository, adds a dedicated webhook delivery component with HMAC signing and bounded retries, and surfaces create/list/delete controls in a new admin-page webhook tab.

### Files to Change
- `packages/db/src/migrations/008_webhook_notifications.sql`: add `webhook_subscriptions` and `webhook_deliveries` with tenant scoping, soft-delete support, and useful indexes.
- `packages/db/src/egp_db/repositories/notification_repo.py`: add webhook subscription records, list/create/deactivate operations, active subscription resolution, and delivery audit updates.
- `packages/notification-core/src/egp_notifications/webhook_delivery.py`: new delivery component using `httpx`, HMAC signature headers, stable event ids, bounded retries, and fail-open behavior.
- `packages/notification-core/src/egp_notifications/dispatcher.py`: call webhook delivery after notification creation.
- `packages/notification-core/src/egp_notifications/__init__.py`: export new delivery types if the package currently re-exports core notification symbols.
- `apps/api/src/egp_api/services/webhook_service.py`: tenant-scoped CRUD with API validation rules.
- `apps/api/src/egp_api/routes/webhooks.py`: top-level webhook management endpoints from the PRD.
- `apps/api/src/egp_api/main.py`: instantiate `WebhookDeliveryService`, wire it into `NotificationDispatcher`, register `WebhookService`, and include the new router.
- `apps/api/src/egp_api/services/rules_service.py`: advertise `webhook` in `supported_channels`.
- `apps/web/src/lib/api.ts`: webhook response/input types and fetch/create/delete helpers.
- `apps/web/src/lib/hooks.ts`: `useWebhooks` query hook.
- `apps/web/src/app/(app)/admin/page.tsx`: add a `webhooks` tab, list existing subscriptions, create form, and delete action.
- `tests/phase2/test_notification_dispatch.py`: extend with webhook dispatch contract tests.
- `tests/phase4/test_webhooks_api.py`: dedicated API tests for create/list/delete, auth, validation, and tenant isolation.

### Implementation Steps
- TDD sequence:
  1. Add failing webhook dispatch tests in `tests/phase2/test_notification_dispatch.py`.
  2. Run `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py -q` and confirm failure because webhook delivery/storage symbols do not exist.
  3. Implement the smallest repo + delivery code to satisfy dispatch tests.
  4. Add failing API tests in `tests/phase4/test_webhooks_api.py`.
  5. Run `./.venv/bin/python -m pytest tests/phase4/test_webhooks_api.py -q` and confirm failure because `/v1/webhooks` routes are missing.
  6. Implement FastAPI service/routes and app wiring.
  7. Add frontend API/hook/page changes for the admin webhooks tab.
  8. Run fast gates, then broader relevant regression checks.

- Functions and responsibilities:
  - `WebhookSubscriptionRecord`: immutable repo DTO for list/create/read responses.
  - `WebhookDeliveryRecord`: immutable repo DTO for persisted delivery state.
  - `SqlNotificationRepository.create_webhook_subscription(...)`: create tenant-scoped webhook configuration and persist subscribed notification types.
  - `SqlNotificationRepository.list_webhook_subscriptions(...)`: list active subscriptions with last delivery summary for the UI/API.
  - `SqlNotificationRepository.list_active_webhook_subscriptions(...)`: runtime resolver for current notification type.
  - `SqlNotificationRepository.deactivate_webhook_subscription(...)`: soft delete to preserve audit history.
  - `SqlNotificationRepository.create_or_get_webhook_delivery(...)`: single auditable delivery row per `(subscription_id, event_id)`.
  - `SqlNotificationRepository.record_webhook_delivery_attempt(...)`: update attempt count, timestamps, response code/body, and final status.
  - `WebhookDeliveryService.deliver(...)`: POST JSON payloads to all matching subscriptions with stable event ids and bounded retries.
  - `_build_webhook_payload(...)`: event envelope containing `event_id`, `event_type`, `tenant_id`, `project_id`, `created_at`, `subject`, `body`, and `template_vars`.
  - `_build_signature(...)`: HMAC-SHA256 signature for `X-EGP-Signature-256`.
  - `_is_retryable_result(...)`: retry on network exception, timeout, `429`, and `5xx`; stop on `2xx` or non-retryable `4xx`.
  - `WebhookService.list_webhooks(...)`, `create_webhook(...)`, `delete_webhook(...)`: API-facing CRUD logic with tenant checks and type validation.
  - `list_webhooks`, `create_webhook`, `delete_webhook`: FastAPI route handlers with `require_admin_role` and `resolve_request_tenant_id`.
  - `fetchWebhooks`, `createWebhook`, `deleteWebhook`: frontend data access helpers.
  - `useWebhooks()`: React Query wrapper for UI data refresh.

- Expected behavior and edge cases:
  - Dispatching a supported notification type still creates in-app notifications first.
  - Webhook delivery is best-effort and fail-open; core run/document/export/billing flows must not error because an external endpoint is unhealthy.
  - Webhook delivery uses a stable event id per created notification so retries are dedupable by receivers.
  - Soft-deleted subscriptions are excluded from future dispatch but their delivery history remains queryable.
  - Invalid webhook URLs or unsupported notification types are rejected at create time.
  - Cross-tenant access is rejected everywhere.

### Test Coverage
- `tests/phase2/test_notification_dispatch.py`
  - `test_dispatch_delivers_webhook_for_matching_tenant_and_type`: sends payload only to matching active subscription.
  - `test_dispatch_skips_webhook_for_other_tenant_or_unsubscribed_type`: tenant/type scope is enforced.
  - `test_dispatch_retries_retryable_webhook_failures_with_same_event_id`: retry-safe idempotency behavior.
  - `test_dispatch_does_not_retry_non_retryable_4xx_webhook_failure`: permanent failures stop immediately.
  - `test_dispatch_webhook_failure_does_not_block_existing_notification_channels`: fail-open behavior.

- `tests/phase4/test_webhooks_api.py`
  - `test_create_and_list_webhooks_returns_tenant_scoped_configuration`: CRUD listing uses current tenant only.
  - `test_delete_webhook_soft_disables_subscription`: delete removes endpoint from active list and future dispatch.
  - `test_webhook_routes_require_admin_role`: owner/admin gate is enforced.
  - `test_webhook_routes_reject_invalid_notification_types_and_bad_urls`: validation behaves predictably.
  - `test_webhook_routes_reject_cross_tenant_delete_attempt`: no tenant leakage on destructive actions.

- Frontend validation
  - `admin/page.tsx` compiles with webhook tab state and mutations.
  - Manual smoke: create webhook, list refreshes, delete webhook, list refreshes again.

### Decision Completeness
- Goal:
  - Add webhook delivery as a production-ready notification channel with tenant-managed subscriptions, stable event ids, auditable payloads, and bounded retry behavior.
- Non-goals:
  - Delayed/background retry queue.
  - Secret rotation/edit endpoints.
  - Full webhook delivery history UI.
  - Non-admin self-service management.
- Success criteria:
  - Tenant admins can create, list, and delete webhook subscriptions.
  - Existing notification producers trigger webhook delivery for matching types.
  - Delivery attempts are persisted with payload, attempt count, response metadata, and final status.
  - Retryable failures retry bounded times with a stable event id.
  - Existing email/in-app notification tests still pass.
- Public interfaces:
  - API: `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{id}`.
  - DB migration: new `webhook_subscriptions` and `webhook_deliveries`.
  - Frontend: admin webhook tab and API helpers.
  - Headers sent outbound: `X-EGP-Event-ID`, `X-EGP-Event-Type`, `X-EGP-Signature-256`.
- Edge cases / failure modes:
  - Invalid create payload: fail closed with request validation error.
  - Unauthorized/non-admin caller: fail closed with `403`.
  - Cross-tenant list/delete: fail closed with `403`/`404`.
  - Transport timeout / DNS / `429` / `5xx`: retry and then persist `failed`.
  - `4xx` from receiver: no retry; persist `failed`.
  - No configured webhook subscriptions: dispatch exits without side effects beyond existing channels.
- Rollout & monitoring:
  - Migration is additive and safe to deploy before app code.
  - Backout path: stop wiring delivery, or delete/disable subscriptions. Tables can remain.
  - Monitor: failed delivery count, latest delivery status code/body, and subscription activity.
- Acceptance checks:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase1/test_projects_and_runs_api.py tests/phase2/test_export_service.py -q`
  - `./.venv/bin/python -m ruff check apps/api/src packages/db/src packages/notification-core/src tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py`
  - `./.venv/bin/python -m compileall apps/api/src packages/db/src packages/notification-core/src`
  - `cd apps/web && npm run typecheck`

### Dependencies
- Existing `NotificationDispatcher` / `NotificationService`.
- Existing tenant auth and admin role checks.
- `httpx` for transport.
- Shared `NotificationType` enum.

### Validation
- Unit-test delivery behavior with a fake transport that records attempts and simulates timeout / `4xx` / `5xx`.
- API-test tenant and admin enforcement with FastAPI `TestClient`.
- Frontend-typecheck the admin webhook tab and mutation helpers.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|----------------------|--------------|
| `packages/notification-core/src/egp_notifications/webhook_delivery.py` | `NotificationDispatcher.dispatch()` after in-app/email creation | `packages/notification-core/src/egp_notifications/dispatcher.py` | `webhook_subscriptions`, `webhook_deliveries` |
| `apps/api/src/egp_api/services/webhook_service.py` | `/v1/webhooks` route handlers | `apps/api/src/egp_api/main.py` app state assignment | `webhook_subscriptions` |
| `apps/api/src/egp_api/routes/webhooks.py` | FastAPI HTTP requests at `/v1/webhooks` | `apps/api/src/egp_api/main.py:app.include_router(webhooks_router)` | N/A |
| `packages/db/src/migrations/008_webhook_notifications.sql` | migration runner / deploy | `packages/db/src/migrations` | `webhook_subscriptions`, `webhook_deliveries` |
| `apps/web/src/lib/api.ts` helpers | admin page data fetch/mutation | imported by `apps/web/src/lib/hooks.ts` and `apps/web/src/app/(app)/admin/page.tsx` | N/A |
| `/admin` webhooks tab | Next admin route segment | `apps/web/src/app/(app)/admin/page.tsx` | N/A |

### Cross-Language Schema Verification
- Existing repo references confirm live names: `tenants`, `users`, `notifications`, `notification_preferences`, `tenant_settings`, `billing_records`, and `billing_subscriptions`.
- TypeScript only consumes API DTOs and does not embed SQL names.
- New tables will be `webhook_subscriptions` and `webhook_deliveries`; there are no current Python or TS references to those names, so the migration is additive and conflict-free.

### Decision-Complete Checklist
- No open decisions remain for the implementer.
- Every new/changed public interface is listed.
- Every behavior change has at least one test.
- Validation commands are specific and scoped.
- Wiring verification covers each new component and migration.
- Rollout/backout is specified.

## Implementation (2026-04-05 16:31:50 +0700) - task-4-2-webhook-delivery

### Goal
- Add tenant-configurable webhook subscriptions and auditable outbound delivery on top of the existing notification pipeline.

### What Changed
- `packages/db/src/migrations/008_webhook_notifications.sql`
  - Added additive Postgres schema for `webhook_subscriptions` and `webhook_deliveries` with tenant scoping, soft-delete support, and delivery status tracking.
- `packages/db/src/egp_db/repositories/notification_repo.py`
  - Added webhook subscription CRUD, active subscription resolution by notification type, persisted delivery rows, delivery-attempt updates, and delivery-summary listing.
- `packages/notification-core/src/egp_notifications/webhook_delivery.py`
  - Added synchronous webhook delivery with signed JSON payloads, bounded retry handling, and repeat-delivery suppression for already-delivered event ids.
- `packages/notification-core/src/egp_notifications/dispatcher.py`
  - Extended `NotificationDispatcher` to invoke webhook delivery after in-app/email creation and include `webhook` in the returned channel list only when at least one delivery succeeds.
- `packages/notification-core/src/egp_notifications/__init__.py`
  - Re-exported webhook delivery types.
- `apps/api/src/egp_api/services/webhook_service.py`
  - Added tenant-scoped webhook CRUD service using existing admin tenant checks.
- `apps/api/src/egp_api/routes/webhooks.py`
  - Added PRD-aligned `GET /v1/webhooks`, `POST /v1/webhooks`, and `DELETE /v1/webhooks/{id}` routes with admin-role gating.
- `apps/api/src/egp_api/main.py`
  - Wired `WebhookDeliveryService` into the runtime dispatcher, registered `WebhookService` in app state, and included the new router.
- `apps/api/src/egp_api/services/rules_service.py`
  - Updated notification channel metadata to advertise `webhook`.
- `apps/web/src/lib/api.ts`
  - Added webhook DTOs and fetch/create/delete helpers.
- `apps/web/src/lib/hooks.ts`
  - Added `useWebhooks()` query hook.
- `apps/web/src/app/(app)/admin/page.tsx`
  - Added a new admin webhook tab with create/list/delete actions and latest-delivery summary display.
- `tests/phase2/test_notification_dispatch.py`
  - Added webhook dispatch, retry, fail-open, and already-delivered event-id coverage.
- `tests/phase2/test_rules_api.py`
  - Updated expected notification channels to include `webhook`.
- `tests/phase4/test_webhooks_api.py`
  - Added tenant-scoped webhook CRUD and auth regression coverage.
- `.taskmaster/tasks/tasks.json`
  - Task Master status moved Task 4.2 into active execution during implementation.

### TDD Evidence
- RED command:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py -q`
  - Failed with `ModuleNotFoundError: No module named 'egp_notifications.webhook_delivery'` during test collection.
- GREEN command:
  - `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py tests/phase2/test_rules_api.py -q`
  - Passed with `15 passed`.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py -q`
  - RED: missing `egp_notifications.webhook_delivery` module.
- `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py tests/phase2/test_rules_api.py -q`
  - GREEN: `15 passed`.
- `./.venv/bin/python -m pytest tests/phase1/test_projects_and_runs_api.py tests/phase1/test_documents_api.py tests/phase1/test_worker_workflows.py tests/phase2/test_export_service.py tests/phase2/test_notification_dispatch.py tests/phase2/test_notification_service.py tests/phase2/test_rules_api.py tests/phase4/test_webhooks_api.py -q`
  - Passed: `51 passed`.
- `./.venv/bin/python -m ruff check apps/api/src packages/db/src packages/notification-core/src tests/phase1/test_projects_and_runs_api.py tests/phase1/test_documents_api.py tests/phase1/test_worker_workflows.py tests/phase2/test_export_service.py tests/phase2/test_notification_dispatch.py tests/phase2/test_notification_service.py tests/phase2/test_rules_api.py tests/phase4/test_webhooks_api.py`
  - Passed.
- `./.venv/bin/python -m compileall apps/api/src packages/db/src packages/notification-core/src`
  - Passed.
- `cd apps/web && npm run typecheck`
  - Passed.
- `cd apps/web && npm run build`
  - Passed.

### Wiring Verification Evidence
- Runtime notification entry point remains `NotificationDispatcher.dispatch()` in `packages/notification-core/src/egp_notifications/dispatcher.py`; webhook delivery is called from there.
- `WebhookDeliveryService` is instantiated in `apps/api/src/egp_api/main.py` and injected into the dispatcher alongside the existing email/in-app service.
- `WebhookService` is registered on `app.state.webhook_service` in `apps/api/src/egp_api/main.py`.
- `apps/api/src/egp_api/main.py` includes `webhooks_router`, which exposes the new `/v1/webhooks` HTTP endpoints.
- Frontend admin wiring is `apps/web/src/lib/api.ts` -> `apps/web/src/lib/hooks.ts` -> `apps/web/src/app/(app)/admin/page.tsx`.

### Behavior Changes / Risk Notes
- Webhook delivery is fail-open: external endpoint failures do not block in-app or email notifications, runs, document review flows, exports, or worker closures.
- Retry behavior is bounded and synchronous: timeout/transport errors, `429`, and `5xx` are retried up to the configured attempt limit; `4xx` errors are treated as terminal.
- Event ids are stable per notification and reused across retries via `X-EGP-Event-ID`; already-delivered event ids are skipped on repeat delivery attempts.
- Soft delete disables future deliveries without erasing historical delivery rows.

### Follow-ups / Known Gaps
- There is no delayed/background retry queue yet; retries are immediate and bounded inside the current dispatch path.
- The admin UI shows latest delivery summary only, not a full per-attempt history view.

## Review (2026-04-05 16:32:39 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: feat/task-4-2-webhook-delivery
- Scope: working-tree
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- apps/api/src/egp_api/main.py apps/api/src/egp_api/routes/webhooks.py apps/api/src/egp_api/services/webhook_service.py packages/db/src/egp_db/repositories/notification_repo.py packages/notification-core/src/egp_notifications/webhook_delivery.py packages/notification-core/src/egp_notifications/dispatcher.py tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py`; targeted `sed -n` reads for the new route/service/delivery files.

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
- Assumed immediate bounded retries are sufficient for Task 4.2 and that delayed/background retry orchestration belongs to a later operational hardening pass.

### Recommended Tests / Validation
- `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py tests/phase2/test_rules_api.py -q`
- `./.venv/bin/python -m pytest tests/phase1/test_projects_and_runs_api.py tests/phase1/test_documents_api.py tests/phase1/test_worker_workflows.py tests/phase2/test_export_service.py tests/phase2/test_notification_dispatch.py tests/phase2/test_notification_service.py tests/phase2/test_rules_api.py tests/phase4/test_webhooks_api.py -q`
- `./.venv/bin/python -m ruff check apps/api/src packages/db/src packages/notification-core/src tests/phase1/test_projects_and_runs_api.py tests/phase1/test_documents_api.py tests/phase1/test_worker_workflows.py tests/phase2/test_export_service.py tests/phase2/test_notification_dispatch.py tests/phase2/test_notification_service.py tests/phase2/test_rules_api.py tests/phase4/test_webhooks_api.py`
- `./.venv/bin/python -m compileall apps/api/src packages/db/src packages/notification-core/src`
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run build`

### Rollout Notes
- Apply additive migration `008_webhook_notifications.sql` before deploying app code.
- Webhook delivery is fail-open, so production incidents should primarily show up as failed delivery rows rather than user-facing API failures.
- Backout is safe by removing webhook subscriptions or reverting runtime wiring; the new tables can remain unused without affecting existing notification channels.

## Review (2026-04-05 17:00:32 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: feat/task-4-2-webhook-delivery
- Scope: working-tree
- Commands Run: `git status --short`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `git diff -- <path>` and `nl -ba` reads for webhook migration/repository/runtime/API/UI/tests; `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py tests/phase2/test_rules_api.py -q`; `./.venv/bin/python -m ruff check apps/api/src packages/db/src packages/notification-core/src tests/phase2/test_notification_dispatch.py tests/phase2/test_rules_api.py tests/phase4/test_webhooks_api.py`; `cd apps/web && npm run typecheck`

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
- Assumed the existing immediate retry loop is acceptable for Task 4.2 and that delayed/backoff retry orchestration is intentionally out of scope for this change.

### Recommended Tests / Validation
- `./.venv/bin/python -m pytest tests/phase2/test_notification_dispatch.py tests/phase4/test_webhooks_api.py tests/phase2/test_rules_api.py -q`
- `./.venv/bin/python -m ruff check apps/api/src packages/db/src packages/notification-core/src tests/phase2/test_notification_dispatch.py tests/phase2/test_rules_api.py tests/phase4/test_webhooks_api.py`
- `cd apps/web && npm run typecheck`

### Rollout Notes
- Deploy `packages/db/src/migrations/008_webhook_notifications.sql` before code that emits webhook deliveries.
- Delivery remains fail-open, so webhook endpoint incidents should surface in `webhook_deliveries` audit rows without blocking in-app/email notification creation.
