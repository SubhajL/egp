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
