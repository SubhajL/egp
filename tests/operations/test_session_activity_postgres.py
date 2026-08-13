"""Real-PostgreSQL contracts for conditional session activity maintenance."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
import os
import threading
from uuid import uuid4

import pytest
from psycopg import connect

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations
from egp_db.repositories.auth_repo import SqlAuthRepository, hash_password


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def postgres_cluster() -> Iterator[TempPostgresCluster]:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries not available")
    with TempPostgresCluster() as cluster:
        yield cluster


@pytest.fixture
def database_url(postgres_cluster: TempPostgresCluster) -> Iterator[str]:
    database_name = f"session_activity_{uuid4().hex[:12]}"
    postgres_cluster.create_database(database_name)
    url = postgres_cluster.database_url(database_name)
    apply_migrations(
        database_url=url,
        migrations_dir=REPO_ROOT / "packages/db/src/migrations",
    )
    try:
        yield url
    finally:
        postgres_cluster.drop_database(database_name)


@pytest.fixture
def ci_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if os.environ.get("EGP_CI_POSTGRES_CONTRACT") != "1" or not url:
        pytest.skip("required CI PostgreSQL contract not enabled")
    return url


def _seed_session(database_url: str) -> tuple[str, str, str]:
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    repository = SqlAuthRepository(database_url=database_url)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id,name,slug,plan_code,is_active) "
            "VALUES (%s,%s,%s,'free',TRUE)",
            (tenant_id, "Activity Tenant", f"activity-{tenant_id[:8]}"),
        )
        cursor.execute(
            "INSERT INTO users "
            "(id,tenant_id,email,full_name,role,status,password_hash) "
            "VALUES (%s,%s,%s,'Activity User','viewer','active',%s)",
            (
                user_id,
                tenant_id,
                f"{user_id[:8]}@example.com",
                hash_password("session-activity-password"),
            ),
        )
        connection.commit()
    token = repository.create_session(
        tenant_id=tenant_id,
        user_id=user_id,
        expires_in_seconds=3600,
    )
    session = repository.get_authenticated_session(session_token=token)
    assert session is not None
    return tenant_id, session.session_id, token


def _last_seen(database_url: str, session_id: str) -> datetime:
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT last_seen_at FROM user_sessions WHERE id=%s",
            (session_id,),
        )
        value = cursor.fetchone()[0]
    return value


def test_activity_touch_is_atomic_monotonic_and_expiry_safe(database_url: str) -> None:
    tenant_id, session_id, _ = _seed_session(database_url)
    old_activity = datetime.now(UTC) - timedelta(hours=1)
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE user_sessions SET last_seen_at=%s, updated_at=%s WHERE id=%s",
            (old_activity, old_activity, session_id),
        )
        connection.commit()

    repositories = [
        SqlAuthRepository(database_url=database_url),
        SqlAuthRepository(database_url=database_url),
    ]
    observed_at = datetime.now(UTC)
    barrier = threading.Barrier(2)
    outcomes: list[int] = []
    errors: list[Exception] = []

    def worker(repository: SqlAuthRepository) -> None:
        try:
            barrier.wait(timeout=2)
            outcomes.append(
                repository.touch_session_activity(
                    tenant_id=tenant_id,
                    session_ids=(session_id,),
                    observed_at=observed_at,
                    minimum_interval_seconds=300,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(repository,)) for repository in repositories]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == [0, 1]
    assert _last_seen(database_url, session_id) == observed_at

    delayed = repositories[0].touch_session_activity(
        tenant_id=tenant_id,
        session_ids=(session_id,),
        observed_at=observed_at - timedelta(minutes=10),
        minimum_interval_seconds=300,
    )
    assert delayed == 0
    assert _last_seen(database_url, session_id) == observed_at

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE user_sessions SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' "
            "WHERE id=%s",
            (session_id,),
        )
        connection.commit()
    expired = repositories[1].touch_session_activity(
        tenant_id=tenant_id,
        session_ids=(session_id,),
        observed_at=observed_at + timedelta(minutes=10),
        minimum_interval_seconds=300,
    )
    assert expired == 0
    assert _last_seen(database_url, session_id) == observed_at


def test_ci_postgres_activity_touch_contract(ci_database_url: str) -> None:
    test_activity_touch_is_atomic_monotonic_and_expiry_safe(ci_database_url)
