"""Lightweight SQL migration runner for numbered Postgres migrations."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from psycopg import connect


@dataclass(frozen=True)
class MigrationRunResult:
    applied_versions: list[str]
    pending_versions: list[str]


def _psycopg_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


def list_migration_files(migrations_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in Path(migrations_dir).iterdir()
        if path.is_file() and path.suffix == ".sql"
    )


def apply_migrations(*, database_url: str, migrations_dir: Path) -> MigrationRunResult:
    database_url = _psycopg_database_url(database_url)
    migrations_dir = Path(migrations_dir)
    migration_files = list_migration_files(migrations_dir)

    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        connection.commit()

        with connection.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations")
            applied_versions = {str(row[0]) for row in cursor.fetchall()}

        pending_files = [path for path in migration_files if path.name not in applied_versions]
        pending_versions = [path.name for path in pending_files]

        for migration_file in pending_files:
            with connection.cursor() as cursor:
                cursor.execute(migration_file.read_text(encoding="utf-8"))
                cursor.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (migration_file.name,),
                )
            connection.commit()

    return MigrationRunResult(
        applied_versions=pending_versions,
        pending_versions=[],
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--migrations-dir", required=True, type=Path)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    result = apply_migrations(
        database_url=args.database_url,
        migrations_dir=args.migrations_dir,
    )
    print(
        f"Applied {len(result.applied_versions)} migration(s): "
        + (", ".join(result.applied_versions) if result.applied_versions else "none")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
