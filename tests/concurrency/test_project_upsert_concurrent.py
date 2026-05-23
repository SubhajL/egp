from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

from egp_db.repositories.project_repo import (
    SqlProjectRepository,
    build_project_upsert_record,
)
from egp_shared_types.enums import ProcurementType, ProjectState


TENANT_ID = "11111111-1111-1111-1111-111111111111"


class RaceHarnessProjectRepository(SqlProjectRepository):
    def __init__(
        self,
        *,
        participant_count: int,
        database_url: str,
        bootstrap_schema: bool = True,
    ) -> None:
        super().__init__(database_url=database_url, bootstrap_schema=bootstrap_schema)
        self._race_barrier = threading.Barrier(participant_count)

    def _find_existing_row(self, connection, *, tenant_id: str, record):
        row = super()._find_existing_row(
            connection,
            tenant_id=tenant_id,
            record=record,
        )
        if row is None:
            self._race_barrier.wait(timeout=10)
        return row


def test_concurrent_project_upsert_is_idempotent(tmp_path) -> None:
    database_path = tmp_path / "phase1.sqlite3"
    participant_count = 5
    repository = RaceHarnessProjectRepository(
        participant_count=participant_count,
        database_url=f"sqlite+pysqlite:///{database_path}",
        bootstrap_schema=True,
    )
    record = build_project_upsert_record(
        tenant_id=TENANT_ID,
        project_number="EGP-2026-CONCURRENT",
        search_name="Concurrent Project",
        detail_name="Concurrent Project",
        project_name="Concurrent Project",
        organization_name="Concurrency Department",
        proposal_submission_date="2026-05-24",
        budget_amount="1000",
        procurement_type=ProcurementType.GOODS,
        project_state=ProjectState.OPEN_INVITATION,
    )

    def upsert_once() -> str:
        project = repository.upsert_project(
            record,
            source_status_text="ประกาศเชิญชวน",
            observed_at="2026-05-24T00:00:00+00:00",
        )
        return project.id

    with ThreadPoolExecutor(max_workers=participant_count) as executor:
        project_ids = list(
            executor.map(lambda _: upsert_once(), range(participant_count))
        )

    with sqlite3.connect(database_path) as connection:
        project_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM projects
            WHERE tenant_id = ? AND canonical_project_id = ?
            """,
            (TENANT_ID, record.canonical_project_id),
        ).fetchone()[0]
        alias_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM project_aliases
            WHERE project_id = ?
            """,
            (project_ids[0],),
        ).fetchone()[0]
        status_event_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM project_status_events
            WHERE project_id = ?
              AND normalized_status = ?
              AND observed_at = ?
            """,
            (
                project_ids[0],
                ProjectState.OPEN_INVITATION.value,
                "2026-05-24 00:00:00.000000",
            ),
        ).fetchone()[0]

    assert set(project_ids) == {project_ids[0]}
    assert project_count == 1
    assert alias_count == 4
    assert status_event_count == 1
