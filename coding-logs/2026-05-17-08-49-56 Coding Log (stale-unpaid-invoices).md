# Coding Log — stale unpaid invoices

Created: 2026-05-17T08:49:56+07:00

## Plan Draft A — backend-first classification + filtered primary snapshot

### Overview
Classify stale unpaid invoices in the billing domain, make the normal billing snapshot exclude them by default, and expose them only through an explicit history path while preserving full admin visibility. This keeps the source-of-truth lifecycle intact while preventing expired unpaid invoices from shaping current checkout UX.

### Files to Change
- `packages/db/src/egp_db/repositories/billing_models.py` — expose stale classification on billing records.
- `packages/db/src/egp_db/repositories/billing_utils.py` — derive stale-unpaid state from period end, status, and outstanding balance.
- `packages/db/src/egp_db/repositories/billing_invoices.py` — support filtered primary snapshots vs full-history snapshots and summaries.
- `apps/api/src/egp_api/services/billing_service.py` — default customer-facing list to primary records and reject payment requests for stale records.
- `apps/api/src/egp_api/routes/billing.py` — serialize classification and add explicit history query flag.
- `apps/web/src/lib/api.ts`, generated API artifacts, `apps/web/src/app/(app)/billing/page.tsx` — request primary vs history views and keep stale records out of primary selection/CTA logic.
- Tests under `tests/phase3/`, `apps/web/tests/unit/`, `apps/web/tests/e2e/` — lock the behavior.

### Implementation Steps
1. Add failing backend tests for default exclusion, explicit history inclusion, and stale payment-request rejection.
2. Add failing frontend/API tests proving history flag wiring and two expired-plan CTAs remain visible when only stale unpaid upgrades exist.
3. Implement the smallest derived-classification change; avoid schema/status migrations.
4. Filter primary list + summary at the service/repository boundary while keeping admin on full-history semantics.
5. Render stale invoices only in a history section and exclude them from default selection and upgrade CTA dedupe.
6. Run focused Python + frontend gates, then review and submit.

### Test Coverage
- `test_billing_records_exclude_stale_unpaid_by_default` — primary list omits expired unpaid records.
- `test_billing_records_include_stale_unpaid_in_history_view` — explicit history includes classified records.
- `test_create_payment_request_rejects_stale_unpaid_record` — provider checkout cannot start for stale invoices.
- `api.test.ts::builds billing history requests` — frontend sends history query flag.
- `billing-page.spec.ts::keeps expired-plan CTAs when stale unpaid upgrade exists` — stale history does not suppress current renewal choices.

### Decision Completeness
- Goal: make stale unpaid invoices historical, not actionable checkout candidates.
- Non-goals: no new DB status, no automatic cancellation, no migration/backfill.
- Success criteria: normal billing view omits stale unpaid records; explicit history/admin still sees them; both renewal CTAs show; stale payment requests fail closed.
- Public interfaces: additive `is_stale_unpaid` response field and `include_stale_unpaid` billing-list query parameter.
- Failure modes: malformed/unknown dates stay on existing validation path; stale classification is derived at read time; payment request creation fails closed.
- Rollout/monitoring: no migration; watch payment-request 400s and billing summary deltas after deploy.
- Acceptance checks: focused pytest suites, frontend unit/e2e billing tests, typecheck/lint/build.

### Dependencies
Existing billing records, generated OpenAPI client artifacts, current payment provider flow.

### Validation
Exercise default list, history list, stale payment request rejection, and expired renewal UX in automated tests.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| stale classification | `BillingService.list_snapshot()` / payment creation | billing repository + service imports | `billing_records`, `billing_payments` |
| history query flag | `GET /v1/billing/records` | `apps/api/src/egp_api/routes/billing.py` | N/A |
| billing history UI | `/billing` page | `apps/web/src/app/(app)/billing/page.tsx` | N/A |

## Plan Draft B — frontend-only partition + backend payment guard

### Overview
Leave list APIs unchanged, add only a derived field plus payment-request rejection in the backend, and let the frontend split stale records into primary vs history buckets. This is smaller operationally but leaves summary totals mixing actionable and historical records.

### Files to Change
Same surface as Draft A except no route query parameter and less repository filtering.

### Implementation Steps
1. Add tests for stale classification and payment-request rejection.
2. Expose `is_stale_unpaid` on records.
3. Partition records in the billing page into primary/history buckets.
4. Keep stale rows out of selected/default/CTA logic.

### Test Coverage
- frontend partitioning behavior
- stale payment rejection
- stale classification field

### Decision Completeness
- Goal: UX correctness with fewer backend changes.
- Non-goals: no primary-summary correction.
- Success criteria: CTAs and selection fixed; stale rows visible only under history.
- Public interfaces: additive response field only.
- Failure modes: primary summary can still look inconsistent; this is the main weakness.
- Rollout/monitoring: trivial rollout, but watch UX confusion around open/outstanding counts.
- Acceptance checks: same focused tests.

### Dependencies
No extra API parameter; generated client still changes for the response field.

### Validation
Frontend E2E plus backend stale payment test.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| stale classification | list serialization | repository helper + route serializer | `billing_records`, `billing_payments` |
| UI partition | `/billing` page | component-local helpers | N/A |

## Comparative Analysis
Draft B is smaller, but it leaves a mismatch where the headline billing summary still counts records the primary list intentionally hides. Draft A is slightly broader yet cleaner: it makes “primary billing” an explicit backend concept, keeps admin/history access intentional, and lets summaries match the list users are actually asked to act on.

## Unified Execution Plan

### Overview
Use Draft A. Keep stale unpaid status derived rather than persisted, introduce an explicit history query flag, filter the normal billing snapshot and summary, preserve admin full-history behavior, and render stale records only in history while keeping upgrade CTA logic based on primary records.

### Files to Change
- `packages/db/src/egp_db/repositories/billing_models.py`
- `packages/db/src/egp_db/repositories/billing_utils.py`
- `packages/db/src/egp_db/repositories/billing_invoices.py`
- `apps/api/src/egp_api/services/billing_service.py`
- `apps/api/src/egp_api/routes/billing.py`
- `tests/phase3/test_invoice_lifecycle.py`
- `tests/phase3/test_payment_links.py`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/generated/openapi.json`
- `apps/web/src/lib/generated/api-types.ts`
- `apps/web/tests/unit/api.test.ts`
- `apps/web/src/app/(app)/billing/page.tsx`
- `apps/web/tests/e2e/billing-page.spec.ts`

### Implementation Steps
1. **RED** — add backend tests for default exclusion, history inclusion, and stale payment rejection; run them and confirm failures.
2. **RED** — add frontend unit/E2E expectations for `include_stale_unpaid=true`, history-only stale visibility, and preserved two-CTA expired renewal state; run and confirm failures.
3. Implement `is_stale_unpaid` as a read-time derived property using non-terminal status + outstanding balance + expired billing period.
4. Add `include_stale_unpaid` plumbing so the primary billing snapshot filters stale rows and summary math while history/admin can still see them.
5. Block payment-request creation when a stale unpaid record is requested.
6. Split billing page data into primary and history sources; base default selection and CTA dedupe on primary records only; render stale rows in a history panel.
7. Regenerate OpenAPI client artifacts and run focused gates.

### Test Coverage
- `test_billing_records_exclude_stale_unpaid_by_default` — excludes stale rows from primary snapshot.
- `test_billing_records_include_stale_unpaid_in_history_view` — exposes stale rows with explicit flag.
- `test_create_payment_request_rejects_stale_unpaid_record` — stale checkout creation is blocked.
- `api.test.ts` billing request test — forwards history query parameter.
- `billing-page.spec.ts` stale-history scenario — shows history only and restores both expired renewal CTAs.

### Decision Completeness
- Goal: classify stale unpaid invoices and remove them from the live billing flow without losing auditability.
- Non-goals: mutate lifecycle enums, auto-cancel invoices, or change admin triage semantics.
- Success criteria: primary billing page/summary exclude stale invoices; history/admin still expose them; stale checkout fails with a clear 400; two normal expired-renewal CTAs remain available.
- Public interfaces: additive `BillingRecordResponse.is_stale_unpaid`; additive `GET /v1/billing/records?include_stale_unpaid=true`.
- Edge cases / failure modes: partially paid expired invoices are stale if balance remains; paid/cancelled/refunded records are never stale; fail closed on payment creation; tenant scoping unchanged.
- Rollout & monitoring: backward-compatible additive API, no migration/backout required; monitor 400 rate on payment-request endpoint and stale-history counts.
- Acceptance checks: `pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py -q`, frontend unit/e2e billing tests, typecheck/lint/build.

### Dependencies
No new external dependencies; requires existing OpenAPI generation scripts.

### Validation
Confirm primary/history API contrast, UI default selection, stale history rendering, payment-request rejection, and unchanged admin access.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `is_stale_unpaid` derivation | `_detail_from_row()` + `BillingService.create_payment_request()` | repository/service imports | `billing_records`, `billing_payments` |
| primary/history list behavior | `GET /v1/billing/records` | billing router included by API app | `billing_records` |
| history UI | `/billing` React route | `apps/web/src/app/(app)/billing/page.tsx` | N/A |
| admin preservation | `GET /v1/admin` | `AdminService.get_snapshot()` | `billing_records` |

### Cross-Language Schema Verification
No migration is planned. Existing Python schema and SQL migrations already use `billing_records` and `billing_payments`; generated frontend types will be refreshed from the API contract.

### Auggie Limitation
Auggie semantic search returned HTTP 429 during planning and implementation preparation. Plan is based on direct inspection of the billing route/service/repository files, frontend billing/admin pages, and related phase 2/3/4 tests.


## Implementation Summary (2026-05-17T08:57:33+07:00)

### Goal
Classify expired unpaid upgrade invoices as historical records, keep them out of the live billing flow, preserve access through history/admin views, and stop stale records from suppressing the normal expired-renewal CTAs.

### What Changed
- `packages/db/src/egp_db/repositories/billing_models.py`, `billing_utils.py`, `billing_invoices.py`
  - added derived `is_stale_unpaid` state for expired unpaid **upgrade** invoices
  - added primary-vs-history filtering through `include_stale_unpaid`
  - made primary snapshot summaries operate on the filtered live set
- `apps/api/src/egp_api/services/billing_service.py`, `routes/billing.py`
  - added `include_stale_unpaid` request plumbing and serialized the additive response field
  - fail closed on payment-request creation for stale unpaid upgrade records
- `apps/web/src/app/(app)/billing/page.tsx`, `src/lib/api.ts`, `src/lib/hooks.ts`
  - fetched live and history snapshots separately
  - kept default selection and upgrade CTA dedupe on live records only
  - rendered stale records only in a dedicated history panel
  - skipped stale history rows in auto-refresh polling
- generated API artifacts refreshed under `apps/web/src/lib/generated/`
- tests added/updated in phase 3 backend suites plus frontend unit/E2E billing coverage

### TDD Evidence
- RED backend command:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py -q`
  - initial failure: stale rows were still listed, lacked `is_stale_unpaid`, and payment-request creation still returned `201`
- RED frontend command:
  - `npm run test:e2e -- --grep 'stale unpaid upgrades'`
  - initial failure: no history-only stale invoice section existed
- GREEN backend command:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py -q`
  - result: `36 passed`
- GREEN frontend focused commands:
  - `npm run test:unit -- --run tests/unit/api.test.ts`
  - `npm run test:e2e -- --grep 'stale unpaid upgrades'`
  - result: both passed

### Validation Run
- `./.venv/bin/ruff check apps/api packages && ./.venv/bin/python -m compileall apps packages`
- `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py tests/phase4/test_billing_repository_decomposition.py -q`
- `(cd apps/web && npm run test:unit && npm test && npm run typecheck && npm run lint && npm run build)`

### Wiring Verification Evidence
- runtime list entry point: `GET /v1/billing/records` → `BillingService.list_snapshot()` → repository `list_billing_records(... include_stale_unpaid=...)`
- runtime payment guard: `POST /v1/billing/records/{record_id}/payment-requests` → `BillingService.create_payment_request()` checks `detail.record.is_stale_unpaid`
- frontend history wiring: billing page calls `useBillingRecords({ include_stale_unpaid: true })` and renders only `record.is_stale_unpaid` rows in the history panel
- admin preservation: `AdminService.get_snapshot()` still calls repository `list_billing_records()` with its default full-history behavior

### Behavior / Risk Notes
- The classification is intentionally narrower than “period ended”: only expired unpaid upgrade invoices are stale. Ordinary overdue invoices remain live receivables and continue existing behavior.
- Payment-request creation now fails closed for stale upgrade invoices with `400 stale unpaid billing record is not payable`.
- No DB migration or lifecycle enum change was required; the field is additive and derived at read time.

### Follow-ups / Known Gaps
- No schema migration is needed, but if product later wants to retire other historical receivables classes, that should be a separate policy decision rather than piggybacking on this upgrade-specific fix.


## Review (2026-05-17T08:59:37+07:00) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main` working tree before feature branch creation
- Scope: working tree
- Commands Run: `git status --porcelain=v1`, targeted `git diff -- <paths>`, `rg -n "is_stale_unpaid|include_stale_unpaid|stale_unpaid_only" apps packages tests`, focused pytest + frontend unit/E2E/typecheck/lint gates

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No remaining findings. During review, the initial client-side history filtering approach was identified as page-window fragile because stale rows older than the first mixed page could disappear from the history panel. That was fixed before formalization by adding a server-side `stale_unpaid_only` slice and switching the UI to use it.

LOW
- No findings.

### Open Questions / Assumptions
- “Stale unpaid” is intentionally scoped to expired unpaid **upgrade** invoices, not ordinary overdue invoices; existing receivables gating depends on ordinary overdue invoices remaining live.
- Existing historical payment requests are displayed as history, but only creation of new requests is blocked here; changing settlement/callback semantics would be a separate policy decision.

### Recommended Tests / Validation
- Keep the focused backend tests for primary-vs-history listing and stale payment rejection.
- Keep the billing-page E2E scenario that proves both expired-renewal CTAs survive when stale upgrade history exists.
- Final pre-submit gates: backend ruff/compileall/pytest and full frontend unit/e2e/typecheck/lint/build.

### Rollout Notes
- Additive API surface only: `is_stale_unpaid` plus explicit history-query support.
- No migration or backfill required; classification is read-time derived.
- Watch payment-request 400s and any unexpected drop in live billing counts after release.


## Follow-up Implementation Note (2026-05-17T09:00:24+07:00)

- Tightened the history API after review: added `stale_unpaid_only` so the billing history panel requests stale records directly instead of filtering a mixed first page on the client.
- Updated backend, generated OpenAPI types, frontend wrapper, unit test, and E2E fixture accordingly.
- Re-ran final gates after this change:
  - `./.venv/bin/ruff check apps/api packages && ./.venv/bin/python -m compileall apps/api/src packages && ./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py tests/phase4/test_billing_repository_decomposition.py -q`
  - `(cd apps/web && npm run test:unit && npm test && npm run typecheck && npm run lint && npm run build)`
- Result: all green.
