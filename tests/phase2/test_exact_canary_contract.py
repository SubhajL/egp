from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from egp_shared_types.enums import DiscoveryFailureCode


TARGET_PAYLOAD = {
    "contract_version": 1,
    "kind": "exact_ingestion_canary",
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "job_id": "22222222-2222-4222-8222-222222222222",
    "profile_id": "33333333-3333-4333-8333-333333333333",
    "keyword": "ประกวดราคาจ้างวิเคราะห์ข้อมูล",
    "live": True,
    "execution_backend": "legacy",
    "browser_required": True,
    "max_pages_per_keyword": 15,
}


def _target_type():
    module = importlib.import_module("egp_shared_types.exact_canary")
    return module.ExactIngestionCanaryTarget


def test_exact_canary_target_round_trips_and_hashes_canonical_contract() -> None:
    target_type = _target_type()

    target = target_type.from_mapping(TARGET_PAYLOAD)

    assert target.to_mapping() == TARGET_PAYLOAD
    assert len(target.canonical_digest()) == 64
    assert target.canonical_digest() == target_type.from_mapping(
        dict(reversed(list(TARGET_PAYLOAD.items())))
    ).canonical_digest()
    assert TARGET_PAYLOAD["keyword"] not in target.canonical_digest()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", 2),
        ("kind", "observation_canary"),
        ("tenant_id", "not-a-uuid"),
        ("job_id", "not-a-uuid"),
        ("profile_id", "not-a-uuid"),
        ("keyword", ""),
        ("keyword", " not-normalized "),
        ("keyword", "bad\x00keyword"),
        ("live", False),
        ("execution_backend", "agent"),
        ("browser_required", False),
        ("max_pages_per_keyword", 0),
        ("max_pages_per_keyword", 16),
    ],
)
def test_exact_canary_target_rejects_invalid_locked_field(field: str, value: object) -> None:
    payload = dict(TARGET_PAYLOAD)
    payload[field] = value

    with pytest.raises(ValueError):
        _target_type().from_mapping(payload)


def test_exact_canary_target_rejects_missing_and_extra_fields() -> None:
    missing = dict(TARGET_PAYLOAD)
    missing.pop("profile_id")
    extra = {**TARGET_PAYLOAD, "required_pages": 5}

    with pytest.raises(ValueError):
        _target_type().from_mapping(missing)
    with pytest.raises(ValueError):
        _target_type().from_mapping(extra)


def test_migration_040_matches_new_discovery_failure_codes() -> None:
    expected_new_codes = {
        "browser_start_failed",
        "pagination_control_hidden",
        "pagination_next_click_failed",
        "pagination_page_change_timeout",
        "pagination_unexpected_no_results",
        "pagination_site_error",
        "canary_target_mismatch",
        "canary_proof_invalid",
    }
    assert expected_new_codes <= {code.value for code in DiscoveryFailureCode}

    migrations_dir = Path(__file__).resolve().parents[2] / "packages/db/src/migrations"
    migration = migrations_dir / "040_exact_canary_failure_codes.sql"
    sql = migration.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT discovery_jobs_last_error_code_check" in sql
    assert "ADD CONSTRAINT discovery_jobs_last_error_code_check" in sql
    for code in DiscoveryFailureCode:
        assert f"'{code.value}'" in sql

    manifest = (migrations_dir / "manifest.sha256").read_text(encoding="utf-8")
    assert "040_exact_canary_failure_codes.sql" in manifest
    assert json.dumps(TARGET_PAYLOAD, ensure_ascii=False) not in sql
