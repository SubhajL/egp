#!/usr/bin/env python3
"""Write or verify the immutable SQL migration checksum manifest."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"
DEFAULT_MANIFEST_PATH = DEFAULT_MIGRATIONS_DIR / "manifest.sha256"


def list_sql_migrations(migrations_dir: Path) -> list[Path]:
    """Return the complete ordered SQL migration set."""

    migrations = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())
    if not migrations:
        raise ValueError(f"no SQL migrations found in {migrations_dir}")
    return migrations


def render_manifest(migrations_dir: Path) -> str:
    """Render sha256sum-compatible entries for every SQL migration."""

    entries = []
    for migration_path in list_sql_migrations(migrations_dir):
        digest = hashlib.sha256(migration_path.read_bytes()).hexdigest()
        entries.append(f"{digest}  {migration_path.name}")
    return "\n".join(entries) + "\n"


def write_manifest(*, migrations_dir: Path, manifest_path: Path) -> int:
    """Replace the manifest with checksums from the current migration set."""

    rendered = render_manifest(migrations_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(rendered, encoding="utf-8")
    print(
        "wrote migration manifest: "
        f"{len(rendered.splitlines())} file(s) -> {manifest_path}"
    )
    return 0


def check_manifest(*, migrations_dir: Path, manifest_path: Path) -> int:
    """Return nonzero when the committed manifest is absent or differs."""

    expected = render_manifest(migrations_dir)
    if not manifest_path.is_file():
        print(
            f"migration manifest mismatch: missing {manifest_path}",
            file=sys.stderr,
        )
        return 1
    actual = manifest_path.read_text(encoding="utf-8")
    if actual != expected:
        print(
            "migration manifest mismatch: SQL filenames or contents changed; "
            "run scripts/check_migration_manifest.py --write and review the diff",
            file=sys.stderr,
        )
        return 1
    print(
        "migration manifest verified: "
        f"{len(expected.splitlines())} file(s) from {migrations_dir}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the manifest-checker command line."""

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the selected write or verification mode."""

    args = build_parser().parse_args(argv)
    try:
        if args.write:
            return write_manifest(
                migrations_dir=args.migrations_dir,
                manifest_path=args.manifest,
            )
        return check_manifest(
            migrations_dir=args.migrations_dir,
            manifest_path=args.manifest,
        )
    except (OSError, ValueError) as exc:
        print(f"migration manifest error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
