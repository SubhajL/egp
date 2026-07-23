-- Migration 032: Renewable discovery-job leases and typed failures
-- Date: 2026-07-23

ALTER TABLE discovery_jobs
    ADD COLUMN claim_token UUID,
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN lease_heartbeat_at TIMESTAMPTZ,
    ADD COLUMN last_error_code TEXT,
    ADD CONSTRAINT discovery_jobs_last_error_code_check CHECK (
        last_error_code IS NULL OR last_error_code IN (
            'keyword_no_results',
            'no_eligible_rows',
            'project_detail_invalid',
            'project_detail_missing_required_fields',
            'live_discovery_partial',
            'search_page_state_error',
            'worker_reported_failure',
            'worker_result_invalid',
            'worker_result_missing',
            'worker_exit_nonzero',
            'worker_timeout',
            'worker_terminated',
            'entitlement_denied',
            'dispatch_exception',
            'lease_lost'
        )
    );

-- An old-version executor may already own a pending row when this migration
-- lands. Preserve that ownership for the remainder of its existing 3-hour
-- subprocess timeout. Rows whose legacy window already elapsed remain
-- immediately reclaimable by the new lease-aware executor.
UPDATE discovery_jobs
SET claim_token = '00000000-0000-0000-0000-000000000000',
    lease_expires_at = processing_started_at + INTERVAL '3 hours',
    lease_heartbeat_at = processing_started_at
WHERE job_status = 'pending'
  AND processing_started_at IS NOT NULL;

CREATE INDEX idx_discovery_jobs_pending_lease
    ON discovery_jobs(job_status, next_attempt_at, lease_expires_at)
    WHERE job_status = 'pending';
