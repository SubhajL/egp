"""Tests for immediate discover trigger after profile creation.

When a user creates a keyword profile via POST /v1/rules/profiles, the API
should schedule background discover jobs — one per keyword — using the
discover_spawner callable on app.state.  In production this spawns a worker
subprocess; in tests we inject a simple recorder.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import (
    DISCOVER_WORKER_TIMEOUT_SECONDS,
    _discovery_dispatch_loop_enabled_for_database_url,
    _discovery_dispatch_route_kick_enabled,
    _logger,
    _make_discover_spawner,
    create_app,
)
from egp_api.services.discovery_dispatch import NonRetriableDiscoveryDispatchError

TENANT_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app_with_recorder(tmp_path, *, spawner=None):
    """Create a test app with an injected discover_spawner recorder."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'discover-trigger.sqlite3'}"
    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        auth_required=False,
    )
    if spawner is not None:
        app.state.discover_spawner = spawner
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_profile_creation_triggers_discover_per_keyword(tmp_path):
    """POST /v1/rules/profiles should dispatch one queued job per keyword."""
    spawned: list[dict] = []

    def record_spawn(*, tenant_id, profile_id, profile_type, keyword):
        spawned.append(
            {
                "tenant_id": tenant_id,
                "profile_id": profile_id,
                "profile_type": profile_type,
                "keyword": keyword,
            }
        )

    client = TestClient(_make_app_with_recorder(tmp_path, spawner=record_spawn))
    today = date.today()
    _seed_subscription(
        client,
        plan_code="monthly_membership",
        keyword_limit=5,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=29),
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Keyword Watchlist",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics", "cloud procurement"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    profile_id = body["id"]

    assert len(spawned) == 2
    assert spawned[0]["tenant_id"] == TENANT_ID
    assert spawned[0]["profile_id"] == profile_id
    assert spawned[0]["profile_type"] == "custom"
    assert spawned[0]["keyword"] == "analytics"
    assert spawned[1]["keyword"] == "cloud procurement"

    with client.app.state.db_engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM discovery_jobs")
        ).scalar_one()
    assert count == 2


def test_profile_creation_uses_overridden_spawner_for_queue_dispatch(tmp_path):
    dispatched: list[str] = []

    def record_spawn(*, tenant_id, profile_id, profile_type, keyword):
        dispatched.append(keyword)

    client = TestClient(_make_app_with_recorder(tmp_path, spawner=record_spawn))
    today = date.today()
    _seed_subscription(
        client,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Override Recorder",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics"],
        },
    )

    assert response.status_code == 201
    assert dispatched == ["analytics"]


def test_profile_creation_succeeds_when_spawner_is_none(tmp_path):
    """Profile creation must not fail if discover_spawner is None."""
    app = create_app(
        artifact_root=tmp_path,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'no-spawner.sqlite3'}",
        auth_required=False,
    )
    app.state.discover_spawner = None

    client = TestClient(app)
    today = date.today()
    _seed_subscription(
        client,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )
    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "No Spawner",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["testing"],
        },
    )

    assert response.status_code == 201
    assert response.json()["keywords"] == ["testing"]


def test_profile_creation_persists_jobs_and_background_processor_dispatches_them(
    tmp_path,
):
    dispatched: list[str] = []

    def record_spawn(*, tenant_id, profile_id, profile_type, keyword):
        dispatched.append(keyword)

    client = TestClient(_make_app_with_recorder(tmp_path, spawner=record_spawn))
    today = date.today()
    _seed_subscription(
        client,
        plan_code="monthly_membership",
        keyword_limit=5,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=29),
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Dispatch Queue",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics", "cloud procurement"],
        },
    )

    assert response.status_code == 201
    assert dispatched == ["analytics", "cloud procurement"]

    with client.app.state.db_engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT keyword, job_status, attempt_count FROM discovery_jobs ORDER BY keyword"
                )
            )
            .mappings()
            .all()
        )
    assert rows == [
        {"keyword": "analytics", "job_status": "dispatched", "attempt_count": 1},
        {
            "keyword": "cloud procurement",
            "job_status": "dispatched",
            "attempt_count": 1,
        },
    ]


def _seed_subscription(
    client: TestClient,
    *,
    plan_code: str,
    keyword_limit: int,
    billing_period_start: date,
    billing_period_end: date,
) -> None:
    now = "2026-04-08T00:00:00+00:00"
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
                    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    :tenant_id,
                    'INV-DISCOVER',
                    :plan_code,
                    'paid',
                    :billing_period_start,
                    :billing_period_end,
                    'THB',
                    '0.00',
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "plan_code": plan_code,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
                "now": now,
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
                    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                    :tenant_id,
                    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                    :plan_code,
                    'active',
                    :billing_period_start,
                    :billing_period_end,
                    :keyword_limit,
                    :now,
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "plan_code": plan_code,
                "billing_period_start": billing_period_start.isoformat(),
                "billing_period_end": billing_period_end.isoformat(),
                "keyword_limit": keyword_limit,
                "now": now,
            },
        )


def test_active_profile_creation_without_subscription_does_not_enqueue_or_dispatch(
    tmp_path,
):
    spawned: list[dict] = []

    def record_spawn(*, tenant_id, profile_id, profile_type, keyword):
        spawned.append(
            {
                "tenant_id": tenant_id,
                "profile_id": profile_id,
                "profile_type": profile_type,
                "keyword": keyword,
            }
        )

    client = TestClient(_make_app_with_recorder(tmp_path, spawner=record_spawn))

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Denied Watchlist",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "active subscription required for runs"
    assert spawned == []

    with client.app.state.db_engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM discovery_jobs")
        ).scalar_one()
    assert count == 0


def test_active_free_trial_profile_creation_still_enqueues_and_dispatches(tmp_path):
    spawned: list[str] = []

    def record_spawn(*, tenant_id, profile_id, profile_type, keyword):
        spawned.append(keyword)

    client = TestClient(_make_app_with_recorder(tmp_path, spawner=record_spawn))
    today = date.today()
    _seed_subscription(
        client,
        plan_code="free_trial",
        keyword_limit=1,
        billing_period_start=today - timedelta(days=1),
        billing_period_end=today + timedelta(days=5),
    )

    response = client.post(
        "/v1/rules/profiles",
        json={
            "tenant_id": TENANT_ID,
            "name": "Trial Watchlist",
            "profile_type": "custom",
            "is_active": True,
            "keywords": ["analytics"],
        },
    )

    assert response.status_code == 201
    assert spawned == ["analytics"]

    with client.app.state.db_engine.connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM discovery_jobs")
        ).scalar_one()
    assert count == 1


def test_make_discover_spawner_logs_spawn_failure_with_keyword_context(
    tmp_path, monkeypatch, caplog
):
    def fake_popen(*args, **kwargs):
        raise RuntimeError("worker exited early")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    caplog.set_level(logging.WARNING, logger=_logger.name)
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")

    with pytest.raises(RuntimeError, match="worker exited early"):
        spawner(
            tenant_id=TENANT_ID,
            profile_id="profile-1",
            profile_type="custom",
            keyword="analytics",
        )
    assert any(
        "Failed to spawn discover for keyword 'analytics'" in message
        for message in caplog.messages
    )


def test_make_discover_spawner_logs_non_zero_exit_with_stderr_preview(
    tmp_path, monkeypatch, caplog
):
    class FakeProcess:
        def __init__(self):
            self.returncode = 7

        def communicate(self, *, input=None, timeout=None):
            return (None, b"fatal worker traceback\nline two")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    caplog.set_level(logging.WARNING, logger=_logger.name)
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")

    with pytest.raises(RuntimeError, match="discover worker exited non-zero"):
        spawner(
            tenant_id=TENANT_ID,
            profile_id="profile-1",
            profile_type="custom",
            keyword="analytics",
        )

    assert any("returncode=7" in message for message in caplog.messages)
    assert any("fatal worker traceback" in message for message in caplog.messages)
    assert any("keyword 'analytics'" in message for message in caplog.messages)


def test_make_discover_spawner_logs_timeout_with_keyword_context(
    tmp_path, monkeypatch, caplog
):
    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False
            self.communicate_calls = 0

        def communicate(self, *, input=None, timeout=None):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                raise subprocess.TimeoutExpired(
                    cmd=["python", "-m", "egp_worker.main"],
                    timeout=600,
                    stderr=b"worker hung after startup",
                )
            self.returncode = -9
            return (None, b"worker hung after startup")

        def kill(self):
            self.killed = True

    fake_process = FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_process)
    caplog.set_level(logging.WARNING, logger=_logger.name)
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")

    with pytest.raises(RuntimeError, match="discover worker timed out"):
        spawner(
            tenant_id=TENANT_ID,
            profile_id="profile-1",
            profile_type="custom",
            keyword="analytics",
        )

    assert fake_process.killed is True
    assert any("timed out" in message for message in caplog.messages)
    assert any("worker hung after startup" in message for message in caplog.messages)
    assert any("keyword 'analytics'" in message for message in caplog.messages)


def test_make_discover_spawner_raises_non_retriable_error_for_entitlement_denial(
    tmp_path, monkeypatch, caplog
):
    class FakeProcess:
        def __init__(self):
            self.returncode = 1

        def communicate(self, *, input=None, timeout=None):
            return (
                None,
                b'{"error_type":"entitlement_denied","detail":"active subscription required for runs"}\n',
            )

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    caplog.set_level(logging.WARNING, logger=_logger.name)
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")

    with pytest.raises(
        NonRetriableDiscoveryDispatchError,
        match="active subscription required for runs",
    ):
        spawner(
            tenant_id=TENANT_ID,
            profile_id="profile-1",
            profile_type="custom",
            keyword="analytics",
        )

    assert any("returncode=1" in message for message in caplog.messages)
    assert any("keyword 'analytics'" in message for message in caplog.messages)


def test_make_discover_spawner_forwards_profile_id_in_worker_payload(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, *, input=None, timeout=None):
            captured["payload"] = input
            captured["timeout"] = timeout
            return (None, b"")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")

    spawner(
        tenant_id=TENANT_ID,
        profile_id="profile-123",
        profile_type="custom",
        keyword="analytics",
    )

    assert captured["timeout"] == DISCOVER_WORKER_TIMEOUT_SECONDS
    payload = captured["payload"].decode()
    assert '"profile_id": "profile-123"' in payload
    assert '"trigger_type": "manual"' in payload


def test_make_discover_spawner_enables_live_document_collection_in_worker_payload(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, *, input=None, timeout=None):
            captured["payload"] = input
            return (None, b"")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")

    spawner(
        tenant_id=TENANT_ID,
        profile_id="profile-123",
        profile_type="custom",
        keyword="analytics",
    )

    payload = json.loads(captured["payload"].decode())
    assert payload["live_include_documents"] is True


def test_discovery_dispatch_runtime_uses_single_dispatch_path_per_database_backend():
    sqlite_url = "sqlite+pysqlite:///test.sqlite3"
    postgres_url = "postgresql://egp:egp_dev@localhost:5432/egp"

    assert _discovery_dispatch_loop_enabled_for_database_url(sqlite_url) is False
    assert _discovery_dispatch_route_kick_enabled(sqlite_url) is True

    assert _discovery_dispatch_loop_enabled_for_database_url(postgres_url) is True
    assert _discovery_dispatch_route_kick_enabled(postgres_url) is False
