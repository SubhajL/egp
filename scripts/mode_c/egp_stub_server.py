"""Minimal stub of gprocurement.go.th for the Mode C dry run.

Returns 200 for most requests, optionally injects 429s on a fixed cadence.

Env vars:
  STUB_PORT             default 9999
  STUB_LATENCY_MS       default 50
  STUB_BURST_429_EVERY  default 0 (set to e.g. 5 to return 429 every 5th request)

Run:
  python scripts/mode_c/egp_stub_server.py
  STUB_BURST_429_EVERY=5 python scripts/mode_c/egp_stub_server.py
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock

PORT = int(os.environ.get("STUB_PORT", "9999"))
LATENCY_MS = int(os.environ.get("STUB_LATENCY_MS", "50"))
BURST_429_EVERY = int(os.environ.get("STUB_BURST_429_EVERY", "0"))


class _Counter:
    def __init__(self) -> None:
        self.lock = Lock()
        self.requests = 0
        self.responded_200 = 0
        self.responded_429 = 0


COUNTER = _Counter()


class StubHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        with COUNTER.lock:
            COUNTER.requests += 1
            req_num = COUNTER.requests
            inject_429 = BURST_429_EVERY > 0 and req_num % BURST_429_EVERY == 0

        time.sleep(LATENCY_MS / 1000.0)

        if self.path == "/__stats":
            with COUNTER.lock:
                payload = {
                    "requests": COUNTER.requests,
                    "ok": COUNTER.responded_200,
                    "rate_429": COUNTER.responded_429,
                }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if inject_429:
            with COUNTER.lock:
                COUNTER.responded_429 += 1
            self.send_response(429)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Retry-After", "5")
            self.end_headers()
            self.wfile.write(b"too many requests\n")
            return

        with COUNTER.lock:
            COUNTER.responded_200 += 1
        body = f"<html><body>stub response #{req_num}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), StubHandler)
    print(
        f"e-GP stub listening on 127.0.0.1:{PORT} "
        f"(latency_ms={LATENCY_MS}, burst_429_every={BURST_429_EVERY})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
