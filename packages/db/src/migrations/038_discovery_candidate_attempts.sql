-- Migration 038: Discovery candidate attempt accounting
-- Date: 2026-08-06
--
-- Tracks every candidate accepted from the e-GP results table during a
-- discovery crawl run.  Each row starts as 'accepted' and transitions to
-- a terminal state (persisted / dropped / failed) once the worker finishes
-- processing it.  Candidates still 'accepted' after the worker exits are
-- reconciled to 'unknown' with terminal_reason = 'worker_lost'.
--
-- The (tenant_id, run_id, candidate_key) uniqueness constraint prevents
-- the same search-result row from being double-counted within one run.

CREATE TABLE discovery_candidate_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    run_id UUID NOT NULL,
    candidate_key TEXT NOT NULL,
    keyword TEXT NOT NULL,
    page_number INTEGER,
    row_ordinal INTEGER,
    candidate_status TEXT NOT NULL DEFAULT 'accepted',
    terminal_reason TEXT,
    project_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT discovery_candidate_attempts_status_check CHECK (
        candidate_status IN ('accepted', 'persisted', 'dropped', 'failed', 'unknown')
    ),
    CONSTRAINT discovery_candidate_attempts_tenant_run_key UNIQUE (tenant_id, run_id, candidate_key)
);

CREATE INDEX idx_dca_tenant_run ON discovery_candidate_attempts(tenant_id, run_id);
CREATE INDEX idx_dca_open_accepted ON discovery_candidate_attempts(run_id, candidate_status) WHERE candidate_status = 'accepted';

-- Re-use the shared updated_at trigger function from migration 001.
CREATE TRIGGER update_discovery_candidate_attempts_updated_at
    BEFORE UPDATE ON discovery_candidate_attempts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
