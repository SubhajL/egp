"""Explicit schema-bootstrap adapter for API tests."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from egp_api.main import create_app
from egp_db.db_utils import is_sqlite_url


def create_test_app(**kwargs: Any) -> FastAPI:
    """Create an API app, opting SQLite tests into mapped-schema bootstrap."""

    database_url = kwargs.get("database_url")
    if "bootstrap_schema" not in kwargs:
        kwargs["bootstrap_schema"] = bool(
            isinstance(database_url, str) and is_sqlite_url(database_url)
        )
    return create_app(**kwargs)
