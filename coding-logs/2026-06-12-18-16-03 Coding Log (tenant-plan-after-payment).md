# Coding Log: tenant-plan-after-payment

## 2026-06-12 18:16 +0700

Goal: diagnose and fix the stale tenant profile plan after LINE/manual payment activation.

Initial diagnosis:
- Production entitlements and keyword limits can update from `billing_subscriptions`, while the profile/header/admin tenant metadata can still read `tenants.plan_code`.
- The billing payment reconciliation path creates `billing_subscriptions` on paid invoices but did not yet show a tenant plan update in the inspected transaction.
- Auggie semantic retrieval was attempted and failed with HTTP 402, so implementation proceeds with direct file inspection and exact-string searches.

## Implementation Summary (2026-06-12 18:21 +0700)

Goal of the change:
- Keep tenant profile metadata in sync when a paid billing record activates a subscription immediately, so profile/admin surfaces that read `tenants.plan_code` no longer remain stale after LINE/manual payment verification.

What changed:
- `packages/db/src/egp_db/repositories/billing_payments.py`
  - Added `_sync_tenant_plan_for_active_subscription`.
  - Calls it from payment reconciliation after inserting a subscription and emitting `subscription_activated`.
  - The update is tenant-scoped and runs only when the computed subscription status is `active`; future `pending_activation` subscriptions do not change the tenant plan early.
- `tests/phase3/test_invoice_lifecycle.py`
  - Added tenant metadata helpers.
  - Added a regression test proving active monthly settlement updates `tenants.plan_code`.
  - Strengthened the future-start settlement test to prove pending subscriptions preserve the current tenant plan.
- `tests/phase4/test_line_webhook_api.py`
  - Replaced an expired hard-coded May 2026 billing period with a UTC-current period so LINE verification tests remain date-safe.

TDD evidence:
- RED: `PYTHONPATH=apps/api/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/notification-core/src ../egp/.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -k 'tenant_profile_plan or future_start_upgrade_settlement_preserves_current_active_subscription' -q`
  - Failed because `_tenant_plan_code(client)` remained `one_time_search_pack` after an active monthly subscription settlement.
- GREEN: same command passed with `2 passed, 17 deselected`.

Tests run:
- `PYTHONPATH=apps/api/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/notification-core/src ../egp/.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -q` -> `19 passed` (run twice after the fix).
- `PYTHONPATH=apps/api/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/notification-core/src ../egp/.venv/bin/python -m pytest tests/phase4/test_line_webhook_api.py -q` -> `12 passed` (run three green times after the fixture fix).
- `PYTHONPATH=apps/api/src:packages/db/src:packages/shared-types/src:packages/crawler-core/src:packages/document-classifier/src:packages/notification-core/src ../egp/.venv/bin/python -m compileall packages/db/src apps/api/src` -> passed.
- `../egp/.venv/bin/ruff check packages/db/src/egp_db/repositories/billing_payments.py tests/phase3/test_invoice_lifecycle.py tests/phase4/test_line_webhook_api.py` -> passed.

Wiring verification:
- Runtime call path is existing admin/LINE/manual payment verification -> `BillingPaymentMixin.reconcile_payment` -> subscription insert -> `_sync_tenant_plan_for_active_subscription` -> `TENANTS_TABLE` update.
- No new endpoint, migration, or environment variable was introduced.

Behavior changes and risk notes:
- Active subscription activation now mirrors the active billing plan into tenant metadata.
- Pending future subscriptions deliberately do not mutate tenant metadata early.
- Existing stale production rows need a one-time data repair because the code path already completed for those payments.

Follow-ups / known gaps:
- No automated backfill is included in this code change; production data repair should be run explicitly for tenants already affected before this deployment.

## Review (2026-06-12 18:21 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp-profile-plan-update`
- Branch: `fix/tenant-plan-after-payment`
- Scope: staged working tree
- Commands Run: `git status --short --branch`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; targeted `nl -ba` inspections; targeted pytest, compileall, and ruff commands listed above.

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
- Assumes `tenants.plan_code` is intended to mirror the currently active paid subscription for legacy/profile/admin metadata surfaces.
- Assumes future-start paid subscriptions should remain pending without changing tenant metadata until a separate activation process marks them active.

### Recommended Tests / Validation
- Keep the added invoice lifecycle tests for active settlement and future-start settlement.
- Keep the LINE webhook suite date-safe because subscription status is computed against current UTC time.

### Rollout Notes
- Deploying the code prevents new stale tenant plans after verified payments.
- Run a one-time production update for any tenant already stale from payments verified before this fix.
