# Expired billing renewal UX

## Exploration note

Auggie semantic search was attempted first but returned HTTP 429, so this plan is based on direct inspection plus exact-string searches of:
- `apps/web/src/app/(app)/billing/page.tsx`
- `apps/web/src/app/(app)/projects/[id]/page.tsx`
- `apps/web/tests/e2e/billing-page.spec.ts`
- `apps/api/src/egp_api/routes/billing.py`
- `apps/api/src/egp_api/services/billing_service.py`
- `packages/db/src/egp_db/repositories/billing_subscriptions.py`
- `packages/db/src/egp_db/repositories/billing_utils.py`
- `tests/phase3/test_invoice_lifecycle.py`

## Plan Draft A — minimal adaptive CTA change

### Overview
Keep the existing `/v1/billing/upgrades` flow and make it status-aware. The frontend will show renewal plus upgrade options when the effective subscription is expired, and the backend will accept expired paid subscriptions as renewal sources.

### Files to change
- `apps/web/src/app/(app)/billing/page.tsx` — derive expired-plan messaging and adaptive renewal/upgrade CTAs.
- `apps/web/src/app/(app)/projects/[id]/page.tsx` — add billing link for subscription-gated download failures.
- `apps/web/tests/e2e/billing-page.spec.ts` — cover expired one-time/monthly CTA behavior and expiry notice.
- `packages/db/src/egp_db/repositories/billing_subscriptions.py` — allow renewal transitions from expired paid plans.
- `tests/phase3/test_invoice_lifecycle.py` — cover accepted expired renewals and retain active downgrade guard.

### TDD sequence
1. Add backend tests for expired one-time renewal and expired monthly renewal/downgrade choice.
2. Run them and confirm current `unsupported subscription upgrade` failures.
3. Add billing-page e2e tests for expired one-time/monthly option resurfacing and expiry copy.
4. Run them and confirm missing CTA/copy failures.
5. Implement the smallest backend transition update and frontend CTA/copy update.
6. Add the project-detail billing-link behavior and verify with focused browser coverage where practical.
7. Run focused fast gates and review wiring.

### Function/test outline
- `getUpgradeOptions()` — make option selection depend on both `plan_code` and `subscription_status`.
- New helper in billing page (name TBD) — choose the latest visible subscription matching the entitlement view so the page can render expiration dates from billing records.
- `create_upgrade_billing_record()` — expand allowed transitions only for expired paid subscriptions.
- Tests:
  - `test_expired_one_time_can_request_renewal_to_one_time_search_pack` — expired one-time can renew same plan.
  - `test_expired_monthly_membership_can_request_one_time_pack` — expired monthly can choose one-time.
  - `billing page resurfaces one-time renewal after expiry` — one-time + monthly CTAs both visible.
  - `billing page resurfaces paid choices after monthly expiry` — one-time + monthly CTAs both visible.

### Decision completeness
- Goal: expired paid users can understand expiry and immediately renew or choose another paid plan.
- Non-goals: changing payment provider behavior, adding new schema, adding download audit logging.
- Success criteria: expired one-time shows its end date plus one-time/monthly CTAs; expired monthly shows one-time/monthly CTAs; active one-time still only shows monthly; active monthly still shows no LHS purchase CTAs; project download denial links to billing.
- Public interfaces: existing `/v1/billing/upgrades` accepts additional expired-source transitions; no new endpoint/schema/env var.
- Failure modes: active monthly downgrade remains blocked (fail closed); pending duplicate renewal remains filtered; no matching billing record means no date callout rather than guessing.
- Rollout/backout: frontend/backend deploy together; rollback is code-only.
- Acceptance checks: focused pytest + web e2e/typecheck.

### Wiring verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Expired renewal transition | `POST /v1/billing/upgrades` | existing billing router/service/repository path | existing `billing_subscriptions`, `billing_records` |
| Adaptive billing CTAs | `/billing` page render | existing `BillingPage -> UpgradeCallout` | N/A |
| Download-denial billing link | `/projects/[id]` download error render | existing project detail page | N/A |

## Plan Draft B — richer billing API contract

### Overview
Add `current_subscription` to the billing records API so the frontend never reconstructs plan state from entitlement plus record history. The UI would use that canonical API object for expiration display and CTA selection.

### Files to change
- All Draft A files plus billing response schemas, route serializer, generated web types/tests.

### Trade-offs
This is architecturally cleaner for the frontend but widens the API contract and duplicates information already available through rules entitlements plus record payloads. It is more work than the user-visible change requires and adds generated-contract churn without solving a current correctness gap.

### Decision completeness
- Goal/non-goals/success criteria are the same as Draft A.
- Public interfaces: would add `current_subscription` to `/v1/billing/records` response.
- Failure modes: better resilience if the expired source record falls outside pagination; more contract migration risk.
- Rollout/backout: API and generated-client changes must ship together.

### Wiring verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Billing current-subscription response | `GET /v1/billing/records` | billing route serializer | existing billing tables |
| Adaptive billing CTAs | `/billing` page render | `BillingPage -> UpgradeCallout` | N/A |
| Download-denial billing link | `/projects/[id]` | existing project detail page | N/A |

## Comparative analysis
Draft A is smaller, keeps existing contracts stable, and directly addresses the requested UX. Draft B is more canonical but adds avoidable surface area right now. The only meaningful weakness in Draft A is that the expiry-date callout depends on the visible record list; given the current 50-record default and tiny billing history per tenant, that is acceptable for this slice and fails safely by omitting the date rather than misrepresenting it.

## Unified execution plan

### Overview
Implement Draft A, but keep the helper boundaries clean so the UI can later consume a first-class `current_subscription` field if the billing API grows one. The fix will make expired paid plans actionable without weakening active-plan upgrade restrictions.

### Files to change
- `packages/db/src/egp_db/repositories/billing_subscriptions.py`
- `tests/phase3/test_invoice_lifecycle.py`
- `apps/web/src/app/(app)/billing/page.tsx`
- `apps/web/tests/e2e/billing-page.spec.ts`
- `apps/web/src/app/(app)/projects/[id]/page.tsx`

### Implementation steps
1. RED: add backend tests proving expired one-time may renew same plan, expired monthly may choose one-time, and active monthly downgrade stays blocked.
2. GREEN: expand `create_upgrade_billing_record()` transition policy by status: active one-time -> monthly only; expired free trial/one-time/monthly -> one-time or monthly where commercially valid; active monthly still no downgrade.
3. RED: add billing-page e2e tests for expired one-time and expired monthly cards/options.
4. GREEN: update `getUpgradeOptions()` to use effective status; add a small helper to locate the currently relevant subscription record and render expiry messaging; adjust titles/copy from pure “upgrade” to “renew or upgrade” when expired.
5. Add project-detail billing CTA for subscription-gated document-download failures.
6. Run focused tests, typecheck, and skeptical review.

### Test coverage
- `test_expired_one_time_can_request_renewal_to_one_time_search_pack` — same-plan renewal allowed after expiry.
- `test_expired_monthly_membership_can_request_one_time_search_pack` — expired monthly can re-enter via cheaper paid plan.
- Existing `test_monthly_membership_cannot_downgrade_via_upgrade_api` — active monthly still protected.
- `billing page shows expired one-time renewal options` — date plus one-time/monthly CTAs visible.
- `billing page shows paid choices after monthly expiry` — both paid choices visible again.
- Project-detail browser assertion (if added in existing suite) — denied download includes billing link.

### Decision completeness
- Goal: expired users are told what expired and can immediately pay again from the billing page.
- Non-goals: no schema change, no download audit trail, no new payment rails.
- Success criteria: tests above pass; active-state behavior remains unchanged; billing link routes to `/billing`.
- Public interfaces: existing upgrade endpoint accepts new expired-source transitions; UI copy changes only.
- Edge cases: pending duplicate target records remain hidden; active monthly downgrade fails closed; if record history lacks the matching subscription, the page still shows CTAs but omits exact date copy.
- Rollout/monitoring: code-only rollout; watch failed upgrade creations and support reports about expired-plan confusion.
- Acceptance checks: `pytest tests/phase3/test_invoice_lifecycle.py -q`; `cd apps/web && npm test -- --grep ...` or focused Playwright command; `npm run typecheck`.

### Dependencies
Existing billing/rules APIs, Playwright test harness, no migrations.

### Validation
- Confirm API creates renewal billing records for expired one-time/monthly sources.
- Confirm `/billing` LHS responds to expired entitlements with the right options and date copy.
- Confirm project-detail entitlement failure offers a path back to billing.

### Wiring verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| Expired renewal rules | `BillingService.create_upgrade_record()` via `POST /v1/billing/upgrades` | `apps/api/src/egp_api/routes/billing.py` -> repository | `billing_subscriptions`, `billing_records` |
| Billing CTA selection | `BillingPage` render | `UpgradeCallout` inside billing page | N/A |
| Expiry callout | `BillingPage` render | same page, sourced from `records` + `rulesData.entitlements` | N/A |
| Billing link on download denial | project detail download error banner | existing `handleDownload()`/render path | N/A |

### Cross-language schema verification
No migration required. Existing Python table names confirmed: `billing_subscriptions`, `billing_records`.

### Decision-complete checklist
- No open decisions remain for implementation.
- All changed public behavior is listed.
- Each behavior change has tests.
- Validation commands are scoped.
- Wiring table covers all changed runtime paths.
- Rollout/backout is code-only and documented.


## Implementation Summary (2026-05-16 18:48:02)

### Goal
Make expired paid plans actionable: explain the expiry, route blocked downloads back to billing, and resurface the correct left-hand renewal/upgrade choices after expiry.

### What changed
- `packages/db/src/egp_db/repositories/billing_subscriptions.py`
  - Split upgrade transitions into active/pending vs expired policies.
  - Expired `one_time_search_pack` can renew itself or move to monthly; expired `monthly_membership` can renew monthly or re-enter via one-time.
  - Active monthly still cannot downgrade mid-cycle.
- `apps/web/src/app/(app)/billing/page.tsx`
  - Made CTA generation status-aware.
  - Added an expiry callout that shows the matched expired plan and its end date.
  - Reworded expired-state CTAs as renew/change actions instead of only upgrades.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`
  - Added billing-aware download-denial handling.
  - When rules say the plan is expired, the banner now states that the named plan expired and links to `/billing`.
- Tests added/updated:
  - `tests/phase3/test_invoice_lifecycle.py`
  - `apps/web/tests/e2e/billing-page.spec.ts`
  - `apps/web/tests/e2e/projects-page.spec.ts`

### TDD evidence
- RED backend command:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -q`
  - Failed because expired one-time/monthly transitions still returned `400 unsupported subscription upgrade`.
- RED frontend command:
  - `npm test -- --grep "billing page resurfaces paid options|project detail links expired"`
  - Failed because the expiry callout, renewed CTAs, and billing link did not exist yet.
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -q` → passed
  - `npm test -- --grep "billing page resurfaces paid options|project detail links expired"` → passed
  - `npm test -- --grep "billing page shows one-time upgrade CTA only for monthly membership|billing page hides upgrade CTA for monthly membership|billing page resurfaces paid options|project detail links expired"` → passed
  - `npm test -- --grep "project detail links expired"` → passed after the more specific expired-copy refinement

### Validation run
- `./.venv/bin/ruff check packages/db/src/egp_db/repositories/billing_subscriptions.py tests/phase3/test_invoice_lifecycle.py` → passed
- `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py -q` → passed
- `cd apps/web && npm run typecheck` → passed
- `cd apps/web && npm run test:unit` → passed
- `cd apps/web && npm run lint` → passed

### Wiring verification
- Expired-plan renewal still flows through the existing runtime path:
  - `POST /v1/billing/upgrades` → `BillingService.create_upgrade_record()` → `BillingSubscriptionMixin.create_upgrade_billing_record()`.
- Billing-page expiry UI is live through the existing `/billing` render path:
  - `BillingPage` → `UpgradeCallout` + `getCurrentSubscriptionFromRecords()`.
- Download denial UX is live through the existing project-detail path:
  - `handleDownload()` → banner render → `/billing` `Link`.

### Behavior and risk notes
- Fail-closed behavior remains for active monthly subscribers: no mid-cycle downgrade was opened.
- If the relevant subscription is absent from the fetched billing-record page, the page still shows paid CTAs but omits the exact expiry-date callout rather than guessing.
- Existing product behavior still allows a different CTA to remain visible when another upgrade is already pending, while the backend accepts only one in-flight upgrade per source subscription; that pre-existing mismatch was not widened in this change.

### Follow-ups / known gaps
- If billing history grows beyond the current records page, consider exposing `current_subscription` directly from the billing API instead of reconstructing the visible expiry card from fetched records.


## Review (2026-05-16 18:48:21) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at `e480dea1`
- Commands Run: `git diff --name-only`, `git diff --stat`, targeted `git diff -- <paths>`, `pytest tests/phase3/test_invoice_lifecycle.py -q`, `pytest tests/phase4/test_entitlements.py -q`, `ruff check ...`, targeted Playwright runs, `npm run typecheck`, `npm run test:unit`, `npm run lint`
- Note: Auggie semantic search was attempted for review context but returned HTTP 429, so review used direct diff inspection plus exact-file inspection.

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No new findings introduced by this change.

LOW
- No new findings introduced by this change.

### Open Questions / Assumptions
- The billing page still reconstructs the expiry card from the fetched billing-record page. This is acceptable for the current small billing history, but if record history becomes large enough to paginate out the relevant subscription, a first-class API field would be safer.
- Pre-existing behavior remains: the UI can still show a second target plan while another upgrade is already pending, but the backend allows only one open upgrade per source subscription. This change does not worsen that mismatch, but it is worth revisiting separately if support sees confusion around switching targets mid-payment.

### Recommended Tests / Validation
- Keep the newly added expired one-time/monthly renewal tests in the backend suite.
- Keep the expired-plan billing-page and project-detail browser tests because they guard the exact user-facing regression discussed here.

### Rollout Notes
- Code-only rollout; no migration or config changes.
- Watch upgrade-creation 400s and support tickets from expired subscribers after deploy to confirm the new renewal path is being used as intended.
