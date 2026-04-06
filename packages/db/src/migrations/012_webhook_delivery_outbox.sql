-- Migration 012: Webhook delivery outbox scheduling
-- Date: 2026-04-06

ALTER TABLE webhook_deliveries
    ADD COLUMN next_attempt_at TIMESTAMPTZ,
    ADD COLUMN processing_started_at TIMESTAMPTZ;

UPDATE webhook_deliveries
SET next_attempt_at = COALESCE(next_attempt_at, created_at)
WHERE next_attempt_at IS NULL;

CREATE INDEX idx_webhook_deliveries_pending_due
    ON webhook_deliveries(delivery_status, next_attempt_at, processing_started_at)
    WHERE delivered_at IS NULL;
