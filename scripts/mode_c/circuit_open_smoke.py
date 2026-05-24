"""Targeted smoke: feed the rate limiter 3 consecutive 429s, confirm the circuit
opens with the configured reset window, then auto-closes once the window elapses.

Useful as a quick sanity check that the production limiter's circuit-breaker
behavior matches expectations before any e-GP-targeted ramp.

Env vars (consumed by the production limiter):
  EGP_EGP_RPS                    default 10.0 (overridden here)
  EGP_EGP_BURST                  default 5    (overridden here)
  EGP_EGP_CIRCUIT_429_THRESHOLD  default 3
  EGP_EGP_CIRCUIT_RESET_SECONDS  default 5
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

os.environ.setdefault("EGP_EGP_RPS", "10.0")
os.environ.setdefault("EGP_EGP_BURST", "5")
os.environ.setdefault("EGP_EGP_CIRCUIT_429_THRESHOLD", "3")
os.environ.setdefault("EGP_EGP_CIRCUIT_RESET_SECONDS", "5")

sys.path.insert(0, str(REPO_ROOT / "packages" / "crawler-core" / "src"))

from egp_crawler_core.rate_limiter import (  # noqa: E402
    CircuitOpenError,
    FileLockRateLimiter,
    RateLimiterConfig,
    reset_default_rate_limiter_for_tests,
)

WORK_DIR = Path(os.environ.get("MODE_C_WORK_DIR", "/tmp/egp-mode-c"))
state = WORK_DIR / "rl-state" / "circuit.json"
state.parent.mkdir(parents=True, exist_ok=True)
if state.exists():
    state.unlink()
reset_default_rate_limiter_for_tests()

cfg = RateLimiterConfig.from_env(default_state_path=state)
lim = FileLockRateLimiter(cfg)

print(
    f"config: rps={cfg.requests_per_second} burst={cfg.burst} "
    f"circuit_threshold={cfg.circuit_429_threshold} reset_s={cfg.circuit_reset_seconds}"
)

for i in range(3):
    waited = lim.acquire(max_wait_seconds=2)
    print(f"  [{i}] acquire ok (waited={waited:.3f}s)")
    lim.record_outcome("ok")

print("\nFeeding 3 consecutive 429s:")
for i in range(3):
    lim.acquire(max_wait_seconds=2)
    lim.record_outcome("429")
    print(f"  recorded 429 #{i + 1}")

print("\nNext acquire with max_wait=0.1 (should raise CircuitOpenError):")
try:
    lim.acquire(max_wait_seconds=0.1)
    print("  FAIL: circuit did NOT open")
except CircuitOpenError as exc:
    print(f"  PASS: CircuitOpenError raised, reset_in={exc.reset_in_seconds:.2f}s")

print(f"\nWaiting {cfg.circuit_reset_seconds + 0.5}s for circuit reset...")
time.sleep(cfg.circuit_reset_seconds + 0.5)

try:
    waited = lim.acquire(max_wait_seconds=2)
    print(f"  PASS: acquire succeeded after reset (waited={waited:.3f}s)")
    lim.record_outcome("ok")
except CircuitOpenError as exc:
    print(f"  FAIL: still open after reset (reset_in={exc.reset_in_seconds:.2f}s)")
