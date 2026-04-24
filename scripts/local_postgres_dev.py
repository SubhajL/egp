#!/usr/bin/env python3
"""Manage the persistent Dockerless local PostgreSQL cluster for app development."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from egp_db.dev_postgres import ensure_local_dev_postgres_ready
from egp_db.dev_postgres import get_local_dev_postgres_status
from egp_db.dev_postgres import stop_local_dev_postgres


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", parents=[common])
    status_parser.add_argument("--database-url-only", action="store_true")

    ensure_parser = subparsers.add_parser("ensure-ready", parents=[common])
    ensure_parser.add_argument("--database-url-only", action="store_true")

    stop_parser = subparsers.add_parser("stop", parents=[common])
    stop_parser.add_argument("--database-url-only", action="store_true")
    return parser


def _emit(payload: dict[str, object], *, database_url_only: bool) -> None:
    if database_url_only:
        print(str(payload["database_url"]))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    args = _build_parser().parse_args()
    repo_root = Path(args.repo_root).resolve()

    if args.command == "status":
        _emit(
            get_local_dev_postgres_status(repo_root=repo_root),
            database_url_only=bool(args.database_url_only),
        )
        return 0
    if args.command == "ensure-ready":
        _emit(
            ensure_local_dev_postgres_ready(
                repo_root=repo_root,
                migrations_dir=repo_root / "packages/db/src/migrations",
            ),
            database_url_only=bool(args.database_url_only),
        )
        return 0
    if args.command == "stop":
        _emit(
            stop_local_dev_postgres(repo_root=repo_root),
            database_url_only=bool(args.database_url_only),
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
