"""Tests for self-service tenant registration (POST /v1/auth/register)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from egp_api.main import create_app


def _create_client(tmp_path) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase4-reg.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=True,
            jwt_secret="phase4-reg-secret",
        ),
        raise_server_exceptions=True,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_register_creates_tenant_user_and_session(tmp_path):
    client = _create_client(tmp_path)
    response = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Smart Water Co",
            "email": "owner@smartwater.example",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    # Session payload matches the same shape as /v1/auth/login
    assert data["user"]["email"] == "owner@smartwater.example"
    assert data["user"]["role"] == "owner"
    assert data["user"]["email_verified"] is True
    assert data["tenant"]["slug"] == "smart-water-co"
    assert data["tenant"]["plan_code"] == "free_trial"
    assert data["tenant"]["is_active"] is True
    # Session cookie must be set
    assert client.cookies.get("egp_session") is not None or any(
        "egp_session" in c for c in response.headers.get("set-cookie", "")
    )


def test_register_slug_derived_from_company_name(tmp_path):
    client = _create_client(tmp_path)
    response = client.post(
        "/v1/auth/register",
        json={
            "company_name": "  บริษัท ABC  ",  # Thai + leading/trailing spaces
            "email": "ceo@abc.example",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    # Slug must be non-empty and URL-safe (lower alphanumeric + hyphens)
    slug = data["tenant"]["slug"]
    assert slug, "slug must not be empty"
    import re

    assert re.fullmatch(r"[a-z0-9][a-z0-9\-]*", slug), f"invalid slug: {slug!r}"


def test_register_can_then_login(tmp_path):
    client = _create_client(tmp_path)
    # Register
    reg = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Login Test Corp",
            "email": "user@logintest.example",
            "password": "secure password 123",
        },
    )
    assert reg.status_code == 200, reg.text
    slug = reg.json()["tenant"]["slug"]

    # Logout first to clear the cookie
    client.post("/v1/auth/logout")

    # Login with same credentials
    login = client.post(
        "/v1/auth/login",
        json={
            "email": "user@logintest.example",
            "password": "secure password 123",
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["user"]["email"] == "user@logintest.example"
    assert login.json()["tenant"]["slug"] == slug


# ---------------------------------------------------------------------------
# Duplicate email guard
# ---------------------------------------------------------------------------


def test_register_duplicate_email_rejected(tmp_path):
    client = _create_client(tmp_path)
    payload = {
        "company_name": "Dup Co",
        "email": "dup@dup.example",
        "password": "correct horse battery staple",
    }
    first = client.post("/v1/auth/register", json=payload)
    assert first.status_code == 200, first.text

    # Second registration with same email (different company name)
    second = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Another Co",
            "email": "dup@dup.example",  # same email
            "password": "correct horse battery staple",
        },
    )
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == "account already exists for this email; please sign in"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_register_missing_fields_returns_422(tmp_path):
    client = _create_client(tmp_path)
    response = client.post(
        "/v1/auth/register",
        json={"company_name": "X"},  # missing email and password
    )
    assert response.status_code == 422


def test_register_short_password_rejected(tmp_path):
    client = _create_client(tmp_path)
    response = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Short Pass Co",
            "email": "x@x.example",
            "password": "short",  # < 8 chars
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Slug collision de-duplication
# ---------------------------------------------------------------------------


def test_register_slug_collision_deduplicates(tmp_path):
    client = _create_client(tmp_path)
    # First registration gets slug "acme"
    first = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Acme",
            "email": "first@acme.example",
            "password": "correct horse battery staple",
        },
    )
    assert first.status_code == 200, first.text

    # Second registration with same company name gets a different slug
    second = client.post(
        "/v1/auth/register",
        json={
            "company_name": "Acme",
            "email": "second@acme.example",
            "password": "correct horse battery staple",
        },
    )
    assert second.status_code == 200, second.text
    assert first.json()["tenant"]["slug"] != second.json()["tenant"]["slug"]
