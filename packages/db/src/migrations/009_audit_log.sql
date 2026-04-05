-- Migration 009: Unified tenant audit log
-- Date: 2026-04-05

CREATE TABLE IF NOT EXISTS audit_log_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source          TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       UUID NOT NULL,
    project_id      UUID REFERENCES projects(id) ON DELETE SET NULL,
    document_id     UUID REFERENCES documents(id) ON DELETE SET NULL,
    actor_subject   TEXT,
    event_type      TEXT NOT NULL,
    summary         TEXT NOT NULL,
    metadata_json   JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT audit_log_events_source_check CHECK (
        source IN ('admin', 'document', 'project', 'billing', 'review')
    ),
    CONSTRAINT audit_log_events_entity_type_check CHECK (
        entity_type IN (
            'project',
            'billing_record',
            'document_review',
            'document',
            'user',
            'tenant_settings',
            'webhook'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_audit_log_events_tenant_occurred
    ON audit_log_events(tenant_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_events_tenant_source_entity
    ON audit_log_events(tenant_id, source, entity_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_events_tenant_entity
    ON audit_log_events(tenant_id, entity_type, entity_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_events_tenant_project
    ON audit_log_events(tenant_id, project_id, occurred_at DESC);
