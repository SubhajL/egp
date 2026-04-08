"""Tests for immediate discover trigger after profile creation.

When a user creates a keyword profile via POST /v1/rules/profiles, the API
should schedule background discover jobs — one per keyword — using the
discover_spawner callable on app.state.  In production this spawns a worker
subprocess; in tests we inject a simple recorder.
"""

from __future__ import annotations

import logging
import subprocess

from fastapi.testclient import TestClient
from sqlalchemy import text

from egp_api.main import _logger, _make_discover_spawner, create_app

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


def test_make_discover_spawner_logs_spawn_failure_with_keyword_context(
    tmp_path, monkeypatch, caplog
):
    def fake_popen(*args, **kwargs):
        raise RuntimeError("worker exited early")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    caplog.set_level(logging.WARNING, logger=_logger.name)
    spawner = _make_discover_spawner("sqlite+pysqlite:///test.sqlite3")

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

    assert captured["timeout"] == 600
    payload = captured["payload"].decode()
    assert '"profile_id": "profile-123"' in payload
