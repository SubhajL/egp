-- Migration 016: add persisted subscription upgrade intent
-- Date: 2026-04-08

ALTER TABLE billing_records
    ADD COLUMN IF NOT EXISTS upgrade_from_subscription_id UUID NULL REFERENCES billing_subscriptions(id) ON DELETE SET NULL;

ALTER TABLE billing_records
    ADD COLUMN IF NOT EXISTS upgrade_mode TEXT NOT NULL DEFAULT 'none';

ALTER TABLE billing_records
    DROP CONSTRAINT IF EXISTS billing_records_upgrade_mode_check;

ALTER TABLE billing_records
    ADD CONSTRAINT billing_records_upgrade_mode_check CHECK (
        upgrade_mode IN ('none', 'replace_now', 'replace_on_activation')
    );

CREATE INDEX IF NOT EXISTS idx_billing_records_upgrade_from_subscription
    ON billing_records (upgrade_from_subscription_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_records_open_upgrade_per_subscription
    ON billing_records (tenant_id, upgrade_from_subscription_id)
    WHERE upgrade_from_subscription_id IS NOT NULL
      AND status NOT IN ('paid', 'cancelled', 'refunded');
