"""Shared DB helpers used across repositories."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PGUUID

UUID_SQL_TYPE = String(36).with_variant(PGUUID(as_uuid=False), "postgresql")


def normalize_uuid_string(value: str) -> str:
    return str(UUID(str(value).strip()))


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def is_sqlite_url(database_url: str) -> bool:
    return normalize_database_url(database_url).startswith("sqlite")
