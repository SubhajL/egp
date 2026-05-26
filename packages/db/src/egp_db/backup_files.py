"""Backup file primitives: naming, hashing, sidecar verification, local rotation.

Pure-function helpers used by the backup CLI and the bash entrypoints
in ``scripts/pg_backup.sh`` / ``scripts/pg_restore.sh``.

Naming convention
-----------------
``egp-pg-YYYY-MM-DDTHHMMSSZ-{sha7}.dump.gz`` with sidecar ``.sha256``.
UTC always; the filename timestamp (not filesystem mtime) is authoritative
for retention to survive R2 overwrites and clock skew.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

_BACKUP_NAME_PATTERN = re.compile(
    r"^egp-pg-(\d{4}-\d{2}-\d{2}T\d{6}Z)-([0-9a-f]{7})\.dump\.gz$"
)
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{7}$")


def build_backup_name(*, created_at: datetime, git_sha: str) -> str:
    """Return canonical archive filename for a Postgres backup."""
    if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
        raise ValueError("created_at must be timezone-aware and UTC")
    if not _GIT_SHA_PATTERN.match(git_sha):
        raise ValueError("git_sha must be exactly 7 lowercase hex characters")
    timestamp = created_at.strftime("%Y-%m-%dT%H%M%SZ")
    return f"egp-pg-{timestamp}-{git_sha}.dump.gz"


def parse_backup_name(name: str) -> datetime | None:
    """Return the UTC timestamp embedded in a backup filename, or ``None``.

    Returns ``None`` for names that don't match the canonical pattern so callers
    can skip unrelated files during rotation.
    """
    match = _BACKUP_NAME_PATTERN.match(name)
    if match is None:
        return None
    timestamp_str = match.group(1)
    try:
        return datetime.strptime(timestamp_str, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def sha256_file(path: Path, *, chunk_size: int = 1_048_576) -> str:
    """Stream-hash ``path`` so large dumps don't load into memory."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def write_sha256_sidecar(artifact_path: Path, *, digest: str) -> Path:
    """Write ``<digest>  <basename>\\n`` to a ``.sha256`` sidecar.

    Returns the sidecar path. Format matches ``sha256sum`` so operators can
    verify with the standard CLI:
        ``cd <dir> && sha256sum -c <name>.sha256``.
    """
    sidecar = artifact_path.with_name(artifact_path.name + ".sha256")
    sidecar.write_text(f"{digest}  {artifact_path.name}\n", encoding="ascii")
    return sidecar


def verify_sha256_sidecar(artifact_path: Path, sidecar_path: Path) -> None:
    """Raise ``ValueError`` if ``artifact_path`` does not match the sidecar."""
    expected_line = sidecar_path.read_text(encoding="ascii").strip()
    if not expected_line:
        raise ValueError(f"sidecar {sidecar_path} is empty")
    expected_digest = expected_line.split(maxsplit=1)[0]
    actual_digest = sha256_file(artifact_path)
    if expected_digest != actual_digest:
        raise ValueError(
            f"sha256 mismatch for {artifact_path}: expected {expected_digest}, "
            f"got {actual_digest}"
        )


def rotate_local_backup_cache(
    cache_dir: Path,
    *,
    retention_days: int,
    keep_min: int,
    now: datetime,
) -> list[Path]:
    """Delete archive/sidecar pairs older than ``retention_days``.

    Always keeps the ``keep_min`` newest archives even if all are past the
    retention window. Returns the list of paths deleted (archive + sidecar
    counted separately). Orphan sidecars whose archive is missing are
    rotated by sidecar timestamp; non-conforming filenames are ignored.
    """
    if retention_days < 0:
        raise ValueError("retention_days must be non-negative")
    if keep_min < 0:
        raise ValueError("keep_min must be non-negative")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    archives: list[tuple[datetime, Path]] = []
    orphan_sidecars: list[tuple[datetime, Path]] = []
    archive_names: set[str] = set()
    sidecar_paths: dict[str, Path] = {}

    for entry in cache_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.name.endswith(".sha256"):
            base = entry.name[: -len(".sha256")]
            ts = parse_backup_name(base)
            if ts is not None:
                sidecar_paths[base] = entry
            continue
        ts = parse_backup_name(entry.name)
        if ts is None:
            continue
        archives.append((ts, entry))
        archive_names.add(entry.name)

    for base, sidecar_path in sidecar_paths.items():
        if base not in archive_names:
            ts = parse_backup_name(base)
            if ts is not None:
                orphan_sidecars.append((ts, sidecar_path))

    archives.sort(key=lambda item: item[0], reverse=True)
    cutoff = now - timedelta(days=retention_days)

    deleted: list[Path] = []
    kept = 0
    for ts, archive_path in archives:
        if ts >= cutoff:
            kept += 1
            continue
        if kept < keep_min:
            kept += 1
            continue
        archive_path.unlink()
        deleted.append(archive_path)
        sidecar = sidecar_paths.get(archive_path.name)
        if sidecar is not None and sidecar.exists():
            sidecar.unlink()
            deleted.append(sidecar)

    for ts, sidecar_path in orphan_sidecars:
        if ts < cutoff and sidecar_path.exists():
            sidecar_path.unlink()
            deleted.append(sidecar_path)

    return deleted
