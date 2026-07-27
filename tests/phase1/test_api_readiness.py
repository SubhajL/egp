from __future__ import annotations

import logging
import os
from pathlib import Path
import sqlite3
from time import monotonic

from fastapi.testclient import TestClient
from psycopg import connect
import pytest

from egp_api.main import create_app
from egp_api.services.readiness_service import ReadinessService
from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations, list_migration_files
from tests.support.app_factory import create_test_app


def test_ci_postgres_readiness_accepts_exact_migration_set(repo_root: Path) -> None:
    if os.environ.get("EGP_CI_POSTGRES_CONTRACT") != "1":
        pytest.skip("CI PostgreSQL contract is opt-in")

    snapshot = ReadinessService(
        database_url=os.environ["DATABASE_URL"],
        migrations_dir=repo_root / "packages/db/src/migrations",
    ).build_readiness_snapshot()

    assert snapshot.is_ready
    assert snapshot.to_payload() == {
        "status": "ready",
        "checks": {
            "database": {"status": "ok"},
            "migrations": {
                "status": "ok",
                "pending_count": 0,
                "unexpected_count": 0,
            },
        },
    }


def test_live_and_health_are_public_database_independent_aliases(
    tmp_path: Path,
) -> None:
    app = create_test_app(
        artifact_root=tmp_path,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'liveness.sqlite3'}",
        auth_required=True,
        jwt_secret="readiness-test-secret",
        payment_callback_secret="readiness-callback-secret",
    )
    client = TestClient(app)

    assert client.get("/live").json() == {"status": "ok"}
    assert client.get("/health").json() == {"status": "ok"}
    assert (
        app.openapi()["paths"]["/health"]["get"]["operationId"] == "health_health_get"
    )


def test_ready_fails_quickly_when_database_unreachable(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url="postgresql://egp:egp@127.0.0.1:1/egp",
            auth_required=True,
            jwt_secret="readiness-test-secret",
            payment_callback_secret="readiness-callback-secret",
            background_runtime_mode="external",
        )
    )

    started_at = monotonic()
    response = client.get("/ready")
    elapsed_seconds = monotonic() - started_at

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "database_unreachable",
        "checks": {
            "database": {"status": "error"},
            "migrations": {
                "status": "unknown",
                "pending_count": None,
                "unexpected_count": None,
            },
        },
    }
    assert elapsed_seconds < 3.0


def test_ready_fails_when_migration_is_missing(
    repo_root: Path,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if not postgres_binaries_available():
        return

    migrations_dir = repo_root / "packages/db/src/migrations"
    expected_versions = [path.name for path in list_migration_files(migrations_dir)]
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_readiness_missing_migration_test")
        database_url = cluster.database_url("egp_readiness_missing_migration_test")
        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.executemany(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    [(version,) for version in expected_versions[:-1]],
                )
            connection.commit()

        client = TestClient(
            create_app(
                artifact_root=tmp_path,
                database_url=database_url,
                auth_required=False,
                payment_callback_secret="readiness-callback-secret",
                background_runtime_mode="external",
            )
        )
        with caplog.at_level(logging.WARNING, logger="egp_api.bootstrap.middleware"):
            response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "migrations_pending",
        "checks": {
            "database": {"status": "ok"},
            "migrations": {
                "status": "error",
                "pending_count": 1,
                "unexpected_count": 0,
            },
        },
    }
    readiness_record = next(
        record
        for record in caplog.records
        if record.message == "readiness check failed"
    )
    assert readiness_record.readiness_reason == "migrations_pending"
    assert readiness_record.pending_migration_count == 1


def test_ready_rejects_unexpected_migration_history(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "unexpected-migration.sqlite3"
    expected_versions = [
        path.name
        for path in list_migration_files(repo_root / "packages/db/src/migrations")
    ]
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            [(version,) for version in [*expected_versions, "999_unexpected.sql"]],
        )

    client = TestClient(
        create_test_app(
            artifact_root=tmp_path,
            database_url=f"sqlite+pysqlite:///{database_path}",
            auth_required=False,
            payment_callback_secret="readiness-callback-secret",
        )
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "migration_history_mismatch"
    assert response.json()["checks"]["migrations"] == {
        "status": "error",
        "pending_count": 0,
        "unexpected_count": 1,
    }


def test_ready_fails_when_migration_ledger_is_absent(tmp_path: Path) -> None:
    client = TestClient(
        create_test_app(
            artifact_root=tmp_path,
            database_url=f"sqlite+pysqlite:///{tmp_path / 'no-ledger.sqlite3'}",
            auth_required=False,
            payment_callback_secret="readiness-callback-secret",
        )
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "migration_ledger_unavailable"


def test_ready_accepts_exact_migrated_postgres(repo_root: Path, tmp_path: Path) -> None:
    if not postgres_binaries_available():
        return

    migrations_dir = repo_root / "packages/db/src/migrations"
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_readiness_migrated_test")
        database_url = cluster.database_url("egp_readiness_migrated_test")
        apply_migrations(database_url=database_url, migrations_dir=migrations_dir)
        client = TestClient(
            create_app(
                artifact_root=tmp_path,
                database_url=database_url,
                auth_required=False,
                payment_callback_secret="readiness-callback-secret",
                background_runtime_mode="external",
            )
        )
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "reason": None,
        "checks": {
            "database": {"status": "ok"},
            "migrations": {
                "status": "ok",
                "pending_count": 0,
                "unexpected_count": 0,
            },
        },
    }
