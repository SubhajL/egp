# Billing Repository Split

## Plan Draft A

### Overview
Split the 2,203-line `billing_repo.py` into focused repository modules while preserving the current public import path. Follow the existing document repository pattern: keep `billing_repo.py` as the facade, move shared dataclasses/schema/helpers into dedicated modules, and compose `SqlBillingRepository` from focused mixins.

Auggie semantic search was unavailable due to HTTP 429, so this plan is based on direct file inspection plus exact identifier searches.

### Files to Change
- `packages/db/src/egp_db/repositories/billing_repo.py`: compatibility facade and factory.
- `packages/db/src/egp_db/repositories/billing_models.py`: public records plus private row records.
- `packages/db/src/egp_db/repositories/billing_schema.py`: SQLAlchemy tables, indexes, metadata constants.
- `packages/db/src/egp_db/repositories/billing_utils.py`: normalization, mapping, grouping, detail assembly.
- `packages/db/src/egp_db/repositories/billing_events.py`: billing event/provider-event helpers.
- `packages/db/src/egp_db/repositories/billing_invoices.py`: billing record listing, creation, status transitions, overdue checks.
- `packages/db/src/egp_db/repositories/billing_payment_requests.py`: payment request lookup/create/update/provider callback.
- `packages/db/src/egp_db/repositories/billing_payments.py`: payment recording and reconciliation.
- `packages/db/src/egp_db/repositories/billing_subscriptions.py`: subscription listing, free trial, effective/upcoming selection, upgrades.
- `tests/phase4/test_billing_repository_decomposition.py`: structural regression test for decomposition and facade exports.

### Implementation Steps
1. Add a failing structural test that expects the new billing modules, a small facade, and mixin composition.
2. Move dataclasses and private row records into `billing_models.py`.
3. Move table metadata and indexes into `billing_schema.py`.
4. Move normalization, row mapping, grouping, and detail helpers into `billing_utils.py`.
5. Move event helpers into `BillingEventMixin`.
6. Move invoice, payment request, payment, and subscription methods into dedicated mixins.
7. Rebuild `SqlBillingRepository` as a facade class inheriting the mixins.
8. Run focused billing tests, compile, and package checks.

### Test Coverage
- `test_billing_repository_is_split_into_focused_modules`: verifies module split exists.
- `test_billing_repo_remains_public_facade`: verifies public imports still work.
- Existing billing API tests: verify behavior did not change.

### Decision Completeness
- Goal: split `billing_repo.py` without changing behavior.
- Non-goals: no schema migrations, no endpoint changes, no billing contract changes.
- Success criteria: old imports work; billing tests pass; facade is substantially smaller.
- Public interfaces: unchanged Python imports from `egp_db.repositories.billing_repo`; no API/env/CLI/schema changes.
- Edge cases/failure modes: tenant isolation and idempotent provider events must remain fail-closed; invalid billing/payment states still raise the same errors.
- Rollout: pure code refactor; backout is reverting the PR.
- Acceptance checks: structural pytest, billing pytest, compileall, ruff.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `billing_repo.py` facade | Existing imports from API/worker/tests | `from egp_db.repositories.billing_repo import ...` | N/A |
| `billing_schema.py` | `SqlBillingRepository._ensure_schema()` via mixins | Imported by facade and helpers | billing tables unchanged |
| Billing mixins | `SqlBillingRepository` inheritance | `billing_repo.py` class definition | Existing billing tables |

## Plan Draft B

### Overview
Split only schema/models/helpers first, leaving all repository methods in `billing_repo.py`. This reduces import risk but leaves the dominant class too large and does not fully deliver PR 16.

### Files to Change
- `billing_models.py`, `billing_schema.py`, `billing_utils.py`, `billing_repo.py`, and structural tests.

### Implementation Steps
1. Add structural test for schema/model/helper extraction.
2. Move dataclasses and SQLAlchemy metadata.
3. Update `billing_repo.py` imports.
4. Leave method bodies in place.

### Test Coverage
- Structural module test.
- Existing billing tests.

### Decision Completeness
- Goal: reduce some file size with minimal risk.
- Non-goals: full subdomain method separation.
- Success criteria: tests pass and schema/models are no longer in facade.
- Public interfaces: unchanged.
- Edge cases/failure modes: same as Draft A.
- Rollout: pure refactor.
- Acceptance checks: same focused gates.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `billing_repo.py` | Existing imports | Existing import path | Existing billing tables |

## Comparative Analysis
Draft A better matches the PR boundary from the phase train: invoices, subscriptions, payment requests, events, and facade become explicit modules. Draft B is lower risk but under-delivers because the main method surface remains tangled in one large file.

Use Draft A, but keep each extraction mechanical: no renamed public methods, no SQL changes, no behavior rewrites beyond imports and mixin composition.

## Unified Execution Plan

### Overview
Implement a behavior-preserving split using the document repository pattern already present in the repo. The public facade remains `egp_db.repositories.billing_repo`, and all runtime call sites continue to use `create_billing_repository()` and `SqlBillingRepository`.

### Files to Change
- `packages/db/src/egp_db/repositories/billing_models.py`: public and private records.
- `packages/db/src/egp_db/repositories/billing_schema.py`: tables, indexes, metadata.
- `packages/db/src/egp_db/repositories/billing_utils.py`: shared normalization/mapping/detail helpers.
- `packages/db/src/egp_db/repositories/billing_events.py`: event insert/idempotency mixin.
- `packages/db/src/egp_db/repositories/billing_invoices.py`: invoice/list/status methods.
- `packages/db/src/egp_db/repositories/billing_payment_requests.py`: payment request methods.
- `packages/db/src/egp_db/repositories/billing_payments.py`: payment recording/reconciliation methods.
- `packages/db/src/egp_db/repositories/billing_subscriptions.py`: subscription/free-trial/upgrade methods.
- `packages/db/src/egp_db/repositories/billing_repo.py`: facade exports and repository factory.
- `tests/phase4/test_billing_repository_decomposition.py`: structural guard.

### TDD Sequence
1. Add the structural test and run it to confirm it fails because modules do not exist and the facade is too large.
2. Add the new modules and move code mechanically.
3. Run the structural test until green.
4. Run focused billing behavior tests.
5. Run compileall and ruff for `packages/db/src`.

### Functions and Classes
- `SqlBillingRepository`: facade class composed from billing mixins.
- `BillingInvoiceMixin`: record loading, list, create, status transition, overdue checks.
- `BillingPaymentRequestMixin`: payment request detail/create/update/provider callback.
- `BillingPaymentMixin`: manual payment recording and reconciliation.
- `BillingSubscriptionMixin`: subscription selection, free trial activation, upgrade record creation.
- `BillingEventMixin`: private event/provider-event persistence helpers.

### Test Coverage
- `test_billing_repository_is_split_into_focused_modules`: verifies expected files and facade size.
- `test_billing_repo_remains_public_facade`: verifies facade exports.
- Existing billing tests: invoice lifecycle, payment links, reconciliation.

### Decision Completeness
- Goal: make billing repository maintainable through focused modules.
- Non-goals: no data model changes; no route/service changes; no generated types changes.
- Success criteria: import compatibility, behavior tests pass, `billing_repo.py` becomes a compact facade.
- Public interfaces: unchanged.
- Operational expectations: deploy as normal code-only refactor; no migration or flag.
- Edge cases: tenant-scoped guards, duplicate provider event idempotency, partial payments, retries, upgrade cancellation, and free-trial uniqueness must remain unchanged.
- Failure mode posture: tenant/security checks fail closed with `PermissionError`/`KeyError`; duplicate provider events return `False` without double-applying work.
- Rollout & monitoring: watch existing billing endpoint smoke/CI tests; no new metrics.
- Acceptance checks: `pytest tests/phase4/test_billing_repository_decomposition.py`, `pytest tests/phase2/test_billing_reconciliation.py tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py`, `python -m compileall packages/db/src`, `ruff check packages/db/src`.

### Dependencies
No external dependencies.

### Validation
Focused billing tests should pass without API or database migration changes.

### Wiring Verification
| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `SqlBillingRepository` | `create_billing_repository()` | `billing_repo.py` facade | N/A |
| Billing mixins | `SqlBillingRepository` inheritance | `billing_repo.py` | Existing billing tables |
| `billing_schema.py` | `_ensure_schema()` and CRUD SQL | Imported by mixins | `billing_records`, `billing_payments`, `billing_payment_requests`, `billing_events`, `billing_provider_events`, `billing_subscriptions` |
| `billing_models.py` | API/service imports via facade | Re-exported by `billing_repo.py` | N/A |



## Implementation Summary (2026-05-16T12:44:43)

### Goal
Split PR 16's billing repository into focused invoice, subscription, payment request, payment, event, schema, model, utility, and facade modules without changing runtime behavior.

### What Changed
- `packages/db/src/egp_db/repositories/billing_repo.py`: reduced to a 96-line compatibility facade, `SqlBillingRepository` composition class, and factory.
- `packages/db/src/egp_db/repositories/billing_models.py`: moved public billing record dataclasses and private row dataclasses.
- `packages/db/src/egp_db/repositories/billing_schema.py`: moved billing SQLAlchemy table/index metadata.
- `packages/db/src/egp_db/repositories/billing_utils.py`: moved normalization, mapping, grouping, and detail assembly helpers.
- `packages/db/src/egp_db/repositories/billing_events.py`: added `BillingEventMixin` for billing event and provider event persistence.
- `packages/db/src/egp_db/repositories/billing_invoices.py`: added `BillingInvoiceMixin` for record loading, listing, creation, transitions, and overdue checks.
- `packages/db/src/egp_db/repositories/billing_payment_requests.py`: added `BillingPaymentRequestMixin` for payment request lifecycle and provider callbacks.
- `packages/db/src/egp_db/repositories/billing_payments.py`: added `BillingPaymentMixin` for manual payment recording and reconciliation.
- `packages/db/src/egp_db/repositories/billing_subscriptions.py`: added `BillingSubscriptionMixin` for subscription selection, free trial activation, and upgrade records.
- `tests/phase4/test_billing_repository_decomposition.py`: added structural guard for module split and facade compatibility.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase4/test_billing_repository_decomposition.py -q` failed with `ModuleNotFoundError: No module named 'egp_db.repositories.billing_events'` before the split.
- GREEN: `./.venv/bin/python -m pytest tests/phase4/test_billing_repository_decomposition.py tests/phase2/test_billing_reconciliation.py tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py -q` passed with 37 tests.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase4/test_billing_repository_decomposition.py -q` -> 2 passed.
- `./.venv/bin/python -m pytest tests/phase2/test_billing_reconciliation.py tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py -q` -> 35 passed.
- `./.venv/bin/python -m pytest tests/phase4/test_billing_repository_decomposition.py tests/phase2/test_billing_reconciliation.py tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py -q` -> 37 passed.
- `./.venv/bin/python -m compileall packages/db/src` -> passed.
- `./.venv/bin/ruff check packages/db/src tests/phase4/test_billing_repository_decomposition.py` -> passed.

### Wiring Verification
- Existing public import path `egp_db.repositories.billing_repo` remains the facade for API, worker, tests, and package exports.
- `SqlBillingRepository` now inherits `BillingInvoiceMixin`, `BillingPaymentRequestMixin`, `BillingPaymentMixin`, `BillingSubscriptionMixin`, and `BillingEventMixin`.
- `_ensure_schema()` still uses the same `METADATA` object and unchanged billing tables from `billing_schema.py`.
- No endpoints, env vars, migrations, or database table names changed.

### Behavior and Risk Notes
- Behavior is intended to be unchanged; this is a code organization refactor.
- Tenant isolation checks, payment idempotency, free-trial uniqueness, and upgrade handling are covered by the focused billing test set.
- Auggie semantic search was attempted but unavailable due to HTTP 429, so implementation used direct file inspection and exact identifier searches.

### Follow-ups / Known Gaps
- Full repository test suite was not run yet; focused package/API billing gates are green.


## Review (2026-05-16T12:46:33) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working tree for PR16 billing repository split
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; targeted `sed -n` inspection of billing facade/mixins/schema/utils/test; `rg -n "from egp_db\.repositories\.billing_repo|create_billing_repository|SqlBillingRepository" apps packages tests`; `./.venv/bin/python -m pytest tests/phase4/test_billing_repository_decomposition.py tests/phase2/test_billing_reconciliation.py tests/phase3/test_invoice_lifecycle.py tests/phase3/test_payment_links.py -q`; `./.venv/bin/python -m compileall packages/db/src`; `./.venv/bin/ruff check packages/db/src tests/phase4/test_billing_repository_decomposition.py`; `./.venv/bin/ruff format --check ...`
- Auggie: attempted twice and failed with HTTP 429; review used direct inspection and exact identifier searches.

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
- Assumption: `egp_db.repositories.billing_repo` remains the intended public compatibility surface; no callers should import private helper modules unless they need structural tests.
- Assumption: code-only refactor is acceptable without a migration or runtime flag.

### Recommended Tests / Validation
- Completed: focused billing/decomposition pytest command passed with 37 tests.
- Completed: package compileall passed.
- Completed: ruff check and ruff format check passed for touched Python files.
- Residual risk: full repository test suite was not run; focused billing/API coverage is strong for the changed surface.

### Rollout Notes
- No schema, endpoint, env var, or public API behavior changes.
- Existing deployment/rollback remains a normal code deploy/revert.


## Submission / Landing Status (2026-05-16T12:49:13)

- Created Graphite branch: `refactor/db-split-billing-repository`.
- Commit: `52b714b6 refactor(db): split billing repository facade`.
- Submitted PR: https://github.com/SubhajL/egp/pull/88.
- Enabled auto-merge with merge commit strategy.
- Landing blocker: required GitHub checks did not start. GitHub check annotations report: `The job was not started because your account is locked due to a billing issue.` This affected CI Pipeline jobs and Claude Code Review.
- Direct merge is blocked by branch protection. Admin bypass was not used because repo guidance requires passing checks and the user has not explicitly authorized bypassing failed required checks.
