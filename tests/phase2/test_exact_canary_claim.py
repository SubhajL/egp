from __future__ import annotations

import importlib
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from egp_db.repositories.discovery_job_repo import SqlDiscoveryJobRepository


TENANT_ID = "11111111-1111-4111-8111-111111111111"
PROFILE_ID = "22222222-2222-4222-8222-222222222222"
KEYWORD = "ประกวดราคาจ้างวิเคราะห์ข้อมูล"


def _target(**overrides: object):
    target_type = importlib.import_module(
        "egp_shared_types.exact_canary"
    ).ExactIngestionCanaryTarget
    payload = {
        "contract_version": 1,
        "kind": "exact_ingestion_canary",
        "tenant_id": TENANT_ID,
        "job_id": overrides.pop("job_id"),
        "profile_id": PROFILE_ID,
        "keyword": KEYWORD,
        "live": True,
        "execution_backend": "legacy",
        "browser_required": True,
        "max_pages_per_keyword": 15,
        **overrides,
    }
    return target_type.from_mapping(payload)


def _repo(tmp_path: Path, name: str) -> SqlDiscoveryJobRepository:
    repo = SqlDiscoveryJobRepository(
        database_url=f"sqlite+pysqlite:///{tmp_path / f'{name}.sqlite3'}",
        bootstrap_schema=True,
    )
    now = "2026-08-24T00:00:00+00:00"
    with repo._engine.begin() as connection:  # test setup only
        connection.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:id, 'Canary', :slug, 'monthly_membership', 1, :now, :now)
                """
            ),
            {"id": TENANT_ID, "slug": f"canary-{name}", "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles (
                    id, tenant_id, name, profile_type, is_active,
                    max_pages_per_keyword, close_consulting_after_days,
                    close_stale_after_days, execution_backend, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, 'Canary', 'custom', 1,
                    15, 30, 45, 'legacy', :now, :now
                )
                """
            ),
            {"id": PROFILE_ID, "tenant_id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profile_keywords (id, profile_id, keyword, position, created_at)
                VALUES (:id, :profile_id, :keyword, 1, :now)
                """
            ),
            {
                "id": str(uuid4()),
                "profile_id": PROFILE_ID,
                "keyword": KEYWORD,
                "now": now,
            },
        )
    return repo


def _job(repo: SqlDiscoveryJobRepository, *, live: bool = True):
    return repo.create_discovery_job(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword=KEYWORD,
        live=live,
    )


def test_exact_canary_claim_requires_every_pinned_field(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "exact-match")
    job = _job(repo)
    target = _target(job_id=job.id)

    assert repo.has_claimable_discovery_jobs(exact_canary_target=target) is True
    claimed = repo.claim_pending_discovery_jobs(
        limit=1,
        exact_canary_target=target,
    )

    assert [record.id for record in claimed] == [job.id]
    assert claimed[0].live is True
    assert claimed[0].execution_backend == "legacy"


@pytest.mark.parametrize(
    "mismatch",
    [
        "tenant_id",
        "job_id",
        "profile_id",
        "keyword",
        "job_live",
        "profile_backend",
        "profile_cap",
        "profile_keyword",
    ],
)
def test_exact_canary_claim_mismatch_does_not_mutate_job(
    tmp_path: Path,
    mismatch: str,
) -> None:
    repo = _repo(tmp_path, mismatch)
    job = _job(repo, live=mismatch != "job_live")
    overrides: dict[str, object] = {"job_id": job.id}
    if mismatch == "tenant_id":
        overrides["tenant_id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    elif mismatch == "job_id":
        overrides["job_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    elif mismatch == "profile_id":
        overrides["profile_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    elif mismatch == "keyword":
        overrides["keyword"] = "คำค้นอื่น"

    with repo._engine.begin() as connection:  # test setup only
        if mismatch == "profile_backend":
            connection.execute(
                text("UPDATE crawl_profiles SET execution_backend = 'agent' WHERE id = :id"),
                {"id": PROFILE_ID},
            )
        elif mismatch == "profile_cap":
            connection.execute(
                text("UPDATE crawl_profiles SET max_pages_per_keyword = 7 WHERE id = :id"),
                {"id": PROFILE_ID},
            )
        elif mismatch == "profile_keyword":
            connection.execute(
                text("UPDATE crawl_profile_keywords SET keyword = 'คำค้นอื่น' WHERE profile_id = :id"),
                {"id": PROFILE_ID},
            )

    target = _target(**overrides)
    assert repo.has_claimable_discovery_jobs(exact_canary_target=target) is False
    assert repo.claim_pending_discovery_jobs(
        limit=1,
        exact_canary_target=target,
    ) == []

    stored = repo.get_discovery_job(tenant_id=TENANT_ID, job_id=job.id)
    assert stored.job_status == "pending"
    assert stored.claim_token is None
    assert stored.processing_started_at is None
