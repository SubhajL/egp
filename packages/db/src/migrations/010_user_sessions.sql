-- Migration 010: User passwords and session persistence
-- Date: 2026-04-05

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

CREATE TABLE IF NOT EXISTS user_sessions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token_hash  TEXT NOT NULL UNIQUE,
    expires_at          TIMESTAMPTZ NOT NULL,
    revoked_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_tenant_user
    ON user_sessions(tenant_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_sessions_token_hash
    ON user_sessions(session_token_hash);

CREATE INDEX IF NOT EXISTS idx_user_sessions_active
    ON user_sessions(user_id, expires_at)
    WHERE revoked_at IS NULL;
