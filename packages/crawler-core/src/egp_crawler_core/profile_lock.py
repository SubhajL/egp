"""Cross-process exclusive lock for a persistent browser profile.

A persistent Chrome ``user-data-dir`` must be used by at most one process at a
time: two Chrome instances on the same profile corrupt it. Both the discovery
worker dispatcher (a crawl) and the keep-warm routine acquire THIS same lock —
same file (:data:`PROFILE_LOCK_FILENAME`) in the profile dir — so a keep-warm
heartbeat can never collide with an in-flight crawl. POSIX ``fcntl.flock``;
works on macOS and Linux.
"""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import IO

PROFILE_LOCK_FILENAME = ".egp-crawl.lock"


class ProfileLockedError(RuntimeError):
    """Raised when the persistent profile is already locked by another process."""


def acquire_profile_lock(profile_dir: Path) -> IO[str]:
    """Take an exclusive, non-blocking flock on the profile's lock file.

    Creates ``profile_dir`` if needed. Returns the open lock-file handle, which
    the caller MUST release via :func:`release_profile_lock`. Raises
    :class:`ProfileLockedError` if the profile is already locked (e.g. a crawl
    is running while a keep-warm pass fires, or vice versa).
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    lock_path = profile_dir / PROFILE_LOCK_FILENAME
    handle = lock_path.open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise ProfileLockedError(
            f"persistent browser profile is locked by another process ({profile_dir})"
        ) from exc
    return handle


def release_profile_lock(handle: IO[str] | None) -> None:
    """Release and close a handle returned by :func:`acquire_profile_lock`."""
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()
