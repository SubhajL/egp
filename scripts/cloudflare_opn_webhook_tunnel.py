"""Open a Cloudflare quick tunnel for local OPN webhook testing.

This helper is intentionally lightweight: it forwards a local FastAPI port to a
public `trycloudflare.com` URL and prints the exact webhook URL that should be
configured in the OPN test dashboard.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urljoin

_TRYCLOUDFLARE_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
_DEFAULT_WEBHOOK_PATH = "/v1/billing/providers/opn/webhooks"


def extract_trycloudflare_url(text: str) -> str | None:
    match = _TRYCLOUDFLARE_PATTERN.search(text)
    if match is None:
        return None
    return match.group(0).rstrip("/")


def build_local_url(*, port: int, host: str = "127.0.0.1", scheme: str = "http") -> str:
    return f"{scheme}://{host}:{port}"


def build_webhook_url(base_url: str, *, path: str = _DEFAULT_WEBHOOK_PATH) -> str:
    normalized_base = base_url.rstrip("/") + "/"
    normalized_path = path.lstrip("/")
    return urljoin(normalized_base, normalized_path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("EGP_API_PORT", "8010")),
        help="Local FastAPI port to expose (default: EGP_API_PORT or 8010)",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("EGP_API_HOST", "127.0.0.1"),
        help="Local FastAPI host to expose (default: EGP_API_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--scheme",
        default="http",
        choices=["http", "https"],
        help="Scheme for the local API target (default: http)",
    )
    parser.add_argument(
        "--path",
        default=_DEFAULT_WEBHOOK_PATH,
        help=f"Webhook path to print for OPN (default: {_DEFAULT_WEBHOOK_PATH})",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    executable = shutil.which("cloudflared")
    if executable is None:
        print(
            "cloudflared is not installed. Install it first, for example with `brew install cloudflared`.",
            file=sys.stderr,
        )
        return 1

    local_url = build_local_url(port=args.port, host=args.host, scheme=args.scheme)
    command = [executable, "tunnel", "--url", local_url]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    tunnel_announced = False
    try:
        assert process.stdout is not None
        for line in process.stdout:
            stripped = line.rstrip()
            if stripped:
                print(stripped)
            tunnel_url = extract_trycloudflare_url(stripped)
            if tunnel_url is not None and not tunnel_announced:
                webhook_url = build_webhook_url(tunnel_url, path=args.path)
                print("\n=== OPN local webhook test endpoint ===")
                print(f"Local API target: {local_url}")
                print(f"Tunnel URL:       {tunnel_url}")
                print(f"Webhook URL:      {webhook_url}")
                print("OPN test keys:    https://dashboard.omise.co/test/keys")
                print("OPN test webhook: https://dashboard.omise.co/test/webhooks")
                print("Keep this process running while OPN sends callbacks.\n")
                tunnel_announced = True
        return process.wait()
    except KeyboardInterrupt:
        print("\nStopping cloudflared tunnel...", file=sys.stderr)
        process.terminate()
        return process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(run())
