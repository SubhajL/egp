"""Tenant-scoped unified audit log persistence and aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    String,
    Table,
    desc,
    func,
    insert,
    literal,
    select,
)
from sqlalchemy import Column
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.sql import Select, union_all

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_db.repositories.billing_repo import BILLING_EVENTS_TABLE
from egp_db.repositories.document_repo import DOCUMENT_REVIEW_EVENTS_TABLE
from egp_db.repositories.project_repo import PROJECTS_TABLE, PROJECT_STATUS_EVENTS_TABLE


METADATA = DB_METADATA

AUDIT_LOG_EVENTS_TABLE = Table(
    "audit_log_events",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("source", String, nullable=False),
    Column("entity_type", String, nullable=False),
    Column("entity_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=True),
    Column("document_id", UUID_SQL_TYPE, nullable=True),
    Column("actor_subject", String, nullable=True),
    Column("event_type", String, nullable=False),
    Column("summary", String, nullable=False),
    Column("metadata_json", JSON, nullable=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True, slots=True)
class AuditLogEventRecord:
    id: str
    tenant_id: str
    source: str
    entity_type: str
    entity_id: str
    project_id: str | None
    document_id: str | None
    actor_subject: str | None
    event_type: str
    summary: str
    metadata_json: dict[str, object] | None
    occurred_at: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    items: list[AuditLogEventRecord]
    total: int
    limit: int
    offset: int


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _audit_event_from_mapping(row: RowMapping) -> AuditLogEventRecord:
    metadata = row["metadata_json"] if isinstance(row["metadata_json"], dict) else None
    return AuditLogEventRecord(
        id=f"{row['source']}:{row['row_id']}",
        tenant_id=str(row["tenant_id"]),
        source=str(row["source"]),
        entity_type=str(row["entity_type"]),
        entity_id=str(row["entity_id"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        document_id=str(row["document_id"]) if row["document_id"] is not None else None,
        actor_subject=str(row["actor_subject"])
        if row["actor_subject"] is not None
        else None,
        event_type=str(row["event_type"]),
        summary=str(row["summary"]),
        metadata_json=metadata,
        occurred_at=_to_iso(row["occurred_at"]) or "",
        created_at=_to_iso(row["created_at"]) or "",
    )


def _direct_audit_select() -> Select:
    return select(
        AUDIT_LOG_EVENTS_TABLE.c.id.label("row_id"),
        AUDIT_LOG_EVENTS_TABLE.c.tenant_id.label("tenant_id"),
        AUDIT_LOG_EVENTS_TABLE.c.source.label("source"),
        AUDIT_LOG_EVENTS_TABLE.c.entity_type.label("entity_type"),
        AUDIT_LOG_EVENTS_TABLE.c.entity_id.label("entity_id"),
        AUDIT_LOG_EVENTS_TABLE.c.project_id.label("project_id"),
        AUDIT_LOG_EVENTS_TABLE.c.document_id.label("document_id"),
        AUDIT_LOG_EVENTS_TABLE.c.actor_subject.label("actor_subject"),
        AUDIT_LOG_EVENTS_TABLE.c.event_type.label("event_type"),
        AUDIT_LOG_EVENTS_TABLE.c.summary.label("summary"),
        AUDIT_LOG_EVENTS_TABLE.c.metadata_json.label("metadata_json"),
        AUDIT_LOG_EVENTS_TABLE.c.occurred_at.label("occurred_at"),
        AUDIT_LOG_EVENTS_TABLE.c.created_at.label("created_at"),
    )


def _project_audit_select() -> Select:
    return select(
        PROJECT_STATUS_EVENTS_TABLE.c.id.label("row_id"),
        PROJECTS_TABLE.c.tenant_id.label("tenant_id"),
        literal("project").label("source"),
        literal("project").label("entity_type"),
        PROJECT_STATUS_EVENTS_TABLE.c.project_id.label("entity_id"),
        PROJECT_STATUS_EVENTS_TABLE.c.project_id.label("project_id"),
        literal(None).label("document_id"),
        literal("system:worker").label("actor_subject"),
        literal("project.status_observed").label("event_type"),
        PROJECT_STATUS_EVENTS_TABLE.c.observed_status_text.label("summary"),
        PROJECT_STATUS_EVENTS_TABLE.c.raw_snapshot.label("metadata_json"),
        PROJECT_STATUS_EVENTS_TABLE.c.observed_at.label("occurred_at"),
        PROJECT_STATUS_EVENTS_TABLE.c.created_at.label("created_at"),
    ).select_from(
        PROJECT_STATUS_EVENTS_TABLE.join(
            PROJECTS_TABLE,
            PROJECTS_TABLE.c.id == PROJECT_STATUS_EVENTS_TABLE.c.project_id,
        )
    )


def _billing_audit_select() -> Select:
    return select(
        BILLING_EVENTS_TABLE.c.id.label("row_id"),
        BILLING_EVENTS_TABLE.c.tenant_id.label("tenant_id"),
        literal("billing").label("source"),
        literal("billing_record").label("entity_type"),
        BILLING_EVENTS_TABLE.c.billing_record_id.label("entity_id"),
        literal(None).label("project_id"),
        literal(None).label("document_id"),
        BILLING_EVENTS_TABLE.c.actor_subject.label("actor_subject"),
        BILLING_EVENTS_TABLE.c.event_type.label("event_type"),
        func.coalesce(
            BILLING_EVENTS_TABLE.c.note,
            func.replace(BILLING_EVENTS_TABLE.c.event_type, "_", "."),
        ).label("summary"),
        literal(None).label("metadata_json"),
        BILLING_EVENTS_TABLE.c.created_at.label("occurred_at"),
        BILLING_EVENTS_TABLE.c.created_at.label("created_at"),
    )


def _review_audit_select() -> Select:
    return select(
        DOCUMENT_REVIEW_EVENTS_TABLE.c.id.label("row_id"),
        DOCUMENT_REVIEW_EVENTS_TABLE.c.tenant_id.label("tenant_id"),
        literal("review").label("source"),
        literal("document_review").label("entity_type"),
        DOCUMENT_REVIEW_EVENTS_TABLE.c.review_id.label("entity_id"),
        DOCUMENT_REVIEW_EVENTS_TABLE.c.project_id.label("project_id"),
        literal(None).label("document_id"),
        DOCUMENT_REVIEW_EVENTS_TABLE.c.actor_subject.label("actor_subject"),
        DOCUMENT_REVIEW_EVENTS_TABLE.c.event_type.label("event_type"),
        func.coalesce(
            DOCUMENT_REVIEW_EVENTS_TABLE.c.note,
            DOCUMENT_REVIEW_EVENTS_TABLE.c.event_type,
        ).label("summary"),
        literal(None).label("metadata_json"),
        DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at.label("occurred_at"),
        DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at.label("created_at"),
    )


class SqlAuditRepository:
    """Persist direct audit rows and expose a unified tenant-scoped feed."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def record_event(
        self,
        *,
        tenant_id: str,
        source: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        summary: str,
        actor_subject: str | None = None,
        project_id: str | None = None,
        document_id: str | None = None,
        metadata_json: dict[str, object] | None = None,
        occurred_at: str | None = None,
    ) -> AuditLogEventRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_entity_id = normalize_uuid_string(entity_id)
        normalized_project_id = (
            normalize_uuid_string(project_id) if project_id is not None else None
        )
        normalized_document_id = (
            normalize_uuid_string(document_id) if document_id is not None else None
        )
        event_time = datetime.fromisoformat(occurred_at) if occurred_at else _now()
        audit_id = str(uuid4())
        with self._engine.begin() as connection:
            connection.execute(
                insert(AUDIT_LOG_EVENTS_TABLE).values(
                    id=audit_id,
                    tenant_id=normalized_tenant_id,
                    source=str(source).strip(),
                    entity_type=str(entity_type).strip(),
                    entity_id=normalized_entity_id,
                    project_id=normalized_project_id,
                    document_id=normalized_document_id,
                    actor_subject=str(actor_subject).strip() if actor_subject else None,
                    event_type=str(event_type).strip(),
                    summary=str(summary).strip(),
                    metadata_json=metadata_json,
                    occurred_at=event_time,
                    created_at=_now(),
                )
            )
            row = (
                connection.execute(
                    _direct_audit_select().where(
                        AUDIT_LOG_EVENTS_TABLE.c.id == audit_id
                    )
                )
                .mappings()
                .one()
            )
        return _audit_event_from_mapping(row)

    def list_events(
        self,
        *,
        tenant_id: str,
        source: str | None = None,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditLogPage:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        combined = union_all(
            _direct_audit_select(),
            _project_audit_select(),
            _billing_audit_select(),
            _review_audit_select(),
        ).subquery("audit_events")
        filtered = select(combined).where(combined.c.tenant_id == normalized_tenant_id)
        if source is not None:
            filtered = filtered.where(combined.c.source == str(source).strip())
        if entity_type is not None:
            filtered = filtered.where(
                combined.c.entity_type == str(entity_type).strip()
            )
        ordered = filtered.order_by(
            desc(combined.c.occurred_at),
            desc(combined.c.created_at),
            desc(combined.c.source),
        )
        with self._engine.connect() as connection:
            total = int(
                connection.execute(
                    select(func.count()).select_from(
                        filtered.subquery("audit_filtered")
                    )
                ).scalar_one()
            )
            rows = (
                connection.execute(
                    ordered.limit(max(1, int(limit))).offset(max(0, int(offset)))
                )
                .mappings()
                .all()
            )
        return AuditLogPage(
            items=[_audit_event_from_mapping(row) for row in rows],
            total=total,
            limit=max(1, int(limit)),
            offset=max(0, int(offset)),
        )


def create_audit_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlAuditRepository:
    return SqlAuditRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
