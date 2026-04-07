# Frontend Handoff

## Purpose

This document is the fastest way for a frontend engineer to start shipping UI in this repo without re-reading the crawler, the PRD, or the backend internals.

Use this together with:
- [`docs/PRD.md`](PRD.md)
- [`apps/web/AGENTS.md`](../apps/web/AGENTS.md)
- [`apps/api/AGENTS.md`](../apps/api/AGENTS.md)

---

## Current State

Phase 1 is complete enough for frontend work to start.

What exists today:
- Next.js 15 + React 19 frontend scaffold in [`apps/web`](../apps/web)
- FastAPI control plane in [`apps/api`](../apps/api)
- Stable Phase 1 APIs for:
  - project list
  - project detail
  - document list
  - document download URL
  - run list
- Shared enum values in [`packages/shared-types/src/egp_shared_types/enums.py`](../packages/shared-types/src/egp_shared_types/enums.py)

What does not exist yet:
- dashboard summary APIs
- advanced explorer filters beyond `project_state`
- export endpoints
- notifications UI/API
- billing/admin UI/API
- rules/profiles UI/API

So frontend can start building Phase 2 read-heavy operator pages immediately, but should treat several product areas as placeholders for now.

Important backend auth note:
- Web operators now authenticate with `POST /v1/auth/login` using `tenant_slug`, `email`, and `password`.
- The API issues an HttpOnly session cookie and `GET /v1/me` returns the current user + tenant context.
- The web app now also exposes:
  - `/invite` for invite acceptance
  - `/forgot-password` and `/reset-password` for recovery
  - `/verify-email` for verification tokens
  - `/security` for current-user MFA and verification controls
- Bearer auth still exists for non-browser/API callers as a compatibility path.
- Tenant context is derived from the authenticated session or bearer token, not trusted from caller input.

---

## Repo Map For FE

### Frontend

- App shell: [`apps/web/src/app/layout.tsx`](../apps/web/src/app/layout.tsx)
- Current home page: [`apps/web/src/app/page.tsx`](../apps/web/src/app/page.tsx)
- Current project list component: [`apps/web/src/components/project-list.tsx`](../apps/web/src/components/project-list.tsx)
- Current API helper: [`apps/web/src/lib/api.ts`](../apps/web/src/lib/api.ts)
- Global styles: [`apps/web/src/app/globals.css`](../apps/web/src/app/globals.css)

### Backend routes

- App entrypoint: [`apps/api/src/egp_api/main.py`](../apps/api/src/egp_api/main.py)
- Project routes: [`apps/api/src/egp_api/routes/projects.py`](../apps/api/src/egp_api/routes/projects.py)
- Document routes: [`apps/api/src/egp_api/routes/documents.py`](../apps/api/src/egp_api/routes/documents.py)
- Run routes: [`apps/api/src/egp_api/routes/runs.py`](../apps/api/src/egp_api/routes/runs.py)

### Shared domain values

- Enum source of truth: [`packages/shared-types/src/egp_shared_types/enums.py`](../packages/shared-types/src/egp_shared_types/enums.py)

---

## Frontend Setup

From [`apps/web`](../apps/web):

```bash
npm install
npm run typecheck
npm run lint
npm run build
npm run dev
```

---

## Required Frontend Env Vars

Defined in [`apps/web/src/lib/api.ts`](../apps/web/src/lib/api.ts):

- `NEXT_PUBLIC_EGP_API_BASE_URL`
  - default fallback: `http://127.0.0.1:8000`
- `NEXT_PUBLIC_EGP_TENANT_ID`
  - legacy compatibility value still referenced by a few older components; not required for login/session auth

Example:

```bash
NEXT_PUBLIC_EGP_API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_EGP_TENANT_ID=11111111-1111-1111-1111-111111111111
```

Current FE browser auth is cookie-session based. Do not reintroduce `NEXT_PUBLIC_EGP_API_BEARER_TOKEN` for user-facing login flows.
For normal tenant-scoped pages, do not pass `tenant_id` from the frontend; rely on session context. Keep explicit `tenant_id` only for support-mode cross-tenant admin flows.

---

## Current API Surface

## Health

### `GET /health`

Response:

```json
{ "status": "ok" }
```

---

## Projects

### `GET /v1/projects?tenant_id=<uuid>&project_state=<optional>`

Auth:
- require `Authorization: Bearer <jwt>`
- tenant is resolved from JWT claim
- if `tenant_id` is also sent, it must match the JWT tenant
- supports `limit` and `offset`

Current backend implementation:
- [`apps/api/src/egp_api/routes/projects.py`](../apps/api/src/egp_api/routes/projects.py)

Response shape:

```json
{
  "total": 123,
  "limit": 50,
  "offset": 0,
  "projects": [
    {
      "id": "uuid",
      "tenant_id": "uuid",
      "canonical_project_id": "project-number:EGP-2026-0001",
      "project_number": "EGP-2026-0001",
      "project_name": "string",
      "organization_name": "string",
      "procurement_type": "goods|services|consulting|unknown",
      "proposal_submission_date": "YYYY-MM-DD|null",
      "budget_amount": "string|null",
      "project_state": "discovered|open_invitation|open_consulting|open_public_hearing|tor_downloaded|prelim_pricing_seen|winner_announced|contract_signed|closed_timeout_consulting|closed_stale_no_tor|closed_manual|error",
      "closed_reason": "winner_announced|contract_signed|consulting_timeout_30d|prelim_pricing|stale_no_tor|manual|merged_duplicate|null",
      "source_status_text": "string|null",
      "first_seen_at": "iso-datetime",
      "last_seen_at": "iso-datetime",
      "last_changed_at": "iso-datetime",
      "created_at": "iso-datetime",
      "updated_at": "iso-datetime"
    }
  ]
}
```

Notes:
- Only `project_state` filtering exists today.
- There is no keyword/org/budget/date filtering yet.
- Default paging is `limit=50`, `offset=0`.
- Use this for the current Explorer table.

### `GET /v1/projects/{project_id}?tenant_id=<uuid>`

Auth rules match the list endpoint.

Response shape:

```json
{
  "project": {
    "id": "uuid",
    "tenant_id": "uuid",
    "canonical_project_id": "project-number:EGP-2026-0001",
    "project_number": "EGP-2026-0001",
    "project_name": "string",
    "organization_name": "string",
    "procurement_type": "services",
    "proposal_submission_date": "2026-05-01",
    "budget_amount": "1500000",
    "project_state": "open_invitation",
    "closed_reason": null,
    "source_status_text": "ประกาศเชิญชวน",
    "first_seen_at": "iso-datetime",
    "last_seen_at": "iso-datetime",
    "last_changed_at": "iso-datetime",
    "created_at": "iso-datetime",
    "updated_at": "iso-datetime"
  },
  "aliases": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "alias_type": "project_number|search_name|detail_name|fingerprint",
      "alias_value": "string",
      "created_at": "iso-datetime"
    }
  ],
  "status_events": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "observed_status_text": "string",
      "normalized_status": "string|null",
      "observed_at": "iso-datetime",
      "run_id": "uuid|null",
      "raw_snapshot": {},
      "created_at": "iso-datetime"
    }
  ]
}
```

Use this for:
- Project Detail header
- status timeline
- alias panel
- closure/state summary

---

## Documents

### `GET /v1/documents/projects/{project_id}?tenant_id=<uuid>`

Auth rules match the projects endpoints.

Current backend implementation:
- [`apps/api/src/egp_api/routes/documents.py`](../apps/api/src/egp_api/routes/documents.py)

Response shape:

```json
{
  "documents": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "file_name": "tor.pdf",
      "sha256": "hash",
      "storage_key": "path",
      "document_type": "invitation|mid_price|tor|other",
      "document_phase": "public_hearing|final|unknown",
      "source_label": "string",
      "source_status_text": "string",
      "size_bytes": 123,
      "is_current": true,
      "supersedes_document_id": "uuid|null",
      "created_at": "iso-datetime"
    }
  ]
}
```

Use this for:
- documents panel on Project Detail
- current vs old badge UI
- version history

### `GET /v1/documents/{document_id}/download?tenant_id=<uuid>&expires_in=300`

Auth rules match the projects endpoints.

Response:

```json
{
  "download_url": "signed-or-local-url"
}
```

Use this for:
- “Download latest TOR”
- direct document download actions

---

## Runs

### `GET /v1/runs?tenant_id=<uuid>`

Auth:
- require `Authorization: Bearer <jwt>`
- tenant is resolved from JWT claim
- if `tenant_id` is also sent, it must match the JWT tenant
- supports `limit` and `offset`

Current backend implementation:
- [`apps/api/src/egp_api/routes/runs.py`](../apps/api/src/egp_api/routes/runs.py)

Response shape:

```json
{
  "total": 42,
  "limit": 50,
  "offset": 0,
  "runs": [
    {
      "run": {
        "id": "uuid",
        "tenant_id": "uuid",
        "trigger_type": "schedule|manual|retry|backfill",
        "status": "queued|running|succeeded|partial|failed|cancelled",
        "profile_id": "uuid|null",
        "started_at": "iso-datetime|null",
        "finished_at": "iso-datetime|null",
        "summary_json": {},
        "error_count": 0,
        "created_at": "iso-datetime"
      },
      "tasks": [
        {
          "id": "uuid",
          "run_id": "uuid",
          "task_type": "discover|update|close_check|download",
          "project_id": "uuid|null",
          "keyword": "string|null",
          "status": "queued|running|succeeded|failed|skipped",
          "attempts": 1,
          "started_at": "iso-datetime|null",
          "finished_at": "iso-datetime|null",
          "payload": {},
          "result_json": {},
          "created_at": "iso-datetime"
        }
      ]
    }
  ]
}
```

Use this for:
- Runs & Operations page
- run list
- task drawer / nested detail

Notes:
- Default paging is `limit=50`, `offset=0`.

What is missing:
- retry actions
- logs/screenshots API
- run detail endpoint separate from list

---

## Current Shared Enums

Source of truth:
- [`packages/shared-types/src/egp_shared_types/enums.py`](../packages/shared-types/src/egp_shared_types/enums.py)

### `project_state`

- `discovered`
- `open_invitation`
- `open_consulting`
- `open_public_hearing`
- `tor_downloaded`
- `prelim_pricing_seen`
- `winner_announced`
- `contract_signed`
- `closed_timeout_consulting`
- `closed_stale_no_tor`
- `closed_manual`
- `error`

### `closed_reason`

- `winner_announced`
- `contract_signed`
- `consulting_timeout_30d`
- `prelim_pricing`
- `stale_no_tor`
- `manual`
- `merged_duplicate`

### `procurement_type`

- `goods`
- `services`
- `consulting`
- `unknown`

### `document_type`

- `invitation`
- `mid_price`
- `tor`
- `other`

### `document_phase`

- `public_hearing`
- `final`
- `unknown`

### `run status`

- `queued`
- `running`
- `succeeded`
- `partial`
- `failed`
- `cancelled`

### `task_type`

- `discover`
- `update`
- `close_check`
- `download`

---

## Existing Frontend Code

## Current API helper

[`apps/web/src/lib/api.ts`](../apps/web/src/lib/api.ts)

Today it only exports:
- `ProjectSummary`
- `getApiBaseUrl()`
- `getTenantId()`
- `getApiBearerToken()`
- `fetchProjects()`

The next frontend dev should extend this file first with:
- `fetchProjectDetail(projectId)`
- `fetchProjectDocuments(projectId)`
- `fetchRuns()`
- later: `fetchDashboardSummary()`

## Current page

[`apps/web/src/components/project-list.tsx`](../apps/web/src/components/project-list.tsx)

This already demonstrates:
- env-driven API base URL
- bearer-token header support for local dev
- compatibility `tenant_id` query usage
- loading state
- empty state
- error state
- simple project card rendering

It is a valid reference, but it is not the final product structure.

---

## Best Next FE Sequence

Lowest-friction order for frontend:

1. Project Explorer
2. Project Detail
3. Runs page
4. Dashboard shell using mocked summary data
5. Rules page shell
6. Export actions shell
7. Admin/Billing shell

Reason:
- Explorer/Detail/Runs are already backed by real API data.
- Dashboard/Rules/Exports/Admin are still partially or fully backend-incomplete.

---

## Recommended FE File Structure

Suggested direction, not yet implemented:

```text
apps/web/src/
  app/
    page.tsx
    explorer/page.tsx
    projects/[projectId]/page.tsx
    runs/page.tsx
    dashboard/page.tsx
  components/
    explorer/
      project-table.tsx
      project-filters.tsx
    project-detail/
      project-header.tsx
      status-timeline.tsx
      alias-panel.tsx
      document-history.tsx
    runs/
      run-table.tsx
      run-detail-drawer.tsx
  lib/
    api.ts
    format.ts
    badges.ts
    types.ts
```

---

## Suggested First FE Deliverables

## 1. Explorer page

Build:
- table view using `GET /v1/projects`
- state badge
- project number
- organization
- budget
- last status
- last seen
- row click to detail

Can ship now with only:
- tenant ID
- optional `project_state` filter

## 2. Detail page

Build:
- header summary from `GET /v1/projects/{id}`
- alias panel from `aliases`
- timeline from `status_events`
- documents panel from `GET /v1/documents/projects/{id}`
- document download action from `GET /v1/documents/{document_id}/download`

## 3. Runs page

Build:
- run list from `GET /v1/runs`
- expandable task section
- status badges
- duration formatting

---

## What FE Should Mock For Now

Safe to mock until backend arrives:
- dashboard widgets
- review queue
- rules & profiles editor
- export jobs
- notifications center
- billing/admin tabs
- screenshots/logs/crawl evidence panel details

---

## Known Backend Gaps FE Should Not Block On

- No frontend auth/session UX yet
- No saved views
- No bulk export endpoint
- No search keyword filter in projects API
- No changed-TOR flag in project list response
- No winner-only filter
- No top-level dashboard summary endpoint
- No dedicated run-detail endpoint
- No project notes/review API

These are expected Phase 2 follow-ons.

---

## FE Notes On Product Semantics

- `winner_announced` is a valid project state and is currently accepted as-is.
- Do not assume “winner announced” implies an additional hidden closed state.
- `budget_amount` should be treated as a nullable string from the API and formatted client-side.
- `project_state`, `procurement_type`, `document_type`, and `document_phase` should use exact enum values from shared types.

---

## Recommended FE Team Starting Commands

```bash
cd apps/web
npm install
npm run typecheck
npm run lint
npm run build
npm run dev
```

If local API is running on default settings:

```bash
export NEXT_PUBLIC_EGP_API_BASE_URL=http://localhost:8000
export NEXT_PUBLIC_EGP_TENANT_ID=<tenant-uuid>
export NEXT_PUBLIC_EGP_API_BEARER_TOKEN=<dev-jwt-with-tenant-claim>
```

---

## Final Recommendation

Frontend should start with:
- Explorer
- Detail
- Runs

That path gives the team the most real product surface with the least backend friction, and it aligns directly with the Phase 2 MVP pages in the PRD.
