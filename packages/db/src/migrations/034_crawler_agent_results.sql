-- Migration 034: Crawler-agent execution routing and durable result inbox
-- Date: 2026-07-28
--
-- U7 gives the API sole ownership of crawler job state. Two things are needed
-- before any agent endpoint exists:
--
-- 1. Execution routing. The already-deployed external discovery executor claims
--    every due pending job with no backend predicate, so an agent consumer would
--    race it. `execution_backend` partitions the queue. It defaults to 'legacy'
--    so applying this migration changes no existing behaviour.
--
-- 2. A durable result inbox with per-claim-attempt identity, so a result that
--    arrives from a lease that has since been reclaimed can never be applied.
--
-- The `result_received` job status is the non-claimable state that accepting a
-- result moves a job into, consuming its lease. Without it, this race exists:
-- token A submits a result, the job stays 'pending', A's lease expires, token B
-- reclaims the job, and the processor later applies A's stale result.

-- ---------------------------------------------------------------------------
-- 1. Execution-backend routing on discovery_jobs
-- ---------------------------------------------------------------------------

ALTER TABLE discovery_jobs
    ADD COLUMN execution_backend TEXT NOT NULL DEFAULT 'legacy',
    ADD CONSTRAINT discovery_jobs_execution_backend_check CHECK (
        execution_backend IN ('legacy', 'agent')
    );

-- Widen the status vocabulary with the non-claimable post-result state. The
-- constraint stays an explicit allow-list; it must not become free text.
--
-- IF EXISTS is deliberate: migration 015 creates discovery_jobs with
-- CREATE TABLE IF NOT EXISTS, so a database where SQLAlchemy metadata created
-- the table first would not carry the named constraint, and an unconditional
-- DROP would abort the whole migration.
ALTER TABLE discovery_jobs
    DROP CONSTRAINT IF EXISTS discovery_jobs_status_check;

ALTER TABLE discovery_jobs
    ADD CONSTRAINT discovery_jobs_status_check CHECK (
        job_status IN ('pending', 'dispatched', 'failed', 'result_received')
    );

-- Required so the inbox can reference (tenant_id, job_id) as a composite FK,
-- which is what makes cross-tenant result attachment impossible at the DB level.
ALTER TABLE discovery_jobs
    ADD CONSTRAINT discovery_jobs_tenant_id_id_key UNIQUE (tenant_id, id);

-- Claim path for the agent backend: mirrors idx_discovery_jobs_pending_lease
-- from migration 032 but partitioned by backend.
CREATE INDEX idx_discovery_jobs_pending_backend
    ON discovery_jobs(execution_backend, job_status, next_attempt_at, lease_expires_at)
    WHERE job_status = 'pending';

-- ---------------------------------------------------------------------------
-- 2. Durable, idempotent result inbox
-- ---------------------------------------------------------------------------

CREATE TABLE crawler_agent_results (
    id                    UUID PRIMARY KEY,
    tenant_id             UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    job_id                UUID NOT NULL,
    claim_token           UUID NOT NULL,
    contract_version      TEXT NOT NULL,
    idempotency_key       TEXT NOT NULL,
    envelope              JSONB NOT NULL,
    envelope_sha256       TEXT NOT NULL,
    inbox_status          TEXT NOT NULL DEFAULT 'pending',
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    -- NOT NULL with a default on purpose: a retry query of the form
    -- `next_attempt_at <= now()` silently skips NULL rows forever.
    next_attempt_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error_code       TEXT,
    -- Processor ownership. Without a processor lease, a consumer that crashes
    -- after setting 'processing' strands the row permanently.
    processor_token       UUID,
    processing_expires_at TIMESTAMPTZ,
    processing_heartbeat_at TIMESTAMPTZ,
    received_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at            TIMESTAMPTZ,

    CONSTRAINT crawler_agent_results_contract_version_check CHECK (
        contract_version IN ('v1')
    ),
    CONSTRAINT crawler_agent_results_status_check CHECK (
        inbox_status IN ('pending', 'processing', 'applied', 'failed', 'rejected')
    ),
    CONSTRAINT crawler_agent_results_error_code_check CHECK (
        last_error_code IS NULL OR last_error_code IN (
            'stale_claim_token',
            'envelope_invalid',
            'envelope_conflict',
            'contract_version_unsupported',
            'tenant_mismatch',
            'job_not_found',
            'apply_failed_transient',
            'apply_failed_permanent',
            'processor_lease_lost'
        )
    ),
    -- A row in 'processing' MUST carry its processor lease. Otherwise the very
    -- stranding this table's lease columns exist to prevent reappears: a reclaim
    -- query of the form `processing_expires_at <= now()` would skip a
    -- lease-less 'processing' row forever.
    CONSTRAINT crawler_agent_results_processing_lease_check CHECK (
        inbox_status <> 'processing'
        OR (processor_token IS NOT NULL AND processing_expires_at IS NOT NULL)
    ),
    -- One accepted result per claim ATTEMPT. The transport idempotency_key and
    -- envelope_sha256 are deliberately NOT part of this key: they exist so the
    -- application can tell an identical replay (return the original row) from a
    -- conflicting one (409) without permitting two different terminal bodies
    -- for a single claim.
    CONSTRAINT crawler_agent_results_claim_key UNIQUE (tenant_id, job_id, claim_token),
    -- Cross-tenant result attachment is impossible: the job must belong to the
    -- same tenant as the result row.
    CONSTRAINT crawler_agent_results_job_fk FOREIGN KEY (tenant_id, job_id)
        REFERENCES discovery_jobs (tenant_id, id) ON DELETE CASCADE
);

-- Drain query: pending/failed rows whose retry time has arrived, oldest first.
CREATE INDEX idx_crawler_agent_results_drain
    ON crawler_agent_results(next_attempt_at)
    WHERE inbox_status IN ('pending', 'failed');

-- Stale-processor reclaim: rows stuck in 'processing' past their lease.
CREATE INDEX idx_crawler_agent_results_processing_lease
    ON crawler_agent_results(processing_expires_at)
    WHERE inbox_status = 'processing';

CREATE INDEX idx_crawler_agent_results_tenant_received
    ON crawler_agent_results(tenant_id, received_at DESC);
