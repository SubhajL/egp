-- Migration 028: Separate saved keyword-group intent from effective entitlement.
--
-- `enabled_by_user` is durable customer intent.  `is_active` remains a
-- compatibility mirror for one rollout window; application code writes both.

ALTER TABLE crawl_profiles
    ADD COLUMN IF NOT EXISTS enabled_by_user BOOLEAN;

UPDATE crawl_profiles AS profile
SET enabled_by_user = (
    profile.is_active
    OR EXISTS (
        SELECT 1
        FROM crawl_profile_keywords AS keyword
        WHERE keyword.profile_id = profile.id
    )
)
WHERE profile.enabled_by_user IS NULL;

ALTER TABLE crawl_profiles
    ALTER COLUMN enabled_by_user SET DEFAULT TRUE,
    ALTER COLUMN enabled_by_user SET NOT NULL;

-- The compatibility flag starts synchronized with restored user intent.  No
-- keyword membership is deleted or rewritten by this migration.
UPDATE crawl_profiles
SET is_active = enabled_by_user
WHERE is_active IS DISTINCT FROM enabled_by_user;

-- Normalize names and deterministically suffix collisions per tenant.  The
-- ordering preserves the oldest row's base name and handles pre-existing
-- suffixes by checking every candidate against names already assigned.
DO $$
DECLARE
    tenant_row RECORD;
    profile_row RECORD;
    base_name TEXT;
    candidate_name TEXT;
    suffix_number INTEGER;
    used_names TEXT[];
BEGIN
    FOR tenant_row IN
        SELECT DISTINCT tenant_id
        FROM crawl_profiles
        ORDER BY tenant_id
    LOOP
        used_names := ARRAY[]::TEXT[];
        FOR profile_row IN
            SELECT id, name
            FROM crawl_profiles
            WHERE tenant_id = tenant_row.tenant_id
            ORDER BY created_at, id
        LOOP
            base_name := btrim(profile_row.name);
            IF base_name = '' THEN
                base_name := 'กลุ่มคำค้น';
            END IF;
            candidate_name := base_name;
            suffix_number := 2;
            WHILE lower(btrim(candidate_name)) = ANY(used_names) LOOP
                candidate_name := base_name || ' (' || suffix_number || ')';
                suffix_number := suffix_number + 1;
            END LOOP;
            IF candidate_name IS DISTINCT FROM profile_row.name THEN
                UPDATE crawl_profiles
                SET name = candidate_name,
                    updated_at = NOW()
                WHERE id = profile_row.id;
            END IF;
            used_names := array_append(used_names, lower(btrim(candidate_name)));
        END LOOP;
    END LOOP;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS crawl_profiles_tenant_normalized_name_uq
    ON crawl_profiles (tenant_id, lower(btrim(name)));
