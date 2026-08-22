from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from shutil import copy2

from psycopg import connect
import pytest

from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations, list_migration_files
from egp_shared_types.enums import CandidateTerminalReason


REPAIR_KEYS = {
    "orphan_or_cross_tenant_run",
    "orphan_or_cross_tenant_project",
    "reason_outside_vocabulary",
    "terminal_status_missing_reason",
    "persisted_missing_project",
    "accepted_or_persisted_with_reason",
    "nonpersisted_with_project",
}


def _stage_required_manifest_files(repo_root: Path, target: Path) -> Path:
    migrations = repo_root / "packages/db/src/migrations"
    target.mkdir()
    names = (
        "038_discovery_candidate_attempts.sql",
        "039_candidate_attempt_integrity.sql",
    )
    lines: list[str] = []
    for name in names:
        source = migrations / name
        copy2(source, target / name)
        lines.append(f"{hashlib.sha256(source.read_bytes()).hexdigest()}  {name}")
    (target / "manifest.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def test_preflight_reason_vocabulary_tracks_shared_candidate_enum() -> None:
    from scripts.candidate_integrity_preflight import TERMINAL_REASONS

    assert set(TERMINAL_REASONS) == {reason.value for reason in CandidateTerminalReason}


def test_preflight_collects_all_counts_from_one_repeatable_read_snapshot() -> None:
    from scripts.candidate_integrity_preflight import collect_preflight_report

    source = inspect.getsource(collect_preflight_report)

    assert "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in source
    assert "BEGIN READ ONLY" not in source


def _stage_migrations(repo_root: Path, target: Path, through: str) -> Path:
    target.mkdir()
    for migration in list_migration_files(repo_root / "packages/db/src/migrations"):
        if migration.name <= through:
            copy2(migration, target / migration.name)
    return target


def _migration_versions(database_url: str) -> list[str]:
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations ORDER BY version")
            return [str(row[0]) for row in cursor.fetchall()]


def _seed_candidate_repair_matrix(database_url: str) -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    run_id = "22222222-2222-2222-2222-222222222222"
    project_id = "33333333-3333-3333-3333-333333333333"
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'Preflight', 'preflight')",
                (tenant_id,),
            )
            cursor.execute(
                """
                INSERT INTO crawl_runs (id, tenant_id, trigger_type, status)
                VALUES (%s, %s, 'manual', 'succeeded')
                """,
                (run_id, tenant_id),
            )
            cursor.execute(
                """
                INSERT INTO projects (
                    id, tenant_id, canonical_project_id, project_name
                ) VALUES (%s, %s, 'preflight-project', 'Preflight project')
                """,
                (project_id, tenant_id),
            )
            rows = (
                (
                    "orphan-run",
                    "44444444-4444-4444-4444-444444444444",
                    "accepted",
                    None,
                    None,
                ),
                (
                    "orphan-project",
                    run_id,
                    "persisted",
                    None,
                    "55555555-5555-5555-5555-555555555555",
                ),
                ("invalid-reason", run_id, "dropped", "legacy free text", None),
                ("missing-reason", run_id, "failed", None, None),
                ("persisted-no-project", run_id, "persisted", None, None),
                ("accepted-with-reason", run_id, "accepted", "worker_lost", None),
                ("accepted-with-project", run_id, "accepted", None, project_id),
            )
            cursor.executemany(
                """
                INSERT INTO discovery_candidate_attempts (
                    tenant_id, run_id, candidate_key, keyword,
                    candidate_status, terminal_reason, project_id
                ) VALUES (%s, %s, %s, 'preflight', %s, %s, %s)
                """,
                [
                    (tenant_id, row_run_id, key, status, reason, row_project_id)
                    for key, row_run_id, status, reason, row_project_id in rows
                ],
            )
        connection.commit()


def test_preflight_supports_037_target_without_candidate_table(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for migration preflight")

    from scripts.candidate_integrity_preflight import collect_preflight_report

    staged = _stage_migrations(
        repo_root,
        tmp_path / "through-037",
        "037_crawl_profile_execution_backend.sql",
    )
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_candidate_preflight_037")
        database_url = cluster.database_url("egp_candidate_preflight_037")
        apply_migrations(database_url=database_url, migrations_dir=staged)
        versions_before = _migration_versions(database_url)

        report = collect_preflight_report(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
            phase="pre",
        )

        assert report.schema_version == 1
        assert report.phase == "pre"
        assert report.status == "ready"
        assert report.candidate_table_present is False
        assert report.active_run_count == 0
        assert report.repair_counts == {key: 0 for key in REPAIR_KEYS}
        assert report.migration_038_applied is False
        assert report.migration_039_applied is False
        assert (
            len(
                report.migration_manifest_sha256["038_discovery_candidate_attempts.sql"]
            )
            == 64
        )
        assert (
            len(report.migration_manifest_sha256["039_candidate_attempt_integrity.sql"])
            == 64
        )
        assert _migration_versions(database_url) == versions_before


def test_preflight_reports_every_039_repair_category_and_blocks_active_run(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for migration preflight")

    from scripts.candidate_integrity_preflight import collect_preflight_report

    staged = _stage_migrations(
        repo_root,
        tmp_path / "through-038",
        "038_discovery_candidate_attempts.sql",
    )
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_candidate_preflight_repairs")
        database_url = cluster.database_url("egp_candidate_preflight_repairs")
        apply_migrations(database_url=database_url, migrations_dir=staged)
        _seed_candidate_repair_matrix(database_url)

        report = collect_preflight_report(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
            phase="pre",
        )

        assert report.status == "ready_with_repairs"
        assert report.candidate_table_present is True
        assert report.active_run_count == 0
        assert report.candidate_count == 7
        assert report.repair_counts == {key: 1 for key in REPAIR_KEYS}
        assert report.migration_038_applied is True
        assert report.migration_039_applied is False

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE crawl_runs SET status = 'running' WHERE id = %s",
                    ("22222222-2222-2222-2222-222222222222",),
                )
            connection.commit()

        blocked = collect_preflight_report(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
            phase="pre",
        )
        assert blocked.status == "blocked_active_runs"
        assert blocked.active_run_count == 1


def test_postflight_requires_zero_repair_counts_and_records_survivor_delta(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for migration preflight")

    from scripts.candidate_integrity_preflight import collect_preflight_report

    through_038 = _stage_migrations(
        repo_root,
        tmp_path / "through-038-post",
        "038_discovery_candidate_attempts.sql",
    )
    through_039 = _stage_migrations(
        repo_root,
        tmp_path / "through-039-post",
        "039_candidate_attempt_integrity.sql",
    )
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_candidate_preflight_post")
        database_url = cluster.database_url("egp_candidate_preflight_post")
        apply_migrations(database_url=database_url, migrations_dir=through_038)
        _seed_candidate_repair_matrix(database_url)
        before = collect_preflight_report(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
            phase="pre",
        )

        apply_migrations(database_url=database_url, migrations_dir=through_039)
        after = collect_preflight_report(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
            phase="post",
            expected_pre_candidate_count=before.candidate_count,
            expected_deleted_orphan_run_count=before.repair_counts[
                "orphan_or_cross_tenant_run"
            ],
        )

        assert after.status == "ready"
        assert after.migration_039_applied is True
        assert after.repair_counts == {key: 0 for key in REPAIR_KEYS}
        assert after.candidate_count == 6
        assert after.survivor_delta_matches is True

        missing_survivor_contract = collect_preflight_report(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
            phase="post",
        )
        assert missing_survivor_contract.status == "blocked_survivor_delta"
        assert missing_survivor_contract.survivor_delta_matches is None


@pytest.mark.parametrize(
    ("pre_count", "deleted_count"),
    [
        (True, 0),
        (0, False),
        (-1, 0),
        (1, -1),
        (1, 2),
    ],
)
def test_preflight_rejects_impossible_survivor_contract_before_database_access(
    repo_root: Path,
    pre_count: int,
    deleted_count: int,
) -> None:
    from scripts.candidate_integrity_preflight import collect_preflight_report

    with pytest.raises(ValueError, match="survivor"):
        collect_preflight_report(
            database_url="postgresql://must-not-connect.invalid/egp",
            migrations_dir=repo_root / "packages/db/src/migrations",
            phase="post",
            expected_pre_candidate_count=pre_count,
            expected_deleted_orphan_run_count=deleted_count,
        )


def test_manifest_evidence_recomputes_required_migration_bytes(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from scripts.candidate_integrity_preflight import _read_manifest_sha256

    staged = _stage_required_manifest_files(repo_root, tmp_path / "manifest")
    expected = _read_manifest_sha256(staged)
    assert set(expected) == {
        "038_discovery_candidate_attempts.sql",
        "039_candidate_attempt_integrity.sql",
    }

    (staged / "039_candidate_attempt_integrity.sql").write_text(
        "-- modified after manifest\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        _read_manifest_sha256(staged)


def test_manifest_evidence_rejects_duplicate_required_entry(
    repo_root: Path,
    tmp_path: Path,
) -> None:
    from scripts.candidate_integrity_preflight import _read_manifest_sha256

    staged = _stage_required_manifest_files(repo_root, tmp_path / "manifest-duplicate")
    first_line = (
        (staged / "manifest.sha256").read_text(encoding="utf-8").splitlines()[0]
    )
    with (staged / "manifest.sha256").open("a", encoding="utf-8") as manifest:
        manifest.write(f"{first_line}\n")

    with pytest.raises(ValueError, match="duplicate"):
        _read_manifest_sha256(staged)


def test_preflight_cli_never_prints_database_url(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for migration preflight")

    from scripts.candidate_integrity_preflight import main

    staged = _stage_migrations(
        repo_root,
        tmp_path / "through-037-cli",
        "037_crawl_profile_execution_backend.sql",
    )
    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_candidate_preflight_cli")
        database_url = cluster.database_url("egp_candidate_preflight_cli")
        apply_migrations(database_url=database_url, migrations_dir=staged)
        monkeypatch.setenv("DATABASE_URL", database_url)

        exit_code = main(
            [
                "--migrations-dir",
                str(repo_root / "packages/db/src/migrations"),
                "--phase",
                "pre",
            ]
        )
        output = capsys.readouterr().out

    assert exit_code == 0
    assert database_url not in output
    assert '"status":"ready"' in output
