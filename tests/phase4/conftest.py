"""Phase 4 test lifecycle fixtures."""

from __future__ import annotations

import pytest

from tests.support.lifespan_client import close_active_test_clients


@pytest.fixture(autouse=True)
def close_helper_clients_after_test():
    yield
    close_active_test_clients()
