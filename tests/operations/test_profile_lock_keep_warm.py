"""TDD: shared persistent-profile lock + lock-safe keep-warm.

The persistent Chrome profile must be used by at most one process at a time —
two Chrome instances on one ``user-data-dir`` corrupt it. The crawl dispatcher
and the keep-warm routine therefore share ONE exclusive flock (same file in the
profile dir), so a keep-warm heartbeat that fires mid-crawl exits as a no-op
instead of stomping the running crawl.
"""

from __future__ import annotations

import pytest

from egp_crawler_core.profile_lock import (
    PROFILE_LOCK_FILENAME,
    ProfileLockedError,
    acquire_profile_lock,
    release_profile_lock,
)


# --- shared lock primitive ------------------------------------------------


def test_acquire_creates_lock_file_and_returns_handle(tmp_path) -> None:
    handle = acquire_profile_lock(tmp_path)
    try:
        assert (tmp_path / PROFILE_LOCK_FILENAME).exists()
    finally:
        release_profile_lock(handle)


def test_acquire_creates_missing_profile_dir(tmp_path) -> None:
    target = tmp_path / "nested" / "prof"
    handle = acquire_profile_lock(target)
    try:
        assert target.is_dir()
    finally:
        release_profile_lock(handle)


def test_second_acquire_while_held_raises(tmp_path) -> None:
    first = acquire_profile_lock(tmp_path)
    try:
        with pytest.raises(ProfileLockedError):
            acquire_profile_lock(tmp_path)
    finally:
        release_profile_lock(first)


def test_release_allows_reacquire(tmp_path) -> None:
    first = acquire_profile_lock(tmp_path)
    release_profile_lock(first)
    second = acquire_profile_lock(tmp_path)  # must NOT raise
    release_profile_lock(second)


def test_release_none_is_noop() -> None:
    release_profile_lock(None)  # must not raise


# --- dispatcher preserves its DiscoverySpawnError contract ----------------


def test_dispatcher_lock_raises_spawn_error_when_held(tmp_path) -> None:
    """A crawl holding the shared lock => dispatcher raises DiscoverySpawnError."""
    from egp_api.services.discovery_worker_dispatcher import (
        DiscoverySpawnError,
        _acquire_profile_lock,
    )

    held = acquire_profile_lock(tmp_path)
    try:
        with pytest.raises(DiscoverySpawnError, match="locked by another crawl"):
            _acquire_profile_lock(tmp_path)
    finally:
        release_profile_lock(held)


def test_dispatcher_lock_acquires_when_free_and_shares_lock(tmp_path) -> None:
    """Dispatcher uses the SAME lock: while it holds it, shared acquire fails."""
    from egp_api.services.discovery_worker_dispatcher import (
        _acquire_profile_lock,
        _release_profile_lock,
    )

    handle = _acquire_profile_lock(tmp_path)
    try:
        with pytest.raises(ProfileLockedError):
            acquire_profile_lock(tmp_path)
    finally:
        _release_profile_lock(handle)
    # released => free again
    again = acquire_profile_lock(tmp_path)
    release_profile_lock(again)


# --- warm-up respects the lock (skip-if-busy) -----------------------------


def test_warmup_skips_when_profile_locked(tmp_path, monkeypatch, capsys) -> None:
    """If a crawl holds the lock, warm-up must NOT launch a second Chrome."""
    import egp_worker.warmup as warmup

    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("EGP_BROWSER_WARMUP_SECONDS", "0")

    def _must_not_launch(*args, **kwargs):
        raise AssertionError("launch_real_chrome ran while the profile was locked")

    monkeypatch.setattr(warmup, "launch_real_chrome", _must_not_launch)

    held = acquire_profile_lock(tmp_path)  # simulate an in-flight crawl
    try:
        rc = warmup.main()
    finally:
        release_profile_lock(held)

    assert rc == 0
    assert "WARMUP_SKIP" in capsys.readouterr().out


def test_warmup_runs_and_releases_when_profile_free(
    tmp_path, monkeypatch, capsys
) -> None:
    """When free, warm-up launches/warms once and releases the lock afterwards."""
    import egp_worker.warmup as warmup

    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("EGP_BROWSER_WARMUP_SECONDS", "0")

    calls = {"launched": 0, "warmed": 0, "shutdown": 0}

    class _FakePlaywright:
        def start(self):
            return self

    def _fake_launch(*args, **kwargs):
        calls["launched"] += 1
        return object()

    def _fake_connect(pw, settings):
        return object(), object()

    def _fake_warm(*args, **kwargs):
        calls["warmed"] += 1

    def _fake_shutdown(**kwargs):
        calls["shutdown"] += 1

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", lambda: _FakePlaywright()
    )
    monkeypatch.setattr(warmup, "launch_real_chrome", _fake_launch)
    monkeypatch.setattr(warmup, "connect_playwright_to_chrome", _fake_connect)
    monkeypatch.setattr(warmup, "warm_page", _fake_warm)
    monkeypatch.setattr(warmup, "safe_shutdown", _fake_shutdown)

    rc = warmup.main()

    assert rc == 0
    assert calls == {"launched": 1, "warmed": 1, "shutdown": 1}
    assert "WARMUP_OK" in capsys.readouterr().out
    # lock released => re-acquire must succeed
    handle = acquire_profile_lock(tmp_path)
    release_profile_lock(handle)


def test_warmup_success_resets_operator_action_required_state(
    tmp_path, monkeypatch, capsys
) -> None:
    """A successful manual warm must clear dispatcher pause state."""
    import json

    import egp_worker.warmup as warmup

    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("EGP_BROWSER_WARMUP_SECONDS", "0")
    (tmp_path / ".egp-profile-state.json").write_text(
        json.dumps(
            {
                "consecutive_warm_failures": 2,
                "last_failure_error": "warm-up failed: Cloudflare not cleared",
                "operator_action_required": True,
            }
        ),
        encoding="utf-8",
    )

    class _FakePlaywright:
        def start(self):
            return self

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", lambda: _FakePlaywright()
    )
    monkeypatch.setattr(warmup, "launch_real_chrome", lambda *a, **k: object())
    monkeypatch.setattr(
        warmup, "connect_playwright_to_chrome", lambda *a, **k: (object(), object())
    )
    monkeypatch.setattr(warmup, "warm_page", lambda *a, **k: None)
    monkeypatch.setattr(warmup, "safe_shutdown", lambda **kwargs: None)

    assert warmup.main() == 0

    state = json.loads(
        (tmp_path / ".egp-profile-state.json").read_text(encoding="utf-8")
    )
    assert state["consecutive_warm_failures"] == 0
    assert state["operator_action_required"] is False
    assert state["source"] == "warm"
    assert "WARMUP_OK" in capsys.readouterr().out


def test_warmup_releases_lock_when_launch_fails(tmp_path, monkeypatch) -> None:
    """If Chrome launch raises, warm-up must still clean up AND release the lock."""
    import egp_worker.warmup as warmup

    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("EGP_BROWSER_WARMUP_SECONDS", "0")

    shutdowns = {"n": 0}

    def _boom_launch(*args, **kwargs):
        raise RuntimeError("chrome failed to start")

    def _fake_shutdown(**kwargs):
        shutdowns["n"] += 1

    monkeypatch.setattr(warmup, "launch_real_chrome", _boom_launch)
    monkeypatch.setattr(warmup, "safe_shutdown", _fake_shutdown)

    with pytest.raises(RuntimeError, match="chrome failed to start"):
        warmup.main()

    # cleanup must have run, and the lock must be free again
    assert shutdowns["n"] == 1
    handle = acquire_profile_lock(tmp_path)
    release_profile_lock(handle)
