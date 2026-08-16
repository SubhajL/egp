"""Structured logging primitives for e-GP services.

Provides correlated, bounded, redacted logging and result framing
for the subprocess discovery dispatcher.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

RESULT_FRAME_BEGIN: Final[str] = "---EGP_RESULT_BEGIN---"
RESULT_FRAME_END: Final[str] = "---EGP_RESULT_END---"

_SECRET_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"(?<=://)[^:\s/]+:[^@\s/]+@"), "[REDACTED]@"),
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]*)?"),
        "[REDACTED]",
    ),
    (re.compile(r"(?i)Bearer\s+\S+"), "[REDACTED]"),
    (re.compile(r"(?i)Basic\s+[A-Za-z0-9+/=]+"), "[REDACTED]"),
    (
        re.compile(
            r"(?i)([\"']?(?:password|passwd|token|secret|api[_-]?key|"
            r"service[_-]?role[_-]?key|authorization)[\"']?\s*[:=]\s*[\"']?)"
            r"[^\s,}\"']+"
        ),
        r"\1[REDACTED]",
    ),
)


def make_event(
    event: str,
    *,
    run_id: str | None = None,
    job_id: str | None = None,
    owner_pid: int | None = None,
    child_pid: int | None = None,
    execution_backend: str | None = None,
    release_sha: str | None = None,
    **extra: object,
) -> str:
    data: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    for key, val in (
        ("run_id", run_id),
        ("job_id", job_id),
        ("owner_pid", owner_pid),
        ("child_pid", child_pid),
        ("execution_backend", execution_backend),
        ("release_sha", release_sha),
    ):
        if val is not None:
            data[key] = val
    for key, val in extra.items():
        data[key] = str(val)
    return json.dumps(data, sort_keys=True)


def redact_preview(text: str) -> str:
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def tail_bounded_preview(
    text: bytes | str | None,
    *,
    limit: int = 2000,
) -> str | None:
    if text is None:
        return None
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        return None
    redacted = redact_preview(text)
    if len(redacted) <= limit:
        return redacted
    return "..." + redacted[-limit:]


def rotate_log_copytruncate(
    path: Path,
    *,
    max_bytes: int = 50_000_000,
    max_files: int = 3,
) -> bool:
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return False
        prefix = path.name + "."
        for f in path.parent.iterdir():
            if f.name.startswith(prefix) and f.name[len(prefix):].isdigit():
                n = int(f.name[len(prefix):])
                if n > max_files:
                    f.unlink()
        for n in range(max_files, 0, -1):
            old = path.parent / (path.name + f".{n}")
            if old.exists():
                if n == max_files:
                    old.unlink()
                else:
                    old.rename(path.parent / (path.name + f".{n + 1}"))
        shutil.copy2(path, path.parent / (path.name + ".1"))
        path.open("w").close()
        return True
    except Exception:
        return False
