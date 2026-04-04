-- Migration 004: Add invoice lifecycle events and subscription activation state
-- Date: 2026-04-05

ALTER TABLE billing_events DROP CONSTRAINT IF EXISTS billing_events_type_check;

ALTER TABLE billing_events
    ADD CONSTRAINT billing_events_type_check CHECK (
        event_type IN (
            'billing_record_created',
            'billing_record_status_changed',
            'payment_recorded',
            'payment_reconciled',
            'payment_rejected',
            'subscription_activated'
        )
    );

CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    billing_record_id       UUID NOT NULL UNIQUE REFERENCES billing_records(id) ON DELETE CASCADE,
    plan_code               TEXT NOT NULL,
    status                  TEXT NOT NULL,
    billing_period_start    DATE NOT NULL,
    billing_period_end      DATE NOT NULL,
    keyword_limit           INT,
    activated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_by_payment_id UUID REFERENCES billing_payments(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT billing_subscriptions_status_check CHECK (
        status IN ('pending_activation', 'active', 'expired', 'cancelled')
    ),
    CONSTRAINT billing_subscriptions_period_order_check CHECK (
        billing_period_end >= billing_period_start
    )
);

CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_tenant_status
    ON billing_subscriptions(tenant_id, status, billing_period_end DESC);

CREATE INDEX IF NOT EXISTS idx_billing_subscriptions_record
    ON billing_subscriptions(billing_record_id);

DROP TRIGGER IF EXISTS update_billing_subscriptions_updated_at ON billing_subscriptions;
CREATE TRIGGER update_billing_subscriptions_updated_at BEFORE UPDATE ON billing_subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
