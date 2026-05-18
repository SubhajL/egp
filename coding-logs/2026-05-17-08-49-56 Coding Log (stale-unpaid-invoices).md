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


## Merge Train (2026-05-17T09:02:42+07:00)

### Landed
- PR #95 `fix(billing): archive stale unpaid upgrade invoices`
- GitHub checks failed before executing any workflow steps (all relevant jobs reported empty `steps` arrays), matching the prior repo-wide CI infrastructure pattern observed earlier on May 17, 2026.
- Local gates were fully green, so PR #95 was merged with admin override.
- Merge commit on `main`: `e5070f2825e48950012e48baa913d9c14696fa12`

### Sync / Stack Actions
- Ran `gt submit --publish --no-interactive` to create PR #95.
- Verified failed remote checks with compact GitHub metadata and empty-step workflow payloads.
- Ran `gh pr merge 95 --merge --admin --delete-branch=false`.
- Ran `gt sync --no-interactive`; local `main` fast-forwarded to `e5070f28`.
- Switched back to `main` and restored the pre-existing unrelated coding-log edit that was present before this task began.

### Result
- Local branch: `main`
- Local `main` and `origin/main` are aligned at `e5070f2825e48950012e48baa913d9c14696fa12`.
- `scripts/check_main_sync.py --json` confirms `branch_synced=true`, `ahead=0`, `behind=0`; `ok=false` only because the restored pre-existing coding-log edit keeps the worktree intentionally dirty.


## Implementation Update (2026-05-17T11:29:25+07:00)

### Goal
Fix the billing page’s contradictory post-payment state so an already-paid active One-Time Search Pack no longer renders an expired warning or a stale one-time renewal CTA while webhook-driven refreshes are settling.

### What Changed
- `apps/web/src/app/(app)/billing/page.tsx`
  - moved billing-page warning and upgrade-option decisions from `rules.entitlements` to the billing snapshot’s `current_subscription`
  - removed the `useRules()` dependency from this page so billing-specific UI is driven by a single fresh source of truth during payment polling
  - warning labels now come from the billing plan map plus `current_subscription`, avoiding mixed expired/future-date copy
- `apps/web/tests/e2e/billing-page.spec.ts`
  - added a regression scenario where `/v1/rules` still says `expired` while `/v1/billing/records` already reports an active paid one-time subscription
  - tightened active one-time/monthly billing fixtures so mocked billing state matches the scenario under test instead of relying on contradictory free-trial data

### TDD Evidence
- RED:
  - `npm run test:e2e -- --grep 'rules cache still says expired'`
  - failed because the page did not render the active one-time CTA state when billing was active but cached rules still said expired
- GREEN:
  - `npm run test:e2e -- --grep 'rules cache still says expired'`
  - passed after switching billing-page decisions to `current_subscription`
- Follow-up regression catch:
  - `npm run test:e2e -- --grep 'billing page'`
  - initially exposed an inconsistent existing fixture (`planCode=one_time_search_pack` with a free-trial billing snapshot); the fixture was corrected, then the suite passed

### Tests Run
- `npm run test:e2e -- --grep 'rules cache still says expired'` — pass
- `npm run test:e2e -- --grep 'billing page'` — pass (`11 passed`)
- `npm run test:unit` — pass (`23 passed`)
- `npm run typecheck` — pass
- `npm run lint` — pass
- `npm run build` — pass
- `npm test` — pass (`33 passed`)

### Wiring Verification Evidence
- `GET /v1/billing/records` already returns `current_subscription` from the billing repository snapshot; the billing page now uses that same field for both the expired banner and upgrade CTA branching.
- OPN settlement updates billing records asynchronously, and the existing `useBillingRecords()` polling path refreshes those records every 5 seconds while a payment request is pending. The fix intentionally follows that refreshed billing path rather than a separate cached `/v1/rules` query.
- Existing expired-state E2E coverage remains green, proving true expired one-time and monthly subscriptions still surface renewal/change options when `current_subscription.subscription_status === "expired"`.

### Behavior / Risk Notes
- This is a frontend source-of-truth fix, not a commercial-policy change: truly expired one-time packs can still surface the existing renewal path, but active one-time packs no longer inherit stale expired copy after payment.
- The change narrows inconsistency risk on the billing page by removing cross-endpoint state mixing. It does not alter backend subscription activation, entitlement calculation, or payment reconciliation behavior.
- Auggie semantic retrieval was attempted twice and returned HTTP 429, so the investigation used direct file inspection plus exact-string searches as the documented fallback.

### Follow-ups / Known Gaps
- If product wants to remove one-time-to-one-time renewal even after real expiry, that is a separate business-rule change touching both the backend transition allowlist and the true-expired E2E/API tests.


## Review (2026-05-17T11:29:25+07:00) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree
- Commands Run: `git status --porcelain=v1`, `git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff` for billing page + billing E2E spec, focused/full frontend validation commands

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
- Assumption: the user’s complaint about “ต่ออายุ One-Time Search Pack” refers to the active-post-payment regression shown in the screenshot, not a request to remove same-plan renewal after a genuinely expired one-time subscription.
- Existing unrelated working-tree edits in `apps/web/next-env.d.ts` and prior coding logs were not part of this review scope.

### Recommended Tests / Validation
- Keep the new stale-rules regression scenario; it is the behavioral test that would fail if the page started mixing `/v1/rules` and billing snapshots again.
- Keep the existing true-expired one-time/monthly E2E cases to guard the intentionally preserved expired-state behavior.

### Rollout Notes
- No API or schema changes; frontend-only behavior correction.
- After deploy, manually settle one OPN test payment and confirm the billing page transitions from expired to active without retaining the amber warning or one-time renewal CTA.


## Implementation Update (2026-05-17T11:58:04+07:00)

### Goal
Let a renewed One-Time Search Pack begin a fresh search cycle without hiding the tenant's previously scraped project history.

### What Changed
- `packages/db/src/egp_db/repositories/billing_payments.py`
  - added renewal-specific profile reset logic inside payment reconciliation
  - when an active `one_time_search_pack` is activated from a prior `one_time_search_pack`, previously active crawl profiles for that tenant are marked inactive instead of deleted
- `tests/phase3/test_invoice_lifecycle.py`
  - added end-to-end renewal coverage proving the old profile is preserved but inactive, the renewed pack has one available keyword slot, a new keyword can be created, and prior projects remain visible

### TDD Evidence
- RED:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -q`
  - failed in `test_one_time_renewal_keeps_project_history_and_reopens_keyword_slot` because `active_keyword_count` stayed `1` after renewal instead of resetting to `0`
- GREEN:
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py::test_one_time_renewal_keeps_project_history_and_reopens_keyword_slot -q`
  - `./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py -q`
  - both passed after renewal activation deactivated the prior active profile set

### Tests Run
- `./.venv/bin/ruff check packages tests/phase3/test_invoice_lifecycle.py` — pass
- `./.venv/bin/python -m compileall packages/db/src apps/api/src` — pass
- `./.venv/bin/ruff check apps/api packages tests/phase3/test_invoice_lifecycle.py && ./.venv/bin/python -m pytest tests/phase3/test_invoice_lifecycle.py tests/phase2/test_rules_api.py tests/phase4/test_entitlements.py -q` — pass (`45 passed`)
- `(cd apps/web && npm run test:unit && npm test && npm run typecheck && npm run lint && npm run build)` — pass

### Wiring Verification Evidence
- The behavior is wired at the shared repository reconciliation layer, so both normal API reconciliation and provider-webhook/Lambda reconciliation paths inherit it through `BillingPaymentMixin.reconcile_payment`.
- `RulesService` and `TenantEntitlementService` already count only active profiles, so deactivating the previous watchlist immediately frees the one-keyword quota for the renewed pack.
- `ProjectQueryMixin.list_projects` is tenant-scoped and independent of crawl-profile activity, which is why historical projects remain queryable after the reset.

### Behavior / Risk Notes
- This is intentionally narrow: only active `one_time_search_pack -> one_time_search_pack` renewals reset the active watchlist. Other plan changes keep their current behavior.
- The reset is fail-closed for future crawling but non-destructive for customer history: old profiles remain stored, and prior projects remain available.
- Auggie semantic retrieval was attempted twice and returned HTTP 429, so the implementation used direct file inspection plus exact-string search as the documented fallback.

### Follow-ups / Known Gaps
- If product later wants expired `monthly_membership -> one_time_search_pack` downgrades to also start with a clean one-keyword slate, that should be a separate explicit policy decision and test.


## Review (2026-05-17T11:58:32+0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree at `e5070f2825e48950012e48baa913d9c14696fa12`
- Commands Run: `git status --porcelain=v1`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff` inspection for billing page / billing E2E / billing reconciliation / invoice lifecycle test, focused backend and full frontend validation commands

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
- Assumption: the requested policy change is intentionally scoped to `one_time_search_pack -> one_time_search_pack` renewals only; expired monthly-to-one-time downgrades keep their existing semantics until product decides otherwise.
- Auggie semantic retrieval was attempted for review and returned HTTP 429, so this review used direct diff inspection plus previously gathered code/test context.

### Recommended Tests / Validation
- Keep `test_one_time_renewal_keeps_project_history_and_reopens_keyword_slot`; it is the regression lock for both customer-history retention and fresh-keyword access after renewal.
- Keep the stale-rules billing-page E2E case from the pre-existing frontend change; it guards against post-payment UI regressions caused by mixing billing and rules snapshots.

### Rollout Notes
- No schema migration is required; the renewal behavior is applied at reconciliation time using existing profile state.
- Historical data remains preserved because profiles are deactivated rather than deleted and project listing remains tenant-scoped.
- The operational behavior is narrow and reversible: if product later wants a different reset policy, the new logic is isolated to the reconciliation path.


## Implementation (2026-05-18 06:23:44 +07) - cycle-aware renewal entitlements

### Goal
- Make renewed one-time packs start with a fresh single-keyword slate without deleting historical crawl data.
- Preserve archive export/download access for previously paid tenants, including monthly members who lapse into free-trial mode.
- Prevent new/manual crawl starts until the current cycle has a keyword, and expose the effective plan in the user header.

### What changed
- `packages/crawler-core/src/egp_crawler_core/discovery_authorization.py`: added shared effective-entitlement resolution for active subscriptions, renewed one-time cycles, and expired-monthly → free-trial fallback so API and worker paths use the same rule.
- `packages/db/src/egp_db/repositories/profile_repo.py`: added cycle repair support that deactivates only stale active profiles created before the new cycle boundary; projects/documents remain untouched.
- `apps/api/src/egp_api/services/entitlement_service.py`: applied cycle repair before counting keywords, added archive access retention for paid history, and changed capability checks so archive-only access can remain valid after active crawling entitlement ends.
- `apps/api/src/egp_api/services/rules_service.py` and `run_service.py`: count only current-cycle keywords, show repaired profile state, and reject run/recrawl starts when no active current-cycle keyword exists.
- `apps/worker/src/egp_worker/scheduler.py` and `workflows/discover.py`: reused the same cycle resolver and repair stale profiles before scheduled/live discovery authorization.
- `apps/api/src/egp_api/services/auth_service.py`, `routes/auth.py`, and bootstrap wiring: added effective-plan summary fields to `/v1/me`.
- `apps/web/src/app/(app)/projects/page.tsx`: replaced the dead-end disabled recrawl state with a first-keyword modal that creates the new keyword before scraping can proceed.
- `apps/web/src/components/layout/app-header.tsx`: shows the effective subscription label beside the tenant slug.
- Regenerated `apps/web/src/lib/generated/openapi.json` and `api-types.ts` after the `/v1/me` contract change.

### TDD evidence
- Added/changed tests:
  - `test_active_one_time_pack_retires_profiles_from_before_current_cycle`
  - `test_expired_monthly_membership_falls_back_to_free_trial_with_archive_access`
  - `test_run_creation_requires_keyword_in_current_cycle`
  - `test_me_includes_effective_subscription_summary`
  - Playwright: `projects page prompts for a new keyword before crawling an empty cycle`
- RED command:
  - `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py tests/phase4/test_auth_api.py -q`
  - Initial failures proved the old behavior: renewed one-time packs still counted old keywords, expired monthly still reported monthly membership, runs could start with no current-cycle keyword, and `/v1/me` lacked effective-plan fields.
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase4/test_entitlements.py tests/phase4/test_auth_api.py tests/phase1/test_worker_live_discovery.py -q`
  - `./.venv/bin/python -m pytest tests/phase2/test_rules_api.py tests/phase3/test_invoice_lifecycle.py tests/phase4/test_entitlements.py tests/phase4/test_auth_api.py tests/phase1/test_worker_live_discovery.py -q`
  - `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts`
  - `cd apps/web && npm test`

### Validation run
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase4/test_entitlements.py tests/phase4/test_auth_api.py` ✅
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages` ✅
- `cd apps/web && npm run test:unit` ✅
- `cd apps/web && npm run typecheck` ✅
- `cd apps/web && npm run lint` ✅
- `cd apps/web && npm run build` ✅
- `cd apps/web && npm test` ✅

### Wiring verification
- `/v1/me` now carries effective plan fields from `AuthService` → `CurrentSessionResponse` → generated web types → `AppHeader`.
- Both API entitlement checks and worker discovery paths call the same shared resolver before authorizing new crawl work.
- The projects-page modal calls the existing `createRuleProfile()` API, whose backend path already enqueues first discovery jobs for active profiles.

### Behavior and risk notes
- Historical scraped projects/documents are preserved; only stale active watchlists are retired when the relevant cycle boundary requires a fresh slate.
- Fail-closed behavior remains for fresh crawling: no current-cycle keyword means no new run/recrawl.
- Archive access is intentionally broader than before for tenants with paid history: exports/downloads remain available even when active crawl entitlement has lapsed.
- I attempted Auggie semantic retrieval before editing, but it returned HTTP 429 repeatedly; this change was implemented from direct file inspection and exact-string searches instead.

### Follow-ups / known gaps
- The monthly fallback currently models ongoing free-trial behavior after lapse, per the requested product rule; if you later want that fallback to expire after a separate grace window, that should be specified as an explicit policy.


## Review (2026-05-18 06:24:55 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commands Run: `git status --short`, `git diff --stat`, targeted `git diff -- <paths>`, targeted pytest suites, Ruff, web unit/typecheck/lint/build/Playwright suites

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No remaining findings after review. During review I found and fixed one edge case before finalizing: a future pending one-time renewal could have been mistaken for an older renewal cycle and prematurely retired the current active keyword. The resolver now requires the comparison cycle to start earlier, and `test_future_one_time_renewal_does_not_retire_current_cycle_profile` covers it.

LOW
- No findings.

### Open Questions / Assumptions
- I treated expired monthly → free-trial fallback as an ongoing product state, not a separate seven-day grace window, because that is the rule the user specified.
- Archive access is intentionally retained for tenants with prior paid history even when fresh crawling is no longer allowed.

### Recommended Tests / Validation
- Already run: focused backend suites, worker discovery suite, Ruff, compileall, web unit tests, typecheck, lint, build, targeted projects-page Playwright, and full web Playwright suite.
- If this policy is later expanded again, add an explicit product test for the new transition rather than reusing the monthly fallback implicitly.

### Rollout Notes
- Existing historical projects/documents are preserved; only stale active watchlists are deactivated at cycle boundaries.
- `/v1/me` response shape changed; web generated API types were regenerated in the same change.
- Auggie semantic retrieval was attempted for review but returned HTTP 429, so review relied on direct diff inspection and executed tests.


## Delivery (2026-05-18 06:27:01 +07) - PR submission status

- Created Graphite branch `05-18-fix_entitlements_align_renewal_cycles_and_archive_access` with commit `dd971eb1`.
- Submitted PR #97: `fix(entitlements): align renewal cycles and archive access`.
- Remote merge is currently blocked by GitHub Actions infrastructure behavior, not by local code failures:
  - PR #97 `CI Pipeline` failed every job in 1–2 seconds with empty `steps` arrays.
  - The latest `main` CI run shows the same pattern, so the gate is failing before jobs actually execute.
- Per merge-train policy, I did **not** bypass required checks or merge while the required remote gate is red.


## Implementation (2026-05-18 09:40:38 +07) - completed crawl visibility after first keyword

### Goal
- Investigate the reported “crawler stopped” behavior for `vbs.pod@gmail.com` after adding `ที่ปรึกษา`.
- Fix the actual gap if the runtime was healthy but the product misrepresented the outcome.

### Investigation result
- Live PostgreSQL inspection showed the tenant had the expected active one-time pack, the old `ระบบสารสนเทศ` profile was inactive, and the new `ที่ปรึกษา` profile was active.
- Discovery job `e4bff914-0d1b-4dea-b59d-9a672b6d263d` was dispatched.
- Run `801359f0-536a-46b3-8693-d5e52d68faaa` finished successfully on May 18, 2026 with `projects_seen = 0` and `live_progress.stage = keyword_no_results`.
- Therefore the worker did not stall; the Projects page hid the completed zero-result outcome, making success look like silence.

### What changed
- `apps/web/src/app/(app)/projects/page.tsx`
  - keeps a latest completed-run card visible when there are no active runs;
  - shows terminal progress such as `ไม่พบผลลัพธ์ · คำค้น "..."` instead of disappearing;
  - starts manual run tracking after first-keyword creation, refetches runs immediately, and clears tracking once a terminal run is observed;
  - uses status-aware labels/colors for succeeded, partial, and failed latest runs;
  - updates the panel copy so it promises queue/active/completed state, not only active work.
- `apps/web/tests/e2e/projects-page.spec.ts`
  - added a regression proving that after the first keyword is created, a fast succeeded zero-result run remains visible to the user.

### TDD evidence
- Added/changed test: `projects page prompts for a new keyword before crawling an empty cycle` now asserts the completed zero-result run card.
- RED command:
  - `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts`
  - Failure: after first-keyword creation, the page showed only “waiting for worker” and never surfaced the completed run result.
- GREEN commands:
  - `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts`
  - `cd apps/web && npm run test:unit && npm run lint && npm run build && npm test`

### Tests run
- `cd apps/web && npm run typecheck` ✅
- `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts` ✅
- `cd apps/web && npm run test:unit && npm run lint && npm run build && npm test` ✅

### Wiring verification
- The first-keyword modal still calls `createRuleProfile()`; after success it now seeds the same tracking state used by manual recrawl and refetches the existing `/v1/runs` query.
- The existing `RunDetailResponse` / `live_progress` contract is reused; no new backend API surface was introduced.

### Behavior and risk notes
- The system remains fail-closed for actual crawl authorization; this change only improves observability of successful/failed terminal outcomes.
- The user will now see when e-GP returns zero results instead of interpreting a hidden completed run as a crawler stop.
- Auggie semantic retrieval was attempted before editing and again returned HTTP 429, so the work used direct inspection plus live DB/runtime evidence.


## Review (2026-05-18 09:41:43 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commands Run: `git status --short`, `git diff --stat`, targeted `git diff -- <paths>`, `npm run typecheck`, targeted Playwright, and the previously completed full web unit/lint/build/Playwright suite

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No remaining findings after review. During review I tightened two terminal-state edge cases before finalizing: first-keyword tracking now clears when a terminal run is observed, and terminal fallback copy now distinguishes succeeded / partial / failed instead of reusing an “already started” message for failed runs.

LOW
- No findings.

### Open Questions / Assumptions
- The live `ที่ปรึกษา` run truly returned zero current e-GP results; this change does not alter crawler search semantics, only how the already-recorded outcome is surfaced.
- I assume keeping the latest completed crawl visible on the Projects page is desirable product behavior for all tenants, not only one-time renewal flows.

### Recommended Tests / Validation
- Already run: web unit tests, typecheck, lint, production build, targeted Projects page Playwright suite, and full web Playwright suite.
- If future UX work changes run visibility again, preserve a regression for `keyword_no_results` so zero-result success never becomes silent again.

### Rollout Notes
- No API or database migration is required; this is a web-only observability fix reusing existing run data.
- Auggie review retrieval was attempted but returned HTTP 429, so review relied on direct diff inspection plus executed tests and live runtime evidence.


## Implementation Summary (2026-05-18 16:33:04 +07) - transient no-results recovery

### Goal
- Investigate why tenant `vbs.pod@gmail.com` received a successful zero-project crawl for keyword `ที่ปรึกษา` despite a visible matching e-GP result.
- Prevent the live worker from classifying a transient empty shell as a final no-results response before real rows finish loading.

### What changed
- `apps/worker/src/egp_worker/browser_discovery.py`
  - Added `NO_RESULTS_STABLE_POLLS = 3` and changed `wait_for_results_ready()` so no-results must remain stable across three polls before being accepted; real rows still win immediately when they appear.
  - Added `log_results_debug_snapshot(..., "keyword_no_results")` before emitting the terminal no-results progress event so future worker logs include table/header/row diagnostics instead of only a bare zero-result outcome.
- `tests/phase1/test_worker_browser_discovery.py`
  - Added a regression test proving that one transient no-results shell does not end readiness waiting when rows arrive on the next poll.

### TDD evidence
- RED: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_results_ready_waits_past_transient_no_results_shell_until_rows_arrive'`
  - Failed because the old implementation returned after the first no-results shell (`assert len(row_checks) == 2`, observed `1`).
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_results_ready_waits_past_transient_no_results_shell_until_rows_arrive or retries_same_keyword_no_results_shell_from_clean_search_page or get_results_rows_filters_placeholder_no_results_row'`
  - Passed after requiring stable no-results detection.

### Tests run
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_results_ready_waits_past_transient_no_results_shell_until_rows_arrive'` — RED, then fixed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_results_ready_waits_past_transient_no_results_shell_until_rows_arrive or retries_same_keyword_no_results_shell_from_clean_search_page or get_results_rows_filters_placeholder_no_results_row'` — 3 passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q` — 68 passed.
- `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_discovery.py tests/phase1/test_worker_browser_discovery.py` — passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q` — 11 passed.
- `cd apps/web && npm run typecheck` — passed.
- `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts` — 3 passed.

### Wiring verification
- `crawl_live_discovery()` calls `search_keyword()` and then `is_no_results_page()` before `_collect_keyword_projects()`; hardening `wait_for_results_ready()` changes the exact gate that prematurely skipped project collection for this tenant.
- Existing worker log evidence for run `801359f0-536a-46b3-8693-d5e52d68faaa` showed only `keyword_start -> keyword_no_results` with no `page_scan_finished` or pagination events, confirming the bug was pre-pagination rather than a 15-page cap issue.

### Behavior / risk notes
- The fix intentionally adds up to roughly two extra seconds before accepting a true no-results page, favoring correctness over a slightly faster empty-search exit.
- Future false no-results cases will now leave richer diagnostics in `worker.log` so we can distinguish table-shape problems from genuinely empty searches.
- Auggie semantic retrieval was attempted first for this edit but returned HTTP 429, so the investigation used direct file inspection and exact-string searches as the documented fallback.


## Implementation Summary (2026-05-18 16:36:26 +07) - restore post-search stabilization

### Goal
- Close the remaining gap after the first no-results fix by restoring the stabilization phase that existed in the legacy crawler but had been lost in the worker extraction.

### What changed
- `apps/worker/src/egp_worker/browser_discovery.py`
  - Added `_wait_for_search_results_stable()` and wired it into `search_keyword()` after `wait_for_results_ready()`.
  - The helper waits for late-arriving rows to become stable before the worker decides whether the keyword really has zero results.
- `tests/phase1/test_worker_browser_discovery.py`
  - Added a regression test covering rows that appear only after several initial empty polls.

### TDD evidence
- RED: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_search_results_stable_waits_for_late_rows'`
  - Failed at collection because `_wait_for_search_results_stable` did not exist yet.
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_results_ready_waits_past_transient_no_results_shell_until_rows_arrive or wait_for_search_results_stable_waits_for_late_rows or retries_same_keyword_no_results_shell_from_clean_search_page'`
  - Passed after adding and wiring the stabilization helper.

### Tests run
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_search_results_stable_waits_for_late_rows'` — RED.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k 'wait_for_results_ready_waits_past_transient_no_results_shell_until_rows_arrive or wait_for_search_results_stable_waits_for_late_rows or retries_same_keyword_no_results_shell_from_clean_search_page'` — 3 passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q` — 69 passed.
- `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_discovery.py tests/phase1/test_worker_browser_discovery.py` — passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q` — 11 passed.

### Wiring verification
- The new helper is called directly from `search_keyword()` before the subsequent `is_no_results_page()` gate used by `crawl_live_discovery()`.
- This restores the legacy crawler's post-search stabilization behavior in the modern worker path instead of relying only on the first render check.

### Behavior / risk notes
- True zero-result searches can now take several extra seconds to settle, but late-rendering real rows are materially less likely to be discarded as false no-results.
- This change is deliberately conservative: it favors finding real projects over shaving a few seconds from empty searches.


## Review (2026-05-18 16:37:00 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree
- Commands Run: `git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff` reads for worker/web changes, `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q`, `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_discovery.py tests/phase1/test_worker_browser_discovery.py`, `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py -q`, `cd apps/web && npm run typecheck`, `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts`

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
- The live e-GP site can transiently render an empty-state shell before rows arrive; the new worker behavior deliberately treats that as provisional until it has stayed empty across repeated polls and a stabilization window.
- Real-site timing can still vary more than local tests model, but the worker now mirrors the older crawler's missing stabilization behavior and records a debug snapshot whenever it still concludes `keyword_no_results`.
- Auggie retrieval was attempted for the review and returned HTTP 429, so the review used direct diff inspection and exact-string searches as fallback.

### Recommended Tests / Validation
- Re-run a manual crawl for `ที่ปรึกษา` under tenant `vbs.pod@gmail.com` after deploying this worker change and confirm the worker log shows `page_scan_finished` events plus discovery of the visible consulting project.
- If the live site still reports zero projects, inspect the newly added `DEBUG [keyword_no_results]` lines in `worker.log`; they should now expose whether the procurement table is absent, empty, or malformed at decision time.

### Rollout Notes
- True zero-result searches now wait a few seconds longer before finishing; that is an intentional correctness tradeoff.
- No schema or API changes are involved. The web observability changes remain backwards-compatible and make completed zero-result runs visible instead of disappearing from the page.


## Implementation Summary (2026-05-18 17:27:37 +07) - refresh projects after completed crawl

### Goal
- Investigate why the projects page showed a completed crawl with 6 discovered projects while the table still displayed only the previous 14 projects for tenant `vbs.pod@gmail.com`.

### Findings
- Live database inspection showed the worker path is correct: run `24db26a5-ed9a-4292-a575-827c7f11b2e7` completed with `projects_seen: 6`, and the six `ที่ปรึกษา` projects were persisted as new project rows on 2026-05-18 between 17:12 and 17:17 Asia/Bangkok.
- The stale behavior was frontend-only: the projects page kept polling run status, but once a run became terminal it did not refresh the projects query, so the table retained the pre-run cache until a manual reload.

### What changed
- `apps/web/src/app/(app)/projects/page.tsx`
  - Added a one-time completed-run refresh guard using `useRef`.
  - When a completed run card becomes visible, the page now refetches the active projects query once for that run ID so newly persisted projects appear without a manual reload.
- `apps/web/tests/e2e/projects-page.spec.ts`
  - Added an end-to-end regression test that starts from an old project list, surfaces a completed crawl, and verifies the table refreshes to show the newly discovered project and updated total.

### TDD evidence
- RED: `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts -g 'refreshes table after a completed crawl becomes visible'`
  - Failed because the new project never appeared after the completed run became visible.
- GREEN: `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts -g 'refreshes table after a completed crawl becomes visible'`
  - Passed after wiring the completed-run project refetch.

### Tests run
- `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts -g 'refreshes table after a completed crawl becomes visible'` — RED, then GREEN.
- `cd apps/web && npm run typecheck` — passed.
- `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts` — 4 passed.
- `cd apps/web && npm run test:unit` — 23 passed.
- `cd apps/web && npm run lint` — passed.
- `cd apps/web && npm run build` — passed.

### Wiring verification
- `useRuns()` already drove the completed-run card; the new effect hooks that same terminal card to `refetchProjects()` from the active `useProjects(projectQuery)` query.
- The refresh is guarded by completed run ID, so a visible terminal card does not trigger an endless refetch loop.

### Behavior / risk notes
- Users who remain on the projects page during a crawl now see the project table catch up automatically when the run completes.
- This is intentionally UI-local; no API or persistence semantics changed.
- Auggie semantic retrieval was attempted first for this edit but returned HTTP 429, so the investigation used direct file inspection and exact-string searches as documented fallback.


## Review (2026-05-18 17:28:10 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree
- Commands Run: targeted `git diff --stat`, targeted diff reads for `apps/web/src/app/(app)/projects/page.tsx` and `apps/web/tests/e2e/projects-page.spec.ts`, `cd apps/web && npm run typecheck`, `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts`, `cd apps/web && npm run test:unit`, `cd apps/web && npm run lint`, `cd apps/web && npm run build`

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
- The intended behavior is that a completed crawl refreshes the currently visible project list once; changing filters/pages already creates a new React Query key and fetches independently.
- The terminal-run refresh is guarded by run ID to avoid a refetch loop while the completed run card remains visible.
- Auggie retrieval was attempted for review and returned HTTP 429, so this review used direct diff inspection and exact-string searches as fallback.

### Recommended Tests / Validation
- The added Playwright case covers the previously missing path: old project list -> completed run visible -> table refreshes to updated project list.
- Manual browser validation for `vbs.pod@gmail.com`: reload `/projects` and confirm total changes from 14 to 20 and the newly crawled `ที่ปรึกษา` projects appear.

### Rollout Notes
- Frontend-only change; no schema or API compatibility impact.
- Users with an already stale open tab still need one reload until this frontend change is deployed; after deployment, future terminal runs will self-refresh the table.


## Review (2026-05-18 17:43:59 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree
- Commands Run: `git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff` reads for `apps/web/src/app/(app)/projects/page.tsx` and `apps/web/tests/e2e/projects-page.spec.ts`, `cd apps/web && npm run typecheck`, `cd apps/web && npx playwright test tests/e2e/projects-page.spec.ts`

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
- The intended refresh scope is the currently visible `projectQuery`; filter/page changes already use separate React Query keys and will fetch normally.
- The one-time guard by completed run ID is sufficient to prevent a repeated-refetch loop while a terminal run card remains visible.
- Auggie retrieval was attempted first and returned HTTP 429, so this review used direct diff inspection and exact-string searches as the fallback path.

### Recommended Tests / Validation
- Existing validation already covers the critical regression: stale project list before crawl, terminal run visible, refreshed table with updated total.
- After deploy, manually verify `/projects` for `vbs.pod@gmail.com` shows 20 projects without requiring a second reload after future runs.

### Rollout Notes
- Frontend-only change; no schema or API migration risk.
- An already-open tab on the old frontend bundle can remain stale until refresh, but new sessions after deploy will self-refresh after completed runs.

## Review (2026-05-18 18:09:24 +07) - working-tree

### Reviewed
- Repo: /Users/subhajlimanond/dev/egp
- Branch: main
- Scope: working-tree
- Commands Run: `git status --porcelain=v1`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`, `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`, targeted `git diff -- <paths>`, `./.venv/bin/ruff check apps/worker packages test_egp_crawler.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py`, `./.venv/bin/python -m compileall apps/worker/src packages`, `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py test_egp_crawler.py -q`

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
- Assumed live close-check is the intended recurring revisit path for tracked projects that remain non-closed.
- Auggie semantic retrieval was unavailable in-session (HTTP 429), so review used direct file inspection plus targeted searches.

### Recommended Tests / Validation
- Keep the added revisit tests as regression coverage for later-stage document collection and non-closing document ingest.
- Consider a future live-browser smoke pass against e-GP because the new path now reopens detail pages during close-check sweeps.

### Rollout Notes
- The change increases work done during live close-check runs because tracked revisitable projects now reopen their detail pages and attempt document collection.
- Document persistence remains content-deduplicated by the existing ingest path, so revisits should not create duplicate stored files for identical bytes.

## Implementation Summary (2026-05-18 18:09:24 +07)

### Goal
- Add `วิธีเฉพาะเจาะจง` to crawler blacklists and ensure already-tracked projects can revisit detail pages to collect available documents such as `ประกาศราคากลาง` even after advancing beyond the initial invitation stage.

### What Changed
- `apps/worker/src/egp_worker/browser_discovery.py`: added `วิธีเฉพาะเจาะจง` to the modern project-name blacklist.
- `egp_crawler.py`: mirrored the new blacklist term in the legacy fallback crawler.
- `apps/worker/src/egp_worker/browser_close_check.py`: extended live close-check revisits so matched tracked projects can reopen detail pages, collect documents, and return to the search page afterward.
- `apps/worker/src/egp_worker/workflows/close_check.py`: broadened revisitable states to include discovered/public-hearing/TOR-downloaded/prelim-pricing projects and ingests revisited documents even when no close transition occurs.
- `apps/worker/src/egp_worker/main.py`: wired close-check worker payloads to pass document-revisit options and artifact storage parameters.
- Added regression coverage in `tests/phase1/test_worker_browser_discovery.py`, `tests/phase1/test_worker_live_discovery.py`, `tests/phase1/test_worker_workflows.py`, and `test_egp_crawler.py`.

### TDD Evidence
- RED: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k "specific_method_projects"` failed because `วิธีเฉพาะเจาะจง` projects were still processed.
- RED: `./.venv/bin/python -m pytest test_egp_crawler.py -q -k "skip_keywords_include_maintenance"` failed because the legacy blacklist lacked `วิธีเฉพาะเจาะจง`.
- RED: `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py -q -k "live_document_revisit or loads_open_projects_for_live_sweep_when_needed or ingests_revisited_documents_without_close_match"` failed because close-check neither revisited later states nor ingested revisit documents.
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k "specific_method_projects" && ./.venv/bin/python -m pytest test_egp_crawler.py -q -k "skip_keywords_include_maintenance"`.
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py -q -k "specific_method_projects or document_revisit_collects_documents_after_prelim_status" && ./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py -q -k "live_document_revisit or loads_open_projects_for_live_sweep_when_needed or ingests_revisited_documents_without_close_match" && ./.venv/bin/python -m pytest test_egp_crawler.py -q -k "skip_keywords_include_maintenance"`.

### Tests Run
- `./.venv/bin/ruff check apps/worker packages test_egp_crawler.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py` → passed.
- `./.venv/bin/python -m compileall apps/worker/src packages` → passed.
- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py test_egp_crawler.py -q` → `285 passed`.

### Wiring Verification
- `apps/worker/src/egp_worker/main.py` now passes `live_include_documents`, `artifact_root`, and storage credentials into `run_close_check_workflow`.
- `run_close_check_workflow` passes `include_documents=True` into `crawl_live_close_check` by default for live sweeps.
- `crawl_live_close_check` now calls `collect_downloaded_documents` after reopening matched project detail pages, and the workflow feeds those artifacts into `ingest_downloaded_documents`.

### Behavior / Risk Notes
- Revisit sweeps now cover `discovered`, `open_invitation`, `open_consulting`, `open_public_hearing`, `tor_downloaded`, and `prelim_pricing_seen` states instead of only the earliest open states.
- Revisited document ingestion is intentionally fail-closed at the task level: if document persistence raises, the close-check task is marked failed rather than silently claiming success.
- Existing document dedupe remains the safety valve for repeated revisits of unchanged files.
- Auggie semantic retrieval was unavailable (HTTP 429), so implementation used direct inspection and targeted exact-string searches per fallback policy.

### Follow-ups / Known Gaps
- A live-browser smoke run against the real e-GP site would still be valuable to confirm the detail-page reopen + return-to-search loop under production DOM timing.
- The active branch is `main`; per repo guidance, move this work to a feature branch before committing or opening a PR.

## Implementation Summary (2026-05-18 18:39:44 +07:00)

### Goal
Align project lifecycle handling with the clarified business rule: discover/download during `ประกาศเชิญชวน`, ignore projects first seen after that stage, and only revisit later statuses for projects with invitation-stage document evidence.

### What changed
- `packages/crawler-core/src/egp_crawler_core/invitation_rules.py`, `packages/crawler-core/src/egp_crawler_core/__init__.py`
  - Added reusable invitation-stage status detection.
- `apps/worker/src/egp_worker/workflows/discover.py`, `apps/worker/src/egp_worker/main.py`
  - Made live discovery collect documents by default.
  - Ignored discovery payloads that do not originate from invitation stage and exposed an `ignored_late_stage_projects` run-summary counter.
- `packages/domain/src/egp_domain/project_ingest.py`, `apps/api/src/egp_api/routes/project_ingest.py`
  - Added a fail-closed ingest guard and translated invalid direct worker-ingest attempts into HTTP 422.
- `packages/db/src/egp_db/repositories/project_queries.py`, `apps/worker/src/egp_worker/workflows/close_check.py`
  - Added invitation-stage document evidence filtering and used it when selecting projects for later-status live revisits.
- Tests updated in `tests/phase1/test_worker_live_discovery.py`, `tests/phase1/test_project_and_run_persistence.py`, and `tests/phase1/test_projects_and_runs_api.py`.
- Existing related work already present on the branch continues to add later-status document revisits in close-check flows and skip specific-method projects during discovery.

### TDD evidence
- RED command:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py::test_run_discover_workflow_downloads_live_browser_documents_by_default tests/phase1/test_worker_live_discovery.py::test_run_discover_workflow_ignores_projects_first_seen_after_invitation_stage tests/phase1/test_worker_live_discovery.py::test_run_close_check_workflow_loads_open_projects_for_live_sweep_when_needed tests/phase1/test_worker_live_discovery.py::test_run_worker_job_defaults_live_include_documents_to_true_for_discover tests/phase1/test_project_and_run_persistence.py::test_list_projects_can_filter_to_invitation_stage_document_evidence tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_rejects_late_stage_first_discovery -q`
  - Key failures: discovery still deferred documents by default, later-stage payloads were still persisted, close-check did not request invitation-stage evidence, discover worker jobs defaulted to `False`, the repository lacked the new filter, and API ingest accepted late-stage discovery.
- GREEN commands:
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py::test_run_discover_workflow_uses_metadata_only_browser_discovery_for_live_runs tests/phase1/test_worker_live_discovery.py::test_run_discover_workflow_downloads_live_browser_documents_by_default tests/phase1/test_worker_live_discovery.py::test_run_discover_workflow_ignores_projects_first_seen_after_invitation_stage tests/phase1/test_worker_live_discovery.py::test_run_close_check_workflow_loads_open_projects_for_live_sweep_when_needed tests/phase1/test_worker_live_discovery.py::test_run_worker_job_defaults_live_include_documents_to_true_for_discover tests/phase1/test_project_and_run_persistence.py::test_list_projects_can_filter_to_invitation_stage_document_evidence tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_rejects_late_stage_first_discovery -q`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_project_and_run_persistence.py tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_upserts_and_notifies_new_projects tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_rejects_late_stage_first_discovery -q`

### Tests run
- `./.venv/bin/ruff check apps/api apps/worker packages` → passed
- `./.venv/bin/python -m compileall apps packages` → passed
- Focused regression suite above → 149 passed
- Broader API slice `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_project_and_run_persistence.py tests/phase1/test_projects_and_runs_api.py -q` surfaced two unrelated pre-existing API test failures around `/v1/runs` creation/listing that are outside this change set.

### Wiring verification
- Discover CLI payload → `apps/worker/src/egp_worker/main.py::run_worker_job()` → `run_discover_workflow(... live_include_documents=True)`.
- Live discovery callback → `run_discover_workflow()` → late-stage guard before event emission / document ingest.
- Internal worker API route → `project_ingest.ingest_discovered_project()` → `ProjectIngestService.ingest_discovered_project()` guard.
- Later-stage revisit selection → `run_close_check_workflow()` → `SqlProjectRepository.list_projects(... has_invitation_stage_documents=True)`.

### Behavior changes and risk notes
- Fail-closed: discovery payloads without invitation-stage status evidence are now ignored/rejected instead of entering the project set.
- Later-status follow-up now depends on persisted invitation-stage document evidence (`documents.source_status_text` containing `ประกาศเชิญชวน`). Existing valid invitation-stage documents created through the worker satisfy this path.
- Auggie semantic retrieval was unavailable due repeated HTTP 429 responses, so the work used direct file inspection plus exact-string search fallback.

### Follow-ups / known gaps
- Historical documents with missing or malformed `source_status_text` will not qualify for later-status revisit selection until backfilled or handled by a future reconciliation job.
- The unrelated `/v1/runs` API test failures should be investigated separately before relying on the full phase1 API suite as a branch gate.

## Review (2026-05-18 18:39:44 +07:00) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree
- Commands Run:
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`
  - targeted `git diff -- <path>` inspection for changed worker/domain/api/repository files
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py tests/phase1/test_worker_workflows.py tests/phase1/test_worker_browser_discovery.py tests/phase1/test_project_and_run_persistence.py tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_upserts_and_notifies_new_projects tests/phase1/test_projects_and_runs_api.py::test_project_ingest_discover_endpoint_rejects_late_stage_first_discovery -q`
  - `./.venv/bin/ruff check apps/api apps/worker packages`
  - `./.venv/bin/python -m compileall apps packages`

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
- The later-status eligibility rule intentionally uses persisted invitation-stage document evidence, not merely “project was once discovered at invitation stage.”
- Historical documents missing `source_status_text` are treated as not proven eligible; that is a deliberate fail-closed choice, but it may need a separate backfill/reconciliation path if old data exists.
- Auggie semantic retrieval was unavailable during review due repeated HTTP 429 responses, so review relied on direct inspection plus exact-string search fallback.

### Recommended Tests / Validation
- Keep the focused 149-test regression slice as the minimum gate for this behavior.
- If historical data migration/backfill is introduced later, add an integration test proving qualifying old projects still enter the close-check sweep after reconciliation.

### Rollout Notes
- Behavioral change is intentionally stricter: projects first observed outside invitation stage will no longer enter tracking, and projects without invitation-stage document evidence will not be revisited in later statuses.
- No schema migration is required for this patch.
