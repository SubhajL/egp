"""Tests for immediate discover trigger after profile creation.

When a user creates a keyword profile via POST /v1/rules/profiles, the API
should schedule background discover jobs — one per keyword — using the
discover_spawner callable on app.state.  In production this spawns a worker
subprocess; in tests we inject a simple recorder.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from egp_api.main import create_app

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
    """POST /v1/rules/profiles should call discover_spawner once per keyword."""
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
