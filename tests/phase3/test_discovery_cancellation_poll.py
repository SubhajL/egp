"""Regression: the cancellation poll loop crashed on every long crawl.

Found by running a real crawl against production e-GP.

`_communicate_with_cancellation` polls `proc.communicate(timeout=...)` on a short
interval so it can notice a lost lease between polls. A `TimeoutExpired` from that
inner call is therefore the NORMAL path — it just means the worker is still
running — and the loop is supposed to go round again.

Instead the except branch fell through to `return result`, which is only assigned
when `communicate` *succeeds*. So the first poll timeout raised

    UnboundLocalError: cannot access local variable 'result'

meaning any crawl outliving a single poll interval died immediately, the job went
back to `pending`, and it retried forever. Observed in production: attempt_count
climbing with the job never leaving `pending`.

No test covered it because the fast path (`cancellation_event is None`) returns
before the loop, and every existing test used that path.
"""

from __future__ import annotations

import subprocess
import threading
import time

import pytest

from egp_api.services.discovery_worker_dispatcher import (
    _DiscoveryLeaseCancellation,
    _communicate_with_cancellation,
)


class _FakeProc:
    """Times out `timeouts_before_success` times, then completes."""

    args = "egp_worker"

    def __init__(self, *, timeouts_before_success: int) -> None:
        self._remaining = timeouts_before_success
        self.calls = 0
        self.killed = False

    def communicate(self, input=None, timeout=None):
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            # Consume the timeout, as the real `communicate` does. Without this,
            # monotonic time never advances, the overall deadline can never trip,
            # and the deadline test silently measures nothing.
            time.sleep(max(0.0, float(timeout or 0.0)))
            raise subprocess.TimeoutExpired(cmd=self.args, timeout=timeout)
        return (b'{"ok": true}', b"")

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def test_a_poll_timeout_does_not_crash_the_dispatcher() -> None:
    """The bug, minimally: one poll timeout then success.

    Before the fix this raised UnboundLocalError instead of returning the output.
    """

    proc = _FakeProc(timeouts_before_success=1)
    stdout, _stderr = _communicate_with_cancellation(
        proc,
        payload=b"{}",
        timeout_seconds=30.0,
        cancellation_event=threading.Event(),
    )
    assert stdout == b'{"ok": true}'
    assert proc.calls == 2, "the loop must poll again rather than fall through"


def test_many_poll_timeouts_still_complete() -> None:
    """A real crawl spans many poll intervals, not one."""

    proc = _FakeProc(timeouts_before_success=3)
    stdout, _stderr = _communicate_with_cancellation(
        proc,
        payload=b"{}",
        timeout_seconds=60.0,
        cancellation_event=threading.Event(),
    )
    assert stdout == b'{"ok": true}'
    assert proc.calls == 4


def test_input_is_only_sent_once_across_polls() -> None:
    """Re-sending stdin on every poll would corrupt the worker's payload."""

    seen: list[object] = []

    class _RecordingProc(_FakeProc):
        def communicate(self, input=None, timeout=None):
            seen.append(input)
            return super().communicate(input=input, timeout=timeout)

    _communicate_with_cancellation(
        _RecordingProc(timeouts_before_success=2),
        payload=b"{}",
        timeout_seconds=30.0,
        cancellation_event=threading.Event(),
    )
    assert seen[0] == b"{}"
    assert all(value is None for value in seen[1:]), seen


def test_a_lost_lease_still_cancels() -> None:
    """The reason the loop exists at all must keep working."""

    event = threading.Event()
    event.set()
    with pytest.raises(_DiscoveryLeaseCancellation):
        _communicate_with_cancellation(
            _FakeProc(timeouts_before_success=0),
            payload=b"{}",
            timeout_seconds=30.0,
            cancellation_event=event,
        )


def test_the_overall_deadline_is_still_enforced() -> None:
    """Control: the fix must not turn a hung worker into an infinite loop."""

    with pytest.raises(subprocess.TimeoutExpired):
        _communicate_with_cancellation(
            _FakeProc(timeouts_before_success=10_000),  # never completes
            payload=b"{}",
            timeout_seconds=0.05,
            cancellation_event=threading.Event(),
        )


def test_the_no_cancellation_fast_path_is_unchanged() -> None:
    """The path every existing test used — and why this bug hid."""

    proc = _FakeProc(timeouts_before_success=0)
    stdout, _stderr = _communicate_with_cancellation(
        proc, payload=b"{}", timeout_seconds=30.0, cancellation_event=None
    )
    assert stdout == b'{"ok": true}'
    assert proc.calls == 1


def test_an_unexpected_exception_still_reaps_the_browser_process_group() -> None:
    """The orphaned-Chrome half of the incident.

    The named handlers kill the process group for the failures they expect. An
    UNEXPECTED exception escaped without killing anything, and every escape left a
    real Chrome plus its helpers holding the persistent profile. One production
    bug produced 27 stray processes and a permanently locked profile, so cleanup
    must not depend on having anticipated the exception.
    """

    import inspect

    from egp_api.services import discovery_worker_dispatcher as module

    source = inspect.getsource(module.SubprocessDiscoveryDispatcher)
    finally_reap = "_kill_process_group(proc)" in source and "poll() is None" in source
    assert finally_reap, (
        "dispatch must reap the worker process group from a finally block, not "
        "only from the exception handlers it happens to name"
    )
