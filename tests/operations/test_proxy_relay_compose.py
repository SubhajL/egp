"""PR 1 (proxy relay infra): verify the relay lands risk-free / default-off.

The relay must NOT start by default (profile-gated), and the discovery-executor's
proxy must default to empty (no proxy = current behavior). Activation is a later PR.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_proxy_relay_service_is_profile_gated_off_by_default() -> None:
    services = _compose()["services"]
    assert "proxy-relay" in services, "proxy-relay service must exist"
    profiles = services["proxy-relay"].get("profiles") or []
    assert "proxy" in profiles, (
        "proxy-relay must be gated behind the 'proxy' compose profile so a plain "
        "`docker compose up` never starts it (risk-free / off by default)"
    )


def test_proxy_relay_forwards_upstream_on_local_http_port() -> None:
    relay = _compose()["services"]["proxy-relay"]
    command = relay["command"]
    joined = " ".join(command) if isinstance(command, list) else str(command)
    assert "EGP_PROXY_UPSTREAM_URL" in joined, (
        "relay must forward to EGP_PROXY_UPSTREAM_URL"
    )
    assert "8118" in joined, "relay must listen on local port 8118"
    # MUST use the default-empty form (:-), never `:?` — a required-var ref would
    # make `docker compose config`/`up` fail for ALL services when it's unset.
    assert "${EGP_PROXY_UPSTREAM_URL:-}" in joined, (
        "relay upstream must use the default-empty :- form (not :?) so unset never breaks compose"
    )


def test_discovery_executor_proxy_defaults_to_empty() -> None:
    env = _compose()["services"]["discovery-executor"]["environment"]
    assert "EGP_BROWSER_PROXY_SERVER" in env, (
        "executor must pass through EGP_BROWSER_PROXY_SERVER"
    )
    assert env["EGP_BROWSER_PROXY_SERVER"] == "${EGP_BROWSER_PROXY_SERVER:-}", (
        "EGP_BROWSER_PROXY_SERVER must default to empty (no proxy = current behavior)"
    )


def test_discovery_executor_persistent_profile_defaults_off() -> None:
    env = _compose()["services"]["discovery-executor"]["environment"]
    assert env["EGP_BROWSER_PROFILE_MODE"] == "${EGP_BROWSER_PROFILE_MODE:-per_run}", (
        "profile mode must default to per_run (current behavior)"
    )
    assert env["EGP_BROWSER_PERSISTENT_PROFILE_DIR"] == "${EGP_BROWSER_PERSISTENT_PROFILE_DIR:-}", (
        "persistent profile dir must default to empty"
    )


def test_discovery_executor_timeout_passthrough_defaults() -> None:
    env = _compose()["services"]["discovery-executor"]["environment"]
    assert env["EGP_BROWSER_NAV_TIMEOUT_MS"] == "${EGP_BROWSER_NAV_TIMEOUT_MS:-60000}"
    assert env["EGP_BROWSER_CLOUDFLARE_TIMEOUT_MS"] == "${EGP_BROWSER_CLOUDFLARE_TIMEOUT_MS:-120000}"
    assert (
        env["EGP_BROWSER_CLOUDFLARE_RELOAD_RETRIES"]
        == "${EGP_BROWSER_CLOUDFLARE_RELOAD_RETRIES:-1}"
    )
    assert (
        env["EGP_BROWSER_PROJECT_DETAIL_TIMEOUT_S"]
        == "${EGP_BROWSER_PROJECT_DETAIL_TIMEOUT_S:-240}"
    )


def test_persistent_profile_volume_is_mounted_and_declared() -> None:
    compose = _compose()
    mounts = compose["services"]["discovery-executor"]["volumes"]
    assert any("egp_browser_profile:" in m for m in mounts), (
        "discovery-executor must mount the egp_browser_profile volume so a warmed "
        "profile survives container recreation"
    )
    assert "egp_browser_profile" in compose["volumes"], "volume must be declared at top level"
