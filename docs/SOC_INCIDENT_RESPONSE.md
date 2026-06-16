# SOC Incident Response Runbook

This is the master operational runbook for production incidents. It does not
replace the specialized runbooks; it tells the operator what to check first,
which runbook owns the recovery path, and what evidence must be recorded before
calling an incident closed.

Related runbooks:

- `docs/LIGHTSAIL_LOW_COST_LAUNCH.md` - Lightsail API, Compose, migrations, launch gates.
- `docs/REMOTE_LOCAL_CRAWLER.md` - Track C Mac crawler, tunnel, R2 artifact upload.
- `docs/OBSERVABILITY.md` - Prometheus, Grafana, metrics, alert meanings.
- `docs/BACKUP_AND_RESTORE.md` - database and artifact backups, restore drills.
- `docs/SECRET_ROTATION.md` - credential rotation during incidents and handoff.
- `docs/STRIPE_DEPLOYMENT.md` - Stripe provider deployment and webhook checks.
- `docs/LINE_MANUAL_PROMPTPAY.md` - LINE OA manual PromptPay slip operations.
- `docs/VERCEL_DEPLOYMENT.md` - frontend deployment and Vercel rollback.

## Severity

| Severity | Definition | Examples | First response |
|---|---|---|---|
| SEV-1 | Customer-visible outage, data-loss risk, security incident, or cross-tenant exposure. | API down, document downloads 5xx/422 for many users, leaked secret, tenant mismatch. | Incident commander owns the room; stop risky jobs before debugging. |
| SEV-2 | Major product path degraded with a workaround. | Crawler queue stuck, R2 upload/download failure for new documents, payment callbacks delayed. | Assign one operator to restore service and one to collect evidence. |
| SEV-3 | Limited impact or internal-only degradation. | One tenant backfill failed, Vercel preview broken, Grafana unavailable. | Fix during working hours unless it blocks launch validation. |

If the blast radius is unknown after 15 minutes, treat it as SEV-2 or higher.

## First 15 minutes

1. Name the incident commander and write down the start time.
2. Freeze optional production changes: no manual migrations, no direct DB edits,
   no extra crawler instances, and no secret rotation until the commander calls it.
3. Capture the production runtime shape:
   ```bash
   ssh <lightsail-host> 'cd /srv/egp && docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml ps'
   curl -fsS https://api.egptracker.com/health
   curl -fsS https://api.egptracker.com/metrics | head -n 40
   scripts/run_remote_crawl.sh check
   scripts/install_launchd.sh status
   ```
4. Classify the incident using the severity table.
5. Pick the recovery playbook below and record every command that changes state.

## Incident records

Create a short incident note before changing production state:

```text
Incident:
Severity:
Started at:
Incident commander:
Customer impact:
Suspected component:
Current production git SHA:
Evidence links:
Actions taken:
Rollback point:
Closed at:
Follow-ups:
```

Required close-out evidence:

- production git SHA and deployment command
- API health result
- crawler/tunnel state when crawler is involved
- database query or API response proving the affected entity recovered
- if documents are involved: R2 `head_object` evidence plus a byte-streaming
  download check with `Content-Length`
- if secrets are involved: exact secret family rotated and verification result

## Escalation matrix

| Area | Primary runbook | Escalate when |
|---|---|---|
| API / Lightsail / Compose | `docs/LIGHTSAIL_LOW_COST_LAUNCH.md` | API health stays red after one redeploy or migrations fail. |
| Mac crawler / Cloudflare / tunnel | `docs/REMOTE_LOCAL_CRAWLER.md` | `run_remote_crawl.sh check` fails or Chrome needs manual Cloudflare clearance. |
| Metrics / alerts | `docs/OBSERVABILITY.md` | Alert is firing but the service looks healthy from health checks. |
| DB or artifact recovery | `docs/BACKUP_AND_RESTORE.md` | Any restore, backup integrity issue, or suspected data loss. |
| Credentials | `docs/SECRET_ROTATION.md` | Any token, API key, env file, cookie secret, or service key exposure. |
| Stripe | `docs/STRIPE_DEPLOYMENT.md` | Stripe webhook delivery or payment-link settlement is suspect. |
| LINE / manual PromptPay | `docs/LINE_MANUAL_PROMPTPAY.md` | Slip image ingest, admin notification, or verification is suspect. |
| Web frontend | `docs/VERCEL_DEPLOYMENT.md` | Vercel production or preview deploy is serving the wrong revision. |

## Recovery playbooks

### API or worker deployment recovery

Use this when code has merged to `main` but the production API/worker behavior is
not live. The frontend can auto-deploy from Vercel, but Lightsail does not
auto-deploy API or executor changes.

```bash
ssh <lightsail-host>
cd /srv/egp
git fetch origin
git merge --ff-only origin/main
docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml build api webhook-executor discovery-executor
docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml run --rm migrate
docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml up -d api webhook-executor --scale discovery-executor=0
docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml ps
```

Keep `discovery-executor=0` for Track C. The Mac crawler is the sole production
claimer while gprocurement.go.th requires real Mac Chrome.

Verify from your workstation:

```bash
curl -fsS https://api.egptracker.com/health
scripts/run_remote_crawl.sh check
```

### Targeted document backfill validation

Use this exact playbook for project `69039416683` and for future one-project
document recovery checks. The goal is to prove four things: the merged API and
worker are deployed, a backfill job for the project is processed, the document
artifact exists in R2, and the API download route streams bytes.

1. Confirm the project, tenant, and current document count:
   ```bash
   ssh <lightsail-host>
   cd /srv/egp
   docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml exec postgres \
     sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT p.tenant_id, p.id AS project_id, p.project_number, p.project_state,
          count(d.id) FILTER (
            WHERE d.document_type IN ('invitation','tor')
              AND d.document_phase IN ('invitation','public_hearing','final')
          ) AS target_documents
   FROM projects p
   LEFT JOIN documents d
     ON d.tenant_id = p.tenant_id AND d.project_id = p.id
   WHERE p.project_number = '69039416683'
   GROUP BY p.tenant_id, p.id, p.project_number, p.project_state;
   SQL
   ```

2. Enqueue a bounded due-candidate scan. This is the normal production path and
   records an `enqueued` document-capture attempt:
   ```bash
   docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml run --rm --no-deps discovery-executor \
     python -m egp_api.executors.document_backfill_enqueue --limit 10
   ```

   If the target is not due but an incident commander explicitly approves a
   one-project validation, enqueue the exact project number once:
   ```sql
   WITH target_project AS (
     SELECT p.tenant_id, p.id AS project_id, p.project_number,
            cp.id AS profile_id, cp.profile_type
     FROM projects p
     JOIN crawl_profiles cp
       ON cp.tenant_id = p.tenant_id AND cp.is_active IS TRUE
     WHERE p.project_number = '69039416683'
     ORDER BY cp.updated_at DESC, cp.id DESC
     LIMIT 1
   )
   INSERT INTO discovery_jobs (
     id, tenant_id, profile_id, profile_type, keyword, trigger_type, live,
     job_status, attempt_count, next_attempt_at, created_at, updated_at
   )
   SELECT gen_random_uuid(), tenant_id, profile_id, profile_type, project_number,
          'backfill', TRUE, 'pending', 0, NOW(), NOW(), NOW()
   FROM target_project
   WHERE NOT EXISTS (
     SELECT 1 FROM discovery_jobs dj
     JOIN target_project tp
       ON tp.tenant_id = dj.tenant_id
      AND tp.profile_id = dj.profile_id
      AND tp.project_number = dj.keyword
     WHERE dj.trigger_type = 'backfill'
       AND dj.live IS TRUE
       AND dj.job_status = 'pending'
   );
   ```

3. Drain the production queue from the Mac crawler:
   ```bash
   scripts/run_remote_crawl.sh check
   scripts/run_remote_crawl.sh warm-profile
   scripts/run_remote_crawl.sh crawl 1
   ```

4. Verify the backfill attempt and document rows:
   ```sql
   SELECT d.id, d.file_name, d.storage_key, d.size_bytes, d.sha256, d.created_at
   FROM documents d
   JOIN projects p ON p.id = d.project_id AND p.tenant_id = d.tenant_id
   WHERE p.project_number = '69039416683'
   ORDER BY d.created_at DESC
   LIMIT 5;

   SELECT status, reason, doc_count, attempted_at
   FROM document_capture_attempts a
   JOIN projects p ON p.id = a.project_id AND p.tenant_id = a.tenant_id
   WHERE p.project_number = '69039416683'
   ORDER BY attempted_at DESC
   LIMIT 5;
   ```

5. Verify the R2 object exists with `head_object` using the document
   `storage_key` from the query:
   ```bash
   docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml run --rm --no-deps api \
     python - "$STORAGE_KEY" <<'PY'
   import os
   import sys
   import boto3

   key = sys.argv[1]
   client = boto3.client("s3")
   response = client.head_object(Bucket=os.environ["S3_BUCKET"], Key=key)
   print({"key": key, "content_length": response["ContentLength"], "etag": response["ETag"]})
   PY
   ```

6. Verify the API download streams bytes. Use an authenticated owner/admin
   browser session cookie or bearer token for the tenant that owns the project:
   ```bash
   curl -fSL \
     -H "Authorization: Bearer $EGP_ADMIN_JWT" \
     -D /tmp/egp-download-headers.txt \
     -o /tmp/egp-69039416683-document.bin \
     "https://api.egptracker.com/v1/documents/<document_id>/download"
   grep -i '^Content-Length:' /tmp/egp-download-headers.txt
   test -s /tmp/egp-69039416683-document.bin
   ```

   If validating through a browser session instead of a JWT, replace the
   `Authorization` header with `-b 'egp_session=<session-token>'`.

Close the incident only when the R2 `head_object` content length is non-zero and
the API download response returns bytes with a `Content-Length` header.

### Crawler stuck or no documents found

1. Confirm Lightsail is not claiming jobs:
   ```bash
   ssh <lightsail-host> 'cd /srv/egp && docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml ps discovery-executor'
   ```
2. Confirm the Mac guard and tunnel:
   ```bash
   scripts/run_remote_crawl.sh check
   nc -z 127.0.0.1 15432
   scripts/install_launchd.sh status
   ```
3. If Cloudflare clearance is stale, run `scripts/run_remote_crawl.sh warm-profile`
   and solve the browser challenge on screen.
4. Run `scripts/run_remote_crawl.sh crawl 1` and inspect the newest
   `crawl_runs`, `crawl_tasks`, and `document_capture_attempts` rows.

### Document download or R2 failures

1. Check API env received R2 settings:
   ```bash
   ssh <lightsail-host> 'cd /srv/egp && docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml exec api printenv AWS_ENDPOINT_URL_S3'
   ```
2. Use the `head_object` check above for the document storage key.
3. If the object exists but API download fails, check entitlement status and API
   logs before changing storage:
   ```bash
   docker compose --env-file /etc/egp/egp.env -f docker-compose.yml -f docker-compose.pg-tunnel.yml logs --tail=200 api
   ```
4. If credentials are suspect, follow `docs/SECRET_ROTATION.md` for R2/S3 key
   rotation and re-run the API download check.

### Secret exposure

1. Stop the affected integration if continuing would leak more data.
2. Rotate using `docs/SECRET_ROTATION.md`; do not invent an ad hoc overlap.
3. Restart only the services that read the rotated secret.
4. Verify the dependent path: login for JWT/session, worker project ingest for
   `EGP_INTERNAL_WORKER_TOKEN`, R2 `head_object` and download for object-store
   secrets, payment callback for provider webhook secrets.

### Backup or restore incident

Follow `docs/BACKUP_AND_RESTORE.md`. Do not restore into production until:

- the incident commander has named the restore point,
- current production has been backed up or snapshotted,
- a non-production restore has verified tenants, projects, documents, billing,
  and document download integrity.

### Payment incident

For OPN/Stripe callback or payment-link failures, pause retries only if duplicate
settlement is likely. Use provider dashboards plus the billing tables to confirm
the payment request, provider reference, callback event, and subscription state.
For manual PromptPay/LINE slip incidents, use `docs/LINE_MANUAL_PROMPTPAY.md` and
verify the slip artifact can still be read from the artifact store.
