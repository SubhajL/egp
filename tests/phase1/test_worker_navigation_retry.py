"""TDD: run_with_navigation_retry — retry ONLY the Playwright navigation-race
("execution context was destroyed ... because of a navigation"), additively.
"""

from __future__ import annotations

import pytest

from egp_worker.browser_discovery import run_with_navigation_retry

NAV_ERR = "Page.query_selector: Execution context was destroyed, most likely because of a navigation"


def test_returns_first_try_result_without_retry() -> None:
    calls: list[int] = []

    def op():
        calls.append(1)
        return "ok"

    assert run_with_navigation_retry(op, retries=2) == "ok"
    assert len(calls) == 1  # no retry on success


def test_retries_then_succeeds_on_navigation_destroyed() -> None:
    calls: list[int] = []
    retried: list[int] = []

    def op():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError(NAV_ERR)
        return "ok"

    assert run_with_navigation_retry(op, retries=2, on_retry=lambda: retried.append(1)) == "ok"
    assert len(calls) == 2
    assert len(retried) == 1


def test_reraises_non_navigation_error_immediately() -> None:
    calls: list[int] = []

    def op():
        calls.append(1)
        raise ValueError("some unrelated error")

    with pytest.raises(ValueError):
        run_with_navigation_retry(op, retries=3)
    assert len(calls) == 1  # non-nav error must NOT retry


def test_reraises_after_exhausting_retries() -> None:
    calls: list[int] = []

    def op():
        calls.append(1)
        raise RuntimeError("execution context was destroyed")

    with pytest.raises(RuntimeError):
        run_with_navigation_retry(op, retries=2)
    assert len(calls) == 3  # initial attempt + 2 retries


def test_on_retry_exception_is_swallowed() -> None:
    calls: list[int] = []

    def op():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("context was destroyed")
        return "ok"

    def bad_on_retry():
        raise RuntimeError("settle failed")

    assert run_with_navigation_retry(op, retries=2, on_retry=bad_on_retry) == "ok"
    assert len(calls) == 2
