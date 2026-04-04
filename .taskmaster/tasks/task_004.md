# Task ID: 4

**Title:** Phase 4: Commercial Hardening

**Status:** pending

**Dependencies:** 3

**Priority:** medium

**Description:** Harden the platform for production readiness as described in PRD phase 4.

**Details:**

Prepare the platform for production operation by adding multi-tenant quotas, webhook notifications, a full audit log, self-service admin, SOC and operational runbooks, disaster recovery and backup validation, cost observability, and support tooling. This phase should tighten operational controls without violating the core architecture and tenant-isolation rules established earlier.

**Test Strategy:**

Validate production-readiness outcomes with quota enforcement tests, webhook contract tests, audit-log coverage, tenant-isolation checks, backup/restore drills, and support-runbook verification. PRD acceptance test 10 remains a hard requirement throughout this phase.

## Subtasks

### 4.1. Implement multi-tenant quotas and entitlement enforcement

**Status:** pending  
**Dependencies:** None  

Enforce per-tenant limits and plan-based product boundaries.

**Details:**

Add tenant-level quota tracking and enforcement in the API and supporting data model. Tie quota behavior to subscription state from phase 3 and ensure limits are applied consistently across runs, exports, documents, and notifications. This includes enforcing launch-package entitlements: `One-Time Search Pack` allows exactly `1 keyword` for `3 days`, while `Monthly Membership` allows up to `5 active keywords` during the prepaid billing period.

### 4.2. Add webhook notification delivery

**Status:** pending  
**Dependencies:** None  

Deliver machine-consumable notifications alongside email and in-product surfaces.

**Details:**

Implement tenant-configurable webhook subscriptions and outbound delivery with retry-safe semantics. Keep payloads auditable and compatible with the event model established earlier in the platform.

### 4.3. Build a full audit log

**Status:** pending  
**Dependencies:** None  

Capture material state changes and operator actions for investigation and compliance.

**Details:**

Persist project, document, billing, review, and admin events with actor and timestamp context. Reuse project_status_events patterns where possible and avoid leaving critical transitions outside the audit trail.

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
