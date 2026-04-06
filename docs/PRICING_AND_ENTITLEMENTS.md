# Pricing And Entitlements

## Current Implemented Plans

Source of truth today:
- `packages/shared-types/src/egp_shared_types/billing_plans.py`

Currently implemented in code:

| Plan Code | Label | Price | Interval | Duration | Keyword Limit | Implemented |
|-----------|-------|-------|----------|----------|---------------|-------------|
| `free_trial` | Free Trial | `0.00 THB` | `trial` | `7 days` | `1` | Yes |
| `one_time_search_pack` | One-Time Search Pack | `300.00 THB` | `one_time` | `3 days` | `1` | Yes |
| `monthly_membership` | Monthly Membership | `1500.00 THB` | `monthly` | `1 month` | `5` | Yes |

## Implemented Trial Plan

| Plan Code | Label | Price | Interval | Duration | Keyword Limit | Goal |
|-----------|-------|-------|----------|----------|---------------|------|
| `free_trial` | Free Trial | `0.00 THB` | `trial` | `7 days` | `1` | Let new tenants experience real crawl value before paying |

Recommended description:
- `Try 1 active keyword for 7 days`

## Recommended Entitlement Matrix

| Capability | Free Trial | One-Time Search Pack | Monthly Membership |
|------------|------------|----------------------|--------------------|
| Active keyword limit | 1 | 1 | 5 |
| Runs allowed | Yes | Yes | Yes |
| Dashboard and project list | Yes | Yes | Yes |
| Runs page | Yes | Yes | Yes |
| Rules page / entitlement snapshot | Yes | Yes | Yes |
| Document metadata view | Yes | Yes | Yes |
| Document download | No | Yes | Yes |
| Exports | No | Yes | Yes |
| Notifications (in-app/email) | No | Yes | Yes |
| Webhooks | No | Optional No | Yes |
| Admin billing visibility | Yes | Yes | Yes |

Recommended product rule:
- `free_trial` should expose real crawler value but withhold export/download/automation features that are strong monetization levers.

## Why This Shape

### Free Trial
- Must be useful enough to demonstrate real product value.
- Must be weaker than paid plans.
- `1 keyword / 7 days` is long enough to observe actual procurement activity without replacing a paid plan.

### One-Time Search Pack
- Serves short, tactical needs.
- Should remain the smallest paid option.
- Clear upgrade from free trial because it adds paid operational outputs like export/download.

### Monthly Membership
- Full recurring plan.
- Highest keyword limit.
- Best fit for ongoing procurement monitoring.

## Recommended Commercial Rules

1. One trial per tenant.
2. Trial should require account creation and verified owner identity.
3. Trial should not stack with another active trial.
4. Upgrading from trial should preserve:
   - tenant
   - users
   - profiles/keywords
   - runs/projects/documents history
5. Trial expiry should immediately disable paid-only capabilities and active-run creation.

## Recommended Runtime Semantics

### Billing Record
- `free_trial` is implemented as a dedicated trial activation path that creates a real subscription without using the standard positive-amount invoice/payment flow.
- It does not require PromptPay or bank transfer.
- `free_trial` now uses a true `0.00` billing record, while payment requests and payments remain strictly positive.

### Subscription Activation
- `free_trial` creates a real `billing_subscriptions` row with:
  - `plan_code = free_trial`
  - `status = active`
  - `keyword_limit = 1`
  - `billing_period_end = start + 6 days`

### Rules / Entitlements
- `plan_label` should render `Free Trial`.
- `runs_allowed` should be `true` while active.
- `exports_allowed` should be `false`.
- `document_download_allowed` should be `false`.
- `notifications_allowed` should be `false` unless the business decides basic email should be allowed.

## Implementation Plan For `free_trial`

This plan assumes the goal is to add a real first-class plan, not just a seeded custom subscription.

### Goal
- Add `free_trial` as a real billing/entitlement plan that new tenants can activate and that the UI can display correctly.

### Non-Goals
- Full marketing/public landing page implementation.
- Full self-serve checkout and tenant signup in the same change.
- Complex anti-abuse logic such as domain-level or payment-fingerprint deduplication.

### Decision Summary
- Add `free_trial` as a normal plan definition in shared plan metadata.
- Keep it as a real subscription-backed entitlement, not a hidden special case.
- Gate paid-only capabilities in the entitlement service based on plan code.
- Make trial activation a zero-payment path rather than forcing fake payments.

### Files Changed / To Change

#### Shared Plan Definitions
- `packages/shared-types/src/egp_shared_types/billing_plans.py`
  - add `free_trial`
  - `amount_due = 0.00`
  - `billing_interval = trial`
  - `keyword_limit = 1`
  - `duration_days = 7`

#### API Billing Service / Routes
- `apps/api/src/egp_api/services/billing_service.py`
  - add or expose a trial activation path that does not require payment request generation
- `apps/api/src/egp_api/routes/billing.py`
  - add a dedicated trial-start route for owner/admin activation

#### Repository / Persistence
- `packages/db/src/egp_db/repositories/billing_repo.py`
  - add a clean activation path that creates `billing_subscriptions` without requiring a payment row when appropriate

#### Entitlements
- `apps/api/src/egp_api/services/entitlement_service.py`
  - keep current subscription selection behavior
  - add plan-sensitive capability flags so `free_trial` differs from paid plans:
    - `runs_allowed = true`
    - `exports_allowed = false`
    - `document_download_allowed = false`
    - `notifications_allowed = false`
  - preserve keyword-limit enforcement from subscription metadata

#### Web UI
- `apps/web/src/app/(app)/billing/page.tsx`
  - show `Free Trial` in the plan list
  - show `0.00 THB`
  - clarify that it activates a 7-day limited experience
- `apps/web/src/lib/api.ts`
  - no schema change required if the existing billing plans response already carries plan metadata
- `apps/web/src/app/(app)/rules/page.tsx`
  - ensure `Free Trial` label and capability messaging render clearly

#### Tests
- `tests/phase4/test_entitlements.py`
  - active `free_trial` returns the expected capability matrix
  - expired `free_trial` disables access
- `tests/phase2/test_rules_api.py`
  - rules endpoint shows `plan_code = free_trial` and `plan_label = Free Trial`
- `tests/phase3/test_payment_links.py`
  - ensure trial records do not incorrectly require payment request generation if trial uses a paymentless activation path
- `tests/phase4/test_admin_api.py`
  - ensure billing/admin flows can list/create/display the new plan

### Key Product/Engineering Decisions To Lock Down

1. **Activation path**
   - Best recommendation: allow zero-payment direct activation for `free_trial`.
   - Avoid forcing fake `paid` billing transitions through PromptPay.

2. **Capability gating model**
   - Current entitlement logic mostly treats any active subscription as fully allowed.
   - `free_trial` requires plan-sensitive gating, so this is the most important behavioral change.

3. **Abuse control**
   - Minimum safe rule: one trial per tenant.
   - Deeper anti-abuse can come later.

4. **Upgrade semantics**
   - Upgrading from `free_trial` to paid should not require a new tenant.
   - Existing profiles, keywords, runs, and discovered projects should remain.

### TDD Sequence

1. Add failing shared-plan-definition test coverage for `free_trial` metadata.
2. Add failing entitlement tests proving active trial is limited vs paid plans.
3. Add failing billing/repository tests for zero-payment activation behavior.
4. Implement the smallest passing backend changes.
5. Add/update web UI tests if present; otherwise verify with targeted component/page assertions where available.
6. Run relevant API + rules + entitlements + billing tests.

### Validation Commands

Backend-focused:
- `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py tests/phase2/test_rules_api.py tests/phase4/test_admin_api.py tests/phase3/test_payment_links.py -q`
- `./.venv/bin/ruff check apps/api packages tests`
- `./.venv/bin/python -m compileall apps/api/src packages`

Frontend-focused:
- `cd apps/web && npm run typecheck`
- `cd apps/web && npm run build`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `free_trial` plan metadata | billing APIs and activation logic | `packages/shared-types/src/egp_shared_types/billing_plans.py` | N/A |
| zero-payment trial activation | billing route/service | `apps/api/src/egp_api/routes/billing.py`, `apps/api/src/egp_api/services/billing_service.py` | `billing_records`, `billing_subscriptions` |
| trial capability gating | rules/export/document/run checks | `apps/api/src/egp_api/services/entitlement_service.py` | `billing_subscriptions`, crawl profiles |
| web display of trial plan | billing/rules pages | `apps/web/src/app/(app)/billing/page.tsx`, `apps/web/src/app/(app)/rules/page.tsx` | N/A |

### Risks

1. Zero-price billing records are now allowed, so any future billing reporting logic must continue distinguishing payable invoices from informational zero-price trial records.
2. Current entitlement logic was originally subscription-status based; plan-sensitive capability gating is now a core policy path that must stay covered by tests.
3. UI wording must clearly distinguish `free_trial` from `one_time_search_pack` or customers will not understand why they should pay.

### Recommended Minimal Implementation Slice

If you want the smallest first release of trial support, do this in phase 1:
1. add `free_trial` to shared plan definitions
2. add zero-payment direct subscription activation for admins/new tenant bootstrap
3. add plan-sensitive entitlement gating
4. display it in web billing/rules UI

Then in phase 2:
1. add self-serve trial start route
2. add landing page + signup funnel
3. add upgrade flow from trial to paid
