-- Migration 017: Tenant storage settings
-- Date: 2026-04-14

CREATE TABLE tenant_storage_settings (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider                    TEXT NOT NULL DEFAULT 'managed',
    connection_status           TEXT NOT NULL DEFAULT 'managed',
    account_email               TEXT,
    folder_label                TEXT,
    folder_path_hint            TEXT,
    managed_fallback_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    last_validated_at           TIMESTAMPTZ,
    last_validation_error       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tenant_storage_settings_provider_check
        CHECK (provider IN ('managed', 'google_drive', 'onedrive', 'local_agent')),
    CONSTRAINT tenant_storage_settings_connection_status_check
        CHECK (connection_status IN ('managed', 'pending_setup', 'connected', 'error', 'disconnected')),
    CONSTRAINT tenant_storage_settings_tenant_uq UNIQUE (tenant_id)
);

CREATE INDEX idx_tenant_storage_settings_tenant ON tenant_storage_settings(tenant_id);
