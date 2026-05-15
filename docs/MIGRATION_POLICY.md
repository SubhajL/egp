# Migration Policy

## Current Behavior

The migration runner in
[`packages/db/src/egp_db/migration_runner.py`](../packages/db/src/egp_db/migration_runner.py)
applies SQL files in filename-sorted order and records the full filename in `schema_migrations`.

That means a migration's filename is part of the applied history once it has shipped.

## Historical State

This repo already contains two historical duplicate numeric prefixes:

- `002_document_tenant_scope.sql`
- `002_notification_preferences.sql`
- `008_tenant_crawl_schedule.sql`
- `008_webhook_notifications.sql`

Those files are already part of the migration history. **Do not rename or renumber them** just to
make the historical sequence look cleaner; changing applied filenames would create drift between
existing databases and the repository.

## Rule For New Migrations

For every new migration:

1. Use the next unused zero-padded numeric prefix after the current maximum prefix in
   [`packages/db/src/migrations`](../packages/db/src/migrations).
2. Keep that prefix unique across all checked-in migration files.
3. Use a descriptive snake_case suffix: `NNN_short_description.sql`.

At the time this policy was written, the highest existing prefix is `020`, so the next migration
should start at `021_...sql`.

## Contributor Checklist

- Before adding a migration, list the existing files and choose the next globally unused prefix.
- Do not backfill skipped-looking historical numbers.
- Do not rename applied migration files without a deliberate migration-history repair plan.
- Keep migration filenames stable once they are merged, because the runner records filenames as
  versions.
