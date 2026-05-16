"""Project repository SQLAlchemy table definitions."""

from __future__ import annotations

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
)
from sqlalchemy import Column

from egp_db.connection import DB_METADATA
from egp_db.db_utils import UUID_SQL_TYPE


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
