-- Migration 039: Candidate-attempt integrity (PR-CANARY-03 F6 + identity)
-- Date: 2026-08-09
--
-- Closes consolidated-review finding HIGH 6 (2026-08-06 07:48:44): migration
-- 038 shipped the candidate ledger without parent/tenant referential
-- integrity, with free-text terminal reasons, and without status-shape
-- constraints. This migration:
--
--   1. adds content-provenance and diagnostics columns
--      (project_number / row_marker / terminal_detail);
--   2-4. repairs any 038-era rows so the new constraints can be added —
--      EVERY displaced reason/project value is PRESERVED into terminal_detail
--      via CONCAT_WS (never silently dropped); rows whose run reference
--      cannot be satisfied tenant-matched are deleted (record the DELETE
--      count when applying in production — see the PR runbook);
--   5. adds the composite parent keys UNIQUE (tenant_id, id) on crawl_runs
--      and projects (same pattern as 034's discovery_jobs_tenant_id_id_key);
--   6. adds the composite tenant foreign keys (with a supporting index for
--      the project FK), the typed terminal_reason vocabulary CHECK, and the
--      status/reason/project shape CHECK.
--
-- The terminal_reason vocabulary below MUST stay identical to
-- egp_shared_types.enums.CandidateTerminalReason — a drift test compares the
-- latest vocabulary-defining migration's CHECK list to the enum and requires
-- every historical list to stay a subset.
--
-- These statements run exactly once (the migration runner records this
-- filename in schema_migrations); they are not individually re-runnable.

-- 1. New columns -----------------------------------------------------------

ALTER TABLE discovery_candidate_attempts ADD COLUMN project_number TEXT;
ALTER TABLE discovery_candidate_attempts ADD COLUMN row_marker TEXT;
ALTER TABLE discovery_candidate_attempts ADD COLUMN terminal_detail TEXT;

-- 2. Normalize non-vocabulary reasons, preserving the original text ---------
-- (terminal_detail is all-NULL here: the column was created in step 1.)

UPDATE discovery_candidate_attempts
SET terminal_detail = terminal_reason,
    terminal_reason = 'unclassified'
WHERE terminal_reason IS NOT NULL
  AND terminal_reason NOT IN (
    'worker_lost', 'lease_lost', 'worker_timeout', 'worker_terminated',
    'cancelled', 'persist_error', 'duplicate_in_run', 'late_stage',
    'unclassified', 'navigation_failure', 'results_page_returned',
    'project_detail_missing_required_fields', 'rejection_page',
    'placeholder_detail', 'out_of_scope_stage', 'detail_unknown'
  );

-- 3. Referential repair (pre-integrity rows) --------------------------------

DELETE FROM discovery_candidate_attempts a
WHERE NOT EXISTS (
    SELECT 1 FROM crawl_runs r
    WHERE r.id = a.run_id AND r.tenant_id = a.tenant_id
);

UPDATE discovery_candidate_attempts a
SET terminal_detail = CONCAT_WS(
        '; ',
        a.terminal_detail,
        'migration_039_orphan_project',
        'displaced_reason=' || a.terminal_reason,
        'displaced_project_id=' || a.project_id::text
    ),
    project_id = NULL,
    candidate_status = 'unknown',
    terminal_reason = 'unclassified'
WHERE a.project_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM projects p
    WHERE p.id = a.project_id AND p.tenant_id = a.tenant_id
  );

-- 4. Shape repair (always preserve displaced evidence) ----------------------
-- CONCAT_WS skips NULL arguments, so pre-existing detail text and absent
-- displaced values compose without clobbering each other.

UPDATE discovery_candidate_attempts
SET terminal_reason = 'unclassified',
    terminal_detail = CONCAT_WS(
        '; ', terminal_detail, 'migration_039_missing_reason')
WHERE candidate_status IN ('dropped', 'failed', 'unknown')
  AND terminal_reason IS NULL;

UPDATE discovery_candidate_attempts
SET candidate_status = 'unknown',
    terminal_detail = CONCAT_WS(
        '; ',
        terminal_detail,
        'migration_039_persisted_without_project',
        'displaced_reason=' || terminal_reason
    ),
    terminal_reason = 'unclassified',
    project_id = NULL
WHERE candidate_status = 'persisted'
  AND project_id IS NULL;

UPDATE discovery_candidate_attempts
SET terminal_detail = CONCAT_WS(
        '; ', terminal_detail, 'migration_039_displaced_reason=' || terminal_reason),
    terminal_reason = NULL
WHERE candidate_status IN ('accepted', 'persisted')
  AND terminal_reason IS NOT NULL;

UPDATE discovery_candidate_attempts
SET terminal_detail = CONCAT_WS(
        '; ', terminal_detail,
        'migration_039_displaced_project_id=' || project_id::text),
    project_id = NULL
WHERE candidate_status IN ('accepted', 'dropped', 'failed', 'unknown')
  AND project_id IS NOT NULL;

-- 5. Composite parent keys --------------------------------------------------

ALTER TABLE crawl_runs
    ADD CONSTRAINT crawl_runs_tenant_id_id_key UNIQUE (tenant_id, id);
ALTER TABLE projects
    ADD CONSTRAINT projects_tenant_id_id_key UNIQUE (tenant_id, id);

-- 6. Composite tenant FKs + typed vocabulary + shape CHECKs -----------------
--
-- Run FK cascades (matches crawl_tasks.run_id and 034's composite FK: a
-- deleted run takes its accounting rows). Project FK is deliberately
-- NO ACTION: nothing deletes projects today, and ON DELETE SET NULL would
-- violate dca_status_shape_check for persisted rows.

ALTER TABLE discovery_candidate_attempts
    ADD CONSTRAINT dca_tenant_run_fkey
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES crawl_runs (tenant_id, id) ON DELETE CASCADE,
    ADD CONSTRAINT dca_tenant_project_fkey
        FOREIGN KEY (tenant_id, project_id)
        REFERENCES projects (tenant_id, id),
    ADD CONSTRAINT dca_terminal_reason_vocab_check CHECK (
        terminal_reason IS NULL OR terminal_reason IN (
            'worker_lost', 'lease_lost', 'worker_timeout', 'worker_terminated',
            'cancelled', 'persist_error', 'duplicate_in_run', 'late_stage',
            'unclassified', 'navigation_failure', 'results_page_returned',
            'project_detail_missing_required_fields', 'rejection_page',
            'placeholder_detail', 'out_of_scope_stage', 'detail_unknown'
        )
    ),
    ADD CONSTRAINT dca_status_shape_check CHECK (
        (candidate_status = 'accepted'
            AND terminal_reason IS NULL AND project_id IS NULL)
        OR (candidate_status = 'persisted'
            AND terminal_reason IS NULL AND project_id IS NOT NULL)
        OR (candidate_status IN ('dropped', 'failed', 'unknown')
            AND terminal_reason IS NOT NULL AND project_id IS NULL)
    );

-- Supporting index for the referencing side of dca_tenant_project_fkey
-- (repo convention: always index foreign keys; partial — most rows have a
-- NULL project_id).
CREATE INDEX idx_dca_tenant_project
    ON discovery_candidate_attempts (tenant_id, project_id)
    WHERE project_id IS NOT NULL;
