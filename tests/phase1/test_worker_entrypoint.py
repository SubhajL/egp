from __future__ import annotations

import json
import subprocess
import sys


def test_python_module_worker_entrypoint_executes_main_for_noop() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "egp_worker.main"],
        input='{"command":"noop"}',
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"service": "worker", "status": "idle"}
