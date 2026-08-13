from __future__ import annotations

import asyncio
import threading

import pytest

from egp_api.auth import AuthContext
from egp_api.services.auth_service import SessionAuthenticationResult
from egp_api.services.session_auth_runtime import (
    SessionAuthenticationRuntime,
    SessionAuthenticationRuntimeConfig,
    SessionAuthenticationUnavailableError,
)


TENANT_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "22222222-2222-2222-2222-222222222222"


class FakeAuthService:
    def __init__(
        self,
        *,
        gate: threading.Event | None = None,
        error: Exception | None = None,
    ) -> None:
        self.gate = gate
        self.error = error
        self.calls = 0

    def authenticate_session(self, token: str):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait()
        if self.error is not None:
            raise self.error
        return SessionAuthenticationResult(
            context=AuthContext(tenant_id=TENANT_ID, subject="user", claims={}),
            session_id=token if len(token) == 36 else SESSION_ID,
            tenant_id=TENANT_ID,
            last_seen_at=None,
        )


class FakeRepository:
    def __init__(self) -> None:
        self.calls = []
        self.written = threading.Event()

    def touch_session_activity(self, **kwargs) -> int:
        self.calls.append(kwargs)
        self.written.set()
        return 1


class BlockingActivityRepository(FakeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()

    def touch_session_activity(self, **kwargs) -> int:
        self.calls.append(kwargs)
        self.written.set()
        self.gate.wait()
        return 1


def _config(**overrides) -> SessionAuthenticationRuntimeConfig:
    values = {
        "lookup_workers": 1,
        "maximum_admitted_lookups": 1,
        "lookup_timeout_seconds": 0.05,
        "activity_queue_capacity": 2,
        "activity_interval_seconds": 300,
        "recent_activity_capacity": 3,
        "shutdown_timeout_seconds": 0.05,
    }
    values.update(overrides)
    return SessionAuthenticationRuntimeConfig(**values)


@pytest.mark.asyncio
async def test_blocking_lookup_does_not_block_event_loop() -> None:
    gate = threading.Event()
    auth = FakeAuthService(gate=gate)
    repository = FakeRepository()
    runtime = SessionAuthenticationRuntime(
        auth_service=auth, repository=repository, config=_config()
    )
    await runtime.start()
    watchdog = threading.Timer(0.1, gate.set)
    watchdog.start()
    task = asyncio.create_task(runtime.authenticate("opaque"))
    started = asyncio.get_running_loop().time()
    await asyncio.sleep(0.01)
    ticker_elapsed = asyncio.get_running_loop().time() - started

    assert ticker_elapsed < 0.05
    assert not task.done()
    gate.set()
    assert (await task).subject == "user"
    watchdog.cancel()
    await runtime.stop()


@pytest.mark.asyncio
async def test_timeout_retains_capacity_until_lookup_finishes() -> None:
    gate = threading.Event()
    auth = FakeAuthService(gate=gate)
    repository = FakeRepository()
    runtime = SessionAuthenticationRuntime(
        auth_service=auth, repository=repository, config=_config()
    )
    await runtime.start()

    with pytest.raises(SessionAuthenticationUnavailableError):
        await runtime.authenticate("one")
    with pytest.raises(SessionAuthenticationUnavailableError, match="saturated"):
        await runtime.authenticate("two")

    gate.set()
    await asyncio.sleep(0.02)
    assert (await runtime.authenticate("three")).subject == "user"
    await runtime.stop()


@pytest.mark.asyncio
async def test_high_fan_in_saturation_rejects_without_event_loop_polling() -> None:
    gate = threading.Event()
    runtime = SessionAuthenticationRuntime(
        auth_service=FakeAuthService(gate=gate),
        repository=FakeRepository(),
        config=_config(lookup_timeout_seconds=0.2),
    )
    await runtime.start()
    admitted = asyncio.create_task(runtime.authenticate("admitted"))
    while runtime._auth_service.calls < 1:
        await asyncio.sleep(0)
    started = asyncio.get_running_loop().time()
    rejected = await asyncio.gather(
        *(runtime.authenticate(f"excess-{index}") for index in range(200)),
        return_exceptions=True,
    )
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.1
    assert all(
        isinstance(result, SessionAuthenticationUnavailableError)
        and "saturated" in str(result)
        for result in rejected
    )
    gate.set()
    assert (await admitted).subject == "user"
    await runtime.stop()


@pytest.mark.asyncio
async def test_saturation_completes_after_one_event_loop_turn() -> None:
    gate = threading.Event()
    runtime = SessionAuthenticationRuntime(
        auth_service=FakeAuthService(gate=gate),
        repository=FakeRepository(),
        config=_config(lookup_timeout_seconds=0.2),
    )
    await runtime.start()
    admitted = asyncio.create_task(runtime.authenticate("admitted"))
    while runtime._auth_service.calls < 1:
        await asyncio.sleep(0)
    excess = asyncio.create_task(runtime.authenticate("excess"))

    await asyncio.sleep(0)

    assert excess.done()
    with pytest.raises(SessionAuthenticationUnavailableError, match="saturated"):
        await excess
    gate.set()
    assert (await admitted).subject == "user"
    await runtime.stop()


@pytest.mark.asyncio
async def test_activity_is_coalesced_without_caching_authentication() -> None:
    auth = FakeAuthService()
    repository = FakeRepository()
    runtime = SessionAuthenticationRuntime(
        auth_service=auth,
        repository=repository,
        config=_config(maximum_admitted_lookups=4),
    )
    await runtime.start()

    results = await asyncio.gather(
        *(runtime.authenticate(f"opaque-{index}") for index in range(4))
    )
    assert await asyncio.to_thread(repository.written.wait, 1)

    assert len(results) == 4
    assert auth.calls == 4
    assert len(repository.calls) == 1
    await runtime.stop()


@pytest.mark.asyncio
async def test_full_activity_queue_drops_activity_without_failing_authentication() -> None:
    auth = FakeAuthService()
    repository = BlockingActivityRepository()
    runtime = SessionAuthenticationRuntime(
        auth_service=auth,
        repository=repository,
        config=_config(activity_queue_capacity=1, recent_activity_capacity=2),
    )
    await runtime.start()

    tokens = (
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
        "44444444-4444-4444-4444-444444444444",
    )
    first = await runtime.authenticate(tokens[0])
    assert await asyncio.to_thread(repository.written.wait, 1)
    second = await runtime.authenticate(tokens[1])
    third = await runtime.authenticate(tokens[2])

    assert first.subject == second.subject == third.subject == "user"
    assert auth.calls == 3
    assert runtime._activity_queue.qsize() <= 1
    repository.gate.set()
    await runtime.stop()


@pytest.mark.asyncio
async def test_shutdown_rejects_new_authentication_within_deadline() -> None:
    gate = threading.Event()
    auth = FakeAuthService(gate=gate)
    repository = FakeRepository()
    runtime = SessionAuthenticationRuntime(
        auth_service=auth, repository=repository, config=_config()
    )
    await runtime.start()
    lookup = asyncio.create_task(runtime.authenticate("blocked"))
    await asyncio.sleep(0.01)

    started = asyncio.get_running_loop().time()
    await runtime.stop()
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.15
    with pytest.raises(SessionAuthenticationUnavailableError, match="unavailable"):
        await runtime.authenticate("after-stop")
    gate.set()
    with pytest.raises(SessionAuthenticationUnavailableError):
        await lookup


@pytest.mark.asyncio
async def test_authentication_is_unavailable_before_start() -> None:
    runtime = SessionAuthenticationRuntime(
        auth_service=FakeAuthService(),
        repository=FakeRepository(),
        config=_config(),
    )

    with pytest.raises(SessionAuthenticationUnavailableError, match="unavailable"):
        await runtime.authenticate("before-start")

    await runtime.stop()


@pytest.mark.asyncio
async def test_shutdown_cancels_a_queued_lookup() -> None:
    gate = threading.Event()
    auth = FakeAuthService(gate=gate)
    runtime = SessionAuthenticationRuntime(
        auth_service=auth,
        repository=FakeRepository(),
        config=_config(maximum_admitted_lookups=2),
    )
    await runtime.start()
    running = asyncio.create_task(runtime.authenticate("running"))
    while auth.calls < 1:
        await asyncio.sleep(0.001)
    queued = asyncio.create_task(runtime.authenticate("queued"))
    await asyncio.sleep(0.005)

    await runtime.stop()

    with pytest.raises(SessionAuthenticationUnavailableError, match="unavailable"):
        await queued
    gate.set()
    with pytest.raises(SessionAuthenticationUnavailableError, match="timed out"):
        await running
    for thread in runtime._lookup_threads:
        thread.join(0.2)
    assert all(not thread.is_alive() for thread in runtime._lookup_threads)


@pytest.mark.asyncio
async def test_database_error_fails_closed_as_unavailable() -> None:
    runtime = SessionAuthenticationRuntime(
        auth_service=FakeAuthService(error=RuntimeError("database detail")),
        repository=FakeRepository(),
        config=_config(),
    )
    await runtime.start()

    with pytest.raises(SessionAuthenticationUnavailableError, match="lookup failed"):
        await runtime.authenticate("opaque")

    await runtime.stop()


@pytest.mark.asyncio
async def test_activity_scheduler_failure_does_not_invalidate_authentication() -> None:
    runtime = SessionAuthenticationRuntime(
        auth_service=FakeAuthService(),
        repository=FakeRepository(),
        config=_config(),
    )
    await runtime.start()

    def fail_scheduling(result) -> None:
        del result
        raise RuntimeError("scheduler detail")

    runtime._schedule_activity = fail_scheduling

    assert (await runtime.authenticate("opaque")).subject == "user"
    await runtime.stop()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, 86_401.0])
def test_runtime_rejects_invalid_durations(value: float) -> None:
    with pytest.raises(ValueError, match="finite and bounded"):
        _config(lookup_timeout_seconds=value)


@pytest.mark.asyncio
async def test_partial_thread_start_failure_rolls_back_started_workers(
    monkeypatch,
) -> None:
    runtime = SessionAuthenticationRuntime(
        auth_service=FakeAuthService(),
        repository=FakeRepository(),
        config=_config(lookup_workers=2, maximum_admitted_lookups=2),
    )
    original_start = threading.Thread.start
    calls = 0

    def fail_second_start(thread) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("thread start failed")
        original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_second_start)

    with pytest.raises(RuntimeError, match="thread start failed"):
        await runtime.start()

    assert runtime._state == "stopped"
    assert all(not thread.is_alive() for thread in runtime._lookup_threads)
