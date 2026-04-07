from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import text

from egp_api.main import create_app

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
JWT_SECRET = "phase4-auth-secret"
PASSWORD = "correct horse battery staple"
PASSWORD_HASH = (
    "pbkdf2_sha256$390000$testsalt12345678$nGS115avKMF_Pqj0rdAgkGSpzD5XoukfnqsHaEBcVM0"
)


def _create_client(
    tmp_path, *, auth_required: bool = True, email_sender=None
) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase4-auth.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=auth_required,
            jwt_secret=JWT_SECRET if auth_required else None,
            notification_email_sender=email_sender,
        )
    )


def _seed_tenant(
    client: TestClient,
    *,
    tenant_id: str = TENANT_ID,
    name: str = "Acme Intelligence",
    slug: str = "acme-intelligence",
) -> None:
    now = datetime.now(UTC).isoformat()
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (
                    id,
                    name,
                    slug,
                    plan_code,
                    is_active,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :name,
                    :slug,
                    'monthly_membership',
                    1,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": tenant_id,
                "name": name,
                "slug": slug,
                "created_at": now,
                "updated_at": now,
            },
        )


def _seed_user(
    client: TestClient,
    *,
    user_id: str = "33333333-3333-3333-3333-333333333333",
    tenant_id: str = TENANT_ID,
    email: str = "owner@acme.example",
    role: str = "owner",
    status: str = "active",
    password_hash: str | None = PASSWORD_HASH,
) -> str:
    now = datetime.now(UTC).isoformat()
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (
                    id,
                    tenant_id,
                    email,
                    full_name,
                    role,
                    status,
                    password_hash,
                    email_verified_at,
                    mfa_secret,
                    mfa_enabled,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :email,
                    'Owner User',
                    :role,
                    :status,
                    :password_hash,
                    NULL,
                    NULL,
                    0,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "id": user_id,
                "tenant_id": tenant_id,
                "email": email,
                "role": role,
                "status": status,
                "password_hash": password_hash,
                "created_at": now,
                "updated_at": now,
            },
        )
    return user_id


def _extract_token(messages: list[dict[str, str]]) -> str:
    assert messages, "expected at least one sent email"
    body = messages[-1]["body"]
    match = re.search(r"token=([A-Za-z0-9._~\-]+)", body)
    assert match, body
    return match.group(1)


def _totp_code(secret: str, *, now: int | None = None) -> str:
    timestamp = int(time.time() if now is None else now)
    counter = timestamp // 30
    padded = secret.strip().upper()
    key = base64.b32decode(f"{padded}{'=' * (-len(padded) % 8)}", casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def _bearer_headers(
    *, tenant_id: str = TENANT_ID, role: str = "owner"
) -> dict[str, str]:
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


def test_login_requires_valid_tenant_slug_email_and_password(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client)

    response = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "owner@acme.example",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401


def test_login_sets_http_only_session_cookie_and_me_reads_session(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client)

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "owner@acme.example",
            "password": PASSWORD,
        },
    )

    assert login.status_code == 200
    assert "set-cookie" in login.headers
    assert "HttpOnly" in login.headers["set-cookie"]

    me = client.get("/v1/me")

    assert me.status_code == 200
    assert me.json()["user"]["email"] == "owner@acme.example"
    assert me.json()["tenant"]["id"] == TENANT_ID
    assert me.json()["user"]["role"] == "owner"


def test_login_accepts_email_and_password_without_tenant_slug(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client)

    login = client.post(
        "/v1/auth/login",
        json={
            "email": "owner@acme.example",
            "password": PASSWORD,
        },
    )

    assert login.status_code == 200
    assert login.json()["user"]["email"] == "owner@acme.example"


def test_login_without_tenant_slug_requires_workspace_for_duplicate_email_across_tenants(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="other-tenant",
    )
    _seed_user(client, email="shared@example.com")
    _seed_user(
        client,
        user_id="44444444-4444-4444-4444-444444444444",
        tenant_id=OTHER_TENANT_ID,
        email="shared@example.com",
    )

    login = client.post(
        "/v1/auth/login",
        json={
            "email": "shared@example.com",
            "password": PASSWORD,
        },
    )

    assert login.status_code == 409
    assert login.json() == {
        "detail": "workspace slug required",
        "code": "workspace_slug_required",
    }


def test_register_duplicate_email_returns_structured_error_code(tmp_path) -> None:
    client = _create_client(tmp_path)

    first = client.post(
        "/v1/auth/register",
        json={
            "company_name": "First Company",
            "email": "duplicate@example.com",
            "password": PASSWORD,
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Second Company",
            "email": "duplicate@example.com",
            "password": PASSWORD,
        },
    )

    assert second.status_code == 409
    assert second.json() == {
        "detail": "account already exists for this email; please sign in",
        "code": "account_already_exists",
    }


def test_register_short_password_validation_returns_structured_field_code(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)

    response = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Short Password Co",
            "email": "owner@example.com",
            "password": "short",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_password_too_short"
    assert isinstance(body["detail"], list)


def test_enable_mfa_invalid_code_returns_structured_error_code(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client, email="mfa-invalid@example.com")

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "mfa-invalid@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200

    setup = client.post("/v1/auth/mfa/setup")
    assert setup.status_code == 200

    response = client.post("/v1/auth/mfa/enable", json={"code": "000000"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": "invalid mfa code",
        "code": "invalid_mfa_code",
    }


def test_login_without_tenant_slug_succeeds_when_only_one_duplicate_email_password_matches(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="other-tenant",
    )
    _seed_user(client, email="shared@example.com")
    _seed_user(
        client,
        user_id="44444444-4444-4444-4444-444444444444",
        tenant_id=OTHER_TENANT_ID,
        email="shared@example.com",
        password_hash=(
            "pbkdf2_sha256$390000$othersalt12345678$"
            "L3bqR3b5rj5pUsQ4K3xK9mFYJx2n2J6s5w7j2dJ6M6I"
        ),
    )

    login = client.post(
        "/v1/auth/login",
        json={
            "email": "shared@example.com",
            "password": PASSWORD,
        },
    )

    assert login.status_code == 200
    assert login.json()["tenant"]["id"] == TENANT_ID


def test_login_without_tenant_slug_requires_workspace_when_duplicate_accounts_share_password(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="other-tenant",
    )
    _seed_user(client, email="shared@example.com")
    _seed_user(
        client,
        user_id="44444444-4444-4444-4444-444444444444",
        tenant_id=OTHER_TENANT_ID,
        email="shared@example.com",
    )

    login = client.post(
        "/v1/auth/login",
        json={
            "email": "shared@example.com",
            "password": PASSWORD,
        },
    )

    assert login.status_code == 409
    assert login.json() == {
        "detail": "workspace slug required",
        "code": "workspace_slug_required",
    }


def test_login_with_duplicate_email_and_wrong_password_stays_generic(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="other-tenant",
    )
    _seed_user(client, email="shared@example.com")
    _seed_user(
        client,
        user_id="44444444-4444-4444-4444-444444444444",
        tenant_id=OTHER_TENANT_ID,
        email="shared@example.com",
    )

    login = client.post(
        "/v1/auth/login",
        json={
            "email": "shared@example.com",
            "password": "wrong-password",
        },
    )

    assert login.status_code == 401
    assert login.json() == {
        "detail": "invalid credentials",
        "code": "invalid_credentials",
    }


def test_me_preflight_returns_cors_headers_for_localhost_dev_origin(tmp_path) -> None:
    client = _create_client(tmp_path)

    response = client.options(
        "/v1/me",
        headers={
            "Origin": "http://localhost:3002",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3002"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_me_unauthorized_response_includes_cors_headers_for_localhost_dev_origin(
    tmp_path,
) -> None:
    client = _create_client(tmp_path)

    response = client.get(
        "/v1/me",
        headers={"Origin": "http://localhost:3002"},
    )

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://localhost:3002"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_logout_revokes_cookie_session(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client)

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "owner@acme.example",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200

    logout = client.post("/v1/auth/logout")
    me = client.get("/v1/me")

    assert logout.status_code == 204
    assert me.status_code == 401


def test_bearer_tokens_remain_supported_for_me(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)

    response = client.get("/v1/me", headers=_bearer_headers())

    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == TENANT_ID
    assert response.json()["user"]["subject"] == "user-123"


def test_passwordless_or_suspended_user_cannot_login(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_tenant(
        client,
        tenant_id=OTHER_TENANT_ID,
        name="Other Tenant",
        slug="other-tenant",
    )
    _seed_user(client, email="suspended@acme.example", status="suspended")
    _seed_user(
        client,
        user_id="44444444-4444-4444-4444-444444444444",
        tenant_id=OTHER_TENANT_ID,
        email="nopassword@other.example",
        password_hash=None,
    )

    suspended = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "suspended@acme.example",
            "password": PASSWORD,
        },
    )

    assert suspended.status_code in {401, 403}


def test_accept_invite_sets_password_marks_email_verified_and_creates_session(
    tmp_path,
) -> None:
    sent: list[dict[str, str]] = []
    client = _create_client(
        tmp_path,
        email_sender=lambda *, to, subject, body: sent.append(
            {"to": to, "subject": subject, "body": body}
        ),
    )
    _seed_tenant(client)
    created = client.app.state.notification_repository.create_user(
        tenant_id=TENANT_ID,
        email="invitee@example.com",
        role="viewer",
        full_name="Invited User",
    )

    invited = client.post(
        f"/v1/admin/users/{created['id']}/invite",
        headers=_bearer_headers(role="owner"),
    )
    assert invited.status_code == 202

    accepted = client.post(
        "/v1/auth/invite/accept",
        json={
            "token": _extract_token(sent),
            "password": "invite accepted password",
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["user"]["email"] == "invitee@example.com"
    assert accepted.json()["user"]["email_verified"] is True
    me = client.get("/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "invitee@example.com"


def test_forgot_password_returns_generic_success_for_unknown_email(tmp_path) -> None:
    sent: list[dict[str, str]] = []
    client = _create_client(
        tmp_path,
        email_sender=lambda *, to, subject, body: sent.append(
            {"to": to, "subject": subject, "body": body}
        ),
    )
    _seed_tenant(client)

    response = client.post(
        "/v1/auth/password/forgot",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "missing@example.com",
        },
    )

    assert response.status_code == 202
    assert sent == []


def test_reset_password_consumes_token_and_replaces_old_password(tmp_path) -> None:
    sent: list[dict[str, str]] = []
    client = _create_client(
        tmp_path,
        email_sender=lambda *, to, subject, body: sent.append(
            {"to": to, "subject": subject, "body": body}
        ),
    )
    _seed_tenant(client)
    _seed_user(client, email="resetme@example.com")

    forgot = client.post(
        "/v1/auth/password/forgot",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "resetme@example.com",
        },
    )
    assert forgot.status_code == 202

    reset = client.post(
        "/v1/auth/password/reset",
        json={
            "token": _extract_token(sent),
            "password": "a brand new password",
        },
    )
    assert reset.status_code == 200

    old_login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "resetme@example.com",
            "password": PASSWORD,
        },
    )
    new_login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "resetme@example.com",
            "password": "a brand new password",
        },
    )

    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_send_and_consume_email_verification_token(tmp_path) -> None:
    sent: list[dict[str, str]] = []
    client = _create_client(
        tmp_path,
        email_sender=lambda *, to, subject, body: sent.append(
            {"to": to, "subject": subject, "body": body}
        ),
    )
    _seed_tenant(client)
    _seed_user(client, email="verifyme@example.com")

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "verifyme@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200

    requested = client.post("/v1/auth/email/verification/send")
    assert requested.status_code == 202

    verified = client.post(
        "/v1/auth/email/verify",
        json={"token": _extract_token(sent)},
    )

    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True
    me = client.get("/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email_verified"] is True


def test_mfa_setup_enable_and_login_require_code(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client, email="mfa@example.com")

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "mfa@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200

    setup = client.post("/v1/auth/mfa/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    code = _totp_code(secret)

    enabled = client.post("/v1/auth/mfa/enable", json={"code": code})
    assert enabled.status_code == 200
    assert enabled.json()["mfa_enabled"] is True

    client.post("/v1/auth/logout")

    without_code = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "mfa@example.com",
            "password": PASSWORD,
        },
    )
    bad_code = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "mfa@example.com",
            "password": PASSWORD,
            "mfa_code": "000000",
        },
    )
    with_code = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "mfa@example.com",
            "password": PASSWORD,
            "mfa_code": _totp_code(secret),
        },
    )

    assert without_code.status_code in {400, 401}
    assert bad_code.status_code in {400, 401}
    assert with_code.status_code == 200
    assert with_code.json()["user"]["mfa_enabled"] is True


def test_mfa_disable_removes_login_requirement(tmp_path) -> None:
    client = _create_client(tmp_path)
    _seed_tenant(client)
    _seed_user(client, email="disablemfa@example.com")

    login = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "disablemfa@example.com",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200

    setup = client.post("/v1/auth/mfa/setup")
    secret = setup.json()["secret"]
    enable = client.post("/v1/auth/mfa/enable", json={"code": _totp_code(secret)})
    assert enable.status_code == 200

    disabled = client.post("/v1/auth/mfa/disable", json={"code": _totp_code(secret)})
    assert disabled.status_code == 200
    assert disabled.json()["mfa_enabled"] is False

    client.post("/v1/auth/logout")
    relogin = client.post(
        "/v1/auth/login",
        json={
            "tenant_slug": "acme-intelligence",
            "email": "disablemfa@example.com",
            "password": PASSWORD,
        },
    )
    assert relogin.status_code == 200
