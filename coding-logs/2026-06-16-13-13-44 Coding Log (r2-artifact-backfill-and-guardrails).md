# R2 Artifact Backfill and Guardrails

## Emergency Repair (2026-06-16 13:13:44 +07)

### Goal

Restore production document downloads for tenant `c717b262-07a8-477d-bb78-f36a4a814eb7`
without re-crawling e-GP, then define the follow-up implementation needed to prevent
local-only artifacts from recurring.

### Production Evidence

Auggie semantic search unavailable; planning and repair were based on direct file
inspection, schema inspection, and production read-only audits. Auggie returned
`HTTP error: 402`.

Inspected paths:

- `apps/api/AGENTS.md`
- `packages/AGENTS.md`
- `apps/api/src/egp_api/routes/documents.py`
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
- `apps/worker/src/egp_worker/main.py`
- `packages/db/src/egp_db/artifact_store.py`
- `packages/db/src/egp_db/repositories/document_delivery.py`
- `packages/db/src/egp_db/repositories/document_persistence.py`
- `packages/db/src/egp_db/repositories/document_schema.py`
- `scripts/run_remote_crawl.sh`
- `.env.remotecrawl` env-key names only; secret values not printed

The failing browser URL was:

`/v1/documents/14ea4607-3108-46cc-abc2-4333ca049a1b/download`

DB metadata for that document:

- `project_number`: `69049141124`
- `project_state`: `tor_downloaded`
- `document_type`: `invitation`
- `file_name`: `ประกาศเชิญชวน.pdf`
- `size_bytes`: `112787`
- `sha256`: `93e64d83d26e69c874e49e1e79c1fd4b81ff6e783ab07869278e01ad23833575`
- `storage_key`: `tenants/c717b262-07a8-477d-bb78-f36a4a814eb7/projects/13dd73a8-9a0c-4bcf-b3e8-4ebab2f90978/artifacts/93e64d83d26e69c874e49e1e79c1fd4b81ff6e783ab07869278e01ad23833575/ประกาศเชิญชวน.pdf`

Initial audit:

- Tenant documents: `48`
- R2 present: `1`
- R2 missing: `47`
- Local files present for all 48 under `.data/artifacts`
- Local candidate bytes: `128188171` (`122.25 MiB`)
- Exact failing local file matched DB size and SHA-256.

### Repair Executed

Uploaded missing local artifacts to Cloudflare R2 under their exact DB `storage_key`
values.

Safety gates used before upload:

- DB row exists for each key.
- Local file exists under `.data/artifacts/<storage_key>`.
- Local file `size_bytes` matches the DB row.
- Local file SHA-256 matches the DB row.
- R2 object is missing before upload.

First uploader result:

- Used boto3 `put_object`.
- Uploaded 30 missing objects successfully.
- Stalled during one object socket write; interrupted with `KeyboardInterrupt`.

Retry uploader result:

- Switched to one `aws s3 cp` process per object with a per-object timeout.
- Uploaded remaining 17 objects.
- Per-object `head_object` verification passed.

Final independent audit:

- Tenant documents: `48`
- R2 present: `48`
- R2 missing: `0`
- R2 size mismatches: `0`

Exact failing object verification:

- R2 `get_object` bytes: `112787`
- R2 SHA-256: `93e64d83d26e69c874e49e1e79c1fd4b81ff6e783ab07869278e01ad23833575`

The unauthenticated API download URL returned `401`, so the authenticated browser
path could not be fully replayed from curl in this shell. The prior `NoSuchKey`
condition is resolved at the storage layer.

### TDD and Validation Evidence

No application code was changed during the emergency repair; this was an
operator-side storage backfill. There was no RED/GREEN test cycle for the upload
itself because the production write used live DB/R2 state, not a code change.
The follow-up implementation plan below includes the tests-first work needed to
turn this repair into repeatable code.

Commands/evidence captured during the repair:

- Read-only DB query for the failing document row.
- R2 `head_object` for the failing key returned 404 before repair.
- Local file `stat` and `shasum -a 256` matched DB `size_bytes` and `sha256`.
- Tenant audit before repair: `documents=48 r2_present=1 r2_missing=47`.
- Upload pass 1: 30 objects uploaded before a boto3 socket write stalled.
- Upload pass 2: 17 remaining objects uploaded through bounded `aws s3 cp`.
- Final R2 audit: `total=48 present=48 missing=0 bad_size=0`.
- Exact failing R2 object: `bytes=112787 sha256=93e64d83d26e69c874e49e1e79c1fd4b81ff6e783ab07869278e01ad23833575`.

### Reasoning and Implementation Gaps Found

1. The first diagnosis correctly separated project recrawl from artifact storage
repair, but it did not immediately quantify the whole tenant blast radius. The
later audit showed 47 missing R2 objects, not a single bad document.

2. The first upload implementation used a single long-running boto3 process without
per-object progress or socket timeout. It safely uploaded many objects, but the
stall made operator visibility poor. The retry path, one bounded object per
process, is the better operational shape.

3. The download endpoint smoke test from this shell cannot represent an authenticated
browser session. A future runbook needs an authenticated API smoke path or an
admin-only storage audit endpoint/job so verification does not depend on manual
browser state.

4. Local code now includes artifact-storage payload plumbing, but the broken June 15
rows prove the live worker runtime produced local-only artifacts then. The follow-up
must verify deployed/runtime process configuration, not infer safety from source.

5. `download-link` and `/download` can surface structured API errors, but users still
experienced a hard failure. The system lacks a proactive orphaned-artifact audit
that alerts before the user clicks.

6. Duplicate replay can repair missing artifacts when the same document is ingested
again, but relying on recrawl/duplicate replay is indirect and unnecessary when
the local artifact exists. A first-class audit/backfill command is needed.

## Plan Draft A - Add a Dedicated Artifact Audit and Backfill Command

### Overview

Create an explicit operator command that audits `documents.storage_key` against the
configured artifact store and optionally uploads matching local files. This keeps
repair independent from crawling and gives operators a dry-run path before any
production write.

### Files to Change

- `scripts/backfill_document_artifacts.py`: new CLI for audit and upload repair.
- `tests/phase1/test_document_artifact_backfill_cli.py`: CLI tests with fake DB
  rows and fake S3/local stores.
- `docs/REMOTE_LOCAL_CRAWLER.md`: add the runbook section for artifact backfill.
- `coding-logs/...`: append implementation evidence after work completes.

### Implementation Steps

TDD sequence:

1. Add failing tests for dry-run audit, hash mismatch refusal, existing-object skip,
   missing-local refusal, and successful upload.
2. Run the new test file and confirm failures are about missing CLI behavior.
3. Implement the smallest CLI: load DB rows, validate local path, validate size/SHA,
   head remote key, and upload only when `--execute` is present.
4. Add progress output, per-object subprocess/SDK timeout, and JSON summary.
5. Run focused tests, ruff, and compile checks.

Function outline:

- `load_env_file(path)`: strict parse env file without shell evaluation.
- `load_document_rows(database_url, tenant_id, document_id=None)`: return bounded
  document metadata needed for repair.
- `audit_document(row, local_root, artifact_store)`: classify as `present`,
  `repairable`, or `refused` with reason.
- `upload_repair(candidate, artifact_store, timeout_s)`: upload one validated local
  file and verify remote head afterward.
- `main(argv)`: parse `--tenant-id`, optional `--document-id`, `--execute`,
  `--json`, and `--timeout-seconds`.

### Test Coverage

- `test_dry_run_reports_repairable_without_upload`: audit only, no writes.
- `test_execute_uploads_missing_valid_artifact`: uploads exact missing key.
- `test_existing_remote_object_is_skipped`: avoids overwriting present object.
- `test_hash_mismatch_is_refused`: prevents corrupt upload.
- `test_missing_local_file_is_refused`: no false repair claim.
- `test_json_summary_has_counts`: operator-readable automation output.

### Decision Completeness

Goal:

- Make artifact repair repeatable, auditable, and independent from recrawl.

Non-goals:

- Do not modify `documents` schema.
- Do not delete or rewrite project rows.
- Do not crawl e-GP as part of artifact repair.

Success criteria:

- Dry-run identifies the same count of missing repairable objects as the live audit.
- Execute mode uploads only validated local files.
- Final audit returns `missing=0` and `bad_size=0`.

Public interfaces:

- New CLI: `scripts/backfill_document_artifacts.py`.
- Flags: `--env-file`, `--tenant-id`, `--document-id`, `--execute`, `--json`,
  `--timeout-seconds`.
- No API, DB schema, or web UI changes.

Failure modes:

- Local file missing: fail closed; report refused.
- Size/SHA mismatch: fail closed; report refused.
- Remote upload timeout: fail current object; continue only if `--continue-on-error`
  is explicitly added later.
- Missing credentials: fail before audit execution.

Rollout and monitoring:

- Run dry-run first.
- Run execute only after dry-run has zero refused rows.
- Re-run dry-run after execute and store JSON summary in the coding log.

Acceptance checks:

- `./.venv/bin/python -m pytest tests/phase1/test_document_artifact_backfill_cli.py -q`
- `./.venv/bin/ruff check scripts/backfill_document_artifacts.py tests/phase1/test_document_artifact_backfill_cli.py`
- Production dry-run JSON shows expected candidates.
- Production execute summary shows uploaded count and zero refused.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| `scripts/backfill_document_artifacts.py` | operator CLI | direct script invocation | `documents.storage_key`, `documents.size_bytes`, `documents.sha256` |
| `load_document_rows` | CLI main | imported within same script | `documents`, optional `projects` for reporting |
| `upload_repair` | CLI main execute branch | same script | R2 key equals DB `documents.storage_key` |

## Plan Draft B - Make Download Path Self-Heal From Local Artifacts

### Overview

Teach the document download path to repair a missing managed object when the local
artifact exists, then continue streaming the file. This makes the user click succeed
even when a previous worker wrote local-only artifacts.

### Files to Change

- `packages/db/src/egp_db/repositories/document_delivery.py`: add repair-on-read
  hook for managed missing-object cases.
- `packages/db/src/egp_db/repositories/document_persistence.py`: extract reusable
  repair helper if needed.
- `tests/phase1/test_documents_api.py`: prove download repairs missing R2 object.
- `tests/phase1/test_document_persistence.py`: prove repair refuses mismatched bytes.

### Implementation Steps

TDD sequence:

1. Add failing tests for download of a DB row whose remote object is missing but
   local file exists.
2. Implement a repository helper that validates local bytes and writes them to
   managed storage before streaming.
3. Keep mismatch/missing-local behavior as `DocumentArtifactReadError`.
4. Run document API and repository tests.

Function outline:

- `_local_artifact_path_for_document(document)`: derive local path from local root
  plus storage key.
- `_repair_managed_artifact_from_local(document)`: validate size/SHA and upload.
- `iter_document_bytes`: on managed missing-object, attempt repair before raising.

### Test Coverage

- `test_download_repairs_missing_managed_object_from_local`: click succeeds.
- `test_download_refuses_local_hash_mismatch`: corrupt local file not uploaded.
- `test_download_missing_local_still_returns_structured_error`: no fake success.

### Decision Completeness

Goal:

- Make user downloads resilient to historical local-only artifact rows.

Non-goals:

- Do not build an operator batch repair command.
- Do not repair external provider documents from local disk automatically.

Success criteria:

- First download of a missing managed object repairs and streams bytes.
- Subsequent download uses R2 directly.

Public interfaces:

- No new endpoint.
- No schema change.
- Possible new env var only if API local artifact root differs from current
  `EGP_ARTIFACT_ROOT`.

Failure modes:

- API host lacks local artifact: still fails with structured error.
- Local file mismatch: fail closed.
- Concurrent clicks may race; object upload must be idempotent.

Rollout and monitoring:

- Deploy API only after tests cover fallback.
- Log `document_artifact_repair_from_local` with tenant/project/document id.
- Watch for repair count spikes.

Acceptance checks:

- Existing `/v1/documents/{id}/download` tests pass.
- New repair tests prove first-click recovery.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| repair-on-read helper | `DocumentDeliveryMixin.iter_document_bytes()` | repository method call | `documents.storage_key`, `documents.sha256`, `documents.size_bytes` |
| API behavior | `GET /v1/documents/{document_id}/download` | `apps/api/src/egp_api/routes/documents.py` router | `documents` |

## Comparative Analysis

Draft A is safer operationally. It is explicit, auditable, dry-runnable, and does
not add side effects to user downloads. It also works even when the API host cannot
see the Mac's local `.data/artifacts` tree, as long as the operator runs it on the
Mac where the files live.

Draft B gives the best user experience for future clicks but couples download
latency to a repair write and only works if the API runtime has access to the local
artifact tree. In this deployment, the API is remote and the local artifacts are on
the Mac crawler host, so self-heal-on-read is likely the wrong primary repair.

Both drafts miss one thing unless combined with a runtime guard: future recrawls can
still create broken rows if the live worker process runs stale code or lacks R2 env.
The unified plan must include a pre-dispatch artifact-store guard and a recurring
audit.

## Unified Execution Plan for gpt-5.3-codex-spark

### Overview

Implement a dedicated artifact audit/backfill CLI first, then add runtime guardrails
that prevent live workers from claiming document-producing jobs unless artifact
storage is configured for the managed R2 store. Keep user downloads simple: they
should stream from the configured store and return structured errors, while repair
is an explicit operator job.

### Files to Change

- `scripts/backfill_document_artifacts.py`
  - New operator CLI with dry-run and execute modes.
- `tests/phase1/test_document_artifact_backfill_cli.py`
  - Unit tests for audit classifications, upload behavior, refusals, and JSON output.
- `scripts/remote_crawl_guard.py`
  - Strengthen guard output to include `artifact_storage_backend`,
    `artifact_storage_bucket`, and `artifact_storage_prefix`, and fail if
    `EGP_ARTIFACT_STORE=s3` credentials are incomplete.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
  - Add structured log line for worker payload artifact fields
    `artifact_storage_backend`, `artifact_storage_bucket`, and
    `artifact_storage_prefix` without printing secrets.
- `apps/worker/src/egp_worker/main.py`
  - Log effective artifact backend as `artifact_storage_backend=<value>` for
    discover/close_check/document_ingest commands.
- `docs/REMOTE_LOCAL_CRAWLER.md`
  - Add artifact repair runbook: dry-run, execute, verify, and when not to recrawl.

### Implementation Steps

TDD sequence:

1. Add tests for the new CLI audit classes and execute behavior.
2. Run the tests and confirm RED failures: no CLI exists.
3. Implement the CLI with dry-run only.
4. Add execute tests and implement upload with per-object timeout/progress.
5. Add guard/logging tests for artifact-store config visibility.
6. Implement guard/logging changes.
7. Run focused tests and lint/compile gates.

Function outline:

- `parse_env_file(env_file: Path) -> dict[str, str]`
  - Parse `.env.remotecrawl` without shell evaluation, matching the remote runner's
    safety model.
- `build_artifact_store(config) -> ArtifactStoreAdapter`
  - Create a thin S3/R2 adapter with `head` and `upload_file` operations.
- `iter_document_artifact_rows(database_url, tenant_id, document_id=None)`
  - Read only `id`, `tenant_id`, `project_id`, `file_name`, `size_bytes`, `sha256`,
    and `storage_key` from `documents`.
- `classify_artifact(row, local_root, remote_store)`
  - Return `present`, `repairable`, or `refused` with exact reason.
- `execute_repairs(candidates, remote_store, timeout_seconds)`
  - Upload one object per process or bounded SDK call, verify with remote head, and
    stop on first failed upload unless a future explicit continue flag is added.
- `emit_summary(summary, json_enabled)`
  - Print stable counts: total, present, repairable, uploaded, refused, bad_size.
- `log_artifact_storage_payload(...)`
  - Log `artifact_storage_backend=<value>`,
    `artifact_storage_bucket=<non-secret-name>`, and
    `artifact_storage_prefix=<non-secret-prefix>` at dispatch/worker start
    without credentials.

### Test Coverage

- `test_parse_env_file_does_not_shell_evaluate_values`
  - Chrome paths with spaces remain safe.
- `test_dry_run_identifies_missing_repairable_artifact`
  - Missing remote plus valid local becomes repairable.
- `test_existing_remote_object_is_skipped`
  - Existing remote object is counted as present and never overwritten.
- `test_dry_run_refuses_missing_local_file`
  - No upload possible without local bytes.
- `test_dry_run_refuses_size_mismatch`
  - DB/local size mismatch blocks repair.
- `test_dry_run_refuses_sha_mismatch`
  - Hash mismatch blocks repair.
- `test_execute_uploads_and_head_verifies`
  - Upload path writes exact key and verifies.
- `test_execute_stops_on_upload_timeout`
  - Timeout fails closed with clear summary.
- `test_dispatcher_logs_artifact_backend_without_secrets`
  - Runtime visibility, no secret leakage.
- `test_worker_logs_effective_artifact_backend`
  - Operator can prove worker is not local-only.

### Decision Completeness

Goal:

- Prevent and repair local-only document artifacts without using recrawl as a repair
  mechanism.

Non-goals:

- No DB migration.
- No web UI in this slice.
- No automatic browser-session auth smoke.
- No object deletion or metadata rewriting.

Success criteria:

- CLI dry-run can report `present=48 missing=0` after the emergency repair.
- CLI execute can repair a fixture missing-object case in tests.
- Remote crawler guard and logs make the effective artifact backend observable.
- Future live document-producing runs show exact proof field
  `artifact_storage_backend=s3`.

Public interfaces:

- New CLI:
  - `./.venv/bin/python scripts/backfill_document_artifacts.py --env-file .env.remotecrawl --tenant-id <tenant-id> --json`
  - Add `--execute` to perform uploads.
  - Optional `--document-id <uuid>` for one-row repair.
- No endpoint/schema changes.

Failure modes:

- Credentials missing: fail before DB or storage write.
- Remote head fails with non-404: fail closed; do not assume missing.
- Local path missing: refused.
- Size/hash mismatch: refused.
- Upload timeout: fail closed; summary includes object id.
- Authenticated download cannot be smoke-tested from shell: verify storage directly
  and ask operator/browser to re-click.

Rollout and monitoring:

1. Land CLI and logging.
2. Restart `com.egp.remote-crawl` so the long-running dispatcher is definitely on
   current code/env.
3. Run CLI dry-run in production; expect `missing=0`.
4. Trigger one small document-producing crawl only after backend logs show `s3`.
5. Re-run dry-run; expect new document keys present in R2.

Backout:

- CLI is additive. If it misbehaves, do not run with `--execute`.
- Logging-only runtime changes can remain; no behavioral backout required.

Acceptance checks:

- `./.venv/bin/python -m pytest tests/phase1/test_document_artifact_backfill_cli.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py -q`
- `./.venv/bin/ruff check scripts/backfill_document_artifacts.py apps/api apps/worker packages tests/phase1/test_document_artifact_backfill_cli.py`
- `./.venv/bin/python -m compileall apps packages scripts`
- Production: dry-run JSON reports `missing=0 refused=0`.
- Production: exact document `14ea4607-3108-46cc-abc2-4333ca049a1b` R2 SHA matches DB SHA.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| artifact backfill CLI | direct operator command | `scripts/backfill_document_artifacts.py` | `documents.storage_key`, `documents.size_bytes`, `documents.sha256` |
| dry-run audit | CLI `main()` | same script | `documents` |
| execute upload | CLI `main()` with `--execute` | same script | R2 object key equals `documents.storage_key` |
| dispatcher artifact logging | `SubprocessDiscoveryDispatcher.dispatch()` | API services bootstrap creates dispatcher | N/A |
| worker artifact logging | `egp_worker.main.run_worker_job()` | subprocess command `python -m egp_worker.main` | N/A |
| remote guard artifact validation | `scripts/run_remote_crawl.sh check/watch` | `scripts/remote_crawl_guard.py` | N/A |

### Cross-Language Schema Verification

Python repository schema uses:

- `documents.id`
- `documents.tenant_id`
- `documents.project_id`
- `documents.file_name`
- `documents.sha256`
- `documents.storage_key`
- `documents.managed_backup_storage_key`
- `documents.size_bytes`

API route uses generated document response models and calls service/repository
methods; no TypeScript DB schema exists. Frontend uses generated OpenAPI types and
download URLs only.

### Decision-Complete Checklist

- No open decisions remain for the implementer.
- Public interface is limited to one new CLI and logging.
- Every behavior change has tests listed.
- Validation commands are scoped and concrete.
- Wiring table covers every new component.
- Rollout/backout is explicit.

## Mixed-Content Download Hotfix Note (2026-06-16 13:47:47 +0700)

### Goal

Restore browser document downloads after Chrome blocked proxied document links as mixed content. The console showed `https://www.egptracker.com/` attempting to download from `https://api.egptracker.com/v1/documents/<id>/download`, but the file navigation was redirected or resolved through an insecure `http://` URL.

### What Changed

- `apps/api/src/egp_api/routes/documents.py`
  - Added `_build_proxy_download_url()` for `/download-link` fallback URLs.
  - The helper uses `X-Forwarded-Proto` and `X-Forwarded-Host` when present, so a TLS-terminating proxy such as Caddy can produce public `https://api.../download` links instead of backend-local `http://...` links.
- `apps/web/src/lib/api.ts`
  - Added `resolveDocumentDownloadHref()`.
  - Non-direct proxy download links are rebuilt against `NEXT_PUBLIC_EGP_API_BASE_URL`, then forced to HTTPS when the current page is HTTPS.
  - Direct provider links are also HTTPS-normalized on HTTPS pages because Chrome will block insecure file downloads from a secure origin anyway.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`
  - Project detail download clicks now use `resolveDocumentDownloadHref(link)` instead of trusting `link.url` verbatim.

### TDD Evidence

- RED: Not run. This was handled as an urgent source hotfix from live browser evidence; validation was not run because this turn did not explicitly request tests/verification.
- GREEN: Not run for the same reason.

### Tests Run

- Not run.

### Wiring Verification Evidence

- API wiring: `get_document_download_link()` now calls `_build_proxy_download_url()` when `DocumentDownloadLink.url` is `None`, which is the managed/local proxy path.
- Frontend wiring: `handleDownload()` in the project detail page now calls `resolveDocumentDownloadHref()` before assigning `anchor.href`.

### Behavior Changes and Risk Notes

- The API should now emit HTTPS proxy download URLs when called through a proxy that sends standard forwarded headers.
- The frontend no longer trusts insecure proxy download URLs returned by `/download-link`; it reconstructs proxy downloads from the configured API base.
- Risk: if a legitimate direct external provider only supports HTTP, the frontend will rewrite it to HTTPS on secure pages. That is intentional for the current browser security model because Chrome blocks insecure downloads from HTTPS origins.

### Follow-ups / Known Gaps

- Add focused tests for forwarded-header proxy URL generation and frontend mixed-content normalization.
- Deploy/restart the API if relying on the backend-side fix; redeploy the web app for the frontend-side defensive fix.
- After deployment, verify a browser click produces no mixed-content console error and that the network request stays on `https://api.egptracker.com/v1/documents/<id>/download`.

## Mixed-Content Download Hotfix Validation and Landing (2026-06-16 15:55:08 +0700)

### Goal

Finish the mixed-content download hotfix by adding regression coverage, validating locally,
deploying the affected runtimes, and landing the source changes on `main`.

### What Changed

- `apps/api/src/egp_api/routes/documents.py`
  - Kept `/download-link` proxy fallback generation behind `_build_proxy_download_url()`.
  - The helper honors the first value of `X-Forwarded-Proto` and `X-Forwarded-Host` when present.
- `tests/phase1/test_documents_api.py`
  - Added `test_document_download_link_uses_forwarded_https_proxy_url()` to lock the TLS proxy behavior.
- `apps/web/src/lib/api.ts`
  - Kept `resolveDocumentDownloadHref()` as the frontend defensive normalizer.
  - Fixed URL normalization to copy `hostname` and `port` explicitly from the API base, avoiding stale backend ports such as `:8000`.
- `apps/web/tests/unit/api.test.ts`
  - Added coverage for rewriting an internal HTTP proxy URL to `https://api.egptracker.com/...`.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`
  - Project-detail downloads use `resolveDocumentDownloadHref(link)`.
- `.gitignore`
  - Added `.vercel` so local Vercel project metadata and prebuilt output are not committed.

### TDD Evidence

- RED: `cd apps/web && npm run test:unit -- tests/unit/api.test.ts` initially failed after adding the mixed-content normalization test because assigning `URL.host` left the stale `:8000` port in the resolved URL.
- GREEN: `cd apps/web && npm run test:unit -- tests/unit/api.test.ts` passed after changing the normalizer to copy `hostname` and `port` explicitly.

### Tests Run

- `./.venv/bin/ruff check apps/api/src/egp_api/routes/documents.py tests/phase1/test_documents_api.py` -> passed.
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q` -> `31 passed, 14 warnings`.
- `cd apps/web && npm run test:unit -- tests/unit/api.test.ts` -> `1 passed`, `11 passed`.
- `cd apps/web && npm run typecheck` -> passed.
- `cd apps/web && npm run lint` -> passed with the existing Next 15 deprecation warning for `next lint`.
- `cd apps/web && npm run build` -> failed locally with `ERR_INVALID_URL` from local env URL loading.
- `cd apps/web && NEXT_PUBLIC_SITE_URL=https://egptracker.com NEXT_PUBLIC_EGP_API_BASE_URL=https://api.egptracker.com npm run build` -> passed.

### Production Verification

- Backend: copied the API route hotfix to `/home/ubuntu/egp`, rebuilt `api` and `webhook-executor`, and restarted both with Docker Compose.
- Backend health: `https://api.egptracker.com/health` returned `{"status":"ok"}`.
- Live `/download-link`: authenticated request for document `14ea4607-3108-46cc-abc2-4333ca049a1b` returned a public HTTPS proxy URL with `direct=false`.
- Live `/download`: authenticated request returned HTTP 200 over HTTPS with `content-length: 112787`, matching the DB/R2 size evidence for the same SHA.
- Frontend: direct Vercel CLI deployment first targeted the wrong local project link (`web`). The correct production project is Git-driven from `origin/main` on Vercel project `egp`, so the source must be pushed to `origin/main` to trigger the normal production frontend deploy.

### Wiring Verification Evidence

- API: `get_document_download_link()` calls `_build_proxy_download_url()` in the fallback proxy path.
- Frontend helper: `resolveDocumentDownloadHref()` is exported from `apps/web/src/lib/api.ts`.
- Frontend UI: project detail download click handling imports and calls `resolveDocumentDownloadHref()`.
- Tests cover both the API forwarded-header contract and frontend proxy URL normalization.

### Behavior Changes and Risk Notes

- Backend-side production behavior is already live and verified for the known failing document.
- Frontend-side defensive behavior becomes live after the `origin/main` push completes and Vercel auto-deploys project `egp`.
- Local build requires valid public URL env values; the production-url override passed, while the un-overridden local env build failed before this change was landed.

### Follow-ups / Known Gaps

- After pushing `origin/main`, verify the Vercel deployment on `egptracker.com`, `www.egptracker.com`, and `app.egptracker.com`.

## Review (2026-06-16 15:55:08 +0700) - working-tree

### Reviewed

- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged working tree for mixed-content document download hotfix
- Commands Run:
  - `mcp__auggie_mcp.codebase_retrieval` -> unavailable with `HTTP error: 402`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --stat`
  - `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --cached --name-only`
  - `nl -ba apps/api/src/egp_api/routes/documents.py | sed -n '250,550p'`
  - `nl -ba apps/web/src/lib/api.ts | sed -n '560,610p'`
  - `nl -ba apps/web/src/app/(app)/projects/[id]/page.tsx | sed -n '180,205p'`
  - `nl -ba tests/phase1/test_documents_api.py | sed -n '1330,1380p'`
  - `nl -ba apps/web/tests/unit/api.test.ts | sed -n '130,175p'`
  - `./.venv/bin/ruff check apps/api/src/egp_api/routes/documents.py tests/phase1/test_documents_api.py`
  - `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py -q`
  - `cd apps/web && npm run test:unit -- tests/unit/api.test.ts`
  - `cd apps/web && npm run typecheck`
  - `cd apps/web && npm run lint`
  - `cd apps/web && NEXT_PUBLIC_SITE_URL=https://egptracker.com NEXT_PUBLIC_EGP_API_BASE_URL=https://api.egptracker.com npm run build`

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

- Assumes the production proxy continues to send `X-Forwarded-Proto: https` and `X-Forwarded-Host: api.egptracker.com`; the backend live verification confirmed the current deployment does.
- Assumes Vercel production remains Git-driven from `origin/main` for project `egp`; this was confirmed from the deployment alias shape and repo docs earlier in the turn.

### Recommended Tests / Validation

- After pushing to `origin/main`, verify Vercel completes the production deployment for project `egp`.
- Re-check a browser download from `https://www.egptracker.com` and confirm the network request stays on `https://api.egptracker.com/v1/documents/<id>/download` with no mixed-content console error.

### Rollout Notes

- Backend side is already live and verified on Lightsail.
- Frontend defensive side becomes live after the `origin/main` push triggers Vercel production deployment.

## Production Diagnosis: Project 69069247778 Missing Documents (2026-06-16 16:50:45 +0700)

### Goal

Explain why project `8e645ef7-a063-45b9-a8bb-cec61d6983fa` / `69069247778`
shows no documents in production even though e-GP has document links.

### Findings

- The project exists for tenant `c717b262-07a8-477d-bb78-f36a4a814eb7`.
- It was first discovered on `2026-06-07` under alias project number `69049163846`.
- It later gained current project number alias `69069247778` on `2026-06-15`.
- Production `documents` has zero rows for this project and no matching rows under the old alias.
- Production `document_capture_attempts` has zero rows for this project.
- There are no `discovery_jobs` with keyword `69049163846` or `69069247778`.
- The original `project_status_events.raw_snapshot` has `downloaded_documents: []`,
  `document_collection_status: no_documents`, and
  `document_collection_reason: document_collection_empty`.
- `list_due_backfill_candidates()` currently includes this project as a due candidate:
  `project_state=open_invitation`, `attempt_count=0`, `target_document_count=0`,
  `project_number=69069247778`.
- The backfill systemd unit files exist in `/home/ubuntu/egp/deploy/systemd`, but
  `egp-document-backfill-enqueue.timer` and `.service` are not installed on Lightsail.

### Conclusion

This is not a frontend display bug and not another R2 missing-object bug. The API
has no document metadata to return. The crawler once saw the project but collected
zero documents, and the durable backfill/retry timer that should enqueue this due
candidate is not installed/running on Lightsail.

### Recommended Next Step

Run the document backfill enqueue path for production, then let the remote crawler
process the `69069247778` backfill job and verify `document_capture_attempts` plus
`documents` rows for this project.
