-- Migration 030: Auditable and idempotent operator recovery requests
-- Date: 2026-07-23

ALTER TABLE recrawl_requests
    ADD COLUMN source TEXT NOT NULL DEFAULT 'manual';

ALTER TABLE recrawl_requests
    ADD COLUMN idempotency_key TEXT;

ALTER TABLE recrawl_requests
    ADD CONSTRAINT recrawl_requests_source_check CHECK (
        source IN ('manual', 'operator_recovery')
    );

CREATE UNIQUE INDEX idx_recrawl_requests_tenant_idempotency
    ON recrawl_requests(tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
