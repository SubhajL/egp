from __future__ import annotations

from pathlib import Path

import pytest

TENANT_ID = "11111111-1111-1111-1111-111111111111"
SECOND_TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
JWT_SECRET = "phase1-test-secret"


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def sqlite_database_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
