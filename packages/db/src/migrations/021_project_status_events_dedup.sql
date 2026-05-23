-- Migration 021: Deduplicate project status events for concurrent upserts
-- Date: 2026-05-24

WITH ranked_status_events AS (
    SELECT
        ctid,
        ROW_NUMBER() OVER (
            PARTITION BY project_id, normalized_status, observed_at
            ORDER BY created_at, id
        ) AS duplicate_rank
    FROM project_status_events
)
DELETE FROM project_status_events AS event
USING ranked_status_events AS ranked
WHERE event.ctid = ranked.ctid
  AND ranked.duplicate_rank > 1;

ALTER TABLE project_status_events
    ADD CONSTRAINT project_status_events_project_status_observed_uq
    UNIQUE (project_id, normalized_status, observed_at);
