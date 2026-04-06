-- Migration 011: Account lifecycle auth hardening
-- Date: 2026-04-06

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS mfa_secret TEXT;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS account_action_tokens (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose         TEXT NOT NULL,
    delivery_email  TEXT,
    token_hash      TEXT NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT account_action_tokens_purpose_check
        CHECK (purpose IN ('invite', 'password_reset', 'email_verification'))
);

CREATE INDEX IF NOT EXISTS idx_account_action_tokens_user_purpose
    ON account_action_tokens(tenant_id, user_id, purpose, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_account_action_tokens_token_hash
    ON account_action_tokens(token_hash);

CREATE INDEX IF NOT EXISTS idx_account_action_tokens_active
    ON account_action_tokens(user_id, purpose, expires_at)
    WHERE consumed_at IS NULL;
