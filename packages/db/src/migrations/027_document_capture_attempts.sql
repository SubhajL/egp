-- Migration 027: Document capture attempt audit/backoff table
-- Date: 2026-06-07

CREATE TABLE IF NOT EXISTS document_capture_attempts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id          UUID REFERENCES crawl_runs(id) ON DELETE SET NULL,
    status          TEXT NOT NULL,
    reason          TEXT,
    doc_count       INTEGER NOT NULL DEFAULT 0,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_capture_attempts_status_check CHECK (
        status IN (
            'enqueued',
            'succeeded',
            'no_documents',
            'failed',
            'timeout',
            'skipped'
        )
    ),
    CONSTRAINT document_capture_attempts_doc_count_check CHECK (doc_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_document_capture_attempts_project_attempted
    ON document_capture_attempts(tenant_id, project_id, attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_capture_attempts_status_attempted
    ON document_capture_attempts(tenant_id, status, attempted_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_capture_attempts_run
    ON document_capture_attempts(run_id)
    WHERE run_id IS NOT NULL;
