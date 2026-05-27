-- Migration 023: Allow 'stripe' as a payment provider value.
--
-- Extends the CHECK constraints introduced by migration 014 so that the
-- StripeProvider (PR-F) can persist payment requests + callback events.
-- Additive only — existing 'mock_promptpay' and 'opn' rows are unaffected.

ALTER TABLE billing_payment_requests
    DROP CONSTRAINT IF EXISTS billing_payment_requests_provider_check;

ALTER TABLE billing_payment_requests
    ADD CONSTRAINT billing_payment_requests_provider_check CHECK (
        provider IN ('mock_promptpay', 'opn', 'stripe')
    );

ALTER TABLE billing_provider_events
    DROP CONSTRAINT IF EXISTS billing_provider_events_provider_check;

ALTER TABLE billing_provider_events
    ADD CONSTRAINT billing_provider_events_provider_check CHECK (
        provider IN ('mock_promptpay', 'opn', 'stripe')
    );
