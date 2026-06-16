# Backup and Restore Runbook

This runbook covers Postgres backups (full cluster dumps to Cloudflare R2 with a
local cache), document-artifact-bucket mirroring to R2, and the quarterly
restore-drill procedure.

> **Status**: shipped in PR-A of the deployment-readiness initiative
> (see `coding-logs/2026-05-26-09-21-17 Coding Log (launch-readiness-week-summary).md`).
> All scripts live under `scripts/`; testable logic lives in
> `packages/db/src/egp_db/backup_files.py` and `packages/db/src/egp_db/backup_targets.py`.

---

## 1. What gets backed up

| Asset | Tool | Frequency | Off-host destination |
|---|---|---|---|
| Postgres cluster (all schemas via `pg_dump -Fc`) | `scripts/pg_backup.sh` | Daily | Cloudflare R2 |
| Document artifact bucket (Supabase Storage or local-fs) | `scripts/artifact_backup.sh` | Daily | Cloudflare R2 |

Postgres backups are gzipped (`-Fc -Z0` then external `gzip` to avoid
double-compression) and accompanied by a `.sha256` sidecar. The artifact bucket
is mirrored using `rclone copy` — **never `sync`** — so accidental source
deletions are not propagated to the backup remote.

---

## 2. One-time setup

### 2.1 Cloudflare R2 bucket

1. Sign into the Cloudflare dashboard → **R2 Object Storage** → **Create bucket**.
2. Pick a name (e.g. `egp-backups-prod`). Region: **Automatic**. Free tier
   gives 10 GB storage and zero egress fees on retrieval.
3. Create an API token: **Manage R2 API tokens** → **Create API token**.
   - Permissions: **Object Read & Write**
   - Bucket: scope to the bucket you just created
   - TTL: leave open-ended; rotate quarterly (see §6)
4. Note the **Account ID** from the R2 home page sidebar.
5. Save the **Access Key ID** and **Secret Access Key** immediately — the
   secret is shown once.

### 2.2 rclone (artifact backup only)

```bash
# macOS
brew install rclone

# Debian / Ubuntu
sudo apt install rclone
```

Configure two remotes (`rclone config`):

- **Source remote** (Supabase Storage S3 endpoint or another R2 bucket
  hosting the artifacts). Example name: `supabase-prod`.
- **Destination remote** pointing at the R2 backup bucket. Example name:
  `r2-backups`.

For Supabase Storage, see Supabase's "S3 connection" docs; you'll need the
project's S3-compatible endpoint, region, and the storage access keys.

### 2.3 Environment variables

The authoritative production env template lives at
[`deploy/.env.production.example`](../deploy/.env.production.example) and
covers every variable below. For a host that runs **only** backup timers
(no API or workers), you can put a scoped subset in `/etc/egp/backup.env`
(mode `0600`, owned by the backup user) — the variables below are exactly
that subset. For a single-host deploy, prefer the full `/etc/egp/egp.env`.

**Never** commit either file. Rotation procedure for the R2 secret:
see [`docs/SECRET_ROTATION.md`](./SECRET_ROTATION.md) §6.

```bash
# Postgres backup target
DATABASE_URL=postgresql://egp:<password>@localhost:5432/egp
EGP_BACKUP_TARGET=r2
EGP_BACKUP_LOCAL_CACHE_DIR=/var/backups/egp-postgres
EGP_BACKUP_LOCAL_RETENTION_DAYS=14
EGP_BACKUP_LOCAL_KEEP_MIN=3

# Cloudflare R2
EGP_BACKUP_R2_ACCOUNT_ID=<account-id>
EGP_BACKUP_R2_ACCESS_KEY_ID=<access-key-id>
EGP_BACKUP_R2_SECRET_ACCESS_KEY=<secret-access-key>
EGP_BACKUP_R2_BUCKET=egp-backups-prod
EGP_BACKUP_R2_OBJECT_PREFIX=prod/

# Artifact backup (rclone)
EGP_ARTIFACT_BACKUP_SRC_REMOTE=supabase-prod:egp-documents
EGP_ARTIFACT_BACKUP_DEST_REMOTE=r2-backups:egp-artifacts-mirror
```

### 2.4 Local cache directory

```bash
sudo mkdir -p /var/backups/egp-postgres
sudo chown egp-backup:egp-backup /var/backups/egp-postgres
sudo chmod 0750 /var/backups/egp-postgres
```

---

## 3. Daily operation

### 3.1 cron (simple)

```cron
# Postgres backup at 02:15 UTC, artifacts at 02:30 UTC
15 2 * * * cd /opt/egp && set -a && . /etc/egp/backup.env && set +a && scripts/pg_backup.sh >> /var/log/egp-pg-backup.log 2>&1
30 2 * * * cd /opt/egp && set -a && . /etc/egp/backup.env && set +a && scripts/artifact_backup.sh >> /var/log/egp-artifact-backup.log 2>&1
```

### 3.2 systemd timer (preferred on systemd hosts)

`/etc/systemd/system/egp-pg-backup.service`:

```ini
[Unit]
Description=e-GP Postgres backup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=egp-backup
EnvironmentFile=/etc/egp/backup.env
WorkingDirectory=/opt/egp
ExecStart=/opt/egp/scripts/pg_backup.sh
```

`/etc/systemd/system/egp-pg-backup.timer`:

```ini
[Unit]
Description=Daily e-GP Postgres backup

[Timer]
OnCalendar=*-*-* 02:15:00 UTC
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
```

Mirror these two files for `egp-artifact-backup.service` and `egp-artifact-backup.timer`.

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now egp-pg-backup.timer egp-artifact-backup.timer
sudo systemctl list-timers | grep egp
```

---

## 4. Quarterly restore drill

**Goal**: prove a fresh restore actually works against a recent backup,
without touching production.

Record each completed drill in
[`docs/DR_RESTORE_DRILL_EVIDENCE.md`](./DR_RESTORE_DRILL_EVIDENCE.md),
including the command, restored counts, integrity checks, and unresolved
production-readiness caveats.

```bash
# 1. Pick a recent backup
./.venv/bin/python -m egp_db.backup_targets download \
    --object-key prod/egp-pg-2026-05-26T021500Z-abc1234.dump.gz \
    --dest-dir /tmp/egp-drill

# 2. Provision a throwaway Postgres
docker run --rm -d --name egp-drill -e POSTGRES_PASSWORD=drill \
    -p 5599:5432 postgres:15

# 3. Restore
bash scripts/pg_restore.sh \
    --source-path /tmp/egp-drill/egp-pg-2026-05-26T021500Z-abc1234.dump.gz \
    --target-url "postgresql://postgres:drill@localhost:5599/postgres-drill" \
    --yes

# 4. Sanity-check row counts
psql "postgresql://postgres:drill@localhost:5599/postgres-drill" \
    -c "SELECT (SELECT COUNT(*) FROM tenants) AS tenants,
             (SELECT COUNT(*) FROM projects) AS projects,
             (SELECT COUNT(*) FROM documents) AS documents;"

# 5. Tear down
docker stop egp-drill
```

If any step fails, file an incident before the next backup cycle.

---

## 5. Disaster recovery — full restore to a new host

1. Provision the new Postgres host (Lightsail / RDS / Hetzner).
2. Apply migrations on an empty DB:
   ```bash
   ./.venv/bin/python -m egp_db.migration_runner \
       --database-url "$NEW_DATABASE_URL" \
       --migrations-dir packages/db/src/migrations
   ```
   (Skip this step if you'd rather restore the dump into an *empty* DB and
   let `pg_restore` rebuild the schema — `--allow-non-empty` is then unnecessary.)
3. Download the latest backup:
   ```bash
   ./.venv/bin/python -m egp_db.backup_targets download \
       --object-key prod/egp-pg-LATEST.dump.gz \
       --dest-dir /tmp/dr
   ```
4. Restore:
   ```bash
   bash scripts/pg_restore.sh \
       --source-path /tmp/dr/egp-pg-LATEST.dump.gz \
       --target-url "$NEW_DATABASE_URL" \
       --allow-non-empty --yes
   ```
5. Recover artifacts: see §7.

---

## 6. Secret rotation

Quarterly:

1. Generate a new R2 API token in the Cloudflare dashboard.
2. Update `EGP_BACKUP_R2_ACCESS_KEY_ID` / `EGP_BACKUP_R2_SECRET_ACCESS_KEY`
   in `/etc/egp/backup.env`.
3. Run one manual backup to confirm:
   ```bash
   sudo -u egp-backup bash -c 'set -a && . /etc/egp/backup.env && set +a && /opt/egp/scripts/pg_backup.sh'
   ```
4. Delete the old token from Cloudflare only after the manual run succeeds.

---

## 7. Artifact bucket recovery

The artifact backup is a flat mirror — no point-in-time history. To recover:

```bash
# Reverse direction: copy from R2 mirror back to source
rclone copy \
    "$EGP_ARTIFACT_BACKUP_DEST_REMOTE" \
    "$EGP_ARTIFACT_BACKUP_SRC_REMOTE" \
    --dry-run
# Inspect the diff, drop --dry-run when satisfied
```

### Notes on Supabase versioning (if used)

Supabase Storage supports object versioning at the bucket level for *some*
plans. **You should NOT rely on this for DR** — the artifact backup script
above is the authoritative recovery story, because:

- R2's S3 `GetBucketVersioning` / `PutBucketVersioning` APIs are
  unimplemented (Cloudflare docs), so neither side has cross-vendor
  versioning semantics.
- Supabase versioning depends on the platform being available; a true
  independent off-vendor copy is more robust.

If your Supabase plan supports versioning, enable it as a defense-in-depth
measure, but treat `scripts/artifact_backup.sh` as the primary off-site
backup.

---

## 8. Tunable retention

| Var | Default | Meaning |
|---|---|---|
| `EGP_BACKUP_LOCAL_RETENTION_DAYS` | 14 | Local cache pruning window |
| `EGP_BACKUP_LOCAL_KEEP_MIN` | 3 | Always keep this many newest local backups |
| `EGP_BACKUP_REMOTE_RETENTION_DAYS` | 30 | R2 pruning window |
| `EGP_BACKUP_REMOTE_KEEP_MIN` | 3 | Always keep this many newest R2 backups |

Remote rotation runs on-demand via the CLI:

```bash
./.venv/bin/python -m egp_db.backup_targets rotate-remote \
    --retention-days 30 --keep-min 3
```

Add a weekly cron entry for this if you want bounded R2 storage:

```cron
0 3 * * 0 cd /opt/egp && set -a && . /etc/egp/backup.env && set +a && .venv/bin/python -m egp_db.backup_targets rotate-remote --retention-days 30 --keep-min 3 >> /var/log/egp-r2-rotate.log 2>&1
```

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `error: another pg_backup.sh is already running` | Concurrent run | Wait or remove stale lockfile under `$EGP_BACKUP_LOCAL_CACHE_DIR/.pg_backup.lock` |
| `error: insufficient free disk` | Cache filling | Increase volume size or lower `EGP_BACKUP_LOCAL_RETENTION_DAYS` |
| `sha256 mismatch` during restore | Corrupt download or tampered file | Re-download from R2; if mismatch persists, file an incident |
| `pg_restore: connection to server failed` | DB unreachable | Check the host/port in `--target-url` and Postgres is accepting connections |
| `error: target database has N public table(s)` | Restoring over an existing DB | Pass `--allow-non-empty` (you'll overwrite the existing schema) |
| `error: rclone is required` | rclone not installed on the host running the artifact backup | `brew install rclone` or `apt install rclone` |

---

## 10. Reference: script flags

### `scripts/pg_backup.sh`

```
pg_backup.sh [--help]
```
All inputs are environment variables (see §2.3).

### `scripts/pg_restore.sh`

```
pg_restore.sh [--help] \
    (--source <r2|local-fs> --object-key <key> | --source-path <path> [--sidecar-path <path>]) \
    --target-url <postgresql://...> \
    [--allow-non-empty] [--yes]
```

### `scripts/artifact_backup.sh`

```
artifact_backup.sh [--help] [--dry-run] [--verbose]
```
Source and destination remotes come from env vars (see §2.3).

---

## 11. Pg version compatibility

The host running `pg_backup.sh` / `pg_restore.sh` must have `pg_dump` /
`pg_restore` major version **≥ the server major version**. We target
Postgres 15 (Lightsail bundle default and Supabase managed Postgres). If
you upgrade the server, upgrade the client tools first.

Check with:

```bash
pg_dump --version
psql --version
```

---

## 12. What's NOT in this PR

- Continuous archiving / PITR (Point-in-Time Recovery via WAL archiving) —
  use Postgres-managed solutions or Supabase's PITR if you need < 1-day RPO.
- Encryption-at-rest of backups beyond what R2 / the local filesystem
  already provide. If you need client-side encryption, wrap `pg_backup.sh`
  in an `age`/`gpg` pipeline before upload.
- Cross-region replication of the R2 bucket.
- Backup-attempt monitoring / alerting (the launch-readiness Prometheus
  metrics will cover this in a follow-up PR; until then, watch the systemd
  unit status with `systemctl status egp-pg-backup.timer`).
