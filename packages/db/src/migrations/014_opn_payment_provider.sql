-- Migration 014: Expand billing payment enums for Opn and cards
-- Date: 2026-04-06

ALTER TABLE billing_payments DROP CONSTRAINT IF EXISTS billing_payments_method_check;

ALTER TABLE billing_payments
    ADD CONSTRAINT billing_payments_method_check CHECK (
        payment_method IN ('bank_transfer', 'promptpay_qr', 'card')
    );

ALTER TABLE billing_payment_requests DROP CONSTRAINT IF EXISTS billing_payment_requests_provider_check;
ALTER TABLE billing_payment_requests DROP CONSTRAINT IF EXISTS billing_payment_requests_method_check;

ALTER TABLE billing_payment_requests
    ADD CONSTRAINT billing_payment_requests_provider_check CHECK (
        provider IN ('mock_promptpay', 'opn')
    );

ALTER TABLE billing_payment_requests
    ADD CONSTRAINT billing_payment_requests_method_check CHECK (
        payment_method IN ('bank_transfer', 'promptpay_qr', 'card')
    );

ALTER TABLE billing_provider_events DROP CONSTRAINT IF EXISTS billing_provider_events_provider_check;

ALTER TABLE billing_provider_events
    ADD CONSTRAINT billing_provider_events_provider_check CHECK (
        provider IN ('mock_promptpay', 'opn')
    );
