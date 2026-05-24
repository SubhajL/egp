"""Mode C dry run: N concurrent workers + rate limiter + e-GP stub + metrics scrape.

Exercises the production rate-limiter and metric-instrumentation code paths under
sustained load against a local stub. Use it before any production worker_count ramp
to confirm the rate limiter holds its target RPS and that metrics evolve as
expected.

Env vars:
  MODE_C_DURATION  default 60   (seconds)
  MODE_C_WORKERS   default 2
  MODE_C_WORK_DIR  default /tmp/egp-mode-c

Rate limiter env vars (consumed by the production limiter):
  EGP_EGP_RPS                       default 2.0 (overridden here)
  EGP_EGP_BURST                     default 1   (overridden here)
  EGP_EGP_CIRCUIT_429_THRESHOLD     default 3
  EGP_EGP_CIRCUIT_RESET_SECONDS     default 20

Prereq: scripts/mode_c/egp_stub_server.py must be running on 127.0.0.1:9999
(start it in a separate terminal, optionally with STUB_BURST_429_EVERY=5).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Rate limiter defaults targeted at making the limiter visibly engage in <60s.
os.environ.setdefault("EGP_EGP_RPS", "2.0")
os.environ.setdefault("EGP_EGP_BURST", "1")
os.environ.setdefault("EGP_EGP_CIRCUIT_429_THRESHOLD", "3")
os.environ.setdefault("EGP_EGP_CIRCUIT_RESET_SECONDS", "20")

for src_dir in (
    REPO_ROOT / "packages" / "crawler-core" / "src",
    REPO_ROOT / "packages" / "observability" / "src",
    REPO_ROOT / "apps" / "api" / "src",
    REPO_ROOT / "packages" / "db" / "src",
    REPO_ROOT / "packages" / "shared-types" / "src",
):
    sys.path.insert(0, str(src_dir))

from egp_crawler_core.rate_limiter import (  # noqa: E402
    CircuitOpenError,
    FileLockRateLimiter,
    RateLimiterConfig,
    reset_default_rate_limiter_for_tests,
)
from egp_observability.metrics import (  # noqa: E402
    initialize_metrics,
    observe_rate_limiter_wait,
    record_egp_request,
    render_prometheus_metrics,
)

initialize_metrics()

STUB_URL = "http://127.0.0.1:9999/"
DURATION_S = int(os.environ.get("MODE_C_DURATION", "60"))
WORKERS = int(os.environ.get("MODE_C_WORKERS", "2"))
WORK_DIR = Path(os.environ.get("MODE_C_WORK_DIR", "/tmp/egp-mode-c"))

state_dir = WORK_DIR / "rl-state"
state_dir.mkdir(parents=True, exist_ok=True)
state_path = state_dir / "egp.json"
if state_path.exists():
    state_path.unlink()
reset_default_rate_limiter_for_tests()

config = RateLimiterConfig.from_env(default_state_path=state_path)
print(
    f"Rate limiter config: rps={config.requests_per_second} "
    f"burst={config.burst} circuit_threshold={config.circuit_429_threshold} "
    f"circuit_reset_s={config.circuit_reset_seconds}"
)

limiter = FileLockRateLimiter(config)


def parse_metrics(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        try:
            out[parts[0]] = float(parts[1])
        except ValueError:
            pass
    return out


def metrics_snapshot() -> dict[str, float]:
    body, _ = render_prometheus_metrics()
    return parse_metrics(body.decode("utf-8"))


def worker_loop(worker_id: int, deadline: float, stats: dict) -> None:
    while time.time() < deadline:
        try:
            waited = limiter.acquire(max_wait_seconds=30.0)
        except CircuitOpenError as exc:
            stats["circuit_open_skips"] = stats.get("circuit_open_skips", 0) + 1
            time.sleep(min(2.0, exc.reset_in_seconds))
            continue
        observe_rate_limiter_wait(duration_seconds=waited)

        try:
            req = urllib.request.Request(STUB_URL, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception:
            status = 0

        outcome = "ok" if status == 200 else (str(status) if status else "error")
        record_egp_request(outcome=outcome)
        limiter.record_outcome(outcome)
        stats[outcome] = stats.get(outcome, 0) + 1
        time.sleep(0.01)


def poll_metrics(deadline: float, samples: list[dict]) -> None:
    while time.time() < deadline:
        snap = metrics_snapshot()
        samples.append(
            {
                "t": round(time.time() - START_TS, 1),
                "wait_count": snap.get("egp_rate_limiter_wait_seconds_count", 0.0),
                "wait_sum": snap.get("egp_rate_limiter_wait_seconds_sum", 0.0),
                "egp_ok": snap.get('egp_egp_request_total{outcome="ok"}', 0.0),
                "egp_429": snap.get('egp_egp_request_total{outcome="429"}', 0.0),
            }
        )
        time.sleep(10)


print(f"\nStarting {WORKERS} workers for {DURATION_S}s against {STUB_URL}\n")
START_TS = time.time()
deadline = START_TS + DURATION_S
worker_stats: list[dict] = [{} for _ in range(WORKERS)]
samples: list[dict] = []

with ThreadPoolExecutor(max_workers=WORKERS + 1) as pool:
    poll_fut = pool.submit(poll_metrics, deadline, samples)
    worker_futs = [
        pool.submit(worker_loop, i, deadline, worker_stats[i]) for i in range(WORKERS)
    ]
    for f in as_completed(worker_futs + [poll_fut]):
        try:
            f.result()
        except Exception as e:
            print(f"  worker/poller error: {e}")

elapsed = time.time() - START_TS
print(f"\nRun finished in {elapsed:.1f}s\n")

try:
    with urllib.request.urlopen("http://127.0.0.1:9999/__stats", timeout=2) as r:
        stub = json.loads(r.read().decode())
    print(
        f"Stub server received {stub['requests']} requests "
        f"(200={stub['ok']}, 429={stub['rate_429']})"
    )
except Exception as e:
    print(f"Could not read stub stats: {e}")

print("\nPer-worker outcomes:")
for i, s in enumerate(worker_stats):
    print(f"  worker {i}: {dict(sorted(s.items()))}")

print("\nMetric timeseries (10s samples):")
print(f"  {'t':>6} {'wait_count':>11} {'wait_sum':>9} {'egp_ok':>7} {'egp_429':>8}")
for s in samples:
    print(
        f"  {s['t']:>6.1f} {s['wait_count']:>11.1f} {s['wait_sum']:>9.2f} "
        f"{s['egp_ok']:>7.0f} {s['egp_429']:>8.0f}"
    )

final = samples[-1] if samples else None
print("\n--- PR-06 gate assertions ---")
if final:
    if final["wait_count"] > 0:
        print(f"  PASS: rate_limiter_wait_seconds_count = {final['wait_count']:.0f} (>0)")
    else:
        print("  FAIL: rate_limiter_wait_seconds_count == 0 (limiter never engaged)")
    print(
        f"  INFO: egp_egp_request_total ok={final['egp_ok']:.0f}, "
        f"429={final['egp_429']:.0f}"
    )

    burst_every = int(os.environ.get("STUB_BURST_429_EVERY", "0"))
    if burst_every:
        if final["egp_429"] > 0:
            print("  PASS: 429 outcomes recorded as expected from stub burst")
        else:
            print("  FAIL: stub configured to burst but no 429s recorded")
    else:
        if final["egp_429"] == 0:
            print("  PASS: 0 e-GP 429s (no bursts configured)")
        else:
            print(f"  WARN: {final['egp_429']:.0f} unexpected 429s")

    total = final["egp_ok"] + final["egp_429"]
    observed_rps = total / max(elapsed, 1)
    target_rps = config.requests_per_second
    if observed_rps <= target_rps * 1.5:
        print(f"  PASS: observed RPS = {observed_rps:.2f} <= 1.5x target {target_rps}")
    else:
        print(f"  FAIL: observed RPS = {observed_rps:.2f} > 1.5x target {target_rps}")
