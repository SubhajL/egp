# Task ID: 4

**Title:** Phase 4: Commercial Hardening

**Status:** in-progress

**Dependencies:** 3

**Priority:** medium

**Description:** Harden the platform for production readiness as described in PRD phase 4.

**Details:**

Prepare the platform for production operation by adding multi-tenant quotas, webhook notifications, a full audit log, self-service admin, SOC and operational runbooks, disaster recovery and backup validation, cost observability, and support tooling. This phase should tighten operational controls without violating the core architecture and tenant-isolation rules established earlier.

**Test Strategy:**

Validate production-readiness outcomes with quota enforcement tests, webhook contract tests, audit-log coverage, tenant-isolation checks, backup/restore drills, and support-runbook verification. PRD acceptance test 10 remains a hard requirement throughout this phase.

## Subtasks

### 4.1. Implement multi-tenant quotas and entitlement enforcement

**Status:** done  
**Dependencies:** None  

Enforce per-tenant limits and plan-based product boundaries.

**Details:**

Add tenant-level quota tracking and enforcement in the API and supporting data model. Tie quota behavior to subscription state from phase 3 and ensure limits are applied consistently across runs, exports, documents, and notifications. This includes enforcing launch-package entitlements: `One-Time Search Pack` allows exactly `1 keyword` for `3 days`, while `Monthly Membership` allows up to `5 active keywords` during the prepaid billing period.

Implementation note:

Task 4.1 is implemented through a new entitlement layer in `apps/api/src/egp_api/services/entitlement_service.py`, backed by tenant-scoped subscription truth from `packages/db/src/egp_db/repositories/billing_repo.py` and active keyword enumeration from `packages/db/src/egp_db/repositories/profile_repo.py`. The API now fail-closes on unpaid or expired access for `POST /v1/runs`, `POST /v1/runs/{run_id}/tasks` discover keywords, `GET /v1/exports/excel`, and `GET /v1/documents/{document_id}/download`, while notification delivery for `RUN_FAILED`, `EXPORT_READY`, and `TOR_CHANGED` is suppressed when the tenant lacks an active subscription via the entitlement-aware dispatcher wired in `apps/api/src/egp_api/main.py`. `GET /v1/rules` and `apps/web/src/app/(app)/rules/page.tsx` now expose the live entitlement snapshot: active plan, subscription status, keyword limit, active keyword count, remaining slots, and whether the tenant is over limit. Regression coverage was added in `tests/phase4/test_entitlements.py` and extended in `tests/phase2/test_rules_api.py`, with legacy paid-capability fixtures updated in phase 1/2 API tests.

### 4.2. Add webhook notification delivery

**Status:** done  
**Dependencies:** None  

Deliver machine-consumable notifications alongside email and in-product surfaces.

**Details:**

Implement tenant-configurable webhook subscriptions and outbound delivery with retry-safe semantics. Keep payloads auditable and compatible with the event model established earlier in the platform.

<info added on 2026-04-05T16:32:39.578+07:00>
Implementation note: Webhook notification delivery is implemented across packages/db/src/migrations/008_webhook_notifications.sql (tenant-scoped webhook_subscriptions + webhook_deliveries tables), packages/db/src/egp_db/repositories/notification_repo.py (subscription CRUD, active subscription resolution, delivery audit persistence), and packages/notification-core/src/egp_notifications/webhook_delivery.py plus packages/notification-core/src/egp_notifications/dispatcher.py (signed JSON delivery, bounded retry-safe semantics, fail-open behavior, and already-delivered event-id suppression). Tenant admin CRUD is exposed via apps/api/src/egp_api/routes/webhooks.py and apps/api/src/egp_api/services/webhook_service.py, wired in apps/api/src/egp_api/main.py, with supported notification channels updated in apps/api/src/egp_api/services/rules_service.py. The admin UI now includes webhook management in apps/web/src/app/(app)/admin/page.tsx via apps/web/src/lib/api.ts and apps/web/src/lib/hooks.ts. Regression coverage was added in tests/phase2/test_notification_dispatch.py, tests/phase2/test_rules_api.py, and tests/phase4/test_webhooks_api.py.
</info added on 2026-04-05T16:32:39.578+07:00>

### 4.3. Build a full audit log

**Status:** done  
**Dependencies:** None  

Capture material state changes and operator actions for investigation and compliance.

**Details:**

Persist project, document, billing, review, and admin events with actor and timestamp context. Reuse project_status_events patterns where possible and avoid leaving critical transitions outside the audit trail.

<info added on 2026-04-05T17:27:22.000+07:00>
Implementation note: Task 4.3 adds additive schema in packages/db/src/migrations/009_audit_log.sql for direct `audit_log_events`, then exposes a unified tenant-scoped feed through packages/db/src/egp_db/repositories/audit_repo.py and apps/api/src/egp_api/services/audit_service.py. The API now serves `GET /v1/admin/audit-log` from apps/api/src/egp_api/routes/admin.py, wired in apps/api/src/egp_api/main.py, while admin/user/webhook mutations and new document ingests append durable audit rows through apps/api/src/egp_api/services/admin_service.py, apps/api/src/egp_api/services/webhook_service.py, and apps/api/src/egp_api/services/document_ingest_service.py. The admin UI now includes an Audit Log tab in apps/web/src/app/(app)/admin/page.tsx via new clients in apps/web/src/lib/api.ts and apps/web/src/lib/hooks.ts. Regression coverage was added in tests/phase4/test_admin_api.py and validated alongside tests/phase4/test_webhooks_api.py, tests/phase1/test_documents_api.py, and tests/phase3/test_invoice_lifecycle.py.
</info added on 2026-04-05T17:27:22.000+07:00>

### 4.4. Implement self-service admin capabilities

**Status:** pending  
**Dependencies:** None  

Provide tenant-facing administrative controls needed for production operation.

**Details:**

Add admin APIs and UI surfaces for tenant management, notification settings, billing state visibility, and support-safe configuration changes. Keep permission boundaries explicit.

### 4.5. Produce SOC and operational runbooks

**Status:** pending  
**Dependencies:** None  

Document and operationalize incident response, maintenance, and platform operations.

**Details:**

Write the production runbooks covering incidents, scheduled operations, recovery procedures, and support escalation. Keep them aligned with the actual architecture in CLAUDE.md and the implemented platform flows.

### 4.6. Validate disaster recovery and backup workflows

**Status:** pending  
**Dependencies:** None  

Prove backups and restores work for the platform’s critical state and artifacts.

**Details:**

Define backup coverage for the database and artifact storage, then run restore validation against realistic data. Ensure restores preserve tenant isolation and document integrity.

### 4.7. Add cost observability and support tooling

**Status:** pending  
**Dependencies:** None  

Expose operating cost signals and internal tooling needed to support customers at production scale.

**Details:**

Implement dashboards or reports for crawl, storage, notification, and payment-related costs, then add internal support tooling for tenant lookup, issue triage, and safe intervention paths.
