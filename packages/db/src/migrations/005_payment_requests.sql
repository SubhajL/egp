-- Migration 005: Add provider-backed payment requests and callback event log
-- Date: 2026-04-05

ALTER TABLE billing_payments DROP CONSTRAINT IF EXISTS billing_payments_method_check;

ALTER TABLE billing_payments
    ADD CONSTRAINT billing_payments_method_check CHECK (
        payment_method IN ('bank_transfer', 'promptpay_qr', 'card')
    );

ALTER TABLE billing_events DROP CONSTRAINT IF EXISTS billing_events_type_check;

ALTER TABLE billing_events
    ADD CONSTRAINT billing_events_type_check CHECK (
        event_type IN (
            'billing_record_created',
            'billing_record_status_changed',
            'payment_request_created',
            'payment_request_settled',
            'payment_recorded',
            'payment_reconciled',
            'payment_rejected',
            'subscription_activated'
        )
    );

CREATE TABLE IF NOT EXISTS billing_payment_requests (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    billing_record_id   UUID NOT NULL REFERENCES billing_records(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
    payment_method      TEXT NOT NULL,
    status              TEXT NOT NULL,
    provider_reference  TEXT NOT NULL,
    payment_url         TEXT NOT NULL,
    qr_payload          TEXT NOT NULL,
    qr_svg              TEXT NOT NULL,
    amount              NUMERIC(18,2) NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'THB',
    expires_at          TIMESTAMPTZ,
    settled_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT billing_payment_requests_provider_check CHECK (
        provider IN ('mock_promptpay', 'opn')
    ),
    CONSTRAINT billing_payment_requests_method_check CHECK (
        payment_method IN ('bank_transfer', 'promptpay_qr', 'card')
    ),
    CONSTRAINT billing_payment_requests_status_check CHECK (
        status IN ('pending', 'settled', 'expired', 'failed', 'cancelled')
    ),
    CONSTRAINT billing_payment_requests_amount_check CHECK (amount > 0),
    CONSTRAINT billing_payment_requests_provider_reference_unique UNIQUE (provider, provider_reference)
);

CREATE TABLE IF NOT EXISTS billing_provider_events (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    payment_request_id  UUID NOT NULL REFERENCES billing_payment_requests(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
    provider_event_id   TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT billing_provider_events_provider_check CHECK (
        provider IN ('mock_promptpay', 'opn')
    ),
    CONSTRAINT billing_provider_events_provider_event_unique UNIQUE (provider, provider_event_id)
);

CREATE INDEX IF NOT EXISTS idx_billing_payment_requests_tenant_created
    ON billing_payment_requests(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_payment_requests_record
    ON billing_payment_requests(billing_record_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_provider_events_request_created
    ON billing_provider_events(payment_request_id, created_at ASC);

DROP TRIGGER IF EXISTS update_billing_payment_requests_updated_at ON billing_payment_requests;
CREATE TRIGGER update_billing_payment_requests_updated_at BEFORE UPDATE ON billing_payment_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
