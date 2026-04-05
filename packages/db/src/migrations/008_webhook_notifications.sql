-- Migration 008: Webhook notification delivery
-- Date: 2026-04-05

CREATE TABLE webhook_subscriptions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    url                 TEXT NOT NULL,
    signing_secret      TEXT NOT NULL,
    notification_types  JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT webhook_subscriptions_url_check CHECK (
        url LIKE 'http://%' OR url LIKE 'https://%'
    ),
    CONSTRAINT webhook_subscriptions_types_is_array CHECK (
        jsonb_typeof(notification_types) = 'array'
    )
);

CREATE INDEX idx_webhook_subscriptions_tenant
    ON webhook_subscriptions(tenant_id, is_active, created_at DESC);

CREATE TABLE webhook_deliveries (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id                   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    webhook_subscription_id     UUID NOT NULL REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    notification_id             UUID NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
    event_id                    TEXT NOT NULL,
    notification_type           TEXT NOT NULL,
    project_id                  UUID,
    payload                     JSONB NOT NULL,
    attempt_count               INTEGER NOT NULL DEFAULT 0,
    delivery_status             TEXT NOT NULL DEFAULT 'pending',
    last_response_status_code   INTEGER,
    last_response_body          TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_attempted_at           TIMESTAMPTZ,
    delivered_at                TIMESTAMPTZ,
    CONSTRAINT webhook_deliveries_status_check CHECK (
        delivery_status IN ('pending', 'delivered', 'failed')
    ),
    CONSTRAINT webhook_deliveries_subscription_event_uq UNIQUE (
        webhook_subscription_id,
        event_id
    )
);

CREATE INDEX idx_webhook_deliveries_tenant
    ON webhook_deliveries(tenant_id, updated_at DESC);

CREATE INDEX idx_webhook_deliveries_subscription
    ON webhook_deliveries(webhook_subscription_id, updated_at DESC);

CREATE TRIGGER update_webhook_subscriptions_updated_at
BEFORE UPDATE ON webhook_subscriptions
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_webhook_deliveries_updated_at
BEFORE UPDATE ON webhook_deliveries
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();
