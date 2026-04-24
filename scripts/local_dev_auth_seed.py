"""Local-dev auth utilities for listing accounts, resetting passwords, and seeding an owner."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update

from egp_db.connection import create_shared_engine
from egp_db.repositories.admin_repo import TENANTS_TABLE, create_admin_repository
from egp_db.repositories.auth_repo import (
    USERS_TABLE,
    create_auth_repository,
    hash_password,
)
from egp_db.repositories.notification_repo import create_notification_repository
from egp_shared_types.enums import UserRole

DEFAULT_OWNER_EMAIL = "owner@local-dev.example"
DEFAULT_OWNER_PASSWORD = "DevPassword123!"
DEFAULT_OWNER_NAME = "Local Dev Owner"
DEFAULT_TENANT_NAME = "Local Dev Workspace"
DEFAULT_TENANT_SLUG = "local-dev"


@dataclass(frozen=True, slots=True)
class LoginAccount:
    tenant_id: str
    tenant_slug: str
    email: str
    role: str
    status: str
    email_verified: bool
    mfa_enabled: bool
    user_id: str


def list_login_accounts(*, database_url: str) -> list[LoginAccount]:
    engine = create_shared_engine(database_url)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(
                    TENANTS_TABLE.c.id.label("tenant_id"),
                    TENANTS_TABLE.c.slug.label("tenant_slug"),
                    USERS_TABLE.c.id.label("user_id"),
                    USERS_TABLE.c.email,
                    USERS_TABLE.c.role,
                    USERS_TABLE.c.status,
                    USERS_TABLE.c.email_verified_at,
                    USERS_TABLE.c.mfa_enabled,
                )
                .select_from(
                    USERS_TABLE.join(
                        TENANTS_TABLE,
                        TENANTS_TABLE.c.id == USERS_TABLE.c.tenant_id,
                    )
                )
                .order_by(TENANTS_TABLE.c.slug, USERS_TABLE.c.email)
            )
            .mappings()
            .all()
        )
    return [
        LoginAccount(
            tenant_id=str(row["tenant_id"]),
            tenant_slug=str(row["tenant_slug"]),
            email=str(row["email"]),
            role=str(row["role"]),
            status=str(row["status"]),
            email_verified=row["email_verified_at"] is not None,
            mfa_enabled=bool(row["mfa_enabled"]),
            user_id=str(row["user_id"]),
        )
        for row in rows
    ]


def reset_all_user_passwords(*, database_url: str, password: str) -> list[LoginAccount]:
    engine = create_shared_engine(database_url)
    auth_repository = create_auth_repository(engine=engine)
    accounts = list_login_accounts(database_url=database_url)
    encoded_password = hash_password(password)

    for account in accounts:
        auth_repository.update_password(
            tenant_id=account.tenant_id,
            user_id=account.user_id,
            password_hash=encoded_password,
        )
        auth_repository.set_mfa_enabled(
            tenant_id=account.tenant_id,
            user_id=account.user_id,
            enabled=False,
        )
        auth_repository.set_mfa_secret(
            tenant_id=account.tenant_id,
            user_id=account.user_id,
            secret=None,
        )
        if not account.email_verified:
            auth_repository.mark_email_verified(
                tenant_id=account.tenant_id,
                user_id=account.user_id,
            )
    return list_login_accounts(database_url=database_url)


def ensure_local_dev_owner(
    *,
    database_url: str,
    tenant_name: str = DEFAULT_TENANT_NAME,
    tenant_slug: str = DEFAULT_TENANT_SLUG,
    email: str = DEFAULT_OWNER_EMAIL,
    password: str = DEFAULT_OWNER_PASSWORD,
    full_name: str = DEFAULT_OWNER_NAME,
) -> LoginAccount:
    engine = create_shared_engine(database_url)
    admin_repository = create_admin_repository(engine=engine)
    notification_repository = create_notification_repository(engine=engine)
    auth_repository = create_auth_repository(engine=engine)

    tenant = admin_repository.get_tenant_by_slug(slug=tenant_slug)
    if tenant is None:
        tenant = admin_repository.create_tenant(
            name=tenant_name,
            slug=tenant_slug,
            plan_code="monthly_membership",
            is_active=True,
        )

    existing = auth_repository.find_login_user(tenant_slug=tenant_slug, email=email)
    now = datetime.now(UTC)
    encoded_password = hash_password(password)
    if existing is None:
        created = notification_repository.create_user(
            tenant_id=tenant.id,
            email=email,
            role=UserRole.OWNER,
            status="active",
            full_name=full_name,
            password_hash=encoded_password,
            email_verified_at=now.isoformat(),
        )
        user_id = str(created["id"])
    else:
        user_id = existing.user_id
        with engine.begin() as connection:
            connection.execute(
                update(USERS_TABLE)
                .where(
                    USERS_TABLE.c.id == user_id,
                    USERS_TABLE.c.tenant_id == tenant.id,
                )
                .values(
                    role=UserRole.OWNER.value,
                    status="active",
                    full_name=full_name,
                    password_hash=encoded_password,
                    email_verified_at=now,
                    mfa_enabled=False,
                    mfa_secret=None,
                    updated_at=now,
                )
            )
    refreshed = auth_repository.find_login_user(tenant_slug=tenant_slug, email=email)
    if refreshed is None:
        raise RuntimeError("local dev owner missing after ensure")
    return LoginAccount(
        tenant_id=refreshed.tenant_id,
        tenant_slug=refreshed.tenant_slug,
        email=refreshed.email,
        role=refreshed.role,
        status=refreshed.status,
        email_verified=refreshed.email_verified_at is not None,
        mfa_enabled=refreshed.mfa_enabled,
        user_id=user_id,
    )


def _accounts_as_json(accounts: list[LoginAccount]) -> str:
    return json.dumps(
        [asdict(account) for account in accounts], ensure_ascii=False, indent=2
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-users")
    list_parser.add_argument("--database-url", required=True)

    reset_parser = subparsers.add_parser("reset-passwords")
    reset_parser.add_argument("--database-url", required=True)
    reset_parser.add_argument("--password", required=True)

    owner_parser = subparsers.add_parser("ensure-owner")
    owner_parser.add_argument("--database-url", required=True)
    owner_parser.add_argument("--tenant-name", default=DEFAULT_TENANT_NAME)
    owner_parser.add_argument("--tenant-slug", default=DEFAULT_TENANT_SLUG)
    owner_parser.add_argument("--email", default=DEFAULT_OWNER_EMAIL)
    owner_parser.add_argument("--password", default=DEFAULT_OWNER_PASSWORD)
    owner_parser.add_argument("--full-name", default=DEFAULT_OWNER_NAME)

    args = parser.parse_args()
    if args.command == "list-users":
        print(_accounts_as_json(list_login_accounts(database_url=args.database_url)))
        return 0
    if args.command == "reset-passwords":
        print(
            _accounts_as_json(
                reset_all_user_passwords(
                    database_url=args.database_url,
                    password=args.password,
                )
            )
        )
        return 0
    if args.command == "ensure-owner":
        owner = ensure_local_dev_owner(
            database_url=args.database_url,
            tenant_name=args.tenant_name,
            tenant_slug=args.tenant_slug,
            email=args.email,
            password=args.password,
            full_name=args.full_name,
        )
        print(json.dumps(asdict(owner), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
