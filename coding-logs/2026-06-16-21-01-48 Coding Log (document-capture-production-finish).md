# Document Capture Production Finish Plan

Generated: 2026-06-16 21:01:48 Asia/Bangkok

## Exploration Notes

- Auggie semantic search was attempted for worker document-capture/download flow context and failed with `HTTP error: 402`; this plan is based on direct file inspection plus exact-string searches.
- Inspected files:
  - `AGENTS.md`
  - `apps/worker/AGENTS.md`
  - `apps/worker/src/egp_worker/browser_downloads.py`
  - `tests/phase1/test_worker_browser_downloads.py`
  - `.codex/coding-log.current`
  - memory registry sections for `egp` document capture, backfill, PR packaging, and production deployment topology.
- Current branch/worktree at planning time: `main...origin/main` with modified `apps/worker/src/egp_worker/browser_downloads.py`, `tests/phase1/test_worker_browser_downloads.py`, `deploy/systemd/egp-document-backfill-enqueue.service`, one modified prior coding log, and an untracked document-capture debug coding log.
- The handoff says the focused worker browser-download tests and Ruff checks already pass; the unresolved acceptance condition is live non-empty artifact verification for project `69069247778`.

## Plan Draft A: Live-Gate First

### Overview

Finish by validating the current worker change against the live e-GP project before spending time on broader gates, review, PR, and deploy. The key risk is that the code now passes synthetic tests but still stores a zero-byte artifact or fails in the real authenticated browser/session path.

### Files To Change

- `apps/worker/src/egp_worker/browser_downloads.py`: only if the live targeted crawl still produces zero bytes, empty SHA, wrong row selection, or missed modal download.
- `tests/phase1/test_worker_browser_downloads.py`: add/adjust focused tests only for defects found in the live run or g-check.
- `deploy/systemd/egp-document-backfill-enqueue.service`: review the existing modification and keep it only if it is necessary for production backfill drain/retry behavior.
- `coding-logs/2026-06-16-18-49-02 Coding Log (document-capture-modal-path-debug).md`: append implementation/validation summary for the in-progress fix.

### Implementation Steps

1. Preserve dirty-worktree context with `git status --short --branch` and a bounded diff stat using `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`.
2. Run a targeted live crawl/backfill for project `69069247778` using the repo's existing remote/live crawler path.
3. Query the database for documents for `69069247778`, checking `size_bytes > 0`, `sha256 <> e3b0c442...b855`, filename suffix `.zip`, current document state, and capture attempt outcome.
4. If the live run fails, patch the smallest affected function:
   - `_table_has_downloadable_document_rows()`: keep metadata/status tables out of document row selection.
   - `_row_download_clickable()`: select row-level document/download controls without allowing metadata cells to masquerade as document rows.
   - `_handle_invitation_modal_download()`: prefer the invitation modal branch for row/cell actions that open nested file lists.
   - `_download_documents_from_current_view()`: capture nested ZIP response before modal recursion or download-event waits.
   - `_document_from_response()`: reject empty bodies.
   - `_document_from_browser_fetch()`: fetch the captured `downloadFileTest` URL with `credentials: "include"` and reject empty bytes.
5. Re-run focused Ruff and pytest after any code edits.
6. Run formal g-check only after live non-empty artifact evidence exists.
7. Create PR, admin-merge, update local `main`, deploy production backend/worker/crawler runtime, then drain backfill and verify sample projects.

### TDD Sequence

1. Add or tighten the focused regression test that reproduces any remaining live defect.
2. Run that test and confirm it fails for the expected reason.
3. Implement the smallest worker-download change.
4. Refactor minimally only if the browser flow becomes harder to follow.
5. Run focused gates, then broader worker gates.

### Test Coverage

- `test_download_one_document_ignores_project_status_metadata_row_in_clickable_table`: metadata/status rows are not documents.
- `test_invitation_row_opens_modal_before_direct_download_timeout`: invitation row avoids direct-download timeout.
- `test_download_documents_from_current_view_captures_zip_fetch_response_first`: nested ZIP response is preferred.
- `test_empty_fetch_response_is_rejected_before_browser_fetch_fallback`: empty response body falls back.
- `test_run_discover_workflow_ingests_live_downloaded_documents_after_persist`: live workflow forwards non-empty document artifacts.

### Decision Completeness

- Goal: land and deploy a worker fix that captures real e-GP modal ZIP artifacts as non-empty documents.
- Non-goals: no search-column rewrite, no Excel system-of-record fallback, no schema/API/UI contract change unless a live failure proves one is required.
- Success criteria: project `69069247778` has at least one document row with `size_bytes > 0`, non-empty SHA not equal to the empty-byte hash, and an expected `.zip` filename after a fresh targeted run; production runtime then shows the same behavior after deploy.
- Public interfaces: no API endpoint, CLI flag, env var, or migration change expected.
- Failure mode: empty response body must fail closed for that capture path and try the credentialed browser-context fetch; it must not persist zero-byte success artifacts.
- Rollout/backout: merge through PR, deploy to Lightsail/Mac crawler runtime, restart only the affected worker/crawler services, back out by reverting the worker commit and redeploying if live capture regresses.
- Acceptance checks: targeted live crawl, database artifact query, Ruff, focused pytest, optional `test_worker_live_discovery.py`, g-check, production health/runtime checks, backfill drain verification.

### Dependencies

- Local `.venv` and Playwright/browser environment.
- Working database credentials/tunnel for targeted crawl and artifact query.
- GitHub CLI permissions for PR/admin merge.
- Lightsail and Mac crawler access for production deployment and launchd/tunnel checks.

### Validation

- Local: `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py`
- Local: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
- Broader: `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q`
- Production: verify API health, crawler/tunnel health, targeted project artifact row, and no new zero-byte artifact for the same source file.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `collect_downloaded_documents()` | Worker live browser discovery/close-check document collection | Called from worker workflows that include live documents | `documents`, `document_capture_attempts`, `discovery_jobs` |
| `_download_documents_from_current_view()` | Modal/subpage file-list traversal | Called by invitation/modal follow-up handlers | `documents` through ingest |
| `_document_from_response()` | Playwright response capture for ZIP fetch | Called by `_click_and_capture_response_document()` | N/A |
| `_document_from_browser_fetch()` | Browser-context credentialed fetch fallback | Called after response capture yields no usable bytes | N/A |
| Backfill enqueue service | systemd timer/service on production host | `deploy/systemd/egp-document-backfill-enqueue.service` | `discovery_jobs`, `document_capture_attempts` |

### Cross-Language Schema Verification

- No DB migration is planned.
- Existing document identity relies on `documents.sha256`.
- Existing durable capture/backfill state relies on `document_capture_attempts`.
- Backfill enqueues use `discovery_jobs.trigger_type = 'backfill'` and project-number keywords.

### Decision-Complete Checklist

- No open implementation decision remains before live validation.
- No public interface change is planned.
- Each behavior change already has focused tests; add only for newly observed defects.
- Validation commands are specific and scoped.
- Runtime wiring covers worker document capture plus backfill enqueue.
- Rollout/backout is deployment-visible and specified.

## Plan Draft B: Review-Gate First

### Overview

Pause live testing long enough to inspect the current diff, normalize logs/service edits, run focused gates, and run g-check before another live crawl. This reduces the chance of testing an accidental unrelated edit, especially because the current worktree is on `main` and includes a modified systemd unit plus two coding logs.

### Files To Change

- `apps/worker/src/egp_worker/browser_downloads.py`: inspect and refine before live test.
- `tests/phase1/test_worker_browser_downloads.py`: ensure regression names and assertions match the two actual root causes.
- `deploy/systemd/egp-document-backfill-enqueue.service`: decide whether this belongs in the PR or is unrelated operational churn.
- Coding logs: keep only the active debug log plus formal review output needed for traceability.

### Implementation Steps

1. Inspect bounded diffs and isolate whether the systemd/log changes are related to the worker modal fix.
2. Run focused Ruff and pytest locally.
3. Run `test_worker_live_discovery.py -q` before live browser work to catch workflow/ingest contract regressions.
4. Run g-check against the working tree and fix any BLOCK/HIGH findings.
5. Only then run the live targeted crawl and artifact SQL verification.
6. Package, submit, merge, land, deploy, and verify production.

### TDD Sequence

1. Convert any g-check finding into a focused failing test.
2. Confirm the new or tightened test fails.
3. Patch the worker function.
4. Keep refactor scope narrow.
5. Re-run focused gates and g-check.

### Test Coverage

- Same focused browser-download tests as Draft A.
- `test_worker_live_discovery.py` workflow tests before live crawl.
- g-check report as a separate review artifact.

### Decision Completeness

- Goal: reduce PR risk before touching live/prod.
- Non-goals: do not deploy or merge until live verification also passes.
- Success criteria: clean focused gates and g-check before live browser validation.
- Public interfaces: no planned API/schema change.
- Failure mode: review may pass while the live browser path still fails, so live verification remains mandatory.
- Rollout/backout: same as Draft A.
- Acceptance checks: local gates/g-check first, live evidence second.

### Dependencies

- Same as Draft A.

### Validation

- Same commands as Draft A, but local review happens before live crawl.

### Wiring Verification

Same as Draft A.

### Cross-Language Schema Verification

Same as Draft A.

### Decision-Complete Checklist

- No public interface changes.
- Review-first ordering selected if live crawler access is currently slow/unavailable.
- Live evidence remains a hard gate before PR/merge/deploy.

## Comparative Analysis

Draft A best matches the current risk: the previous code already passed focused tests once but still produced a zero-byte live success, so the next decisive signal is a fresh targeted live crawl plus database artifact query. Draft B is safer for PR cleanliness but can waste time polishing a still-wrong browser assumption.

The main gap in Draft A is that the dirty worktree includes `deploy/systemd/egp-document-backfill-enqueue.service`; that needs explicit diff review before PR packaging. The main gap in Draft B is delaying the highest-value acceptance check.

Both plans follow repo constraints: keep PostgreSQL as source of truth, avoid Excel closure flags, preserve tenant isolation, and run smallest relevant checks for touched directories.

## Unified Execution Plan

### Overview

Use a hybrid path: inspect the current diff just enough to understand scope, then run the targeted live crawl immediately because non-empty artifact verification is the real gate. If that passes, lock the behavior with broader local gates, formal g-check, clean PR packaging, merge/local landing, production deploy, and production artifact/backfill verification.

### Files To Change

- `apps/worker/src/egp_worker/browser_downloads.py`: worker modal/response/fetch capture logic; only edit further if live/g-check reveals a defect.
- `tests/phase1/test_worker_browser_downloads.py`: focused regression coverage for metadata-row filtering, modal-first branch, response capture, empty-body rejection, and browser fetch fallback.
- `deploy/systemd/egp-document-backfill-enqueue.service`: include only if its diff is necessary for the backfill drain/retry operational path; otherwise move it out of the PR.
- `coding-logs/2026-06-16-18-49-02 Coding Log (document-capture-modal-path-debug).md`: append implementation, validation, g-check, PR, merge, deploy, and production verification notes.

### Implementation Steps

1. Inspect bounded diff stat and specific changed hunks.
2. Run targeted live crawl for project `69069247778`.
3. Query project/document/capture-attempt rows and explicitly check:
   - document file name includes the expected ZIP or real e-GP filename.
   - `size_bytes > 0`.
   - `sha256` is present and not `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
   - stale zero-byte row `5a716181-ad3b-4d20-a598-6c95f36953e4` is superseded, ignored by current listing, or cleaned up with a deliberate audit note.
4. If live fails, implement the smallest targeted fix and repeat focused tests plus live verification.
5. Once live passes, run:
   - `./.venv/bin/ruff check apps/worker/src/egp_worker/browser_downloads.py tests/phase1/test_worker_browser_downloads.py`
   - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_downloads.py -q`
   - `./.venv/bin/python -m pytest tests/phase1/test_worker_live_discovery.py -q`
   - consider `./.venv/bin/python -m compileall apps/worker/src packages` if the final diff touches shared imports or service wiring.
6. Append a concise implementation/validation summary to the active document-capture debug coding log.
7. Run formal g-check on the working tree; fix any BLOCK/HIGH issues and rerun affected gates.
8. Create a feature branch from the current work, preferably not directly on dirty `main`; if needed, use a clean `origin/main` worktree/cherry-pick to avoid unrelated local commits.
9. Create PR with live evidence and test output in the body.
10. Admin-merge to `origin/main`, update local `main` without discarding unrelated local changes.
11. Deploy backend/worker/crawler runtime:
    - merge/pull updated code on Lightsail host.
    - preserve host-local overrides.
    - rebuild/restart affected API/worker executor containers if the worker code is packaged there.
    - update Mac crawler checkout/path if live document capture runs from launchd on the Mac crawler path.
12. Verify production:
    - `https://api.egptracker.com/health`.
    - `docker compose ps` on Lightsail.
    - `launchctl print gui/$(id -u)/com.egp.pg-tunnel`.
    - `launchctl print gui/$(id -u)/com.egp.remote-crawl`.
    - `nc -z 127.0.0.1 15432`.
    - `./scripts/run_remote_crawl.sh check`.
    - targeted crawl/backfill for `69069247778` in production context.
    - SQL query showing non-empty artifact and non-empty SHA.
13. Re-enable/restore any disabled remote crawler launchd/timer state only after the production fix is deployed and the guard check passes.
14. Run a bounded backfill drain and verify a sample of previously zero-document projects no longer end in `document_collection_empty` when e-GP has downloadable rows.

### Test Coverage

- `test_download_one_document_ignores_project_status_metadata_row_in_clickable_table`: ignores status metadata rows.
- `test_invitation_row_opens_modal_before_direct_download_timeout`: avoids direct download timeout.
- `test_download_documents_from_current_view_captures_zip_fetch_response_first`: captures nested ZIP response.
- `test_empty_fetch_response_is_rejected_before_browser_fetch_fallback`: rejects empty response bodies.
- Browser-fetch fallback test: preserves non-empty bytes and filename suffix.
- `test_worker_live_discovery.py` workflow tests: ingest and attempt outcomes remain wired.

### Decision Completeness

- Goal: production document capture produces real non-empty artifacts for e-GP modal ZIP downloads.
- Non-goals: no search-column change; no treating empty e-GP pages as root cause; no API/UI/schema migration unless further evidence requires it; no Excel as source of truth.
- Success criteria:
  - Fresh targeted run for `69069247778` stores non-empty ZIP bytes.
  - Stored SHA is not the empty-byte hash.
  - Capture attempt outcome is success with document count > 0.
  - g-check has no blocking findings.
  - PR is merged to `origin/main`.
  - Local `main` contains the merge.
  - Production runtime has the merged code and passes the same targeted artifact verification.
- Public interfaces: none expected.
- Edge cases/failure modes:
  - Metadata/status row has clickable cells: skip as non-document row.
  - Nested `downloadFileTest` response has headers but empty body: reject and try browser-context credentialed fetch.
  - Browser-context fetch returns empty bytes: fail closed, do not persist a zero-byte document.
  - Known missing-file modal: classify as unavailable, not a generic timeout.
  - Existing zero-byte row: do not let it satisfy acceptance; supersede or clean up deliberately.
- Rollout/monitoring:
  - Watch worker logs for `DOCUMENT_PROGRESS` stages around modal/response/fetch capture.
  - Watch `document_capture_attempts` and `egp_document_capture_attempts_total` outcomes.
  - Watch for repeated `document_collection_empty` on projects with visible e-GP document rows.
  - Back out via revert + redeploy if production capture starts failing broader jobs.
- Acceptance checks:
  - Focused Ruff and pytest pass.
  - Live target SQL evidence passes non-empty checks.
  - g-check passes.
  - Production health and crawler guard checks pass.

### Dependencies

- Live browser/session/crawler environment with e-GP access.
- Database credentials or tunnel for query verification.
- GitHub CLI and admin merge permission.
- Lightsail host and Mac launchd crawler access.

### Validation

Use the targeted live run and SQL evidence as the primary proof, then local gates and production verification as release proof. Do not claim the fix is live until production runtime has been updated and a production-context targeted run shows non-empty artifact bytes.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `browser_downloads.collect_downloaded_documents()` | Live discovery/close-check document capture | Worker workflow call sites pass `include_documents=True` | `documents`, `document_capture_attempts` |
| `_download_one_document()` | Target document iteration for `DOCS_TO_DOWNLOAD` | Called by `collect_downloaded_documents()` | N/A |
| `_handle_invitation_modal_download()` | Invitation/status-row modal branch | Called before direct/page download fallback when click metadata indicates modal probe | N/A |
| `_download_documents_from_current_view()` | Nested modal file-list traversal | Called by modal/invitation/follow-up handlers | N/A |
| `_click_and_capture_response_document()` | Captures `downloadFileTest` ZIP response | Called for nested modal file download buttons | N/A |
| `_document_from_response()` | Converts Playwright response to document bytes | Called by response-capture path | N/A |
| `_document_from_browser_fetch()` | Credentialed browser fetch fallback | Called when captured response body is empty/unusable | N/A |
| `ingest_downloaded_documents()` | Persists captured artifacts | Worker workflows after live crawl result | `documents`, storage provider |
| `egp-document-backfill-enqueue.service` | Enqueues targeted backfill jobs | systemd timer/service on production host | `discovery_jobs`, `document_capture_attempts` |

### Cross-Language Schema Verification

- No migration planned.
- Python repository code uses `documents` for artifacts and `document_capture_attempts` for durable attempt state.
- Backfill wiring uses `discovery_jobs.trigger_type = 'backfill'`.
- Frontend/API generated contracts are not expected to change because this is worker behavior only.

### Decision-Complete Checklist

- No open decision remains for the next implementer other than whether the current systemd diff belongs in this PR after diff inspection.
- Public interface changes: none.
- Behavior changes have focused tests.
- Validation commands are concrete.
- Wiring table covers worker capture and backfill enqueue runtime pieces.
- Rollout/backout is specified.

## Implementation Summary (2026-06-16 21:55:01 +07) - Operator Cloudflare Recovery And Profile Freshness

### Goal

Implement items 3 and 4 from the recovery plan: keep Chrome open when Cloudflare/Turnstile blocks the worker, emit the exact operator-facing status `Cloudflare verification required.`, retry after the operator clears the challenge, and make persistent-profile freshness depend on actual search-control readiness rather than a recent timestamp alone.

### What Changed

- `apps/worker/src/egp_worker/browser_discovery.py`
  - Added explicit Cloudflare/Turnstile detection, profile-freshness invalidation by deleting `.egp-profile-state.json`, and `wait_for_cloudflare_or_operator()`.
  - Live discovery and search recovery now use the operator-aware wait path. When a challenge is detected after the normal wait/reload budget, the worker logs and emits `cloudflare_verification_required` with `Cloudflare verification required.`, leaves Chrome running, waits up to `cloudflare_operator_wait_timeout_ms`, and resumes once the challenge clears.
  - `_wait_for_search_controls_ready()` now returns a boolean so callers can require usable search controls.
- `apps/worker/src/egp_worker/warmup.py`
  - Warm-up now requires Cloudflare clearance plus enabled search controls on the search page before it can succeed.
  - Reads `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS` for manual-verification hold time.
- `apps/worker/src/egp_worker/browser_close_check.py`
  - Close-check entry and return-to-search paths now use the same operator-aware wait.
- `apps/api/src/egp_api/config.py` and `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
  - Added `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS` plumbing and pass it into worker/warm-up browser settings.
- `apps/worker/src/egp_worker/main.py`
  - Parses `browser_cloudflare_operator_wait_timeout_ms` from dispatcher payloads.
- Tests
  - Added focused coverage for operator status emission plus profile-state invalidation, warm-up search-control gating, config parsing, dispatcher payload propagation, and worker payload parsing.

### TDD Evidence

- RED: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py::test_operator_cloudflare_wait_emits_status_and_invalidates_profile_state -q` failed with `ImportError: cannot import name 'CLOUDFLARE_VERIFICATION_REQUIRED_MESSAGE'`.
- RED: `./.venv/bin/python -m pytest tests/operations/test_warm_browser_profile.py::test_warm_page_raises_when_search_controls_never_enable -q` failed with `TypeError: warm_page() got an unexpected keyword argument 'controls_ready'`.
- GREEN: `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py::test_operator_cloudflare_wait_emits_status_and_invalidates_profile_state -q` -> `1 passed`.
- GREEN: `./.venv/bin/python -m pytest tests/operations/test_warm_browser_profile.py::test_warm_page_succeeds_when_cloudflare_clears tests/operations/test_warm_browser_profile.py::test_warm_page_raises_when_search_controls_never_enable -q` -> `2 passed`.

### Tests Run

- `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_build_browser_settings.py -q` -> `93 passed`.
- `./.venv/bin/python -m pytest tests/operations/test_warm_browser_profile.py tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py -q` -> `51 passed`.
- `for i in 1 2 3; do ./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_build_browser_settings.py tests/operations/test_warm_browser_profile.py tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py -q || exit 1; done` -> three consecutive runs of `144 passed`.
- `./.venv/bin/python -m compileall apps/worker/src apps/api/src` -> passed.
- `./.venv/bin/ruff check apps/worker apps/api packages` -> `All checks passed`.

### Wiring Verification

| Component | Wiring Verified? | How Verified |
|-----------|------------------|--------------|
| `wait_for_cloudflare_or_operator()` | YES | Called by live discovery startup/recovery, `search_keyword()`, `clear_search()`, and close-check search-page transitions. |
| `invalidate_profile_freshness()` | YES | Uses the same `.egp-profile-state.json` filename read by the dispatcher freshness check; test asserts the marker is deleted on Turnstile. |
| `cloudflare_operator_wait_timeout_ms` setting | YES | API config -> dispatcher `_build_persistent_warm_browser_settings()` and `_resolve_browser_settings_payload()` -> worker `_build_browser_settings()` -> `BrowserDiscoverySettings`. |
| Warm-up search-control gate | YES | `run_profile_warmup()` can only print `WARMUP_OK` after `warm_page()` succeeds; `warm_page()` now requires enabled search controls on `SEARCH_URL`. |

### Behavior And Risk Notes

- The profile freshness policy now fails closed on Turnstile: a challenge deletes the freshness marker, and a later successful warm/crawl can write it again.
- Operator recovery is bounded by `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS` (default 600000 ms) so the worker keeps Chrome open for manual verification without becoming unbounded forever.
- Existing unrelated dirty files were preserved and not changed by this implementation slice.

### Follow-Ups / Known Gaps

- Production still needs deployment/runtime verification after merge because API/worker changes do not auto-deploy just because the PR lands.
- No database migration or frontend contract change is required.

## Review (2026-06-16 21:56:20 +07) - staged operator recovery slice

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged changes only, because unrelated pre-existing tracked edits remain unstaged in `apps/worker/src/egp_worker/browser_downloads.py`, `tests/phase1/test_worker_browser_downloads.py`, `deploy/systemd/egp-document-backfill-enqueue.service`, and one older coding log.
- Commands Run:
  - `git status -sb`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- apps/worker/src/egp_worker/browser_discovery.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged -- apps/worker/src/egp_worker/warmup.py apps/api/src/egp_api/services/discovery_worker_dispatcher.py apps/worker/src/egp_worker/browser_close_check.py`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --check`
  - `./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_build_browser_settings.py -q`
  - `./.venv/bin/python -m pytest tests/operations/test_warm_browser_profile.py tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py -q`
  - `for i in 1 2 3; do ./.venv/bin/python -m pytest tests/phase1/test_worker_browser_discovery.py tests/phase1/test_worker_build_browser_settings.py tests/operations/test_warm_browser_profile.py tests/phase2/test_browser_runner_config.py tests/phase2/test_persistent_browser_profile.py -q || exit 1; done`
  - `./.venv/bin/python -m compileall apps/worker/src apps/api/src`
  - `./.venv/bin/ruff check apps/worker apps/api packages`

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

- Assumption: a bounded 600000 ms default operator wait is acceptable for production because the outer worker timeout remains the final cap.
- Assumption: close-check should share the same operator-assisted search-page recovery semantics as discovery because it uses the same e-GP search controls and persistent profile.

### Recommended Tests / Validation

- Completed focused tests and repeated flakiness check listed above.
- Before claiming production-live behavior, deploy the API/worker runtime and run a real browser crawl that exercises Cloudflare/Turnstile recovery or at least verifies profile freshness is rewritten only after a successful search-page warm.

### Rollout Notes

- New env knob: `EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS`, default `600000`.
- No migration or frontend change is required.
- Backend/worker deployment is required after merge; this repo's API/worker runtime does not become live from a GitHub merge alone.
