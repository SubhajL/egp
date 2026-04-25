"""Local development helpers for running a temporary PostgreSQL cluster."""

from __future__ import annotations

import base64
import contextlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

from fastapi.testclient import TestClient
from psycopg import connect

from egp_api.main import create_app
from egp_db.migration_runner import apply_migrations
from egp_db.repositories.project_repo import (
    build_project_upsert_record,
    create_project_repository,
)
from egp_db.repositories.run_repo import create_run_repository
from egp_shared_types.enums import ProcurementType, ProjectState

DEFAULT_LOCAL_DEV_POSTGRES_HOST = "127.0.0.1"
DEFAULT_LOCAL_DEV_POSTGRES_PORT = 55_432
DEFAULT_LOCAL_DEV_POSTGRES_USER = "egp"
DEFAULT_LOCAL_DEV_POSTGRES_DATABASE = "egp"


def _find_binary(name: str) -> Path | None:
    resolved = shutil.which(name)
    return Path(resolved) if resolved is not None else None


def postgres_binaries_available() -> bool:
    return all(_find_binary(name) is not None for name in ("initdb", "pg_ctl", "psql"))


def _find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


@dataclass(frozen=True, slots=True)
class LocalDevPostgresConfig:
    root_dir: Path
    host: str = DEFAULT_LOCAL_DEV_POSTGRES_HOST
    port: int = DEFAULT_LOCAL_DEV_POSTGRES_PORT
    user: str = DEFAULT_LOCAL_DEV_POSTGRES_USER
    database_name: str = DEFAULT_LOCAL_DEV_POSTGRES_DATABASE

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def log_path(self) -> Path:
        return self.root_dir / "postgres.log"

    @property
    def postgres_url(self) -> str:
        return f"postgresql://{self.user}@{self.host}:{self.port}/postgres"

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.user}@{self.host}:{self.port}/{self.database_name}"


def build_local_dev_postgres_config(
    *,
    repo_root: Path,
    root_dir: Path | None = None,
    host: str = DEFAULT_LOCAL_DEV_POSTGRES_HOST,
    port: int = DEFAULT_LOCAL_DEV_POSTGRES_PORT,
    user: str = DEFAULT_LOCAL_DEV_POSTGRES_USER,
    database_name: str = DEFAULT_LOCAL_DEV_POSTGRES_DATABASE,
) -> LocalDevPostgresConfig:
    resolved_repo_root = Path(repo_root).resolve()
    resolved_root_dir = (
        Path(root_dir).resolve()
        if root_dir is not None
        else resolved_repo_root / ".data" / "local-postgres"
    )
    return LocalDevPostgresConfig(
        root_dir=resolved_root_dir,
        host=host,
        port=port,
        user=user,
        database_name=database_name,
    )


def _persistent_cluster_initialized(config: LocalDevPostgresConfig) -> bool:
    return (config.data_dir / "PG_VERSION").exists()


def _persistent_cluster_running(config: LocalDevPostgresConfig) -> bool:
    if not _persistent_cluster_initialized(config):
        return False
    pg_ctl = _find_binary("pg_ctl")
    if pg_ctl is None:
        return False
    result = subprocess.run(
        [str(pg_ctl), "-D", str(config.data_dir), "status"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.returncode == 0


def get_local_dev_postgres_status(
    *,
    repo_root: Path,
    root_dir: Path | None = None,
    host: str = DEFAULT_LOCAL_DEV_POSTGRES_HOST,
    port: int = DEFAULT_LOCAL_DEV_POSTGRES_PORT,
    user: str = DEFAULT_LOCAL_DEV_POSTGRES_USER,
    database_name: str = DEFAULT_LOCAL_DEV_POSTGRES_DATABASE,
) -> dict[str, object]:
    config = build_local_dev_postgres_config(
        repo_root=repo_root,
        root_dir=root_dir,
        host=host,
        port=port,
        user=user,
        database_name=database_name,
    )
    return {
        "root_dir": str(config.root_dir),
        "data_dir": str(config.data_dir),
        "log_path": str(config.log_path),
        "host": config.host,
        "port": config.port,
        "user": config.user,
        "database_name": config.database_name,
        "postgres_url": config.postgres_url,
        "database_url": config.database_url,
        "initialized": _persistent_cluster_initialized(config),
        "running": _persistent_cluster_running(config),
    }


def _require_postgres_binaries() -> None:
    if not postgres_binaries_available():
        raise RuntimeError(
            "PostgreSQL binaries are required on PATH (expected initdb, pg_ctl, and psql)."
        )


def _create_database_if_missing(config: LocalDevPostgresConfig) -> None:
    with connect(config.postgres_url) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (config.database_name,),
            )
            if cursor.fetchone() is None:
                cursor.execute(f'CREATE DATABASE "{config.database_name}"')


def ensure_local_dev_postgres_ready(
    *,
    repo_root: Path,
    migrations_dir: Path,
    root_dir: Path | None = None,
    host: str = DEFAULT_LOCAL_DEV_POSTGRES_HOST,
    port: int = DEFAULT_LOCAL_DEV_POSTGRES_PORT,
    user: str = DEFAULT_LOCAL_DEV_POSTGRES_USER,
    database_name: str = DEFAULT_LOCAL_DEV_POSTGRES_DATABASE,
) -> dict[str, object]:
    _require_postgres_binaries()
    config = build_local_dev_postgres_config(
        repo_root=repo_root,
        root_dir=root_dir,
        host=host,
        port=port,
        user=user,
        database_name=database_name,
    )
    config.root_dir.mkdir(parents=True, exist_ok=True)
    if not _persistent_cluster_initialized(config):
        subprocess.run(
            [
                str(_find_binary("initdb")),
                "-D",
                str(config.data_dir),
                "-A",
                "trust",
                "-U",
                config.user,
                "--no-locale",
                "-E",
                "UTF8",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    if not _persistent_cluster_running(config):
        subprocess.run(
            [
                str(_find_binary("pg_ctl")),
                "-D",
                str(config.data_dir),
                "-l",
                str(config.log_path),
                "-o",
                f"-F -p {config.port} -c listen_addresses={config.host}",
                "-w",
                "start",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    _create_database_if_missing(config)
    apply_migrations(
        database_url=config.database_url, migrations_dir=Path(migrations_dir)
    )
    status = get_local_dev_postgres_status(
        repo_root=repo_root,
        root_dir=config.root_dir,
        host=config.host,
        port=config.port,
        user=config.user,
        database_name=config.database_name,
    )
    status["migrations_dir"] = str(Path(migrations_dir))
    return status


def stop_local_dev_postgres(
    *,
    repo_root: Path,
    root_dir: Path | None = None,
    host: str = DEFAULT_LOCAL_DEV_POSTGRES_HOST,
    port: int = DEFAULT_LOCAL_DEV_POSTGRES_PORT,
    user: str = DEFAULT_LOCAL_DEV_POSTGRES_USER,
    database_name: str = DEFAULT_LOCAL_DEV_POSTGRES_DATABASE,
) -> dict[str, object]:
    config = build_local_dev_postgres_config(
        repo_root=repo_root,
        root_dir=root_dir,
        host=host,
        port=port,
        user=user,
        database_name=database_name,
    )
    if _persistent_cluster_running(config):
        _require_postgres_binaries()
        subprocess.run(
            [
                str(_find_binary("pg_ctl")),
                "-D",
                str(config.data_dir),
                "-w",
                "stop",
                "-m",
                "fast",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    return get_local_dev_postgres_status(
        repo_root=repo_root,
        root_dir=config.root_dir,
        host=config.host,
        port=config.port,
        user=config.user,
        database_name=config.database_name,
    )


@dataclass
class TempPostgresCluster:
    root_dir: Path | None = None
    user: str = "egp"

    def __post_init__(self) -> None:
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        self._owned_root = self.root_dir is None
        if self.root_dir is None:
            self._tempdir = tempfile.TemporaryDirectory(prefix="egp-postgres-")
            self.root_dir = Path(self._tempdir.name)
        self._root_dir = Path(self.root_dir)
        self._data_dir = self._root_dir / "data"
        self._log_path = self._root_dir / "postgres.log"
        self._port = _find_free_port()
        self._started = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def postgres_url(self) -> str:
        return f"postgresql://{self.user}@127.0.0.1:{self.port}/postgres"

    def database_url(self, database_name: str) -> str:
        return f"postgresql://{self.user}@127.0.0.1:{self.port}/{database_name}"

    def start(self) -> "TempPostgresCluster":
        if self._started:
            return self
        self._root_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(_find_binary("initdb")),
                "-D",
                str(self._data_dir),
                "-A",
                "trust",
                "-U",
                self.user,
                "--no-locale",
                "-E",
                "UTF8",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            [
                str(_find_binary("pg_ctl")),
                "-D",
                str(self._data_dir),
                "-l",
                str(self._log_path),
                "-o",
                f"-F -p {self.port} -c listen_addresses=127.0.0.1",
                "-w",
                "start",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._started = True
        return self

    def stop(self) -> None:
        if self._started:
            subprocess.run(
                [
                    str(_find_binary("pg_ctl")),
                    "-D",
                    str(self._data_dir),
                    "-w",
                    "stop",
                    "-m",
                    "fast",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self._started = False
        if self._owned_root and self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

    def create_database(self, database_name: str) -> None:
        with connect(self.postgres_url) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE DATABASE "{database_name}"')

    def apply_sql(self, sql_path: Path, *, database_name: str) -> None:
        subprocess.run(
            [
                str(_find_binary("psql")),
                self.database_url(database_name),
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                str(sql_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def __enter__(self) -> "TempPostgresCluster":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def run_phase1_postgres_smoke(
    *,
    repo_root: Path,
    artifact_root: Path | str,
) -> dict[str, object]:
    repo_root = Path(repo_root)
    artifact_root = Path(artifact_root)
    migrations_dir = repo_root / "packages/db/src/migrations"
    database_name = "egp_smoke"

    with TempPostgresCluster() as cluster:
        cluster.create_database(database_name)
        database_url = cluster.database_url(database_name)
        apply_migrations(database_url=database_url, migrations_dir=migrations_dir)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (name, slug, plan_code)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    ("Smoke Tenant", "smoke-tenant", "dev"),
                )
                tenant_id = str(cursor.fetchone()[0])
                cursor.execute(
                    """
                    INSERT INTO projects (
                        tenant_id,
                        canonical_project_id,
                        project_name,
                        organization_name,
                        procurement_type,
                        project_state
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tenant_id,
                        "project-number:SMOKE-1",
                        "Smoke Project",
                        "Smoke Org",
                        "services",
                        "open_invitation",
                    ),
                )
                project_id = str(cursor.fetchone()[0])
                today = date.today()
                now = datetime.now(UTC)
                cursor.execute(
                    """
                    INSERT INTO billing_records (
                        id,
                        tenant_id,
                        record_number,
                        plan_code,
                        status,
                        billing_period_start,
                        billing_period_end,
                        currency,
                        amount_due,
                        created_at,
                        updated_at
                    ) VALUES (
                        gen_random_uuid(),
                        %s,
                        %s,
                        'monthly_membership',
                        'paid',
                        %s,
                        %s,
                        'THB',
                        '1500.00',
                        %s,
                        %s
                    )
                    RETURNING id
                    """,
                    (
                        tenant_id,
                        f"INV-SMOKE-{tenant_id[:8]}",
                        (today - timedelta(days=1)).isoformat(),
                        (today + timedelta(days=29)).isoformat(),
                        now,
                        now,
                    ),
                )
                billing_record_id = str(cursor.fetchone()[0])
                cursor.execute(
                    """
                    INSERT INTO billing_subscriptions (
                        id,
                        tenant_id,
                        billing_record_id,
                        plan_code,
                        status,
                        billing_period_start,
                        billing_period_end,
                        keyword_limit,
                        activated_at,
                        created_at,
                        updated_at
                    ) VALUES (
                        gen_random_uuid(),
                        %s,
                        %s,
                        'monthly_membership',
                        'active',
                        %s,
                        %s,
                        5,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        tenant_id,
                        billing_record_id,
                        (today - timedelta(days=1)).isoformat(),
                        (today + timedelta(days=29)).isoformat(),
                        now,
                        now,
                        now,
                    ),
                )
            connection.commit()

        client = TestClient(
            create_app(
                artifact_root=artifact_root,
                database_url=database_url,
                auth_required=False,
            )
        )
        ingest_response = client.post(
            "/v1/documents/ingest",
            json={
                "tenant_id": tenant_id,
                "project_id": project_id,
                "file_name": "tor.pdf",
                "content_base64": base64.b64encode(b"smoke-tor").decode("ascii"),
                "source_label": "เอกสารประกวดราคา",
                "source_status_text": "ประกาศเชิญชวน",
            },
        )
        document_id = ingest_response.json()["document"]["id"]
        listed = client.get(
            f"/v1/documents/projects/{project_id}", params={"tenant_id": tenant_id}
        )
        download = client.get(
            f"/v1/documents/{document_id}/download", params={"tenant_id": tenant_id}
        )

        return {
            "status_code": ingest_response.status_code,
            "listed_documents": len(listed.json()["documents"]),
            "download_status_code": download.status_code,
            "download_content_type": download.headers.get("content-type"),
            "download_size": len(download.content),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "database_url": database_url,
        }


def run_phase1_postgres_project_run_smoke(
    *,
    repo_root: Path,
) -> dict[str, object]:
    repo_root = Path(repo_root)
    migrations_dir = repo_root / "packages/db/src/migrations"
    database_name = "egp_phase1_repo_smoke"

    with TempPostgresCluster() as cluster:
        cluster.create_database(database_name)
        database_url = cluster.database_url(database_name)
        apply_migrations(database_url=database_url, migrations_dir=migrations_dir)

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tenants (name, slug, plan_code)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    ("Phase 1 Repo Tenant", "phase1-repo-tenant", "dev"),
                )
                tenant_id = str(cursor.fetchone()[0])
            connection.commit()

        project_repository = create_project_repository(
            database_url=database_url,
            bootstrap_schema=False,
        )
        run_repository = create_run_repository(
            database_url=database_url,
            bootstrap_schema=False,
        )

        project = project_repository.upsert_project(
            build_project_upsert_record(
                tenant_id=tenant_id,
                project_number="EGP-POSTGRES-0001",
                search_name="Phase 1 Repo Smoke",
                detail_name="Phase 1 Repo Smoke",
                project_name="Phase 1 Repo Smoke",
                organization_name="Smoke Org",
                proposal_submission_date="2026-05-01",
                budget_amount="1000000.00",
                procurement_type=ProcurementType.SERVICES,
                project_state=ProjectState.OPEN_INVITATION,
            ),
            source_status_text="ประกาศเชิญชวน",
        )
        project_detail = project_repository.get_project_detail(
            tenant_id=tenant_id,
            project_id=project.id,
        )

        run = run_repository.create_run(tenant_id=tenant_id, trigger_type="manual")
        task = run_repository.create_task(
            run_id=run.id,
            task_type="discover",
            project_id=project.id,
            keyword="โรงพยาบาล",
            payload={"page": 1},
        )
        run_repository.mark_run_started(run.id)
        run_repository.mark_task_finished(
            task.id, status="succeeded", result_json={"count": 1}
        )
        finished = run_repository.mark_run_finished(
            run.id,
            status="succeeded",
            summary_json={"projects_seen": 1},
        )
        run_detail = run_repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)

        return {
            "tenant_id": tenant_id,
            "database_url": database_url,
            "project_id": project.id,
            "alias_count": len(project_detail.aliases)
            if project_detail is not None
            else 0,
            "status_event_count": len(project_detail.status_events)
            if project_detail is not None
            else 0,
            "run_status": finished.status.value,
            "task_count": len(run_detail.tasks) if run_detail is not None else 0,
        }
