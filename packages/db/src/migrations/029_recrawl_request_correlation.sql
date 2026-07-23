-- Migration 029: Durable manual recrawl request and run correlation
-- Date: 2026-07-23

CREATE TABLE IF NOT EXISTS recrawl_requests (
    id                          UUID PRIMARY KEY,
    tenant_id                   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    requested_keyword_count     INTEGER NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT recrawl_requests_keyword_count_check CHECK (
        requested_keyword_count >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_recrawl_requests_tenant_created
    ON recrawl_requests(tenant_id, created_at DESC);

ALTER TABLE discovery_jobs
    ADD COLUMN IF NOT EXISTS recrawl_request_id UUID
        REFERENCES recrawl_requests(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_discovery_jobs_recrawl_request
    ON discovery_jobs(tenant_id, recrawl_request_id, created_at);

ALTER TABLE crawl_runs
    ADD COLUMN IF NOT EXISTS discovery_job_id UUID
        REFERENCES discovery_jobs(id) ON DELETE SET NULL;

ALTER TABLE crawl_runs
    ADD COLUMN IF NOT EXISTS recrawl_request_id UUID
        REFERENCES recrawl_requests(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_crawl_runs_recrawl_request
    ON crawl_runs(tenant_id, recrawl_request_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_crawl_runs_discovery_job
    ON crawl_runs(discovery_job_id, created_at DESC);
