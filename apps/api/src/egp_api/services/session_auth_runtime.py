"""Bounded async bridge and best-effort activity coalescing for cookie sessions."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
import queue
import threading
import time

from egp_api.auth import AuthContext
from egp_api.services.auth_service import AuthService, SessionAuthenticationResult
from egp_db.repositories.auth_repo import SqlAuthRepository


class SessionAuthenticationUnavailableError(RuntimeError):
    """The bounded session authentication runtime cannot serve this request."""


@dataclass(frozen=True, slots=True)
class SessionAuthenticationRuntimeConfig:
    lookup_workers: int = 4
    maximum_admitted_lookups: int = 32
    lookup_timeout_seconds: float = 2.0
    activity_queue_capacity: int = 1024
    activity_interval_seconds: float = 300.0
    recent_activity_capacity: int = 8192
    shutdown_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.lookup_workers <= 0:
            raise ValueError("lookup_workers must be positive")
        if self.maximum_admitted_lookups < self.lookup_workers:
            raise ValueError("maximum_admitted_lookups must cover lookup_workers")
        for value in (
            self.lookup_timeout_seconds,
            self.activity_interval_seconds,
            self.shutdown_timeout_seconds,
        ):
            if not math.isfinite(value) or value <= 0 or value > 86_400:
                raise ValueError("session runtime durations must be finite and bounded")
        if self.activity_queue_capacity <= 0:
            raise ValueError("activity_queue_capacity must be positive")
        if self.recent_activity_capacity < self.activity_queue_capacity + 1:
            raise ValueError("recent_activity_capacity must cover queued and active writes")


@dataclass(frozen=True, slots=True)
class _LookupRequest:
    session_token: str
    future: Future[SessionAuthenticationResult | None]


@dataclass(frozen=True, slots=True)
class _ActivityObservation:
    tenant_id: str
    session_id: str
    observed_at: datetime


class SessionAuthenticationRuntime:
    def __init__(
        self,
        *,
        auth_service: AuthService,
        repository: SqlAuthRepository,
        config: SessionAuthenticationRuntimeConfig | None = None,
    ) -> None:
        self._auth_service = auth_service
        self._repository = repository
        self._config = config or SessionAuthenticationRuntimeConfig()
        self._admission = threading.BoundedSemaphore(
            self._config.maximum_admitted_lookups
        )
        self._lookup_queue: queue.Queue[_LookupRequest | None] = queue.Queue(
            maxsize=self._config.maximum_admitted_lookups
        )
        self._lookup_futures: set[Future[SessionAuthenticationResult | None]] = set()
        self._lookup_futures_lock = threading.Lock()
        self._lookup_threads: list[threading.Thread] = []
        self._activity_queue: queue.Queue[_ActivityObservation | None] = queue.Queue(
            maxsize=self._config.activity_queue_capacity
        )
        self._activity_lock = threading.Lock()
        self._pending_activity: set[tuple[str, str]] = set()
        self._next_activity_at: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._activity_stop = threading.Event()
        self._activity_thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._state = "created"

    async def start(self) -> None:
        with self._lifecycle_lock:
            if self._state == "running":
                return
            if self._state != "created":
                raise RuntimeError("session authentication runtime cannot be restarted")
            self._state = "starting"
            self._lookup_threads = [
                threading.Thread(
                    target=self._run_lookup_worker,
                    daemon=True,
                    name=f"egp-session-lookup-{index}",
                )
                for index in range(self._config.lookup_workers)
            ]
            self._activity_thread = threading.Thread(
                target=self._run_activity_worker,
                daemon=True,
                name="egp-session-activity",
            )
        started_threads: list[threading.Thread] = []
        try:
            for thread in self._lookup_threads:
                thread.start()
                started_threads.append(thread)
            self._activity_thread.start()
            started_threads.append(self._activity_thread)
        except BaseException:
            self._activity_stop.set()
            for _ in started_threads:
                try:
                    self._lookup_queue.put_nowait(None)
                except queue.Full:
                    break
            deadline = time.monotonic() + self._config.shutdown_timeout_seconds
            for thread in started_threads:
                thread.join(max(0.0, deadline - time.monotonic()))
            with self._lifecycle_lock:
                self._state = "stopped"
            raise
        with self._lifecycle_lock:
            self._state = "running"

    async def stop(self) -> None:
        with self._lifecycle_lock:
            if self._state == "stopped":
                return
            if self._state == "created":
                self._state = "stopped"
                return
            self._state = "stopping"
        deadline = time.monotonic() + self._config.shutdown_timeout_seconds
        self._activity_stop.set()
        self._cancel_queued_lookups()
        for _ in self._lookup_threads:
            try:
                self._lookup_queue.put_nowait(None)
            except queue.Full:
                break
        try:
            self._activity_queue.put_nowait(None)
        except queue.Full:
            pass
        threads = (*self._lookup_threads, self._activity_thread)
        for thread in threads:
            if thread is not None:
                await asyncio.to_thread(thread.join, max(0.0, deadline - time.monotonic()))
        with self._lifecycle_lock:
            self._state = "stopped"

    async def authenticate(self, session_token: str) -> AuthContext | None:
        with self._lifecycle_lock:
            if self._state != "running":
                raise SessionAuthenticationUnavailableError("runtime unavailable")
        if not self._admission.acquire(blocking=False):
            raise SessionAuthenticationUnavailableError("lookup saturated")
        future: Future[SessionAuthenticationResult | None] = Future()
        with self._lifecycle_lock:
            if self._state != "running":
                self._admission.release()
                raise SessionAuthenticationUnavailableError("runtime unavailable")
            with self._lookup_futures_lock:
                self._lookup_futures.add(future)
            try:
                self._lookup_queue.put_nowait(
                    _LookupRequest(session_token=session_token, future=future)
                )
            except queue.Full as exc:
                with self._lookup_futures_lock:
                    self._lookup_futures.discard(future)
                self._admission.release()
                raise SessionAuthenticationUnavailableError("lookup saturated") from exc

        def lookup_finished(completed: Future[SessionAuthenticationResult | None]) -> None:
            self._admission.release()
            with self._lookup_futures_lock:
                self._lookup_futures.discard(completed)

        future.add_done_callback(lookup_finished)
        try:
            result = await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(future)),
                timeout=self._config.lookup_timeout_seconds,
            )
        except TimeoutError as exc:
            raise SessionAuthenticationUnavailableError("lookup timed out") from exc
        except asyncio.CancelledError:
            if future.cancelled():
                raise SessionAuthenticationUnavailableError("runtime unavailable") from None
            raise
        except Exception as exc:
            raise SessionAuthenticationUnavailableError("lookup failed") from exc
        if result is None:
            return None
        try:
            self._schedule_activity(result)
        except Exception:
            # Activity accounting is intentionally best effort and cannot invalidate auth.
            pass
        return result.context

    def _run_lookup_worker(self) -> None:
        while True:
            request = self._lookup_queue.get()
            try:
                if request is None:
                    return
                if not request.future.set_running_or_notify_cancel():
                    continue
                try:
                    result = self._auth_service.authenticate_session(request.session_token)
                except BaseException as exc:
                    request.future.set_exception(exc)
                else:
                    request.future.set_result(result)
            finally:
                self._lookup_queue.task_done()
            if self._activity_stop.is_set():
                return

    def _cancel_queued_lookups(self) -> None:
        while True:
            try:
                request = self._lookup_queue.get_nowait()
            except queue.Empty:
                return
            try:
                if request is not None:
                    request.future.cancel()
            finally:
                self._lookup_queue.task_done()

    def _schedule_activity(self, result: SessionAuthenticationResult) -> None:
        now = datetime.now(UTC)
        if result.last_seen_at is not None:
            last_seen = result.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            if last_seen > now - timedelta(seconds=self._config.activity_interval_seconds):
                return
        key = (result.tenant_id, result.session_id)
        monotonic_now = time.monotonic()
        with self._activity_lock:
            if key in self._pending_activity or self._next_activity_at.get(key, 0) > monotonic_now:
                return
            observation = _ActivityObservation(
                tenant_id=result.tenant_id,
                session_id=result.session_id,
                observed_at=now,
            )
            try:
                self._activity_queue.put_nowait(observation)
            except queue.Full:
                return
            self._pending_activity.add(key)
            self._next_activity_at[key] = (
                monotonic_now + self._config.activity_interval_seconds
            )
            self._next_activity_at.move_to_end(key)
            self._trim_recent_activity()

    def _trim_recent_activity(self) -> None:
        while len(self._next_activity_at) > self._config.recent_activity_capacity:
            oldest_key = next(iter(self._next_activity_at))
            if oldest_key in self._pending_activity:
                self._next_activity_at.move_to_end(oldest_key)
                if all(key in self._pending_activity for key in self._next_activity_at):
                    return
                continue
            self._next_activity_at.popitem(last=False)

    def _run_activity_worker(self) -> None:
        while not self._activity_stop.is_set():
            try:
                observation = self._activity_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if observation is None:
                self._activity_queue.task_done()
                return
            key = (observation.tenant_id, observation.session_id)
            try:
                self._repository.touch_session_activity(
                    tenant_id=observation.tenant_id,
                    session_ids=(observation.session_id,),
                    observed_at=observation.observed_at,
                    minimum_interval_seconds=self._config.activity_interval_seconds,
                )
            except Exception:
                with self._activity_lock:
                    self._next_activity_at.pop(key, None)
            finally:
                with self._activity_lock:
                    self._pending_activity.discard(key)
                self._activity_queue.task_done()
