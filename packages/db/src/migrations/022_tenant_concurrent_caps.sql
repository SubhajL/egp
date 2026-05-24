-- Migration 022: Add tenant admission control caps
-- Date: 2026-05-24

CREATE TABLE IF NOT EXISTS tenant_entitlements (
    tenant_id               UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    max_concurrent_runs     INT NOT NULL DEFAULT 1,
    max_queued_keywords     INT NOT NULL DEFAULT 20,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tenant_entitlements_max_concurrent_runs_check CHECK (
        max_concurrent_runs > 0
    ),
    CONSTRAINT tenant_entitlements_max_queued_keywords_check CHECK (
        max_queued_keywords > 0
    )
);

DROP TRIGGER IF EXISTS update_tenant_entitlements_updated_at ON tenant_entitlements;
CREATE TRIGGER update_tenant_entitlements_updated_at BEFORE UPDATE ON tenant_entitlements
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
