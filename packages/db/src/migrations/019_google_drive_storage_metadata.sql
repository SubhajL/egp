-- Migration 019: Google Drive storage metadata
-- Date: 2026-04-16

ALTER TABLE tenant_storage_configs
    ADD COLUMN provider_folder_id TEXT,
    ADD COLUMN provider_folder_url TEXT;

CREATE INDEX idx_tenant_storage_configs_provider_folder
    ON tenant_storage_configs(provider, provider_folder_id);
