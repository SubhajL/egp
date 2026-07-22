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

---

## Review (2026-07-22 09:28:11 +0700) - system

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feature/keyword-group-lifecycle` at `f19531af`; `main` / `origin/main` at
  `8aedaad630c8`.
- Scope: production recrawl acceptance, local Mac executor supervision, discovery job/run state
  transitions, worker authorization, failure reconciliation, UI status rendering, tests, and the
  relationship to PR #170.
- Commands run: repository/branch/status/history checks; bounded source and test inspection; local
  launchd/process/tunnel/profile-state inspection; production guard validation; read-only production
  PostgreSQL queries through the existing SSH tunnel; bounded worker-log inspection; production API
  health check; focused entitlement-denial regression test.
- Sources: `docs/REMOTE_LOCAL_CRAWLER.md`, `scripts/run_remote_crawl.sh`,
  `scripts/install_launchd.sh`, `apps/api/src/egp_api/services/discovery_dispatch.py`,
  `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`,
  `apps/api/src/egp_api/executors/discovery_dispatch.py`,
  `apps/api/src/egp_api/services/rules_service.py`,
  `apps/worker/src/egp_worker/workflows/discover.py`,
  `packages/db/src/egp_db/repositories/run_repo.py`, relevant phase 1/2 tests, the Projects page,
  production queue/run records, local artifact logs, and the 20 June crawler recovery Coding Log.
- Auggie: unavailable in this session; direct exact-identifier inspection was used.

### High-level assessment

The current recrawl did not fail inside Chrome or the e-GP site. It has not started. Production
accepted 13 manual jobs for 12 unique keywords at `2026-07-21 23:45:05+00` (06:45 Bangkok on 22
July), and all 13 remain `pending` with `attempt_count=0`. There is no crawl run newer than 6 July.
The production SSH tunnel is running and the remote-crawl guard passes, but the sole production
claimer, launchd service `com.egp.remote-crawl`, is not loaded. The API health endpoint still returns
`{"status":"ok"}` because it does not represent crawler-plane health.

There is also a recovery safety constraint: the installed launchd plist executes this mutable
developer checkout directly, and the checkout is currently on PR #170 while production has not
applied migration 028. Reloading the watcher as-is could run feature code that queries
`enabled_by_user` against the pre-028 production schema. Recovery must first use a pinned
production-compatible checkout or complete the feature migration/deployment.

The attached run `f8258b26-d7c0-4b49-b3b3-93be8f67d4b3` is a separate historical run from 6 July,
not a run created by the current click. Its worker log contains the actual terminal result:
`{"detail": "discover keyword is not entitled for tenant", "error_type":
"entitlement_denied"}`. The matching discovery job for `เทคโนโลยีสารสนเทศ` was correctly marked
failed with that `last_error`, but the crawl run was left active and later rewritten as
`worker_lost`. Therefore the displayed error is a secondary reconciliation artifact, not the root
cause.

This is not evidence that the keyword lifecycle work was wasted. PR #167 and the production replay
restored the paid tenant's two profiles, and PR #170 fixes durable intent plus cross-group keyword
deduplication. Those changes address entitlement/data correctness. They do not supervise the sole
Mac executor, expose its health, or guarantee terminal run bookkeeping for every subprocess exit.

### As-is execution path

1. Vercel UI calls `POST /v1/rules/recrawl` on the Lightsail API.
2. API entitlement/admission checks run and durable `discovery_jobs` rows are inserted in production
   PostgreSQL.
3. No server-side executor claims those rows by design. The Mac is the sole claimer.
4. launchd must keep `scripts/run_remote_crawl.sh watch` running; it reaches PostgreSQL through a
   separately supervised SSH tunnel.
5. The dispatcher creates a queued `crawl_run`, spawns `python -m egp_worker.main`, and stores only
   owner PID, child PID, and worker-log path in the run summary.
6. The child reloads current entitlement before marking the run started or creating any task.
7. The parent marks timeouts and signal deaths explicitly, but does not mark ordinary non-zero exits
   (including parsed entitlement denial) terminal.
8. The next missing-PID sweep sees the intentionally exited child and labels the still-active run
   `worker_lost`, overwriting the more useful error field.

### Drift matrix

| Area | Intended behavior | Current production/runtime truth | Impact |
|---|---|---|---|
| Durable enqueue | Recrawl survives API/request lifetime | Works: 13 rows are durable and untouched | No data loss, but durability is mistaken for execution availability |
| Sole executor | launchd watcher continuously drains the queue | Plist exists but service is not loaded; this same state was manually repaired on 20 June | Total crawl outage with no automatic detection or recovery |
| Tunnel | Tunnel enables worker DB access | Tunnel is independently healthy now | A green tunnel is not evidence of a green crawler |
| Browser profile | Pre-dispatch warm makes Chrome usable | Last recorded success is 6 July; profile is over two weeks cold | Executor restart may immediately require operator Cloudflare recovery |
| Run finalization | Every created run reaches a truthful terminal state | Ordinary child exit leaves run active; missing-PID sweep later rewrites it | Root causes are hidden and operators chase the wrong failure |
| Failure taxonomy | `worker_lost` means unexplained process loss | Sample historical `worker_lost` logs show entitlement denial or PostgreSQL tunnel failures | Metrics and UI cannot distinguish application, transport, or supervision failures |
| Job/run correlation | One job attempt can be traced to one run | Dispatch request/run metadata omit `discovery_job_id` | Incident reconstruction depends on timestamps/profile/keyword inference |
| UI status | Operator sees queue, executor, and run stage | UI can show the immediate waiting message, but API exposes no executor heartbeat or durable queue age | Refresh/session loss and old run summaries can obscure the current blocker |
| API health | Health reflects operability | API reports healthy while production crawling is completely idle | External monitoring cannot detect this outage |
| Worker code provenance | Production worker runs an immutable deployed revision compatible with its schema | launchd executes the developer checkout's current branch; currently PR #170 code vs pre-028 production DB | A local branch switch can silently change or break the production worker |
| Duplicate keywords | One normalized keyword should execute once | Deployed `main` enqueued 13 jobs for 12 terms because one term belongs to both profiles | Unnecessary crawl, rate-limit, and Cloudflare exposure; fixed in PR #170 but not deployed |
| Logs | Logs support bounded diagnosis | `crawl.log` is about 278 MB and has no current watcher output after 6 July | Weak retention/rotation and difficult operations |

### Strengths

- The durable outbox preserved all 13 current jobs without phantom attempts.
- The guard correctly validates production target, single-flight mode, real Chrome profile, HTTPS
  event sink, and remote artifact storage.
- The worker's fail-closed entitlement recheck is correct in principle and prevented stale work.
- Worker logs preserved the original entitlement and database errors even when run summaries did
  not.
- The Projects page now distinguishes “accepted but no worker run yet” during the initiating browser
  session and polls every five seconds.
- PR #170 centralizes profile/keyword eligibility and fixes duplicate ownership in tests; it is a
  necessary data-policy improvement even though it is not an executor-availability fix.

### Findings

CRITICAL

- Production has a total crawler-plane outage: the sole executor is not loaded, 13 current jobs have
  zero attempts, and neither `/health` nor any heartbeat/alert detects it. This exact operational
  failure was found and manually repaired on 20 June, proving the prior repair restored an instance
  rather than eliminating the failure mode. launchd `KeepAlive` only helps after an agent is loaded;
  it cannot recover an explicitly booted-out/unloaded agent.

HIGH

- Crawl-run terminalization is incomplete. After creating a run, the dispatcher only explicitly
  finalizes timeout and signal cases. Parsed entitlement denial and generic non-zero child exits are
  re-raised without `fail_run_if_active`. The next PID sweep then assigns `worker_lost`. The supplied
  run and several historical tunnel failures demonstrate this path in production.
- The reconciler overwrites `summary_json.error` and `failure_reason` based only on PID absence. A PID
  no longer existing after `communicate()` is normal for every completed child; it is not sufficient
  evidence that the worker was lost. This destroys causal fidelity and contaminates failure metrics.
- Crawler operability depends simultaneously on a logged-in Mac, a loaded launchd watcher, a separate
  SSH tunnel, a warm persistent Chrome profile, and an external site/Cloudflare clearance. There is
  no control-plane representation of worker registration, last heartbeat, lease ownership, or queue
  age, so each dependency can fail silently while customer-facing control-plane health stays green.
- Production execution is coupled to whichever Git branch happens to be checked out in the developer
  repo. The current branch contains a new required database column that production does not yet
  have. Supervision recovery can therefore introduce a schema/version incident unless the operator
  notices and pins compatible code first.

MEDIUM

- The current deployed API intentionally queues per profile, while only the response keyword list is
  deduplicated. This produced 13 jobs for 12 unique terms. PR #170 fixes the selector, but its CI is
  account-blocked and production migration/deployment remain outstanding.
- Test coverage validates that entitlement denial raises a non-retriable exception, and separately
  validates signal failure and missing-PID reconciliation. It does not assert the end-to-end
  invariant that every created run becomes terminal with the original semantic cause. The focused
  entitlement test passes while reproducing the blind spot.
- `DiscoveryDispatchRequest` drops the durable job ID before spawning. There is no direct job-attempt
  to run foreign key/correlation field, limiting retry, reconciliation, UI, and forensic correctness.
- The manual Cloudflare recovery playbook requires stopping the watcher, warming, running one bounded
  crawl, and restarting supervision. There is no enforced final check that the watcher was restored,
  and no audit trail currently explains when or why this agent became unloaded.

LOW

- The 278 MB combined crawl log lacks bounded rotation and mixes repeated readiness warnings with
  useful failures, increasing diagnostic cost.

### Why prior reasoning and implementation missed this

1. Work was organized around local symptoms—Cloudflare warming, tunnel recovery, stale-run display,
   billing restoration, keyword lifecycle—without one end-to-end availability invariant: “a queued
   production job must be claimed within N minutes or alert.”
2. A successful bounded crawl was treated as proof of system recovery. It proved Chrome, tunnel, and
   code could work at that moment, not that supervision would remain installed or observable.
3. Durable queue safety was conflated with service operability. The queue correctly prevents data
   loss while still allowing an indefinite silent outage.
4. Process supervision was modeled through PIDs rather than an explicit attempt state machine. The
   implementation can tell that a PID is gone, but not whether it exited successfully, was rejected,
   crashed, lost DB connectivity, or was killed with its parent.
5. Tests were component-shaped. Each branch—entitlement parsing, signals, PID reconciliation,
   launchd asset generation—has a test, but the seams between them do not.
6. The UI consumes `crawl_runs`, which do not exist until the Mac dispatcher acts. It therefore
   cannot diagnose the most important pre-run failure without a queue/executor API.
7. PR #170 solves the selected keyword lifecycle domain. It was never scoped to executor heartbeat,
   subprocess finalization, tunnel resilience, or worker-plane health, so expecting it to cure
   crawling availability would be a category error.

### Tactical improvements (next 1-3 days)

1. Recover without re-enqueueing, but first pin code/schema compatibility. Leave the 13 pending rows
   intact and either run from a clean operational worktree pinned to production `main` at
   `8aedaad630c8`, or complete PR #170 migration/deployment before using PR #170 worker code. Then
   perform the documented foreground profile warm, drain exactly one bounded job, reload a watcher
   that points to the pinned operational checkout, and verify a fresh run plus declining queue
   depth. Do not press recrawl again and do not reload the current feature-checkout plist as-is.
2. Make dispatcher finalization unconditional after `create_run`: every child return code/exception
   must call one terminalizer with a structured cause (`entitlement_denied`, `worker_nonzero`,
   `worker_timeout`, `worker_terminated`, transport error). Preserve the first semantic failure;
   `worker_lost` must only fill an otherwise unknown cause.
3. Add regressions for entitlement denial, generic Python exception, database/tunnel failure, and
   parent/reconciler restart. Each must assert job status, run status, error/failure reason, finished
   timestamp, and non-overwrite behavior.
4. Carry `discovery_job_id` and an attempt ID through `DiscoveryDispatchRequest`, crawl-run metadata,
   worker payload, logs, and API responses.
5. Add a worker-plane status endpoint sourced from durable heartbeat data: worker ID, last heartbeat,
   current job/run, oldest pending age, queue depth, and profile readiness. Alert if jobs are pending
   with no fresh worker heartbeat.
6. Deploy PR #170 only after CI/review gates are resolved, then apply migration 028 and verify 12
   unique runnable terms produce 12 jobs, not 13.
7. Rotate/compress `~/Library/Logs/egp/crawl.log` and retain per-run logs as the detailed source.

### Strategic improvements (1-6 weeks)

1. Replace PID-derived inference with a durable job-attempt state machine: queued, leased, preparing,
   worker_started, running, succeeded, partial, rejected, failed, cancelled, lease_lost. Store exit
   code and structured error separately from the human message.
2. Register crawler agents with renewable leases/heartbeats. Queue admission may remain available,
   but the UI must say “crawler offline” before accepting or immediately after enqueueing when no
   eligible agent is live.
3. Remove the SSH tunnel from the worker's correctness path by moving remaining DB reads/writes behind
   authenticated worker APIs or an explicit remote queue/event protocol. A tunnel interruption should
   pause/retry an attempt, not corrupt run finalization.
4. Add fault-injection acceptance tests covering unloaded watcher, tunnel loss during a crawl, stale
   Cloudflare profile, worker non-zero exit, parent restart, and delayed reconciliation.
5. Define and monitor crawler SLOs: enqueue-to-claim latency, oldest pending age, run success/partial
   rate by true cause, heartbeat freshness, and consecutive warm failures.

### Big architectural change (justified)

- Proposal: operate discovery as an explicit crawler-agent service on dedicated always-on hardware
  (a managed Mac/desktop worker if real Chrome and Cloudflare behavior require it), registered to the
  control plane with leases and heartbeats. Keep browser execution outside the API, but replace the
  implicit “one developer Mac + launchd + SSH tunnel” bridge with a first-class worker protocol.
- Benefits: customer-visible health, durable ownership, truthful retries, removal of laptop/login
  dependency, controlled browser/profile lifecycle, and failure isolation from API health.
- Costs: agent authentication, heartbeat/lease tables or endpoints, event/result APIs, deployment and
  monitoring work, and a staged migration from direct DB access.
- Migration: first add job/run correlation and heartbeat without moving execution; then make the UI
  and alerts consume it; then move writes behind worker APIs; finally place the same tested agent on
  dedicated always-on hardware and retire the production SSH-tunnel hot path.

### Verification evidence

- `scripts/install_launchd.sh status`: tunnel running at PID 75680; remote crawler not loaded; warm
  timer not loaded.
- Installed crawler plist: directly invokes
  `/Users/subhajlimanond/dev/egp/scripts/run_remote_crawl.sh watch`; that checkout is on PR #170 while
  a read-only production `information_schema` check returned zero `crawl_profiles.enabled_by_user`
  columns, confirming migration 028 is not applied.
- `scripts/run_remote_crawl.sh check`: production guard passed.
- Local tunnel: listening on `127.0.0.1:15432`; production read-only queries succeeded.
- Current queue: 13 pending manual jobs, 12 distinct normalized keywords, all zero attempts.
- Current runs: newest run is the supplied 6 July run; no run was created for the 22 July click.
- Supplied run log: explicit `entitlement_denied`; matching job has the same true `last_error` and was
  updated within the same two-second interval.
- Historical `worker_lost` samples: worker logs end with PostgreSQL tunnel refusal/server-closed
  errors, confirming that the label is not causally specific.
- API health: `{"status":"ok"}` during the crawler outage.
- Focused existing test: entitlement-denial test passed (`1 passed, 12 deselected`) while containing
  no assertion about the created crawl run's terminal status.
- Working tree after review: only the protected, unrelated untracked `docs/TOR KEYWORDS.md`; no
  product code or production state changed.

---

## Operational Recovery Update (2026-07-22 09:57:39 +0700) - pinned crawler runtime

### Goal

Recover the 13 already-pending production discovery jobs without re-enqueueing them or running PR
#170 worker code against the pre-migration production schema.

### What changed and why

- Created `/Users/subhajlimanond/dev/egp-ops-main` as a detached Git worktree pinned exactly to
  production-compatible `8aedaad630c8ee688342fa94790bbdcfb1564f75`.
- Reused the ignored production remote-crawl environment, external browser profile, and artifact
  directory. Created a worktree-local virtualenv because the original editable virtualenv resolved
  Python modules back to the PR #170 feature checkout; verified `egp_api`, `egp_worker`, `egp_db`,
  and `egp_crawler_core` now all resolve under `egp-ops-main`.
- Warmed the real persistent Chrome profile. The standard warm failed closed on Cloudflare; the
  existing extended search-controls settle recovery succeeded and reset the profile state to
  `operator_action_required=false` with a fresh success timestamp.
- Drained exactly one production job. Run `9c7237e0-ddab-49fa-aa5b-c1e258353843` succeeded with zero
  errors, one project seen, and an `ok` keyword scan. Its discovery job moved to `dispatched` with
  attempt count 1; the queue fell from 13 to 12 without a second recrawl request.
- Reinstalled `com.egp.pg-tunnel` and `com.egp.remote-crawl` from the pinned operational checkout.
  Both launchd agents are running, and the rendered plists point to `egp-ops-main`, not the mutable
  feature checkout. The expected tunnel-readiness startup race occurred once; launchd KeepAlive
  restarted the watcher after the tunnel became available.
- Verified the watcher claimed the next job and created running production run
  `33baec6c-0194-439b-8666-5e211b425181`, owned by watcher PID 9419 and progressing through real
  document collection with zero errors at the final check.

### TDD evidence

- Tests added or changed: none; this was a production operational recovery using the already-reviewed
  release at `8aedaad630c8`, not a source-code change.
- RED evidence: the first foreground warm exited non-zero with `warm-up failed: Cloudflare not
  cleared`; the first launchd watcher start exited because the separately reloaded SSH tunnel was
  not yet accepting connections.
- GREEN evidence: extended warm returned `WARMUP_OK`; bounded `crawl 1` returned `Processed 1 pending
  discovery dispatch jobs`; the canary run succeeded; launchd status then showed both agents running
  and a subsequent watcher-owned run advancing.

### Commands and results

- `git worktree add --detach /Users/subhajlimanond/dev/egp-ops-main 8aedaad...`: passed.
- `scripts/bootstrap_python_env.sh` in the operational worktree: passed; isolated editable installs
  resolve to that worktree.
- `scripts/run_remote_crawl.sh check`: passed before warm, canary, and launchd installation.
- Standard warm: failed safely on Cloudflare; extended-settle warm: passed.
- Read-only production query before claim: exactly 13 pending jobs, 12 normalized terms, zero
  attempts, one tenant.
- `scripts/run_remote_crawl.sh crawl 1`: passed; run `9c7237e0...` succeeded.
- `scripts/install_launchd.sh install` and `status`: passed; tunnel PID 9361 and final watcher PID
  9419 were running.
- Production API and queue checks were read-only except for normal worker processing; no manual row
  mutation or duplicate enqueue was performed.

### Wiring and risk notes

- The production daemon now runs immutable, schema-compatible application code from a detached
  worktree with its own virtualenv. The feature checkout remains free for PR #170 work.
- The remaining 12 rows intentionally stay `pending` while the single-flight watcher processes one
  at a time; a claimed row retains pending status until its attempt finishes.
- The browser warm timer remains opt-in and unloaded; pre-dispatch freshness logic remains active.
- The current checked-in installer still permits a mutable checkout. Permanent SHA pin enforcement,
  heartbeat/leases, queue-age health, truthful run finalization, job/run correlation, UI status, and
  dedicated-host preparation remain the requested code work.

### Release blocker

- Retried the failed GitHub Actions workflows for PR #170. Every required GitHub job again ended in
  two seconds without running any step. The check annotation is exact: `The job was not started
  because your account is locked due to a billing issue.` Vercel remains passed and GitHub reports
  the PR mergeable.
- g-coding requires the current PR to land before starting another PR and forbids an unapproved admin
  override of required checks. The next implementation slice therefore requires either resolving the
  GitHub billing lock and rerunning checks, or explicit user authorization for a documented merge
  override based on the already-recorded local gates.

### Protected files

- `docs/TOR KEYWORDS.md` remains untracked and untouched.

---

## Review (2026-07-22 13:27:13 +0700) - crawl result/dispatch semantics

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `feature/keyword-group-lifecycle` at `f19531af`; relevant crawler/UI files are
  byte-identical to production-compatible `8aedaad630c8`.
- Scope: Projects-page recent crawl summary, worker result propagation, durable dispatch retry,
  browser/profile health, and the 22 July production run sequence.
- Commands Run: targeted source/test inspection; production read-only PostgreSQL queries through the
  validated SSH tunnel; four focused pytest cases (`4 passed in 7.01s`); bounded worker/supervisor
  log inspection.
- Auggie semantic retrieval was attempted first but exceeded the required two-second limit, so this
  review used direct file inspection and exact-string searches.

### High-Level Assessment

Run `79552403-d4fe-417c-975e-0100a3af89e5` did exactly one targeted document-backfill search for
project number `69069469196`; its own log states `keyword_count=1`, and it succeeded. The Projects
page is misleading because it fetches the latest ten run rows and labels that arbitrary window
"latest 10 keywords." Those ten rows mix triggers, profiles, attempts, and time: one successful
backfill at 11:47 plus nine preceding failures. The displayed nine failures are not sibling keywords
inside run `79552403`; they are older, separate crawl runs.

There is nevertheless a serious crawler defect. After manual run `b54a0bf0...` collected 12 projects
for `ระบบสารสนเทศ`, e-GP returned its generic application-error toast while navigating from page 9
to page 10. The next ten manual keyword runs and one backfill run all received the same toast at
search startup. Each crawl run correctly became `failed`, but the worker process returned exit code
zero with JSON `run_status=failed`. The parent dispatcher interprets only process exit, marks the
durable job `dispatched`, clears `last_error`, records the persistent browser profile as successful,
and immediately continues. Thus all ten manual jobs were consumed with no retry. A fresh pre-dispatch
warm more than an hour later reset the stale session sufficiently for the new backfill job for
`69069469196` to succeed.

### As-Is Pipeline Diagram

Manual recrawl/backfill enqueue -> one `discovery_jobs` row per keyword/project number -> single-flight
watcher claims one row -> `SubprocessDiscoveryDispatcher` creates one `crawl_runs` row and launches
one worker process -> browser workflow retries an e-GP site-error toast once -> workflow stores
`failed`/`partial` in `crawl_runs` and returns a result object -> worker prints JSON and exits zero ->
parent treats dispatch as successful, marks the queue row `dispatched`, and marks the browser profile
fresh -> Projects page fetches the newest ten run rows and aggregates them as though they were one
keyword batch.

### Strengths

- The successful backfill preserved trustworthy scan evidence: one row, one eligible project, one
  accepted project, stable seven-column signature, and one downloaded archive.
- Browser search already performs one clean-page recovery before declaring the site toast terminal.
- Crawl-run/task records truthfully retain the semantic `failed` status and exact e-GP error.
- The host-shared file-lock rate limiter safely coordinates ordinary browser actions across worker
  processes.
- The pinned operational worktree, tunnel, watcher, and pre-dispatch warm were functioning; this is
  no longer the earlier unloaded-watcher outage.

### Key Risks / Gaps

CRITICAL

- None identified.

HIGH

- Semantic crawl failure is converted into durable dispatch success. `run_worker_job` returns
  `run_status`, but `main()` records every returned result as worker outcome `success` and exits zero.
  The parent checks only `returncode`; `DiscoveryDispatchProcessor` then marks the job `dispatched`.
  Production proof: the 13 recovered manual jobs ended as 2 succeeded, 1 partial, and 10 failed runs,
  but all 13 queue rows are `dispatched` with no error and none is pending for retry.
- Repeated e-GP application errors do not trip a host circuit or pause the queue. The limited click is
  recorded as `success` before the toast is inspected; the circuit recognizes consecutive HTTP 429
  outcomes only. The executor therefore burned through ten keywords after the first pagination site
  error instead of pausing after a small threshold.
- Failed runs falsely refresh persistent-profile health. Any zero-exit worker result calls
  `_record_persistent_profile_success(source="crawl")`, so the repeated site-error session remained
  "fresh" and skipped pre-dispatch warmups. The later backfill succeeded only after the 30-minute
  freshness window had elapsed and a pre-dispatch warm actually ran.

MEDIUM

- The Projects-page summary has no batch identity. It counts run attempts, not unique keywords, and
  mixes manual and backfill triggers plus different profiles. The same keyword `69069469196` appears
  once failed and once succeeded inside the latest-ten window, yet the UI calls them ten keywords.
- Queue state `dispatched` means only that the subprocess returned normally, not that discovery
  succeeded. That name and contract prevent operators from distinguishing accepted execution from
  successful crawl completion.
- Worker logs for immediate site-error failures contain only `keyword_start` and the final JSON
  result. The causal error lives in `crawl_runs.summary_json`, making file-based incident diagnosis
  incomplete.
- There is no recrawl request/batch ID joining the 13 manual queue rows and their runs. The UI cannot
  truthfully display progress for the specific click after browser-local tracking is lost.

LOW

- The E2E fixture assumes a curated homogeneous manual-run set and does not test mixed triggers,
  duplicate keyword attempts, or a latest-N window that slices through a batch.

### Drift Matrix

| Area | Intended | Implemented | Impact | Fix direction |
|---|---|---|---|---|
| Run scope | One run/batch explains all requested keywords | One run is one keyword | Successful run appears to omit siblings | Expose batch/request identity |
| UI summary | Summarize one recrawl request | Aggregate newest ten completed runs | Mixed triggers and duplicate attempts mislabeled as keywords | Batch-scoped API/UI |
| Dispatch success | Job completes when crawl outcome is accepted | Any zero process exit completes job | Failed keywords are permanently consumed | Return typed worker result and branch on status |
| Retry | Transient e-GP errors back off and retry | Retry only when dispatcher raises | Semantic failures never retry | Classify failed/partial outcomes explicitly |
| Circuit breaker | Repeated site rejection pauses host | Only action exceptions/429 affect circuit | Eleven near-identical errors run consecutively | Feed site-toast outcome into shared circuit |
| Profile health | Fresh means search session is usable | Any zero-exit crawl refreshes freshness | Broken session is continuously trusted | Mark success only for succeeded/acceptable partial runs |
| Observability | Worker/job/run metrics agree | Worker metric says success while run says failed | Alerts and rates understate failure | Single canonical outcome taxonomy |

### Why Earlier Reasoning Missed This

1. Recovery validation stopped after proving the queue drained and new runs appeared. It did not
   assert the end-to-end invariant `queue outcome == crawl run outcome`.
2. The architecture treats subprocess transport success and business crawl success as the same
   signal. Existing tests mirror those separate layers and never test their composition.
3. Rate limiting was implemented around browser actions, but e-GP reports this failure as an
   application toast after an otherwise successful click. The important failure sits outside the
   limiter's observation boundary.
4. Profile freshness was designed around Cloudflare/warmup completion, then reused as crawl health.
   It lacks a semantic rule for a completed process whose crawl result is failed.
5. The UI created a plausible batch summary from positional history because runs lack request/batch
   correlation. This worked in a three-run test fixture but is not valid operationally.
6. The document-backfill retry path later created another job for the same project number, masking
   the loss by producing a successful newest run. It did not retry the failed manual keyword jobs.

### Tactical Improvements (1-3 days)

1. Make subprocess dispatch parse the final worker JSON and return a typed result containing
   `run_id`, `run_status`, `error`, and retry classification. Only `succeeded` (and explicitly
   accepted `partial`) may mark a job `dispatched`. Done when a simulated `run_status=failed` leaves
   the job pending with backoff and preserved `last_error`.
2. Stop recording persistent-profile success when `run_status=failed`. Invalidate/pause the profile
   after a configurable number of consecutive search/pagination site errors. Done when two semantic
   site failures force a warm or operator-visible pause before another keyword is claimed.
3. Feed `site_error_toast` into the shared host circuit separately from HTTP 429, with bounded
   exponential cooldown. Done when repeated toast errors stop queue drain and later recover without
   losing jobs.
4. Add seam tests spanning worker result -> subprocess parser -> queue outcome for succeeded,
   zero-result, partial-after-projects, failed-before-results, timeout, and entitlement denial.
5. Replace `summarizeRecentKeywordRuns(latest 10)` with a truthful label immediately ("latest 10
   runs") and display trigger/time. Then add batch scoping once a batch ID exists. Done when mixed
   backfill/manual duplicate-keyword fixtures cannot claim ten unique keywords.
6. Re-enqueue the ten failed 22 July manual keywords only after the retry/circuit fix or under a
   bounded operator run; the original rows are already terminal `dispatched`, and the current queue
   has no pending jobs.

### Strategic Improvements (1-6 weeks)

1. Add `crawl_batches`/`request_id` and `discovery_job_attempts` correlation. Preserve each attempt
   and link queue job -> run -> batch; migrate the UI to batch progress with exact requested,
   succeeded, zero-result, failed, and retrying counts.
2. Replace `dispatched` as a terminal semantic with explicit queue states such as `leased`,
   `running`, `succeeded`, `partial`, `retry_wait`, `failed_terminal`, and `cancelled`. Migrate in
   stages by first adding attempt/result columns, dual-writing, then switching selectors/UI.
3. Unify worker, run, queue, profile, and metrics outcomes under one typed failure taxonomy. Add
   alerts for consecutive `egp_site_error`, batch completion below 100%, and jobs whose run failed
   while the queue says success.

### Big Architectural Changes

- None required for this incident. A typed result contract, retry-aware queue state, site-error
  circuit, and batch correlation close the demonstrated gaps without replacing the crawler plane.

### Open Questions / Assumptions

- The exact upstream reason for e-GP's generic toast cannot be proven from current artifacts. The
  sequence strongly supports a transient server/session rejection rather than keyword-specific data:
  all terms failed identically after page 10, and the same project-number search succeeded after a
  later warm.
- Whether `partial` should retry must be a product decision: persisted projects must remain, while a
  follow-up attempt should resume or deduplicate rather than replay blindly.

### Verification Evidence

- Production latest runs: one successful backfill at 11:47; prior backfill at 10:23 failed; ten
  manual runs between 10:15 and 10:23 failed with the identical error; preceding manual run was
  partial after page 9 with 12 persisted projects.
- Production recent manual outcome count: `succeeded=2`, `partial=1`, `failed=10`.
- Production queue: no pending rows; relevant manual and backfill jobs are `dispatched` with
  `attempt_count=1` and cleared `last_error`.
- Success run log: `keyword_count=1`, stable header, one eligible/accepted project, one document.
- Failure logs: only keyword start plus JSON `run_status=failed`; semantic error is stored in DB.
- Supervisor log: repeated "profile is fresh; skipping pre-dispatch warm" during drain; later
  `PREDISPATCH_WARMUP_OK` before the successful backfill.
- Focused tests: clean-page site-toast retry, terminal toast error, partial pagination error, and
  dispatched-job behavior all pass independently (`4 passed`). Their separation demonstrates the
  missing end-to-end result contract.
- No product code, queue rows, profile state, or production configuration was modified. The only
  write was this required `g-review` Coding Log append. `docs/TOR KEYWORDS.md` remains untouched.
