from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os

from sqlalchemy import text

from egp_db.connection import create_shared_engine
from egp_db.repositories.auth_repo import hash_password


DEFAULT_DATABASE_URL = "postgresql+psycopg://egp:egp_dev@localhost:5432/egp"
TENANT_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "33333333-3333-3333-3333-333333333333"
TENANT_NAME = "Acme Intelligence"
TENANT_SLUG = "acme-intelligence"
EMAIL = "owner@acme.example"
PASSWORD = "correct horse battery staple"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    return parser


def seed_manual_test_user(*, database_url: str) -> None:
    now = datetime.now(UTC)
    engine = create_shared_engine(database_url)
    password_hash = hash_password(PASSWORD)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:id, :name, :slug, 'monthly_membership', TRUE, :created_at, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    slug = EXCLUDED.slug,
                    plan_code = EXCLUDED.plan_code,
                    is_active = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "id": TENANT_ID,
                "name": TENANT_NAME,
                "slug": TENANT_SLUG,
                "created_at": now,
                "updated_at": now,
            },
        )
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
                    'owner',
                    'active',
                    :password_hash,
                    :email_verified_at,
                    NULL,
                    FALSE,
                    :created_at,
                    :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    email = EXCLUDED.email,
                    full_name = EXCLUDED.full_name,
                    role = EXCLUDED.role,
                    status = EXCLUDED.status,
                    password_hash = EXCLUDED.password_hash,
                    email_verified_at = EXCLUDED.email_verified_at,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "id": USER_ID,
                "tenant_id": TENANT_ID,
                "email": EMAIL,
                "password_hash": password_hash,
                "email_verified_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
    print("Seeded manual test tenant/user")
    print(f"database_url={database_url}")
    print(f"tenant_slug={TENANT_SLUG}")
    print(f"email={EMAIL}")
    print(f"password={PASSWORD}")


def main() -> None:
    args = _build_parser().parse_args()
    seed_manual_test_user(database_url=args.database_url)


if __name__ == "__main__":
    main()
