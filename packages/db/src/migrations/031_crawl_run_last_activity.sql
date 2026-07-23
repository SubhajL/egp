-- Migration 031: Canonical crawl-run activity timestamp
-- Date: 2026-07-23

ALTER TABLE crawl_runs
    ADD COLUMN last_activity_at TIMESTAMPTZ;

UPDATE crawl_runs
SET last_activity_at = COALESCE(finished_at, started_at, created_at)
WHERE last_activity_at IS NULL;

ALTER TABLE crawl_runs
    ALTER COLUMN last_activity_at SET DEFAULT NOW(),
    ALTER COLUMN last_activity_at SET NOT NULL;

CREATE INDEX idx_crawl_runs_tenant_status_activity
    ON crawl_runs(tenant_id, status, last_activity_at DESC);
