# e-GP Intelligence Platform — Product Requirements Document

**Version:** 1.0
**Date:** 2026-04-02
**Status:** Draft
**Authors:** Engineering Team

---

## Table of Contents

1. [Product Name](#1-product-name)
2. [Product Summary](#2-product-summary)
3. [Problem Statement](#3-problem-statement)
4. [Product Vision](#4-product-vision)
5. [Goals](#5-goals)
6. [Non-goals for MVP](#6-non-goals-for-mvp)
7. [Primary Users](#7-primary-users)
8. [Core Product Principles](#8-core-product-principles)
9. [Core Modules](#9-core-modules)
10. [Detailed Lifecycle Rules](#10-detailed-lifecycle-rules)
11. [Document Rules](#11-document-rules)
12. [User Stories](#12-user-stories)
13. [UI Requirements](#13-ui-requirements)
14. [Roles and Permissions](#14-roles-and-permissions)
15. [Non-functional Requirements](#15-non-functional-requirements)
16. [Success Metrics](#16-success-metrics)
17. [Target Architecture](#17-target-architecture)
18. [Service Boundaries](#18-service-boundaries)
19. [State Model](#19-state-model)
20. [Database Schema](#20-database-schema)
21. [Document Versioning Rules](#21-document-versioning-rules)
22. [Crawl Workflows](#22-crawl-workflows)
23. [API Endpoints](#23-api-endpoints)
24. [Frontend Page Structure](#24-frontend-page-structure)
25. [Supabase Deployment Blueprint](#25-supabase-deployment-blueprint)
26. [Thailand Payment Integration](#26-thailand-payment-integration)
27. [Data Retention and Backup](#27-data-retention-and-backup)
28. [Security Plan](#28-security-plan)
29. [Implementation Phases](#29-implementation-phases)
30. [Acceptance Tests](#30-acceptance-tests)
31. [Risks and Mitigations](#31-risks-and-mitigations)

---

## 1. Product Name

**e-GP Intelligence Platform**

Working name for the SaaS product that transforms the existing e-GP crawler script into a commercial procurement monitoring service.

---

## 2. Product Summary

A SaaS platform that continuously crawls Thailand's e-GP procurement system, discovers relevant tenders based on customer-defined profiles and keywords, downloads and versions procurement documents (TOR), detects lifecycle changes (winner announcements, stale consulting projects), and presents results through a searchable web application with notifications, exports, and audit history.

---

## 3. Problem Statement

Organizations tracking public procurement in Thailand face five persistent problems:

1. **Discovery is manual and repetitive** — analysts must search e-GP daily for matching tenders
2. **Document downloads are fragile** — browser automation against e-GP fails intermittently (Cloudflare, timeouts, OneDrive permission errors)
3. **Duplicate projects** — the same project appears under different names/keywords with no canonical identity
4. **Ambiguous project closure** — especially for consulting procurements and winner announcements; the current script uses binary `tor_downloaded`/`prelim_pricing` flags
5. **No document versioning** — draft TOR (public hearing) can differ from final TOR, but most workflows overwrite rather than preserve history

The current `egp_crawler.py` script (2,200 lines, single-file) solves part of this for a power user but has these architectural limitations:

- Excel as source of truth (`project_list.xlsx`)
- Binary completion model (`tor_downloaded == Yes OR prelim_pricing == Yes`)
- Only searches invitation status (`หนังสือเชิญชวน/ประกาศเชิญชวน`)
- Single 45-day stale rule that writes fake `tor_downloaded = Yes` to stop revisits
- OneDrive dependency with documented permission failures in runtime logs
- No document hashing, versioning, or phase classification
- No project number canonicalization (relies on triple-key Excel indexing)

---

## 4. Product Vision

Provide the most reliable Thailand public-procurement monitoring platform for consultants, integrators, system vendors, and bid teams by combining:

- High-reliability crawling with isolated browser workers
- Project lifecycle intelligence with explicit state transitions
- Document versioning with content-hash-based diff detection
- Collaborative review workflows
- Thai-friendly payment and billing flows (PromptPay QR, bank transfer)

---

## 5. Goals

### Business Goals

- Launch a sellable SaaS product for Thai B2B customers
- Reduce manual tender monitoring work by at least 70%
- Support subscription billing with Thai payment rails
- Reach stable multi-tenant production readiness

### User Goals

- Find relevant tenders quickly via keyword profiles
- Avoid duplicate or missed projects
- Know when a project is effectively closed (winner announced, contract signed, consulting timeout)
- Compare public-hearing TOR and final TOR side by side
- Export or share findings easily

---

## 6. Non-goals for MVP

- Automatic bid writing or proposal generation
- Full OCR of every uploaded scan as default behavior
- Deep financial analysis of TOR documents
- Mobile native app
- International procurement sources beyond e-GP
- Fully automated legal/compliance interpretation

---

## 7. Primary Users

| Persona | Role | Primary Needs |
|---------|------|---------------|
| **A** | Business Development Manager | Alerts on new projects, budgets, agencies, closing status |
| **B** | Presales / Bid Analyst | Full document history, TOR version comparison, exports |
| **C** | Administrator / Owner | Tenant management, usage controls, billing, auditability |
| **D** | Operations Analyst | Run health, worker failures, retry controls, rule tuning |

---

## 8. Core Product Principles

1. Local and persistent project history
2. Explicit lifecycle state, not binary done/not-done
3. Document version preservation (never overwrite)
4. Operational transparency (every action logged)
5. Thai-first workflows
6. Multi-tenant from the start

---

## 9. Core Modules

### 9.1 Discovery Engine

- Run profile-based keyword searches against e-GP
- Support predefined profiles (TOR/TOE/LUE) and user-defined profiles
- Search multiple pages per keyword (configurable, default 15)
- Store `first_seen_at` and `last_seen_at` timestamps
- Classify `procurement_type` where possible (goods/services/consulting)

### 9.2 Project Registry

- One canonical project record per real project
- Merge aliases from different names, search names, and identifiers
- Fallback fingerprinting when `project_number` is absent: `normalized_org + normalized_project_name + invitation_date + budget`
- Keep status history over time via `project_status_events`

### 9.3 Document Collection

- Download procurement documents (invitation, mid-price, TOR)
- Classify documents by type and phase
- SHA-256 hash artifacts to prevent duplicate storage
- Preserve all distinct document versions
- Store metadata: label, source URL, size, hash, timestamp

### 9.4 TOR Versioning and Compare

- Distinguish public-hearing TOR from final TOR
- Preserve both versions when both exist
- Detect content changes via hash comparison
- Side-by-side comparison in UI
- Alert when final TOR materially differs from public-hearing TOR

### 9.5 Lifecycle Intelligence

- Mark projects closed when winner announcement or contract-signing status detected
- Mark consulting projects closed after configurable inactivity (default 30 days)
- Mark stale non-consulting projects closed after configurable threshold (default 45 days)
- Preserve closure reason separately from download success
- Never write fake `tor_downloaded = Yes` as a closure mechanism

### 9.6 Notifications

Supported alert types:
- New project discovered
- Winner announced
- Contract signed
- TOR changed (public hearing vs final differs)
- Failed crawl run
- Export ready

MVP channels: email, in-app, webhook
Later: LINE Messaging integration

### 9.7 Search, Filter, Export

- Full-text and field-based filtering
- Saved views
- CSV and Excel export
- Per-project sharing links within tenant
- Sorting by relevance, date, budget, organization

### 9.8 Administration

- Tenant settings
- User management with roles
- API keys / webhooks
- Profile and keyword configuration
- Crawl frequency and rule configuration
- Audit log

### 9.9 Billing and Payments

- Subscription invoicing
- Payment by Thai bank transfer
- Payment by Thai QR / PromptPay
- Optional payment-link flow
- Manual or automatic reconciliation

---

## 10. Detailed Lifecycle Rules

### 10.1 Project States

```
discovered
open_invitation
open_consulting
open_public_hearing
tor_downloaded
prelim_pricing_seen
winner_announced
contract_signed
closed_timeout_consulting
closed_stale_no_tor
closed_manual
error
```

### 10.2 Closure Reasons

```
winner_announced
contract_signed
consulting_timeout_30d
prelim_pricing
stale_no_tor
manual
merged_duplicate
```

### 10.3 Consulting Closure Rule

If `procurement_type = consulting` AND no meaningful change observed for 30 days:
- Set `project_state = closed_timeout_consulting`
- Set `closed_reason = consulting_timeout_30d`

### 10.4 Winner Closure Rule

If matched project observed with winner announcement or equivalent close-status:
- Set `project_state = winner_announced` or `contract_signed`
- Set `closed_reason` accordingly

### 10.5 Stale Closure Rule

If non-consulting project remains open beyond configured threshold AND no qualifying document or status movement:
- Set `project_state = closed_stale_no_tor`
- Set `closed_reason = stale_no_tor`
- Do NOT write fake `tor_downloaded = Yes`

---

## 11. Document Rules

### 11.1 Artifact Identity

A document is unique by: `project_id + content_hash (SHA-256) + document_type + document_phase`

### 11.2 Document Phases

```
public_hearing     — ประชาพิจารณ์ TOR
final              — Final TOR after bidding process
unknown            — Cannot determine phase
```

### 11.3 Duplicate Handling

Same project + same content hash = do not store as new version; attach observation metadata only.

### 11.4 Supersession

Same project + same document class + different hash:
- Previous version: `is_current = false`
- New document: `is_current = true`
- Create `document_diffs` row
- Raise `tor_changed` notification

---

## 12. User Stories

### Discovery
- As a BD manager, I want to define keywords and get alerted when matching projects appear
- As an analyst, I want one project record even if the same tender appears under multiple keywords

### Review
- As an analyst, I want to see all TOR versions for a project
- As an analyst, I want to compare draft and final TOR text

### Closure
- As a user, I want winner-announced projects automatically closed
- As a consulting-focused user, I want hanging consulting tenders auto-closed after 30 days of inactivity

### Admin
- As an owner, I want to manage users, plans, and billing settings
- As an ops user, I want to inspect crawl runs and retry failures

### Billing
- As a Thai customer, I want to pay by bank transfer or QR code
- As an admin, I want payment status tied to subscription activation

---

## 13. UI Requirements

### 13.1 Pages

| # | Page | Purpose |
|---|------|---------|
| 1 | Login | Email/password, SSO later, MFA optional |
| 2 | Dashboard | Active projects, new today, closed today, changed TOR, failed runs, alerts |
| 3 | Project Explorer | Main table with filters, bulk export, saved views |
| 4 | Project Detail | Summary, timeline, status history, aliases, documents, crawl evidence |
| 5 | TOR Compare | Two-pane diff view, metadata diff, review outcome |
| 6 | Runs & Operations | Run list, task list, logs, screenshots, retry actions |
| 7 | Rules & Profiles | Keywords, page limit, closure rules, notification rules, schedules |
| 8 | Admin & Billing | Users, roles, plan, invoices, payment status, webhooks |

### 13.2 Project Explorer Columns

| Column | Description |
|--------|-------------|
| Project | Name (truncated) |
| Organization | Agency name |
| Project Number | e-GP reference |
| Procurement Type | goods/services/consulting |
| State | Current lifecycle state badge |
| Budget | Amount in THB |
| Last Status | Most recent observed status |
| Last Seen | Timestamp |
| Winner | Flag if winner announced |
| Changed TOR | Flag if TOR content changed |

### 13.3 UX Requirements

- Thai and English UI ready (MVP can launch English first)
- Fast table filtering (< 200ms perceived)
- Clear state badges with color coding
- Obvious current vs old document badges
- Strong auditability for every closure and version change

---

## 14. Roles and Permissions

| Role | Capabilities |
|------|-------------|
| **Owner** | Full tenant and billing control |
| **Admin** | Operational and user administration |
| **Analyst** | Project and document access, review and annotate |
| **Viewer** | Read-only access |

---

## 15. Non-functional Requirements

| Category | Target |
|----------|--------|
| Availability | 99.5% MVP, 99.9% post-hardening |
| Page Load | < 2s for project list with common filters |
| Export Generation | < 2 minutes for standard datasets |
| Crawl Scheduling | Near real-time for manual runs |
| Encryption | In transit (TLS) and at rest |
| Tenant Isolation | Row-level security, no cross-tenant data access |
| Compliance | PDPA-aware user data handling |

---

## 16. Success Metrics

### Product KPIs
- Daily active tenants
- Projects discovered per tenant
- Project dedupe success rate
- Document download success rate
- Changed-TOR detection rate
- Payment conversion rate
- Churn

### Ops KPIs
- Crawl success rate
- Worker failure rate
- Mean time to detect crawl regressions
- Mean time to reconcile payments

---

## 17. Target Architecture

```
[Frontend SPA]
     |
     v
[API Service] ---- [Supabase Postgres]
     |                  |
     |                  +-- project state, documents, rules, runs, alerts
     |
     +---- [Supabase Storage] raw docs / normalized docs / exports / screenshots
     |
     +---- [Job Queue / Scheduler] crawl jobs / retry jobs / close-check jobs
                    |
                    v
             [Crawler Workers]
                    |
                    +-- Playwright + Chrome session
                    +-- e-GP parsing
                    +-- document download
                    +-- status tracking
                    +-- hash + versioning

[Scheduler] -> enqueues periodic crawl jobs
[Notifier]  -> email / LINE / webhook / in-app alerts
[Doc Processor] -> extract text, hash, compare TOR versions
```

**Key principle:** The crawler worker does NOT own product state. It only emits events and artifacts. The API service owns all state transitions.

---

## 18. Service Boundaries

### A. API Service (`/apps/api`)

**Responsibilities:** tenants, users, auth, roles, project CRUD, document/history APIs, rule configuration, scheduling, exports, audit log

**Stack:** Python FastAPI, PostgreSQL (Supabase-managed in hosted environments), Redis (optional for caching)

### B. Crawler Worker (`/apps/worker`)

**Responsibilities:** open e-GP, pass Cloudflare/Turnstile, search by keyword/profile, discover project pages, classify state, download documents, emit events (project_discovered, project_updated, project_closed, document_downloaded, tor_version_changed, crawl_failed)

**Stack:** Python, Playwright, isolated Chrome session

**Why isolated:** Current script depends on real Chrome/Playwright with persistent browser profile. Operationally different from a normal API container.

### C. Document Processor (`/apps/doc-processor`)

**Responsibilities:** SHA-256 hash every artifact, extract text from PDF/HTML/ZIP, classify document type and phase, detect public-hearing vs final TOR, generate diff metadata

### D. Scheduler

**Responsibilities:** periodic crawl launches, close-check jobs, backfill jobs, retry with backoff, dead-letter handling

**Implementation:** scheduler + queue provider kept flexible; Supabase-backed Postgres remains the source of truth

### E. Notification Service

**Responsibilities:** changed TOR alert, project closed alert, winner announced alert, failed crawl alert, export ready alert

---

## 19. State Model

### Current Script State (REPLACING)

```python
# egp_crawler.py:1069
done = tor_status == "yes" or prelim == "yes"
```

This binary model is replaced with an explicit lifecycle enum.

### New Project State Machine

```
discovered ──────────────────► open_invitation
                                    │
                          ┌─────────┼──────────┐
                          ▼         ▼          ▼
                   open_consulting  open_public_hearing
                          │         │          │
                          ▼         ▼          ▼
                   tor_downloaded ◄─┘    prelim_pricing_seen
                          │                    │
                          ▼                    ▼
                   winner_announced ◄──────────┘
                          │
                          ▼
                   contract_signed
                          │
                          ▼
                      [CLOSED]

Timeout paths:
  open_consulting ──(30d)──► closed_timeout_consulting
  open_* ──(45d)──► closed_stale_no_tor
  Any ──(manual)──► closed_manual
```

---

## 20. Database Schema

See `/packages/db/src/migrations/001_initial_schema.sql` for complete DDL.

### Core Tables

| Table | Purpose |
|-------|---------|
| `tenants` | Multi-tenant root |
| `users` | Tenant users with roles |
| `crawl_profiles` | Keyword groups + rules |
| `crawl_profile_keywords` | Keywords per profile |
| `projects` | Canonical project records with lifecycle state |
| `project_aliases` | Alternative names/numbers/fingerprints |
| `project_status_events` | Status change history |
| `documents` | Versioned document artifacts with SHA-256 |
| `document_diffs` | Diff metadata between document versions |
| `crawl_runs` | Crawl execution records |
| `crawl_tasks` | Individual tasks within a run |
| `notifications` | Alert records |
| `exports` | Export job records |

### Canonical ID Rule

1. Use `project_number` when present
2. Else use stable fingerprint: `normalized_org + normalized_project_name + invitation_date + budget`
3. Keep all alternative names in `project_aliases`

---

## 21. Document Versioning Rules

### Classification Rules

When a file is downloaded:
- `document_type = tor` if label matches TOR-like terms (`TOR_DOC_MATCH_TERMS`)
- `document_phase = public_hearing` if label contains ประชาพิจารณ์ or status/page context indicates hearing/draft
- `document_phase = final` if winner/final bidding context or TOR appears later with no hearing marker
- Otherwise `document_phase = unknown`

### Replacement Rules

- Same project + same hash → duplicate, do not create new version
- Same project + different hash + same `document_type=tor`:
  - Previous: `is_current = false`
  - New: `is_current = true`
  - Create `document_diffs` row
  - Raise `tor_changed` notification

### UI Behavior

Project Detail shows:
- TOR (Public Hearing) — version 1
- TOR (Final) — version 2
- Badge: "Changed" or "Identical"
- Actions: View original, Download, Compare text, Mark as reviewed

---

## 22. Crawl Workflows

### Workflow A — Discover Open Projects
1. Run keyword search
2. Collect eligible rows
3. Open project detail page
4. Extract identifiers and metadata
5. Upsert project
6. Schedule document download tasks

### Workflow B — Update Existing Open Projects
1. For active/open projects, revisit detail page
2. Refresh status and documents
3. If no change, update `last_seen_at`
4. If state changed, emit status event

### Workflow C — Close-check Sweep (NEW)

Run a second search for:
- ประกาศผู้ชนะประกวดราคา (winner announced)
- Contract signed statuses

Then:
- Match by project number or alias
- Set `project_state = winner_announced` or `contract_signed`
- Set `closed_reason`
- Disable future open-check scheduling

### Workflow D — Consulting Timeout Sweep (NEW)
- For `procurement_type = consulting`
- If still open and unchanged for 30 days
- Mark `closed_timeout_consulting`

### Workflow E — Stale Fallback Sweep (MODIFIED)
- For non-consulting open items
- If unchanged past threshold and no TOR/final artifact
- Mark `closed_stale_no_tor`
- Do NOT write `tor_downloaded = Yes`

---

## 23. API Endpoints

### Auth and Tenant
```
POST   /v1/auth/login
POST   /v1/auth/logout
GET    /v1/me
GET    /v1/tenant
GET    /v1/users
POST   /v1/users
PATCH  /v1/users/:id
```

### Profiles and Rules
```
GET    /v1/profiles
POST   /v1/profiles
GET    /v1/profiles/:id
PATCH  /v1/profiles/:id
POST   /v1/profiles/:id/keywords
DELETE /v1/profiles/:id/keywords/:keywordId
```

### Runs and Tasks
```
GET    /v1/runs
POST   /v1/runs
GET    /v1/runs/:id
GET    /v1/runs/:id/tasks
POST   /v1/runs/:id/retry-failed
POST   /v1/runs/:id/cancel
```

### Projects
```
GET    /v1/projects
GET    /v1/projects/:id
PATCH  /v1/projects/:id
POST   /v1/projects/:id/close
POST   /v1/projects/:id/reopen
GET    /v1/projects/:id/status-events
GET    /v1/projects/:id/aliases
```

Filters: `state`, `closedReason`, `procurementType`, `organization`, `keyword`, `budgetMin`, `budgetMax`, `updatedAfter`, `hasChangedTor`, `hasWinner`

### Documents
```
GET    /v1/projects/:id/documents
GET    /v1/documents/:id
GET    /v1/documents/:id/download
GET    /v1/documents/:id/text
GET    /v1/documents/:id/diff/:otherId
POST   /v1/documents/:id/mark-reviewed
```

### Notifications
```
GET    /v1/notifications
PATCH  /v1/notifications/:id/read
POST   /v1/webhooks
GET    /v1/webhooks
DELETE /v1/webhooks/:id
```

### Exports
```
POST   /v1/exports
GET    /v1/exports
GET    /v1/exports/:id/download
```

---

## 24. Frontend Page Structure

### Page 1: Login
- Email/password or SSO
- Remember device, MFA optional later

### Page 2: Dashboard
- Widgets: Active projects, Closed today, Winner today, TOR changed this week, Failed runs, Crawl/download success rates, Top organizations
- Bottom panels: Recent runs, Recently changed projects, Review queue

### Page 3: Project Explorer
- Left filter rail (state, procurement type, org, keyword, date range, budget range, changed TOR only, winner only, closed reason)
- Main table with columns (see section 13.2)
- Row actions: Open, Download latest TOR, Mark closed, Export row, Copy link

### Page 4: Project Detail
- Header summary
- Timeline / status history
- Alias/identifier panel
- Documents panel with version history
- Crawl evidence panel (logs, screenshots)
- Notes/review panel
- Closure info

### Page 5: TOR Compare
- Two-pane view with version selector
- Text diff + metadata diff + change summary
- Review outcome: no material change / material change / needs manual review

### Page 6: Runs & Operations
- Run list table (ID, profile, trigger, status, duration, discovered, updated, closed, errors)
- Detail drawer: task list, logs, screenshots, retry actions

### Page 7: Rules & Profiles
- Tabs: profiles, keywords, close rules, retry/backoff, notifications, webhooks
- Configure: consulting 30-day close, stale 45-day close, close on winner, notify on TOR changed

### Page 8: Admin / Billing
- Tabs: users & roles, API keys, audit log, usage & quotas, plan/billing, tenant settings

---

## 25. Supabase Deployment Blueprint

**Note:** prefer Supabase for managed Postgres, Auth, and Storage; keep crawler workers on a separate container host.

### Services

| Service | Managed Resource |
|---------|------------------|
| Frontend | Vercel or equivalent static/app host |
| Auth | Supabase Auth |
| API + Workers | Container host (Fly.io / Railway / Render / ECS) |
| Database | Supabase Postgres |
| Document Storage | Supabase Storage (separate prefixes/buckets per env) |
| Job Queues | Provider-flexible queue or DB-backed job runner |
| Scheduling | Provider-flexible cron / scheduled jobs |
| Secrets | Supabase secrets + host secret manager |
| Monitoring | Host/platform logs, metrics, alarms |

### VPC Layout

```
Public Edge:     frontend host + API ingress
App Runtime:     API, crawler worker, doc processor containers
Managed Data:    Supabase Postgres, Supabase Storage, optional Redis
Background:      queue + scheduler provider
```

### Container Split

- `api-service` — FastAPI
- `worker-dispatcher` — job orchestration
- `crawler-worker` — Playwright/Chrome (low concurrency)
- `doc-processor` — hashing, classification, diff
- `notifier` — email/webhook delivery

### Environments

- **Dev:** single-tenant sandbox, smaller DB, lower concurrency
- **Staging:** production-like networking, real queueing, safe test data
- **Production:** managed Postgres backups enabled, isolated runtime secrets, separate worker autoscaling, tested backup/restore

---

## 26. Thailand Payment Integration

### Priority Order

1. **PromptPay QR** — core Thai payment rail, instant settlement
2. **Manual bank transfer** with invoice — common for Thai B2B
3. **Payment links** with PromptPay QR option
4. **Card payments** — later, not first

### Provider Options

| Provider | PromptPay QR | Payment Links | Notes |
|----------|-------------|---------------|-------|
| Omise/Opn | Yes (source + charge + webhook) | Yes | Well-documented Thai API |
| Xendit | Yes (instant settlement) | Yes | Strong SMB checkout |
| 2C2P | Yes | Yes | Broader enterprise coverage |
| KBank QR API | Yes (direct bank) | Limited | Good for later scale |

### Payment UX

**QR Flow:** Show QR + expiry → customer scans → webhook confirms → subscription activates

**Bank Transfer Flow:** Invoice with amount + account details → customer transfers → uploads slip → admin verifies → subscription activates

### Billing States

```
draft → issued → awaiting_payment → payment_detected → paid
                                  → failed / overdue / cancelled / refunded
```

---

## 27. Data Retention and Backup

| Resource | Policy |
|----------|--------|
| Database | Automated snapshots, PITR, 30-35 day retention |
| Artifacts (Supabase Storage) | Versioned prefixes/buckets, lifecycle rules for old evidence |
| Logs | CloudWatch, archival after 90 days |

---

## 28. Security Plan

- Supabase Auth with JWT
- RBAC enforced in API middleware
- Tenant scoping on every database query
- Signed Supabase Storage URLs for documents
- Secrets only in Supabase secrets or host secret manager
- No payment secrets in frontend
- Webhook signature verification
- Audit log for admin actions and billing changes
- PDPA-aware user data handling

---

## 29. Implementation Phases

### Phase 1: Foundation and State Correctness

**Goal:** Replace fragile script-state assumptions

- PostgreSQL schema
- API service skeleton
- Crawler worker refactor (extract from monolithic script)
- Canonical project model with aliases
- Explicit lifecycle state and closure reasons
- Document hashing (SHA-256)
- Supabase Storage / object-storage artifact persistence
- Basic project list UI

**Exit criteria:**
- One canonical project per real tender
- Winner-close and consulting-close rules work
- Duplicate artifacts no longer create duplicate versions

### Phase 2: Product MVP

**Goal:** Internal beta

- Dashboard
- Project Explorer
- Project Detail
- Runs page
- Rules page
- Export APIs
- Email notifications
- Manual billing records + bank transfer reconciliation

### Phase 3: TOR Intelligence and Payments

**Goal:** Commercial beta

- Public-hearing vs final TOR classification
- Diff engine
- Review workflow
- Payment link generation
- PromptPay QR integration
- Invoice lifecycle and subscription activation

### Phase 4: Commercial Hardening

**Goal:** Production readiness

- Multi-tenant quotas
- Webhook notifications
- Full audit log
- Self-service admin
- SOC/ops runbooks
- DR and backup validation
- Cost observability
- Support tooling

---

## 30. Acceptance Tests

1. Same project found under 3 different keywords creates one canonical project
2. Same project without `project_number` on day 1 and with `project_number` on day 3 merges correctly
3. ประชาพิจารณ์ TOR and final TOR with same bytes do NOT create false change alerts
4. ประชาพิจารณ์ TOR and final TOR with different bytes DO create a change alert and both remain accessible
5. Consulting project with no status movement for 30 days closes automatically
6. Project with ประกาศผู้ชนะประกวดราคา closes automatically
7. Browser download failure does not create duplicate project rows
8. Managed object-storage artifact exists even when UI parsing partially fails
9. Exported Excel matches filtered project list
10. Tenant A cannot access Tenant B's projects or artifacts

---

## 31. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Gateway onboarding/KYC delay | Launch with manual bank transfer; parallelize PSP onboarding |
| Duplicate payment events | Idempotency keys + provider event log table |
| Slip fraud in manual transfer | Do not auto-activate on slip upload; require finance verification |
| Crawl fragility (e-GP changes) | Isolate workers, preserve evidence, retries + DLQs, regression fixtures |
| Cloudflare blocks automation | Persistent Chrome profile, browser fingerprint management |
| Managed backend lock-in | Keep crawler runtime, queueing, and artifact interfaces provider-agnostic |
| Excel migration data loss | Keep Excel as export format; migrate with validation |
| Test keyword count drift (12 vs 11) | Fix in Phase 1; add assertion in CI |
