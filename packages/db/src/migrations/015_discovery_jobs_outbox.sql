-- Migration 015: Durable discovery dispatch outbox
-- Date: 2026-04-07

CREATE TABLE IF NOT EXISTS discovery_jobs (
    id                      UUID PRIMARY KEY,
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    profile_id              UUID NOT NULL REFERENCES crawl_profiles(id) ON DELETE CASCADE,
    profile_type            TEXT NOT NULL,
    keyword                 TEXT NOT NULL,
    trigger_type            TEXT NOT NULL DEFAULT 'profile_created',
    live                    BOOLEAN NOT NULL DEFAULT TRUE,
    job_status              TEXT NOT NULL DEFAULT 'pending',
    attempt_count           INTEGER NOT NULL DEFAULT 0,
    last_error              TEXT,
    next_attempt_at         TIMESTAMPTZ NOT NULL,
    processing_started_at   TIMESTAMPTZ,
    dispatched_at           TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT discovery_jobs_status_check CHECK (
        job_status IN ('pending', 'dispatched', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_discovery_jobs_tenant_created
    ON discovery_jobs(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_discovery_jobs_pending_due
    ON discovery_jobs(job_status, next_attempt_at, processing_started_at)
    WHERE job_status = 'pending';
