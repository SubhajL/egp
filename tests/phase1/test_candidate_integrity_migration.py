"""PR-CANARY-03 F6: migration 039 candidate-attempt integrity (real PostgreSQL).

T1-T6 are the authoritative oracles for migration
``039_candidate_attempt_integrity.sql``: composite tenant foreign keys (backed
by new ``UNIQUE (tenant_id, id)`` parent keys), the typed ``terminal_reason``
vocabulary, the status/reason/project shape CHECK, and the 038-era data repair.
They run the REAL migration chain on a temporary PostgreSQL cluster and are
skipped only when local PostgreSQL binaries are absent.

The drift guards are pure-parse tests (never skipped): the LATEST
vocabulary-defining migration's CHECK list must equal
``CandidateTerminalReason`` exactly, every historical list must stay a subset
(so future vocabulary migrations never brick CI against applied history), and
the detail-terminal members must mirror ``ProjectDetailReason``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from egp_db.dev_postgres import postgres_binaries_available
from egp_shared_types.enums import CandidateTerminalReason


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "packages/db/src/migrations"
MIGRATION_039 = MIGRATIONS_DIR / "039_candidate_attempt_integrity.sql"


# ---------------------------------------------------------------------------
# Shared cluster + seed helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_cluster():
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries (initdb/pg_ctl/psql) not on PATH")
    from egp_db.dev_postgres import TempPostgresCluster

    with TempPostgresCluster() as cluster:
        yield cluster


def _fresh_migrated_database(pg_cluster) -> str:
    from egp_db.migration_runner import apply_migrations

    name = f"egp_f6_{uuid4().hex[:12]}"
    pg_cluster.create_database(name)
    url = pg_cluster.database_url(name)
    apply_migrations(database_url=url, migrations_dir=MIGRATIONS_DIR)
    return url


@pytest.fixture(scope="module")
def shared_migrated_db(pg_cluster) -> str:
    """One migrated database shared by T1-T5 (QCHECK perf finding: the full
    39-migration chain is expensive; per-test tenants keep isolation)."""
    return _fresh_migrated_database(pg_cluster)


@pytest.fixture()
def seeded_ids(shared_migrated_db) -> dict[str, str]:
    return _seed_two_tenants(shared_migrated_db)


def _seed_two_tenants(url: str) -> dict[str, str]:
    """Seed tenants A/B, one crawl run and one project each; return their ids."""
    from psycopg import connect

    ids: dict[str, str] = {}
    with connect(url) as connection:
        with connection.cursor() as cursor:
            for label in ("a", "b"):
                cursor.execute(
                    "INSERT INTO tenants (name, slug, plan_code)"
                    " VALUES (%s, %s, %s) RETURNING id",
                    (
                        f"F6 Tenant {label.upper()}",
                        f"f6-tenant-{label}-{uuid4().hex[:8]}",
                        "dev",
                    ),
                )
                tenant_id = str(cursor.fetchone()[0])
                ids[f"tenant_{label}"] = tenant_id
                cursor.execute(
                    "INSERT INTO crawl_runs (tenant_id, trigger_type)"
                    " VALUES (%s, 'manual') RETURNING id",
                    (tenant_id,),
                )
                ids[f"run_{label}"] = str(cursor.fetchone()[0])
                cursor.execute(
                    "INSERT INTO projects"
                    " (tenant_id, canonical_project_id, project_name)"
                    " VALUES (%s, %s, %s) RETURNING id",
                    (tenant_id, f"canon-{label}-{uuid4().hex[:8]}", f"Project {label}"),
                )
                ids[f"project_{label}"] = str(cursor.fetchone()[0])
        connection.commit()
    return ids


def _insert_candidate(
    cursor,
    *,
    tenant_id: str,
    run_id: str,
    status: str = "accepted",
    terminal_reason: str | None = None,
    project_id: str | None = None,
) -> str:
    key = f"key-{uuid4().hex}"
    cursor.execute(
        "INSERT INTO discovery_candidate_attempts"
        " (id, tenant_id, run_id, candidate_key, keyword,"
        "  candidate_status, terminal_reason, project_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            str(uuid4()),
            tenant_id,
            run_id,
            key,
            "kw",
            status,
            terminal_reason,
            project_id,
        ),
    )
    return key


# ---------------------------------------------------------------------------
# T1 / T2: composite tenant-run foreign key
# ---------------------------------------------------------------------------


def test_candidate_insert_rejects_cross_tenant_run(
    shared_migrated_db, seeded_ids
) -> None:
    from psycopg import connect
    from psycopg.errors import ForeignKeyViolation

    url, ids = shared_migrated_db, seeded_ids
    with connect(url) as connection:
        with connection.cursor() as cursor:
            # Positive control: same-tenant run reference is accepted.
            _insert_candidate(cursor, tenant_id=ids["tenant_a"], run_id=ids["run_a"])
        connection.commit()
        with pytest.raises(ForeignKeyViolation) as excinfo:
            with connection.cursor() as cursor:
                _insert_candidate(
                    cursor, tenant_id=ids["tenant_a"], run_id=ids["run_b"]
                )
        assert "dca_tenant_run_fkey" in str(excinfo.value)


def test_candidate_insert_rejects_nonexistent_run(
    shared_migrated_db, seeded_ids
) -> None:
    from psycopg import connect
    from psycopg.errors import ForeignKeyViolation

    url, ids = shared_migrated_db, seeded_ids
    with connect(url) as connection:
        with pytest.raises(ForeignKeyViolation):
            with connection.cursor() as cursor:
                _insert_candidate(
                    cursor, tenant_id=ids["tenant_a"], run_id=str(uuid4())
                )


# ---------------------------------------------------------------------------
# T3: composite tenant-project foreign key (cross-tenant, nonexistent, NULL)
# ---------------------------------------------------------------------------


def test_candidate_project_fk_same_tenant_only_null_and_nonexistent(
    shared_migrated_db, seeded_ids
) -> None:
    from psycopg import connect
    from psycopg.errors import ForeignKeyViolation

    url, ids = shared_migrated_db, seeded_ids
    with connect(url) as connection:
        # Cross-tenant project reference is rejected.
        with pytest.raises(ForeignKeyViolation) as excinfo:
            with connection.cursor() as cursor:
                _insert_candidate(
                    cursor,
                    tenant_id=ids["tenant_a"],
                    run_id=ids["run_a"],
                    status="persisted",
                    project_id=ids["project_b"],
                )
        assert "dca_tenant_project_fkey" in str(excinfo.value)
        connection.rollback()
        # Nonexistent project reference is rejected.
        with pytest.raises(ForeignKeyViolation):
            with connection.cursor() as cursor:
                _insert_candidate(
                    cursor,
                    tenant_id=ids["tenant_a"],
                    run_id=ids["run_a"],
                    status="persisted",
                    project_id=str(uuid4()),
                )
        connection.rollback()
        # Same-tenant project passes; NULL project passes.
        with connection.cursor() as cursor:
            _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                status="persisted",
                project_id=ids["project_a"],
            )
            _insert_candidate(cursor, tenant_id=ids["tenant_a"], run_id=ids["run_a"])
        connection.commit()


# ---------------------------------------------------------------------------
# T4: typed terminal_reason vocabulary
# ---------------------------------------------------------------------------


def test_terminal_reason_vocabulary_enforced(shared_migrated_db, seeded_ids) -> None:
    from psycopg import connect
    from psycopg.errors import CheckViolation

    url, ids = shared_migrated_db, seeded_ids
    with connect(url) as connection:
        with pytest.raises(CheckViolation) as excinfo:
            with connection.cursor() as cursor:
                _insert_candidate(
                    cursor,
                    tenant_id=ids["tenant_a"],
                    run_id=ids["run_a"],
                    status="failed",
                    terminal_reason="Boom: Traceback (most recent call last)",
                )
        assert "dca_terminal_reason_vocab_check" in str(excinfo.value)
        connection.rollback()
        with connection.cursor() as cursor:
            _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                status="failed",
                terminal_reason=CandidateTerminalReason.PERSIST_ERROR.value,
            )
        connection.commit()


# ---------------------------------------------------------------------------
# T5: full status/reason/project shape matrix (R4)
# ---------------------------------------------------------------------------

_STATUSES = ("accepted", "persisted", "dropped", "failed", "unknown")
_VALID_SHAPES = {
    ("accepted", None, None),
    ("persisted", None, "project"),
    ("dropped", "worker_lost", None),
    ("failed", "worker_lost", None),
    ("unknown", "worker_lost", None),
}


@pytest.mark.parametrize("status", _STATUSES)
@pytest.mark.parametrize("reason", (None, "worker_lost"))
@pytest.mark.parametrize("project", (None, "project"))
def test_status_shape_full_matrix(
    pg_cluster, shared_migrated_db, status, reason, project
) -> None:
    from psycopg import connect
    from psycopg.errors import CheckViolation

    url = shared_migrated_db
    ids = getattr(pg_cluster, "_f6_matrix_ids", None)
    if ids is None:
        ids = _seed_two_tenants(url)
        pg_cluster._f6_matrix_ids = ids

    expected_valid = (status, reason, project) in _VALID_SHAPES
    with connect(url) as connection:
        if expected_valid:
            with connection.cursor() as cursor:
                _insert_candidate(
                    cursor,
                    tenant_id=ids["tenant_a"],
                    run_id=ids["run_a"],
                    status=status,
                    terminal_reason=reason,
                    project_id=ids["project_a"] if project else None,
                )
            connection.commit()
        else:
            with pytest.raises(CheckViolation) as excinfo:
                with connection.cursor() as cursor:
                    _insert_candidate(
                        cursor,
                        tenant_id=ids["tenant_a"],
                        run_id=ids["run_a"],
                        status=status,
                        terminal_reason=reason,
                        project_id=ids["project_a"] if project else None,
                    )
            assert "dca_status_shape_check" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T6: 038-era data repair (stepwise upgrade)
# ---------------------------------------------------------------------------


def test_migration_039_repairs_pre_existing_038_data(pg_cluster, tmp_path) -> None:
    from psycopg import connect

    from egp_db.migration_runner import apply_migrations

    # Apply only 001..038 first (copy them into a temp migrations dir).
    pre_039_dir = tmp_path / "migrations_pre_039"
    pre_039_dir.mkdir()
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if sql_file.name.split("_", 1)[0] <= "038":
            shutil.copy(sql_file, pre_039_dir / sql_file.name)

    name = f"egp_f6_upg_{uuid4().hex[:8]}"
    pg_cluster.create_database(name)
    url = pg_cluster.database_url(name)
    apply_migrations(database_url=url, migrations_dir=pre_039_dir)
    ids = _seed_two_tenants(url)

    legacy: dict[str, str] = {}
    with connect(url) as connection:
        with connection.cursor() as cursor:
            # (a) failed row with raw exception text as its reason.
            legacy["free_text"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                status="failed",
                terminal_reason="Boom: Traceback (most recent call last)",
            )
            # (b) accepted row referencing a run that never existed.
            legacy["orphan_run"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=str(uuid4()),
            )
            # (c) persisted row referencing a project that never existed.
            orphan_project_uuid = str(uuid4())
            legacy["orphan_project"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                status="persisted",
                project_id=orphan_project_uuid,
            )
            # (d) cross-tenant parent: tenant A candidate on tenant B's run
            #     (legal pre-039; the tenant-matched repair must DELETE it).
            legacy["cross_tenant_run"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_b"],
            )
            # (e) typed-but-shape-invalid: accepted row carrying a reason.
            legacy["accepted_with_reason"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                terminal_reason="worker_lost",
            )
            # (f) shape-invalid: failed row carrying a VALID project reference
            #     (the displaced project UUID must be preserved, not dropped).
            legacy["failed_with_project"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                status="failed",
                terminal_reason="worker_lost",
                project_id=ids["project_a"],
            )
            # (g) shape-invalid: persisted row without a project but WITH a
            #     typed reason (the displaced reason must be preserved).
            legacy["persisted_no_project"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                status="persisted",
                terminal_reason="worker_lost",
            )
            # (h) fully valid typed terminal row: must pass through UNCHANGED.
            legacy["untouched_failed"] = _insert_candidate(
                cursor,
                tenant_id=ids["tenant_a"],
                run_id=ids["run_a"],
                status="failed",
                terminal_reason="worker_lost",
            )
        connection.commit()

    # Apply the full chain (only 039 is new by filename).
    apply_migrations(database_url=url, migrations_dir=MIGRATIONS_DIR)

    with connect(url) as connection:
        with connection.cursor() as cursor:

            def row_for(key: str):
                cursor.execute(
                    "SELECT candidate_status, terminal_reason, terminal_detail,"
                    " project_id FROM discovery_candidate_attempts"
                    " WHERE candidate_key = %s",
                    (key,),
                )
                return cursor.fetchone()

            # (a) reason normalized; original preserved in terminal_detail.
            status, reason, detail, project_id = row_for(legacy["free_text"])
            assert reason == "unclassified"
            assert detail == "Boom: Traceback (most recent call last)"

            # (b) orphan-run row deleted.
            assert row_for(legacy["orphan_run"]) is None

            # (c) orphan-project row repaired to unknown/unclassified/NULL,
            #     with the displaced project UUID preserved in the detail.
            status, reason, detail, project_id = row_for(legacy["orphan_project"])
            assert status == "unknown"
            assert reason == "unclassified"
            assert project_id is None
            assert detail == (
                "migration_039_orphan_project;"
                f" displaced_project_id={orphan_project_uuid}"
            )

            # (d) cross-tenant-parent row deleted (run lookup is tenant-matched).
            assert row_for(legacy["cross_tenant_run"]) is None

            # (e) reason cleared but PRESERVED into terminal_detail.
            status, reason, detail, project_id = row_for(legacy["accepted_with_reason"])
            assert status == "accepted"
            assert reason is None
            assert detail == "migration_039_displaced_reason=worker_lost"

            # (f) valid-project displaced from a failed row: preserved.
            status, reason, detail, project_id = row_for(legacy["failed_with_project"])
            assert status == "failed"
            assert reason == "worker_lost"
            assert project_id is None
            assert detail == (f"migration_039_displaced_project_id={ids['project_a']}")

            # (g) persisted-without-project: displaced reason preserved.
            status, reason, detail, project_id = row_for(legacy["persisted_no_project"])
            assert status == "unknown"
            assert reason == "unclassified"
            assert detail == (
                "migration_039_persisted_without_project; displaced_reason=worker_lost"
            )

            # (h) fully valid typed terminal row untouched.
            status, reason, detail, project_id = row_for(legacy["untouched_failed"])
            assert status == "failed"
            assert reason == "worker_lost"
            assert detail is None
            assert project_id is None

            # Every survivor satisfies both CHECKs (re-expressed as SQL).
            vocab = tuple(m.value for m in CandidateTerminalReason)
            cursor.execute(
                "SELECT count(*) FROM discovery_candidate_attempts WHERE NOT ("
                " (candidate_status = 'accepted' AND terminal_reason IS NULL"
                "  AND project_id IS NULL)"
                " OR (candidate_status = 'persisted' AND terminal_reason IS NULL"
                "  AND project_id IS NOT NULL)"
                " OR (candidate_status IN ('dropped','failed','unknown')"
                "  AND terminal_reason IS NOT NULL AND project_id IS NULL))",
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT count(*) FROM discovery_candidate_attempts"
                " WHERE terminal_reason IS NOT NULL"
                " AND terminal_reason != ALL(%s::text[])",
                (list(vocab),),
            )
            assert cursor.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# T15: enum <-> SQL vocabulary drift (pure parse; never skipped)
# ---------------------------------------------------------------------------


_VOCAB_LIST_PATTERN = r"terminal_reason\s+(?:NOT\s+)?IN\s*\(([^)]*)\)"


def _parse_vocab_lists(sql_text: str) -> list[set[str]]:
    return [
        {value.strip().strip("'") for value in raw.split(",")}
        for raw in re.findall(_VOCAB_LIST_PATTERN, sql_text, flags=re.IGNORECASE)
    ]


def test_terminal_reason_vocabulary_drift_guard() -> None:
    """R3(b) at the right altitude (QCHECK Tier-1 finding): the AUTHORITY is
    the LATEST migration that defines dca_terminal_reason_vocab_check — its
    CHECK list must equal the enum exactly. Historical/repair lists (039's
    NOT-IN repair predicate, and superseded CHECK definitions after a future
    re-creation) only need to remain SUBSETS of the enum, so extending the
    vocabulary via a new migration never bricks CI against applied history."""
    enum_values = {member.value for member in CandidateTerminalReason}

    # 039 itself must carry exactly two lists (repair NOT-IN + CHECK IN) —
    # dropping the repair predicate's explicit list would silently weaken the
    # upgrade-normalization contract (QCHECK Tier-2 finding).
    lists_039 = _parse_vocab_lists(MIGRATION_039.read_text(encoding="utf-8"))
    assert len(lists_039) == 2, (
        f"039 must contain exactly the repair NOT-IN list and the CHECK IN "
        f"list; found {len(lists_039)}"
    )
    assert lists_039[0] == lists_039[1], (
        "039 repair vocabulary must exactly match its CHECK vocabulary: "
        f"repair-only={sorted(lists_039[0] - lists_039[1])} "
        f"check-only={sorted(lists_039[1] - lists_039[0])}"
    )

    vocab_defining = [
        path
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
        if "dca_terminal_reason_vocab_check" in path.read_text(encoding="utf-8")
    ]
    assert vocab_defining, "no migration defines dca_terminal_reason_vocab_check"
    authority = vocab_defining[-1]
    authority_lists = _parse_vocab_lists(authority.read_text(encoding="utf-8"))
    # The CHECK list is the last IN list in the authority file (constraints
    # are added after any repair statements).
    assert authority_lists[-1] == enum_values, (
        f"{authority.name} CHECK vocabulary drifted from CandidateTerminalReason: "
        f"sql-only={sorted(authority_lists[-1] - enum_values)} "
        f"enum-only={sorted(enum_values - authority_lists[-1])}"
    )

    # Every list in every migration stays a subset of the enum (no stray
    # values were ever, or will ever be, valid vocabulary).
    for path in vocab_defining:
        for sql_values in _parse_vocab_lists(path.read_text(encoding="utf-8")):
            assert sql_values <= enum_values, (
                f"{path.name} contains non-vocabulary values: "
                f"{sorted(sql_values - enum_values)}"
            )


def test_detail_reasons_are_mirrored_in_terminal_vocabulary() -> None:
    """QCHECK Tier-1 finding: the detail-terminal members are hand-mirrored
    from ProjectDetailReason; this drift test makes an unmirrored addition a
    test-time failure instead of a crawl-time ValueError in F4's mapping."""
    from egp_shared_types.enums import ProjectDetailReason

    terminal_values = {member.value for member in CandidateTerminalReason}
    renames = {
        ProjectDetailReason.UNKNOWN.value: CandidateTerminalReason.DETAIL_UNKNOWN.value
    }
    for member in ProjectDetailReason:
        if member is ProjectDetailReason.VALID:
            continue
        expected = renames.get(member.value, member.value)
        assert expected in terminal_values, (
            f"ProjectDetailReason.{member.name} has no CandidateTerminalReason "
            f"mirror — F4's detail-to-terminal mapping would raise at crawl time"
        )
