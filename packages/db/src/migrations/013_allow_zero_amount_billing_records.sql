-- Migration 013: allow zero-amount billing records for free trials
-- Date: 2026-04-06

ALTER TABLE billing_records
    DROP CONSTRAINT IF EXISTS billing_records_amount_due_check;

ALTER TABLE billing_records
    ADD CONSTRAINT billing_records_amount_due_check CHECK (amount_due >= 0);
