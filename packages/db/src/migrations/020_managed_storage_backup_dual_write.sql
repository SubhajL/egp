-- Migration 020: Managed storage backup dual-write
-- Date: 2026-04-16

ALTER TABLE tenant_storage_settings
    ADD COLUMN managed_backup_enabled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE tenant_storage_configs
    ADD COLUMN managed_backup_enabled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE documents
    ADD COLUMN managed_backup_storage_key TEXT;

CREATE INDEX idx_documents_managed_backup_storage_key
    ON documents(managed_backup_storage_key);
