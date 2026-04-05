-- Migration 006: Add document review workflow for changed diffs
-- Date: 2026-04-05

CREATE TABLE IF NOT EXISTS document_diff_reviews (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_diff_id    UUID NOT NULL REFERENCES document_diffs(id) ON DELETE CASCADE,
    status              TEXT NOT NULL,
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_diff_reviews_status_check CHECK (
        status IN ('pending', 'approved', 'rejected')
    ),
    CONSTRAINT document_diff_reviews_document_diff_unique UNIQUE (document_diff_id)
);

CREATE TABLE IF NOT EXISTS document_review_events (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    review_id           UUID NOT NULL REFERENCES document_diff_reviews(id) ON DELETE CASCADE,
    document_diff_id    UUID NOT NULL REFERENCES document_diffs(id) ON DELETE CASCADE,
    event_type          TEXT NOT NULL,
    actor_subject       TEXT,
    note                TEXT,
    from_status         TEXT,
    to_status           TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT document_review_events_type_check CHECK (
        event_type IN ('created', 'approved', 'rejected', 'reopened')
    ),
    CONSTRAINT document_review_events_from_status_check CHECK (
        from_status IS NULL OR from_status IN ('pending', 'approved', 'rejected')
    ),
    CONSTRAINT document_review_events_to_status_check CHECK (
        to_status IS NULL OR to_status IN ('pending', 'approved', 'rejected')
    )
);

CREATE INDEX IF NOT EXISTS idx_document_diff_reviews_project_created
    ON document_diff_reviews(tenant_id, project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_diff_reviews_status_created
    ON document_diff_reviews(tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_document_review_events_review_created
    ON document_review_events(review_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_document_review_events_diff_created
    ON document_review_events(document_diff_id, created_at ASC);

DROP TRIGGER IF EXISTS update_document_diff_reviews_updated_at ON document_diff_reviews;
CREATE TRIGGER update_document_diff_reviews_updated_at BEFORE UPDATE ON document_diff_reviews
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
