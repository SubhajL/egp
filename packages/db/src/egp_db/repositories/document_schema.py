"""Document repository SQLAlchemy table definitions."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy import Column

from egp_db.connection import DB_METADATA
from egp_db.db_utils import UUID_SQL_TYPE


METADATA = DB_METADATA

DOCUMENTS_TABLE = Table(
    "documents",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("file_name", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("storage_key", String, nullable=False),
    Column("managed_backup_storage_key", String, nullable=True),
    Column("document_type", String, nullable=False),
    Column("document_phase", String, nullable=False),
    Column("source_label", String, nullable=False, default=""),
    Column("source_status_text", String, nullable=False, default=""),
    Column("size_bytes", Integer, nullable=False),
    Column("is_current", Boolean, nullable=False, default=True),
    Column("supersedes_document_id", UUID_SQL_TYPE, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "project_id",
        "sha256",
        "document_type",
        "document_phase",
        name="documents_project_hash_class_phase_uq",
    ),
)

DOCUMENT_DIFFS_TABLE = Table(
    "document_diffs",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("old_document_id", UUID_SQL_TYPE, nullable=False),
    Column("new_document_id", UUID_SQL_TYPE, nullable=False),
    Column("diff_type", String, nullable=False),
    Column("summary_json", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

DOCUMENT_DIFF_REVIEWS_TABLE = Table(
    "document_diff_reviews",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("document_diff_id", UUID_SQL_TYPE, nullable=False),
    Column("status", String, nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "document_diff_id",
        name="document_diff_reviews_document_diff_unique",
    ),
)

DOCUMENT_REVIEW_EVENTS_TABLE = Table(
    "document_review_events",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=False),
    Column("review_id", UUID_SQL_TYPE, nullable=False),
    Column("document_diff_id", UUID_SQL_TYPE, nullable=False),
    Column("event_type", String, nullable=False),
    Column("actor_subject", String, nullable=True),
    Column("note", String, nullable=True),
    Column("from_status", String, nullable=True),
    Column("to_status", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

Index(
    "idx_documents_project",
    DOCUMENTS_TABLE.c.tenant_id,
    DOCUMENTS_TABLE.c.project_id,
    DOCUMENTS_TABLE.c.is_current,
    DOCUMENTS_TABLE.c.created_at,
)
Index(
    "idx_documents_type",
    DOCUMENTS_TABLE.c.tenant_id,
    DOCUMENTS_TABLE.c.project_id,
    DOCUMENTS_TABLE.c.document_type,
    DOCUMENTS_TABLE.c.document_phase,
    DOCUMENTS_TABLE.c.created_at,
)
Index(
    "idx_diffs_project",
    DOCUMENT_DIFFS_TABLE.c.tenant_id,
    DOCUMENT_DIFFS_TABLE.c.project_id,
    DOCUMENT_DIFFS_TABLE.c.created_at,
)
Index(
    "idx_document_diff_reviews_project_created",
    DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.project_id,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.created_at,
)
Index(
    "idx_document_diff_reviews_status_created",
    DOCUMENT_DIFF_REVIEWS_TABLE.c.tenant_id,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.status,
    DOCUMENT_DIFF_REVIEWS_TABLE.c.created_at,
)
Index(
    "idx_document_review_events_review_created",
    DOCUMENT_REVIEW_EVENTS_TABLE.c.review_id,
    DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at,
)
Index(
    "idx_document_review_events_diff_created",
    DOCUMENT_REVIEW_EVENTS_TABLE.c.document_diff_id,
    DOCUMENT_REVIEW_EVENTS_TABLE.c.created_at,
)
