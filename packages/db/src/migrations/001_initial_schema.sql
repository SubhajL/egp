-- e-GP Intelligence Platform — Initial Schema
-- Migration 001: Core tables for project lifecycle, documents, crawl runs
-- Date: 2026-04-02

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==========================================================================
-- Tenants & Users
-- ==========================================================================

CREATE TABLE tenants (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    plan_code       TEXT NOT NULL DEFAULT 'free',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    full_name       TEXT,
    role            TEXT NOT NULL DEFAULT 'viewer',  -- owner/admin/analyst/viewer
    status          TEXT NOT NULL DEFAULT 'active',  -- active/suspended/deactivated
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, email),
    CONSTRAINT users_role_check CHECK (role IN ('owner', 'admin', 'analyst', 'viewer')),
    CONSTRAINT users_status_check CHECK (status IN ('active', 'suspended', 'deactivated'))
);

-- ==========================================================================
-- Crawl Profiles & Keywords
-- ==========================================================================

CREATE TABLE crawl_profiles (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                        TEXT NOT NULL,
    profile_type                TEXT NOT NULL DEFAULT 'tor',  -- tor/toe/lue/custom
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
    max_pages_per_keyword       INT NOT NULL DEFAULT 15,
    close_consulting_after_days INT NOT NULL DEFAULT 30,
    close_stale_after_days      INT NOT NULL DEFAULT 45,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT profiles_type_check CHECK (profile_type IN ('tor', 'toe', 'lue', 'custom'))
);

CREATE TABLE crawl_profile_keywords (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id      UUID NOT NULL REFERENCES crawl_profiles(id) ON DELETE CASCADE,
    keyword         TEXT NOT NULL,
    position        INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_profile_keywords_profile ON crawl_profile_keywords(profile_id);

-- ==========================================================================
-- Projects — Core lifecycle tracking
-- ==========================================================================

CREATE TABLE projects (
    id                              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Identity
    canonical_project_id            TEXT NOT NULL,
    project_number                  TEXT,
    project_name                    TEXT NOT NULL,
    organization_name               TEXT,

    -- Classification
    procurement_type                TEXT,  -- goods/services/consulting/unknown
    budget_amount                   NUMERIC(18,2),
    currency                        TEXT DEFAULT 'THB',

    -- Lifecycle state
    project_state                   TEXT NOT NULL DEFAULT 'discovered',
    closed_reason                   TEXT,

    -- Source data
    source_status_text              TEXT,
    proposal_submission_date        DATE,
    invitation_announcement_date    DATE,
    winner_announced_at             DATE,
    contract_signed_at              DATE,

    -- Tracking timestamps
    first_seen_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_changed_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_run_id                     UUID,

    -- Flags
    is_active                       BOOLEAN NOT NULL DEFAULT TRUE,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (tenant_id, canonical_project_id),

    CONSTRAINT projects_state_check CHECK (project_state IN (
        'discovered',
        'open_invitation',
        'open_consulting',
        'open_public_hearing',
        'tor_downloaded',
        'prelim_pricing_seen',
        'winner_announced',
        'contract_signed',
        'closed_timeout_consulting',
        'closed_stale_no_tor',
        'closed_manual',
        'error'
    )),

    CONSTRAINT projects_closed_reason_check CHECK (closed_reason IS NULL OR closed_reason IN (
        'winner_announced',
        'contract_signed',
        'consulting_timeout_30d',
        'prelim_pricing',
        'stale_no_tor',
        'manual',
        'merged_duplicate'
    ))
);

CREATE INDEX idx_projects_tenant ON projects(tenant_id);
CREATE INDEX idx_projects_state ON projects(tenant_id, project_state);
CREATE INDEX idx_projects_number ON projects(project_number) WHERE project_number IS NOT NULL;
CREATE INDEX idx_projects_last_seen ON projects(tenant_id, last_seen_at);

-- ==========================================================================
-- Project Aliases — multi-key dedup
-- ==========================================================================

CREATE TABLE project_aliases (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    alias_type      TEXT NOT NULL,  -- search_name/detail_name/project_number/fingerprint
    alias_value     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, alias_type, alias_value),
    CONSTRAINT aliases_type_check CHECK (alias_type IN (
        'search_name', 'detail_name', 'project_number', 'fingerprint'
    ))
);

CREATE INDEX idx_aliases_value ON project_aliases(alias_value);
CREATE INDEX idx_aliases_project ON project_aliases(project_id);

-- ==========================================================================
-- Project Status Events — status change history
-- ==========================================================================

CREATE TABLE project_status_events (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id              UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    observed_status_text    TEXT NOT NULL,
    normalized_status       TEXT,
    observed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id                  UUID,
    raw_snapshot            JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_status_events_project ON project_status_events(project_id, observed_at);

-- ==========================================================================
-- Documents — versioned artifacts with SHA-256
-- ==========================================================================

CREATE TABLE documents (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id              UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Classification
    document_type           TEXT NOT NULL,       -- invitation/mid_price/tor/other
    document_phase          TEXT NOT NULL,        -- public_hearing/final/unknown

    -- Source metadata
    source_label            TEXT,
    source_url              TEXT,
    source_status_text      TEXT,
    published_at            DATE,

    -- File metadata
    file_name               TEXT NOT NULL,
    mime_type               TEXT,
    size_bytes              BIGINT,

    -- Content identity
    sha256                  TEXT NOT NULL,
    storage_key             TEXT NOT NULL,        -- object storage key

    -- Version tracking
    is_current              BOOLEAN NOT NULL DEFAULT TRUE,
    supersedes_document_id  UUID REFERENCES documents(id),

    -- Text extraction
    extracted_text_key      TEXT,                 -- object storage key for extracted text

    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT documents_type_check CHECK (document_type IN (
        'invitation', 'mid_price', 'tor', 'other'
    )),
    CONSTRAINT documents_phase_check CHECK (document_phase IN (
        'public_hearing', 'final', 'unknown'
    ))
);

-- Prevent storing exact duplicate content for same project/class/phase
CREATE UNIQUE INDEX documents_project_hash_class_phase_uq
ON documents(project_id, sha256, document_type, document_phase);

CREATE INDEX idx_documents_project ON documents(project_id, is_current);
CREATE INDEX idx_documents_type ON documents(project_id, document_type, document_phase);

-- ==========================================================================
-- Document Diffs — change tracking between versions
-- ==========================================================================

CREATE TABLE document_diffs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    old_document_id     UUID NOT NULL REFERENCES documents(id),
    new_document_id     UUID NOT NULL REFERENCES documents(id),
    diff_type           TEXT NOT NULL,  -- identical/changed
    summary_json        JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT diffs_type_check CHECK (diff_type IN ('identical', 'changed'))
);

CREATE INDEX idx_diffs_project ON document_diffs(project_id);

-- ==========================================================================
-- Crawl Runs & Tasks
-- ==========================================================================

CREATE TABLE crawl_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    profile_id      UUID REFERENCES crawl_profiles(id),
    trigger_type    TEXT NOT NULL,  -- schedule/manual/retry/backfill
    status          TEXT NOT NULL DEFAULT 'queued',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    summary_json    JSONB,
    error_count     INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT runs_trigger_check CHECK (trigger_type IN (
        'schedule', 'manual', 'retry', 'backfill'
    )),
    CONSTRAINT runs_status_check CHECK (status IN (
        'queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled'
    ))
);

CREATE INDEX idx_runs_tenant ON crawl_runs(tenant_id, created_at DESC);

CREATE TABLE crawl_tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
    task_type       TEXT NOT NULL,  -- discover/update/close-check/download
    project_id      UUID REFERENCES projects(id),
    keyword         TEXT,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempts        INT NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    payload         JSONB,
    result_json     JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tasks_type_check CHECK (task_type IN (
        'discover', 'update', 'close_check', 'download'
    )),
    CONSTRAINT tasks_status_check CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'skipped'
    ))
);

CREATE INDEX idx_tasks_run ON crawl_tasks(run_id);
CREATE INDEX idx_tasks_project ON crawl_tasks(project_id) WHERE project_id IS NOT NULL;

-- ==========================================================================
-- Notifications
-- ==========================================================================

CREATE TABLE notifications (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id          UUID REFERENCES projects(id),
    notification_type   TEXT NOT NULL,  -- winner/closed/tor_changed/run_failed/new_project/export_ready
    channel             TEXT NOT NULL,  -- email/webhook/in_app/line
    status              TEXT NOT NULL DEFAULT 'pending',
    payload             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at             TIMESTAMPTZ,
    CONSTRAINT notif_status_check CHECK (status IN ('pending', 'sent', 'failed', 'read'))
);

CREATE INDEX idx_notifications_tenant ON notifications(tenant_id, created_at DESC);
CREATE INDEX idx_notifications_unread ON notifications(tenant_id, status) WHERE status = 'pending';

-- ==========================================================================
-- Exports
-- ==========================================================================

CREATE TABLE exports (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    requested_by    UUID REFERENCES users(id),
    export_type     TEXT NOT NULL,  -- xlsx/csv/pdf
    status          TEXT NOT NULL DEFAULT 'pending',
    storage_key     TEXT,           -- object storage key for generated file
    params_json     JSONB,          -- filters/options used
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    CONSTRAINT exports_type_check CHECK (export_type IN ('xlsx', 'csv', 'pdf')),
    CONSTRAINT exports_status_check CHECK (status IN ('pending', 'processing', 'completed', 'failed'))
);

CREATE INDEX idx_exports_tenant ON exports(tenant_id, created_at DESC);

-- ==========================================================================
-- Updated-at triggers
-- ==========================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_tenants_updated_at BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_profiles_updated_at BEFORE UPDATE ON crawl_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
