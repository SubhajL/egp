-- Migration 003: Add manual billing records and bank-transfer reconciliation
-- Date: 2026-04-04

CREATE TABLE IF NOT EXISTS billing_records (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    record_number           TEXT NOT NULL,
    plan_code               TEXT NOT NULL,
    status                  TEXT NOT NULL,
    billing_period_start    DATE NOT NULL,
    billing_period_end      DATE NOT NULL,
    due_at                  TIMESTAMPTZ,
    issued_at               TIMESTAMPTZ,
    paid_at                 TIMESTAMPTZ,
    currency                TEXT NOT NULL DEFAULT 'THB',
    amount_due              NUMERIC(18,2) NOT NULL,
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, record_number),
    CONSTRAINT billing_records_status_check CHECK (
        status IN (
            'draft',
            'issued',
            'awaiting_payment',
            'payment_detected',
            'paid',
            'failed',
            'overdue',
            'cancelled',
            'refunded'
        )
    ),
    CONSTRAINT billing_records_amount_due_check CHECK (amount_due > 0),
    CONSTRAINT billing_records_period_order_check CHECK (billing_period_end >= billing_period_start)
);

CREATE TABLE IF NOT EXISTS billing_payments (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    billing_record_id       UUID NOT NULL REFERENCES billing_records(id) ON DELETE CASCADE,
    payment_method          TEXT NOT NULL,
    payment_status          TEXT NOT NULL,
    amount                  NUMERIC(18,2) NOT NULL,
    currency                TEXT NOT NULL DEFAULT 'THB',
    reference_code          TEXT,
    received_at             TIMESTAMPTZ NOT NULL,
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reconciled_at           TIMESTAMPTZ,
    note                    TEXT,
    recorded_by             TEXT,
    reconciled_by           TEXT,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT billing_payments_method_check CHECK (
        payment_method IN ('bank_transfer')
    ),
    CONSTRAINT billing_payments_status_check CHECK (
        payment_status IN ('pending_reconciliation', 'reconciled', 'rejected')
    ),
    CONSTRAINT billing_payments_amount_check CHECK (amount > 0)
);

CREATE TABLE IF NOT EXISTS billing_events (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    billing_record_id       UUID NOT NULL REFERENCES billing_records(id) ON DELETE CASCADE,
    payment_id              UUID REFERENCES billing_payments(id) ON DELETE SET NULL,
    event_type              TEXT NOT NULL,
    actor_subject           TEXT,
    note                    TEXT,
    from_status             TEXT,
    to_status               TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT billing_events_type_check CHECK (
        event_type IN (
            'billing_record_created',
            'payment_recorded',
            'payment_reconciled',
            'payment_rejected'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_billing_records_tenant_created
    ON billing_records(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_records_tenant_due_at
    ON billing_records(tenant_id, due_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_payments_tenant_recorded
    ON billing_payments(tenant_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_payments_record
    ON billing_payments(billing_record_id, payment_status, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_events_record_created
    ON billing_events(billing_record_id, created_at ASC);

DROP TRIGGER IF EXISTS update_billing_records_updated_at ON billing_records;
CREATE TRIGGER update_billing_records_updated_at BEFORE UPDATE ON billing_records
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_billing_payments_updated_at ON billing_payments;
CREATE TRIGGER update_billing_payments_updated_at BEFORE UPDATE ON billing_payments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
