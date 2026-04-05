# Task ID: 3

**Title:** Phase 3: TOR Intelligence and Payments

**Status:** in-progress

**Dependencies:** 2

**Priority:** high

**Description:** Deliver the commercial beta intelligence and payment workflows described in PRD phase 3.

**Details:**

Implement the commercial-beta layer: classify public-hearing versus final TOR documents, generate document diffs, support review workflows, and add payment flows including payment link generation, PromptPay QR support, invoice lifecycle, and subscription activation. This phase depends directly on the document hashing/versioning base from phase 1 and the operator product surfaces from phase 2.

**Test Strategy:**

Cover PRD acceptance tests 3 and 4 for TOR classification and change alerts, then validate the billing path from invoice creation through payment confirmation and subscription activation.

## Subtasks

### 3.1. Classify public-hearing versus final TOR documents

**Status:** done  
**Dependencies:** None  

Detect TOR phase correctly so identical and changed documents are handled with the right semantics.

**Details:**

Implement public_hearing versus final TOR classification in apps/doc-processor and shared packages, keeping names aligned with packages/shared-types/src/enums.py and document constraints in packages/db/src/migrations/001_initial_schema.sql.

### 3.2. Build the diff engine and surfaced change alerts

**Status:** done  
**Dependencies:** None  

Generate meaningful document diffs and attach them to reviewable project events.

**Details:**

Store structured diff metadata for document pairs, preserve both versions, and surface change alerts without false positives when bytes are identical. The document processor should write durable diff records rather than transient filesystem artifacts.

### 3.3. Add review workflow for document intelligence

**Status:** done  
**Dependencies:** None  

Let operators review and disposition detected document changes before downstream actions.

**Details:**

Implement review states, operator actions, and traceability for document-change review. Keep auditability explicit so future support and compliance work in phase 4 has a clean foundation.

<info added on 2026-04-05T13:32:43.000+07:00>
Implemented an API-first document review workflow on top of `document_diffs`. Added shared review enums in `packages/shared-types/src/egp_shared_types/enums.py` plus additive schema in `packages/db/src/migrations/006_document_reviews.sql` for `document_diff_reviews` and `document_review_events`. `packages/db/src/egp_db/repositories/document_repo.py` now auto-creates a pending review for each changed diff, supports tenant-scoped review listing/action history, and validates approve/reject/reopen transitions.

`apps/api/src/egp_api/routes/documents.py` now exposes `GET /v1/documents/projects/{project_id}/reviews` and `POST /v1/documents/reviews/{review_id}/actions`, backed by new service methods in `apps/api/src/egp_api/services/document_ingest_service.py`. TOR-change notifications are no longer emitted at ingest time; they dispatch only on first approval so downstream actions are explicitly operator-gated. Coverage: `tests/phase1/test_document_persistence.py` and `tests/phase1/test_documents_api.py` now verify pending review creation, tenant scoping, action history, and approval-triggered notification dispatch.
</info added on 2026-04-05T13:32:43.000+07:00>

### 3.4. Generate payment links and PromptPay QR codes

**Status:** pending  
**Dependencies:** None  

Support commercial beta payment collection flows for subscriptions or invoice settlement.

**Details:**

Implement payment link creation and PromptPay QR generation in a way that integrates cleanly with invoice records and tenant-scoped billing state. Keep external provider calls isolated behind service boundaries.

### 3.5. Implement invoice lifecycle and subscription activation

**Status:** done  
**Dependencies:** None  

Move from manual billing records to invoice-driven activation and entitlement changes.

**Details:**

Define invoice states, payment reconciliation hooks, and subscription activation behavior in the API and data model. Preserve auditability and ensure successful payment activates the right tenant entitlements without cross-tenant leakage.
