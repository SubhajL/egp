-- Migration 007: Tenant admin settings
-- Date: 2026-04-05

CREATE TABLE tenant_settings (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    support_email           TEXT,
    billing_contact_email   TEXT,
    timezone                TEXT NOT NULL DEFAULT 'Asia/Bangkok',
    locale                  TEXT NOT NULL DEFAULT 'th-TH',
    daily_digest_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    weekly_digest_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT tenant_settings_tenant_uq UNIQUE (tenant_id)
);

CREATE INDEX idx_tenant_settings_tenant ON tenant_settings(tenant_id);
