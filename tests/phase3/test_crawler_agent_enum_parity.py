"""The shared enums must stay in lockstep with migration 034's CHECK constraints.

`packages/shared-types/AGENTS.md` requires cross-service vocabularies to live in
`egp_shared_types.enums` and to stay synchronised with the database CHECK
constraints. Nothing in the repository enforced that, so the two could drift
silently: an enum value the database rejects would fail only at runtime, and a
database value with no enum member would be unrepresentable in code.

This test is that missing oracle. It parses the CHECK vocabularies straight out of
the migration SQL rather than restating them, so a change to either side that is
not mirrored fails here.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from egp_shared_types.enums import (
    AgentContractVersion,
    AgentInboxErrorCode,
    AgentInboxStatus,
    DiscoveryJobStatus,
    ExecutionBackend,
)


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "packages/db/src/migrations/034_crawler_agent_results.sql"
)


def _check_vocabulary(column: str) -> set[str]:
    """Extract the quoted allow-list for `<column> IN (...)` from migration 034."""

    sql = MIGRATION.read_text(encoding="utf-8")
    match = re.search(rf"{re.escape(column)}\s+IN\s*\(([^)]*)\)", sql, re.IGNORECASE)
    if match is None:  # pragma: no cover - guards a malformed migration
        raise AssertionError(f"no CHECK vocabulary found for {column} in {MIGRATION}")
    return set(re.findall(r"'([^']+)'", match.group(1)))


@pytest.mark.parametrize(
    ("column", "enum_type"),
    [
        ("execution_backend", ExecutionBackend),
        ("job_status", DiscoveryJobStatus),
        ("contract_version", AgentContractVersion),
        ("inbox_status", AgentInboxStatus),
        ("last_error_code", AgentInboxErrorCode),
    ],
)
def test_enum_matches_migration_check_vocabulary(column: str, enum_type) -> None:
    assert {member.value for member in enum_type} == _check_vocabulary(column)


def test_inbox_table_columns_match_migration_034() -> None:
    """The SQLAlchemy table and the SQL migration must declare the same columns.

    Tests bootstrap their schema from SQLAlchemy metadata while production applies
    the SQL migrations, so the two can drift silently: a column present in only one
    of them makes tests pass against a schema production does not have. There is no
    general migration-vs-metadata oracle in this repository, so this pins the one
    table U7 introduces.
    """

    from egp_db.repositories.crawler_agent_repo import CRAWLER_AGENT_RESULTS_TABLE

    migrations_dir = Path(__file__).resolve().parents[2] / "packages/db/src/migrations"
    body = (migrations_dir / "034_crawler_agent_results.sql").read_text(
        encoding="utf-8"
    ).split("CREATE TABLE crawler_agent_results (", 1)[1]

    declared: set[str] = set()
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("--") or line.upper().startswith("CONSTRAINT"):
            continue
        match = re.match(
            r"([a-z0-9_]+)\s+(UUID|TEXT|JSONB|INTEGER|TIMESTAMPTZ)\b", line
        )
        if match:
            declared.add(match.group(1))

    assert declared, "failed to parse any column out of migration 034"

    # Later migrations legitimately extend this table (036 adds the shadow
    # delivery columns), so the oracle has to follow them. Reading 034 alone was a
    # technique limitation, not the intent: the property under test is
    # "metadata and SQL declare the same columns", and pinning it to one file
    # would force either deleting the oracle or freezing the table forever.
    for path in sorted(migrations_dir.glob("*.sql")):
        # Statement-scoped: a migration may ALTER several tables (034 itself also
        # alters discovery_jobs), so matching per file would pull in columns that
        # belong to a different table entirely.
        for statement in path.read_text(encoding="utf-8").split(";"):
            if not re.search(
                r"ALTER\s+TABLE\s+crawler_agent_results\b", statement, re.IGNORECASE
            ):
                continue
            for match in re.finditer(
                r"ADD\s+COLUMN\s+([a-z0-9_]+)\s+"
                r"(UUID|TEXT|JSONB|INTEGER|TIMESTAMPTZ)\b",
                statement,
                re.IGNORECASE,
            ):
                declared.add(match.group(1))

    modelled = {column.name for column in CRAWLER_AGENT_RESULTS_TABLE.columns}

    assert declared == modelled
