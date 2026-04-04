# Task ID: 2

**Title:** Phase 2: Product MVP

**Status:** in-progress

**Dependencies:** 1 ⧖

**Priority:** high

**Description:** Deliver the internal beta product surface described in PRD phase 2.

**Details:**

Build the internal beta product around the phase-1 foundation. This phase spans dashboard, Project Explorer, Project Detail, Runs, Rules, export APIs, email notifications, and manual billing plus bank-transfer reconciliation. Use apps/web for the operator-facing UI, apps/api for the product APIs and export surfaces, and packages/notification-core for reusable notification behavior when that package becomes concrete.

**Test Strategy:**

Exercise the end-to-end internal beta flows: project browsing, run inspection, rule visibility, export generation, email delivery, and billing record reconciliation. Cover PRD acceptance test 9 for export correctness against filtered project lists.

## Subtasks

### 2.1. Build the dashboard experience

**Status:** in-progress  
**Dependencies:** None  

Expose key portfolio and run-state summaries on the dashboard page.

**Details:**

Implement the dashboard page in apps/web with API-backed summary cards and operational visibility suitable for internal users. Reuse the canonical state and run data established in phase 1.

### 2.2. Implement Project Explorer and Project Detail

**Status:** done  
**Dependencies:** None  

Provide search, filtering, and project drill-down views for internal beta users.

**Details:**

Add explorer and detail flows in apps/web and the supporting APIs in apps/api. Ensure filters, aliases, lifecycle state, document history, and artifact links all reflect canonical project records rather than legacy exports.

### 2.3. Expose runs and rules pages

**Status:** in-progress  
**Dependencies:** None  

Make crawl/run visibility and rule configuration readable in the product.

**Details:**

Add the runs page for worker execution history and the rules page for lifecycle and alert settings. Keep runs tied to durable crawl-run records and make rule definitions traceable to explicit platform logic rather than hidden script behavior.

### 2.4. Ship export APIs and operator exports

**Status:** done  
**Dependencies:** None  

Provide export endpoints and UI triggers for filtered project data.

**Details:**

Implement export APIs in apps/api and the corresponding operator controls in apps/web. Exports should be derived from canonical filtered project views so that export output matches what the user sees in the product. This subtask also serves as the fulfillment layer for the `One-Time Search Pack`: one batch export of all relevant TOR files for projects matching a purchased keyword.

### 2.5. Add email notification delivery

**Status:** in-progress  
**Dependencies:** None  

Send internal beta alerts for project and document events.

**Details:**

Wire email notification generation to platform events and keep the implementation reusable so packages/notification-core can absorb it cleanly later. Ensure tenant boundaries and notification preferences are respected.

### 2.6. Implement manual billing records and bank transfer reconciliation

**Status:** pending  
**Dependencies:** None  

Support internal beta billing operations without automated subscription rails yet.

**Details:**

Add billing record management, manual payment recording, and reconciliation support in the API and admin-facing UI. Keep invoice and activation concepts compatible with the payment workflows planned for phase 3. Pricing and package definitions for launch should cover `One-Time Search Pack` (`300 THB`, `1 keyword`, batch export fulfillment, expires after `3 days` even if no projects match) and `Monthly Membership` (`1,500 THB`, prepaid monthly, up to `5 keywords`, cancel anytime with access through the paid period).
