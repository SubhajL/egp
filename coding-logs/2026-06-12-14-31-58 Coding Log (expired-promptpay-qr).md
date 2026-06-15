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

## Review (2026-06-12 23:03:13 +07) - system

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: discovery/crawler queue, run/task persistence, and project/runs UI truth surface for the 12-keyword TOR-style test
- Commands Run: `git rev-parse --show-toplevel`; `git branch --show-current`; `git status --porcelain=v1`; `git log -n 20 --oneline --decorate`; Auggie semantic search attempt; direct `rg`/`nl` inspection; production `psql` read-only queries through `ssh egp`; production container/env/log-path checks
- Sources: `AGENTS.md`, `apps/api/src/egp_api/services/rules_service.py`, `packages/db/src/egp_db/repositories/profile_repo.py`, `apps/api/src/egp_api/services/discovery_dispatch.py`, `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`, `apps/worker/src/egp_worker/workflows/discover.py`, `apps/web/src/app/(app)/projects/page.tsx`, `apps/web/src/app/(app)/runs/page.tsx`, `apps/web/src/lib/run-progress.ts`, production `crawl_profiles`, `discovery_jobs`, `crawl_runs`, `projects`

### High-Level Assessment
- The multi-keyword test did reach the backend queue and worker path. Production has one 12-keyword active custom profile and 12 `profile_created` discovery jobs marked `dispatched`.
- The backend currently models those 12 keywords as 12 independent single-keyword crawl runs, not as one batch run.
- All 12 recent runs finished between `2026-06-12 11:56:49+00` and `2026-06-12 12:12:19+00`; 11 succeeded with zero projects and one failed with `live crawl anomaly: keyword_no_results`.
- The tenant still has 17 projects, with latest project row created `2026-06-07 05:01:48+00`, so the Jun 12 multi-keyword run created no new project rows.
- The UI mostly watches latest run/project rows, so a fully processed zero-result batch can look like it "tried then stopped".

### Strengths
- The discovery outbox is durable enough to show all 12 profile-created jobs and final status.
- The worker writes useful live progress into `crawl_runs.summary_json`, including the keyword, even when no `crawl_tasks` row exists.
- The project page already polls `/v1/runs` and can show active/latest run cards; the missing piece is batch-aware status, not a total absence of runtime data.

### Key Risks / Gaps (severity ordered)
CRITICAL
- No critical data-loss finding in this pass. The crawler ran; it just produced no project rows.

HIGH
- Zero-result keyword runs do not create `crawl_tasks`, because tasks are only created inside `_persist_discovered_project()` after an eligible project payload exists (`apps/worker/src/egp_worker/workflows/discover.py:396-435`). Result: run/task tables cannot answer "which keywords were processed?" without parsing `summary_json`, and the runs page shows empty task keyword rows for zero-result runs.
- Profile creation bypasses the safer manual recrawl admission path. `queue_active_discovery_jobs()` calls `check_runs_admission()` and dedupes through `create_pending_discovery_job_if_absent()` (`apps/api/src/egp_api/services/rules_service.py:300-367`), but `create_profile()` only checks subscription/keyword limit then asks the repository to enqueue jobs inline (`apps/api/src/egp_api/services/rules_service.py:140-162`; `packages/db/src/egp_db/repositories/profile_repo.py:311-325`). A newly created 12-keyword profile can therefore bypass queued-run caps and create direct outbox rows without the same operator feedback semantics.
- The project page is not batch-aware. It requests only the latest 10 runs and uses one latest completed run as the post-action summary (`apps/web/src/app/(app)/projects/page.tsx:291-316`, `717-752`). For 12 queued keywords represented as 12 runs, it can show "latest job finished with 0 projects" while hiding the other 11 keywords.

MEDIUM
- `profile_created`/`profile_updated` jobs are collapsed to `crawl_runs.trigger_type='manual'` (`apps/api/src/egp_api/services/run_trigger_mapping.py:20-30`). That keeps the DB check constraint happy, but makes production run history unable to distinguish first-time profile seeding from a user-requested recrawl without joining back to `discovery_jobs`.
- Production run metadata from this incident points `worker_log_path` at `/Users/subhajlimanond/dev/egp/.data/artifacts/...`, but the current container resolves `EGP_ARTIFACT_ROOT=/var/lib/egp/artifacts` and has only `/var/lib/egp/artifacts` mounted. `RunService.get_run_log()` returns only the exact absolute path when `worker_log_path` is absolute (`apps/api/src/egp_api/services/run_service.py:170-190`, `196-208`), so old absolute dev paths make logs unavailable through the app.
- `discovery_jobs.job_status='dispatched'` is semantically overloaded. The processor marks the job dispatched after `dispatch()` returns (`apps/api/src/egp_api/services/discovery_dispatch.py:125-175`), but the subprocess dispatcher blocks on the worker completion (`apps/api/src/egp_api/services/discovery_worker_dispatcher.py:575-601`). In practice "dispatched" means "worker exited successfully enough", not merely "started".

LOW
- The 12-keyword profile was created as a second `คำค้นหลัก` custom profile, while the legacy TOR keyword set exists only in `egp_crawler.py`. There is no product-level "TOR" preset/import path, so operators can accidentally create duplicate generic groups and lose the intent of the keyword set.

### Nit-Picks / Nitty Gritty
- One keyword (`ระบบฐานข้อมูลใหญ่`) becomes failed because terminal `keyword_no_results` is treated as a live crawl anomaly, while other zero-result runs finished as succeeded with `keyword_finished`. This is confusing unless the UI separates "no matching results" from "crawler failure".
- The run task table is currently project-centric. That is reasonable for persisted project work, but it is not adequate as an audit trail for keyword-level crawling.
- The current project page refetches projects when the latest completed run changes, but no project rows were created, so the visible result table legitimately stays unchanged.

### Tactical Improvements (1-3 days)
1. Persist a keyword-level crawl task (or equivalent run item) at keyword start, even if no project is found. Finish it as `succeeded` with `projects_seen=0`, or `failed` with the live anomaly/error.
2. Make profile creation use the same discovery job service path as manual recrawl: admission check, pending-job dedupe, queued keyword response, and consistent notification/wake behavior.
3. Add a batch status surface on the project page after recrawl/profile creation: "12 keywords queued/processed, 11 completed with 0 projects, 1 failed: ระบบฐานข้อมูลใหญ่" instead of only the latest run.
4. Store `worker_log_path` as a path relative to artifact root, or normalize absolute paths containing `/tenants/...` through the current artifact root before rejecting them.
5. Introduce a first-class TOR preset/import action instead of relying on the legacy script constants.

### Strategic Improvements (1-6 weeks)
1. Add a crawl batch entity tying one user action to N keyword runs. Keep current per-keyword workers, but expose batch state for UI/admin/operator diagnostics.
2. Split discovery outbox lifecycle labels: `pending`, `claimed`, `worker_started`, `worker_finished`, `failed`. Keep `crawl_runs` as execution evidence, but avoid calling completed work only `dispatched`.
3. Normalize profile templates/presets in DB or config-managed seed data so legacy crawler constants are not the only source of truth for business keyword sets.

### Big Architectural Changes (only if justified)
- Proposal: Introduce a lightweight `crawl_batches`/`crawl_batch_items` model for user-triggered or profile-triggered multi-keyword crawls.
  - Pros: clean operator truth for multi-keyword requests, better UI progress, simple per-keyword retry/resume, no need to overload latest-run cards.
  - Cons: one schema migration and API/UI contract expansion; existing run history needs compatibility handling.
  - Migration Plan: create batch tables; write batch rows only for new profile-create/manual-recrawl actions; keep existing per-keyword run workers; backfill no historical rows initially; add UI batch card; later link discovery jobs to batch items.
  - Tests/Rollout: repository tests for batch/item lifecycle, API tests for recrawl/profile-create responses, UI tests for mixed zero-result/failure batches, production feature flag or read-only batch card first.

### Open Questions / Assumptions
- Assumption: the Jun 12 user-facing symptom refers to tenant `c717b262-07a8-477d-bb78-f36a4a814eb7` and the 12-keyword profile `697c1002-ad87-4263-b40d-5c9563dc364c`.
- Assumption: a true "no projects found" keyword should not be presented to users as a crawler failure unless the browser/search page state was abnormal.
