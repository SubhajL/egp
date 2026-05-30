-- Migration 025: LINE-mediated manual PromptPay slip verification.
-- Date: 2026-05-29
--
-- Backs the ฿0-fee bootstrap flow where a customer pays a personal PromptPay
-- QR and forwards the slip image via LINE OA for a human to verify. Additive
-- only — no existing tables are altered.
--
-- payment_slips.tenant_id is intentionally NULLable: a slip can arrive before
-- it is matched to a tenant (operator inbox). It is populated when the slip is
-- matched to a billing record; tenant-scoped admin listings filter on it once set.

CREATE TABLE IF NOT EXISTS payment_slips (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id             UUID REFERENCES tenants(id) ON DELETE CASCADE,
    billing_record_id     UUID REFERENCES billing_records(id) ON DELETE SET NULL,
    payment_request_id    UUID REFERENCES billing_payment_requests(id) ON DELETE SET NULL,
    line_user_id          TEXT NOT NULL,
    line_message_id       TEXT NOT NULL UNIQUE,
    reference_code_match  TEXT,
    image_object_key      TEXT,
    image_content_type    TEXT,
    image_sha256          TEXT,
    verification_status   TEXT NOT NULL DEFAULT 'pending',
    -- Stores the verifying admin's subject id when it is a UUID; no FK to
    -- users(id) because the auth subject (e.g. a Supabase sub) is not
    -- guaranteed to be a row in users. Matches the SQLAlchemy schema.
    verified_by_user_id   UUID,
    verified_at           TIMESTAMPTZ,
    verification_notes    TEXT,
    received_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT payment_slips_verification_status_check CHECK (
        verification_status IN ('pending', 'matched', 'verified', 'rejected')
    )
);

CREATE TABLE IF NOT EXISTS line_payment_contexts (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    line_user_id        TEXT NOT NULL,
    reference_code      TEXT NOT NULL,
    tenant_id           UUID REFERENCES tenants(id) ON DELETE CASCADE,
    billing_record_id   UUID REFERENCES billing_records(id) ON DELETE SET NULL,
    plan_code           TEXT,
    source_message_id   TEXT NOT NULL UNIQUE,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS line_admin_subscribers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    line_user_id    TEXT NOT NULL UNIQUE,
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    display_name    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_slips_status_received
    ON payment_slips(verification_status, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_payment_slips_tenant_status
    ON payment_slips(tenant_id, verification_status);

CREATE INDEX IF NOT EXISTS idx_payment_slips_reference
    ON payment_slips(reference_code_match);

CREATE INDEX IF NOT EXISTS idx_line_payment_contexts_user_created
    ON line_payment_contexts(line_user_id, created_at DESC);

DROP TRIGGER IF EXISTS update_payment_slips_updated_at ON payment_slips;
CREATE TRIGGER update_payment_slips_updated_at BEFORE UPDATE ON payment_slips
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
