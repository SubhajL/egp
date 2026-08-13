from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from egp_api.services.session_auth_runtime import (
    SessionAuthenticationUnavailableError,
)
from tests.support.app_factory import create_test_app
from tests.phase4.test_auth_api import (
    PASSWORD,
    TENANT_ID,
    _create_client,
    _seed_tenant,
    _seed_user,
)


def _login(client: TestClient) -> str:
    response = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "owner@acme.example",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    token = client.cookies.get("egp_session")
    assert token
    return token


def _session_times(client: TestClient) -> tuple[str, str]:
    with client.app.state.db_engine.connect() as connection:
        row = connection.execute(
            text("SELECT last_seen_at, updated_at FROM user_sessions")
        ).one()
    return str(row[0]), str(row[1])


def test_session_runtime_is_owned_by_application_lifespan(tmp_path) -> None:
    app = create_test_app(
        artifact_root=tmp_path,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'lifespan.sqlite3'}",
        auth_required=False,
    )

    assert app.state.session_auth_runtime._state == "created"
    with TestClient(app):
        assert app.state.session_auth_runtime._state == "running"
    assert app.state.session_auth_runtime._state == "stopped"

    with pytest.raises(RuntimeError, match="cannot be restarted"):
        asyncio.run(app.state.session_auth_runtime.start())


def test_repository_session_lookup_is_read_only(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client)
    token = _login(client)
    before = _session_times(client)

    authenticated = client.app.state.auth_repository.get_authenticated_session(
        session_token=token
    )

    assert authenticated is not None
    assert authenticated.tenant_id == TENANT_ID
    assert _session_times(client) == before


def test_conditional_activity_touch_coalesces_and_cannot_touch_revoked_session(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client)
    token = _login(client)
    session = client.app.state.auth_repository.get_authenticated_session(
        session_token=token
    )
    assert session is not None
    observed_at = datetime.now(UTC) + timedelta(minutes=10)

    first = client.app.state.auth_repository.touch_session_activity(
        tenant_id=TENANT_ID,
        session_ids=(session.session_id,),
        observed_at=observed_at,
        minimum_interval_seconds=300,
    )
    second = client.app.state.auth_repository.touch_session_activity(
        tenant_id=TENANT_ID,
        session_ids=(session.session_id,),
        observed_at=observed_at,
        minimum_interval_seconds=300,
    )
    client.app.state.auth_repository.revoke_session(session_token=token)
    revoked = client.app.state.auth_repository.touch_session_activity(
        tenant_id=TENANT_ID,
        session_ids=(session.session_id,),
        observed_at=observed_at + timedelta(minutes=10),
        minimum_interval_seconds=300,
    )

    assert (first, second, revoked) == (1, 0, 0)


def test_session_database_unavailability_returns_generic_503_with_cors(tmp_path) -> None:
    client = _create_client(tmp_path)

    async def unavailable(token: str):
        del token
        raise SessionAuthenticationUnavailableError("sensitive database detail")

    client.app.state.session_auth_runtime.authenticate = unavailable
    client.cookies.set("egp_session", "opaque-cookie")

    response = client.get(
        "/v1/me",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "session authentication temporarily unavailable"
    }
    assert "sensitive" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_invalid_bearer_with_cookie_never_invokes_session_runtime(tmp_path) -> None:
    client = _create_client(tmp_path)
    session_calls: list[str] = []

    async def session_spy(token: str):
        session_calls.append(token)
        return None

    client.app.state.session_auth_runtime.authenticate = session_spy
    client.cookies.set("egp_session", "valid-looking-cookie")

    response = client.get(
        "/v1/me",
        headers={"Authorization": "Bearer malformed"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid bearer token"}
    assert session_calls == []
