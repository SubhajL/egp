-- Migration 040: exact-ingestion canary failure vocabulary
-- Date: 2026-08-24
--
-- The typed failure vocabulary is append-only in shared Python code. Recreate
-- the discovery-job constraint so persisted failures can use the new values.
-- No discovery-job data is rewritten by this migration.

ALTER TABLE discovery_jobs
    DROP CONSTRAINT discovery_jobs_last_error_code_check;

ALTER TABLE discovery_jobs
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
            'lease_lost',
            'browser_start_failed',
            'pagination_control_hidden',
            'pagination_next_click_failed',
            'pagination_page_change_timeout',
            'pagination_unexpected_no_results',
            'pagination_site_error',
            'canary_target_mismatch',
            'canary_proof_invalid'
        )
    );
