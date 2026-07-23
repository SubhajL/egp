from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from urllib.request import urlopen

import pytest

from egp_crawler_core.rate_limiter import (
    CircuitOpenError,
    FileLockRateLimiter,
    RateLimiterConfig,
    exponential_backoff_delay,
)


class _TimestampHandler(BaseHTTPRequestHandler):
    timestamps: list[float] = []
    timestamps_lock = threading.Lock()

    def do_GET(self) -> None:
        with self.timestamps_lock:
            self.timestamps.append(time.monotonic())
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args) -> None:
        return None


def _start_timestamp_server() -> tuple[ThreadingHTTPServer, str]:
    _TimestampHandler.timestamps = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TimestampHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}/probe"


def test_file_lock_rate_limiter_limits_requests_across_workers(tmp_path: Path) -> None:
    server, url = _start_timestamp_server()
    participant_count = 4
    requests_per_second = 5.0
    config = RateLimiterConfig(
        requests_per_second=requests_per_second,
        burst=1,
        circuit_429_threshold=10,
        circuit_reset_seconds=30.0,
        state_path=tmp_path / "egp-rate-limit.json",
    )
    start_barrier = threading.Barrier(participant_count)

    def worker_request() -> None:
        limiter = FileLockRateLimiter(config)
        start_barrier.wait(timeout=5)
        limiter.acquire(max_wait_seconds=5.0)
        with urlopen(url, timeout=5) as response:
            assert response.read() == b"ok"
        limiter.record_outcome("success")

    try:
        with ThreadPoolExecutor(max_workers=participant_count) as executor:
            list(executor.map(lambda _: worker_request(), range(participant_count)))
    finally:
        server.shutdown()
        server.server_close()

    timestamps = sorted(_TimestampHandler.timestamps)
    assert len(timestamps) == participant_count
    observed_duration = timestamps[-1] - timestamps[0]
    assert observed_duration >= ((participant_count - 1) / requests_per_second) * 0.75


def test_circuit_opens_after_429_burst_and_resets(tmp_path: Path) -> None:
    limiter = FileLockRateLimiter(
        RateLimiterConfig(
            requests_per_second=100.0,
            burst=1,
            circuit_429_threshold=2,
            circuit_reset_seconds=0.15,
            state_path=tmp_path / "egp-rate-limit.json",
        )
    )

    limiter.record_outcome("429")
    limiter.record_outcome("429")

    assert limiter.is_circuit_open() is True
    with pytest.raises(CircuitOpenError):
        limiter.acquire(max_wait_seconds=0.0)

    time.sleep(0.2)
    limiter.acquire(max_wait_seconds=1.0)
    assert limiter.is_circuit_open() is False


def test_site_error_circuit_opens_and_uses_exponential_cooldown(tmp_path: Path) -> None:
    clock = {"now": 1_000.0}
    config = RateLimiterConfig(
        requests_per_second=0.0,
        burst=1,
        circuit_429_threshold=5,
        circuit_reset_seconds=30.0,
        site_error_threshold=2,
        site_error_base_seconds=10.0,
        site_error_max_seconds=40.0,
        state_path=tmp_path / "egp-rate-limit.json",
    )
    limiter = FileLockRateLimiter(config, now=lambda: clock["now"])
    peer_limiter = FileLockRateLimiter(config, now=lambda: clock["now"])

    limiter.record_outcome("site_error")
    assert limiter.is_circuit_open() is False
    peer_limiter.record_outcome("site_error")
    with pytest.raises(CircuitOpenError) as first_trip:
        peer_limiter.acquire(max_wait_seconds=0.0)
    assert first_trip.value.reset_in_seconds == 10.0

    clock["now"] += 11.0
    assert limiter.is_circuit_open() is False
    limiter.record_outcome("site_error")
    limiter.record_outcome("site_error")
    with pytest.raises(CircuitOpenError) as second_trip:
        limiter.acquire(max_wait_seconds=0.0)
    assert second_trip.value.reset_in_seconds == 20.0

    clock["now"] += 21.0
    peer_limiter.record_outcome("site_error")
    peer_limiter.record_outcome("site_error")
    with pytest.raises(CircuitOpenError) as capped_trip:
        limiter.acquire(max_wait_seconds=0.0)
    assert capped_trip.value.reset_in_seconds == 40.0

    clock["now"] += 41.0
    limiter.record_outcome("site_error")
    limiter.record_outcome("site_error")
    with pytest.raises(CircuitOpenError) as still_capped_trip:
        peer_limiter.acquire(max_wait_seconds=0.0)
    assert still_capped_trip.value.reset_in_seconds == 40.0

    clock["now"] += 41.0
    limiter.record_outcome("site_success")
    limiter.record_outcome("site_error")
    limiter.record_outcome("site_error")
    with pytest.raises(CircuitOpenError) as reset_trip:
        limiter.acquire(max_wait_seconds=0.0)
    assert reset_trip.value.reset_in_seconds == 10.0


def test_circuit_snapshot_exposes_sanitized_reset_time(tmp_path: Path) -> None:
    clock = {"now": 1_000.0}
    limiter = FileLockRateLimiter(
        RateLimiterConfig(
            requests_per_second=0.0,
            circuit_429_threshold=2,
            circuit_reset_seconds=30.0,
            state_path=tmp_path / "egp-rate-limit.json",
        ),
        now=lambda: clock["now"],
    )

    limiter.record_outcome("429")
    limiter.record_outcome("429")
    snapshot = limiter.get_circuit_snapshot()

    assert snapshot.is_open is True
    assert snapshot.reset_in_seconds == 30.0
    assert snapshot.reset_at == datetime.fromtimestamp(1_030.0, UTC).isoformat()
    assert snapshot.last_outcome == "429"


def test_rate_limiter_config_reads_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_EGP_RPS", "1.25")
    monkeypatch.setenv("EGP_EGP_BURST", "3")
    monkeypatch.setenv("EGP_EGP_CIRCUIT_429_THRESHOLD", "7")
    monkeypatch.setenv("EGP_EGP_CIRCUIT_RESET_SECONDS", "45")
    monkeypatch.setenv("EGP_EGP_SITE_ERROR_THRESHOLD", "4")
    monkeypatch.setenv("EGP_EGP_SITE_ERROR_BASE_SECONDS", "90")
    monkeypatch.setenv("EGP_EGP_SITE_ERROR_MAX_SECONDS", "900")

    config = RateLimiterConfig.from_env(default_state_path=tmp_path / "state.json")

    assert config.requests_per_second == 1.25
    assert config.burst == 3
    assert config.circuit_429_threshold == 7
    assert config.circuit_reset_seconds == 45.0
    assert config.site_error_threshold == 4
    assert config.site_error_base_seconds == 90.0
    assert config.site_error_max_seconds == 900.0
    assert config.state_path == tmp_path / "state.json"


def test_exponential_backoff_delay_has_jitter_bounds() -> None:
    low = exponential_backoff_delay(
        attempt=2,
        base_seconds=1.0,
        max_seconds=10.0,
        jitter_ratio=0.25,
        random_value=lambda: 0.0,
    )
    high = exponential_backoff_delay(
        attempt=2,
        base_seconds=1.0,
        max_seconds=10.0,
        jitter_ratio=0.25,
        random_value=lambda: 1.0,
    )

    assert low == 3.0
    assert high == 5.0


class _FakeLimiter:
    def __init__(self) -> None:
        self.acquire_calls = 0
        self.outcomes: list[str] = []

    def acquire(self, *, max_wait_seconds: float | None = None) -> float:
        del max_wait_seconds
        self.acquire_calls += 1
        return 0.0

    def record_outcome(self, outcome: str) -> None:
        self.outcomes.append(outcome)


class _FakeGotoPage:
    def __init__(self) -> None:
        self.goto_calls: list[tuple[str, str | None, int | None]] = []

    def goto(self, url: str, wait_until=None, timeout=None) -> None:
        self.goto_calls.append((url, wait_until, timeout))


class _FakeSearchPage:
    def __init__(self) -> None:
        self.evaluate_calls: list[tuple[str, object | None]] = []

    def evaluate(self, script: str, arg=None):
        self.evaluate_calls.append((script, arg))
        return True


class _FakeDownloadPage:
    def __init__(self) -> None:
        self.download_handlers: list[object] = []

    def on(self, event_name: str, handler) -> None:
        assert event_name == "download"
        self.download_handlers.append(handler)

    def remove_listener(self, event_name: str, handler) -> None:
        assert event_name == "download"
        self.download_handlers.remove(handler)

    def query_selector_all(self, selector: str):
        assert (
            selector == ".modal.show, .modal.fade.show, .swal2-popup, [role='dialog']"
        )
        return []


def test_browser_discovery_goto_and_search_use_rate_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from egp_worker import browser_discovery

    limiter = _FakeLimiter()
    monkeypatch.setattr(browser_discovery, "get_default_rate_limiter", lambda: limiter)

    page = _FakeGotoPage()
    browser_discovery._goto_with_recovery(
        page,
        "https://process5.gprocurement.go.th/egp-agpc01-web/announcement",
        browser_discovery.BrowserDiscoverySettings(nav_timeout_ms=1234),
    )
    browser_discovery.click_search_button(_FakeSearchPage())

    assert limiter.acquire_calls == 2
    assert limiter.outcomes == ["success", "success"]


def test_browser_download_click_uses_rate_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from egp_worker import browser_downloads

    limiter = _FakeLimiter()
    click_calls = 0
    monkeypatch.setattr(browser_downloads, "get_default_rate_limiter", lambda: limiter)
    monkeypatch.setattr(browser_downloads, "_sleep", lambda seconds: None)

    def click_action() -> None:
        nonlocal click_calls
        click_calls += 1

    result = browser_downloads._click_and_capture_immediate_download_or_missing_modal(
        _FakeDownloadPage(),
        click_action,
        file_label="TOR",
        click_context="test",
        timeout_s=0.01,
    )

    assert result is None
    assert click_calls == 1
    assert limiter.acquire_calls == 1
    assert limiter.outcomes == ["success"]
