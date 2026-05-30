-- Migration 026: add the intermediate 'verifying' state to payment_slips.
-- Date: 2026-05-30
--
-- Slip verification claims the row (matched -> verifying) BEFORE settling the
-- billing record, and only marks 'verified' AFTER settlement succeeds. This
-- means a crash mid-settlement leaves a recoverable 'verifying' row (recovered
-- via a stale lease) rather than a stranded 'verified'-but-unpaid slip.
-- Additive only.

ALTER TABLE payment_slips
    DROP CONSTRAINT IF EXISTS payment_slips_verification_status_check;

ALTER TABLE payment_slips
    ADD CONSTRAINT payment_slips_verification_status_check CHECK (
        verification_status IN ('pending', 'matched', 'verifying', 'verified', 'rejected')
    );
