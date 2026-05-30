-- Migration 024: Allow 'promptpay_manual' as a payment provider value.
--
-- Extends the CHECK constraints (migrations 014/023) so the
-- PromptpayManualProvider can persist payment requests + the admin-verified
-- settle event. This is the ฿0-fee personal-PromptPay bootstrap path used
-- before the operator can onboard a registered acquirer.
-- Additive only — existing 'mock_promptpay', 'opn', 'stripe' rows are unaffected.

ALTER TABLE billing_payment_requests
    DROP CONSTRAINT IF EXISTS billing_payment_requests_provider_check;

ALTER TABLE billing_payment_requests
    ADD CONSTRAINT billing_payment_requests_provider_check CHECK (
        provider IN ('mock_promptpay', 'promptpay_manual', 'opn', 'stripe')
    );

ALTER TABLE billing_provider_events
    DROP CONSTRAINT IF EXISTS billing_provider_events_provider_check;

ALTER TABLE billing_provider_events
    ADD CONSTRAINT billing_provider_events_provider_check CHECK (
        provider IN ('mock_promptpay', 'promptpay_manual', 'opn', 'stripe')
    );
