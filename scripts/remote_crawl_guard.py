#!/usr/bin/env python3
"""Safety guard for Track C — the local Mac crawler pointed at PRODUCTION.

See ``docs/REMOTE_LOCAL_CRAWLER.md`` and ``TRACKS.md``. ``scripts/run_local.sh``
(Track A) refuses to touch anything but ``localhost:5434``; this guard is the
deliberate inverse — it REFUSES to run unless the operator has explicitly
acknowledged production and every safety rail is in place:

  * production acknowledgement token present,
  * worker events posted to the API over **https**,
  * artifacts written to **Supabase** (not local files the API can't serve),
  * a real warmed **persistent single-flight** Chrome profile, outside synced
    folders,
  * the database target is a legitimate prod connection — an SSH-tunnel
    loopback port (Topology A) or a TLS Supabase URL (Topology B) — and NEVER
    the localdev ``localhost:5434`` database.

Pure functions take a plain ``Mapping`` so they are unit-testable; ``main``
loads ``--env-file`` via the strict ``parse_env_file`` (NO shell evaluation) or
falls back to ``os.environ``. The bash wrapper never ``source``s the env file.
"""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

PRODUCTION_ACK_VALUE = "I_UNDERSTAND_THIS_WRITES_PRODUCTION"
LOCALDEV_DB_PORT = 5434
DEFAULT_TUNNEL_LOCAL_PORT = 15432
_PLACEHOLDER_MARKER = "CHANGE_ME"
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_TLS_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})
_SYNC_FOLDER_MARKERS = (
    "onedrive",
    "icloud",
    "dropbox",
    "google drive",
    "library/mobile documents",
)


class RemoteCrawlGuardError(RuntimeError):
    """Raised when the remote-crawl environment is unsafe to run."""


def _coerce_port(value: str) -> int | None:
    """Return an int port if ``value`` is a valid 1..65535 port, else ``None``."""
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _expected_tunnel_local_port(config: Mapping[str, str]) -> int:
    return (
        _coerce_port(_get(config, "EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT"))
        or DEFAULT_TUNNEL_LOCAL_PORT
    )


def parse_env_file(path: str | os.PathLike[str]) -> dict[str, str]:
    """Parse a strict ``KEY=value`` dotenv file with NO shell expansion.

    Blank lines and ``#`` comments are ignored. A leading ``export`` is
    stripped. Surrounding single/double quotes are removed; ``${...}`` and
    ``$(...)`` are preserved verbatim (never expanded).
    """
    result: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if key:
                result[key] = value
    return result


def _get(config: Mapping[str, str], key: str) -> str:
    return str(config.get(key, "") or "").strip()


def validate_remote_crawl_env(config: Mapping[str, str]) -> list[str]:
    """Return a list of safety problems with the non-DB environment (empty=ok)."""
    problems: list[str] = []

    if _get(config, "EGP_REMOTECRAWL_PRODUCTION_ACK") != PRODUCTION_ACK_VALUE:
        problems.append(
            "missing/invalid EGP_REMOTECRAWL_PRODUCTION_ACK "
            f"(must equal {PRODUCTION_ACK_VALUE!r} to acknowledge writing PRODUCTION)"
        )

    api_base = _get(config, "EGP_INTERNAL_API_BASE_URL")
    if not api_base.startswith("https://"):
        problems.append(
            "EGP_INTERNAL_API_BASE_URL must be an https:// URL "
            "(worker events cross the public internet to the control-plane)"
        )

    if _get(config, "EGP_ARTIFACT_STORE").lower() != "supabase":
        problems.append(
            "EGP_ARTIFACT_STORE must be 'supabase' so artifacts land in the "
            "bucket the API serves (not local files on this Mac)"
        )
    for supabase_key in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_STORAGE_BUCKET",
    ):
        if not _get(config, supabase_key):
            problems.append(f"{supabase_key} is required for Supabase artifact storage")

    if not _get(config, "EGP_BROWSER_CHROME_PATH"):
        problems.append(
            "EGP_BROWSER_CHROME_PATH must point at real Google Chrome "
            "(only a real warmed browser clears Cloudflare Turnstile)"
        )

    if _get(config, "EGP_BROWSER_PROFILE_MODE").lower() != "persistent":
        problems.append(
            "EGP_BROWSER_PROFILE_MODE must be 'persistent' (a warmed profile is "
            "required to pass attestation)"
        )
    profile_dir = _get(config, "EGP_BROWSER_PERSISTENT_PROFILE_DIR")
    if not profile_dir:
        problems.append(
            "EGP_BROWSER_PERSISTENT_PROFILE_DIR is required when profile mode is persistent"
        )
    else:
        lowered = profile_dir.lower()
        marker = next((m for m in _SYNC_FOLDER_MARKERS if m in lowered), None)
        if marker is not None:
            problems.append(
                f"EGP_BROWSER_PERSISTENT_PROFILE_DIR is inside a synced folder ({marker!r}); "
                "browser profiles corrupt there — move it outside OneDrive/iCloud/Dropbox"
            )

    if _get(config, "EGP_DISCOVERY_WORKER_COUNT") != "1":
        problems.append(
            "EGP_DISCOVERY_WORKER_COUNT must be 1 — a single warmed persistent "
            "profile is single-flight (one browser at a time)"
        )

    if not _get(config, "EGP_INTERNAL_WORKER_TOKEN"):
        problems.append(
            "EGP_INTERNAL_WORKER_TOKEN is required — the API rejects worker event "
            "ingestion (/internal/worker/*) without it"
        )

    for port_key in (
        "EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT",
        "EGP_REMOTECRAWL_TUNNEL_REMOTE_PORT",
    ):
        raw_port = _get(config, port_key)
        if raw_port and _coerce_port(raw_port) is None:
            problems.append(f"{port_key} must be an integer in 1..65535")

    # No required value may still hold a copy-the-template placeholder.
    for key, value in config.items():
        if _PLACEHOLDER_MARKER in str(value):
            problems.append(
                f"{key} still contains a {_PLACEHOLDER_MARKER} placeholder — fill it in"
            )

    return problems


def validate_database_topology(config: Mapping[str, str]) -> list[str]:
    """Return DB-target safety problems (empty=ok).

    Accepts an SSH-tunnel loopback port (Topology A) or a TLS Supabase URL
    (Topology B). Always refuses the localdev ``localhost:5434`` database and
    any plaintext remote connection.
    """
    database_url = _get(config, "DATABASE_URL")
    if not database_url:
        return ["DATABASE_URL is required"]

    try:
        parts = urlsplit(database_url)
        port = parts.port  # may raise ValueError on a malformed port
    except ValueError:
        return ["DATABASE_URL has an invalid port"]
    host = (parts.hostname or "").lower()
    query = parse_qs(parts.query)
    sslmode = (query.get("sslmode", [""])[0] or "").lower()

    if not host:
        return [
            "DATABASE_URL must specify a host — refusing a socket/host-less connection"
        ]

    if host in _LOOPBACK_HOSTS:
        if port == LOCALDEV_DB_PORT:
            return [
                f"DATABASE_URL points at the localdev database (localhost:{LOCALDEV_DB_PORT}); "
                "Track C must target PRODUCTION via the SSH tunnel, never localdev"
            ]
        if port is None:
            return [
                "loopback DATABASE_URL must include an explicit port (the SSH tunnel local port)"
            ]
        expected = _expected_tunnel_local_port(config)
        if port != expected:
            return [
                f"loopback DATABASE_URL port {port} must equal the SSH tunnel local port "
                f"{expected} (EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT) — refusing an unexpected local DB"
            ]
        # Loopback on the configured tunnel port == the SSH tunnel to Lightsail Postgres.
        return []

    # Non-loopback host == direct remote DB (Topology B / Supabase) — require TLS.
    if sslmode not in _TLS_SSLMODES:
        return [
            "direct remote DATABASE_URL must use sslmode=require (or stricter) — "
            "refusing to send production credentials in plaintext"
        ]
    return []


def build_ssh_tunnel_command(config: Mapping[str, str]) -> list[str]:
    """Return the ``ssh -N -L`` argv that forwards prod Postgres to this Mac.

    Reads ``EGP_REMOTECRAWL_SSH_HOST`` plus optional local/remote tunnel ports
    (default 15432). The forward stays bound to loopback on both ends.
    """
    ssh_host = _get(config, "EGP_REMOTECRAWL_SSH_HOST")
    if not ssh_host:
        raise RemoteCrawlGuardError(
            "EGP_REMOTECRAWL_SSH_HOST is required to build the tunnel command"
        )
    local_port = _coerce_port(
        _get(config, "EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT")
        or str(DEFAULT_TUNNEL_LOCAL_PORT)
    )
    remote_port = _coerce_port(
        _get(config, "EGP_REMOTECRAWL_TUNNEL_REMOTE_PORT")
        or str(DEFAULT_TUNNEL_LOCAL_PORT)
    )
    if local_port is None or remote_port is None:
        raise RemoteCrawlGuardError(
            "EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT / _REMOTE_PORT must be integers in 1..65535"
        )
    return [
        "ssh",
        "-N",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
        "-L",
        f"{local_port}:127.0.0.1:{remote_port}",
        ssh_host,
    ]


def require_safe_remote_crawl(config: Mapping[str, str]) -> None:
    """Raise ``RemoteCrawlGuardError`` if the environment is unsafe to run."""
    problems = validate_remote_crawl_env(config) + validate_database_topology(config)
    if problems:
        raise RemoteCrawlGuardError(
            "refusing to start remote crawler — "
            + str(len(problems))
            + " problem(s):\n  - "
            + "\n  - ".join(problems)
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guard the Track C remote crawler.")
    parser.add_argument(
        "command",
        choices=("check", "tunnel-cmd", "tunnel-exec", "print-env"),
        nargs="?",
        default="check",
        help=(
            "check: validate env (default). tunnel-cmd: print the ssh tunnel command. "
            "tunnel-exec: validate then exec the ssh tunnel. print-env: validate then "
            "emit NUL-delimited KEY=VALUE for safe export."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Strict dotenv file to load (no shell expansion). Defaults to the process env.",
    )
    return parser


def _resolve_config(
    args: argparse.Namespace, env: Mapping[str, str] | None
) -> dict[str, str]:
    if env is not None:
        return dict(env)
    if args.env_file:
        return parse_env_file(args.env_file)
    return dict(os.environ)


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = _resolve_config(args, env)

    if args.command == "tunnel-cmd":
        try:
            command = build_ssh_tunnel_command(config)
        except RemoteCrawlGuardError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(shlex.join(command))
        return 0

    # check / tunnel-exec / print-env all require a safe environment first.
    try:
        require_safe_remote_crawl(config)
    except RemoteCrawlGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.command == "print-env":
        # NUL-delimited KEY=VALUE so the wrapper can export without shell eval.
        sys.stdout.write("".join(f"{key}={value}\0" for key, value in config.items()))
        return 0

    if args.command == "tunnel-exec":
        command = build_ssh_tunnel_command(config)
        merged_env = {**os.environ, **config}
        os.execvpe(command[0], command, merged_env)  # replaces this process
        return 0  # unreachable

    print("remote-crawl guard: OK (environment is safe to crawl PRODUCTION)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
