## Goal

- Design and implement Phase A backend support for explicit commercial upgrades:
  - `free_trial -> one_time_search_pack`
  - `free_trial -> monthly_membership`
  - `one_time_search_pack -> monthly_membership`

## Exploration

- `main` is in sync with `origin/main` (`0 0`) before planning.
- Relevant plan metadata is centralized in `packages/shared-types/src/egp_shared_types/billing_plans.py`.
- Current plan set is:
  - `free_trial`
  - `one_time_search_pack`
  - `monthly_membership`
- Trial activation is a dedicated zero-payment path via:
  - `apps/api/src/egp_api/services/billing_service.py::start_free_trial()`
  - `packages/db/src/egp_db/repositories/billing_repo.py::activate_free_trial_subscription()`
- Paid plan activation happens only on payment settlement/reconciliation in `packages/db/src/egp_db/repositories/billing_repo.py::reconcile_payment(...)`.
- Current entitlement selection is implicit and potentially ambiguous:
  - `apps/api/src/egp_api/services/entitlement_service.py::_select_current_subscription()`
  - it prefers by status only (`active`, `pending_activation`, `expired`, `cancelled`), then returns the first matching subscription from `list_subscriptions_for_tenant()`
  - `list_subscriptions_for_tenant()` currently orders rows by `created_at desc`
- That means upgrades are not modeled explicitly today; they only work accidentally if the newly created row happens to win the selector.
- Billing records and subscriptions currently have no upgrade-specific linkage fields, so the system cannot explain or safely supersede prior subscriptions during payment settlement.
- `docs/PRICING_AND_ENTITLEMENTS.md` already recommends trial upgrades that preserve tenant/users/profiles/history, but those upgrade channels are not implemented.

## Architectural Conclusion

- Phase A needs explicit upgrade intent persisted in the database plus deterministic subscription selection.
- A pure “just create another paid billing record” approach is not safe enough because entitlement resolution would remain dependent on row ordering and status coincidence.
- The smallest safe backend design is:
  - persist upgrade intent on `billing_records`
  - validate allowed upgrade transitions in a dedicated API/service path
  - when upgraded payment settles, create the new subscription and mark the replaced subscription `cancelled`
  - make entitlement selection prefer the most recent active/pending non-cancelled upgrade result deterministically

## Plan Draft A

### Overview

- Add a dedicated backend upgrade channel under billing.
- Persist upgrade intent on billing records using a migration.
- On successful settlement of an upgrade purchase, cancel the replaced subscription immediately and activate or pending-activate the new subscription according to billing period dates.
- Keep phase scope backend-only: no billing page upgrade UI yet.

### Files To Change

- Migrations:
  - `packages/db/src/migrations/014_subscription_upgrades.sql` (or next sequential migration number if 014 is already used elsewhere)
- Shared enums/types if needed:
  - `packages/shared-types/src/egp_shared_types/enums.py` only if new event/status strings are added there
- DB repository:
  - `packages/db/src/egp_db/repositories/billing_repo.py`
- API service:
  - `apps/api/src/egp_api/services/billing_service.py`
  - `apps/api/src/egp_api/services/entitlement_service.py`
- API route:
  - `apps/api/src/egp_api/routes/billing.py`
- Tests:
  - `tests/phase3/test_invoice_lifecycle.py`
  - `tests/phase3/test_payment_links.py`
  - `tests/phase4/test_entitlements.py`
  - possibly `tests/phase4/test_admin_api.py` if the billing snapshot payload should expose upgrade metadata clearly

### Implementation Steps

1. Add RED migration/repository-backed tests for allowed upgrade transitions.
   - `free_trial -> one_time_search_pack` request creates a billing record with upgrade linkage
   - `free_trial -> monthly_membership` request creates a billing record with upgrade linkage
   - `one_time_search_pack -> monthly_membership` request creates a billing record with upgrade linkage
   - invalid paths are rejected:
     - `monthly_membership -> one_time_search_pack`
     - `one_time_search_pack -> free_trial`
     - `monthly_membership -> free_trial`
2. Add RED tests for settlement semantics.
   - when an upgrade payment settles, the new subscription is created
   - the replaced subscription is marked `cancelled`
   - entitlement selection resolves to the new subscription, not the replaced one
   - future-start upgrades become `pending_activation` while still superseding the older subscription only when appropriate
3. Add RED entitlement tests.
   - trial upgraded to paid now unlocks paid capabilities
   - one-time upgraded to monthly now exposes keyword limit `5`
4. Add migration fields on `billing_records`.
   - `upgrade_from_subscription_id UUID NULL`
   - `upgrade_mode TEXT NOT NULL DEFAULT 'none'`
   - optional FK to `billing_subscriptions(id)` if safe in the existing schema order
   - check constraint for `upgrade_mode IN ('none', 'replace_now', 'replace_on_activation')`
5. Extend `BillingRecordRecord` / `BillingRecordDetail` mapping in `billing_repo.py` to surface the new fields.
6. Add repository upgrade-request API.
   - validate tenant-scoped current subscription
   - validate allowed transition matrix
   - create billing record using target plan defaults
   - persist `upgrade_from_subscription_id` and `upgrade_mode`
7. Add API/service route for upgrade initiation.
   - likely `POST /v1/billing/upgrades`
   - tenant resolved from auth
   - request body includes `target_plan_code` and optional `billing_period_start`
   - response returns the created `BillingRecordDetail`
8. Update reconciliation/settlement logic.
   - when a billing record with `upgrade_from_subscription_id` settles:
     - create new subscription row as today
     - cancel the replaced subscription for `replace_now`
     - for `replace_on_activation`, keep current behavior explicit and deterministic if future-start support is chosen in this phase
9. Replace implicit subscription selection with deterministic effective-subscription logic.
   - prefer non-cancelled `active`
   - then non-cancelled `pending_activation`
   - when multiple remain, prefer most recent created row
   - ensure cancelled subscriptions never win entitlement selection
10. Run fast validation, then refactor only if needed.

### Test Coverage

- `tests/phase3/test_invoice_lifecycle.py`
  - new: `free_trial -> one_time_search_pack` upgrade request creation
  - new: `free_trial -> monthly_membership` upgrade request creation
  - new: `one_time_search_pack -> monthly_membership` settlement supersedes old subscription
  - new: invalid downgrade/sidegrade transitions rejected
- `tests/phase3/test_payment_links.py`
  - new: upgrade billing record can still create payment requests and settle via QR callback
- `tests/phase4/test_entitlements.py`
  - new: upgraded paid plan governs entitlement snapshot after settlement
  - new: monthly upgrade raises keyword limit to `5`

### Decision Completeness

- Goal:
  - explicit backend-only upgrade channel with deterministic entitlement behavior
- Non-goals:
  - no UI upgrade buttons yet
  - no proration or credit ledger
  - no support for multiple simultaneous cumulative paid subscriptions
- Measurable success criteria:
  - supported upgrade transitions create upgrade-linked billing records
  - settlement supersedes the replaced subscription deterministically
  - entitlement snapshot reflects the upgraded plan
  - unsupported transitions are rejected clearly
- Changed public interfaces:
  - new API endpoint: `POST /v1/billing/upgrades`
  - billing record payload now carries upgrade metadata
  - schema migration for `billing_records`
- Edge cases and failure modes:
  - repeated upgrade attempts while a prior upgrade invoice is still open
  - future-start upgrades becoming `pending_activation`
  - cancelled replaced subscriptions must not win entitlement selection
  - trial history must remain preserved even when superseded
- Rollout/backout expectations:
  - deploy migration first, then backend code
  - safe rollback requires code rollback only if migration is additive and nullable
- Concrete acceptance checks:
  - trial tenant can request paid upgrade and settle it
  - one-time tenant can request monthly upgrade and settle it
  - monthly tenant cannot request downgrade to one-time through the upgrade API
  - entitlement snapshot switches from trial/one-time to the upgraded paid plan

### Dependencies

- Existing plan metadata in `packages/shared-types`
- Existing billing reconciliation flow in `packages/db/src/egp_db/repositories/billing_repo.py`
- Existing entitlement snapshot logic in `apps/api/src/egp_api/services/entitlement_service.py`

### Validation

- `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py tests/phase4/test_entitlements.py -q`
- `./.venv/bin/ruff check apps/api packages tests`
- `./.venv/bin/python -m compileall apps/api/src packages`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| upgrade request API | authenticated billing POST route | `apps/api/src/egp_api/routes/billing.py` -> `apps/api/src/egp_api/services/billing_service.py` | writes `billing_records` |
| persisted upgrade intent | billing record create path | `packages/db/src/egp_db/repositories/billing_repo.py` | `billing_records.upgrade_from_subscription_id`, `billing_records.upgrade_mode` |
| supersede-on-settlement logic | payment callback/reconcile path | `packages/db/src/egp_db/repositories/billing_repo.py::reconcile_payment` | updates `billing_subscriptions.status` |
| deterministic entitlement selection | entitlement snapshot callers | `apps/api/src/egp_api/services/entitlement_service.py` | reads `billing_subscriptions` |

## Plan Draft B

### Overview

- Avoid a schema migration in Phase A.
- Implement upgrade intent implicitly in service code by looking at the current subscription at request time and encoding upgrade notes only in billing events/notes.
- On settlement, cancel the latest active subscription if the target plan is a supported upgrade.

### Files To Change

- `packages/db/src/egp_db/repositories/billing_repo.py`
- `apps/api/src/egp_api/services/billing_service.py`
- `apps/api/src/egp_api/routes/billing.py`
- `apps/api/src/egp_api/services/entitlement_service.py`
- tests as in Draft A

### Implementation Steps

1. Add RED tests for supported and unsupported upgrade requests.
2. Add service-only upgrade API that derives upgrade behavior from current active subscription.
3. On settlement, infer “upgrade” by comparing current subscription and target plan code.
4. Cancel previous active subscription heuristically.
5. Tighten entitlement selection order.

### Test Coverage

- Same behavioral coverage as Draft A.

### Decision Completeness

- Goal:
  - same as Draft A
- Non-goals:
  - same as Draft A
- Measurable success criteria:
  - same as Draft A
- Changed public interfaces:
  - new upgrade API but no schema change
- Edge cases:
  - weaker auditability for repeated or concurrent upgrade attempts

### Dependencies

- Relies on existing billing event trails and notes instead of persisted relational upgrade intent.

### Validation

- Same as Draft A.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| inferred upgrade API | authenticated billing POST route | `apps/api/src/egp_api/routes/billing.py` | no new table columns |
| heuristic supersede logic | payment reconciliation path | `packages/db/src/egp_db/repositories/billing_repo.py` | `billing_subscriptions.status` only |

## Comparative Analysis

- Draft A strengths:
  - explicit, auditable, deterministic
  - handles concurrent open invoices and future upgrades safely
  - aligns with money-moving correctness expectations
- Draft A costs:
  - requires an additive migration
- Draft B strengths:
  - smaller initial diff
  - no migration
- Draft B weaknesses:
  - upgrade intent is implicit and fragile
  - concurrency and repeated-upgrade scenarios are hard to reason about
  - support/debugging quality is materially worse

## Unified Execution Plan

### Overview

- Follow Draft A.
- Phase A backend should add an explicit upgrade channel and persisted upgrade intent on billing records.
- Use additive schema only; avoid destructive changes and avoid prorating/credits in this phase.

### Files To Change

- `packages/db/src/migrations/014_subscription_upgrades.sql` (or next sequential migration)
- `packages/db/src/egp_db/repositories/billing_repo.py`
- `apps/api/src/egp_api/services/billing_service.py`
- `apps/api/src/egp_api/routes/billing.py`
- `apps/api/src/egp_api/services/entitlement_service.py`
- `tests/phase3/test_invoice_lifecycle.py`
- `tests/phase3/test_payment_links.py`
- `tests/phase4/test_entitlements.py`

### Implementation Steps

1. Add RED tests in `tests/phase3/test_invoice_lifecycle.py` for explicit upgrade requests.
   - `free_trial -> one_time_search_pack` request succeeds
   - `free_trial -> monthly_membership` request succeeds
   - `one_time_search_pack -> monthly_membership` request succeeds
   - unsupported transitions return `400`
2. Add RED settlement tests in `tests/phase3/test_invoice_lifecycle.py` and `tests/phase3/test_payment_links.py`.
   - settling an upgrade creates the new subscription
   - replaced subscription becomes `cancelled`
   - QR/webhook settlement path also triggers upgrade supersession correctly
3. Add RED entitlement tests in `tests/phase4/test_entitlements.py`.
   - entitlement snapshot after upgrade chooses upgraded plan deterministically
   - monthly upgrade increases keyword limit to `5`
4. Add additive migration fields on `billing_records`.
   - `upgrade_from_subscription_id UUID NULL`
   - `upgrade_mode TEXT NOT NULL DEFAULT 'none'`
   - add FK/index/check constraint
5. Extend repository models and serializers.
   - `BillingRecordRecord` and any response serializers include the new fields
6. Implement repository upgrade request creation.
   - add helper to load current effective subscription for tenant
   - validate supported transitions:
     - `free_trial -> one_time_search_pack`
     - `free_trial -> monthly_membership`
     - `one_time_search_pack -> monthly_membership`
   - create upgrade-linked billing record using target plan defaults
7. Implement billing service + route.
   - add `POST /v1/billing/upgrades`
   - request body: `tenant_id?`, `target_plan_code`, optional `billing_period_start`, optional `record_number`, optional `notes`
   - route resolves tenant from auth and returns `201`
8. Implement supersede-on-settlement logic in repository reconciliation.
   - if the billing record has `upgrade_mode='replace_now'` and `upgrade_from_subscription_id`:
     - create new subscription row
     - update replaced subscription to `cancelled`
     - append upgrade-related billing events
9. Tighten entitlement selection.
   - exclude `cancelled` rows from winning over active/pending upgrades
   - use deterministic status+recency ordering for the effective subscription
10. Run fast validation, then run skeptical review + `g-check`.

### Test Coverage

- `tests/phase3/test_invoice_lifecycle.py`
  - upgrade request creation
  - settlement supersedes old subscription
  - invalid upgrade paths rejected
- `tests/phase3/test_payment_links.py`
  - paid QR callback can settle an upgrade-linked billing record
- `tests/phase4/test_entitlements.py`
  - upgraded plan governs snapshot and capability matrix

### Decision Completeness

- Goal:
  - explicit backend upgrade channel with deterministic entitlement behavior
- Non-goals:
  - no frontend upgrade UI
  - no proration/credit ledger
  - no cumulative active-plan stacking
- Measurable success criteria:
  - upgrade API exists and enforces supported transitions only
  - settlement supersedes replaced subscription predictably
  - entitlement snapshot reflects the upgraded plan
  - existing tenant/users/profiles/history remain untouched
- Changed public interfaces:
  - new route `POST /v1/billing/upgrades`
  - billing record response includes upgrade metadata
  - additive DB migration on `billing_records`
- Edge cases and failure modes:
  - repeated upgrade invoices for the same tenant
  - future-start upgrades returning `pending_activation`
  - cancelled replaced subscription must not be selected for entitlements
- Rollout/backout expectations:
  - apply migration before deploy
  - code rollback is safe because migration is additive and defaults are nullable/non-breaking
- Concrete acceptance checks:
  - active free trial can request one-time or monthly upgrade
  - active one-time can request monthly upgrade
  - monthly cannot use upgrade API to downgrade to one-time
  - settled upgraded subscription becomes current effective entitlement

### Dependencies

- Billing plan metadata in `packages/shared-types`
- Payment request and settlement flows in `billing_service.py` and `billing_repo.py`
- Entitlement snapshot consumers across API/worker already rely on `TenantEntitlementService`

### Validation

- `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py tests/phase4/test_entitlements.py -q`
- `./.venv/bin/ruff check apps/api packages tests`
- `./.venv/bin/python -m compileall apps/api/src packages`

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| upgrade request route | authenticated billing POST route | `apps/api/src/egp_api/routes/billing.py` | writes `billing_records` |
| upgrade service orchestration | route handler | `apps/api/src/egp_api/services/billing_service.py` | reads `billing_subscriptions`, writes `billing_records` |
| persisted upgrade intent | repository create path | `packages/db/src/egp_db/repositories/billing_repo.py` | `billing_records.upgrade_from_subscription_id`, `billing_records.upgrade_mode` |
| supersede-on-settlement behavior | payment callback/reconcile path | `packages/db/src/egp_db/repositories/billing_repo.py::reconcile_payment` | updates `billing_subscriptions.status` |
| effective subscription selection | entitlement snapshot | `apps/api/src/egp_api/services/entitlement_service.py` | reads `billing_subscriptions` |

## Review (2026-04-08 12:56:46 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree (Phase A billing/entitlement upgrade implementation)
- Commands Run: `git status --porcelain=v1`; `git diff --name-only`; `git diff --stat`; targeted `git diff` on billing route/service/repository/tests; Auggie code retrieval; focused tests `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py tests/phase4/test_entitlements.py -q`; `./.venv/bin/ruff check apps/api packages`; `./.venv/bin/python -m compileall apps/api/src packages/db/src packages/shared-types/src`

### Findings
CRITICAL
- No findings.

HIGH
- Duplicate open upgrade invoices are currently allowed for the same source subscription. `POST /v1/billing/upgrades` flows straight through `apps/api/src/egp_api/routes/billing.py:431` and `apps/api/src/egp_api/services/billing_service.py:130` into `packages/db/src/egp_db/repositories/billing_repo.py:1566`, where `create_upgrade_billing_record()` validates the transition but never checks for an existing non-terminal billing record tied to the same `upgrade_from_subscription_id`. Repeating the same request can create multiple payable upgrade records for one current subscription. When one settles, `reconcile_payment()` cancels the old subscription at `packages/db/src/egp_db/repositories/billing_repo.py:2034`, but later settlement of another duplicate upgrade record can still create an additional active or pending subscription for the tenant. Fix direction: enforce one open upgrade record per source subscription, or make duplicate requests idempotently reuse the existing open record. Tests needed: repeated upgrade request while the first upgrade invoice is still `awaiting_payment`, plus settlement of the second invoice after the first has already settled.
- Future-dated upgrades using `replace_now` can prematurely remove tenant access. `create_upgrade_billing_record()` always stores `upgrade_mode="replace_now"` at `packages/db/src/egp_db/repositories/billing_repo.py:1605`, even when `billing_period_start` is in the future. On settlement, `reconcile_payment()` derives a `pending_activation` subscription for a future period at `packages/db/src/egp_db/repositories/billing_repo.py:1997` and then immediately cancels the current subscription at `packages/db/src/egp_db/repositories/billing_repo.py:2034`. `apps/api/src/egp_api/services/entitlement_service.py:83` only grants access from `ACTIVE` subscriptions, so the tenant can lose runs/exports/downloads/notifications until the future start date. Fix direction: either reject future-start upgrades in Phase A or implement `replace_on_activation` and delay cancellation until activation time. Tests needed: future-start upgrade settlement should either fail validation or preserve the current active entitlement until the replacement becomes active.

MEDIUM
- No findings.

LOW
- No findings.

### Open Questions / Assumptions
- Assume Phase A intends at most one in-flight upgrade per current subscription.
- Assume future-start upgrades are only acceptable if entitlement continuity is preserved.

### Recommended Tests / Validation
- Add a repository/API test proving duplicate upgrade requests are rejected or reused while an earlier upgrade invoice is still non-terminal.
- Add a payment-settlement test for a future `billing_period_start` to prove the tenant either keeps current access until activation or the API rejects the request.

### Rollout Notes
- The migration is additive, but these two behaviors can create real billing/support incidents if shipped as-is: money can be collected for duplicate upgrades, and a future-dated paid upgrade can unexpectedly disable existing paid access.

## Review (2026-04-08 13:07:52 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree (Phase A follow-up after duplicate/future-start fixes)
- Commands Run: `git status --porcelain=v1`; `git diff --name-only`; `git diff --stat`; targeted `git diff` on billing route/service/repository/tests; Auggie code retrieval; focused tests `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py tests/phase4/test_entitlements.py -q`

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- The duplicate-upgrade guard is still vulnerable to concurrent requests because it is implemented as a read-then-insert check without a database constraint. `create_upgrade_billing_record()` performs a standalone lookup for any open upgrade row at `packages/db/src/egp_db/repositories/billing_repo.py:1605`, exits that transaction, and only then calls `create_billing_record()` to insert the new row at `packages/db/src/egp_db/repositories/billing_repo.py:1630`. Two concurrent requests can both observe no existing upgrade and both insert payable records. The current API test only proves sequential rejection (`tests/phase3/test_invoice_lifecycle.py:377`), so it does not cover this race. Fix direction: enforce uniqueness in the database for non-terminal upgrade records, or perform the check and insert inside one transaction guarded by a lockable source row/constraint. Tests needed: a repository-level concurrency test if practical, or at minimum a constraint-backed failure path test.

LOW
- No findings.

### Open Questions / Assumptions
- Assume Phase A traffic is low enough that a follow-up hardening change can land before broad rollout if concurrent upgrade requests are considered realistic.

### Recommended Tests / Validation
- Add a lower-level repository test around the eventual database-backed uniqueness strategy, since request-level sequential tests will not expose the race.

### Rollout Notes
- The product-level duplicate/future-start behaviors are now covered, but the duplicate protection is not yet concurrency-safe under simultaneous requests.

## Review (2026-04-08 16:46:22 +0700) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree (Phase A backend upgrade implementation, current state)
- Commands Run: `git status --porcelain=v1`; `git diff --name-only`; `git diff --stat`; Auggie code retrieval; targeted file inspection of billing route/service/repository/tests; `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py tests/phase4/test_entitlements.py -q`; `./.venv/bin/ruff check apps/api packages tests`; `./.venv/bin/python -m compileall apps/api/src packages`; `gh pr list --state open --json number,title,headRefName,baseRefName,url`

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
- Assume Phase A intentionally rejects future-start upgrades, matching the current API validation and test coverage.
- Assume Phase C will handle upgrade-chain admin/audit visibility beyond the persisted linkage now present on `billing_records`.

### Recommended Tests / Validation
- Before merge/deploy, apply `packages/db/src/migrations/016_subscription_upgrades.sql` against the target Postgres environment, since the focused test suite here exercised SQLite-backed repository behavior.
- When Phase B starts, add an end-to-end web/API flow test around upgrade CTA to QR request creation so the new backend path stays wired.

### Rollout Notes
- The reviewed Phase A backend slice is additive and currently green on focused tests, lint, and compile checks.
- Local work remains uncommitted on `main`, so none of this review corresponds to a commit or PR yet.
