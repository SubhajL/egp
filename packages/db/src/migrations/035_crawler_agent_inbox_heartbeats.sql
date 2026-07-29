-- Migration 035: Crawler-agent inbox processor liveness
-- Date: 2026-07-28
--
-- The `crawler-agent-inbox-executor` compose service has no HTTP server and its
-- healthcheck is disabled, so its own comment records the gap this table closes:
-- "A running PID is not proof the processor can drain."
--
-- Backlog depth alone cannot close it. With an empty queue a dead processor and a
-- healthy idle one are indistinguishable, so liveness has to be reported by the
-- processor itself, on EVERY drain iteration including the ones that claim nothing.
--
-- Like `crawler_runtime_heartbeats` (033), this is GLOBAL operational state and
-- deliberately carries no tenant, customer, credential, URL, path, or free-form
-- error payload. `last_outcome` is a bounded vocabulary precisely because an
-- exception message is where tenant data would otherwise leak into global state.

CREATE TABLE crawler_agent_inbox_heartbeats (
    processor_id    TEXT PRIMARY KEY,
    status          TEXT NOT NULL CHECK (status IN ('running', 'stopping', 'error')),
    backlog_depth   INTEGER NOT NULL DEFAULT 0 CHECK (backlog_depth >= 0),
    last_outcome    TEXT NOT NULL CHECK (
        last_outcome IN (
            'idle',
            'applied',
            'retried',
            'rejected',
            'reclaimed',
            'lease_lost',
            'error'
        )
    ),
    reported_at     TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL
);

-- Health reads take the FRESHEST heartbeat across processors: with several
-- replicas, a stale row left behind by a scaled-down replica must not make the
-- fleet look wedged forever.
CREATE INDEX idx_crawler_agent_inbox_heartbeats_reported_at
    ON crawler_agent_inbox_heartbeats(reported_at DESC);

-- No index is added to `crawler_agent_results` here. The stranded-processing
-- probe is already served by `idx_crawler_agent_results_processing_lease` (034),
-- which has the identical definition. Adding a duplicate would also make this
-- migration depend on a table 034 creates, and the 034 upgrade-path test stages
-- every migration EXCEPT 034 — so the duplicate broke that test before it could
-- ever have paid for itself.
