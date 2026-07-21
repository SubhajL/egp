# Coding Log: Keyword Groups and Membership Restoration

Date: 2026-07-21 (Asia/Bangkok)

## Problem statement and evidence

The Rules page already persists named records in `crawl_profiles` and keyword members in
`crawl_profile_keywords`, but the product presents profile creation as a single generic composer.
Users can repeatedly create groups with the same default name, cannot rename or safely pause a
group from the card, and the current “ปิดใช้งาน” action deletes every keyword in the group.

Membership lifecycle is coupled to mutations of `crawl_profiles.is_active`:

- entitlement reads and scheduled discovery call
  `deactivate_active_profiles_created_before(...)`;
- one-time renewal settlement deactivates profiles;
- current `main` contains a billing-time heuristic that reactivates any inactive profile that still
  has keywords when a monthly membership activates.

This makes `is_active` carry three incompatible meanings: user intent, plan-cycle eligibility, and
current runtime entitlement. It also makes restoration depend on the exact payment code path and
deployment version that settled the invoice.

Live production evidence for tenant `LLL` on 2026-07-21:

- the July monthly record is `paid` and its subscription is `active` for 2026-07-06 through
  2026-08-05;
- both saved groups named `คำค้นหลัก` remain `is_active = false` while retaining 1 and 12 keywords;
- production checkout HEAD is `32b9ad4` (through PR #166) and does not contain PR #167
  (`a6846166`, membership keyword-profile restoration);
- local/origin `main` is `8aedaad6`, and the worktree has one unrelated untracked user file:
  `docs/TOR KEYWORDS.md`, which this plan will not touch.

## Exploration note

Auggie semantic search did not return within the required two-second deadline. This plan therefore
uses targeted file inspection plus exact-identifier searches. Inspected paths:

- `AGENTS.md`, `CLAUDE.md`, `apps/web/AGENTS.md`, `apps/api/AGENTS.md`,
  `apps/worker/AGENTS.md`, `packages/AGENTS.md`, `packages/db/AGENTS.md`
- `apps/web/src/app/(app)/rules/page.tsx`, `page-helpers.ts`, `view-model.tsx`
- `apps/web/src/lib/api.ts`, `hooks.ts`, generated OpenAPI files
- `apps/api/src/egp_api/routes/rules.py`
- `apps/api/src/egp_api/services/rules_service.py`, `entitlement_service.py`,
  `billing_service.py`
- `apps/api/src/egp_api/bootstrap/services.py`, `repositories.py`, `middleware.py`
- `packages/db/src/egp_db/repositories/profile_repo.py`, `billing_payments.py`,
  `discovery_job_repo.py`
- `packages/crawler-core/src/egp_crawler_core/discovery_authorization.py`
- `apps/worker/src/egp_worker/scheduler.py`, `workflows/discover.py`
- migrations `001`, `004`, `015`, `016`, `024`-`027` and `docs/MIGRATION_POLICY.md`
- rules, entitlement, billing, worker, API, unit, and Playwright tests named below

---

# Plan Draft A: Separate Saved Configuration from Effective Entitlement

## 1. Overview

Treat each existing `crawl_profiles` row as a first-class named keyword group, preserve the user's
enabled/paused intent independently of subscription state, and compute whether a group can run from
the current entitlement. Membership expiry will never mutate or hide saved groups; a monthly
reinstatement will make all user-enabled historical groups runnable immediately through normal
entitlement evaluation.

## 2. Files to change

- `packages/db/src/migrations/028_keyword_group_lifecycle.sql` — add explicit user intent,
  backfill preserved groups, normalize duplicate group names, and add tenant/name uniqueness.
- `packages/db/src/egp_db/repositories/profile_repo.py` — map `enabled_by_user`, validate unique
  names, preserve keywords when pausing, and expose saved/enabled keyword queries.
- `packages/shared-types/src/egp_shared_types/enums.py` — define keyword-group effective statuses
  and reasons once for Python consumers.
- `packages/crawler-core/src/egp_crawler_core/discovery_authorization.py` — compute profile-cycle
  eligibility without database writes and authorize a profile/keyword pair.
- `packages/db/src/egp_db/repositories/billing_payments.py` — remove profile mutations from
  payment settlement after the new lifecycle is authoritative.
- `apps/api/src/egp_api/services/entitlement_service.py` — return saved, enabled, and runnable
  keyword counts without deactivating profiles.
- `apps/api/src/egp_api/services/rules_service.py` — create/update named groups, resolve effective
  statuses, preserve keywords on pause, and queue only runnable keywords.
- `apps/api/src/egp_api/routes/rules.py` — publish the additive request/response fields and stable
  structured errors.
- `apps/worker/src/egp_worker/scheduler.py` — select runnable groups without mutating them and
  deduplicate the same normalized keyword across groups.
- `apps/worker/src/egp_worker/workflows/discover.py` — fail closed if a stale queued job references
  a group that is not currently runnable.
- `apps/web/src/app/(app)/rules/page.tsx` — replace the global composer with group-oriented create,
  rename, pause/resume, and edit interactions.
- `apps/web/src/app/(app)/rules/page-helpers.ts` — add pure group form/status presentation helpers.
- `apps/web/src/app/(app)/rules/view-model.tsx` — map effective status to Thai labels, colors, and
  plan-specific guidance.
- `apps/web/src/lib/api.ts`, `apps/web/src/lib/generated/openapi.json`,
  `apps/web/src/lib/generated/api-types.ts` — adopt the additive API contract.
- `tests/phase2/test_rules_api.py`, `tests/phase4/test_entitlements.py`,
  `tests/phase3/test_invoice_lifecycle.py`, `tests/phase1/test_worker_workflows.py`,
  `tests/phase1/test_worker_live_discovery.py` — backend and worker TDD coverage.
- `apps/web/tests/unit/rules.test.ts`, `apps/web/tests/e2e/rules-page.spec.ts` — view-model and
  user-flow coverage.
- `docs/PRICING_AND_ENTITLEMENTS.md`, `docs/MANUAL_WEB_APP_TESTING.md` — document persistence,
  lifecycle semantics, and acceptance scenarios.

## 3. Implementation steps

### TDD sequence

1. Add/stub migration, repository, service, worker, API, unit, and Playwright tests.
2. Run them and confirm failures specifically show missing lifecycle fields, destructive pause,
   duplicate-name acceptance, and missing reinstatement visibility.
3. Implement the smallest schema/repository/shared-policy changes to pass backend tests.
4. Implement the smallest API and UI changes to pass contract and browser tests.
5. Refactor only duplicated eligibility/status mapping into shared pure helpers.
6. Run scoped Python, OpenAPI generation, unit, typecheck, lint, build, and Playwright gates.

### Schema and repository

- Add `crawl_profiles.enabled_by_user BOOLEAN` as an additive column. Backfill `true` for active
  rows and inactive rows that still contain keywords; backfill `false` only for empty inactive rows.
  Then set `NOT NULL DEFAULT TRUE` and synchronize legacy `is_active` to the same user-intent value.
- Keep `is_active` for one compatibility window, but document it as a deprecated mirror of
  `enabled_by_user`; no entitlement or billing path may write it independently.
- Normalize duplicate active group names per tenant. Preserve the oldest name and suffix later
  duplicates deterministically, checking collisions before creating a unique expression index on
  `(tenant_id, lower(btrim(name)))`.
- `SqlProfileRepository.assert_profile_name_available(...)` checks a normalized name within one
  tenant, excluding the current group during rename, and translates the database uniqueness error
  into `profile name already exists`.
- `SqlProfileRepository.list_profiles_with_keywords(...)` returns every saved group and keyword,
  regardless of subscription state.
- `SqlProfileRepository.list_enabled_profiles_with_keywords(...)` returns user-enabled saved
  groups only; it does not apply billing policy.
- `SqlProfileRepository.update_profile(...)` changes `enabled_by_user`/legacy `is_active` without
  deleting keyword rows. An empty group is permitted but cannot be runnable.

### Shared eligibility and entitlement

- Extend `EffectiveDiscoveryEntitlement` with enough context to evaluate a group without mutation.
  `profile_is_in_effective_cycle(...)` returns false for historical groups excluded by a one-time or
  free-fallback cycle, but returns true for all saved groups under recurring monthly membership.
- `resolve_profile_effective_status(...)` returns exactly one of:
  `running`, `paused_by_user`, `paused_by_plan`, or `blocked_quota`, plus a reason of
  `subscription_inactive`, `outside_current_plan_cycle`, `keyword_limit_exceeded`, or null.
- `build_runnable_profile_keywords(...)` filters enabled, non-empty, in-cycle groups and deduplicates
  normalized keywords. If one keyword appears in several groups, the oldest group then lowest UUID
  is the deterministic canonical run attribution; group membership remains visible in every group.
- `TenantEntitlementService.get_snapshot(...)` becomes read-only. It returns additive
  `saved_keyword_count`, `enabled_keyword_count`, `runnable_keyword_count`, and
  `runnable_keywords`; existing `active_keyword_count`/`active_keywords` remain compatibility aliases
  of runnable values.
- An over-limit configuration fails closed for discovery. Saved groups stay visible and editable,
  but no keyword runs until the owner pauses enough groups/keywords or upgrades.

### Rules API and service

- Keep the existing `/v1/rules/profiles` resource for backward compatibility while labeling it
  “keyword groups” in the product.
- `CreateRuleProfileRequest` and `UpdateRuleProfileRequest` add `enabled_by_user`. Existing
  `is_active` remains accepted for one compatibility window; if both are supplied and differ, return
  HTTP 400 with `profile_enabled_state_conflict`.
- `RuleProfileResponse` adds `enabled_by_user`, `effective_status`, and `status_reason`.
  `is_active` remains the user-intent compatibility alias, not the runtime entitlement result.
- `RulesService.create_profile(...)` allows owners/admins to save configuration without a current
  subscription. It queues immediate discovery only when the new group is effectively `running`.
- `RulesService.update_profile(...)` supports rename and pause/resume without replacing keywords.
  Enabling during an active limited plan returns HTTP 409 `active_keyword_limit_exceeded` if it
  would exceed the current quota; the UI may retry as “save paused.”
- `_queue_profile_created_jobs(...)` and `_queue_profile_update_jobs(...)` receive resolved
  effective status and never queue paused/blocked groups.
- GET remains available to the tenant, while create/rename/pause/resume/remove-keyword remains
  owner/admin-only through the existing role checks.

### Worker and dispatch safety

- Remove all calls to `deactivate_active_profiles_created_before(...)` from API entitlement reads,
  scheduled enqueue, and live discovery authorization.
- Scheduled discovery builds jobs only from `running` groups and deduplicates normalized keywords
  across groups.
- Extend `DiscoveryAuthorizationSnapshot` with runnable profile/keyword pairs. When `profile_id` is
  present, `require_discovery_authorization(...)` verifies both tenant keyword entitlement and that
  exact group pair. A stale pending job for a paused group therefore fails closed even if another
  group contains the same keyword.
- Do not automatically start a crawler during payment settlement. Normal scheduled discovery
  resumes, and the existing manual recrawl action remains the explicit “run now” path.

### UX/UI

- Replace the always-open default-name composer with a page heading “กลุ่มคำค้น” and primary button
  “สร้างกลุ่มคำค้น”. Open an inline panel/modal containing required group name and initial keywords.
- Never silently default every submission to `คำค้นหลัก`. Suggest `กลุ่มคำค้น 1`, `2`, etc. only as
  placeholders; require an explicit nonblank unique name.
- Cards show the name, unique keyword count, updated date, and one effective badge:
  “กำลังติดตาม”, “หยุดโดยคุณ”, “พักไว้ตามแพ็กเกจ”, or “ต้องจัดการโควต้า”.
- Card actions are “เปลี่ยนชื่อ”, “แก้ไขคำค้น”, and a reversible “หยุดติดตาม/เริ่มติดตาม” switch.
  Remove the trash icon and stop deleting keywords when a group is paused.
- During lapse/fallback, render all saved groups and keywords. Disable “run now” but allow safe
  organization edits; explain that enabled groups resume automatically under Monthly Membership.
- After monthly reinstatement, historical enabled groups display “กำลังติดตาม” immediately. If
  quota conflict exists under another plan, show one page-level action-required banner and link to
  pause groups rather than hiding data.
- Duplicate keyword membership is allowed for organization, but the quota and crawler count the
  normalized term once. Explain this in helper copy.

## 4. Test coverage

### `tests/phase2/test_rules_api.py`

- `test_create_multiple_uniquely_named_keyword_groups` — creates separate tenant-scoped named groups.
- `test_duplicate_group_name_returns_structured_conflict` — rejects normalized duplicate group name.
- `test_rename_group_preserves_keywords_and_order` — rename leaves all keyword rows unchanged.
- `test_pause_group_preserves_keywords_and_user_intent` — reversible pause never deletes saved terms.
- `test_save_group_without_subscription_queues_no_jobs` — persists configuration but performs no crawl.
- `test_resume_group_queues_only_when_effectively_runnable` — entitlement controls immediate enqueue.
- `test_rules_response_reports_saved_enabled_runnable_counts` — exposes distinct lifecycle counts.
- `test_rules_mutations_remain_tenant_scoped` — cannot rename or pause another tenant group.

### `tests/phase4/test_entitlements.py`

- `test_expired_membership_keeps_saved_groups_visible` — lapse performs no profile mutation.
- `test_monthly_reinstatement_makes_historical_groups_runnable` — prior enabled groups return automatically.
- `test_user_paused_group_stays_paused_after_reinstatement` — explicit intent wins over membership.
- `test_one_time_cycle_excludes_old_groups_without_mutation` — fresh slot preserves historical configuration.
- `test_over_limit_groups_remain_saved_but_runs_fail_closed` — visibility retained while crawling blocked.

### `tests/phase3/test_invoice_lifecycle.py`

- `test_membership_activation_does_not_mutate_profile_intent` — billing only changes subscription state.
- `test_one_time_activation_does_not_delete_or_disable_groups` — plan cycle remains computed policy.
- `test_keyword_group_backfill_restores_expiry_paused_rows` — migration maps legacy rows safely.

### Worker tests

- `test_scheduler_deduplicates_keyword_across_named_groups` — one normalized term creates one job.
- `test_scheduler_skips_paused_group_without_writing_profile` — read-only eligibility filtering.
- `test_live_discovery_rejects_stale_paused_profile_job` — exact profile pair fails closed.
- `test_monthly_reinstatement_schedules_historical_enabled_groups` — restored groups resume on schedule.

### Web tests

- `test_group_status_copy_maps_all_effective_states` — Thai labels match backend statuses.
- `test_create_group_requires_unique_nonblank_name` — form prevents ambiguous group identity.
- `rules page creates two named keyword groups` — Playwright covers repeated group creation.
- `rules page pauses group without removing keywords` — paused card retains every chip.
- `rules page shows saved groups after reinstatement` — historical cards become runnable.

## 5. Decision completeness

### Goal

Users can organize keywords into several durable, uniquely named groups, and a reinstated monthly
membership automatically makes every previously user-enabled group available and runnable without
recreating data.

### Non-goals

- No new microservice or separate keyword-group table.
- No hard deletion or archival workflow for groups in this slice.
- No crawler run automatically launched as a side effect of payment settlement.
- No project retagging or historical result regrouping.
- No change to monthly pricing or billing-period calculation.

### Success criteria

- Two or more uniquely named groups can be created and shown simultaneously.
- Pausing a group changes zero rows in `crawl_profile_keywords`.
- A paid active monthly membership makes all historical `enabled_by_user=true` groups `running`.
- A user-paused group remains paused across lapse and reinstatement.
- `GET /v1/rules` performs no profile UPDATE statements.
- Scheduler and live worker use the same profile-cycle eligibility policy.
- Duplicate normalized keywords across groups cause one scheduled crawl, not duplicates.
- All new queries and uniqueness checks are tenant-scoped.

### Public interfaces

- Migration: `028_keyword_group_lifecycle.sql`.
- DB: `crawl_profiles.enabled_by_user BOOLEAN NOT NULL DEFAULT TRUE` and unique normalized group
  name per tenant; legacy `is_active` remains temporarily.
- API request additions: `enabled_by_user?: boolean` on create/update.
- API response additions: `enabled_by_user`, `effective_status`, `status_reason` on profiles;
  `saved_keyword_count`, `enabled_keyword_count`, `runnable_keyword_count`, `runnable_keywords` on
  entitlements.
- Error codes: `profile_name_conflict`, `profile_enabled_state_conflict`,
  `active_keyword_limit_exceeded`.
- No new CLI flags, environment variables, message topics, or external dependencies.

### Edge cases and failure modes

- Duplicate names differing only by whitespace/case: reject with 409; fail closed.
- Existing duplicate names during migration: deterministic suffix, preserve groups and keywords.
- Duplicate keyword across groups: preserve membership; dedupe quota and jobs by normalized value.
- Empty group: visible and editable, never runnable.
- Subscription inactive: save/view allowed, crawler denied; fail closed.
- One-time/fallback cycle excludes old groups: keep visible as `paused_by_plan`; no mutation.
- Active limited plan over quota: keep all groups visible, block discovery until resolved; fail closed.
- Stale queued job after pause: exact profile/keyword authorization rejects it; fail closed.
- Concurrent rename/create collision: database unique index wins and returns structured 409.
- Mixed deployment version: legacy `is_active` mirrors intent; additive column supports safe rollback.

### Rollout and monitoring

1. Immediate operational prerequisite: deploy current `origin/main` so production includes PR #167
   and #168. Because the LLL subscription was already activated on the older deployment, use a
   tenant-scoped recovery or the migration backfill; merely deploying PR #167 will not replay it.
2. Apply migration 028 before the new API/worker/web containers. It is additive and backfills
   `enabled_by_user`; it does not delete keyword rows.
3. Deploy API and worker together, then web. Old code may still toggle legacy `is_active` briefly,
   but it cannot erase `enabled_by_user` or keywords.
4. Verify LLL shows two distinct names, 13 group memberships, 12 unique terms, and running monthly
   status. Do not touch `docs/TOR KEYWORDS.md`.
5. Backout: roll code back while leaving the additive column/index. Legacy `is_active` remains
   synchronized, so old code continues safely; do not reverse the data migration.
6. Add structured logs/metrics without keyword text or email: group counts by effective status,
   runnable unique keyword count, duplicate-job dedupe count, and authorization-denied reason.

### Acceptance checks

- Local migration applies once and records exactly `028_keyword_group_lifecycle.sql`.
- API tests prove no keyword deletion on pause and automatic monthly availability.
- Worker tests prove no stale/duplicate group job executes.
- Playwright shows two groups, pause/resume, and reinstatement states.
- Production read-only SQL confirms saved/enabled/runnable counts after deploy.

## 6. Dependencies

- Existing PostgreSQL migration runner and SQLAlchemy repositories.
- Existing FastAPI/OpenAPI generation and React Query stack.
- Existing subscription resolver and discovery authorization package.
- No new third-party package.

## 7. Validation

```bash
docker compose -f docker-compose-localdev.yml up -d postgres
./.venv/bin/python -m egp_db.migration_runner \
  --database-url postgresql://egp:egp_dev@localhost:5432/egp \
  --migrations-dir packages/db/src/migrations
./.venv/bin/python -m pytest \
  tests/phase2/test_rules_api.py \
  tests/phase4/test_entitlements.py \
  tests/phase3/test_invoice_lifecycle.py \
  tests/phase1/test_worker_workflows.py \
  tests/phase1/test_worker_live_discovery.py -q
./.venv/bin/ruff check apps/api apps/worker packages tests
./.venv/bin/python -m compileall apps packages
(cd apps/web && npm run generate:openapi && npm run generate:api-types)
(cd apps/web && npm run check:api-types && npm run test:unit)
(cd apps/web && npm run typecheck && npm run lint && npm run build)
(cd apps/web && npx playwright test tests/e2e/rules-page.spec.ts)
```

Expected outcome: all commands pass; migration is idempotently recorded; no saved keyword row is
deleted by pause, expiry, one-time cycle change, or monthly reinstatement.

## 8. Wiring verification

| Component | Entry point | Registration location | Schema/table |
|---|---|---|---|
| Migration 028 | migration runner | filename-sorted `packages/db/src/migrations` | `crawl_profiles` |
| Group intent mapping | rules API and worker repository calls | `bootstrap/repositories.py:create_profile_repository` | `crawl_profiles.enabled_by_user`, `is_active` |
| Effective group status | `RulesService.get_rules`, scheduler, live discover | shared import from `discovery_authorization.py` | `billing_subscriptions`, `crawl_profiles`, `crawl_profile_keywords` |
| Rules API contract | `GET /v1/rules`, POST/PATCH profiles | `bootstrap/middleware.py:_register_routes` | same profile tables |
| Entitlement counts | `TenantEntitlementService.get_snapshot` | `bootstrap/services.py` injection into Rules/Run services | subscriptions + profile tables |
| Scheduled job selection | `run_scheduled_discovery` | worker `run_worker_job` command | `discovery_jobs`, profile tables |
| Live stale-job guard | `run_discover_workflow` | dispatcher subprocess invokes worker main | subscriptions + profile tables |
| Rules UI | browser route `/rules` | Next.js app router | API only |
| Generated TS contract | `api.ts` imports `generated/api-types.ts` | OpenAPI generation scripts | N/A |

Every row has a runtime caller, registration point, and verified schema owner. No new library is left
unwired.

## 9. Cross-language schema verification

- SQL uses `crawl_profiles(id, tenant_id, name, profile_type, is_active, ...)` and
  `crawl_profile_keywords(id, profile_id, keyword, position, created_at)`.
- Python repository code uses the same tables through `CRAWL_PROFILES_TABLE` and
  `CRAWL_PROFILE_KEYWORDS_TABLE`.
- Python billing, API entitlement, worker scheduler, live workflow, discovery dispatcher,
  document-capture selection, and tests all reference `crawl_profiles`/`profile_id`.
- TypeScript does not query tables; it consumes `RuleProfileResponse` through generated OpenAPI
  types in `apps/web/src/lib/api.ts`.
- `crawl_runs.profile_id` references `crawl_profiles(id)` without delete cascade, so this plan does
  not hard-delete groups.
- `discovery_jobs.profile_id` references `crawl_profiles(id)` with delete cascade; jobs remain tied
  to the canonical group selected for a normalized keyword.
- No Go code or second database schema exists in this repo.

## 10. Decision-complete checklist

- [x] Goal, non-goals, success criteria, interfaces, failures, rollout, and backout are locked.
- [x] No implementer choice remains between mutation-based and computed entitlement.
- [x] Every public field and error code is named consistently.
- [x] Every behavior change has at least one defect-detecting test.
- [x] Validation commands are scoped and executable.
- [x] Wiring covers migration, repository, policy, API, worker, and web.
- [x] Schema names were verified across SQL, Python, and TypeScript boundaries.

---

# Plan Draft B: Keep Mutation-Based Lifecycle with Explicit Pause Reasons

## 1. Overview

Make a smaller change by retaining `crawl_profiles.is_active` as the runtime state, adding an
explicit `inactive_reason`, and ensuring only membership-expired groups are reactivated. Add the
named-group UI and uniqueness rules while leaving the billing-time restore hook as the activation
mechanism.

## 2. Files to change

- `packages/db/src/migrations/028_keyword_group_inactive_reason.sql` — add reason and name index.
- `packages/db/src/egp_db/repositories/profile_repo.py` — write explicit reasons.
- `packages/db/src/egp_db/repositories/billing_payments.py` — reactivate only expiry reasons.
- `apps/api/src/egp_api/services/entitlement_service.py`, `rules_service.py`, routes — preserve
  keywords and expose reason.
- `apps/worker/src/egp_worker/scheduler.py`, `workflows/discover.py` — write plan-cycle reasons.
- Rules page, API client/generated types, backend tests, unit tests, Playwright tests, and docs from
  Draft A, with status derived from `inactive_reason`.

## 3. Implementation steps

### TDD sequence

1. Add tests for reason-specific deactivation/reactivation, unique names, and nondestructive pause.
2. Confirm user-pause versus expiry tests fail under the current heuristic.
3. Add `inactive_reason` and update each state-transition writer.
4. Add group-oriented UI and API fields.
5. Refactor repeated reason transitions only if tests remain clear.
6. Run the same scoped quality gates as Draft A.

### Functions and behavior

- `deactivate_active_profiles_created_before(..., reason)` writes `is_active=false` and one of
  `user_paused`, `subscription_expired`, or `outside_plan_cycle`.
- `RulesService.update_profile(...)` writes `user_paused` without deleting keywords.
- `_reactivate_profiles_for_membership_activation(...)` reactivates only
  `subscription_expired`/`outside_plan_cycle`; `user_paused` remains off.
- `assert_profile_name_available(...)` and the normalized unique index match Draft A.
- The UI create/rename/pause/resume interaction matches Draft A, but effective status is read from
  persisted `is_active` and `inactive_reason`.

## 4. Test coverage

- `test_user_paused_reason_survives_membership_activation` — restore hook respects user choice.
- `test_expiry_reason_reactivates_on_monthly_payment` — billing hook restores correct groups.
- `test_every_deactivation_writer_supplies_reason` — no ambiguous inactive state remains.
- `test_duplicate_group_name_returns_structured_conflict` — normalized names remain unique.
- `rules page pauses group without deleting keywords` — frontend uses reversible action.
- Existing billing, entitlement, scheduler, and live-workflow tests are updated to assert reasons.

## 5. Decision completeness

### Goal

Deliver named groups and reliable monthly restoration with minimal changes to current runtime
semantics.

### Non-goals

- No computed saved-versus-runnable lifecycle.
- No change to mutation-based expiry and plan-cycle handling.
- No new resource path or hard-delete behavior.

### Success criteria

- Every inactive row has a reason.
- Monthly activation reactivates only system-paused groups.
- User pause retains keywords and survives reinstatement.
- Group names are unique per tenant.

### Public interfaces

- DB: `crawl_profiles.inactive_reason` and normalized tenant/name unique index.
- API: `inactive_reason`, rename, and nondestructive pause/resume through existing endpoints.
- Errors: same name/state conflict codes as Draft A.
- No new CLI flags, env vars, topics, or dependencies.

### Edge cases and failure modes

- Missing/unknown legacy reason: fail closed and leave group inactive.
- Payment settles on an API version without the restore hook: group remains unavailable.
- Deactivation path forgets a reason: database check/default must reject or mark unknown.
- User pause during activation race: transaction ordering decides final state; require row locking.
- Duplicate names and cross-tenant access: database/service reject.

### Rollout and monitoring

- Deploy PR #167 immediately, then apply the reason migration and new code.
- Backfill inactive-with-keywords as `subscription_expired`; inactive-empty as `user_paused`.
- Watch counts by inactive reason and restoration events.
- Backout leaves the additive reason column while old code continues using `is_active`.

### Acceptance checks

- Billing activation changes only system-reason rows.
- All deactivation call sites write a reason.
- UI pause preserves keywords.

## 6. Dependencies

Same existing database, FastAPI, worker, React, and OpenAPI tooling as Draft A.

## 7. Validation

Run the same migration, targeted pytest, OpenAPI, unit, typecheck, lint, build, and Playwright
commands as Draft A, adding an exact search that verifies every call to
`deactivate_active_profiles_created_before` supplies a reason.

## 8. Wiring verification

| Component | Entry point | Registration location | Schema/table |
|---|---|---|---|
| Inactive reason migration | migration runner | migrations directory ordering | `crawl_profiles` |
| Reason-aware expiry | entitlement reads and scheduler | existing service/worker imports | profile tables |
| Reason-aware restore | payment reconciliation | billing repository facade | billing + profile tables |
| Named-group API | existing rules routes | router registration | profile tables |
| Named-group UI | `/rules` | Next.js app router | API only |

## 9. Cross-language schema verification

Table and column consumers are the same verified SQL/Python/TypeScript paths listed in Draft A.
`crawl_runs.profile_id` again prevents hard deletion.

## 10. Decision-complete checklist

- [x] Interfaces, reasons, migration, failure behavior, tests, and rollout are specified.
- [x] Every mutation writer is named as a required update.
- [x] UI and API are backward-compatible.
- [x] Wiring and cross-language schema paths are identified.

---

# Comparative Analysis

## Strengths

- Draft A separates durable customer configuration from transient commercial entitlement. Reads
  become side-effect free, every payment path behaves consistently, historical groups remain
  visible, and one-time/fallback behavior becomes computed policy rather than destructive mutation.
- Draft B is smaller and can reuse PR #167 with fewer changes to the authorization model.

## Gaps

- Draft A touches more API/worker tests and requires an additive compatibility field during rollout.
- Draft B remains vulnerable when a settlement path or deployment version omits the restore hook,
  exactly what happened in production. It also requires every future deactivation caller to write
  the correct reason and introduces row-order races between user pause and billing activation.

## Trade-offs

- Draft A spends more implementation effort once to remove an invalid state coupling.
- Draft B optimizes short-term delivery but keeps billing, entitlement reads, scheduler, and profile
  persistence mutually dependent.
- Both preserve current tables, tenant isolation, generated OpenAPI types, and existing routes.

## Compliance

Both drafts follow tenant-scoped PostgreSQL persistence, strict TypeScript, Python type hints, TDD,
the migration numbering policy, and the control-plane/worker-plane split. Draft A better satisfies
the repository preference for explicit lifecycle states and API-owned product policy because worker
and entitlement reads stop writing customer configuration.

---

# Unified Execution Plan (Recommended)

## 1. Overview

Implement Draft A. Keep the existing `crawl_profiles`/`crawl_profile_keywords` data model, but make
groups a clear product concept and make `enabled_by_user` the durable customer intent. Compute
`running` from subscription, plan cycle, quota, and intent everywhere; never deactivate or reactivate
saved configuration as a billing side effect.

## 2. Files to change

Use the complete Draft A file list. Do not create a new microservice or new group table. The only
new production file is migration `028_keyword_group_lifecycle.sql`; frontend test/helper files may
be added as listed.

## 3. Implementation steps

### Tests-first order

1. Add migration/repository tests for backfill, unique names, and nondestructive pause.
2. Run and confirm the repository/API tests fail for the expected missing fields/behavior.
3. Add entitlement tests proving reads do not mutate and monthly reinstatement restores effective
   access while user pause survives.
4. Add worker tests for shared eligibility, profile-specific fail-closed authorization, and keyword
   deduplication; confirm failures.
5. Implement migration, repository mapping, shared eligibility, entitlement, Rules service/routes,
   billing decoupling, scheduler, and live authorization in that order.
6. Regenerate OpenAPI, then add unit and Playwright tests for group create/rename/pause/resume and
   reinstatement rendering; confirm failures before UI implementation.
7. Implement the group-oriented UI and pure presentation helpers.
8. Refactor minimally, run scoped gates, perform local migration/browser smoke, then deploy using
   the rollout order below.

### Locked function behavior

- `assert_profile_name_available` enforces tenant-scoped normalized uniqueness.
- `list_profiles_with_keywords` always returns saved configuration.
- `list_enabled_profiles_with_keywords` expresses user intent only.
- `profile_is_in_effective_cycle` is the single pure plan-cycle rule.
- `build_runnable_profile_keywords` is the single shared unique-keyword selector.
- `TenantEntitlementService.get_snapshot` is read-only and exposes saved/enabled/runnable counts.
- `RulesService.create_profile`/`update_profile` manage named groups and preserve keywords on pause.
- `require_discovery_authorization(..., profile_id=...)` denies stale paused-group jobs.
- Billing activation creates subscriptions and tenant-plan state only; it never writes profiles.

## 4. Test coverage

Implement every Draft A test. Retire or rewrite existing tests whose expected behavior is profile
mutation, especially:

- `test_active_one_time_pack_retires_profiles_from_before_current_cycle`
- `test_expired_monthly_membership_falls_back_to_free_trial_with_archive_access`
- `test_expired_one_time_pack_falls_back_to_free_trial_with_archive_access`
- `test_monthly_membership_activation_reactivates_deactivated_profiles_with_keywords`
- `test_one_time_activation_does_not_reactivate_deactivated_profiles`

Their replacements must assert unchanged saved intent plus computed effective status.

## 5. Decision completeness

### Goal and non-goals

The goal and non-goals are exactly Draft A. In particular, “available after reinstatement” means
visible, editable, and `running` under monthly entitlement; it does not mean an automatic crawler
spawn during payment.

### Success criteria

All Draft A criteria are mandatory. Add the production criterion that tenant LLL's two saved groups
are restored without recreating 13 memberships and without producing duplicate scheduled searches
for its 12 unique terms.

### Public interfaces

Use the additive DB/API fields and error codes from Draft A. Keep `/v1/rules/profiles` and `is_active`
for one compatibility window; new frontend and worker code must use `enabled_by_user` and effective
status. No open API naming decision remains.

### Edge cases and failure modes

Use Draft A's fail-closed matrix. The key invariant is: commercial or quota failure may stop work,
but must never delete, hide, or rewrite saved keyword membership.

### Rollout and monitoring

1. Before feature deployment, reconcile production to current `origin/main`; preserve the host-local
   Caddy and Compose override files.
2. Apply migration 028. It repairs the already-active LLL tenant by deriving enabled intent from
   retained keywords and resolves duplicate names without deleting a group or keyword.
3. Deploy API and worker, then web; run health and targeted rules smoke.
4. Verify LLL via read-only DB and `/v1/rules`: two uniquely named saved groups, 13 memberships,
   12 unique runnable terms, monthly active, no quota block.
5. Monitor effective-status counts, authorization denials, and deduped jobs for one billing cycle.
6. Roll back code only if needed; keep additive migration applied.

### Acceptance checks

All Draft A commands and outcomes are mandatory. Add a production smoke that pauses and resumes a
noncritical test group, verifies keyword row count is unchanged, and confirms scheduled selection
changes accordingly.

## 6. Dependencies

No external dependencies. Deployment access is required only for the production reconciliation and
post-deploy verification.

## 7. Validation

Run the complete Draft A command set, then:

```bash
./.venv/bin/python scripts/check_main_sync.py --json
git status --short --branch
```

Expected: branch synchronized, only the user's unrelated `docs/TOR KEYWORDS.md` plus the intended
feature/log changes appear, and all targeted gates pass.

## 8. Wiring verification

Use Draft A's full wiring table. During implementation, explicitly prove the shared selector is
called from all three runtime paths: API snapshot/manual recrawl, scheduled enqueue, and live worker
authorization. A selector that is only imported or tested but not called in one of those paths is
incomplete.

## 9. Cross-language schema verification

Use Draft A's findings. Before merging, repeat exact searches for `is_active`,
`deactivate_active_profiles_created_before`, `crawl_profiles`, `crawl_profile_keywords`, and
`profile_id`; any remaining entitlement-driven profile UPDATE requires explicit removal or written
justification.

## 10. Decision-complete checklist

- [x] Robust lifecycle model selected; mutation-based Draft B rejected.
- [x] Existing tables and route retained; no architecture fork.
- [x] Migration/backfill behavior covers current production data.
- [x] Group naming, duplicate keywords, pause/resume, quota, cycle, and stale-job behavior locked.
- [x] Tests-first sequence and exact test names listed.
- [x] Validation, rollout, monitoring, and backout specified.
- [x] Wiring covers every component and runtime caller.
- [x] No open decisions remain for the implementer.

---

## Implementation Update (2026-07-21 14:05:55 +07) - Safe Production Recovery

### Goal

Reconcile the Lightsail checkout with current `origin/main`, preserve all host-local Caddy and
Compose files, deploy PRs #167-#169, and restore tenant LLL's already-paid monthly keyword profiles
without recreating or deleting keyword memberships.

### What changed and why

- Production Git only: fetched `origin/main`, proved the 14 production-only commits contained no
  tree changes beyond merge history, renamed the old branch to
  `backup/production-pre-recovery-20260721T065935Z`, and created a fresh `main` tracking
  `origin/main` at `8aedaad630c8ee688342fa94790bbdcfb1564f75`.
- Production host files: copied the modified `deploy/caddy/Caddyfile` and both untracked Compose
  override files to `/home/ubuntu/egp-host-local-backups/20260721T065935Z`; pre/post SHA-256 checks
  proved all three working-copy files remained byte-identical.
- Production runtime: rebuilt `migrate`, `api`, and `webhook-executor`; the migration runner applied
  zero migrations; recreated only API and webhook executor. Caddy, Postgres, and proxy relay were
  not recreated.
- Production data: replayed PR #167's tenant-scoped restoration condition for LLL only: active
  current `monthly_membership`, inactive profile, and at least one retained keyword. Exactly two
  profiles changed from inactive to active; all 13 memberships and 12 normalized unique keywords
  remained intact.

### TDD evidence

- Tests added or changed: none; this was an operational recovery before feature implementation.
- RED run: not applicable because no repository code changed. The pre-recovery failure evidence was
  live state: production HEAD `32b9ad48380f`, two inactive populated profiles, and a paid active
  monthly subscription through 2026-08-05.
- GREEN verification: production HEAD and `origin/main` both resolve to `8aedaad630c8`; API health is
  `{"status":"ok"}`; two profiles are active with 13 memberships and 12 unique active keywords.

### Commands and results

- `git fetch origin main` locally and on production: local/main stayed `8aedaad630c8`; production
  discovered 14-ahead/3-behind merge-only divergence from merge base `99f54b31a4f`.
- `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --quiet <merge-base>..HEAD`: passed on production; the old
  production HEAD tree exactly matched the merge-base tree.
- `sudo docker compose --env-file /etc/egp/egp.env config -q`: passed before deploy.
- `sudo docker compose --env-file /etc/egp/egp.env build migrate api webhook-executor`: passed.
- `sudo docker compose --env-file /etc/egp/egp.env run --rm migrate`: passed; applied 0 migrations.
- `sudo docker compose --env-file /etc/egp/egp.env up -d --no-deps api webhook-executor`: passed.
- `curl -fsS https://api.egptracker.com/health`: passed with `{"status":"ok"}`.
- Tenant-scoped restoration transaction: committed exactly two rows; post-check returned two active
  profiles, 13 memberships, and 12 normalized unique active keywords.

### Wiring and risk notes

- Recovery used the exact discriminator implemented by
  `BillingPaymentsRepository._reactivate_profiles_for_membership_activation`: recurring active
  membership plus inactive populated profiles, scoped to tenant LLL.
- The duplicate normalized group name remains intentionally unresolved until migration 028; no
  production name or keyword row was rewritten during recovery.
- Backout refs/files are retained. The additive feature migration has not yet been applied.
- Auggie timed out at the required two-second limit; implementation exploration will use direct
  target-file inspection and exact-identifier searches.

### Follow-ups

- Implement the Unified Execution Plan on `feature/keyword-group-lifecycle` with strict RED/GREEN
  evidence, then run QCHECK, formal `g-check`, and open a PR.

---

## Implementation Update (2026-07-21 14:46:11 +07) - Durable Keyword-Group Lifecycle

### Goal

Replace billing-driven profile mutation with durable user intent plus computed runtime eligibility,
then expose the lifecycle consistently through the API, worker, rules UI, tests, and operating docs.

### What changed and why

- Added migration `028_keyword_group_lifecycle.sql`. It introduces non-null
  `enabled_by_user`, restores populated legacy groups without deleting memberships, synchronizes
  the compatibility `is_active` field, deterministically repairs normalized duplicate names, and
  enforces tenant-scoped normalized name uniqueness.
- Added shared keyword-group effective statuses and a single discovery selector/policy. Saved,
  enabled, quota-eligible, and runnable keywords are now distinct. Monthly renewal reuses durable
  intent; one-time plans filter groups by cycle; over-limit configuration fails closed.
- Removed billing-settlement and worker mutations of crawl profiles. Billing only changes billing
  state; the API snapshot, scheduler, and live worker all compute runtime eligibility from the same
  selector.
- Made live authorization profile-aware. A worker must be authorized for the exact normalized
  `(profile_id, keyword)` pair, preventing stale jobs for a paused group from borrowing permission
  from another group containing the same keyword.
- Extended the rules API with `enabled_by_user`, `effective_status`, `status_reason`, and saved /
  enabled / runnable counts. `is_active` remains an input/output compatibility alias for one
  rollout window. Conflicting aliases, duplicate names, and quota violations have structured
  errors.
- Rules can be saved and edited without an active subscription. Pause/resume no longer deletes
  memberships. Empty groups are accepted by the API for recovery/organization, while the web
  composer requires an initial keyword.
- Rebuilt `/rules` around explicit named groups, unique-name validation, stable Thai status copy,
  non-destructive pause/resume, separate saved/runnable counts, and plan/quota guidance.
- Updated OpenAPI/generated TypeScript, pricing semantics, and the manual web acceptance path.

### TDD evidence

- RED 1: the migration/name/pause slice failed 3/3 as intended because migration 028 did not exist,
  active creation was subscription-coupled, and legacy pause was destructive.
- GREEN 1: the identical three-test command passed after the migration, repository, and service
  changes.
- RED 2: seven entitlement/billing/worker lifecycle tests failed as intended: monthly historical
  groups did not resume from computed state, user pauses were not durable, one-time filtering
  mutated storage, quota/stale-profile authorization was incomplete, and billing mutated intent.
- GREEN 2: the identical seven-test command passed after wiring the shared selector into API,
  scheduler, live worker, and settlement paths.
- RED/GREEN follow-ups covered duplicate-name conflicts, rename preservation, empty API groups,
  manual duplicate-keyword dedupe, quota conflicts, exact profile authorization, and the rule that
  an over-limit tenant may rename/reduce groups but may not enable more over-limit keywords.
- Web RED initially lacked named-group create/pause/reinstatement flows. Unit helpers and Playwright
  acceptance were added; the final rules-page suite passes all seven scenarios.

### Verification results

- Local PostgreSQL migration: applied exactly `028_keyword_group_lifecycle.sql`; immediate rerun
  applied zero migrations.
- Focused Python lifecycle suite: 149 passed on each of three consecutive runs (two existing
  SQLite datetime-adapter warnings per run).
- Additional API/worker regression slice after review fixes: 124 passed.
- Frontend unit suite: 49 passed on each of three consecutive runs.
- Rules-page Playwright suite: 7 passed on each of three consecutive runs.
- `ruff check apps/api apps/worker packages tests`: passed.
- `python -m compileall -q apps packages`: passed.
- Web `lint`, `typecheck`, OpenAPI/type drift check, and production `build`: passed.
- Full Python suite first run found one stale assertion expecting subscriptionless group creation
  to be rejected. The test was updated to the locked contract (save as `paused_by_plan`, no job or
  dispatch); its focused rerun passed. The final full-suite rerun passed 1,283 tests with 108
  existing SQLite datetime-adapter warnings.

### Wiring verification

| Runtime path | Shared policy input | Enforcement/output | Verified by |
|---|---|---|---|
| Rules snapshot/API | subscriptions + all profile memberships | counts and per-group effective status | rules + entitlement tests |
| Create/update/manual recrawl | exact runnable profile-keyword list | queue only eligible deduped terms | rules + immediate-discover tests |
| Scheduled enqueue | profile candidates + effective entitlement | deterministic runnable jobs | scheduler/live-worker tests |
| Live worker | fresh snapshot + task profile ID and keyword | fail-closed exact-pair authorization | stale-paused-profile tests |
| Billing settlement | billing records/subscriptions only | no crawl-profile writes | invoice lifecycle tests |

### Compatibility and risk notes

- `is_active` is still written as a mirror of `enabled_by_user`; new runtime decisions use durable
  intent plus computed effective status.
- Duplicate keyword text across enabled groups selects the oldest group deterministically and queues
  only one discovery job; exact-pair authorization still rejects paused groups.
- Migration 028 is additive and remains safe if application code is rolled back. Its unique index
  can surface previously hidden duplicate-name writes, which the API maps to HTTP 409.
- The unrelated user-owned `docs/TOR KEYWORDS.md` remained untracked and untouched throughout.

### QCHECK review fixes

- P1 fixed: the profile-update queue path rebuilt its enqueue list from all newly saved keywords
  after the shared selector had already removed duplicates owned by an older group. That could
  enqueue a second `(profile_id, keyword)` job and undermine deterministic ownership. The path now
  filters only the selector-approved list; a RED/GREEN regression proves the newer group queues
  nothing for the older group's term.
- P1 fixed: create admission counted every keyword in a duplicate organizational group even when
  the selector would enqueue zero new work. The admission count now includes only terms absent from
  the current quota set and skips admission entirely for zero new terms. A queue-cap regression
  proves two named groups can share one term while consuming one job slot.
- P1 fixed: profile updates previously bypassed queued-keyword admission. Updates now calculate only
  newly runnable terms, check admission before persistence, and return the same structured 429 as
  create/manual paths. A regression proves a rejected update leaves saved membership unchanged.
- Post-fix focused API/worker/entitlement suite: 127 passed; Ruff remained clean.

### Remaining release gate

- Stage only intended files, perform QCHECK and formal `g-check`, fix any findings, then commit,
  push, and create the feature PR without merging it.

---

## Review (2026-07-21 14:55:01 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feature/keyword-group-lifecycle`
- Scope: staged working tree based on `8aedaad630c8ee688342fa94790bbdcfb1564f75`
- Commands Run: staged status/name/stat/check inspection; targeted diffs for migration, repository,
  entitlement, rules, scheduler, live worker, billing, web, generated types, and tests; exact-string
  mutation/wiring searches; real PostgreSQL migration plus idempotency; Ruff; compileall; web lint,
  typecheck, OpenAPI drift, build, unit, and Playwright; focused and full Pytest suites. Auggie had
  already timed out at the required two-second limit, so direct inspection was used.

### Findings

CRITICAL
- No findings.

HIGH
- No findings.

MEDIUM
- No findings after fixes. QCHECK identified and implementation fixed deterministic duplicate
  ownership during profile updates, phantom duplicate queue admission, and missing update admission;
  each now has a focused regression test.

LOW
- No findings.

### Open Questions / Assumptions
- `is_active` remains a one-window compatibility mirror by explicit plan decision; no removal date is
  introduced in this PR.
- Monthly membership remains unlimited in the existing runtime policy even if older commercial docs
  display a seeded limit; production LLL's 12 unique terms therefore remain intentionally runnable.
- Production migration 028 and the final rules smoke are deployment steps, not PR-creation steps.

### Recommended Tests / Validation
- Run the final full Python suite after the QCHECK fixes, then repeat the narrow rules lifecycle suite
  if any submission-time conflict resolution changes product code.
- Require CI to repeat Python, Ruff, web type/lint/build/unit, and generated-contract gates.
- On deploy, verify the LLL tenant has two uniquely named enabled groups, 13 memberships, 12 unique
  runnable terms, and no duplicate scheduled keyword jobs.

### Rollout Notes
- Deploy migration first, then API/worker, then web. Migration 028 is additive and should remain
  applied during application rollback.
- Preserve `/home/ubuntu/egp` host-local Caddy and Compose override files; their durable recovery
  backup is `/home/ubuntu/egp-host-local-backups/20260721T065935Z`.
- Billing activation no longer performs a profile replay. Monthly groups resume through computed
  eligibility on the next rules read/schedule cycle; user-paused groups remain paused.
- `docs/TOR KEYWORDS.md` is unrelated, remains untracked, and must not be staged by submission.

### Post-review Validation
- Final full Python suite after all QCHECK fixes: 1,286 passed with 108 existing SQLite
  datetime-adapter warnings in 160.76 seconds.

---

## Submission Update (2026-07-21 14:59:40 +0700) - PR #170

- Committed the reviewed feature as `0e3bc80af44c37e834b22de1366c83c0d15717a0`
  (`feat(rules): add durable keyword group lifecycle`). The staged pre-commit hook repeated web
  typecheck/lint and Python Ruff successfully.
- Pushed `feature/keyword-group-lifecycle` and opened PR #170:
  `https://github.com/SubhajL/egp/pull/170`. GitHub reports the PR open and mergeable against
  `main`.
- GitHub Actions did not execute product code. All CI and Claude-review jobs ended in 2-3 seconds
  with zero steps and the annotation: `The job was not started because your account is locked due
  to a billing issue.` This is an account-level CI blocker, not a test failure. Vercel preview was
  still pending at the first post-creation check.
- The working tree after the feature commit contained only the protected untracked
  `docs/TOR KEYWORDS.md`.
