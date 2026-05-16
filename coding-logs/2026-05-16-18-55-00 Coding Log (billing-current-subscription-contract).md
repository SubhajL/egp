# Billing current subscription contract

## Exploration note

Auggie semantic search was attempted first but returned HTTP 429. Planning is based on direct inspection plus exact-string searches of:
- `packages/db/src/egp_db/repositories/billing_models.py`
- `packages/db/src/egp_db/repositories/billing_invoices.py`
- `packages/db/src/egp_db/repositories/billing_subscriptions.py`
- `apps/api/src/egp_api/routes/billing.py`
- `apps/api/src/egp_api/services/billing_service.py`
- `apps/web/src/app/(app)/billing/page.tsx`
- `apps/web/src/lib/api.ts`
- `apps/web/src/lib/generated/openapi.json`
- `apps/web/src/lib/generated/api-types.ts`
- `apps/web/tests/unit/api.test.ts`
- `apps/web/tests/unit/generated-api-types.test.ts`

## Plan Draft A — add current_subscription to existing billing list response

### Overview
Extend the existing `/v1/billing/records` response with `current_subscription`, sourced from the billing repository’s effective-subscription selector. Switch the billing page to consume that field directly and delete the client-side reconstruction helper.

### Files to change
- `packages/db/src/egp_db/repositories/billing_models.py`
- `packages/db/src/egp_db/repositories/billing_invoices.py`
- `apps/api/src/egp_api/routes/billing.py`
- billing API tests / frontend unit fixtures / generated API artifacts
- `apps/web/src/app/(app)/billing/page.tsx`

### TDD sequence
1. Add API-level test that `/v1/billing/records` returns an effective expired `current_subscription` even when the relevant source record is outside the requested page.
2. Run RED and confirm the response lacks the field.
3. Add frontend contract/type tests requiring `current_subscription` in `BillingListResponse`.
4. Run RED and confirm generated types/fixtures fail.
5. Implement repository + serializer + web page change.
6. Regenerate OpenAPI artifacts and run focused validation.

### Decision completeness
- Goal: make billing’s current subscription canonical and pagination-independent.
- Non-goals: no new endpoint, no schema migration, no entitlement redesign.
- Success criteria: API always returns effective current subscription; UI expiry card uses that field; old helper removed.
- Public interfaces: add nullable `current_subscription` to `GET /v1/billing/records` response.
- Failure modes: no subscription returns `null`; current subscription remains effective-status-derived; UI should still render without a current subscription.
- Rollout: additive API change, backward-compatible for tolerant clients.

### Wiring verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `current_subscription` billing field | `GET /v1/billing/records` | existing billing route serializer | existing `billing_subscriptions` |
| billing-page expiry card | `/billing` page render | existing `BillingPage` | N/A |

## Plan Draft B — create a dedicated billing overview endpoint

### Overview
Add a new endpoint such as `/v1/billing/overview` containing summary + current subscription, keeping `/records` purely paginated history.

### Trade-offs
This is conceptually clean, but it forces another request and a broader client hook change for little gain. The current endpoint already represents a billing snapshot, so the additive field is simpler and still coherent.

### Decision completeness
- Goal/non-goals/success criteria are equivalent.
- Public interfaces: new endpoint instead of an additive response field.
- Rollout: more wiring, more round trips, no material product advantage today.

### Wiring verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| new billing overview endpoint | `GET /v1/billing/overview` | new billing route | existing billing tables |
| billing page | `/billing` | new hook + page render | N/A |

## Comparative analysis
Draft A is the right fit: additive, canonical enough, and directly solves the pagination leak. Draft B is tidier in the abstract but introduces unnecessary moving parts.

## Unified execution plan

### Overview
Implement Draft A. `/v1/billing/records` becomes a true billing snapshot: paginated record history plus one authoritative `current_subscription` field.

### Files to change
- `packages/db/src/egp_db/repositories/billing_models.py`
- `packages/db/src/egp_db/repositories/billing_invoices.py`
- `apps/api/src/egp_api/routes/billing.py`
- `tests/phase3/test_invoice_lifecycle.py`
- generated API artifacts in `apps/web/src/lib/generated/`
- `apps/web/tests/unit/api.test.ts`
- `apps/web/tests/unit/generated-api-types.test.ts`
- `apps/web/tests/e2e/billing-page.spec.ts`
- `apps/web/src/app/(app)/billing/page.tsx`

### Implementation steps
1. RED: add billing API regression covering paginated history + current subscription.
2. GREEN: add `current_subscription` to `BillingPage`, populate it with `get_effective_subscription_for_tenant()`, and serialize it in `BillingListResponse`.
3. RED: update frontend fixtures/tests so the contract requires the new field.
4. GREEN: regenerate OpenAPI artifacts and switch the billing page to `data?.current_subscription`.
5. Remove `getCurrentSubscriptionFromRecords()` entirely.
6. Run focused backend/frontend validation and review.

### Test coverage
- `test_billing_records_include_effective_current_subscription_outside_page_window` — paginated records still expose current subscription.
- Existing expired billing-page tests — expiry card remains visible from canonical field.
- API/generated type tests — response contract includes `current_subscription`.

### Decision completeness
- Goal: canonical billing current-subscription contract.
- Non-goals: no new endpoint, no migration, no removal of records pagination.
- Public interfaces: `BillingListResponse.current_subscription: BillingSubscriptionResponse | null`.
- Edge cases: no subscription => null; effective expired subscription remains returned; paginated records can exclude the source record without hiding current subscription.
- Rollout/backout: additive field; rollback is code-only.
- Validation: pytest, web unit/type/e2e, OpenAPI generation checks.

### Dependencies
Existing billing repository selector and OpenAPI generation scripts.

### Wiring verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| `BillingPage.current_subscription` model field | repository return from `list_billing_records()` | existing repository call path | `billing_subscriptions` |
| `BillingListResponse.current_subscription` | `GET /v1/billing/records` | `_serialize_page()` | N/A |
| Billing page authoritative read | `/billing` page render | existing `useBillingRecords()` hook | N/A |

### Cross-language schema verification
No migration required. Existing source of truth remains `billing_subscriptions`.

### Decision-complete checklist
- No open implementation decisions remain.
- Public contract change named explicitly.
- Every behavior change has a test.
- Validation commands are concrete.
- Wiring table covers model, route, and UI usage.


## Implementation Summary (2026-05-16 18:55:05)

### Goal
Replace client-side reconstruction of the billing expiry source with a first-class, pagination-independent `current_subscription` field on the billing API.

### What changed
- `packages/db/src/egp_db/repositories/billing_models.py`
  - Added `current_subscription` to `BillingPage`.
- `packages/db/src/egp_db/repositories/billing_invoices.py`
  - `list_billing_records()` now always includes the effective current subscription alongside paginated record rows.
- `apps/api/src/egp_api/routes/billing.py`
  - Added nullable `current_subscription` to `BillingListResponse` and serialized it with the existing subscription serializer.
- `apps/web/src/app/(app)/billing/page.tsx`
  - Removed the record-scanning helper and now reads `data?.current_subscription` directly.
- API/client contract updates:
  - regenerated `apps/web/src/lib/generated/openapi.json`
  - regenerated `apps/web/src/lib/generated/api-types.ts`
  - updated unit and e2e fixtures to include `current_subscription`.

### TDD evidence
- RED backend command:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -q`
  - Failed with `KeyError: 'current_subscription'` in `test_billing_records_include_effective_current_subscription_outside_page_window`.
- RED frontend command:
  - `cd apps/web && npm run typecheck`
  - Failed because generated `BillingListResponse` did not yet contain `current_subscription`.
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -q` → passed
  - `cd apps/web && npm run generate:openapi && npm run generate:api-types` → regenerated contract artifacts
  - `cd apps/web && npm run typecheck` → passed

### Validation run
- `cd apps/web && npm run test:unit` → passed
- `cd apps/web && npm run check:api-types` → passed
- `cd apps/web && npm test -- --grep "billing page shows one-time upgrade CTA only for monthly membership|billing page hides upgrade CTA for monthly membership|billing page resurfaces paid options|project detail links expired"` → passed
- `./.venv/bin/ruff check apps/api/src/egp_api/routes/billing.py packages/db/src/egp_db/repositories/billing_models.py packages/db/src/egp_db/repositories/billing_invoices.py tests/phase3/test_invoice_lifecycle.py` → passed
- `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py -q` → passed

### Wiring verification
- Repository source: `SqlBillingRepository.list_billing_records()` now calls `get_effective_subscription_for_tenant()` and packages that into `BillingPage.current_subscription`.
- API source: `GET /v1/billing/records` returns the field through `_serialize_page()`.
- UI source: `BillingPage` reads `data?.current_subscription` directly; no record-page reconstruction remains.

### Behavior and risk notes
- The change is additive and backward-compatible at the HTTP level.
- It removes the hidden dependency on the current subscription’s record being present in the currently fetched page.
- No database migration was required; effective status derivation still happens in the existing subscription repository logic.

### Follow-ups / known gaps
- None required for the requested behavior.


## Review (2026-05-16 18:55:29) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at `e480dea1`
- Commands Run: targeted `git diff --stat`, focused pytest/vitest/playwright/typecheck/ruff commands, OpenAPI generation and `check:api-types`
- Note: Auggie semantic review lookup returned HTTP 429, so review used direct diff inspection and related-file checks.

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
- `current_subscription` is intentionally nullable and represents the repository’s effective subscription selector, matching the existing admin snapshot semantics.

### Recommended Tests / Validation
- Keep `test_billing_records_include_effective_current_subscription_outside_page_window`; it is the regression guard for the original pagination weakness.
- Keep OpenAPI contract checks in the normal frontend gate whenever billing response models change.

### Rollout Notes
- Additive response field only; no migration or config sequencing required.
- Generated client artifacts were updated in the same change, so frontend and backend stay in lockstep.
