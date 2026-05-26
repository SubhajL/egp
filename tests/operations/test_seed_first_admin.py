"""TDD coverage for ``scripts/seed_first_admin.py``.

Helper-direct tests use ``TempPostgresCluster`` with the canonical
schema applied via the migration runner. CLI subprocess tests verify
argparse contract, password input policy, and JSON output shape.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "seed_first_admin.py"

# Allow `from seed_first_admin import ...` by adding scripts/ to sys.path.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from egp_db.dev_postgres import (  # noqa: E402
    TempPostgresCluster,
    postgres_binaries_available,
)
from egp_db.migration_runner import apply_migrations  # noqa: E402
from egp_db.repositories.auth_repo import verify_password  # noqa: E402

import seed_first_admin as seeder  # noqa: E402


VALID_PASSWORD = "correct-horse-battery-staple"  # >= 12 chars
SECOND_PASSWORD = "another-strong-passphrase-2026"


def _pg_or_skip() -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries not available")


def _seed_clean_db(cluster: TempPostgresCluster, database_name: str) -> str:
    cluster.create_database(database_name)
    database_url = cluster.database_url(database_name)
    apply_migrations(
        database_url=database_url,
        migrations_dir=REPO_ROOT / "packages/db/src/migrations",
    )
    return database_url


# ---------------------------------------------------------------------------
# Helper-direct tests (require Postgres)
# ---------------------------------------------------------------------------


def test_seed_first_admin_creates_tenant_and_active_verified_owner() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_1")
        result = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Acme Procurement",
            tenant_slug="acme-procurement",
            admin_email="ops@acme.example",
            admin_full_name="Acme Ops",
            password=VALID_PASSWORD,
        )
        assert result.status == "created"
        assert result.tenant_slug == "acme-procurement"
        assert result.admin_email == "ops@acme.example"
        assert result.admin_count == 1
        assert result.user_id is not None
        from psycopg import connect

        with connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT role, status, email_verified_at, mfa_enabled, password_hash "
                "FROM users WHERE id = %s",
                (result.user_id,),
            )
            row = cur.fetchone()
            assert row is not None
            role, status, email_verified_at, mfa_enabled, password_hash = row
            assert role == "owner"
            assert status == "active"
            assert email_verified_at is not None
            assert mfa_enabled is False
            assert verify_password(VALID_PASSWORD, password_hash) is True


def test_seed_first_admin_reuses_existing_tenant_without_mutating_metadata() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_reuse")
        # First seed creates tenant + owner
        first = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Original Name",
            tenant_slug="acme",
            admin_email="first@acme.example",
            admin_full_name="First Owner",
            password=VALID_PASSWORD,
            plan_code="free",
        )
        # Second seed with different metadata MUST refuse (admin exists)
        # but the call path must reuse the existing tenant row (not mutate).
        from psycopg import connect

        with connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET role='viewer' WHERE id = %s", (first.user_id,)
            )
            conn.commit()
        # Now no owner/admin → second invocation can re-seed
        second = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Tried New Name",  # different
            tenant_slug="acme",
            admin_email="second@acme.example",
            admin_full_name="Second Owner",
            password=SECOND_PASSWORD,
            plan_code="monthly_membership",  # different
        )
        assert second.tenant_id == first.tenant_id
        with connect(database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT name, plan_code FROM tenants WHERE slug='acme'")
            name, plan_code = cur.fetchone()
            # Tenant metadata MUST NOT be mutated on reuse
            assert name == "Original Name"
            assert plan_code == "free"


def test_seed_first_admin_refuses_when_tenant_has_owner_regardless_of_status() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_refuse_owner")
        first = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Acme",
            tenant_slug="acme",
            admin_email="owner@acme.example",
            admin_full_name="Owner",
            password=VALID_PASSWORD,
        )
        # Suspend the owner — refusal must still trigger
        from psycopg import connect

        with connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET status='suspended' WHERE id=%s", (first.user_id,)
            )
            conn.commit()
        second = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Acme",
            tenant_slug="acme",
            admin_email="other@acme.example",
            admin_full_name="Other",
            password=SECOND_PASSWORD,
        )
        assert second.status == "already-seeded"
        assert second.admin_count >= 1
        assert second.tenant_id == first.tenant_id


def test_seed_first_admin_refuses_when_tenant_has_admin_regardless_of_status() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_refuse_admin")
        first = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Acme",
            tenant_slug="acme",
            admin_email="admin@acme.example",
            admin_full_name="Admin",
            password=VALID_PASSWORD,
            role="admin",
        )
        second = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Acme",
            tenant_slug="acme",
            admin_email="other@acme.example",
            admin_full_name="Other",
            password=SECOND_PASSWORD,
        )
        assert second.status == "already-seeded"
        assert second.tenant_id == first.tenant_id


def test_seed_first_admin_creates_when_only_analyst_or_viewer_exists() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_lower_role")
        # Manually create a tenant + viewer
        from psycopg import connect

        with connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (name, slug, plan_code) VALUES (%s, %s, %s) "
                "RETURNING id",
                ("Acme", "acme", "free"),
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO users (tenant_id, email, full_name, role, status) "
                "VALUES (%s, %s, %s, %s, %s)",
                (tenant_id, "viewer@acme.example", "Viewer", "viewer", "active"),
            )
            conn.commit()
        result = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Acme",
            tenant_slug="acme",
            admin_email="ops@acme.example",
            admin_full_name="Ops",
            password=VALID_PASSWORD,
        )
        assert result.status == "created"
        assert result.tenant_id == tenant_id


def test_seed_first_admin_allows_admin_in_different_tenant() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_multi_tenant")
        seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Acme",
            tenant_slug="acme",
            admin_email="ops@acme.example",
            admin_full_name="Acme Ops",
            password=VALID_PASSWORD,
        )
        result = seeder.seed_first_admin(
            database_url=database_url,
            tenant_name="Beta Co",
            tenant_slug="beta",
            admin_email="ops@beta.example",
            admin_full_name="Beta Ops",
            password=SECOND_PASSWORD,
        )
        assert result.status == "created"
        assert result.tenant_slug == "beta"


def test_seed_first_admin_refuses_duplicate_email_belonging_to_non_admin() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_dup_email")
        from psycopg import connect

        with connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (name, slug, plan_code) VALUES (%s, %s, %s) "
                "RETURNING id",
                ("Acme", "acme", "free"),
            )
            tenant_id = str(cur.fetchone()[0])
            cur.execute(
                "INSERT INTO users (tenant_id, email, full_name, role, status) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    tenant_id,
                    "ops@acme.example",
                    "Existing Analyst",
                    "analyst",
                    "active",
                ),
            )
            conn.commit()
        with pytest.raises(ValueError, match="email already used"):
            seeder.seed_first_admin(
                database_url=database_url,
                tenant_name="Acme",
                tenant_slug="acme",
                admin_email="ops@acme.example",  # collides with analyst
                admin_full_name="Ops",
                password=VALID_PASSWORD,
            )


def test_seed_first_admin_concurrent_runs_only_one_creates_admin() -> None:
    _pg_or_skip()
    import threading

    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_concurrent")
        results: list[seeder.SeedFirstAdminResult] = []
        errors: list[Exception] = []

        def worker(email: str) -> None:
            try:
                results.append(
                    seeder.seed_first_admin(
                        database_url=database_url,
                        tenant_name="Acme",
                        tenant_slug="acme",
                        admin_email=email,
                        admin_full_name="Ops",
                        password=VALID_PASSWORD,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(f"ops{i}@acme.example",))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Idempotency contract: concurrent runs MUST NEVER error.
        # Exactly one wins with status="created"; the other two return
        # "already-seeded" with the same tenant_id; and the DB ends up
        # with exactly one owner/admin row.
        assert errors == [], f"concurrent runs must not error, got: {errors}"
        created = [r for r in results if r.status == "created"]
        already = [r for r in results if r.status == "already-seeded"]
        assert len(created) == 1
        assert len(already) == 2
        tenant_ids = {r.tenant_id for r in results}
        assert len(tenant_ids) == 1, (
            f"all concurrent runs must share one tenant_id, got: {tenant_ids}"
        )
        from psycopg import connect

        with connect(database_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE role IN ('owner', 'admin')"
            )
            admin_count = int(cur.fetchone()[0])
        assert admin_count == 1, (
            f"expected exactly 1 owner/admin in DB, got {admin_count}"
        )


# ---------------------------------------------------------------------------
# Input-validation tests (no DB needed)
# ---------------------------------------------------------------------------


def test_seed_first_admin_rejects_password_shorter_than_12() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_pw_short")
        with pytest.raises(ValueError, match="password"):
            seeder.seed_first_admin(
                database_url=database_url,
                tenant_name="Acme",
                tenant_slug="acme",
                admin_email="ops@acme.example",
                admin_full_name="Ops",
                password="short",
            )


def test_seed_first_admin_rejects_empty_or_whitespace_slug() -> None:
    with pytest.raises(ValueError, match="slug"):
        seeder._validate_slug("")
    with pytest.raises(ValueError, match="slug"):
        seeder._validate_slug("   ")
    with pytest.raises(ValueError, match="slug"):
        seeder._validate_slug("has spaces")
    assert seeder._validate_slug("acme-procurement") == "acme-procurement"


def test_seed_first_admin_rejects_invalid_email() -> None:
    with pytest.raises(ValueError, match="email"):
        seeder._validate_email("not-an-email")
    with pytest.raises(ValueError, match="email"):
        seeder._validate_email("")
    assert seeder._validate_email("ops@acme.example") == "ops@acme.example"


def test_seed_first_admin_rejects_invalid_role() -> None:
    with pytest.raises(ValueError, match="role"):
        seeder._validate_role("viewer")
    with pytest.raises(ValueError, match="role"):
        seeder._validate_role("hacker")
    assert seeder._validate_role("owner") == "owner"
    assert seeder._validate_role("admin") == "admin"


def test_seed_first_admin_rejects_invalid_plan_code() -> None:
    with pytest.raises(ValueError, match="plan_code"):
        seeder._validate_plan_code("")
    with pytest.raises(ValueError, match="plan_code"):
        seeder._validate_plan_code("has spaces")
    assert seeder._validate_plan_code("monthly_membership") == "monthly_membership"


# ---------------------------------------------------------------------------
# CLI tests (use main() with injected streams; one subprocess smoke)
# ---------------------------------------------------------------------------


def _run_main(
    argv: list[str], env: dict[str, str], stdin: str = ""
) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    in_stream = io.StringIO(stdin)
    code = seeder.main(argv=argv, env=env, stdin=in_stream, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_cli_help_exits_zero_and_mentions_required_args() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    out = completed.stdout
    assert "--tenant-slug" in out
    assert "--admin-email" in out
    assert "--password-stdin" in out


def test_cli_rejects_password_argv_flag_with_clear_error() -> None:
    code, _, err = _run_main(
        argv=[
            "--tenant-name",
            "Acme",
            "--tenant-slug",
            "acme",
            "--admin-email",
            "ops@acme.example",
            "--admin-full-name",
            "Ops",
            "--database-url",
            "postgresql://x@y/z",
            "--password",
            "abcdefghijkl",
        ],
        env={},
    )
    assert code != 0
    combined = err.lower()
    assert "--password" in combined or "password" in combined
    assert "stdin" in combined or "env" in combined


def test_cli_reads_password_from_stdin_stripping_trailing_newline() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_cli_stdin")
        code, out, _err = _run_main(
            argv=[
                "--tenant-name",
                "Acme",
                "--tenant-slug",
                "acme",
                "--admin-email",
                "ops@acme.example",
                "--admin-full-name",
                "Ops",
                "--database-url",
                database_url,
                "--password-stdin",
            ],
            env={},
            stdin=VALID_PASSWORD + "\n",
        )
        assert code == 0, out
        payload = json.loads(out)
        assert payload["status"] == "created"


def test_cli_reads_password_from_env_var() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_cli_env")
        code, out, _err = _run_main(
            argv=[
                "--tenant-name",
                "Acme",
                "--tenant-slug",
                "acme",
                "--admin-email",
                "ops@acme.example",
                "--admin-full-name",
                "Ops",
                "--database-url",
                database_url,
            ],
            env={"EGP_FIRST_ADMIN_PASSWORD": VALID_PASSWORD},
        )
        assert code == 0, out
        payload = json.loads(out)
        assert payload["status"] == "created"
        assert "password" not in payload  # never echoed
        assert "password_hash" not in payload


def test_cli_emits_json_block_on_stdout_on_success() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_cli_json")
        code, out, _err = _run_main(
            argv=[
                "--tenant-name",
                "Acme",
                "--tenant-slug",
                "acme",
                "--admin-email",
                "ops@acme.example",
                "--admin-full-name",
                "Ops",
                "--database-url",
                database_url,
            ],
            env={"EGP_FIRST_ADMIN_PASSWORD": VALID_PASSWORD},
        )
        assert code == 0
        payload = json.loads(out)
        assert set(payload.keys()) >= {
            "status",
            "tenant_id",
            "user_id",
            "tenant_slug",
            "admin_email",
            "admin_count",
        }


def test_cli_emits_database_target_preview_to_stderr_before_insert() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_target_preview")
        _, _, err = _run_main(
            argv=[
                "--tenant-name",
                "Acme",
                "--tenant-slug",
                "acme",
                "--admin-email",
                "ops@acme.example",
                "--admin-full-name",
                "Ops",
                "--database-url",
                database_url,
            ],
            env={"EGP_FIRST_ADMIN_PASSWORD": VALID_PASSWORD},
        )
        combined = err.lower()
        assert "host=" in combined or "host:" in combined
        assert "dbname=" in combined or "dbname:" in combined


def test_cli_emits_already_seeded_status_on_idempotent_rerun() -> None:
    _pg_or_skip()
    with TempPostgresCluster() as cluster:
        database_url = _seed_clean_db(cluster, "seed_admin_idempotent")
        argv = [
            "--tenant-name",
            "Acme",
            "--tenant-slug",
            "acme",
            "--admin-email",
            "ops@acme.example",
            "--admin-full-name",
            "Ops",
            "--database-url",
            database_url,
        ]
        env = {"EGP_FIRST_ADMIN_PASSWORD": VALID_PASSWORD}
        code1, out1, _ = _run_main(argv=argv, env=env)
        code2, out2, _ = _run_main(argv=argv, env=env)
        assert code1 == 0 and code2 == 0
        first = json.loads(out1)
        second = json.loads(out2)
        assert first["status"] == "created"
        assert second["status"] == "already-seeded"
        assert second["tenant_id"] == first["tenant_id"]
        # info-leak safety: do NOT echo the existing admin's email when refusing
        assert second.get("admin_email") in (None, "")


def test_cli_exits_nonzero_when_no_password_provided() -> None:
    code, _, err = _run_main(
        argv=[
            "--tenant-name",
            "Acme",
            "--tenant-slug",
            "acme",
            "--admin-email",
            "ops@acme.example",
            "--admin-full-name",
            "Ops",
            "--database-url",
            "postgresql://x@y/z",
        ],
        env={},  # no env var, no stdin flag
    )
    assert code != 0
    assert "password" in err.lower()


def test_cli_rejects_invalid_email_via_argparse() -> None:
    code, _, err = _run_main(
        argv=[
            "--tenant-name",
            "Acme",
            "--tenant-slug",
            "acme",
            "--admin-email",
            "not-an-email",
            "--admin-full-name",
            "Ops",
            "--database-url",
            "postgresql://x@y/z",
        ],
        env={"EGP_FIRST_ADMIN_PASSWORD": VALID_PASSWORD},
    )
    assert code != 0
    assert "email" in err.lower()
