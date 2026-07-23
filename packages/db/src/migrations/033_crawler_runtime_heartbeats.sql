-- Migration 033: Sanitized crawler-agent runtime heartbeats
-- Date: 2026-07-23
--
-- This is global operational state. It deliberately contains no tenant,
-- customer, credential, URL, filesystem path, or free-form error payload.

CREATE TABLE crawler_runtime_heartbeats (
    agent_id TEXT PRIMARY KEY,
    runtime_mode TEXT NOT NULL CHECK (runtime_mode IN ('embedded', 'external')),
    watcher_status TEXT NOT NULL CHECK (
        watcher_status IN ('running', 'stopping', 'error')
    ),
    database_status TEXT NOT NULL CHECK (
        database_status IN ('connected', 'unreachable', 'unknown')
    ),
    blocker_code TEXT CHECK (
        blocker_code IS NULL OR blocker_code IN (
            'agent_offline',
            'database_unreachable',
            'correlation_mismatch',
            'circuit_open',
            'profile_busy',
            'profile_warm_retry',
            'profile_operator_action_required'
        )
    ),
    profile_status TEXT NOT NULL CHECK (
        profile_status IN (
            'ready',
            'busy',
            'warm_retry',
            'operator_action_required',
            'unknown'
        )
    ),
    circuit_state TEXT NOT NULL CHECK (
        circuit_state IN ('closed', 'open', 'half_open', 'unknown')
    ),
    circuit_reset_at TIMESTAMPTZ,
    reported_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_crawler_runtime_heartbeats_reported_at
    ON crawler_runtime_heartbeats(reported_at DESC);
