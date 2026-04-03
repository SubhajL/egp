-- Migration 002: Add tenant scoping to documents and document_diffs
-- Date: 2026-04-02

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE documents AS documents_to_backfill
SET tenant_id = projects.tenant_id
FROM projects
WHERE projects.id = documents_to_backfill.project_id
  AND documents_to_backfill.tenant_id IS NULL;

ALTER TABLE documents
ALTER COLUMN tenant_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'documents_tenant_id_fkey'
    ) THEN
        ALTER TABLE documents
        ADD CONSTRAINT documents_tenant_id_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
    END IF;
END $$;

DROP INDEX IF EXISTS documents_project_hash_class_phase_uq;
CREATE UNIQUE INDEX documents_project_hash_class_phase_uq
ON documents(tenant_id, project_id, sha256, document_type, document_phase);

DROP INDEX IF EXISTS idx_documents_project;
CREATE INDEX idx_documents_project
ON documents(tenant_id, project_id, is_current);

DROP INDEX IF EXISTS idx_documents_type;
CREATE INDEX idx_documents_type
ON documents(tenant_id, project_id, document_type, document_phase);

ALTER TABLE document_diffs
ADD COLUMN IF NOT EXISTS tenant_id UUID;

UPDATE document_diffs AS diffs_to_backfill
SET tenant_id = projects.tenant_id
FROM projects
WHERE projects.id = diffs_to_backfill.project_id
  AND diffs_to_backfill.tenant_id IS NULL;

ALTER TABLE document_diffs
ALTER COLUMN tenant_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'document_diffs_tenant_id_fkey'
    ) THEN
        ALTER TABLE document_diffs
        ADD CONSTRAINT document_diffs_tenant_id_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
    END IF;
END $$;

DROP INDEX IF EXISTS idx_diffs_project;
CREATE INDEX idx_diffs_project
ON document_diffs(tenant_id, project_id);
