"""Fixed child-process outcomes for operator/test-only discovery fault injection."""

from __future__ import annotations

import json
import os
import signal
import sys
import time


FAULT_MODES = frozenset(
    {
        "worker_timeout",
        "nonzero_exit",
        "missing_result",
        "entitlement_denied",
        "worker_crash",
    }
)


def main(argv: list[str] | None = None) -> int:
    """Consume the parent payload, then produce one fixed process outcome."""

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in FAULT_MODES:
        return 2
    fault_mode = args[0]
    sys.stdin.buffer.read()

    if fault_mode == "worker_timeout":
        time.sleep(24 * 60 * 60)
        return 0
    if fault_mode == "nonzero_exit":
        return 17
    if fault_mode == "missing_result":
        return 0
    if fault_mode == "entitlement_denied":
        print(
            json.dumps(
                {
                    "error_type": "entitlement_denied",
                    "detail": "fault injection entitlement denial",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 18
    os.kill(os.getpid(), signal.SIGTERM)
    return 19


if __name__ == "__main__":
    raise SystemExit(main())
