from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 5, 26, 14, 30, 45, tzinfo=UTC)


@pytest.fixture
def fake_git_sha() -> str:
    return "abc1234"


@pytest.fixture
def tmp_backup_root(tmp_path: Path) -> Path:
    root = tmp_path / "backups"
    root.mkdir()
    return root


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
