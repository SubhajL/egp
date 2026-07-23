"""Host-level e-GP rate limiting helpers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import tempfile
import time
from collections.abc import Callable, Iterator
from typing import Any

import fcntl


DEFAULT_EGP_RPS = 0.5
DEFAULT_EGP_BURST = 1
DEFAULT_CIRCUIT_429_THRESHOLD = 5
DEFAULT_CIRCUIT_RESET_SECONDS = 300.0
DEFAULT_SITE_ERROR_THRESHOLD = 2
DEFAULT_SITE_ERROR_BASE_SECONDS = 300.0
DEFAULT_SITE_ERROR_MAX_SECONDS = 1_800.0


class CircuitOpenError(RuntimeError):
    """Raised when the e-GP circuit is open and acquisition is fail-fast."""

    def __init__(self, *, reset_in_seconds: float) -> None:
        self.reset_in_seconds = max(0.0, float(reset_in_seconds))
        super().__init__(
            f"e-GP rate limiter circuit is open; reset in {self.reset_in_seconds:.3f}s"
        )


@dataclass(frozen=True, slots=True)
class RateLimiterConfig:
    requests_per_second: float = DEFAULT_EGP_RPS
    burst: int = DEFAULT_EGP_BURST
    circuit_429_threshold: int = DEFAULT_CIRCUIT_429_THRESHOLD
    circuit_reset_seconds: float = DEFAULT_CIRCUIT_RESET_SECONDS
    site_error_threshold: int = DEFAULT_SITE_ERROR_THRESHOLD
    site_error_base_seconds: float = DEFAULT_SITE_ERROR_BASE_SECONDS
    site_error_max_seconds: float = DEFAULT_SITE_ERROR_MAX_SECONDS
    state_path: Path = Path(tempfile.gettempdir()) / "egp-rate-limiter" / "egp.json"

    @classmethod
    def from_env(
        cls,
        *,
        environ: dict[str, str] | None = None,
        default_state_path: Path | None = None,
    ) -> "RateLimiterConfig":
        source = environ if environ is not None else os.environ
        default_rps = 0.0 if _running_under_pytest(source) else DEFAULT_EGP_RPS
        return cls(
            requests_per_second=_float_from_env(
                source,
                "EGP_EGP_RPS",
                default_rps,
            ),
            burst=_int_from_env(source, "EGP_EGP_BURST", DEFAULT_EGP_BURST),
            circuit_429_threshold=_int_from_env(
                source,
                "EGP_EGP_CIRCUIT_429_THRESHOLD",
                DEFAULT_CIRCUIT_429_THRESHOLD,
            ),
            circuit_reset_seconds=_float_from_env(
                source,
                "EGP_EGP_CIRCUIT_RESET_SECONDS",
                DEFAULT_CIRCUIT_RESET_SECONDS,
            ),
            site_error_threshold=_int_from_env(
                source,
                "EGP_EGP_SITE_ERROR_THRESHOLD",
                DEFAULT_SITE_ERROR_THRESHOLD,
            ),
            site_error_base_seconds=_float_from_env(
                source,
                "EGP_EGP_SITE_ERROR_BASE_SECONDS",
                DEFAULT_SITE_ERROR_BASE_SECONDS,
            ),
            site_error_max_seconds=_float_from_env(
                source,
                "EGP_EGP_SITE_ERROR_MAX_SECONDS",
                DEFAULT_SITE_ERROR_MAX_SECONDS,
            ),
            state_path=default_state_path
            or Path(tempfile.gettempdir()) / "egp-rate-limiter" / "egp.json",
        )


class FileLockRateLimiter:
    """File-lock token bucket shared by all worker processes on a host."""

    def __init__(
        self,
        config: RateLimiterConfig,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._now = now

    def acquire(self, *, max_wait_seconds: float | None = None) -> float:
        started_at = self._now()
        waited_seconds = 0.0
        while True:
            wait_seconds = 0.0
            circuit_wait_seconds = 0.0
            with self._locked_state() as state:
                now = self._now()
                self._normalize_state(state, now=now)
                circuit_open_until = float(state.get("circuit_open_until") or 0.0)
                if circuit_open_until > now:
                    circuit_wait_seconds = circuit_open_until - now
                    wait_seconds = circuit_wait_seconds
                else:
                    if circuit_open_until:
                        state["circuit_open_until"] = 0.0
                        state["consecutive_429"] = 0
                    wait_seconds = self._consume_or_wait(state, now=now)
                    if wait_seconds <= 0:
                        return waited_seconds

            if (
                max_wait_seconds is not None
                and waited_seconds + wait_seconds > max_wait_seconds
            ):
                if circuit_wait_seconds > 0:
                    raise CircuitOpenError(reset_in_seconds=circuit_wait_seconds)
                raise TimeoutError("timed out waiting for e-GP rate limiter token")
            self._sleep(wait_seconds)
            waited_seconds = max(0.0, self._now() - started_at)

    def record_outcome(self, outcome: str) -> None:
        normalized = str(outcome or "unknown").strip().casefold()
        with self._locked_state() as state:
            now = self._now()
            self._normalize_state(state, now=now)
            if normalized == "429":
                consecutive = int(state.get("consecutive_429") or 0) + 1
                state["consecutive_429"] = consecutive
                if consecutive >= max(1, int(self._config.circuit_429_threshold)):
                    state["circuit_open_until"] = max(
                        float(state.get("circuit_open_until") or 0.0),
                        now + max(0.0, float(self._config.circuit_reset_seconds)),
                    )
            elif normalized == "site_error":
                consecutive = int(state.get("consecutive_site_errors") or 0) + 1
                state["consecutive_site_errors"] = consecutive
                if consecutive >= max(1, int(self._config.site_error_threshold)):
                    trip_count = int(state.get("site_error_trip_count") or 0) + 1
                    base_seconds = max(0.0, float(self._config.site_error_base_seconds))
                    max_seconds = max(0.0, float(self._config.site_error_max_seconds))
                    cooldown_seconds = min(
                        max_seconds,
                        base_seconds * (2 ** max(0, trip_count - 1)),
                    )
                    state["consecutive_site_errors"] = 0
                    state["site_error_trip_count"] = trip_count
                    state["circuit_open_until"] = max(
                        float(state.get("circuit_open_until") or 0.0),
                        now + cooldown_seconds,
                    )
            elif normalized == "site_success":
                state["consecutive_site_errors"] = 0
                state["site_error_trip_count"] = 0
                if float(state.get("circuit_open_until") or 0.0) <= now:
                    state["circuit_open_until"] = 0.0
            elif normalized in {"success", "ok", "200"}:
                state["consecutive_429"] = 0
                if float(state.get("circuit_open_until") or 0.0) <= now:
                    state["circuit_open_until"] = 0.0
            state["last_outcome"] = normalized

    def is_circuit_open(self) -> bool:
        with self._locked_state() as state:
            now = self._now()
            self._normalize_state(state, now=now)
            circuit_open_until = float(state.get("circuit_open_until") or 0.0)
            if circuit_open_until > now:
                return True
            if circuit_open_until:
                state["circuit_open_until"] = 0.0
                state["consecutive_429"] = 0
            return False

    def _consume_or_wait(self, state: dict[str, Any], *, now: float) -> float:
        rps = max(0.0, float(self._config.requests_per_second))
        burst = max(1, int(self._config.burst))
        if rps <= 0:
            state["updated_at"] = now
            state["tokens"] = float(burst)
            return 0.0
        raw_updated_at = state.get("updated_at")
        updated_at = now if raw_updated_at is None else float(raw_updated_at)
        raw_tokens = state.get("tokens")
        tokens = float(burst) if raw_tokens is None else float(raw_tokens)
        tokens = min(float(burst), tokens)
        tokens = min(float(burst), tokens + max(0.0, now - updated_at) * rps)
        if tokens >= 1.0:
            state["tokens"] = tokens - 1.0
            state["updated_at"] = now
            return 0.0
        state["tokens"] = tokens
        state["updated_at"] = now
        return max(0.0, (1.0 - tokens) / rps)

    def _normalize_state(self, state: dict[str, Any], *, now: float) -> None:
        burst = max(1, int(self._config.burst))
        state.setdefault("tokens", float(burst))
        state.setdefault("updated_at", now)
        state.setdefault("consecutive_429", 0)
        state.setdefault("consecutive_site_errors", 0)
        state.setdefault("site_error_trip_count", 0)
        state.setdefault("circuit_open_until", 0.0)

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        path = self._config.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as state_file:
            fcntl.flock(state_file.fileno(), fcntl.LOCK_EX)
            state_file.seek(0)
            state = _decode_state(state_file.read())
            try:
                yield state
                state_file.seek(0)
                state_file.truncate()
                json.dump(state, state_file, sort_keys=True)
                state_file.flush()
                os.fsync(state_file.fileno())
            finally:
                fcntl.flock(state_file.fileno(), fcntl.LOCK_UN)


_default_rate_limiter: FileLockRateLimiter | None = None
_default_rate_limiter_config: RateLimiterConfig | None = None


def get_default_rate_limiter() -> FileLockRateLimiter:
    """Return the process-local handle for the host-shared e-GP limiter."""

    global _default_rate_limiter, _default_rate_limiter_config
    config = RateLimiterConfig.from_env()
    if _default_rate_limiter is None or config != _default_rate_limiter_config:
        _default_rate_limiter = FileLockRateLimiter(config)
        _default_rate_limiter_config = config
    return _default_rate_limiter


def reset_default_rate_limiter_for_tests() -> None:
    global _default_rate_limiter, _default_rate_limiter_config
    _default_rate_limiter = None
    _default_rate_limiter_config = None


def exponential_backoff_delay(
    *,
    attempt: int,
    base_seconds: float = 1.0,
    max_seconds: float = 30.0,
    jitter_ratio: float = 0.25,
    random_value: Callable[[], float] | None = None,
) -> float:
    """Return exponential backoff delay with symmetric bounded jitter."""

    base_delay = min(
        max(0.0, max_seconds), max(0.0, base_seconds) * (2 ** max(0, attempt))
    )
    jitter = max(0.0, min(1.0, jitter_ratio))
    if jitter == 0 or base_delay == 0:
        return base_delay
    draw = random.random() if random_value is None else random_value()
    multiplier = 1.0 + ((max(0.0, min(1.0, draw)) * 2.0) - 1.0) * jitter
    return max(0.0, min(max_seconds, base_delay * multiplier))


def _decode_state(raw: str) -> dict[str, Any]:
    try:
        decoded = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _float_from_env(source: dict[str, str], name: str, default: float) -> float:
    try:
        return max(0.0, float(str(source.get(name, "")).strip() or default))
    except (TypeError, ValueError):
        return default


def _int_from_env(source: dict[str, str], name: str, default: int) -> int:
    try:
        return max(1, int(str(source.get(name, "")).strip() or default))
    except (TypeError, ValueError):
        return default


def _running_under_pytest(source: dict[str, str]) -> bool:
    return "PYTEST_CURRENT_TEST" in source and "EGP_EGP_RPS" not in source
