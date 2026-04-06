-- Migration 008: Tenant crawl schedule settings
-- Date: 2026-04-06

ALTER TABLE tenant_settings
    ADD COLUMN crawl_interval_hours INT;

ALTER TABLE tenant_settings
    ADD CONSTRAINT tenant_settings_crawl_interval_hours_check
    CHECK (crawl_interval_hours IS NULL OR crawl_interval_hours > 0);
