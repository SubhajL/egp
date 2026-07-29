-- Migration 036: Shadow delivery mode and parity verdicts for the agent inbox
-- Date: 2026-07-29
--
-- U8 shadow parity: the Mac crawler, while executing an ordinary LEGACY discovery
-- job, additionally reports the agent result envelope it *would* have sent. That
-- envelope is recorded and COMPARED against what the legacy path durably wrote for
-- the same run — it is never applied. One crawl, two reports, zero extra load on
-- e-GP.
--
-- `delivery_mode` is stamped at ACCEPTANCE time, not read at processing time.
-- Otherwise flipping `EGP_CRAWLER_AGENT_PROTOCOL` between acceptance and drain
-- would turn a shadow report into a real write — which is precisely the accident
-- this column exists to make impossible.
--
-- The default is 'primary' so every row already in the table keeps its existing
-- meaning: those were accepted by the U7b contract, which only ever applied.

ALTER TABLE crawler_agent_results
    ADD COLUMN delivery_mode TEXT NOT NULL DEFAULT 'primary';

ALTER TABLE crawler_agent_results
    ADD CONSTRAINT crawler_agent_results_delivery_mode_check
    CHECK (delivery_mode IN ('primary', 'shadow'));

-- Verdict of a shadow comparison. NULL for primary rows and for shadow rows that
-- have not been compared yet.
ALTER TABLE crawler_agent_results
    ADD COLUMN parity_verdict TEXT;

ALTER TABLE crawler_agent_results
    ADD CONSTRAINT crawler_agent_results_parity_verdict_check
    CHECK (
        parity_verdict IS NULL
        OR parity_verdict IN ('match', 'mismatch', 'unavailable')
    );

-- A primary row can never carry a parity verdict: primary applies, it does not
-- compare. Enforced rather than merely documented, because the processor branches
-- on delivery_mode and a row with both would mean the branch had gone wrong.
ALTER TABLE crawler_agent_results
    ADD CONSTRAINT crawler_agent_results_primary_has_no_verdict_check
    CHECK (delivery_mode = 'shadow' OR parity_verdict IS NULL);

-- COUNTS ONLY. Deliberately not the differing project names or numbers: this is
-- operator triage data, and an envelope diff would put tenant procurement detail
-- into a column that operator tooling reads across tenants.
ALTER TABLE crawler_agent_results
    ADD COLUMN parity_detail JSONB;

-- Operator triage: "show me the mismatches". Partial, because match is the
-- expected case and the table is dominated by primary rows.
CREATE INDEX idx_crawler_agent_results_parity_mismatch
    ON crawler_agent_results(received_at DESC)
    WHERE parity_verdict = 'mismatch';
