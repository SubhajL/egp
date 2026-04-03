"""Shared engine and metadata helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine, make_url

from egp_db.db_utils import normalize_database_url

DB_METADATA = MetaData()


@lru_cache(maxsize=32)
def _engine_for_url(normalized_url: str) -> Engine:
    url = make_url(normalized_url)
    if url.drivername.startswith("sqlite"):
        if url.database not in (None, "", ":memory:"):
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            normalized_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
    return create_engine(normalized_url, future=True)


def create_shared_engine(database_url: str) -> Engine:
    return _engine_for_url(normalize_database_url(database_url))
