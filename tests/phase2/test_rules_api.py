from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from fastapi.testclient import TestClient

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _seed_profile(
    client: TestClient,
    *,
    profile_id: str,
    name: str,
    profile_type: str,
    is_active: bool,
    max_pages_per_keyword: int,
    close_consulting_after_days: int,
    close_stale_after_days: int,
    keywords: list[tuple[str, int]],
) -> None:
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles (
                    id,
                    tenant_id,
                    name,
                    profile_type,
                    is_active,
                    max_pages_per_keyword,
                    close_consulting_after_days,
                    close_stale_after_days,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :name,
                    :profile_type,
                    :is_active,
                    :max_pages_per_keyword,
                    :close_consulting_after_days,
                    :close_stale_after_days,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": profile_id,
                "tenant_id": TENANT_ID,
                "name": name,
                "profile_type": profile_type,
                "is_active": is_active,
                "max_pages_per_keyword": max_pages_per_keyword,
                "close_consulting_after_days": close_consulting_after_days,
                "close_stale_after_days": close_stale_after_days,
                "created_at": "2026-04-04T00:00:00+00:00",
                "updated_at": "2026-04-04T00:00:00+00:00",
            },
        )
        for index, (keyword, position) in enumerate(keywords, start=1):
            connection.execute(
                text(
                    """
                    INSERT INTO crawl_profile_keywords (
                        id,
                        profile_id,
                        keyword,
                        position,
                        created_at
                    ) VALUES (
                        :id,
                        :profile_id,
                        :keyword,
                        :position,
                        :created_at
                    )
                    """
                ),
                {
                    "id": str(uuid4()),
                    "profile_id": profile_id,
                    "keyword": keyword,
                    "position": position,
                    "created_at": "2026-04-04T00:00:00+00:00",
                },
            )


def test_rules_endpoint_returns_profiles_keywords_and_explicit_platform_settings(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="TOR",
        profile_type="tor",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("ระบบสารสนเทศ", 2), ("วิเคราะห์ข้อมูล", 1)],
    )
    _seed_profile(
        client,
        profile_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        name="TOE",
        profile_type="toe",
        is_active=False,
        max_pages_per_keyword=10,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("เครื่องแม่ข่าย", 1)],
    )

    response = client.get("/v1/rules", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert [profile["name"] for profile in body["profiles"]] == ["TOR", "TOE"]
    assert body["profiles"][0]["profile_type"] == "tor"
    assert body["profiles"][0]["is_active"] is True
    assert body["profiles"][0]["max_pages_per_keyword"] == 15
    assert body["profiles"][0]["keywords"] == ["วิเคราะห์ข้อมูล", "ระบบสารสนเทศ"]
    assert body["profiles"][1]["is_active"] is False
    assert body["profiles"][1]["keywords"] == ["เครื่องแม่ข่าย"]

    assert body["closure_rules"]["close_on_winner_status"] is True
    assert body["closure_rules"]["close_on_contract_status"] is True
    assert body["closure_rules"]["winner_status_terms"] == [
        "ประกาศผู้ชนะ",
        "ผู้ชนะการเสนอราคา",
    ]
    assert body["closure_rules"]["contract_status_terms"] == [
        "ลงนามสัญญา",
        "อยู่ระหว่างลงนามสัญญา",
    ]
    assert body["closure_rules"]["consulting_timeout_days"] == 30
    assert body["closure_rules"]["stale_no_tor_days"] == 45
    assert body["closure_rules"]["stale_eligible_states"] == [
        "discovered",
        "open_consulting",
        "open_invitation",
        "open_public_hearing",
    ]
    assert (
        body["closure_rules"]["source"]
        == "packages/crawler-core/src/egp_crawler_core/closure_rules.py"
    )

    assert body["notification_rules"]["supported_channels"] == ["in_app", "email"]
    assert body["notification_rules"]["supported_types"] == [
        "new_project",
        "winner_announced",
        "contract_signed",
        "tor_changed",
        "run_failed",
        "export_ready",
    ]
    assert body["notification_rules"]["event_wiring_complete"] is True
    assert (
        body["notification_rules"]["source"]
        == "packages/notification-core/src/egp_notifications/service.py"
    )

    assert body["schedule_rules"]["supported_trigger_types"] == [
        "schedule",
        "manual",
        "retry",
        "backfill",
    ]
    assert body["schedule_rules"]["schedule_execution_supported"] is True
    assert body["schedule_rules"]["editable_in_product"] is False
    assert (
        body["schedule_rules"]["source"]
        == "packages/db/src/migrations/001_initial_schema.sql"
    )


def test_rules_endpoint_returns_defaults_when_no_profiles_exist(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-empty.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    response = client.get("/v1/rules", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["profiles"] == []
    assert body["closure_rules"]["consulting_timeout_days"] == 30
    assert body["closure_rules"]["stale_no_tor_days"] == 45
    assert body["notification_rules"]["event_wiring_complete"] is True
    assert body["schedule_rules"]["supported_trigger_types"] == [
        "schedule",
        "manual",
        "retry",
        "backfill",
    ]
