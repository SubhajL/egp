# DR Restore Drill Evidence

This file records concrete backup/restore validation runs for Task Master 4.6.
Do not mark a future drill complete from runbook text alone; record the command,
environment, restored counts, and remaining caveats here.

## 2026-06-16 - Local Non-Production Postgres Restore Drill

### Scope

- Environment: local throwaway PostgreSQL cluster created by `TempPostgresCluster`.
- Source data: synthetic but realistic tenant-scoped rows for tenants, projects,
  documents, and billing records.
- Restore target: a dropped and recreated non-production database in the same
  temporary cluster.
- Artifact scope: document artifact metadata and SHA identity restored from the
  database dump; production artifact-object streaming was separately validated
  during the 2026-06-16 Lightsail rollout.

### Command

```bash
./.venv/bin/python -m pytest \
  tests/operations/test_pg_backup_restore.py::test_pg_backup_restore_round_trips_temp_postgres -q
```

### Result

- Test result: `1 passed`.
- `restored_tenant_count=2`
- `restored_project_count=1`
- `restored_document_count=1`
- `restored_billing_record_count=1`
- `tenant_isolation_preserved=True`
- `document_sha256_preserved=True`
- `billing_status_preserved=True`
- `sha256_verified=True`

### Production Readiness Notes

- Lightsail `/etc/egp/egp.env` contains the Postgres backup target variables
  (`EGP_BACKUP_TARGET`, `EGP_BACKUP_R2_*`, retention settings, and
  `EGP_BACKUP_LOCAL_CACHE_DIR`).
- The Lightsail host did not have host-level `pg_dump`, `pg_restore`, or `psql`
  on `PATH` at drill time; the running Postgres container has PostgreSQL 15
  client tools available.
- `EGP_ARTIFACT_BACKUP_SRC_REMOTE` and `EGP_ARTIFACT_BACKUP_DEST_REMOTE` existed
  in the Lightsail env file but were empty at drill time, and `rclone` was not
  installed on the host. Artifact mirror scheduling should not be considered
  live until those remotes and `rclone` are provisioned and a mirror run is
  recorded.
