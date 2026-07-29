-- Migration 037: Per-profile execution backend (the canary control)
-- Date: 2026-07-29
--
-- Until now nothing created `execution_backend='agent'` discovery jobs, so the V1
-- agent endpoints claimed nothing even when the protocol was enabled. This is the
-- switch that changes that, at the granularity the rollout needs: ONE profile.
--
-- Default 'legacy' so every existing profile keeps producing exactly the jobs it
-- produces today. Adding the column changes no behaviour; flipping one row does.
--
-- IMPORTANT — a flip is not self-reversing. `discovery_jobs.execution_backend` is
-- stamped per job at insert and is immutable thereafter, and the in-flight dedupe
-- is backend-agnostic. So setting a profile back to 'legacy' does NOT rescue jobs
-- already queued as 'agent': they stay agent-owned, and their presence BLOCKS
-- creation of replacement legacy jobs for the same keyword. Rolling back requires
-- explicitly rerouting those queued rows — see
-- `scripts/set_profile_execution_backend.py --reroute-pending`.

ALTER TABLE crawl_profiles
    ADD COLUMN execution_backend TEXT NOT NULL DEFAULT 'legacy';

ALTER TABLE crawl_profiles
    ADD CONSTRAINT crawl_profiles_execution_backend_check
    CHECK (execution_backend IN ('legacy', 'agent'));

-- Partial: 'legacy' is the overwhelming default, so only the canary rows are worth
-- indexing. Answers "which profiles are routed away from the legacy crawler?".
CREATE INDEX idx_crawl_profiles_execution_backend
    ON crawl_profiles(tenant_id, execution_backend)
    WHERE execution_backend <> 'legacy';
