"""Tenant-scoped project persistence and alias deduplication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    and_,
    desc,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy import Column
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_db.repositories.document_repo import DOCUMENT_DIFFS_TABLE, DOCUMENTS_TABLE
from egp_crawler_core.canonical_id import build_project_aliases, generate_canonical_id
from egp_crawler_core.project_lifecycle import transition_state
from egp_shared_types.enums import ClosedReason, ProcurementType, ProjectState


@dataclass(frozen=True, slots=True)
class ProjectUpsertRecord:
    tenant_id: str
    canonical_project_id: str
    project_name: str
    organization_name: str
    project_number: str | None
    procurement_type: ProcurementType
    proposal_submission_date: str | None
    budget_amount: str | None
    project_state: ProjectState
    closed_reason: ClosedReason | None
    aliases: list[tuple[str, str]]


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    id: str
    tenant_id: str
    canonical_project_id: str
    project_number: str | None
    project_name: str
    organization_name: str
    procurement_type: ProcurementType
    proposal_submission_date: str | None
    budget_amount: str | None
    project_state: ProjectState
    closed_reason: ClosedReason | None
    source_status_text: str | None
    has_changed_tor: bool
    first_seen_at: str
    last_seen_at: str
    last_changed_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectAliasRecord:
    id: str
    project_id: str
    alias_type: str
    alias_value: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProjectStatusEventRecord:
    id: str
    project_id: str
    observed_status_text: str
    normalized_status: str | None
    observed_at: str
    run_id: str | None
    raw_snapshot: dict[str, object] | None
    created_at: str


@dataclass(frozen=True, slots=True)
class ProjectDetail:
    project: ProjectRecord
    aliases: list[ProjectAliasRecord]
    status_events: list[ProjectStatusEventRecord]


@dataclass(frozen=True, slots=True)
class ProjectPage:
    items: list[ProjectRecord]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class DashboardRecentProjectChangeRecord:
    project_id: str
    project_name: str
    project_state: str
    last_changed_at: str


@dataclass(frozen=True, slots=True)
class DashboardWinnerProjectRecord:
    project_id: str
    project_name: str
    project_state: str
    awarded_at: str


@dataclass(frozen=True, slots=True)
class DashboardDailyDiscoveryPoint:
    date: str
    count: int


@dataclass(frozen=True, slots=True)
class DashboardStateBreakdownPoint:
    bucket: str
    count: int


@dataclass(frozen=True, slots=True)
class DashboardProjectSummary:
    active_projects: int
    discovered_today: int
    winner_projects_this_week: int
    closed_today: int
    changed_tor_projects: int
    recent_changes: list[DashboardRecentProjectChangeRecord]
    winner_projects: list[DashboardWinnerProjectRecord]
    daily_discovery: list[DashboardDailyDiscoveryPoint]
    project_state_breakdown: list[DashboardStateBreakdownPoint]


METADATA = DB_METADATA

PROJECTS_TABLE = Table(
    "projects",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("canonical_project_id", String, nullable=False),
    Column("project_number", String, nullable=True),
    Column("project_name", String, nullable=False),
    Column("organization_name", String, nullable=True),
    Column("procurement_type", String, nullable=False),
    Column("budget_amount", Numeric(18, 2), nullable=True),
    Column("currency", String, nullable=True, default="THB"),
    Column("source_status_text", String, nullable=True),
    Column("proposal_submission_date", Date, nullable=True),
    Column("invitation_announcement_date", Date, nullable=True),
    Column("winner_announced_at", Date, nullable=True),
    Column("contract_signed_at", Date, nullable=True),
    Column("project_state", String, nullable=False),
    Column("closed_reason", String, nullable=True),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_changed_at", DateTime(timezone=True), nullable=False),
    Column("last_run_id", UUID_SQL_TYPE, nullable=True),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id", "canonical_project_id", name="projects_tenant_canonical_uq"
    ),
    CheckConstraint(
        "project_state IN ("
        "'discovered',"
        "'open_invitation',"
        "'open_consulting',"
        "'open_public_hearing',"
        "'tor_downloaded',"
        "'prelim_pricing_seen',"
        "'winner_announced',"
        "'contract_signed',"
        "'closed_timeout_consulting',"
        "'closed_stale_no_tor',"
        "'closed_manual',"
        "'error'"
        ")",
        name="projects_state_check",
    ),
    CheckConstraint(
        "closed_reason IS NULL OR closed_reason IN ("
        "'winner_announced',"
        "'contract_signed',"
        "'consulting_timeout_30d',"
        "'prelim_pricing',"
        "'stale_no_tor',"
        "'manual',"
        "'merged_duplicate'"
        ")",
        name="projects_closed_reason_check",
    ),
)

PROJECT_ALIASES_TABLE = Table(
    "project_aliases",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column(
        "project_id",
        UUID_SQL_TYPE,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("alias_type", String, nullable=False),
    Column("alias_value", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "project_id", "alias_type", "alias_value", name="aliases_project_alias_uq"
    ),
    CheckConstraint(
        "alias_type IN ('search_name', 'detail_name', 'project_number', 'fingerprint')",
        name="aliases_type_check",
    ),
)

PROJECT_STATUS_EVENTS_TABLE = Table(
    "project_status_events",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column(
        "project_id",
        UUID_SQL_TYPE,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("observed_status_text", String, nullable=False),
    Column("normalized_status", String, nullable=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("run_id", UUID_SQL_TYPE, nullable=True),
    Column("raw_snapshot", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index(
    "idx_projects_tenant_state",
    PROJECTS_TABLE.c.tenant_id,
    PROJECTS_TABLE.c.project_state,
)
Index(
    "idx_projects_last_changed_at",
    PROJECTS_TABLE.c.tenant_id,
    PROJECTS_TABLE.c.last_changed_at,
)
Index("idx_aliases_value", PROJECT_ALIASES_TABLE.c.alias_value)
Index("idx_aliases_project", PROJECT_ALIASES_TABLE.c.project_id)
Index(
    "idx_status_events_project",
    PROJECT_STATUS_EVENTS_TABLE.c.project_id,
    PROJECT_STATUS_EVENTS_TABLE.c.observed_at,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


def _normalize_optional_text(value: str | None) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _normalize_date(value: str | None) -> date | None:
    if value is None or not str(value).strip():
        return None
    return date.fromisoformat(str(value).strip())


def _normalize_budget_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("budget_amount must be numeric") from exc


def _normalize_run_id(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_uuid_string(value)


def _normalize_decimal_filter(
    value: Decimal | float | int | str | None,
) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("budget filter must be numeric") from exc


def _normalize_datetime_filter(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("updated_after must be ISO-8601 datetime") from exc


def _normalize_multi_value_filter(
    values: list[object] | tuple[object, ...] | None,
) -> list[str]:
    normalized_values: list[str] = []
    for raw_value in values or []:
        for part in str(raw_value).split(","):
            normalized = part.strip()
            if normalized:
                normalized_values.append(normalized)
    return normalized_values


_STRONG_ALIAS_TYPES = {"project_number", "fingerprint"}
_DASHBOARD_CLOSED_STATES = {
    ProjectState.CLOSED_TIMEOUT_CONSULTING.value,
    ProjectState.CLOSED_STALE_NO_TOR.value,
    ProjectState.CLOSED_MANUAL.value,
}
_DASHBOARD_WINNER_STATES = {
    ProjectState.WINNER_ANNOUNCED.value,
    ProjectState.CONTRACT_SIGNED.value,
}
_DASHBOARD_BREAKDOWN_BUCKETS = (
    "discovered",
    "open_invitation",
    "open_consulting",
    "tor_downloaded",
    "winner",
    "closed",
)


def _dashboard_bucket_for_state(project_state: str) -> str | None:
    if project_state == ProjectState.DISCOVERED.value:
        return "discovered"
    if project_state in {
        ProjectState.OPEN_INVITATION.value,
        ProjectState.OPEN_PUBLIC_HEARING.value,
        ProjectState.PRELIM_PRICING_SEEN.value,
    }:
        return "open_invitation"
    if project_state == ProjectState.OPEN_CONSULTING.value:
        return "open_consulting"
    if project_state == ProjectState.TOR_DOWNLOADED.value:
        return "tor_downloaded"
    if project_state in _DASHBOARD_WINNER_STATES:
        return "winner"
    if project_state in _DASHBOARD_CLOSED_STATES:
        return "closed"
    return None


def _date_value_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _datetime_value_to_iso(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _project_from_mapping(row: RowMapping) -> ProjectRecord:
    def as_iso(value):
        return value.isoformat() if isinstance(value, datetime) else str(value)

    budget_amount = row["budget_amount"]
    if isinstance(budget_amount, Decimal):
        normalized_budget_amount = (
            format(budget_amount.normalize(), "f").rstrip("0").rstrip(".")
        )
    else:
        normalized_budget_amount = _normalize_optional_text(budget_amount)

    return ProjectRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        canonical_project_id=str(row["canonical_project_id"]),
        project_number=_normalize_optional_text(row["project_number"]),
        project_name=str(row["project_name"]),
        organization_name=str(row["organization_name"] or ""),
        procurement_type=ProcurementType(str(row["procurement_type"])),
        proposal_submission_date=(
            row["proposal_submission_date"].isoformat()
            if isinstance(row["proposal_submission_date"], date)
            else _normalize_optional_text(row["proposal_submission_date"])
        ),
        budget_amount=normalized_budget_amount or None,
        project_state=ProjectState(str(row["project_state"])),
        closed_reason=(
            ClosedReason(str(row["closed_reason"]))
            if row["closed_reason"] is not None
            else None
        ),
        source_status_text=_normalize_optional_text(row["source_status_text"]),
        has_changed_tor=bool(row["has_changed_tor"])
        if "has_changed_tor" in row
        else False,
        first_seen_at=as_iso(row["first_seen_at"]),
        last_seen_at=as_iso(row["last_seen_at"]),
        last_changed_at=as_iso(row["last_changed_at"]),
        created_at=as_iso(row["created_at"]),
        updated_at=as_iso(row["updated_at"]),
    )


def _alias_from_mapping(row: RowMapping) -> ProjectAliasRecord:
    created_at = row["created_at"]
    return ProjectAliasRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        alias_type=str(row["alias_type"]),
        alias_value=str(row["alias_value"]),
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at),
    )


def _status_event_from_mapping(row: RowMapping) -> ProjectStatusEventRecord:
    observed_at = row["observed_at"]
    created_at = row["created_at"]
    return ProjectStatusEventRecord(
        id=str(row["id"]),
        project_id=str(row["project_id"]),
        observed_status_text=str(row["observed_status_text"]),
        normalized_status=_normalize_optional_text(row["normalized_status"]),
        observed_at=observed_at.isoformat()
        if isinstance(observed_at, datetime)
        else str(observed_at),
        run_id=_normalize_optional_text(row["run_id"]),
        raw_snapshot=row["raw_snapshot"],
        created_at=created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at),
    )


def build_project_upsert_record(
    *,
    tenant_id: str,
    project_number: str | None,
    search_name: str | None,
    detail_name: str | None,
    project_name: str,
    organization_name: str,
    proposal_submission_date: str | None,
    budget_amount: str | None,
    procurement_type: ProcurementType | str | None,
    project_state: ProjectState | str = ProjectState.DISCOVERED,
    closed_reason: ClosedReason | str | None = None,
) -> ProjectUpsertRecord:
    transition = transition_state(
        current_state=ProjectState.DISCOVERED,
        next_state=project_state,
        closed_reason=closed_reason,
    )
    canonical_project_id = generate_canonical_id(
        project_number=project_number,
        organization_name=organization_name,
        project_name=project_name,
        proposal_submission_date=proposal_submission_date,
        budget_amount=budget_amount,
    )
    aliases = build_project_aliases(
        project_number=project_number,
        search_name=search_name,
        detail_name=detail_name,
        organization_name=organization_name,
        project_name=project_name,
        proposal_submission_date=proposal_submission_date,
        budget_amount=budget_amount,
    )
    normalized_procurement_type = ProcurementType(
        str(procurement_type or ProcurementType.UNKNOWN).strip()
    )
    normalized_project_number = str(project_number).strip() if project_number else None
    normalized_budget_amount = str(budget_amount).strip() if budget_amount else None
    normalized_date = (
        str(proposal_submission_date).strip() if proposal_submission_date else None
    )
    return ProjectUpsertRecord(
        tenant_id=tenant_id,
        canonical_project_id=canonical_project_id,
        project_name=project_name,
        organization_name=organization_name,
        project_number=normalized_project_number,
        procurement_type=normalized_procurement_type,
        proposal_submission_date=normalized_date,
        budget_amount=normalized_budget_amount,
        project_state=transition["project_state"],
        closed_reason=transition["closed_reason"],
        aliases=aliases,
    )


class SqlProjectRepository:
    """Relational project repository with canonical-id and alias dedup."""

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

    def _find_existing_row(
        self, connection, *, tenant_id: str, record: ProjectUpsertRecord
    ):
        row = (
            connection.execute(
                select(PROJECTS_TABLE)
                .where(
                    and_(
                        PROJECTS_TABLE.c.tenant_id == tenant_id,
                        PROJECTS_TABLE.c.canonical_project_id
                        == record.canonical_project_id,
                    )
                )
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row is not None:
            return row

        alias_values = [
            alias_value
            for alias_type, alias_value in record.aliases
            if alias_type in _STRONG_ALIAS_TYPES
        ]
        if not alias_values:
            return None
        return (
            connection.execute(
                select(PROJECTS_TABLE)
                .join(
                    PROJECT_ALIASES_TABLE,
                    PROJECT_ALIASES_TABLE.c.project_id == PROJECTS_TABLE.c.id,
                )
                .where(
                    and_(
                        PROJECTS_TABLE.c.tenant_id == tenant_id,
                        PROJECT_ALIASES_TABLE.c.alias_value.in_(alias_values),
                    )
                )
                .order_by(desc(PROJECTS_TABLE.c.updated_at))
                .limit(1)
            )
            .mappings()
            .first()
        )

    def _upsert_aliases(
        self,
        connection,
        *,
        project_id: str,
        aliases: list[tuple[str, str]],
        created_at: datetime,
    ) -> None:
        for alias_type, alias_value in aliases:
            existing = connection.execute(
                select(PROJECT_ALIASES_TABLE.c.id).where(
                    and_(
                        PROJECT_ALIASES_TABLE.c.project_id == project_id,
                        PROJECT_ALIASES_TABLE.c.alias_type == alias_type,
                        PROJECT_ALIASES_TABLE.c.alias_value == alias_value,
                    )
                )
            ).first()
            if existing is not None:
                continue
            connection.execute(
                insert(PROJECT_ALIASES_TABLE).values(
                    id=str(uuid4()),
                    project_id=project_id,
                    alias_type=alias_type,
                    alias_value=alias_value,
                    created_at=created_at,
                )
            )

    def _insert_status_event(
        self,
        connection,
        *,
        project_id: str,
        observed_status_text: str,
        normalized_status: str,
        observed_at: datetime,
        run_id: str | None,
        raw_snapshot: dict[str, object] | None,
    ) -> None:
        connection.execute(
            insert(PROJECT_STATUS_EVENTS_TABLE).values(
                id=str(uuid4()),
                project_id=project_id,
                observed_status_text=observed_status_text,
                normalized_status=normalized_status,
                observed_at=observed_at,
                run_id=run_id,
                raw_snapshot=raw_snapshot,
                created_at=observed_at,
            )
        )

    def upsert_project(
        self,
        record: ProjectUpsertRecord,
        *,
        source_status_text: str | None = None,
        run_id: str | None = None,
        raw_snapshot: dict[str, object] | None = None,
        observed_at: str | None = None,
    ) -> ProjectRecord:
        tenant_id = normalize_uuid_string(record.tenant_id)
        normalized_run_id = _normalize_run_id(run_id)
        now = datetime.fromisoformat(observed_at) if observed_at else _now()
        normalized_status_text = _normalize_optional_text(source_status_text)

        with self._engine.begin() as connection:
            existing_row = self._find_existing_row(
                connection, tenant_id=tenant_id, record=record
            )

            if existing_row is None:
                project_id = str(uuid4())
                connection.execute(
                    insert(PROJECTS_TABLE).values(
                        id=project_id,
                        tenant_id=tenant_id,
                        canonical_project_id=record.canonical_project_id,
                        project_number=record.project_number,
                        project_name=record.project_name,
                        organization_name=record.organization_name,
                        procurement_type=record.procurement_type.value,
                        budget_amount=_normalize_budget_amount(record.budget_amount),
                        currency="THB",
                        source_status_text=normalized_status_text,
                        proposal_submission_date=_normalize_date(
                            record.proposal_submission_date
                        ),
                        invitation_announcement_date=None,
                        winner_announced_at=(
                            now.date()
                            if record.project_state is ProjectState.WINNER_ANNOUNCED
                            else None
                        ),
                        contract_signed_at=(
                            now.date()
                            if record.project_state is ProjectState.CONTRACT_SIGNED
                            else None
                        ),
                        project_state=record.project_state.value,
                        closed_reason=record.closed_reason.value
                        if record.closed_reason
                        else None,
                        first_seen_at=now,
                        last_seen_at=now,
                        last_changed_at=now,
                        last_run_id=normalized_run_id,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                existing = _project_from_mapping(existing_row)
                transition = transition_state(
                    current_state=existing.project_state,
                    next_state=record.project_state,
                    closed_reason=record.closed_reason,
                )
                project_id = existing.id
                changed = any(
                    (
                        existing.canonical_project_id != record.canonical_project_id,
                        existing.project_number != record.project_number
                        and record.project_number is not None,
                        existing.project_name != record.project_name,
                        existing.organization_name != record.organization_name,
                        existing.procurement_type != record.procurement_type,
                        existing.proposal_submission_date
                        != record.proposal_submission_date,
                        existing.budget_amount != record.budget_amount,
                        existing.project_state != transition["project_state"],
                        existing.closed_reason != transition["closed_reason"],
                        existing.source_status_text != normalized_status_text
                        and normalized_status_text is not None,
                    )
                )
                connection.execute(
                    update(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == tenant_id,
                            PROJECTS_TABLE.c.id == project_id,
                        )
                    )
                    .values(
                        canonical_project_id=record.canonical_project_id,
                        project_number=record.project_number or existing.project_number,
                        project_name=record.project_name,
                        organization_name=record.organization_name,
                        procurement_type=record.procurement_type.value,
                        budget_amount=_normalize_budget_amount(record.budget_amount)
                        if record.budget_amount is not None
                        else _normalize_budget_amount(existing.budget_amount),
                        currency="THB",
                        source_status_text=normalized_status_text
                        or existing.source_status_text,
                        proposal_submission_date=_normalize_date(
                            record.proposal_submission_date
                        )
                        or _normalize_date(existing.proposal_submission_date),
                        winner_announced_at=(
                            now.date()
                            if transition["project_state"]
                            is ProjectState.WINNER_ANNOUNCED
                            else existing_row["winner_announced_at"]
                        ),
                        contract_signed_at=(
                            now.date()
                            if transition["project_state"]
                            is ProjectState.CONTRACT_SIGNED
                            else existing_row["contract_signed_at"]
                        ),
                        project_state=transition["project_state"].value,
                        closed_reason=(
                            transition["closed_reason"].value
                            if transition["closed_reason"] is not None
                            else None
                        ),
                        last_seen_at=now,
                        last_changed_at=now
                        if changed
                        else datetime.fromisoformat(existing.last_changed_at),
                        last_run_id=normalized_run_id or existing_row["last_run_id"],
                        updated_at=now,
                    )
                )

            self._upsert_aliases(
                connection,
                project_id=project_id,
                aliases=record.aliases,
                created_at=now,
            )
            if normalized_status_text is not None:
                self._insert_status_event(
                    connection,
                    project_id=project_id,
                    observed_status_text=normalized_status_text,
                    normalized_status=(
                        transition["project_state"].value
                        if existing_row is not None
                        else record.project_state.value
                    ),
                    observed_at=now,
                    run_id=normalized_run_id,
                    raw_snapshot=raw_snapshot,
                )

            row = (
                connection.execute(
                    select(PROJECTS_TABLE)
                    .where(PROJECTS_TABLE.c.id == project_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _project_from_mapping(row)

    def transition_project(
        self,
        *,
        tenant_id: str,
        project_id: str,
        next_state: ProjectState | str,
        closed_reason: ClosedReason | str | None = None,
        source_status_text: str,
        run_id: str | None = None,
        raw_snapshot: dict[str, object] | None = None,
        observed_at: str | None = None,
    ) -> ProjectRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        now = datetime.fromisoformat(observed_at) if observed_at else _now()
        normalized_run_id = _normalize_run_id(run_id)

        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.id == normalized_project_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError(project_id)
            existing = _project_from_mapping(row)
            transition = transition_state(
                current_state=existing.project_state,
                next_state=next_state,
                closed_reason=closed_reason,
            )
            connection.execute(
                update(PROJECTS_TABLE)
                .where(
                    and_(
                        PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                        PROJECTS_TABLE.c.id == normalized_project_id,
                    )
                )
                .values(
                    project_state=transition["project_state"].value,
                    closed_reason=(
                        transition["closed_reason"].value
                        if transition["closed_reason"] is not None
                        else None
                    ),
                    source_status_text=source_status_text,
                    winner_announced_at=(
                        now.date()
                        if transition["project_state"] is ProjectState.WINNER_ANNOUNCED
                        else row["winner_announced_at"]
                    ),
                    contract_signed_at=(
                        now.date()
                        if transition["project_state"] is ProjectState.CONTRACT_SIGNED
                        else row["contract_signed_at"]
                    ),
                    last_seen_at=now,
                    last_changed_at=now,
                    last_run_id=normalized_run_id or row["last_run_id"],
                    updated_at=now,
                )
            )
            self._insert_status_event(
                connection,
                project_id=normalized_project_id,
                observed_status_text=source_status_text,
                normalized_status=transition["project_state"].value,
                observed_at=now,
                run_id=normalized_run_id,
                raw_snapshot=raw_snapshot,
            )
            updated_row = (
                connection.execute(
                    select(PROJECTS_TABLE)
                    .where(PROJECTS_TABLE.c.id == normalized_project_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _project_from_mapping(updated_row)

    def get_project(self, *, tenant_id: str, project_id: str) -> ProjectRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_project_id = normalize_uuid_string(project_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.id == normalized_project_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        return _project_from_mapping(row) if row is not None else None

    def find_existing_project(
        self, record: ProjectUpsertRecord
    ) -> ProjectRecord | None:
        normalized_tenant_id = normalize_uuid_string(record.tenant_id)
        with self._engine.connect() as connection:
            row = self._find_existing_row(
                connection,
                tenant_id=normalized_tenant_id,
                record=record,
            )
        return _project_from_mapping(row) if row is not None else None

    def get_project_detail(
        self, *, tenant_id: str, project_id: str
    ) -> ProjectDetail | None:
        project = self.get_project(tenant_id=tenant_id, project_id=project_id)
        if project is None:
            return None
        with self._engine.connect() as connection:
            aliases = (
                connection.execute(
                    select(PROJECT_ALIASES_TABLE)
                    .where(PROJECT_ALIASES_TABLE.c.project_id == project.id)
                    .order_by(PROJECT_ALIASES_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
            status_events = (
                connection.execute(
                    select(PROJECT_STATUS_EVENTS_TABLE)
                    .where(PROJECT_STATUS_EVENTS_TABLE.c.project_id == project.id)
                    .order_by(PROJECT_STATUS_EVENTS_TABLE.c.observed_at)
                )
                .mappings()
                .all()
            )
        return ProjectDetail(
            project=project,
            aliases=[_alias_from_mapping(alias) for alias in aliases],
            status_events=[_status_event_from_mapping(row) for row in status_events],
        )

    def list_projects(
        self,
        *,
        tenant_id: str,
        project_states: list[ProjectState | str] | None = None,
        procurement_types: list[ProcurementType | str] | None = None,
        closed_reasons: list[ClosedReason | str] | None = None,
        organization: str | None = None,
        keyword: str | None = None,
        budget_min: Decimal | float | int | str | None = None,
        budget_max: Decimal | float | int | str | None = None,
        updated_after: datetime | str | None = None,
        has_changed_tor: bool | None = None,
        has_winner: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectPage:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_limit = max(1, min(int(limit), 200))
        normalized_offset = max(0, int(offset))
        normalized_project_states = _normalize_multi_value_filter(project_states)
        normalized_procurement_types = _normalize_multi_value_filter(procurement_types)
        normalized_closed_reasons = _normalize_multi_value_filter(closed_reasons)
        normalized_organization = _normalize_optional_text(organization)
        normalized_keyword = _normalize_optional_text(keyword)
        normalized_budget_min = _normalize_decimal_filter(budget_min)
        normalized_budget_max = _normalize_decimal_filter(budget_max)
        normalized_updated_after = _normalize_datetime_filter(updated_after)
        statement = select(PROJECTS_TABLE).where(
            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id
        )
        count_statement = (
            select(func.count())
            .select_from(PROJECTS_TABLE)
            .where(PROJECTS_TABLE.c.tenant_id == normalized_tenant_id)
        )
        conditions = []

        if normalized_project_states:
            conditions.append(
                PROJECTS_TABLE.c.project_state.in_(normalized_project_states)
            )
        if normalized_procurement_types:
            conditions.append(
                PROJECTS_TABLE.c.procurement_type.in_(normalized_procurement_types)
            )
        if normalized_closed_reasons:
            conditions.append(
                PROJECTS_TABLE.c.closed_reason.in_(normalized_closed_reasons)
            )
        if normalized_organization is not None:
            conditions.append(
                PROJECTS_TABLE.c.organization_name.ilike(f"%{normalized_organization}%")
            )
        if normalized_budget_min is not None:
            conditions.append(PROJECTS_TABLE.c.budget_amount >= normalized_budget_min)
        if normalized_budget_max is not None:
            conditions.append(PROJECTS_TABLE.c.budget_amount <= normalized_budget_max)
        if normalized_updated_after is not None:
            conditions.append(
                PROJECTS_TABLE.c.last_changed_at >= normalized_updated_after
            )
        changed_tor_project_ids = (
            select(DOCUMENT_DIFFS_TABLE.c.project_id)
            .join(
                DOCUMENTS_TABLE,
                DOCUMENTS_TABLE.c.id == DOCUMENT_DIFFS_TABLE.c.new_document_id,
            )
            .where(
                and_(
                    DOCUMENT_DIFFS_TABLE.c.tenant_id == normalized_tenant_id,
                    DOCUMENTS_TABLE.c.tenant_id == normalized_tenant_id,
                    DOCUMENT_DIFFS_TABLE.c.diff_type == "changed",
                    DOCUMENTS_TABLE.c.document_type == "tor",
                )
            )
            .distinct()
        )
        has_changed_tor_column = PROJECTS_TABLE.c.id.in_(changed_tor_project_ids).label(
            "has_changed_tor"
        )
        if has_winner is not None:
            winner_states = [
                ProjectState.WINNER_ANNOUNCED.value,
                ProjectState.CONTRACT_SIGNED.value,
            ]
            if has_winner:
                conditions.append(PROJECTS_TABLE.c.project_state.in_(winner_states))
            else:
                conditions.append(PROJECTS_TABLE.c.project_state.not_in(winner_states))
        if has_changed_tor is not None:
            if has_changed_tor:
                conditions.append(PROJECTS_TABLE.c.id.in_(changed_tor_project_ids))
            else:
                conditions.append(PROJECTS_TABLE.c.id.not_in(changed_tor_project_ids))
        if normalized_keyword is not None:
            keyword_like = f"%{normalized_keyword}%"
            alias_project_ids = select(PROJECT_ALIASES_TABLE.c.project_id).where(
                PROJECT_ALIASES_TABLE.c.alias_value.ilike(keyword_like)
            )
            conditions.append(
                or_(
                    PROJECTS_TABLE.c.project_name.ilike(keyword_like),
                    PROJECTS_TABLE.c.organization_name.ilike(keyword_like),
                    PROJECTS_TABLE.c.project_number.ilike(keyword_like),
                    PROJECTS_TABLE.c.id.in_(alias_project_ids),
                )
            )

        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = statement.add_columns(has_changed_tor_column)
        statement = (
            statement.order_by(desc(PROJECTS_TABLE.c.last_changed_at))
            .limit(normalized_limit)
            .offset(normalized_offset)
        )
        with self._engine.connect() as connection:
            total = int(connection.execute(count_statement).scalar_one())
            rows = connection.execute(statement).mappings().all()
        return ProjectPage(
            items=[_project_from_mapping(row) for row in rows],
            total=total,
            limit=normalized_limit,
            offset=normalized_offset,
        )

    def get_dashboard_project_summary(
        self,
        *,
        tenant_id: str,
        now: datetime | None = None,
        discovery_days: int = 14,
        recent_changes_limit: int = 5,
        winner_limit: int = 5,
    ) -> DashboardProjectSummary:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        reference_now = now or _now()
        today = reference_now.date()
        discovery_window_days = max(1, int(discovery_days))
        discovery_start = today - timedelta(days=discovery_window_days - 1)
        winner_window_start = today - timedelta(days=6)
        recent_limit = max(1, int(recent_changes_limit))
        normalized_winner_limit = max(1, int(winner_limit))

        changed_tor_project_ids = (
            select(DOCUMENT_DIFFS_TABLE.c.project_id)
            .join(
                DOCUMENTS_TABLE,
                DOCUMENTS_TABLE.c.id == DOCUMENT_DIFFS_TABLE.c.new_document_id,
            )
            .where(
                and_(
                    DOCUMENT_DIFFS_TABLE.c.tenant_id == normalized_tenant_id,
                    DOCUMENTS_TABLE.c.tenant_id == normalized_tenant_id,
                    DOCUMENT_DIFFS_TABLE.c.diff_type == "changed",
                    DOCUMENTS_TABLE.c.document_type == "tor",
                )
            )
            .distinct()
            .subquery()
        )

        with self._engine.connect() as connection:
            active_projects = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.not_in(
                                [
                                    *sorted(_DASHBOARD_CLOSED_STATES),
                                    ProjectState.ERROR.value,
                                ]
                            ),
                        )
                    )
                ).scalar_one()
            )
            discovered_today = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            func.date(PROJECTS_TABLE.c.first_seen_at)
                            == today.isoformat(),
                        )
                    )
                ).scalar_one()
            )
            winner_projects_this_week = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.in_(
                                sorted(_DASHBOARD_WINNER_STATES)
                            ),
                            or_(
                                PROJECTS_TABLE.c.winner_announced_at
                                >= winner_window_start,
                                PROJECTS_TABLE.c.contract_signed_at
                                >= winner_window_start,
                            ),
                        )
                    )
                ).scalar_one()
            )
            closed_today = int(
                connection.execute(
                    select(func.count())
                    .select_from(PROJECTS_TABLE)
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.in_(
                                sorted(_DASHBOARD_CLOSED_STATES)
                            ),
                            func.date(PROJECTS_TABLE.c.last_changed_at)
                            == today.isoformat(),
                        )
                    )
                ).scalar_one()
            )
            changed_tor_projects = int(
                connection.execute(
                    select(func.count()).select_from(changed_tor_project_ids)
                ).scalar_one()
            )
            recent_change_rows = (
                connection.execute(
                    select(
                        PROJECTS_TABLE.c.id,
                        PROJECTS_TABLE.c.project_name,
                        PROJECTS_TABLE.c.project_state,
                        PROJECTS_TABLE.c.last_changed_at,
                    )
                    .where(PROJECTS_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(
                        desc(PROJECTS_TABLE.c.last_changed_at),
                        desc(PROJECTS_TABLE.c.created_at),
                    )
                    .limit(recent_limit)
                )
                .mappings()
                .all()
            )
            winner_rows = (
                connection.execute(
                    select(
                        PROJECTS_TABLE.c.id,
                        PROJECTS_TABLE.c.project_name,
                        PROJECTS_TABLE.c.project_state,
                        func.coalesce(
                            PROJECTS_TABLE.c.winner_announced_at,
                            PROJECTS_TABLE.c.contract_signed_at,
                        ).label("awarded_at"),
                    )
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            PROJECTS_TABLE.c.project_state.in_(
                                sorted(_DASHBOARD_WINNER_STATES)
                            ),
                            or_(
                                PROJECTS_TABLE.c.winner_announced_at
                                >= winner_window_start,
                                PROJECTS_TABLE.c.contract_signed_at
                                >= winner_window_start,
                            ),
                        )
                    )
                    .order_by(
                        desc(
                            func.coalesce(
                                PROJECTS_TABLE.c.winner_announced_at,
                                PROJECTS_TABLE.c.contract_signed_at,
                            )
                        ),
                        desc(PROJECTS_TABLE.c.updated_at),
                    )
                    .limit(normalized_winner_limit)
                )
                .mappings()
                .all()
            )
            discovery_date = func.date(PROJECTS_TABLE.c.first_seen_at)
            daily_rows = (
                connection.execute(
                    select(
                        discovery_date.label("discovery_date"),
                        func.count().label("count"),
                    )
                    .where(
                        and_(
                            PROJECTS_TABLE.c.tenant_id == normalized_tenant_id,
                            discovery_date >= discovery_start.isoformat(),
                            discovery_date <= today.isoformat(),
                        )
                    )
                    .group_by(discovery_date)
                )
                .mappings()
                .all()
            )
            state_rows = (
                connection.execute(
                    select(
                        PROJECTS_TABLE.c.project_state,
                        func.count().label("count"),
                    )
                    .where(PROJECTS_TABLE.c.tenant_id == normalized_tenant_id)
                    .group_by(PROJECTS_TABLE.c.project_state)
                )
                .mappings()
                .all()
            )

        daily_counts = {
            _date_value_to_iso(row["discovery_date"]): int(row["count"])
            for row in daily_rows
        }
        daily_discovery = [
            DashboardDailyDiscoveryPoint(
                date=(discovery_start + timedelta(days=offset)).isoformat(),
                count=daily_counts.get(
                    (discovery_start + timedelta(days=offset)).isoformat(),
                    0,
                ),
            )
            for offset in range(discovery_window_days)
        ]
        breakdown_counts = {bucket: 0 for bucket in _DASHBOARD_BREAKDOWN_BUCKETS}
        for row in state_rows:
            bucket = _dashboard_bucket_for_state(str(row["project_state"]))
            if bucket is not None:
                breakdown_counts[bucket] += int(row["count"])

        return DashboardProjectSummary(
            active_projects=active_projects,
            discovered_today=discovered_today,
            winner_projects_this_week=winner_projects_this_week,
            closed_today=closed_today,
            changed_tor_projects=changed_tor_projects,
            recent_changes=[
                DashboardRecentProjectChangeRecord(
                    project_id=str(row["id"]),
                    project_name=str(row["project_name"]),
                    project_state=str(row["project_state"]),
                    last_changed_at=_datetime_value_to_iso(row["last_changed_at"]),
                )
                for row in recent_change_rows
            ],
            winner_projects=[
                DashboardWinnerProjectRecord(
                    project_id=str(row["id"]),
                    project_name=str(row["project_name"]),
                    project_state=str(row["project_state"]),
                    awarded_at=_date_value_to_iso(row["awarded_at"]),
                )
                for row in winner_rows
                if row["awarded_at"] is not None
            ],
            daily_discovery=daily_discovery,
            project_state_breakdown=[
                DashboardStateBreakdownPoint(
                    bucket=bucket, count=breakdown_counts[bucket]
                )
                for bucket in _DASHBOARD_BREAKDOWN_BUCKETS
            ],
        )


def create_project_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlProjectRepository:
    return SqlProjectRepository(
        database_url=database_url, engine=engine, bootstrap_schema=bootstrap_schema
    )
