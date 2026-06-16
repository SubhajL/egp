# R2 Document Download Recovery Planning

## Exploration Summary

Auggie semantic search returned the document infrastructure, artifact-store, project
repository, and document API areas. Direct inspection then focused on:

- `AGENTS.md`, `apps/api/AGENTS.md`, `apps/worker/AGENTS.md`, `packages/db/AGENTS.md`
- `apps/api/src/egp_api/routes/documents.py`
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`
- `apps/api/src/egp_api/bootstrap/repositories.py`
- `apps/api/src/egp_api/config.py`
- `apps/worker/src/egp_worker/main.py`
- `apps/worker/src/egp_worker/workflows/discover.py`
- `apps/worker/src/egp_worker/workflows/close_check.py`
- `apps/worker/src/egp_worker/workflows/document_ingest.py`
- `apps/worker/src/egp_worker/browser_downloads.py`
- `packages/db/src/egp_db/artifact_store.py`
- `packages/db/src/egp_db/tenant_storage_resolver.py`
- `packages/db/src/egp_db/repositories/document_delivery.py`
- `packages/db/src/egp_db/repositories/document_persistence.py`
- `packages/db/src/egp_db/repositories/project_persistence.py`
- `packages/db/src/egp_db/repositories/project_aliases.py`
- `packages/db/src/egp_db/repositories/project_queries.py`
- `tests/phase1/test_api_discovery_spawn.py`
- `tests/phase1/test_worker_live_discovery.py`
- `tests/phase1/test_documents_api.py`
- `tests/phase1/test_document_persistence.py`

Working hypothesis:

1. Previous projects are likely not deleted by the normal crawl ingest path. The
   project repository upserts by tenant/canonical id and strong aliases, while the
   public list endpoint is tenant-scoped, paginated, and filterable. Disappearance
   needs a production data audit before any code change claim.
2. New attachment downloads are failing because live discovery/close-check document
   ingestion does not receive `artifact_storage_backend`, `artifact_bucket`, or
   `artifact_prefix`. The worker defaults document ingestion to local storage, but
   the API later resolves unprefixed managed storage keys through the configured R2
   store and returns a direct R2 URL. R2 then returns `NoSuchKey` because the object
   was never written there.
3. The direct download-link path compounds the issue: `/download-link` returns a
   storage URL without verifying object existence. The proxy `/download` route is
   the path that can detect object read failure and use a managed backup fallback.

## Plan Draft A - Fix Wiring and Keep Direct Links

### Overview

Make worker document ingestion use the same artifact store configuration as the API
and keep the existing direct signed URL behavior. Add object-existence validation
before returning direct R2 links so missing-object failures become API errors or
proxy fallbacks instead of raw R2 XML pages.

### Files to Change

- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: include artifact
  storage backend, bucket, prefix, and Supabase/S3-compatible settings in discover
  subprocess payloads.
- `apps/api/src/egp_api/bootstrap/services.py` or dispatcher bootstrap location:
  pass resolved artifact storage config into `SubprocessDiscoveryDispatcher`.
- `apps/worker/src/egp_worker/main.py`: parse artifact backend/bucket/prefix for
  `discover` and `close_check` commands and forward them.
- `apps/worker/src/egp_worker/workflows/discover.py`: accept storage config and pass
  it to `ingest_downloaded_documents`.
- `apps/worker/src/egp_worker/workflows/close_check.py`: accept storage config and
  pass it to `ingest_downloaded_documents`.
- `apps/worker/src/egp_worker/browser_downloads.py`: accept storage config and pass
  it to `ingest_document_artifact`.
- `packages/db/src/egp_db/repositories/document_delivery.py`: add a read/probe path
  for direct link validation before returning a URL when using managed storage.
- `packages/db/src/egp_db/artifact_store.py`: add an optional `exists` or `head`
  protocol method for stores that can check object presence cheaply.
- `tests/phase1/test_api_discovery_spawn.py`: assert discover payload includes
  artifact storage config.
- `tests/phase1/test_worker_live_discovery.py`: assert live discover and close-check
  document ingestion forwards storage config.
- `tests/phase1/test_documents_api.py`: assert missing direct R2 object falls back to
  proxy or returns a structured API error.
- `tests/phase1/test_document_persistence.py`: assert direct link validation uses
  managed backup when primary is unavailable.

### Implementation Steps

TDD sequence:

1. Add/stub tests for discovery payload storage config, worker forwarding, and
   missing-object download-link behavior.
2. Run the targeted tests and confirm they fail because the config is absent and
   direct links are returned without object validation.
3. Implement the smallest wiring change from API dispatcher to worker ingest.
4. Implement direct-link validation and fallback logic.
5. Refactor only duplicated config plumbing if it becomes error-prone.
6. Run fast gates:
   `./.venv/bin/ruff check apps/api apps/worker packages`,
   `./.venv/bin/python -m pytest tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_documents_api.py tests/phase1/test_document_persistence.py -q`.

Function changes:

- `SubprocessDiscoveryDispatcher.__init__`: store resolved artifact backend, bucket,
  prefix, and provider-specific URL/key options needed by worker subprocesses.
- `SubprocessDiscoveryDispatcher.dispatch`: include storage config in the JSON
  payload for `command="discover"`.
- `run_worker_job`: parse storage config for `discover` and `close_check`.
- `run_discover_workflow`: add storage config parameters and pass them to
  `ingest_downloaded_documents`.
- `run_close_check_workflow`: add the same parameters for close-check captures.
- `ingest_downloaded_documents`: forward storage config into
  `ingest_document_artifact`.
- `DocumentDeliveryMixin.get_download_url`: optionally verify/probe key before
  returning a direct URL, then fall back to managed backup when present.
- `S3ArtifactStore.exists` or `head`: call `head_object` with the fully qualified
  key and return a boolean or raise a typed miss.

Expected behavior and edge cases:

- New live-crawl documents are written to the configured R2/Supabase store, not
  local files.
- Existing local-only rows do not silently return unusable R2 URLs.
- Missing primary object with managed backup returns a usable backup/proxy path.
- Missing primary object without backup returns a structured API error, not an R2
  XML page.
- Misconfigured storage fails closed during ingestion instead of claiming successful
  document capture.

### Test Coverage

- `test_discover_spawner_forwards_artifact_storage_config`: payload includes backend.
- `test_run_worker_job_discover_uses_payload_artifact_store`: writes via configured store.
- `test_run_worker_job_close_check_uses_payload_artifact_store`: close-check forwards config.
- `test_ingest_downloaded_documents_forwards_artifact_store`: per-document ingest wiring.
- `test_download_link_probes_s3_before_direct_url`: no raw missing-object URL.
- `test_download_link_uses_backup_when_primary_missing`: backup path is selected.
- `test_download_link_returns_proxy_when_direct_unverified`: browser hits API proxy.

### Decision Completeness

Goal:

- Restore reliable attachment downloads for new crawls and prevent users from seeing
  raw R2 `NoSuchKey` XML.

Non-goals:

- Do not delete, rewrite, or merge existing project rows.
- Do not reintroduce Excel as source of truth.
- Do not implement broad storage-provider migration in this slice.

Success criteria:

- New live discovery and close-check documents create `documents.storage_key` values
  whose objects exist in the configured managed artifact store.
- Browser document download no longer opens an R2 XML `NoSuchKey` page.
- Missing-object cases surface through API-controlled status/error handling.

Public interfaces:

- No new endpoint required.
- Possible additive worker payload fields: `artifact_storage_backend`,
  `artifact_bucket`, `artifact_prefix`, `supabase_url`, `supabase_service_role_key`.
- No DB migration expected.
- No UI copy change required unless surfacing a clearer structured download error.

Edge cases / failure modes:

- Worker has R2 env but payload lacks backend: fail by test before implementation.
- R2 credentials missing: fail closed and mark document capture failed.
- Existing DB row points at local-only object: fail closed through API, with audit
  query/backfill plan.
- Backup object exists but primary missing: prefer backup/proxy.
- Storage prefix changes after rows were written: direct link must not assume current
  prefix is valid for historical rows without probing.

Rollout & monitoring:

- Deploy API and worker together; do not rely on web auto-deploy alone.
- Watch worker logs for `document_store_primary_write_succeeded` provider and
  `raw_storage_key`.
- Watch `document_capture_attempts` non-success outcomes.
- Run production object audit before and after deployment.
- Backout: route `/download-link` to proxy-only behavior while preserving metadata.

Acceptance checks:

- Targeted pytest commands above pass.
- A live crawl writes at least one artifact to R2 and the exact key can be fetched.
- `GET /v1/documents/{id}/download-link` returns a URL that downloads bytes, not XML.
- `GET /v1/documents/{id}/download` streams the same bytes.

### Dependencies

- R2/S3-compatible credentials and endpoint must be available to both API dispatcher
  and worker subprocess environment.
- Production deploy must include the worker runtime, not just the web frontend.

### Validation

- Local tests with fake S3 client.
- Production smoke with one newly crawled project and one existing broken document row.
- SQL audit for orphaned document rows:
  `SELECT id, project_id, storage_key, managed_backup_storage_key FROM documents WHERE tenant_id = ...`.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Dispatcher storage payload | `SubprocessDiscoveryDispatcher.dispatch()` | Created by API services bootstrap | N/A |
| Worker discover storage config | `egp_worker.main:run_worker_job()` | Subprocess module `python -m egp_worker.main` | N/A |
| Discover document ingest | `run_discover_workflow()` | Called by worker `discover` command | `documents` |
| Close-check document ingest | `run_close_check_workflow()` | Called by worker `close_check` command | `documents` |
| Artifact write | `ingest_document_artifact()` | `ingest_downloaded_documents()` | `documents.storage_key` |
| Download link probe | `/v1/documents/{id}/download-link` | `apps/api/src/egp_api/routes/documents.py` | `documents` |

### Cross-Language Schema Verification

Python uses:

- `documents.storage_key`
- `documents.managed_backup_storage_key`
- `document_capture_attempts`
- `projects`
- `project_status_events`

Frontend uses generated OpenAPI document schemas and `fetchDocumentDownloadLink`.
No TypeScript-side DB schema exists.

### Decision-Complete Checklist

- No open decisions remain for the implementer.
- Public worker payload changes are named.
- Behavior changes have tests listed.
- Validation commands are scoped.
- Wiring table covers API, worker, repository, and storage.
- Rollout/backout is specified.

## Plan Draft B - Proxy Downloads First, Then Fix Worker Wiring

### Overview

Immediately stop returning direct R2 links from `/download-link` and always route
browser downloads through the API proxy. Then fix worker storage wiring as a second
step so new artifacts land in R2 while old broken rows produce controlled API errors.

### Files to Change

- `apps/api/src/egp_api/routes/documents.py`: return proxy URLs from
  `/download-link` for managed/S3 storage.
- `packages/domain/src/egp_domain/document_ingest.py`: change
  `get_document_download_link` to prefer proxy when direct link reliability is not
  guaranteed.
- `apps/web/src/app/(app)/projects/[id]/page.tsx`: keep existing link navigation but
  handle proxy `direct=false` consistently.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: add storage config
  to payloads after proxy mitigation.
- `apps/worker/src/egp_worker/main.py`, `workflows/discover.py`,
  `workflows/close_check.py`, `browser_downloads.py`: forward config as in Draft A.
- `tests/phase1/test_documents_api.py`: assert proxy URL is returned for managed
  store and missing objects do not expose storage XML.
- `tests/phase1/test_api_discovery_spawn.py`, `tests/phase1/test_worker_live_discovery.py`:
  assert storage config forwarding.

### Implementation Steps

TDD sequence:

1. Add/stub proxy-first download-link tests and worker storage wiring tests.
2. Run tests and confirm direct-link expectations and missing payload fields fail.
3. Change download-link to proxy-first for managed/S3.
4. Wire artifact backend/bucket/prefix through API dispatcher and worker workflows.
5. Refactor only if storage config plumbing becomes duplicated.
6. Run the same targeted pytest and ruff checks as Draft A.

Function changes:

- `DocumentIngestService.get_document_download_link`: return `url=None` for managed
  storage or when the repository cannot guarantee object existence.
- `get_document_download_link` route: return API proxy URL when service returns no
  direct URL.
- `handleDownload`: no structural change expected; existing code already handles
  direct and proxy links.
- Worker/dispatcher functions: same as Draft A.

Expected behavior and edge cases:

- Users never see R2 XML because browser goes through API proxy.
- API proxy can stream primary or managed backup.
- API returns structured 422 if both primary and backup are missing.
- This increases API bandwidth usage until direct links are safely reintroduced.

### Test Coverage

- `test_document_download_link_returns_proxy_for_managed_s3`: direct false.
- `test_proxy_download_reports_missing_artifact_as_api_error`: no storage XML.
- `test_proxy_download_uses_backup_when_primary_missing`: fallback works.
- `test_discover_spawner_forwards_artifact_storage_config`: worker payload.
- `test_run_worker_job_discover_uses_payload_artifact_store`: writes to R2 fake.
- `test_run_worker_job_close_check_uses_payload_artifact_store`: close-check path.

### Decision Completeness

Goal:

- Prioritize user-visible recovery by routing downloads through API-controlled
  logic, while also fixing the root worker storage wiring.

Non-goals:

- Do not build a full direct-link health cache.
- Do not change billing/entitlement semantics.
- Do not alter project lifecycle logic.

Success criteria:

- Clicking download never opens raw R2 XML.
- New crawls write to configured artifact storage.
- Broken existing rows are diagnosable through structured API errors.

Public interfaces:

- Existing `/download-link` response still returns `url`, `direct`, `filename`,
  `size_bytes`, `sha256`; only `direct` value changes for managed storage.
- Additive worker payload storage fields.
- No DB migration.

Edge cases / failure modes:

- Large files increase API egress: accepted for reliability.
- Missing object and no backup: return API 422 with document/storage key metadata.
- Entitlement failures remain 403 before artifact access.
- Browser popup/new-tab behavior remains same enough because anchor URL is same-origin.

Rollout & monitoring:

- Can deploy proxy-first API before worker fix for immediate user relief.
- Watch API document download latency and error rate.
- Backout: re-enable direct links after probe coverage is stable.

Acceptance checks:

- Same targeted pytest/ruff gates.
- Manual smoke confirms one existing broken link yields API error instead of XML.
- Manual smoke confirms one healthy document downloads through API.

### Dependencies

- API runtime must have artifact-store credentials for proxy reads.
- Production worker still needs env/payload wiring for the root fix.

### Validation

- Tests simulate missing primary and backup fallback.
- Production smoke uses both `/download-link` and `/download`.
- Audit logs confirm provider/key in structured errors.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Proxy-first link | `/v1/documents/{id}/download-link` | documents router | `documents` |
| Proxy stream | `/v1/documents/{id}/download` | documents router | `documents` |
| Dispatcher storage payload | `SubprocessDiscoveryDispatcher.dispatch()` | API services bootstrap | N/A |
| Worker document ingest | `ingest_downloaded_documents()` | discover/close-check workflows | `documents` |

### Cross-Language Schema Verification

Python owns `documents` and `document_capture_attempts`; TypeScript consumes
generated response fields and does not need DB schema changes.

### Decision-Complete Checklist

- No open decisions remain.
- Public response behavior change is listed.
- Tests cover changed behavior.
- Validation commands are scoped.
- Wiring table covers all new paths.
- Rollout/backout is specified.

## Comparative Analysis

Draft A strengths:

- Preserves efficient direct storage downloads.
- Fixes root worker storage config and adds validation.

Draft A gaps:

- Direct link validation can be provider-specific and still misses time-of-use
  object deletion after the probe.
- More complex than needed for immediate user relief.

Draft B strengths:

- Fastest way to prevent raw R2 XML from reaching users.
- Reuses already implemented proxy route, including backup fallback and structured
  API errors.
- Lower risk while diagnosing existing orphaned rows.

Draft B gaps:

- Increases API bandwidth and load.
- Direct links may need later reintroduction for large-file efficiency.

Trade-offs:

- Draft A optimizes for storage-origin download efficiency; Draft B optimizes for
  reliability and operator control.
- Both must fix worker storage wiring. Without that, new captures can continue to
  create DB rows whose objects are not in R2.

Compliance:

- Both plans keep Postgres as source of truth.
- Both preserve tenant-scoped document/project access.
- Both use tests-first sequencing.
- Neither reintroduces Excel or fake closure flags.

## Unified Execution Plan

### Overview

Use Draft B as the first implementation slice, then add the root storage wiring from
Draft A in the same PR. This stops users from seeing raw R2 `NoSuchKey` immediately
and prevents new crawls from writing local-only artifacts while the API expects R2.

### Files to Change

- `packages/domain/src/egp_domain/document_ingest.py`: make
  `get_document_download_link` proxy-first for managed/S3 or when direct reliability
  is unknown.
- `apps/api/src/egp_api/routes/documents.py`: preserve response schema and return
  same-origin proxy URL when the service declines a direct URL.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: carry artifact
  storage backend, bucket, prefix, and provider-specific config into discover
  subprocess payloads.
- `apps/api/src/egp_api/bootstrap/services.py`: pass resolved storage config into
  dispatcher construction.
- `apps/worker/src/egp_worker/main.py`: parse payload storage fields for
  `discover` and `close_check`.
- `apps/worker/src/egp_worker/workflows/discover.py`: accept and forward storage
  config.
- `apps/worker/src/egp_worker/workflows/close_check.py`: accept and forward storage
  config.
- `apps/worker/src/egp_worker/browser_downloads.py`: accept and forward storage
  config into `ingest_document_artifact`.
- `tests/phase1/test_documents_api.py`: update/add download-link and proxy tests.
- `tests/phase1/test_api_discovery_spawn.py`: assert storage fields in subprocess
  payload.
- `tests/phase1/test_worker_live_discovery.py`: assert discover/close-check storage
  forwarding and success document count still records.
- `tests/phase1/test_document_infrastructure.py` or
  `tests/phase1/test_document_persistence.py`: add fake S3 write/read coverage if
  current tests do not already cover the payload-driven path.

### Implementation Steps

TDD sequence:

1. Add tests:
   - proxy-first `/download-link`;
   - missing object returns API-controlled response through `/download`;
   - dispatcher includes storage config;
   - worker discover and close-check forward config to ingestion.
2. Run:
   `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py -q`
   and confirm failures match missing behavior.
3. Implement proxy-first link behavior without changing response schema.
4. Add a small artifact storage config value object or explicit constructor fields
   in `SubprocessDiscoveryDispatcher`.
5. Forward those fields through worker `run_worker_job`, `run_discover_workflow`,
   `run_close_check_workflow`, and `ingest_downloaded_documents`.
6. Keep ingestion fail-closed: if backend is `s3`/`supabase` and credentials/bucket
   are missing, the document capture task should fail and record a non-success
   capture attempt.
7. Run targeted tests and ruff.
8. Run production data audit before deployment:
   - count projects by tenant and state;
   - count documents by storage key prefix/provider;
   - sample broken URL key from the screenshot and check whether an object exists in
     R2 and whether a local artifact exists at the worker artifact root.
9. Deploy API and worker runtime together.
10. Run a live crawl/backfill smoke and verify new object existence plus browser
    download.

Function names:

- `DocumentIngestService.get_document_download_link`: return proxy-needed result
  for managed/S3 until direct link verification is reliable.
- `SubprocessDiscoveryDispatcher.__init__`: accept storage config resolved from API
  env/config.
- `SubprocessDiscoveryDispatcher.dispatch`: add storage fields to JSON payload.
- `run_worker_job`: parse and pass storage fields for `discover` and `close_check`.
- `run_discover_workflow`: thread storage fields to document ingestion.
- `run_close_check_workflow`: thread storage fields to document ingestion.
- `ingest_downloaded_documents`: forward storage fields to `ingest_document_artifact`.

Expected behavior and edge cases:

- Healthy artifacts download through API proxy.
- Broken artifacts produce API 422 instead of R2 XML.
- New crawls write artifacts to R2/Supabase when configured.
- Duplicate document replay still returns existing metadata and does not delete
  referenced objects.
- Historical rows with local-only storage keys remain queryable and auditable.

### Test Coverage

- `test_document_download_link_returns_proxy_for_managed_store`: direct false.
- `test_document_download_missing_primary_returns_structured_error`: no raw XML.
- `test_document_download_uses_managed_backup_after_primary_failure`: backup path.
- `test_discover_spawner_forwards_artifact_storage_config`: payload fields present.
- `test_run_worker_job_discover_passes_artifact_storage_to_ingest`: discover wiring.
- `test_run_worker_job_close_check_passes_artifact_storage_to_ingest`: close-check wiring.
- `test_ingest_downloaded_documents_passes_artifact_storage_config`: per-document path.
- `test_project_list_remains_tenant_scoped_without_deleting_old_rows`: guard against
  mistaken deletion assumptions if a regression test is needed.

### Decision Completeness

Goal:

- Stop raw R2 `NoSuchKey` pages and ensure future crawled attachments are stored
  where the API can serve them.

Non-goals:

- Do not mutate production data during code implementation.
- Do not delete or merge project rows as part of this fix.
- Do not build a complete historical artifact migration until the audit identifies
  which keys are orphaned.

Success criteria:

- Screenshot-class error no longer appears after clicking a document.
- New document capture writes an object whose key matches `documents.storage_key`.
- Project counts by tenant do not decrease during the fix.
- Existing missing artifacts are listed in an audit report with remediation status.

Public interfaces:

- `/v1/documents/{document_id}/download-link`: same response schema; `direct` may
  become `false` for managed/S3 storage.
- Worker JSON payload: additive fields `artifact_storage_backend`,
  `artifact_bucket`, `artifact_prefix`, `supabase_url`, `supabase_service_role_key`
  where relevant.
- No migrations.
- No CLI flag required unless `discovery_dispatch.py` should expose explicit storage
  overrides; env defaults are acceptable.

Edge cases / failure modes:

- Missing primary, backup present: proxy streams backup.
- Missing primary, no backup: API returns structured 422.
- Worker payload missing backend: tests fail; implementation should default from API
  config before payload creation.
- R2 endpoint/bucket env missing: remote crawl guard and worker task fail closed.
- Previous projects "missing": diagnose via tenant/filter/pagination/database audit
  before assuming deletion.

Rollout & monitoring:

- Roll API and worker together.
- Watch logs for `document_store_primary_write_succeeded` provider and key.
- Watch `document_capture_attempts` non-success rate and `DocumentArtifactReadError`.
- Audit production project counts before/after deploy.
- Backout: keep proxy-first link behavior; disable live document capture if storage
  writes still fail.

Acceptance checks:

- `./.venv/bin/ruff check apps/api apps/worker packages`
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_document_persistence.py -q`
- Production SQL audit returns stable project counts before/after.
- Production R2/key audit confirms a new crawl object exists.
- Browser download returns document bytes, not XML.

### Dependencies

- API and worker must share the same `DATABASE_URL`.
- API and worker must share storage env/config for R2/Supabase.
- Production deploy process must update the worker/executor, not only frontend.

### Validation

Use local fake S3 tests first. Then run production read-only audit:

- Count projects and documents by tenant.
- Inspect the screenshot key:
  `tenants/c717b262-07a8-477d-bb78-f36a4a814eb7/projects/f6379d59-...`
- Check whether that key exists in R2.
- If absent, check worker local artifact root for the same relative key.
- Sample a newly crawled document and verify DB key, object existence, and browser
  download.

### Wiring Verification

| Component | Entry Point | Registration Location | Schema/Table |
|-----------|-------------|-----------------------|--------------|
| Proxy download-link | `/v1/documents/{id}/download-link` | `apps/api/src/egp_api/routes/documents.py` | `documents` |
| Proxy byte stream | `/v1/documents/{id}/download` | `apps/api/src/egp_api/routes/documents.py` | `documents` |
| Dispatcher storage config | `SubprocessDiscoveryDispatcher.dispatch()` | API services bootstrap | N/A |
| Worker command parser | `egp_worker.main:run_worker_job()` | `python -m egp_worker.main` subprocess | N/A |
| Discover ingest | `run_discover_workflow()` | worker `discover` command | `documents`, `document_capture_attempts` |
| Close-check ingest | `run_close_check_workflow()` | worker `close_check` command | `documents` |
| Per-document ingest | `ingest_downloaded_documents()` | discover/close-check workflows | `documents.storage_key` |

### Cross-Language Schema Verification

Database tables confirmed in migrations:

- `projects`
- `project_status_events`
- `documents.storage_key`
- `documents.managed_backup_storage_key`
- `document_capture_attempts`
- `discovery_jobs`

Frontend uses generated OpenAPI fields and `fetchDocumentDownloadLink`; no frontend
schema migration is required.

### Decision-Complete Checklist

- No open decisions remain for implementation.
- Public response behavior and worker payload additions are listed.
- Each behavior change has tests.
- Validation commands are concrete.
- Wiring table covers every new/changed runtime path.
- Rollout/backout and monitoring are specified.



## Implementation Summary (2026-06-16 06:20:46 +07) - R2 Document Download Recovery

### Goal
Stop browser clicks from exposing raw R2 `NoSuchKey` XML and fix live/scheduled document-ingest storage wiring so worker-captured artifacts use the same managed store configuration as the API.

### Production Read-Only Audit
- `scripts/run_remote_crawl.sh check`: production remote-crawl guard passed.
- `nc -z 127.0.0.1 15432`: production Postgres tunnel was reachable.
- Production aggregate query found tenant `c717b262-07a8-477d-bb78-f36a4a814eb7` with 58 projects: `open_consulting=8`, `open_invitation=43`, `tor_downloaded=7`.
- Production document key-shape query found 48 document rows, all `managed_unprefixed_tenants`.
- No DB row matched the truncated `f6379d59` screenshot project fragment from the planning note.
- R2 `head_object` on 5 recent document keys returned 404 for all 5 sampled keys.
- Lightsail API container `/var/lib/egp/artifacts/<key>` check returned `exists=no` for 4 sampled keys.

### What Changed
- `packages/domain/src/egp_domain/document_ingest.py`: made `/download-link` proxy-first for unprefixed managed storage keys; prefixed external provider keys (`google_drive:`, `onedrive:`) can still return direct URLs.
- `apps/api/src/egp_api/routes/documents.py`: updated route docstring to describe proxy-first managed-store behavior.
- `apps/api/src/egp_api/bootstrap/repositories.py`: retained resolved artifact backend, bucket, prefix, and Supabase settings in `RepositoryBundle`.
- `apps/api/src/egp_api/bootstrap/services.py`, `apps/api/src/egp_api/main.py`: passed resolved storage settings into the discovery subprocess factory.
- `apps/api/src/egp_api/services/discovery_worker_dispatcher.py`: added storage settings to discover worker JSON payloads.
- `apps/api/src/egp_api/executors/discovery_dispatch.py`: wired standalone Track C dispatcher construction to read and pass storage config from env.
- `apps/worker/src/egp_worker/main.py`: parsed payload storage settings once and forwarded them for `discover`, `close_check`, and existing `document_ingest` commands.
- `apps/worker/src/egp_worker/workflows/discover.py`, `apps/worker/src/egp_worker/workflows/close_check.py`, `apps/worker/src/egp_worker/browser_downloads.py`: threaded storage settings into `ingest_document_artifact`.
- Tests added/updated in `tests/phase1/test_documents_api.py`, `tests/phase1/test_api_discovery_spawn.py`, `tests/phase1/test_worker_live_discovery.py`, and `tests/phase1/test_document_infrastructure.py`.

### TDD Evidence
- RED command:
  `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py::test_document_download_link_returns_proxy_url_for_managed_supabase_store tests/phase1/test_documents_api.py::test_document_download_link_returns_signed_url_for_prefixed_provider_key tests/phase1/test_api_discovery_spawn.py::test_discover_spawner_forwards_artifact_storage_config tests/phase1/test_worker_live_discovery.py::test_run_discover_workflow_can_opt_into_live_browser_document_downloads tests/phase1/test_worker_live_discovery.py::test_run_worker_job_forwards_artifact_storage_config_to_discover_workflow tests/phase1/test_worker_live_discovery.py::test_run_close_check_workflow_forwards_artifact_storage_to_document_ingest tests/phase1/test_worker_live_discovery.py::test_run_worker_job_forwards_artifact_storage_config_to_close_check_workflow -q`
- RED result: 6 failed, 1 passed. Failures matched expected gaps: Supabase link returned `direct=true`; `_make_discover_spawner`, `run_discover_workflow`, and `run_close_check_workflow` rejected storage args; worker job forwarding omitted storage keys.
- GREEN focused command:
  `./.venv/bin/python -m pytest tests/phase1/test_document_infrastructure.py::test_ingest_downloaded_documents_forwards_artifact_storage_config tests/phase1/test_documents_api.py::test_document_download_link_returns_proxy_url_for_managed_supabase_store tests/phase1/test_documents_api.py::test_document_download_link_returns_signed_url_for_prefixed_provider_key tests/phase1/test_api_discovery_spawn.py::test_discover_spawner_forwards_artifact_storage_config tests/phase1/test_worker_live_discovery.py::test_run_discover_workflow_can_opt_into_live_browser_document_downloads tests/phase1/test_worker_live_discovery.py::test_run_worker_job_forwards_artifact_storage_config_to_discover_workflow tests/phase1/test_worker_live_discovery.py::test_run_close_check_workflow_forwards_artifact_storage_to_document_ingest tests/phase1/test_worker_live_discovery.py::test_run_worker_job_forwards_artifact_storage_config_to_close_check_workflow -q`
- GREEN result: 8 passed.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_document_infrastructure.py tests/phase1/test_document_persistence.py -q`: 137 passed, 50 warnings.
- Same targeted pytest command repeated twice more for flakiness: 137 passed each run, 50 warnings each run.
- `./.venv/bin/ruff check apps/api apps/worker packages tests/phase1/test_documents_api.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_document_infrastructure.py`: passed.
- `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/domain/src packages/db/src`: passed.

### Wiring Verification
| Component | Wiring Verified? | Evidence |
|-----------|------------------|----------|
| Proxy-first managed links | YES | `packages/domain/src/egp_domain/document_ingest.py:447` gates direct URLs to external prefixed keys; `apps/api/src/egp_api/routes/documents.py:531` returns `download_document` proxy URL when `link.url is None`. |
| API dispatcher storage payload | YES | `apps/api/src/egp_api/bootstrap/services.py:263` passes bundle storage config; `apps/api/src/egp_api/services/discovery_worker_dispatcher.py:581` writes fields into worker JSON payload. |
| Standalone Track C dispatcher | YES | `apps/api/src/egp_api/executors/discovery_dispatch.py:97` passes env-resolved storage config into `SubprocessDiscoveryDispatcher`. |
| Worker command parser | YES | `apps/worker/src/egp_worker/main.py:87` builds storage kwargs; discover and close-check pass them to workflows. |
| Discover document ingest | YES | `apps/worker/src/egp_worker/workflows/discover.py:566` passes storage settings into `ingest_downloaded_documents`. |
| Close-check document ingest | YES | `apps/worker/src/egp_worker/workflows/close_check.py:155` passes storage settings into `ingest_downloaded_documents`. |
| Per-document artifact write | YES | `apps/worker/src/egp_worker/browser_downloads.py:315` passes storage settings into `ingest_document_artifact`. |

### Self Review / QCHECK
- CRITICAL: No findings.
- HIGH: No findings.
- MEDIUM: No findings after fixing the stale `/download-link` route docstring.
- LOW: No findings.
- Residual risk: proxy-first managed downloads increase API egress until direct-link probing is reintroduced; accepted by plan for reliability.
- Rollout note: API and worker/remote crawler must deploy together. Web auto-deploy alone is insufficient for the worker storage fix.


## Review (2026-06-16 06:24:10 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged working tree before commit
- Commit reviewed: working tree on `7636a398`
- Commands Run: `git branch --show-current && git rev-parse --short HEAD`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; targeted staged diffs for API/worker/domain files; `rg -n "run_scheduled_discovery|discovery_dispatch|egp_worker.main|discovery-executor|webhook-executor" docker-compose.yml deploy .github scripts docs apps`; `./.venv/bin/python -m pytest tests/phase1/test_documents_api.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_document_infrastructure.py tests/phase1/test_document_persistence.py -q`; `./.venv/bin/ruff check apps/api apps/worker packages tests/phase1/test_documents_api.py tests/phase1/test_api_discovery_spawn.py tests/phase1/test_worker_live_discovery.py tests/phase1/test_document_infrastructure.py`; `./.venv/bin/python -m compileall apps/api/src apps/worker/src packages/domain/src packages/db/src`

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
- Assumption: proxy-first behavior for unprefixed managed keys is acceptable API bandwidth tradeoff until direct-link probing is introduced.
- Assumption: passing Supabase service-role config over subprocess stdin is acceptable because it is not exposed in command-line args or run summaries; production R2 path uses inherited AWS env plus payload backend/bucket/prefix.

### Recommended Tests / Validation
- Already passed: 137-test targeted phase1 slice, repeated 3 consecutive times.
- Already passed: ruff and compileall gates.
- Deployment validation still required after merge: run production API/worker deploy, trigger one live crawl/backfill smoke, confirm DB `storage_key`, R2 object existence, `/download-link` returns `direct=false`, and `/download` streams bytes or returns structured 422.

### Rollout Notes
- Deploy API and worker/remote-crawler runtime together. Vercel/web deployment alone does not activate the worker storage fix.
- Existing sampled production keys are missing from both R2 and the API container artifact root; this code prevents raw XML exposure but does not recreate historical missing objects.

## Implementation (2026-06-16 09:37:01 +07) - duplicate replay artifact repair

### Goal
Fix duplicate document replay so a preserved `documents` row no longer blocks artifact recovery when the storage object has disappeared. The durable behavior is: verify the existing artifact, rewrite replay bytes to managed storage if missing, keep the same logical document row, and let targeted backfill/recrawl repair project `69039416683`.

### What Changed
- `packages/db/src/egp_db/artifact_store.py`: added an `exists()` capability to artifact stores. Local storage checks the filesystem, S3/R2 uses `head_object`, and provider stores fall back to a guarded read probe.
- `packages/db/src/egp_db/repositories/document_persistence.py`: before returning the duplicate replay result, checks whether the existing artifact or managed backup is readable. If missing, it writes the replay bytes to managed storage. Managed rows are rewritten at their existing key; external-provider rows receive/refresh `managed_backup_storage_key`.
- `tests/phase1/test_document_persistence.py`: added regression coverage for missing managed artifacts and missing external primaries repaired into managed backup storage without creating a second document row.
- `tests/phase3/test_document_ingest_contract.py`: extended the API-to-worker retry contract so worker replay bytes restore a missing artifact while keeping one row, zero diffs, and the canonical duplicate replay event.

### TDD Evidence
- RED command:
  `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -k 'repairs_missing' -q`
- RED result: 2 failed. The managed-artifact replay returned `created=False` but left the artifact path missing; the external-primary replay returned the existing row with `managed_backup_storage_key is None`.
- GREEN focused command:
  `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -k 'repairs_missing' -q`
- GREEN result: 2 passed.

### Tests Run
- `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py::test_cross_path_document_retry_is_idempotent -q`: 1 passed.
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q`: 26 passed.
- `./.venv/bin/ruff format packages/db/src/egp_db/artifact_store.py packages/db/src/egp_db/repositories/document_persistence.py tests/phase1/test_document_persistence.py tests/phase3/test_document_ingest_contract.py`: 2 files reformatted, 2 unchanged.
- `./.venv/bin/python -m compileall packages/db/src apps/worker/src`: passed.
- `./.venv/bin/ruff check packages/db/src/egp_db/artifact_store.py packages/db/src/egp_db/repositories/document_persistence.py tests/phase1/test_document_persistence.py tests/phase3/test_document_ingest_contract.py`: passed.
- `./.venv/bin/ruff check apps/worker packages`: passed.
- `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py tests/phase3/test_document_ingest_contract.py -q`: 29 passed.
- Same 29-test command repeated three consecutive times for flake check: 29 passed each run. One parallel run emitted a pytest temporary-directory cleanup warning after passing; no test failed.

### Wiring Verification
| Component | Wiring Verified? | Evidence |
|-----------|------------------|----------|
| Artifact existence probe | YES | `DocumentPersistenceMixin._document_artifact_exists()` calls `ResolvedArtifactStore.decode_storage_key()` and `ArtifactStore.exists()` before duplicate replay returns. |
| Duplicate replay repair | YES | `DocumentPersistenceMixin.store_document()` calls `_repair_duplicate_document_artifact()` only inside the existing-document branch, preserving row identity and returning `created=False`. |
| Managed row repair | YES | Regression test unlinks the managed object, replays same bytes, and verifies the original `storage_key` is restored with one document row. |
| External row repair | YES | Regression test simulates a missing Google Drive primary and verifies `managed_backup_storage_key` is populated with managed bytes while the original row id and primary key remain. |
| Worker/API replay path | YES | `test_cross_path_document_retry_is_idempotent` deletes the API-ingested artifact, replays from worker bytes, and verifies one row, zero diffs, and restored bytes. |

### Self Review / QCHECK
- CRITICAL: No findings.
- HIGH: No findings.
- MEDIUM: No findings.
- LOW: No findings.
- Residual risk: provider `exists()` for Google Drive/OneDrive/Supabase uses a read-style probe where cheap metadata checks are not available in the current abstraction; S3/R2 uses `head_object`.

### Behavior Changes And Risk Notes
- Duplicate replay is still idempotent for metadata: no new document row, no diff row, no review row.
- Missing managed artifacts are repaired at the existing storage key, matching the existing document row.
- Missing external primary artifacts are repaired by adding managed backup storage, so existing provider references are preserved while download/content reads can fall back.
- The targeted backfill must still be run for project number `69039416683` after deployment; this change makes that replay repair the artifact instead of silently returning the stale row.

### Follow-ups / Known Gaps
- Production deployment is required for API/worker behavior; merge to `main` alone is not enough for Lightsail.
- After deployment, run a targeted backfill/recrawl for `69039416683` and verify the document row still exists, the managed object exists, and document download streams bytes.

## Review (2026-06-16 09:37:58 +07) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged working tree before commit
- Commit reviewed: working tree on `4f0b812c`
- Commands Run: Auggie formal-review retrieval for artifact repair paths; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; targeted line inspection for `packages/db/src/egp_db/repositories/document_persistence.py`, `packages/db/src/egp_db/artifact_store.py`, `tests/phase1/test_document_persistence.py`, and `tests/phase3/test_document_ingest_contract.py`; `./.venv/bin/python -m pytest tests/phase3/test_document_ingest_contract.py::test_cross_path_document_retry_is_idempotent -q`; `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py -q`; `./.venv/bin/python -m compileall packages/db/src apps/worker/src`; `./.venv/bin/ruff check packages/db/src/egp_db/artifact_store.py packages/db/src/egp_db/repositories/document_persistence.py tests/phase1/test_document_persistence.py tests/phase3/test_document_ingest_contract.py`; `./.venv/bin/ruff check apps/worker packages`; `./.venv/bin/python -m pytest tests/phase1/test_document_persistence.py tests/phase3/test_document_ingest_contract.py -q` repeated three times

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
- Assumption: treating provider read/probe exceptions as "artifact unavailable, attempt managed repair" is the desired duplicate-replay behavior; if managed write also fails, the replay raises and does not silently claim repair.
- Assumption: when an external primary is missing, preserving `storage_key` and adding `managed_backup_storage_key` is preferred over replacing the primary provider reference.

### Recommended Tests / Validation
- Already passed: document persistence suite, API-worker ingest contract test, ruff checks, compileall, and three consecutive runs of the combined 29-test document set.
- Production validation after deploy: run targeted backfill/recrawl for project number `69039416683`, verify the existing project/document row remains, verify the managed object exists in production storage, and verify document download streams bytes.

### Rollout Notes
- Backend/worker deployment is required on Lightsail; Vercel/web auto-deploy alone will not activate this repository-layer repair.
- The targeted backfill should be project-number scoped to `69039416683`, not a broad discovery recrawl.
## Review (2026-06-16 09:56:20 +07) - working-tree follow-up

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: working tree follow-up for duplicate rediscovery lifecycle preservation
- Commands Run: `git status --porcelain=v1`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- packages/domain/src/egp_domain/project_ingest.py`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff -- tests/phase1/test_worker_workflows.py`; `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py::test_api_project_event_sink_preserves_existing_state_on_duplicate_rediscovery -q`; `./.venv/bin/python -m pytest tests/phase1/test_worker_workflows.py tests/phase1/test_document_persistence.py tests/phase3/test_document_ingest_contract.py -q`; `./.venv/bin/ruff check packages/domain/src/egp_domain/project_ingest.py tests/phase1/test_worker_workflows.py`; `./.venv/bin/python -m compileall packages/domain/src`

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
- Assumption: duplicate invitation-stage rediscovery for an already advanced project should preserve the existing lifecycle state, but still update observation fields and allow document replay.
- Assumption: the repository-level transition guard should remain strict for direct upsert callers; the exception belongs at the worker ingest boundary.

### Recommended Tests / Validation
- Already run: focused API-sink regression test for `tor_downloaded` existing project plus `open_invitation` duplicate rediscovery.
- Already run: related worker workflow, document persistence, and document ingest contract tests.
- Production validation still requires rerunning the targeted project backfill and checking R2 object existence for project `69039416683`.

### Rollout Notes
- No schema or environment changes.
- Deploy API image before rerunning the targeted backfill so `/internal/worker/projects/discover` accepts duplicate rediscovery without lifecycle rollback.

## Implementation Summary (2026-06-16 12:13:23 +0700) - SOC runbook and Task Master reconciliation

### Goal
- Close the remaining non-runtime operational gaps before production validation: add a dedicated SOC/incident-response master runbook and reconcile stale Task Master statuses so it can be used as the current source of truth.

### What changed
- `docs/SOC_INCIDENT_RESPONSE.md`
  - Added the master SOC incident-response runbook linking the existing Lightsail, Track C remote crawler, observability, backup/restore, secret-rotation, Stripe, LINE PromptPay, and Vercel runbooks.
  - Added severity definitions, first-15-minute response, incident-record requirements, escalation matrix, recovery playbooks, and exact document-backfill validation steps for project `69039416683`.
  - The validation path covers Lightsail deploy, targeted backfill enqueue/drain, R2 `head_object`, and authenticated API download byte-stream checks with `Content-Length`.
- `tests/operations/test_soc_runbook.py`
  - Added drift coverage that requires the SOC runbook to exist, link the existing operational docs, include the targeted project validation path, and retain basic incident-response sections.
- `.taskmaster/tasks/tasks.json`, `.taskmaster/tasks/task_003.md`, `.taskmaster/tasks/task_004.md`
  - Reconciled Task Master status for implemented payment links/PromptPay QR (3.4), Phase 3 (3), self-service admin (4.4), and SOC/runbooks (4.5).
  - Left DR/backup restore validation (4.6) pending because documentation exists but no current restore-drill evidence was found or run.

### TDD evidence
- RED: `./.venv/bin/python -m pytest tests/operations/test_soc_runbook.py -q`
  - Result: failed with four failures because `docs/SOC_INCIDENT_RESPONSE.md` did not exist.
- GREEN: `./.venv/bin/python -m pytest tests/operations/test_soc_runbook.py -q`
  - Result: `4 passed in 0.01s`.

### Tests run
- `./.venv/bin/python -m pytest tests/operations/test_soc_runbook.py -q` - passed.

### Wiring verification evidence
- The runbook is linked by test coverage through `tests/operations/test_soc_runbook.py`.
- Existing runtime commands referenced in the runbook were verified against actual checked-in entry points:
  - `python -m egp_api.executors.document_backfill_enqueue`
  - `scripts/run_remote_crawl.sh crawl`
  - `GET /v1/documents/{document_id}/download`
  - S3/R2 `head_object` via the `boto3`-backed `S3ArtifactStore`.

### Behavior changes and risk notes
- No runtime behavior changed; this is documentation, operations drift coverage, and Task Master reconciliation.
- The production blocker remains runtime validation after merge/deploy: deploy API/worker on Lightsail, run the targeted backfill for `69039416683`, verify the R2 object, and verify API download streams bytes.

### Follow-ups / known gaps
- Task Master now shows only Phase 4.6 as pending under Phase 4; keep it pending until a real backup/restore drill is run and recorded.

## Review (2026-06-16 12:16:00 +0700) - working-tree

### Reviewed
- Repo: `/Users/subhajlimanond/dev/egp`
- Branch: `main`
- Scope: staged working tree before commit
- Commit reviewed: working tree on `716cdfca`
- Commands Run: Auggie retrieval for SOC/runbook, backfill, R2/download, deployment, and Task Master surfaces; Task Master `get_tasks`; Task Master `set_task_status` for `3.4`, `3`, `4.4`, and `4.5`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --name-only`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --stat`; `CODEX_ALLOW_LARGE_OUTPUT=1 git diff --staged --check`; targeted staged diff inspection for `.taskmaster/tasks/task_003.md`, `.taskmaster/tasks/task_004.md`, `.taskmaster/tasks/tasks.json`, `docs/SOC_INCIDENT_RESPONSE.md`, and `tests/operations/test_soc_runbook.py`; `for i in 1 2 3; do ./.venv/bin/python -m pytest tests/operations/test_soc_runbook.py -q || exit 1; done`; `./.venv/bin/ruff check tests/operations/test_soc_runbook.py`; `./.venv/bin/python -m compileall tests/operations/test_soc_runbook.py`

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
- Assumption: marking Task Master 4.4 done is appropriate because admin APIs/UI, support views, storage settings, billing visibility, and tests are present; DR validation remains pending because only runbook coverage, not a fresh restore drill, is evidenced.
- Assumption: the SOC runbook is allowed to document an incident-commander-approved SQL fallback for exact one-project backfill enqueue, while the normal path remains the existing `document_backfill_enqueue` executor.

### Recommended Tests / Validation
- Already passed: SOC runbook drift test three consecutive times, ruff on the new operations test, compileall for the new operations test, and staged whitespace check.
- Runtime validation still required after merge/deploy: deploy Lightsail API/executors, run targeted project `69039416683` backfill, verify R2 `head_object`, and verify API download streams bytes with `Content-Length`.

### Rollout Notes
- No schema or runtime code changes.
- Lightsail backend deployment is still required after merge; Vercel/frontend auto-deploy does not update API/executor containers.

## Production Validation (2026-06-16 12:26:00 +0700) - PR 160 and Lightsail

### PR and landing
- Created PR: https://github.com/SubhajL/egp/pull/160
- Admin-merged PR #160 to `origin/main` with merge commit `8f738a6c09fcb03b48d727339f246be03a89cb25`.
- Fast-forwarded local `main`; `git status --short --branch` showed `## main...origin/main`.
- GitHub Actions failed before job steps/logs were available; local gates and formal g-check were clean, and admin merge was explicitly requested.

### Lightsail deployment
- Updated `/home/ubuntu/egp` on the Lightsail host to include `origin/main` while preserving host-local overrides.
- Built production images for `api`, `webhook-executor`, and `discovery-executor`.
- Ran production migrations with `sudo docker compose ... run --rm migrate`; result: `Applied 0 migration(s): none`.
- Recreated `egp-api-1` and `egp-webhook-executor-1`; `discovery-executor` remains disabled by the host override as expected for Track C.
- Verified `egp-api-1` healthy and `https://api.egptracker.com/health` returned `{"status":"ok"}`.

### Targeted project validation
- Inserted and drained exact backfill job `bd5ad48a-00b1-490b-9b16-fee8601f1021` for project `69039416683`.
- The first manual drain saw the launchd watcher hold the persistent profile; paused only `com.egp.remote-crawl`, cleared the stale processing marker for that job, drained one bounded crawl, and restarted `com.egp.remote-crawl`.
- Final job row: `job_status=dispatched`, `attempt_count=1`, `dispatched_at=2026-06-16 05:25:29.665404+00`, no `last_error`.
- Capture attempts for project `69039416683` included a new successful attempt at `2026-06-16 05:22:28.729196+00` with `doc_count=1`.
- Production documents were already present and deduplicated, including `de752ddf-b7da-4e50-a6f2-a00d345f8839` / `69039416683_15052569.zip`.

### R2 and API download validation
- R2 `head_object` succeeded for `tenants/c717b262-07a8-477d-bb78-f36a4a814eb7/projects/f6379d59-1cc5-4437-9729-5894d6b50a6e/artifacts/be756aa7091c7b4bb3ae2171fdf3e0ab8eaec0f3f5f86ad7b79df28ffe954efa/69039416683_15052569.zip`.
- R2 result: `content_length=1805061`, ETag `"0149073a65642ce76faf80ac02fad71e"`.
- Authenticated production API download for document `de752ddf-b7da-4e50-a6f2-a00d345f8839` returned HTTP `200`.
- API download headers/body matched: `Content-Length: 1805061`, ETag `"be756aa7091c7b4bb3ae2171fdf3e0ab8eaec0f3f5f86ad7b79df28ffe954efa"`, downloaded bytes `1805061`.

### Remaining gap
- Task Master 4.6 remains pending until a real backup/restore drill is run and recorded.
