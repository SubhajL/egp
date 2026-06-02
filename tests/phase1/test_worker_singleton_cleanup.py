"""TDD: clear_stale_singleton_locks — remove Chrome's leftover Singleton* locks
(often DANGLING symlinks) from a reused profile dir without touching real data.
"""

from __future__ import annotations

from types import SimpleNamespace

import egp_worker.browser_discovery as browser_discovery
from egp_worker.browser_discovery import (
    BrowserDiscoverySettings,
    clear_stale_singleton_locks,
)

LOCK_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def test_removes_lock_files_and_returns_names(tmp_path) -> None:
    for name in LOCK_NAMES:
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "Cookies").write_text("keep", encoding="utf-8")
    (tmp_path / "Local State").write_text("keep", encoding="utf-8")
    (tmp_path / "Default").mkdir()

    removed = clear_stale_singleton_locks(tmp_path)

    assert sorted(removed) == sorted(LOCK_NAMES)
    for name in LOCK_NAMES:
        assert not (tmp_path / name).exists()
    # real profile data is untouched
    assert (tmp_path / "Cookies").read_text(encoding="utf-8") == "keep"
    assert (tmp_path / "Local State").exists()
    assert (tmp_path / "Default").is_dir()


def test_removes_dangling_symlink_locks(tmp_path) -> None:
    # Chrome's SingletonLock is a dangling symlink "hostname-pid".
    (tmp_path / "SingletonLock").symlink_to("8957cb912d6a-19")
    assert (tmp_path / "SingletonLock").is_symlink()
    assert not (tmp_path / "SingletonLock").exists()  # dangling

    removed = clear_stale_singleton_locks(tmp_path)

    assert "SingletonLock" in removed
    assert not (tmp_path / "SingletonLock").is_symlink()


def test_noop_when_no_locks(tmp_path) -> None:
    assert clear_stale_singleton_locks(tmp_path) == []


def test_noop_when_dir_absent(tmp_path) -> None:
    assert clear_stale_singleton_locks(tmp_path / "does-not-exist") == []


def _stub_chrome_launch(monkeypatch) -> None:
    """Neutralize the real Chrome launch so launch_real_chrome runs lock-only."""
    monkeypatch.setattr(
        browser_discovery, "resolve_chrome_binary", lambda chrome_path: "/x/chrome"
    )
    monkeypatch.setattr(
        browser_discovery,
        "build_chrome_launch_command",
        lambda settings, chrome_path: ["x"],
    )
    monkeypatch.setattr(
        browser_discovery.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(pid=1),
    )
    monkeypatch.setattr(
        browser_discovery, "wait_for_local_tcp_listen", lambda *args, **kwargs: True
    )


def test_launch_does_not_clear_locks_by_default(tmp_path, monkeypatch) -> None:
    # The recovery relaunch must NOT touch a lock that a not-yet-reaped Chrome
    # from the same run may still legitimately hold.
    _stub_chrome_launch(monkeypatch)
    (tmp_path / "SingletonLock").write_text("x", encoding="utf-8")
    settings = BrowserDiscoverySettings(browser_profile_dir=tmp_path)

    browser_discovery.launch_real_chrome(settings)

    assert (tmp_path / "SingletonLock").exists()


def test_launch_clears_locks_when_opted_in(tmp_path, monkeypatch) -> None:
    # Workflow-entry launches (first discovery launch, warm-up, close-check)
    # opt in to clear a previous run's stale lock.
    _stub_chrome_launch(monkeypatch)
    (tmp_path / "SingletonLock").write_text("x", encoding="utf-8")
    settings = BrowserDiscoverySettings(browser_profile_dir=tmp_path)

    browser_discovery.launch_real_chrome(settings, clear_singleton_locks=True)

    assert not (tmp_path / "SingletonLock").exists()
