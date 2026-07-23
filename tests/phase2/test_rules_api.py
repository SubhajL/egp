from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from fastapi.testclient import TestClient
from jose import jwt

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"
JWT_SECRET = "phase2-rules-secret"


class RecordingWakeSignal:
    def __init__(self) -> None:
        self.wake_count = 0

    def wake(self) -> None:
        self.wake_count += 1


class FailingDiscoveryProcessor:
    def process_pending(self, *, limit: int | None = None) -> int:
        raise AssertionError("route handlers must not execute discovery dispatch")


def _auth_headers(*, role: str, tenant_id: str = TENANT_ID) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": tenant_id,
            "role": role,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


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
                    enabled_by_user,
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


def _seed_active_subscription(
    client: TestClient,
    *,
    plan_code: str,
    keyword_limit: int | None,
) -> None:
    active_start = date.today() - timedelta(days=1)
    active_end = date.today() + timedelta(days=6)
    activated_at = f"{active_start.isoformat()}T00:00:00+00:00"
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
                    :record_number,
                    :plan_code,
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    :amount_due,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "record_number": f"INV-{plan_code.upper()}",
                "plan_code": plan_code,
                "billing_period_start": active_start.isoformat(),
                "billing_period_end": active_end.isoformat(),
                "amount_due": "0.00" if plan_code == "free_trial" else "1500.00",
                "created_at": activated_at,
                "updated_at": activated_at,
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
                    :billing_record_id,
                    :plan_code,
                    'active',
                    :billing_period_start,
                    :billing_period_end,
                    :keyword_limit,
                    :activated_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": TENANT_ID,
                "billing_record_id": connection.execute(
                    text(
                        """
                        SELECT id
                        FROM billing_records
                        WHERE tenant_id = :tenant_id
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"tenant_id": TENANT_ID},
                ).scalar_one(),
                "plan_code": plan_code,
                "billing_period_start": active_start.isoformat(),
                "billing_period_end": active_end.isoformat(),
                "keyword_limit": keyword_limit,
                "activated_at": activated_at,
                "created_at": activated_at,
                "updated_at": activated_at,
            },
        )


def _seed_tenant_entitlements(
    client: TestClient,
    *,
    max_concurrent_runs: int = 1,
    max_queued_keywords: int = 20,
) -> None:
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenant_entitlements (
                    tenant_id,
                    max_concurrent_runs,
                    max_queued_keywords,
                    created_at,
                    updated_at
                ) VALUES (
                    :tenant_id,
                    :max_concurrent_runs,
                    :max_queued_keywords,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "max_concurrent_runs": max_concurrent_runs,
                "max_queued_keywords": max_queued_keywords,
                "created_at": "2026-04-04T00:00:00+00:00",
                "updated_at": "2026-04-04T00:00:00+00:00",
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
        "saved_keyword_count": 3,
        "enabled_keyword_count": 2,
        "runnable_keyword_count": 0,
        "runnable_keywords": [],
        "active_keyword_count": 0,
        "remaining_keyword_slots": None,
        "active_keywords": [],
        "over_keyword_limit": False,
        "runs_allowed": False,
        "exports_allowed": False,
        "document_download_allowed": False,
        "notifications_allowed": False,
        "source": "billing_subscriptions + crawl_profiles + crawl_profile_keywords",
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
        "saved_keyword_count": 0,
        "enabled_keyword_count": 0,
        "runnable_keyword_count": 0,
        "runnable_keywords": [],
        "active_keyword_count": 0,
        "remaining_keyword_slots": None,
        "active_keywords": [],
        "over_keyword_limit": False,
        "runs_allowed": False,
        "exports_allowed": False,
        "document_download_allowed": False,
        "notifications_allowed": False,
        "source": "billing_subscriptions + crawl_profiles + crawl_profile_keywords",
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
    assert plans["monthly_membership"]["keyword_limit"] is None


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
    client.app.state.discovery_dispatch_route_kick_enabled = False
    active_start = date.today() - timedelta(days=1)
    active_end = date.today() + timedelta(days=6)
    activated_at = f"{active_start.isoformat()}T00:00:00+00:00"

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
                    'aaaaaaaa-2222-2222-2222-222222222222',
                    :tenant_id,
                    'INV-CREATE',
                    'monthly_membership',
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    '1500.00',
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "billing_period_start": active_start.isoformat(),
                "billing_period_end": active_end.isoformat(),
                "created_at": activated_at,
                "updated_at": activated_at,
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
                    'bbbbbbbb-2222-2222-2222-222222222222',
                    :tenant_id,
                    'aaaaaaaa-2222-2222-2222-222222222222',
                    'monthly_membership',
                    'active',
                    :billing_period_start,
                    :billing_period_end,
                    5,
                    :activated_at,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "billing_period_start": active_start.isoformat(),
                "billing_period_end": active_end.isoformat(),
                "activated_at": activated_at,
                "created_at": activated_at,
                "updated_at": activated_at,
            },
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
    with client.app.state.db_engine.connect() as connection:
        queued_jobs = (
            connection.execute(
                text(
                    """
                SELECT keyword, trigger_type, job_status
                FROM discovery_jobs
                WHERE tenant_id = :tenant_id
                ORDER BY keyword
                """
                ),
                {"tenant_id": TENANT_ID},
            )
            .mappings()
            .all()
        )

    assert [dict(row) for row in queued_jobs] == [
        {
            "keyword": "analytics",
            "trigger_type": "profile_created",
            "job_status": "pending",
        },
        {
            "keyword": "cloud procurement",
            "trigger_type": "profile_created",
            "job_status": "pending",
        },
    ]

    listing = client.get("/v1/rules", params={"tenant_id": TENANT_ID})
    assert listing.status_code == 200
    assert listing.json()["profiles"][0]["keywords"] == [
        "analytics",
        "cloud procurement",
    ]


def test_admin_can_update_profile_keywords_and_deactivate_from_rules_api(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-update.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    wake_signal = RecordingWakeSignal()
    client.app.state.discovery_dispatch_route_kick_enabled = True
    client.app.state.discovery_dispatch_wake_signal = wake_signal
    client.app.state.discovery_dispatch_processor = FailingDiscoveryProcessor()
    _seed_active_subscription(
        client, plan_code="monthly_membership", keyword_limit=None
    )
    _seed_profile(
        client,
        profile_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        name="Keyword Watchlist",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("analytics", 1), ("cloud procurement", 2)],
    )

    updated = client.patch(
        "/v1/rules/profiles/cccccccc-cccc-cccc-cccc-cccccccccccc",
        json={
            "tenant_id": TENANT_ID,
            "keywords": ["analytics", "ai procurement"],
        },
    )

    assert updated.status_code == 200
    assert updated.json()["keywords"] == ["analytics", "ai procurement"]
    assert wake_signal.wake_count == 1
    with client.app.state.db_engine.connect() as connection:
        queued_keyword = connection.execute(
            text(
                """
                SELECT keyword
                FROM discovery_jobs
                WHERE tenant_id = :tenant_id
                    AND profile_id = :profile_id
                    AND trigger_type = 'profile_updated'
                    AND job_status = 'pending'
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "profile_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            },
        ).scalar_one()
    assert queued_keyword == "ai procurement"

    deactivated = client.patch(
        "/v1/rules/profiles/cccccccc-cccc-cccc-cccc-cccccccccccc",
        json={
            "tenant_id": TENANT_ID,
            "is_active": False,
            "keywords": [],
        },
    )

    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["enabled_by_user"] is False
    assert deactivated.json()["effective_status"] == "paused_by_user"
    assert deactivated.json()["keywords"] == ["analytics", "ai procurement"]
    assert wake_signal.wake_count == 1
    listing = client.get("/v1/rules", params={"tenant_id": TENANT_ID})
    assert listing.status_code == 200
    assert listing.json()["entitlements"]["active_keyword_count"] == 0


def test_profile_update_does_not_queue_keyword_owned_by_older_group(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-update-dedupe.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(client, plan_code="monthly_membership", keyword_limit=None)
    for profile_id, name, keywords in (
        (
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "Older Group",
            [("analytics", 1)],
        ),
        (
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "Newer Group",
            [("procurement", 1)],
        ),
    ):
        _seed_profile(
            client,
            profile_id=profile_id,
            name=name,
            profile_type="custom",
            is_active=True,
            max_pages_per_keyword=15,
            close_consulting_after_days=30,
            close_stale_after_days=45,
            keywords=keywords,
        )

    response = client.patch(
        "/v1/rules/profiles/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        json={
            "tenant_id": TENANT_ID,
            "keywords": ["procurement", " ANALYTICS "],
        },
    )

    assert response.status_code == 200
    with client.app.state.db_engine.connect() as connection:
        jobs = connection.execute(
            text(
                """
                SELECT profile_id, keyword
                FROM discovery_jobs
                WHERE trigger_type = 'profile_updated'
                """
            )
        ).mappings().all()
    assert jobs == []


def test_profile_creation_respects_active_keyword_limit(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-limit.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    active_start = date.today() - timedelta(days=1)
    active_end = date.today() + timedelta(days=6)
    activated_at = f"{active_start.isoformat()}T00:00:00+00:00"

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
                    :billing_period_start,
                    :billing_period_end,
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
                "billing_period_start": active_start.isoformat(),
                "billing_period_end": active_end.isoformat(),
                "created_at": activated_at,
                "updated_at": activated_at,
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
                    :billing_period_start,
                    :billing_period_end,
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
                "billing_period_start": active_start.isoformat(),
                "billing_period_end": active_end.isoformat(),
                "activated_at": activated_at,
                "created_at": activated_at,
                "updated_at": activated_at,
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

    assert response.status_code == 409
    assert (
        response.json()["detail"] == "active keyword configuration exceeds plan limit"
    )
    assert response.json()["code"] == "active_keyword_limit_exceeded"


def test_over_limit_configuration_allows_rename_but_blocks_new_enabled_group(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-over-limit-edit.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)
    profile_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    _seed_profile(
        client,
        profile_id=profile_id,
        name="Existing Group",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("first keyword", 1), ("second keyword", 2)],
    )

    renamed = client.patch(
        f"/v1/rules/profiles/{profile_id}",
        json={"tenant_id": TENANT_ID, "name": "Renamed Group"},
    )
    created = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "New Group",
            "profile_type": "custom",
            "enabled_by_user": True,
            "keywords": ["third keyword"],
        },
    )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed Group"
    assert renamed.json()["effective_status"] == "blocked_quota"
    assert created.status_code == 409
    assert created.json()["code"] == "active_keyword_limit_exceeded"


def test_profile_creation_denies_before_outbox_insert_when_keyword_queue_cap_exceeded(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-create-cap.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(
        client, plan_code="monthly_membership", keyword_limit=None
    )
    _seed_tenant_entitlements(client, max_queued_keywords=1)

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Queue Cap Create",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics", "platform"],
        },
    )

    assert response.status_code == 429
    assert response.json() == {
        "detail": "queued keyword limit exceeded",
        "code": "queued_keyword_limit_exceeded",
        "status": "queued",
        "inflight_run_count": 0,
        "max_concurrent_runs": 1,
        "queued_keyword_count": 2,
        "max_queued_keywords": 1,
    }
    with client.app.state.db_engine.connect() as connection:
        profile_count = connection.execute(
            text("SELECT COUNT(*) FROM crawl_profiles WHERE tenant_id = :tenant_id"),
            {"tenant_id": TENANT_ID},
        ).scalar_one()
        job_count = connection.execute(
            text("SELECT COUNT(*) FROM discovery_jobs WHERE tenant_id = :tenant_id"),
            {"tenant_id": TENANT_ID},
        ).scalar_one()

    assert profile_count == 0
    assert job_count == 0


def test_duplicate_keyword_group_does_not_consume_another_queue_slot(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-create-dedupe-cap.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(
        client, plan_code="monthly_membership", keyword_limit=None
    )
    _seed_tenant_entitlements(client, max_queued_keywords=1)

    first = client.post(
        "/v1/rules/profiles",
        json={"tenant_id": TENANT_ID, "name": "First Group", "keywords": ["analytics"]},
    )
    second = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Second Group",
            "keywords": [" ANALYTICS "],
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    with client.app.state.db_engine.connect() as connection:
        profile_count = connection.execute(text("SELECT COUNT(*) FROM crawl_profiles")).scalar_one()
        job_count = connection.execute(text("SELECT COUNT(*) FROM discovery_jobs")).scalar_one()
    assert profile_count == 2
    assert job_count == 1


def test_profile_update_respects_keyword_queue_cap_before_persistence(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-update-cap.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(
        client, plan_code="monthly_membership", keyword_limit=None
    )
    _seed_tenant_entitlements(client, max_queued_keywords=1)
    created = client.post(
        "/v1/rules/profiles",
        json={"tenant_id": TENANT_ID, "name": "First Group", "keywords": ["analytics"]},
    )
    profile_id = created.json()["id"]

    updated = client.patch(
        f"/v1/rules/profiles/{profile_id}",
        json={
            "tenant_id": TENANT_ID,
            "keywords": ["analytics", "procurement"],
        },
    )

    assert updated.status_code == 429
    assert updated.json()["code"] == "queued_keyword_limit_exceeded"
    detail = client.app.state.profile_repository.get_profile_detail(
        tenant_id=TENANT_ID,
        profile_id=profile_id,
    )
    assert detail is not None
    assert [keyword.keyword for keyword in detail.keywords] == ["analytics"]


def test_manual_recrawl_queues_and_wakes_active_free_trial_keyword(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    spawned: list[tuple[str, str, str]] = []
    wake_signal = RecordingWakeSignal()

    client.app.state.discover_spawner = (
        lambda *, tenant_id, profile_id, profile_type, keyword: spawned.append(
            (profile_id, profile_type, keyword)
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = True
    client.app.state.discovery_dispatch_wake_signal = wake_signal
    client.app.state.discovery_dispatch_processor = FailingDiscoveryProcessor()
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)
    _seed_profile(
        client,
        profile_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        name="Trial",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("แพลตฟอร์ม", 1)],
    )

    response = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert response.status_code == 202
    assert response.json() == {
        "queued_job_count": 1,
        "queued_keywords": ["แพลตฟอร์ม"],
    }
    assert spawned == []
    assert wake_signal.wake_count == 1

    with client.app.state.db_engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM discovery_jobs")
        ).scalar_one()
    assert count == 1


def test_manual_recrawl_allows_analyst_with_runs_entitlement(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-analyst.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=True,
            jwt_secret=JWT_SECRET,
        )
    )
    wake_signal = RecordingWakeSignal()
    client.app.state.discovery_dispatch_route_kick_enabled = True
    client.app.state.discovery_dispatch_wake_signal = wake_signal
    client.app.state.discovery_dispatch_processor = FailingDiscoveryProcessor()
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="Analyst Trial",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("แพลตฟอร์ม", 1)],
    )

    response = client.post("/v1/rules/recrawl", headers=_auth_headers(role="analyst"), json={})

    assert response.status_code == 202
    assert response.json() == {
        "queued_job_count": 1,
        "queued_keywords": ["แพลตฟอร์ม"],
    }
    assert wake_signal.wake_count == 1


def test_manual_recrawl_denies_viewer_role(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-viewer.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=True,
            jwt_secret=JWT_SECRET,
        )
    )
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)
    _seed_profile(
        client,
        profile_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        name="Viewer Trial",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("แพลตฟอร์ม", 1)],
    )

    response = client.post("/v1/rules/recrawl", headers=_auth_headers(role="viewer"), json={})

    assert response.status_code == 403
    assert response.json()["detail"] == "run operator role required"


def test_manual_recrawl_requires_at_least_one_active_keyword(tmp_path) -> None:
    database_url = (
        f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-empty.sqlite3'}"
    )
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)

    response = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert response.status_code == 400
    assert response.json() == {
        "detail": "at least one active keyword is required",
        "code": "active_keywords_required",
    }


def test_manual_recrawl_does_not_duplicate_pending_jobs(tmp_path) -> None:
    database_url = (
        f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-dedupe.sqlite3'}"
    )
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)
    _seed_profile(
        client,
        profile_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        name="Pending Trial",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("แพลตฟอร์ม", 1)],
    )

    first = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})
    second = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert first.status_code == 202
    assert first.json() == {
        "queued_job_count": 1,
        "queued_keywords": ["แพลตฟอร์ม"],
    }
    assert second.status_code == 202
    assert second.json() == {
        "queued_job_count": 0,
        "queued_keywords": [],
    }

    with client.app.state.db_engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                SELECT profile_id, keyword, job_status
                FROM discovery_jobs
                WHERE tenant_id = :tenant_id
                """
                ),
                {"tenant_id": TENANT_ID},
            )
            .mappings()
            .all()
        )

    assert rows == [
        {
            "profile_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "keyword": "แพลตฟอร์ม",
            "job_status": "pending",
        }
    ]


def test_manual_recrawl_denies_second_request_until_inflight_run_finishes(
    tmp_path,
) -> None:
    database_url = (
        f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-admission.sqlite3'}"
    )
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)
    _seed_profile(
        client,
        profile_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        name="Admission Trial",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("แพลตฟอร์ม", 1)],
    )

    first = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})
    assert first.status_code == 202

    job = client.app.state.discovery_job_repository.list_discovery_jobs(
        tenant_id=TENANT_ID
    )[0]
    client.app.state.discovery_job_repository.record_discovery_job_attempt(
        tenant_id=TENANT_ID,
        job_id=job.id,
        job_status="dispatched",
        processing_started_at=None,
        dispatched=True,
    )
    running_run = client.app.state.run_repository.create_run(
        tenant_id=TENANT_ID,
        trigger_type="manual",
        profile_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    )
    client.app.state.run_repository.mark_run_started(running_run.id)

    second = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert second.status_code == 429
    assert second.json() == {
        "detail": "queued — previous run still in progress",
        "code": "run_admission_queued",
        "status": "queued",
        "inflight_run_count": 1,
        "max_concurrent_runs": 1,
        "queued_keyword_count": 1,
        "max_queued_keywords": 20,
    }

    client.app.state.run_repository.mark_run_finished(
        running_run.id,
        status="succeeded",
    )
    third = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert third.status_code == 202
    assert third.json() == {
        "queued_job_count": 1,
        "queued_keywords": ["แพลตฟอร์ม"],
    }


def test_manual_recrawl_ignores_stale_inflight_run_for_admission(tmp_path) -> None:
    database_url = (
        f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-stale-admission.sqlite3'}"
    )
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(client, plan_code="free_trial", keyword_limit=1)
    _seed_profile(
        client,
        profile_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        name="Admission Trial",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("แพลตฟอร์ม", 1)],
    )
    stale_started_at = datetime.now(UTC) - timedelta(days=4)
    stale_run = client.app.state.run_repository.create_run(
        tenant_id=TENANT_ID,
        trigger_type="manual",
        profile_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    )
    client.app.state.run_repository.mark_run_started(stale_run.id)
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE crawl_runs
                SET started_at = :stale_started_at,
                    created_at = :stale_started_at
                WHERE id = :run_id
                """
            ),
            {"stale_started_at": stale_started_at, "run_id": stale_run.id},
        )

    response = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert response.status_code == 202
    assert response.json() == {
        "queued_job_count": 1,
        "queued_keywords": ["แพลตฟอร์ม"],
    }


def test_manual_recrawl_denies_before_outbox_insert_when_keyword_queue_cap_exceeded(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-cap.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path, database_url=database_url, auth_required=False
        )
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(
        client, plan_code="monthly_membership", keyword_limit=None
    )
    _seed_tenant_entitlements(client, max_queued_keywords=1)
    _seed_profile(
        client,
        profile_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        name="Queue Cap",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("analytics", 1), ("platform", 2)],
    )

    response = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert response.status_code == 429
    assert response.json() == {
        "detail": "queued keyword limit exceeded",
        "code": "queued_keyword_limit_exceeded",
        "status": "queued",
        "inflight_run_count": 0,
        "max_concurrent_runs": 1,
        "queued_keyword_count": 2,
        "max_queued_keywords": 1,
    }
    with client.app.state.db_engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM discovery_jobs")
        ).scalar_one()
    assert count == 0


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


def test_duplicate_group_name_returns_structured_conflict(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-name-conflict.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
        )
    )

    first = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Infrastructure",
            "enabled_by_user": True,
            "keywords": ["analytics"],
        },
    )
    duplicate = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "  INFRASTRUCTURE  ",
            "enabled_by_user": False,
            "keywords": ["platform"],
        },
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "detail": "profile name already exists",
        "code": "profile_name_conflict",
    }


def test_pause_group_preserves_keywords_and_user_intent(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-pause.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
        )
    )
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="Durable group",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("analytics", 1), ("platform", 2)],
    )

    response = client.patch(
        "/v1/rules/profiles/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        json={
            "tenant_id": TENANT_ID,
            "enabled_by_user": False,
            "keywords": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["enabled_by_user"] is False
    assert response.json()["is_active"] is False
    assert response.json()["effective_status"] == "paused_by_user"
    assert response.json()["keywords"] == ["analytics", "platform"]
    with client.app.state.db_engine.connect() as connection:
        keyword_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM crawl_profile_keywords
                WHERE profile_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                """
            )
        ).scalar_one()
    assert keyword_count == 2


def test_create_multiple_uniquely_named_keyword_groups(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-multiple-groups.sqlite3'}"
    client = TestClient(
        create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False)
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(client, plan_code="monthly_membership", keyword_limit=None)

    first = client.post(
        "/v1/rules/profiles",
        json={"tenant_id": TENANT_ID, "name": "Infrastructure", "keywords": ["cloud"]},
    )
    second = client.post(
        "/v1/rules/profiles",
        json={"tenant_id": TENANT_ID, "name": "Analytics", "keywords": ["data"]},
    )
    listing = client.get("/v1/rules", params={"tenant_id": TENANT_ID})

    assert first.status_code == 201
    assert second.status_code == 201
    assert [profile["name"] for profile in listing.json()["profiles"]] == [
        "Infrastructure",
        "Analytics",
    ]
    assert {profile["effective_status"] for profile in listing.json()["profiles"]} == {
        "running"
    }


def test_rename_group_preserves_keywords_and_order(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-rename.sqlite3'}"
    client = TestClient(
        create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False)
    )
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="Before",
        profile_type="custom",
        is_active=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("first", 1), ("second", 2)],
    )
    with client.app.state.db_engine.connect() as connection:
        ids_before = connection.execute(
            text(
                """
                SELECT id FROM crawl_profile_keywords
                WHERE profile_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                ORDER BY position
                """
            )
        ).scalars().all()

    response = client.patch(
        "/v1/rules/profiles/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        json={"tenant_id": TENANT_ID, "name": "After"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "After"
    assert response.json()["keywords"] == ["first", "second"]
    with client.app.state.db_engine.connect() as connection:
        ids_after = connection.execute(
            text(
                """
                SELECT id FROM crawl_profile_keywords
                WHERE profile_id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
                ORDER BY position
                """
            )
        ).scalars().all()
    assert ids_after == ids_before


def test_resume_group_queues_only_when_effectively_runnable(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-resume.sqlite3'}"
    client = TestClient(
        create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False)
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_profile(
        client,
        profile_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        name="Paused",
        profile_type="custom",
        is_active=False,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=[("analytics", 1)],
    )

    inactive_resume = client.patch(
        "/v1/rules/profiles/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        json={"tenant_id": TENANT_ID, "enabled_by_user": True},
    )
    client.patch(
        "/v1/rules/profiles/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        json={"tenant_id": TENANT_ID, "enabled_by_user": False},
    )
    _seed_active_subscription(client, plan_code="monthly_membership", keyword_limit=None)
    active_resume = client.patch(
        "/v1/rules/profiles/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        json={"tenant_id": TENANT_ID, "enabled_by_user": True},
    )

    assert inactive_resume.status_code == 200
    assert inactive_resume.json()["effective_status"] == "paused_by_plan"
    assert active_resume.status_code == 200
    assert active_resume.json()["effective_status"] == "running"
    with client.app.state.db_engine.connect() as connection:
        jobs = connection.execute(
            text("SELECT keyword FROM discovery_jobs ORDER BY created_at")
        ).scalars().all()
    assert jobs == ["analytics"]


def test_rules_mutations_remain_tenant_scoped(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-tenant-scope.sqlite3'}"
    client = TestClient(
        create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False)
    )
    other_tenant_id = "22222222-2222-2222-2222-222222222222"
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:id, 'Other', 'other', 'free', 1, :now, :now)
                """
            ),
            {"id": other_tenant_id, "now": "2026-07-21T00:00:00+00:00"},
        )
    other = client.app.state.profile_repository.create_profile(
        tenant_id=other_tenant_id,
        name="Other tenant group",
        profile_type="custom",
        enabled_by_user=True,
        max_pages_per_keyword=15,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=["private"],
    )

    response = client.patch(
        f"/v1/rules/profiles/{other.profile.id}",
        json={"tenant_id": TENANT_ID, "name": "Cross-tenant rename"},
    )

    assert response.status_code == 404
    unchanged = client.app.state.profile_repository.get_profile_detail(
        tenant_id=other_tenant_id,
        profile_id=other.profile.id,
    )
    assert unchanged is not None
    assert unchanged.profile.name == "Other tenant group"


def test_profile_enabled_state_conflict_returns_structured_error(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-state-conflict.sqlite3'}"
    client = TestClient(
        create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False)
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Conflict",
            "enabled_by_user": True,
            "is_active": False,
            "keywords": ["analytics"],
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "profile enabled state conflict",
        "code": "profile_enabled_state_conflict",
    }


def test_empty_group_is_saved_but_never_runnable(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-empty-group.sqlite3'}"
    client = TestClient(
        create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False)
    )
    _seed_active_subscription(client, plan_code="monthly_membership", keyword_limit=None)

    response = client.post(
        "/v1/rules/profiles",
        json={"tenant_id": TENANT_ID, "name": "Empty group", "keywords": []},
    )

    assert response.status_code == 201
    assert response.json()["enabled_by_user"] is True
    assert response.json()["effective_status"] == "paused_by_plan"
    assert response.json()["status_reason"] is None
    assert response.json()["keywords"] == []


def test_manual_recrawl_deduplicates_keyword_across_named_groups(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase2-rules-recrawl-groups.sqlite3'}"
    client = TestClient(
        create_app(artifact_root=tmp_path, database_url=database_url, auth_required=False)
    )
    client.app.state.discovery_dispatch_route_kick_enabled = False
    _seed_active_subscription(client, plan_code="monthly_membership", keyword_limit=None)
    for profile_id, name, keyword in (
        ("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "First", "analytics"),
        ("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "Second", " ANALYTICS "),
    ):
        _seed_profile(
            client,
            profile_id=profile_id,
            name=name,
            profile_type="custom",
            is_active=True,
            max_pages_per_keyword=15,
            close_consulting_after_days=30,
            close_stale_after_days=45,
            keywords=[(keyword, 1)],
        )

    response = client.post("/v1/rules/recrawl", json={"tenant_id": TENANT_ID})

    assert response.status_code == 202
    assert response.json() == {"queued_job_count": 1, "queued_keywords": ["analytics"]}
    with client.app.state.db_engine.connect() as connection:
        jobs = connection.execute(
            text("SELECT profile_id, keyword FROM discovery_jobs")
        ).mappings().all()
    assert jobs == [
        {"profile_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "keyword": "analytics"}
    ]
