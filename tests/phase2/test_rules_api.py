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

    assert body["entitlements"] == {
        "plan_code": None,
        "plan_label": None,
        "subscription_status": None,
        "has_active_subscription": False,
        "keyword_limit": None,
        "active_keyword_count": 2,
        "remaining_keyword_slots": None,
        "active_keywords": ["วิเคราะห์ข้อมูล", "ระบบสารสนเทศ"],
        "over_keyword_limit": False,
        "runs_allowed": False,
        "exports_allowed": False,
        "document_download_allowed": False,
        "notifications_allowed": False,
        "source": "billing_subscriptions + crawl_profile_keywords",
    }

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

    assert body["notification_rules"]["supported_channels"] == [
        "in_app",
        "email",
        "webhook",
    ]
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
    assert body["schedule_rules"]["editable_in_product"] is True
    assert body["schedule_rules"]["tenant_crawl_interval_hours"] is None
    assert body["schedule_rules"]["default_crawl_interval_hours"] == 24
    assert body["schedule_rules"]["effective_crawl_interval_hours"] == 24
    assert (
        body["schedule_rules"]["source"] == "tenant_settings + default schedule policy"
    )


def test_rules_endpoint_includes_cors_headers_for_localhost_dev_origin(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-cors.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
        )
    )

    response = client.get(
        "/v1/rules",
        params={"tenant_id": TENANT_ID},
        headers={"Origin": "http://localhost:3002"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3002"
    assert response.headers["access-control-allow-credentials"] == "true"


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
    assert body["entitlements"] == {
        "plan_code": None,
        "plan_label": None,
        "subscription_status": None,
        "has_active_subscription": False,
        "keyword_limit": None,
        "active_keyword_count": 0,
        "remaining_keyword_slots": None,
        "active_keywords": [],
        "over_keyword_limit": False,
        "runs_allowed": False,
        "exports_allowed": False,
        "document_download_allowed": False,
        "notifications_allowed": False,
        "source": "billing_subscriptions + crawl_profile_keywords",
    }
    assert body["closure_rules"]["consulting_timeout_days"] == 30
    assert body["closure_rules"]["stale_no_tor_days"] == 45
    assert body["notification_rules"]["event_wiring_complete"] is True
    assert body["schedule_rules"]["supported_trigger_types"] == [
        "schedule",
        "manual",
        "retry",
        "backfill",
    ]
    assert body["schedule_rules"]["effective_crawl_interval_hours"] == 24


def test_billing_plans_include_free_trial(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-plans.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    response = client.get("/v1/billing/plans")

    assert response.status_code == 200
    plans = {plan["code"]: plan for plan in response.json()["plans"]}
    assert plans["free_trial"] == {
        "code": "free_trial",
        "label": "Free Trial",
        "description": "Try 1 active keyword for 7 days",
        "currency": "THB",
        "amount_due": "0.00",
        "billing_interval": "trial",
        "keyword_limit": 1,
        "duration_days": 7,
        "duration_months": None,
    }


def test_rules_endpoint_returns_tenant_crawl_schedule_override(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-schedule.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenant_settings (
                    id,
                    tenant_id,
                    timezone,
                    locale,
                    daily_digest_enabled,
                    weekly_digest_enabled,
                    crawl_interval_hours,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    'Asia/Bangkok',
                    'th-TH',
                    1,
                    0,
                    6,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "created_at": "2026-04-06T00:00:00+00:00",
                "updated_at": "2026-04-06T00:00:00+00:00",
            },
        )

    response = client.get("/v1/rules", params={"tenant_id": TENANT_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["schedule_rules"]["tenant_crawl_interval_hours"] == 6
    assert body["schedule_rules"]["effective_crawl_interval_hours"] == 6


def test_admin_can_create_custom_profile_from_rules_api(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-create.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Keyword Watchlist",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics", "  analytics  ", "cloud procurement"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Keyword Watchlist"
    assert body["profile_type"] == "custom"
    assert body["keywords"] == ["analytics", "cloud procurement"]

    listing = client.get("/v1/rules", params={"tenant_id": TENANT_ID})
    assert listing.status_code == 200
    assert listing.json()["profiles"][0]["keywords"] == [
        "analytics",
        "cloud procurement",
    ]


def test_profile_creation_respects_active_keyword_limit(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-limit.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO billing_records (
                    id,
                    tenant_id,
                    record_number,
                    plan_code,
                    status,
                    billing_period_start,
                    billing_period_end,
                    currency,
                    amount_due,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    'INV-LIMIT',
                    'free_trial',
                    'paid',
                    '2026-04-05',
                    '2026-04-11',
                    'THB',
                    '0.00',
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": "aaaaaaaa-1111-1111-1111-111111111111",
                "tenant_id": TENANT_ID,
                "created_at": "2026-04-05T00:00:00+00:00",
                "updated_at": "2026-04-05T00:00:00+00:00",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO billing_subscriptions (
                    id,
                    tenant_id,
                    billing_record_id,
                    plan_code,
                    status,
                    billing_period_start,
                    billing_period_end,
                    keyword_limit,
                    activated_at,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    'aaaaaaaa-1111-1111-1111-111111111111',
                    'free_trial',
                    'active',
                    '2026-04-05',
                    '2026-04-11',
                    1,
                    :activated_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": "bbbbbbbb-1111-1111-1111-111111111111",
                "tenant_id": TENANT_ID,
                "activated_at": "2026-04-05T00:00:00+00:00",
                "created_at": "2026-04-05T00:00:00+00:00",
                "updated_at": "2026-04-05T00:00:00+00:00",
            },
        )
    _seed_profile(
        client,
        profile_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        name="Trial",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("first keyword", 1)],
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Second Profile",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["second keyword"],
        },
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"] == "active keyword configuration exceeds plan limit"
    )
    assert response.json()["code"] == "active_keyword_limit_exceeded"


def test_profile_creation_with_blank_name_returns_structured_validation_code(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-validation.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "   ",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics"],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "profile name is required",
        "code": "profile_name_required",
    }
