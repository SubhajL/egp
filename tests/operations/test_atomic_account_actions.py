"""Real-PostgreSQL contract tests for atomic one-time account actions."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from uuid import uuid4

import pytest
from psycopg import connect

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations
from egp_db.repositories.auth_repo import (
    AccountActionTargetInactiveError,
    SqlAuthRepository,
    hash_password,
    verify_password,
)


REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
OLD_PASSWORD = "old-password-for-contract"
NEW_PASSWORD = "new-password-for-contract"
PURPOSES = ("invite", "password_reset", "email_verification")


@pytest.fixture(scope="module")
def postgres_cluster() -> Iterator[TempPostgresCluster]:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries not available")
    with TempPostgresCluster() as cluster:
        yield cluster


@pytest.fixture
def database_url(postgres_cluster: TempPostgresCluster) -> Iterator[str]:
    database_name = f"atomic_auth_{uuid4().hex[:12]}"
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


def _seed_target(
    database_url: str,
    *,
    tenant_active: bool = True,
    user_status: str = "active",
) -> tuple[str, str]:
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id,name,slug,plan_code,is_active) "
            "VALUES (%s,%s,%s,'free',%s)",
            (tenant_id, "Atomic Tenant", f"atomic-{tenant_id[:8]}", tenant_active),
        )
        cursor.execute(
            "INSERT INTO users "
            "(id,tenant_id,email,full_name,role,status,password_hash) "
            "VALUES (%s,%s,%s,'Atomic User','viewer',%s,%s)",
            (
                user_id,
                tenant_id,
                f"{user_id[:8]}@example.com",
                user_status,
                hash_password(OLD_PASSWORD),
            ),
        )
        connection.commit()
    return tenant_id, user_id


def _issue_token(
    repository: SqlAuthRepository,
    *,
    tenant_id: str,
    user_id: str,
    purpose: str,
) -> str:
    return repository.create_account_action_token(
        tenant_id=tenant_id,
        user_id=user_id,
        purpose=purpose,
        delivery_email="atomic@example.com",
        expires_in_seconds=3600,
    )


def _seed_session(
    repository: SqlAuthRepository, *, tenant_id: str, user_id: str
) -> str:
    return repository.create_session(
        tenant_id=tenant_id,
        user_id=user_id,
        expires_in_seconds=3600,
    )


def _invoke(repository: SqlAuthRepository, purpose: str, token: str):
    if purpose == "invite":
        return repository.accept_invite_atomically(
            token=token,
            password_hash_factory=lambda: hash_password(NEW_PASSWORD),
            session_expires_in_seconds=3600,
        )
    if purpose == "password_reset":
        return repository.reset_password_atomically(
            token=token,
            password_hash_factory=lambda: hash_password(NEW_PASSWORD),
        )
    return repository.verify_email_atomically(token=token)


def _state(database_url: str, *, token: str, user_id: str) -> dict[str, object]:
    from egp_db.repositories.auth_repo import _hash_opaque_token

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT consumed_at FROM account_action_tokens WHERE token_hash=%s",
            (_hash_opaque_token(token),),
        )
        consumed_at = cursor.fetchone()[0]
        cursor.execute(
            "SELECT password_hash,email_verified_at FROM users WHERE id=%s",
            (user_id,),
        )
        password_hash, email_verified_at = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*),COUNT(*) FILTER (WHERE revoked_at IS NOT NULL) "
            "FROM user_sessions WHERE user_id=%s",
            (user_id,),
        )
        session_count, revoked_count = cursor.fetchone()
    return {
        "consumed_at": consumed_at,
        "password_hash": password_hash,
        "email_verified_at": email_verified_at,
        "session_count": int(session_count),
        "revoked_count": int(revoked_count),
    }


@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_account_action_has_exactly_one_postgres_winner(
    database_url: str, purpose: str
) -> None:
    repository = SqlAuthRepository(database_url=database_url)
    tenant_id, user_id = _seed_target(database_url)
    token = _issue_token(
        repository, tenant_id=tenant_id, user_id=user_id, purpose=purpose
    )
    if purpose == "password_reset":
        _seed_session(repository, tenant_id=tenant_id, user_id=user_id)

    barrier = threading.Barrier(2)
    outcomes: list[object] = []
    errors: list[Exception] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=2)
            outcomes.append(_invoke(repository, purpose, token))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    assert len(outcomes) == 2
    assert sum(bool(outcome) for outcome in outcomes) == 1
    state = _state(database_url, token=token, user_id=user_id)
    assert state["consumed_at"] is not None
    if purpose == "invite":
        assert state["session_count"] == 1
        assert state["email_verified_at"] is not None
        assert verify_password(NEW_PASSWORD, state["password_hash"])
    elif purpose == "password_reset":
        assert state["revoked_count"] == 1
        assert verify_password(NEW_PASSWORD, state["password_hash"])
    else:
        assert state["email_verified_at"] is not None
        assert verify_password(OLD_PASSWORD, state["password_hash"])


@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_account_action_rejects_wrong_purpose_expiry_and_replay(
    database_url: str, purpose: str
) -> None:
    repository = SqlAuthRepository(database_url=database_url)
    tenant_id, user_id = _seed_target(database_url)
    wrong_purpose = next(candidate for candidate in PURPOSES if candidate != purpose)
    wrong_token = _issue_token(
        repository,
        tenant_id=tenant_id,
        user_id=user_id,
        purpose=wrong_purpose,
    )
    before_wrong = _state(database_url, token=wrong_token, user_id=user_id)
    assert not _invoke(repository, purpose, wrong_token)
    assert _state(database_url, token=wrong_token, user_id=user_id) == before_wrong
    assert _invoke(repository, wrong_purpose, wrong_token)

    token = _issue_token(
        repository, tenant_id=tenant_id, user_id=user_id, purpose=purpose
    )
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_action_tokens SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' "
            "WHERE token_hash=(SELECT token_hash FROM account_action_tokens "
            "WHERE user_id=%s AND purpose=%s ORDER BY created_at DESC LIMIT 1)",
            (user_id, purpose),
        )
        connection.commit()
    before_expired = _state(database_url, token=token, user_id=user_id)
    assert not _invoke(repository, purpose, token)
    assert _state(database_url, token=token, user_id=user_id) == before_expired

    live_token = _issue_token(
        repository, tenant_id=tenant_id, user_id=user_id, purpose=purpose
    )
    assert _invoke(repository, purpose, live_token)
    after_first = _state(database_url, token=live_token, user_id=user_id)
    assert not _invoke(repository, purpose, live_token)
    assert _state(database_url, token=live_token, user_id=user_id) == after_first


@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_account_action_rejects_tenant_user_mismatch(
    database_url: str, purpose: str
) -> None:
    repository = SqlAuthRepository(database_url=database_url)
    tenant_a, user_a = _seed_target(database_url)
    tenant_b, user_b = _seed_target(database_url)
    token = _issue_token(
        repository, tenant_id=tenant_a, user_id=user_a, purpose=purpose
    )
    if purpose == "password_reset":
        _seed_session(repository, tenant_id=tenant_a, user_id=user_a)
        _seed_session(repository, tenant_id=tenant_b, user_id=user_b)
    from egp_db.repositories.auth_repo import _hash_opaque_token

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_action_tokens SET user_id=%s WHERE token_hash=%s",
            (user_b, _hash_opaque_token(token)),
        )
        connection.commit()

    before_user_a = _state(database_url, token=token, user_id=user_a)
    before_user_b = _state(database_url, token=token, user_id=user_b)
    assert not _invoke(repository, purpose, token)
    assert _state(database_url, token=token, user_id=user_a) == before_user_a
    assert _state(database_url, token=token, user_id=user_b) == before_user_b


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize(
    ("tenant_active", "user_status"),
    ((False, "active"), (True, "suspended"), (True, "deactivated")),
)
def test_each_account_action_rejects_inactive_target_without_consuming(
    database_url: str,
    purpose: str,
    tenant_active: bool,
    user_status: str,
) -> None:
    repository = SqlAuthRepository(database_url=database_url)
    tenant_id, user_id = _seed_target(
        database_url,
        tenant_active=tenant_active,
        user_status=user_status,
    )
    token = _issue_token(
        repository, tenant_id=tenant_id, user_id=user_id, purpose=purpose
    )
    before = _state(database_url, token=token, user_id=user_id)

    with pytest.raises(AccountActionTargetInactiveError):
        _invoke(repository, purpose, token)
    assert _state(database_url, token=token, user_id=user_id) == before


@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_account_action_rolls_back_claim_when_protected_write_fails(
    database_url: str, purpose: str
) -> None:
    repository = SqlAuthRepository(database_url=database_url)
    tenant_id, user_id = _seed_target(database_url)
    token = _issue_token(
        repository, tenant_id=tenant_id, user_id=user_id, purpose=purpose
    )
    if purpose == "password_reset":
        _seed_session(repository, tenant_id=tenant_id, user_id=user_id)
    before = _state(database_url, token=token, user_id=user_id)

    if purpose == "invite":
        table, timing, operation = "user_sessions", "BEFORE", "INSERT"
    elif purpose == "password_reset":
        table, timing, operation = "user_sessions", "BEFORE", "UPDATE"
    else:
        table, timing, operation = "users", "BEFORE", "UPDATE"
    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "CREATE FUNCTION fail_atomic_action() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'injected protected action failure'; END $$"
        )
        cursor.execute(
            f"CREATE TRIGGER fail_atomic_action {timing} {operation} ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION fail_atomic_action()"
        )
        connection.commit()

    with pytest.raises(Exception, match="injected protected action failure"):
        _invoke(repository, purpose, token)
    assert _state(database_url, token=token, user_id=user_id) == before

    with connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute(f"DROP TRIGGER fail_atomic_action ON {table}")
        cursor.execute("DROP FUNCTION fail_atomic_action()")
        connection.commit()
    assert _invoke(repository, purpose, token)
