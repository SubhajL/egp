-- Migration 018: Tenant storage configs and credentials
-- Date: 2026-04-14

CREATE TABLE tenant_storage_configs (
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
    CONSTRAINT tenant_storage_configs_provider_check
        CHECK (provider IN ('managed', 'google_drive', 'onedrive', 'local_agent')),
    CONSTRAINT tenant_storage_configs_connection_status_check
        CHECK (connection_status IN ('managed', 'pending_setup', 'connected', 'error', 'disconnected')),
    CONSTRAINT tenant_storage_configs_tenant_uq UNIQUE (tenant_id)
);

CREATE INDEX idx_tenant_storage_configs_tenant ON tenant_storage_configs(tenant_id);

INSERT INTO tenant_storage_configs (
    tenant_id,
    provider,
    connection_status,
    account_email,
    folder_label,
    folder_path_hint,
    managed_fallback_enabled,
    last_validated_at,
    last_validation_error,
    created_at,
    updated_at
)
SELECT
    tenant_id,
    provider,
    connection_status,
    account_email,
    folder_label,
    folder_path_hint,
    managed_fallback_enabled,
    last_validated_at,
    last_validation_error,
    COALESCE(created_at, NOW()),
    COALESCE(updated_at, NOW())
FROM tenant_storage_settings
ON CONFLICT (tenant_id) DO NOTHING;

CREATE TABLE tenant_storage_credentials (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
    credential_type     TEXT NOT NULL DEFAULT 'oauth_tokens',
    encrypted_payload   TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tenant_storage_credentials_provider_check
        CHECK (provider IN ('google_drive', 'onedrive', 'local_agent')),
    CONSTRAINT tenant_storage_credentials_tenant_provider_uq UNIQUE (tenant_id, provider)
);

CREATE INDEX idx_tenant_storage_credentials_tenant_provider
    ON tenant_storage_credentials(tenant_id, provider);
