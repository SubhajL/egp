#!/usr/bin/env python3
"""Collect credential-safe, read-only evidence for migration 039."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Literal, Sequence

from psycopg import connect


Phase = Literal["pre", "post"]

REPAIR_KEYS: tuple[str, ...] = (
    "orphan_or_cross_tenant_run",
    "orphan_or_cross_tenant_project",
    "reason_outside_vocabulary",
    "terminal_status_missing_reason",
    "persisted_missing_project",
    "accepted_or_persisted_with_reason",
    "nonpersisted_with_project",
)
MIGRATION_038 = "038_discovery_candidate_attempts.sql"
MIGRATION_039 = "039_candidate_attempt_integrity.sql"
TERMINAL_REASONS: tuple[str, ...] = (
    "worker_lost",
    "lease_lost",
    "worker_timeout",
    "worker_terminated",
    "cancelled",
    "persist_error",
    "duplicate_in_run",
    "late_stage",
    "unclassified",
    "navigation_failure",
    "results_page_returned",
    "project_detail_missing_required_fields",
    "rejection_page",
    "placeholder_detail",
    "out_of_scope_stage",
    "detail_unknown",
)


@dataclass(frozen=True, slots=True)
class CandidateIntegrityPreflightReport:
    schema_version: int
    phase: Phase
    status: str
    candidate_table_present: bool
    active_run_count: int
    candidate_count: int
    repair_counts: dict[str, int]
    migration_038_applied: bool
    migration_039_applied: bool
    migration_manifest_sha256: dict[str, str]
    survivor_delta_matches: bool | None


def _psycopg_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


def _read_manifest_sha256(migrations_dir: Path) -> dict[str, str]:
    required_names = {MIGRATION_038, MIGRATION_039}
    digests: dict[str, str] = {}
    manifest_path = Path(migrations_dir) / "manifest.sha256"
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError("invalid migration manifest")
        digest, filename = parts
        filename = filename.strip()
        if filename in required_names:
            if filename in digests:
                raise ValueError("duplicate migration manifest entry")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("invalid migration manifest digest")
            try:
                actual_digest = hashlib.sha256(
                    (Path(migrations_dir) / filename).read_bytes()
                ).hexdigest()
            except OSError as exc:
                raise ValueError("unable to read required migration") from exc
            if actual_digest != digest:
                raise ValueError("migration manifest digest mismatch")
            digests[filename] = digest
    if set(digests) != required_names:
        raise ValueError("migration manifest is missing required entries")
    return {name: digests[name] for name in (MIGRATION_038, MIGRATION_039)}


def _table_present(cursor: Any, table_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    return cursor.fetchone()[0] is not None


def _count(cursor: Any, query: str, parameters: tuple[Any, ...] = ()) -> int:
    cursor.execute(query, parameters)
    return int(cursor.fetchone()[0])


def _ledger_versions(cursor: Any, present: bool) -> set[str]:
    if not present:
        return set()
    cursor.execute("SELECT version FROM schema_migrations")
    return {str(row[0]) for row in cursor.fetchall()}


def _repair_queries() -> dict[str, str]:
    reasons = ", ".join(f"'{reason}'" for reason in TERMINAL_REASONS)
    return {
        "orphan_or_cross_tenant_run": """
            SELECT COUNT(*)
            FROM discovery_candidate_attempts a
            WHERE NOT EXISTS (
                SELECT 1 FROM crawl_runs r
                WHERE r.id = a.run_id AND r.tenant_id = a.tenant_id
            )
        """,
        "orphan_or_cross_tenant_project": """
            SELECT COUNT(*)
            FROM discovery_candidate_attempts a
            WHERE a.project_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM projects p
                  WHERE p.id = a.project_id AND p.tenant_id = a.tenant_id
              )
        """,
        "reason_outside_vocabulary": f"""
            SELECT COUNT(*)
            FROM discovery_candidate_attempts
            WHERE terminal_reason IS NOT NULL
              AND terminal_reason NOT IN ({reasons})
        """,
        "terminal_status_missing_reason": """
            SELECT COUNT(*)
            FROM discovery_candidate_attempts
            WHERE candidate_status IN ('dropped', 'failed', 'unknown')
              AND terminal_reason IS NULL
        """,
        "persisted_missing_project": """
            SELECT COUNT(*)
            FROM discovery_candidate_attempts
            WHERE candidate_status = 'persisted'
              AND project_id IS NULL
        """,
        "accepted_or_persisted_with_reason": """
            SELECT COUNT(*)
            FROM discovery_candidate_attempts
            WHERE candidate_status IN ('accepted', 'persisted')
              AND terminal_reason IS NOT NULL
        """,
        "nonpersisted_with_project": """
            SELECT COUNT(*)
            FROM discovery_candidate_attempts
            WHERE candidate_status IN ('accepted', 'dropped', 'failed', 'unknown')
              AND project_id IS NOT NULL
        """,
    }


def _repair_counts(cursor: Any, candidate_table_present: bool) -> dict[str, int]:
    if not candidate_table_present:
        return {key: 0 for key in REPAIR_KEYS}
    queries = _repair_queries()
    return {key: _count(cursor, queries[key]) for key in REPAIR_KEYS}


def _survivor_delta(
    *,
    candidate_count: int,
    expected_pre_candidate_count: int | None,
    expected_deleted_orphan_run_count: int | None,
) -> bool | None:
    if (
        expected_pre_candidate_count is None
        and expected_deleted_orphan_run_count is None
    ):
        return None
    if (
        expected_pre_candidate_count is None
        or expected_deleted_orphan_run_count is None
    ):
        return False
    return candidate_count == (
        expected_pre_candidate_count - expected_deleted_orphan_run_count
    )


def _status(
    *,
    phase: Phase,
    active_run_count: int,
    repair_counts: dict[str, int],
    migration_039_applied: bool,
    survivor_delta_matches: bool | None,
) -> str:
    if active_run_count > 0:
        return "blocked_active_runs"
    if phase == "pre":
        return "ready_with_repairs" if any(repair_counts.values()) else "ready"
    if not migration_039_applied:
        return "blocked_migration_039"
    if any(repair_counts.values()):
        return "blocked_repairs_remaining"
    if survivor_delta_matches is not True:
        return "blocked_survivor_delta"
    return "ready"


def _validate_survivor_contract(
    *,
    expected_pre_candidate_count: int | None,
    expected_deleted_orphan_run_count: int | None,
) -> None:
    if (
        expected_pre_candidate_count is None
        and expected_deleted_orphan_run_count is None
    ):
        return
    if (
        expected_pre_candidate_count is None
        or expected_deleted_orphan_run_count is None
        or type(expected_pre_candidate_count) is not int
        or type(expected_deleted_orphan_run_count) is not int
        or expected_pre_candidate_count < 0
        or expected_deleted_orphan_run_count < 0
        or expected_deleted_orphan_run_count > expected_pre_candidate_count
    ):
        raise ValueError("invalid survivor contract")


def collect_preflight_report(
    *,
    database_url: str,
    migrations_dir: Path,
    phase: Phase,
    expected_pre_candidate_count: int | None = None,
    expected_deleted_orphan_run_count: int | None = None,
) -> CandidateIntegrityPreflightReport:
    """Collect migration-039 integrity evidence without changing the database."""
    _validate_survivor_contract(
        expected_pre_candidate_count=expected_pre_candidate_count,
        expected_deleted_orphan_run_count=expected_deleted_orphan_run_count,
    )
    manifest_sha256 = _read_manifest_sha256(Path(migrations_dir))
    database_url = _psycopg_database_url(database_url)

    with connect(database_url) as connection:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                schema_migrations_present = _table_present(cursor, "schema_migrations")
                ledger_versions = _ledger_versions(cursor, schema_migrations_present)
                migration_038_applied = MIGRATION_038 in ledger_versions
                migration_039_applied = MIGRATION_039 in ledger_versions

                crawl_runs_present = _table_present(cursor, "crawl_runs")
                active_run_count = (
                    _count(
                        cursor,
                        """
                        SELECT COUNT(*)
                        FROM crawl_runs
                        WHERE status IN ('queued', 'running')
                        """,
                    )
                    if crawl_runs_present
                    else 0
                )

                candidate_table_present = _table_present(
                    cursor, "discovery_candidate_attempts"
                )
                candidate_count = (
                    _count(cursor, "SELECT COUNT(*) FROM discovery_candidate_attempts")
                    if candidate_table_present
                    else 0
                )
                repair_counts = _repair_counts(cursor, candidate_table_present)
        finally:
            connection.rollback()

    survivor_delta_matches = _survivor_delta(
        candidate_count=candidate_count,
        expected_pre_candidate_count=expected_pre_candidate_count,
        expected_deleted_orphan_run_count=expected_deleted_orphan_run_count,
    )
    return CandidateIntegrityPreflightReport(
        schema_version=1,
        phase=phase,
        status=_status(
            phase=phase,
            active_run_count=active_run_count,
            repair_counts=repair_counts,
            migration_039_applied=migration_039_applied,
            survivor_delta_matches=survivor_delta_matches,
        ),
        candidate_table_present=candidate_table_present,
        active_run_count=active_run_count,
        candidate_count=candidate_count,
        repair_counts=repair_counts,
        migration_038_applied=migration_038_applied,
        migration_039_applied=migration_039_applied,
        migration_manifest_sha256=manifest_sha256,
        survivor_delta_matches=survivor_delta_matches,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrations-dir", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("pre", "post"))
    parser.add_argument("--expected-pre-candidate-count", type=int)
    parser.add_argument("--expected-deleted-orphan-run-count", type=int)
    return parser


def _emit_error() -> None:
    print(json.dumps({"schema_version": 1, "status": "error"}, separators=(",", ":")))


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        _emit_error()
        return 1
    try:
        report = collect_preflight_report(
            database_url=database_url,
            migrations_dir=args.migrations_dir,
            phase=args.phase,
            expected_pre_candidate_count=args.expected_pre_candidate_count,
            expected_deleted_orphan_run_count=args.expected_deleted_orphan_run_count,
        )
    except Exception:
        _emit_error()
        return 1
    print(json.dumps(asdict(report), sort_keys=True, separators=(",", ":")))
    return 0 if report.status in {"ready", "ready_with_repairs"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
