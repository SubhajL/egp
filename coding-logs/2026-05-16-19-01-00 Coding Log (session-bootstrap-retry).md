# Session bootstrap retry

## Exploration note

Auggie semantic search was attempted first but returned HTTP 429. Investigation used direct inspection of:
- `apps/web/src/app/(app)/layout.tsx`
- `apps/web/src/lib/hooks.ts`
- `apps/web/tests/unit/hooks.test.ts`
- `apps/web/tests/e2e/auth-pages.spec.ts`
- current local API/web process state and recent runtime logs

## Plan Draft A — retry transient `/v1/me` failures

### Overview
Keep 401 handling strict, but let the current-session query automatically retry non-401 failures so temporary API restarts/network hiccups do not strand the user on a full-page error state.

### Files to change
- `apps/web/src/lib/hooks.ts`
- `apps/web/tests/unit/hooks.test.ts`
- `apps/web/tests/e2e/auth-pages.spec.ts` or focused layout coverage if needed

### TDD sequence
1. Add a unit test for the retry predicate: 401 should not retry; 500/network-style errors should retry.
2. Run RED and confirm `useMe()` currently has `retry: false`.
3. Implement a named retry helper and wire it into `useMe()`.
4. Add/adjust UI behavior only if needed after focused browser verification.

### Decision completeness
- Goal: transient session bootstrap failures recover automatically.
- Non-goals: do not change login redirect semantics; do not mask persistent backend failures forever.
- Success criteria: 401 still redirects to login; non-401 errors are retried a bounded number of times before the existing user-facing error appears.
- Public interfaces: none.
- Failure modes: fail closed on 401; retry transient failures up to a small bounded count.

## Plan Draft B — use stored session as stale fallback

### Overview
Hydrate the shell from localStorage when `/v1/me` fails transiently, then refresh in the background.

### Trade-offs
This would avoid the blank screen, but it risks showing stale authorization state and is more invasive than needed for a transient retry problem.

## Unified execution plan

Use Draft A. Add a small, testable retry policy and keep the current error state as the eventual fallback only after bounded retries are exhausted.

### Wiring verification
| Component | Entry Point | Registration Location | Schema/Table |
|---|---|---|---|
| session retry helper | `useMe()` | `apps/web/src/lib/hooks.ts` | N/A |
| app shell fallback | `(app)/layout.tsx` | existing route-group layout | N/A |


## Implementation Summary (2026-05-16 19:05:53 +07)

### Goal
Prevent transient `/v1/me` failures from immediately collapsing the authenticated app shell into the full-page user-load error, while keeping real unauthorized sessions fail-closed.

### What changed
- `apps/web/src/lib/hooks.ts`
  - Added `shouldRetryCurrentSession()`.
  - Wired `useMe()` to retry non-401 failures twice, but never retry 401 responses.
- `apps/web/tests/unit/hooks.test.ts`
  - Added regression coverage for the retry policy: 401 stops immediately; transient 500/network-style failures retry only within the bounded limit.
- `apps/web/src/app/(app)/security/page.tsx`
  - Normalized the `useMe()` error before passing it into `QueryState`, keeping the prop type-safe once the query error is treated as `unknown`.

### TDD evidence
- Added tests: `shouldRetryCurrentSession` cases in `apps/web/tests/unit/hooks.test.ts`.
- RED: `cd apps/web && npm run test:unit`
  - Failed because `shouldRetryCurrentSession` did not exist yet (`TypeError: shouldRetryCurrentSession is not a function`).
- GREEN: `cd apps/web && npm run test:unit`
  - Passed after adding the retry helper and wiring it into `useMe()`.

### Validation run
- `cd apps/web && npm run test:unit` — passed.
- `cd apps/web && npm run typecheck` — initially failed on `apps/web/src/app/(app)/security/page.tsx` because an `unknown` query error was passed into `QueryState`; passed after normalizing that prop.
- `cd apps/web && npm run lint` — passed.
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts -g "redirects unauthenticated protected pages to login"`
  - First focused run landed on `/security` as a 404 while the security page still had the type issue above.
  - Rerun after the type-safe `QueryState` fix passed.

### Wiring verification
- Runtime entry point: `(app)/layout.tsx` still consumes `useMe()` for auth gating.
- New helper is not dead code: `useMe()` passes `retry: shouldRetryCurrentSession` directly into React Query.
- Unauthorized flow remains wired to the existing redirect effect in `(app)/layout.tsx`; the focused Playwright auth-gate test passed after the fix.

### Behavior / risk notes
- Fail-closed behavior remains unchanged for 401s: stored session is cleared and the app redirects to login without retrying.
- Transient non-401 failures now get two automatic retries before the existing user-facing error appears, which reduces false-negative app-shell failures during short API hiccups.
- This does not mask persistent backend failures forever; the retry window is intentionally bounded.
- Auggie semantic retrieval was attempted twice during implementation and once before the type-safe security-page edit, but each call returned HTTP 429, so the change used direct file inspection plus exact-string searches.

### Follow-ups / known gaps
- No new browser-level transient-recovery test was added; current coverage is unit-level for the retry policy plus existing browser coverage for the 401 redirect path.


## Review (2026-05-16 19:06:05 +07) - targeted working-tree auth bootstrap change

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: targeted working-tree diff for `apps/web/src/lib/hooks.ts`, `apps/web/tests/unit/hooks.test.ts`, and `apps/web/src/app/(app)/security/page.tsx`
- Commands Run: `git diff --stat -- <targeted files>`, `git diff -- <targeted files>`, `npm run test:unit`, `npm run typecheck`, `npm run lint`, focused Playwright auth redirect test

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
- Assumption: `/v1/me` continues to use 401 for unauthenticated sessions; other non-401 failures are safe to treat as transient candidates for bounded retry.
- Assumption: two retries is an acceptable latency/recovery tradeoff for short local API restarts or brief network hiccups.

### Recommended Tests / Validation
- Keep the new unit retry-policy coverage in place.
- If this path regresses again, add a browser-level test where `/v1/me` returns one transient 500 before succeeding, so the app shell recovery behavior is asserted end-to-end.

### Rollout Notes
- No schema or API contract changes.
- Behavior is backward-compatible except that transient app-shell failures may now recover automatically instead of surfacing immediately.
- 401 handling remains fail-closed and was revalidated with the focused auth redirect Playwright test.


## Implementation Summary (2026-05-16 19:37:12 +07)

### Goal
Fix the repeated local browser 404s by preventing concurrent Next.js dev servers from corrupting the primary server's live dev build artifacts.

### What changed
- `apps/web/scripts/dev-web.sh`
  - Removed the destructive `rm -rf "$NEXT_DIST_DIR"` startup step so launching another dev server no longer deletes assets that an existing server is still serving.
- `apps/web/playwright.config.ts`
  - Gave the Playwright-managed server its own `NEXT_DIST_DIR` (`.next-playwright`) instead of letting it share `.next-dev` with the local server on port 3002.
- `apps/web/tests/unit/dev-web-script.test.ts`
  - Added regression coverage for both invariants: the dev script must preserve its dist dir, and the Playwright server must use an isolated dist dir.

### TDD evidence
- Added tests: `dev web script` cases in `apps/web/tests/unit/dev-web-script.test.ts`.
- RED 1: `cd apps/web && npm run test:unit`
  - Failed because `scripts/dev-web.sh` still contained `rm -rf "$NEXT_DIST_DIR"`.
- RED 2: `cd apps/web && npm run test:unit`
  - Failed because `playwright.config.ts` did not yet set `NEXT_DIST_DIR: ".next-playwright"`.
- GREEN: `cd apps/web && npm run test:unit`
  - Passed after removing the deletion and isolating the Playwright server dist dir.

### Validation run
- `cd apps/web && npm run test:unit` — passed.
- `cd apps/web && sh -n scripts/dev-web.sh` — passed.
- `cd apps/web && npm run typecheck` — passed.
- `cd apps/web && npm run lint` — passed.
- `cd apps/web && npx playwright test tests/e2e/auth-pages.spec.ts -g "redirects unauthenticated protected pages to login"` — passed.
- Live runtime check after the Playwright server started: `curl` requests to `http://127.0.0.1:3002/`, `/dashboard`, and `/security` all returned `200`.

### Wiring verification
- `apps/web/scripts/dev.sh` still starts the primary local frontend through `./scripts/dev-web.sh`, which now defaults to `.next-dev` without deleting it.
- `apps/web/playwright.config.ts` still starts the test frontend through `npm run dev:web`, but now overrides `NEXT_DIST_DIR` to `.next-playwright`.
- `apps/web/next.config.mjs` already honors `process.env.NEXT_DIST_DIR`, so the new Playwright override is active at runtime.

### Behavior / risk notes
- Before the fix, starting the Playwright dev server could delete or overwrite the primary local server's `.next-dev` files, producing repeated browser 404s and later `ENOENT` 500s such as missing `server/app/(app)/dashboard/page.js`.
- After the fix, local dev and Playwright servers write to separate build directories, so one server no longer invalidates the other's compiled pages.
- Preserving dev artifacts across restarts is intentional; Next's compiler can refresh them safely, while cross-process deletion was unsafe.
- Auggie semantic retrieval was attempted before investigation and before both edit phases, but each call returned HTTP 429, so this work used direct file inspection, process inspection, and live runtime evidence.

### Follow-ups / known gaps
- Manual extra dev servers launched outside Playwright still need distinct `NEXT_DIST_DIR` values if they are run concurrently on purpose; the common local-vs-Playwright collision is now isolated by default.


## Review (2026-05-16 19:37:38 +07) - targeted working-tree local dev artifact isolation

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: targeted working-tree diff for `apps/web/scripts/dev-web.sh`, `apps/web/playwright.config.ts`, and `apps/web/tests/unit/dev-web-script.test.ts`
- Commands Run: targeted `git diff --stat`, targeted `git diff`, `npm run test:unit`, `sh -n scripts/dev-web.sh`, `npm run typecheck`, `npm run lint`, focused Playwright auth test, live `curl` checks against port 3002

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
- Assumption: the only routinely concurrent second frontend server is Playwright's port-3100 server; that path is now explicitly isolated.
- Assumption: preserving the primary `.next-dev` directory between launches is acceptable because Next's compiler can invalidate stale files safely on startup.

### Recommended Tests / Validation
- Keep the new script/config invariants under unit test.
- Re-run the focused Playwright test while the local 3002 server is up whenever dev-server bootstrap wiring changes.
- For future multi-server support beyond Playwright, consider a port-derived `NEXT_DIST_DIR` strategy rather than relying on callers to choose one.

### Rollout Notes
- Local-development-only behavior change; no production runtime or API contract impact.
- Existing broken 3002 processes need one restart after the fix so they rebuild from a clean dev directory; a fresh restart was performed during validation.
- Live validation after Playwright launch showed `/`, `/dashboard`, and `/security` remained healthy with HTTP 200.


## Review (2026-05-17 06:35:57 +07) - system

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: billing UX/payment-resumption subsystem
- Commands Run: targeted `rg`, direct reads of billing page/service/repository/tests, official Opn PromptPay docs lookup
- Sources: `apps/web/src/app/(app)/billing/page.tsx`, `apps/api/src/egp_api/services/billing_service.py`, `apps/api/src/egp_api/services/payment_provider.py`, `packages/db/src/egp_db/repositories/billing_payments.py`, `packages/db/src/egp_db/repositories/billing_subscriptions.py`, `tests/phase3/test_invoice_lifecycle.py`, `apps/web/tests/e2e/billing-page.spec.ts`

### As-Is Pipeline Diagram
- Expired/free-trial entitlement -> billing page derives visible upgrade options -> open upgrade invoices suppress duplicate CTAs -> user may select an old unpaid invoice in the record list -> clicking “create PromptPay QR” creates a fresh provider request for the same record -> on settlement, subscription activation reuses that record’s original billing period dates -> entitlement service derives active vs expired from those stored dates.

### High-Level Assessment
- The current flow is good at preventing duplicate upgrade invoices, but it conflates “an unpaid commercial intent exists” with “that exact invoice is still a valid path to restored service.”
- For one-time packs, that assumption breaks once the original service window is already in the past.
- The UI currently hides the one-time CTA when an open one-time upgrade exists, even if that open invoice is stale and no longer a sensible product to pay.

### Drift Matrix
| Intended | Implemented | Impact | Fix direction |
|---|---|---|---|
| Old unpaid invoice should remain safe to resume | Any payable open invoice can create a new QR regardless of service-period age | Customer can pay for a period that has already ended | Distinguish resumable vs stale open invoices |
| One-time CTA should guide the fastest valid recovery path | Open one-time upgrade suppresses duplicate one-time CTA entirely | LHS only shows monthly, hiding the natural recovery action | Replace hidden CTA with resume/replace semantics |
| PromptPay expiry should be clear and current | UI requests `expires_in_minutes: 30`, but OPN provider does not forward that to charge creation | Product copy/expectation can diverge from actual provider expiry | Either pass explicit expiry to OPN or align UI with provider default |
| Expired payment artifacts should stop looking live | Request status can remain `pending` after `expires_at` without local expiry reconciliation | Stale QR can still look actionable | Derive/display expired-by-time and offer regenerate |
| Payment after expiry should restore service | Settlement reuses original billing period and can create an immediately expired subscription | Successful payment may not restore access | Reissue/supersede stale invoices before payment |

### Strengths
- Duplicate upgrade-invoice prevention is intentional and tested.
- The billing page already has the right conceptual split between current entitlement, upgrade options, and billing history.
- Fresh payment requests can be generated for an existing record; the backend does not depend on an old QR remaining alive.

### Key Risks / Gaps (severity ordered)
CRITICAL
- A stale unpaid one-time-pack invoice whose `billing_period_end` is before today can still be paid; settlement will activate a subscription using the old dates, which is immediately `expired` and therefore does not restore service.

HIGH
- The LHS suppresses the one-time path exactly when a stale unpaid one-time invoice exists, pushing the user toward monthly even if one-time is their intended purchase.

MEDIUM
- OPN PromptPay QR default expiry is 24 hours per official docs, while the frontend asks for 30 minutes but the OPN provider currently ignores that request field.
- Payment request status can remain `pending` in local data after provider-side expiry unless a callback updates it.

LOW
- The right-side record list is doing too much explanatory work for the primary customer decision.

### Tactical Improvements (1–3 days)
1. Classify open upgrade invoices as `resumable` vs `stale` based on service-period validity and latest request expiry.
2. In the LHS, replace the hidden duplicate one-time CTA with:
   - `ดำเนินการชำระ One-Time Search Pack ต่อ` for resumable open invoices.
   - `เริ่ม One-Time Search Pack รอบใหม่` for stale ones.
3. For stale one-time invoices, cancel/supersede and create a fresh invoice beginning today before generating QR.
4. Treat `expires_at < now` as expired in the UI even if stored status is still `pending`, and present “สร้าง QR ใหม่” instead of a misleading live state.
5. Either pass explicit `expires_at` into OPN charge creation or remove the 30-minute promise from this path and align around OPN’s actual expiry behavior.

### Strategic Improvements (1–6 weeks)
1. Move “next best billing action” into a first-class backend object rather than reconstructing from record history in the page; it should encode `resume_existing_invoice`, `replace_stale_invoice`, or `create_new_invoice`.
2. Add explicit invoice supersession semantics so finance/audit can see that an unpaid stale invoice was replaced, not silently abandoned.

### Big Architectural Changes (only if justified)
- Not needed yet. The current model is close; the main issue is missing lifecycle semantics for stale unpaid upgrade invoices, not a wrong overall architecture.

### Open Questions / Assumptions
- Assumption: the desired product behavior is “pay now, receive future usable access,” not “pay for the originally quoted historical date window.”
- Assumption: unpaid one-time-pack intents older than their service window should be replaced rather than collected as historical debt.
- Auggie semantic retrieval was attempted twice for this review but returned HTTP 429, so the review used direct inspection and exact searches.


## Review (2026-05-17 06:49:09 +07) - system

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: follow-up billing UX decision on stale unpaid invoices
- Commands Run: prior targeted billing-page/service/repository inspection reused; no new code changes
- Sources: same billing subsystem sources as the immediately preceding review

### High-Level Assessment
- For customer-facing UX, stale unpaid invoices are better treated as history than as primary actions once their service window has already ended.
- The simpler and clearer page is: expired-plan notice + two valid forward-looking choices, while stale unpaid artifacts remain retained for audit/support outside the primary renewal flow.

### Strengths
- This direction preserves financial history while reducing cognitive load.
- It avoids presenting a technically payable but semantically invalid action as the default next step.

### Key Risks / Gaps (severity ordered)
CRITICAL
- No new findings beyond the previously documented stale-invoice settlement risk.

HIGH
- No new findings.

MEDIUM
- If stale invoices are merely hidden but still payable through deep links, the product risk remains; hiding should pair with non-resumable semantics.

LOW
- If history is hidden too aggressively, support users may need a secondary affordance to inspect stale records.

### Tactical Improvements (1–3 days)
1. Exclude stale unpaid records from the primary customer-facing record list/default selection.
2. Keep them visible in history or support/admin context only.
3. Ensure the two standard forward-looking CTAs resurface when only stale unpaid invoices exist.
4. Block or supersede stale invoice payment attempts instead of merely hiding them.

### Strategic Improvements (1–6 weeks)
1. Add explicit invoice lifecycle states such as `stale` or `superseded` so the UI does not have to infer business meaning from dates alone.

### Big Architectural Changes (only if justified)
- Not needed; this remains a billing lifecycle refinement, not an architecture problem.

### Open Questions / Assumptions
- Assumption: for one-time packs, customer value is tied to future access, so collecting payment against an already elapsed access window is not desired behavior.


## Review (2026-05-17 06:55:58 +07) - branch pre-submit

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `05-17-fix_billing_restore_expired_renewal_flow_and_harden_web_dev`
- Scope: branch diff `main...HEAD`
- Commands Run: targeted `git diff --stat main...HEAD`, relevant pytest/ruff/frontend unit/type/lint/build checks, focused Playwright billing/project/auth checks

### Findings
CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings in the submitted change set. Separate product follow-up remains: stale unpaid one-time-pack invoices can still be semantically stale even when technically payable; that behavior was analyzed after this implementation pass but is intentionally not changed in this branch.

LOW
- No findings.

### Open Questions / Assumptions
- Assumption: this PR should capture the completed implementation work only, not the later stale-unpaid-invoice UX redesign discussion.
- Auggie semantic retrieval was attempted for the review but returned HTTP 429, so review used the branch diff plus direct code/test inspection already gathered during implementation.

### Recommended Tests / Validation
- Existing focused billing/project/auth browser checks plus unit/API contract tests are adequate for the submitted behavior.
- If stale-invoice handling is implemented next, add separate lifecycle and browser coverage rather than folding it into this PR retroactively.

### Rollout Notes
- API addition is backward-compatible (`current_subscription` is additive).
- Frontend dev-server isolation changes affect local/test infrastructure only.
- Subscription-renewal UX behavior changes are covered by backend lifecycle tests and Playwright expectations.
