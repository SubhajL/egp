"""Regression: `/ready` must find the migrations directory in a BUILT image.

Found by deploying to production, not by any test.

`_default_migrations_dir()` was `Path(__file__).resolve().parents[5] /
"packages/db/src/migrations"` — fixed path arithmetic that assumes the module sits
at a known depth below the repo root. That holds for a source checkout
(`<root>/apps/api/src/egp_api/services/…` → 5 up is `<root>`) and silently breaks
once the package is *installed*, because
`<root>/.venv/lib/python3.12/site-packages/egp_api/services/…` → 5 up is
`<root>/.venv`.

The runtime images install the packages rather than mounting the source, so in
production this resolved to `/app/.venv/packages/db/src/migrations`, which does not
exist. `/ready` returned 503 `migration_manifest_unavailable` — permanently, and
for a reason that had nothing to do with the database or the migrations. The API
container was marked unhealthy.

Nothing caught it because every test runs from a source checkout, where the wrong
arithmetic happens to give the right answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from egp_api.services.readiness_service import (
    ReadinessService,
    _default_migrations_dir,
    resolve_migrations_dir,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_default_migrations_dir_exists_from_a_source_checkout() -> None:
    """Baseline: the resolution must keep working where it already worked."""

    resolved = _default_migrations_dir()
    assert resolved.is_dir(), f"{resolved} is not a directory"
    assert any(resolved.glob("*.sql")), f"no migrations found under {resolved}"


def test_resolution_finds_the_migrations_when_the_package_is_installed(
    tmp_path: Path,
) -> None:
    """The production layout, reproduced.

    An installed package sits at `<root>/.venv/lib/pythonX/site-packages/egp_api/…`.
    Fixed `parents[5]` arithmetic lands on `<root>/.venv` and finds nothing; the
    resolver must still locate `<root>/packages/db/src/migrations`.
    """

    root = tmp_path / "app"
    migrations = root / "packages/db/src/migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_initial_schema.sql").write_text("SELECT 1;", encoding="utf-8")

    installed_module = (
        root / ".venv/lib/python3.12/site-packages/egp_api/services/readiness_service.py"
    )
    installed_module.parent.mkdir(parents=True)
    installed_module.write_text("", encoding="utf-8")

    resolved = resolve_migrations_dir(module_file=installed_module)
    assert resolved == migrations


def test_resolution_still_works_from_a_source_layout(tmp_path: Path) -> None:
    """Control: without it, a resolver that only handled the installed layout
    would pass the test above and break every developer checkout."""

    root = tmp_path / "repo"
    migrations = root / "packages/db/src/migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_initial_schema.sql").write_text("SELECT 1;", encoding="utf-8")

    source_module = (
        root / "apps/api/src/egp_api/services/readiness_service.py"
    )
    source_module.parent.mkdir(parents=True)
    source_module.write_text("", encoding="utf-8")

    assert resolve_migrations_dir(module_file=source_module) == migrations


def test_an_explicit_env_override_wins(tmp_path: Path, monkeypatch) -> None:
    """An operator escape hatch for a layout nobody anticipated — which is exactly
    the class of problem this bug was."""

    migrations = tmp_path / "custom/migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_initial_schema.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setenv("EGP_MIGRATIONS_DIR", str(migrations))

    assert resolve_migrations_dir() == migrations


def test_readiness_reports_manifest_unavailable_only_when_it_truly_is(
    tmp_path: Path,
) -> None:
    """The failure mode this bug produced was indistinguishable from a real
    missing manifest, so the reason code stays meaningful only if it is reserved
    for the genuine case."""

    empty = tmp_path / "no-migrations"
    empty.mkdir()
    service = ReadinessService(
        database_url="postgresql://unused/unused", migrations_dir=empty
    )
    snapshot = service.build_readiness_snapshot()
    assert snapshot.reason == "migration_manifest_unavailable"


@pytest.mark.parametrize("depth", [1, 3, 7])
def test_resolution_is_not_sensitive_to_module_depth(tmp_path: Path, depth: int) -> None:
    """The original defect was depth sensitivity. Pin that it is gone rather than
    trusting that the two layouts above are the only ones that will ever exist."""

    root = tmp_path / f"root{depth}"
    migrations = root / "packages/db/src/migrations"
    migrations.mkdir(parents=True)
    (migrations / "001_initial_schema.sql").write_text("SELECT 1;", encoding="utf-8")

    nested = root.joinpath(*[f"level{i}" for i in range(depth)])
    nested.mkdir(parents=True, exist_ok=True)
    module = nested / "readiness_service.py"
    module.write_text("", encoding="utf-8")

    assert resolve_migrations_dir(module_file=module) == migrations
