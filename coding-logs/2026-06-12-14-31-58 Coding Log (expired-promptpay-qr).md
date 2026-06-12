# Expired PromptPay QR

## Plan Draft A - Inline Frontend Fix

### Overview
Fix the billing page so a payment request with `status === "pending"` but an `expires_at` in the past is treated as expired by the UI. The page should hide the stale QR as usable, stop live polling, and make regeneration via `สร้าง QR ใหม่` the primary action.

### Files to Change
- `apps/web/src/app/(app)/billing/page.tsx`: derive active-vs-expired payment request state and adjust button/panel rendering.
- `apps/web/tests/e2e/billing-page.spec.ts`: add browser regression for pending-but-expired QR behavior.

### Implementation Steps
1. Add/stub expiry logic near the billing page.
2. Add a failing browser regression with an expired pending request.
3. Implement the smallest rendering and polling changes.
4. Refactor only if the logic gets reused in multiple branches.
5. Run focused Playwright, unit tests if touched, typecheck, lint, and build.

### Decision Completeness
- Goal: expired pending QR requests are no longer presented as live payment actions.
- Non-goals: backend expiry state mutation, LINE OA configuration automation, schema/API changes.
- Success criteria: expired pending request shows `สร้าง QR ใหม่`; QR/payment/LINE actions are hidden or explicitly expired; future pending request behavior remains.
- Public interfaces: no API, env var, CLI, migration, or schema change.
- Edge cases: invalid expiry fails open as not expired to avoid hiding valid provider data; null expiry remains usable for providers that omit it; paid/settled requests remain visible historically.
- Rollout: frontend-only deploy; backout is revert of the UI helper and render checks.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Billing page expiry branch | `/billing` page render | Next app route `src/app/(app)/billing/page.tsx` | Existing OpenAPI `BillingPaymentRequest.expires_at` |

## Plan Draft B - Shared Helper Fix

### Overview
Extract billing payment request lifecycle logic into a shared frontend helper under `src/lib/`, then consume it from the billing page and hook polling logic. This gives unit-level coverage for expiry boundaries and keeps rendering branches thin.

### Files to Change
- `apps/web/src/lib/billing-payment-requests.ts`: new helper for expired/usable pending payment requests.
- `apps/web/tests/unit/billing-payment-requests.test.ts`: helper regression coverage.
- `apps/web/src/lib/hooks.ts`: stop auto-refreshing expired pending requests.
- `apps/web/src/app/(app)/billing/page.tsx`: use helper for QR panel/action decisions.
- `apps/web/tests/e2e/billing-page.spec.ts`: browser regression if cheap after helper tests.

### Implementation Steps
1. Add a stub helper exported from `src/lib/billing-payment-requests.ts`.
2. Add failing unit tests for future, past, null, invalid, and non-pending requests.
3. Implement helper.
4. Wire helper into billing page and billing auto-refresh.
5. Add focused e2e coverage for the user-visible expired QR action.
6. Run frontend gates.

### Decision Completeness
- Goal: one reusable source of truth for payment-request expiry behavior.
- Non-goals: backend cleanup job, provider callback semantics, LINE rich menu deployment.
- Success criteria: helper tests fail before implementation and pass after; billing page uses helper for polling and QR render.
- Public interfaces: no API, env var, CLI, migration, or schema change.
- Edge cases: fail closed for expired pending requests; fail open for missing/invalid timestamps to avoid blocking provider oddities.
- Rollout: frontend-only; monitor support reports around QR regeneration and admin slip matches.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `billing-payment-requests.ts` | `BillingPage` render and `shouldAutoRefreshBilling` | imports in `page.tsx` and `hooks.ts` | Existing OpenAPI `BillingPaymentRequest.expires_at` |

## Unified Execution Plan

### Overview
Use Draft B. A small shared helper is the safer implementation because the stale QR bug exists in both rendering and polling semantics: the page displays the QR and `useBillingRecords` keeps polling any pending request.

### Files to Change
- `apps/web/src/lib/billing-payment-requests.ts`: lifecycle helpers.
- `apps/web/tests/unit/billing-payment-requests.test.ts`: TDD coverage for expiry decisions.
- `apps/web/src/lib/hooks.ts`: poll only usable pending requests.
- `apps/web/src/app/(app)/billing/page.tsx`: primary regeneration button and expired QR panel behavior.
- `apps/web/tests/e2e/billing-page.spec.ts`: user-visible regression.

### TDD Sequence
1. Add helper tests and run them RED.
2. Implement helper and run unit tests GREEN.
3. Wire helper into hooks/page.
4. Add focused Playwright regression and run it RED/GREEN if the mock supports it.
5. Run `npm run test:unit`, focused Playwright, `npm run typecheck`, `npm run lint`, and `npm run build`.

### Test Coverage
- `detects pending requests expired at or before now`: expired QR rule.
- `keeps future pending requests usable`: preserves current live QR behavior.
- `does not expire non-pending requests`: history display remains.
- `treats missing or invalid expiry as not expired`: conservative provider compatibility.
- `billing page makes expired PromptPay QR regeneration primary`: visible action changes.

### Decision Completeness
- Goal: expired pending PromptPay QR requests are not usable in UI, and regeneration is obvious.
- Non-goals: LINE OA setting changes, rich menu auto-deploy, backend request expiry migration.
- Success criteria: stale QR panel no longer exposes QR/payment URL/LINE CTA; `สร้าง QR ใหม่` appears; no live polling for expired pending.
- Public interfaces: no API/endpoints/schemas/env vars/CLI/migrations.
- Edge cases/failure modes: expired pending fails closed to regeneration; missing/invalid expiry fails open; stale unpaid records still cannot regenerate; card requests also stop being treated as live if expired.
- Rollout/monitoring: frontend deploy only; watch customer reports and admin slip queue for unmatched references.
- Acceptance checks: frontend unit/e2e/typecheck/lint/build; g-check before commit.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `isPaymentRequestExpired` | `BillingPage`, `shouldAutoRefreshBilling` | TypeScript imports | Existing `expires_at` response field |
| Expired QR render branch | `/billing` browser route | Next app route file | N/A |

### Notes
- Auggie semantic search failed with `HTTP error: 402`; plan is based on direct file inspection plus exact-string searches.
- LINE diagnosis is confirmed as operational/configuration-facing from code inspection: app webhook is `/v1/integrations/line/webhook`, `EGP_LINE_*` envs are read by API config, and rich menu deployment is a standalone script.

## Implementation (2026-06-12 14:38 +07)

### Goal
Expired pending PromptPay requests should stop appearing as usable QR actions, and regeneration should become the primary user action.

### What Changed
- `apps/web/src/lib/billing-payment-requests.ts`: added lifecycle helpers for pending payment-request expiry and usable pending state.
- `apps/web/src/lib/hooks.ts`: billing auto-refresh now polls only pending requests that are not expired.
- `apps/web/src/app/(app)/billing/page.tsx`: expired pending requests clear rendered QR state, stop live polling copy, hide QR/payment/LINE actions, show an expired notice, and relabel the primary action to `สร้าง QR ใหม่`.
- `apps/web/src/app/(app)/billing/page.tsx`: direct PromptPay generation/regeneration now reuses the existing PromptPay helper so `promptpay_manual` requests get the same 1440-minute expiry window as auto-created upgrade QR requests.
- `apps/web/tests/unit/billing-payment-requests.test.ts`: added expiry boundary tests.
- `apps/web/tests/e2e/billing-page.spec.ts`: added expired PromptPay QR regression and mocked payment config so billing tests exercise the configured manual PromptPay path.

### TDD Evidence
- RED: `npm run test:unit -- billing-payment-requests` failed with `Error: Not implemented` from `src/lib/billing-payment-requests.ts`.
- GREEN: `npm run test:unit -- billing-payment-requests` passed after implementing the helper.

### Tests Run
- `npm run test:unit -- billing-payment-requests`: passed after implementation.
- `npm run test:e2e -- billing-page.spec.ts`: 12 passed.
- `npm run test:unit`: 9 files / 39 tests passed.
- `npm run typecheck`: passed.
- `npm run lint`: passed with no warnings/errors.
- `npm run build`: passed.
- Flake reruns: focused helper test passed three green runs total; billing Playwright spec passed three green runs total.
- After the direct-regeneration expiry-window fix: `npm run test:unit`, `npm run test:e2e -- billing-page.spec.ts`, `npm run typecheck`, `npm run lint`, and `npm run build` all passed again.

### Wiring Verification
| Component | Runtime Call Site | Verification |
|-----------|-------------------|--------------|
| `isPaymentRequestExpired` | `BillingPage` render and QR SVG effect | imported in `apps/web/src/app/(app)/billing/page.tsx` |
| `isUsablePendingPaymentRequest` | `BillingPage` live polling copy and `useBillingRecords` refetch decision | imported in `page.tsx` and `apps/web/src/lib/hooks.ts` |
| Expired QR branch | `/billing?record_id=record-expired-1` | Playwright test verifies expired notice, no QR payload, no LINE CTA, and `สร้าง QR ใหม่` POST |

### Risk Notes
- Expired pending requests fail closed to regeneration.
- Missing or invalid `expires_at` stays usable to avoid hiding provider payloads that do not send reliable expiry data.
- No API, schema, migration, or env var change.

### Follow-Ups
- LINE OA webhook/rich-menu configuration remains an operational setup task, not an app code path.

## Review (2026-06-12 14:39:59 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-expired-promptpay-qr`
- Branch: `fix/expired-promptpay-qr`
- Scope: staged working tree against `origin/main` at `cb403d49`
- Commands Run: `git status -sb`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --stat`; targeted `git diff --cached` for `billing-payment-requests.ts`, `hooks.ts`, `billing/page.tsx`, and billing tests; `npm run test:unit`; `npm run test:e2e -- billing-page.spec.ts`; `npm run typecheck`; `npm run lint`; `npm run build`
- Auggie: attempted earlier for this task and failed with `HTTP error: 402`; review used direct staged diff inspection.

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
- Assumption: missing or invalid `expires_at` should remain usable rather than forcing regeneration; this preserves compatibility with provider payloads that omit expiry.
- Assumption: LINE OA webhook/rich-menu setup is operational and should not be automated inside this app change.

### Recommended Tests / Validation
- Completed: helper unit tests, full frontend unit suite, billing Playwright spec, typecheck, lint, and build.
- The focused helper and billing browser checks were rerun repeatedly during implementation to cover flakiness risk.

### Rollout Notes
- Frontend-only behavior change; no API/schema/env migration required.
- Monitor user reports around QR regeneration and admin slip queue matching after deploy.
