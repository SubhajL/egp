from __future__ import annotations

from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_db.repositories.auth_repo import (
    create_auth_repository,
    hash_password,
    verify_password,
)
from egp_db.repositories.notification_repo import create_notification_repository
from egp_shared_types.enums import UserRole
from scripts.local_dev_auth_seed import (
    DEFAULT_OWNER_EMAIL,
    DEFAULT_OWNER_PASSWORD,
    DEFAULT_TENANT_SLUG,
    ensure_local_dev_owner,
    list_login_accounts,
    reset_all_user_passwords,
)


def _create_client(tmp_path) -> tuple[TestClient, str]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase4-local-dev-auth.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=True,
            jwt_secret="phase4-local-dev-auth-secret",
        ),
        raise_server_exceptions=True,
    )
    return client, database_url


def test_ensure_local_dev_owner_creates_owner_and_is_idempotent(tmp_path) -> None:
    client, database_url = _create_client(tmp_path)
    try:
        first = ensure_local_dev_owner(database_url=database_url)
        second = ensure_local_dev_owner(database_url=database_url)

        accounts = list_login_accounts(database_url=database_url)
        owner_accounts = [
            account for account in accounts if account.email == DEFAULT_OWNER_EMAIL
        ]

        assert first.tenant_slug == DEFAULT_TENANT_SLUG
        assert second.email == DEFAULT_OWNER_EMAIL
        assert len(owner_accounts) == 1
        assert owner_accounts[0].role == UserRole.OWNER.value

        auth_repository = create_auth_repository(database_url=database_url)
        owner_user = auth_repository.find_login_user(
            tenant_slug=DEFAULT_TENANT_SLUG,
            email=DEFAULT_OWNER_EMAIL,
        )
        assert owner_user is not None
        assert verify_password(DEFAULT_OWNER_PASSWORD, owner_user.password_hash)
    finally:
        client.close()


def test_reset_all_user_passwords_updates_existing_accounts(tmp_path) -> None:
    client, database_url = _create_client(tmp_path)
    try:
        local_owner = ensure_local_dev_owner(database_url=database_url)
        notification_repository = create_notification_repository(
            database_url=database_url
        )
        created = notification_repository.create_user(
            tenant_id=local_owner.tenant_id,
            email="analyst@example.com",
            role=UserRole.ANALYST,
            status="active",
            full_name="Example Analyst",
            password_hash=hash_password("OriginalPassword123!"),
            email_verified_at=None,
        )
        auth_repository = create_auth_repository(database_url=database_url)
        auth_repository.set_mfa_secret(
            tenant_id=local_owner.tenant_id,
            user_id=str(created["id"]),
            secret="JBSWY3DPEHPK3PXP",
        )
        auth_repository.set_mfa_enabled(
            tenant_id=local_owner.tenant_id,
            user_id=str(created["id"]),
            enabled=True,
        )

        updated_accounts = reset_all_user_passwords(
            database_url=database_url,
            password="ResetPassword123!",
        )

        assert {account.email for account in updated_accounts} >= {
            DEFAULT_OWNER_EMAIL,
            "analyst@example.com",
        }

        owner_user = auth_repository.find_login_user(
            tenant_slug=DEFAULT_TENANT_SLUG,
            email=DEFAULT_OWNER_EMAIL,
        )
        analyst_user = auth_repository.find_login_user(
            tenant_slug=DEFAULT_TENANT_SLUG,
            email="analyst@example.com",
        )
        assert owner_user is not None
        assert analyst_user is not None
        assert verify_password("ResetPassword123!", owner_user.password_hash)
        assert verify_password("ResetPassword123!", analyst_user.password_hash)
        assert owner_user.email_verified_at is not None
        assert analyst_user.email_verified_at is not None
        assert owner_user.mfa_enabled is False
        assert analyst_user.mfa_enabled is False
    finally:
        client.close()
