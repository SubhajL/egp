"""Lightweight SQL migration runner for numbered Postgres migrations."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from psycopg import connect


MIGRATION_ADVISORY_LOCK_KEY = 0x4547504D494752


class MigrationLockUnavailableError(RuntimeError):
    """Raised when another migration runner owns the session advisory lock."""


class MigrationManifestError(RuntimeError):
    """Raised when the migration manifest is missing or does not attest the files."""


class MigrationChecksumMismatchError(RuntimeError):
    """Raised when applied migration history does not match the current migration files."""


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


_MANIFEST_ENTRY_RE = re.compile(
    r"(?P<digest>[0-9a-f]{64})  (?P<name>[^\s/\\\x00-\x1f\x7f]+\.sql)"
)


def _load_migration_payloads(
    migrations_dir: Path,
    migration_files: list[Path],
    *,
    require_manifest: bool,
) -> tuple[dict[str, bytes], dict[str, str]]:
    migration_payloads = {
        migration_file.name: migration_file.read_bytes()
        for migration_file in migration_files
    }
    migration_digests = {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in migration_payloads.items()
    }

    manifest_path = migrations_dir / "manifest.sha256"
    if not manifest_path.exists():
        if require_manifest:
            raise MigrationManifestError(
                f"migration manifest is required but missing: {manifest_path.name}"
            )
        return migration_payloads, migration_digests
    if not manifest_path.is_file():
        raise MigrationManifestError(
            f"migration manifest path is not a file: {manifest_path.name}"
        )

    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise MigrationManifestError(
            f"could not read migration manifest: {manifest_path.name}"
        ) from error

    manifest_digests: dict[str, str] = {}
    for line_number, line in enumerate(manifest_text.splitlines(), start=1):
        if not line.strip():
            continue
        match = _MANIFEST_ENTRY_RE.fullmatch(line)
        if match is None:
            raise MigrationManifestError(
                f"invalid migration manifest entry at line {line_number}: "
                "expected digest, two spaces, and a safe .sql name"
            )
        name = match.group("name")
        if Path(name).name != name:
            raise MigrationManifestError(
                f"migration manifest contains an unsafe name: {name}"
            )
        if name in manifest_digests:
            raise MigrationManifestError(
                f"duplicate migration name in manifest: {name}"
            )
        manifest_digests[name] = match.group("digest")

    migration_names = set(migration_digests)
    manifest_names = set(manifest_digests)
    extra_names = sorted(manifest_names - migration_names)
    if extra_names:
        raise MigrationManifestError(
            f"migration manifest contains unknown name: {extra_names[0]}"
        )
    missing_names = sorted(migration_names - manifest_names)
    if missing_names:
        raise MigrationManifestError(
            f"migration manifest is missing name: {missing_names[0]}"
        )

    for name, expected_digest in manifest_digests.items():
        if migration_digests[name] != expected_digest:
            raise MigrationManifestError(
                f"migration manifest digest mismatch for name: {name}"
            )

    return migration_payloads, migration_digests


def apply_migrations(
    *,
    database_url: str,
    migrations_dir: Path,
    require_manifest: bool = False,
) -> MigrationRunResult:
    database_url = _psycopg_database_url(database_url)
    migrations_dir = Path(migrations_dir)
    migration_files = list_migration_files(migrations_dir)
    migration_payloads, migration_digests = _load_migration_payloads(
        migrations_dir,
        migration_files,
        require_manifest=require_manifest,
    )

    lock_acquired = False
    primary_exception: BaseException | None = None
    with connect(database_url) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_lock(%s)",
                    (MIGRATION_ADVISORY_LOCK_KEY,),
                )
                lock_acquired = bool(cursor.fetchone()[0])
            if not lock_acquired:
                raise MigrationLockUnavailableError(
                    "another migration runner holds the database lock"
                )

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        sha256 TEXT
                    )
                    """
                )
                cursor.execute(
                    "ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS sha256 TEXT"
                )
            connection.commit()

            with connection.cursor() as cursor:
                cursor.execute("SELECT version, sha256 FROM schema_migrations")
                applied_rows = [(str(row[0]), row[1]) for row in cursor.fetchall()]

            migration_names = set(migration_digests)
            missing_migration_names = sorted(
                {version for version, _ in applied_rows} - migration_names
            )
            if missing_migration_names:
                raise MigrationChecksumMismatchError(
                    "applied migration is missing from the current manifest: "
                    + missing_migration_names[0]
                )

            legacy_versions: list[str] = []
            for version, stored_digest in applied_rows:
                expected_digest = migration_digests[version]
                if stored_digest is None:
                    legacy_versions.append(version)
                elif stored_digest != expected_digest:
                    raise MigrationChecksumMismatchError(
                        f"applied migration checksum mismatch for version: {version}"
                    )

            if legacy_versions:
                with connection.cursor() as cursor:
                    for version in legacy_versions:
                        cursor.execute(
                            "UPDATE schema_migrations SET sha256 = %s WHERE version = %s",
                            (migration_digests[version], version),
                        )
                connection.commit()

            pending_files = [
                path
                for path in migration_files
                if path.name not in {version for version, _ in applied_rows}
            ]
            pending_versions = [path.name for path in pending_files]

            for migration_file in pending_files:
                with connection.cursor() as cursor:
                    cursor.execute(
                        migration_payloads[migration_file.name].decode("utf-8")
                    )
                    cursor.execute(
                        "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                        (migration_file.name, migration_digests[migration_file.name]),
                    )
                connection.commit()
        except BaseException as error:
            primary_exception = error
            raise
        finally:
            if lock_acquired:
                try:
                    connection.rollback()
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT pg_advisory_unlock(%s)",
                            (MIGRATION_ADVISORY_LOCK_KEY,),
                        )
                        lock_released = bool(cursor.fetchone()[0])
                    if not lock_released:
                        raise RuntimeError("migration advisory lock was not held")
                except BaseException:
                    if primary_exception is None:
                        raise

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
        require_manifest=True,
    )
    print(
        f"Applied {len(result.applied_versions)} migration(s): "
        + (", ".join(result.applied_versions) if result.applied_versions else "none")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
