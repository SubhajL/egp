-- e-GP Intelligence Platform — Notification Preferences
-- Migration 002: Per-user notification channel preferences
-- Date: 2026-04-04

CREATE TABLE notification_preferences (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_type   TEXT NOT NULL,
    channel             TEXT NOT NULL,
    is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, user_id, notification_type, channel),
    CONSTRAINT notification_prefs_type_check CHECK (notification_type IN (
        'new_project', 'winner_announced', 'contract_signed', 'tor_changed', 'run_failed', 'export_ready'
    )),
    CONSTRAINT notification_prefs_channel_check CHECK (channel IN ('email', 'in_app', 'webhook', 'line'))
);

CREATE INDEX idx_notification_prefs_tenant_user
    ON notification_preferences(tenant_id, user_id, notification_type, channel);

CREATE TRIGGER update_notification_preferences_updated_at
BEFORE UPDATE ON notification_preferences
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
