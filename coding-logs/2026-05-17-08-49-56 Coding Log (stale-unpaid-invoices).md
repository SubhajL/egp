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
