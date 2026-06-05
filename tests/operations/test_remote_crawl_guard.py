"""TDD coverage for ``scripts/remote_crawl_guard.py``.

The remote-crawl guard is the safety gate for Track C (local Mac crawler →
PRODUCTION control-plane). It must fail CLOSED: refuse to run unless the
operator has acknowledged production, the worker writes artifacts to Supabase
and events over HTTPS, a real warmed single-flight Chrome profile is configured,
and the database target is a legitimate prod connection (SSH-tunnel loopback or
TLS Supabase) — never the localdev ``localhost:5434`` DB.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import remote_crawl_guard  # noqa: E402
from remote_crawl_guard import (  # noqa: E402
    RemoteCrawlGuardError,
    build_ssh_tunnel_command,
    main,
    parse_env_file,
    require_safe_remote_crawl,
    validate_database_topology,
    validate_remote_crawl_env,
)

ACK = "I_UNDERSTAND_THIS_WRITES_PRODUCTION"


def _valid_config(tmp_path: Path) -> dict[str, str]:
    return {
        "EGP_REMOTECRAWL_PRODUCTION_ACK": ACK,
        "DATABASE_URL": "postgresql://egp:pw@127.0.0.1:15432/egp",
        "EGP_INTERNAL_API_BASE_URL": "https://api.example.com",
        "EGP_INTERNAL_WORKER_TOKEN": "tok",
        "EGP_ARTIFACT_STORE": "supabase",
        "SUPABASE_URL": "https://ref.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
        "SUPABASE_STORAGE_BUCKET": "egp-documents",
        "EGP_BROWSER_CHROME_PATH": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "EGP_BROWSER_PROFILE_MODE": "persistent",
        "EGP_BROWSER_PERSISTENT_PROFILE_DIR": str(tmp_path / "prod-profile"),
        "EGP_DISCOVERY_WORKER_COUNT": "1",
        "EGP_REMOTECRAWL_SSH_HOST": "ubuntu@api.example.com",
        "EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT": "15432",
        "EGP_REMOTECRAWL_TUNNEL_REMOTE_PORT": "15432",
    }


# --- parse_env_file -------------------------------------------------------


def test_parse_env_file_strips_quotes_and_ignores_comments(tmp_path: Path) -> None:
    path = tmp_path / ".env.remotecrawl"
    path.write_text(
        "# a comment\nFOO=bar\nQUOTED=\"with space\"\n\nEXPORTED=export-handled=ok\n",
        encoding="utf-8",
    )
    parsed = parse_env_file(path)
    assert parsed["FOO"] == "bar"
    assert parsed["QUOTED"] == "with space"
    assert "# a comment" not in parsed


def test_parse_env_file_does_not_expand_shell(tmp_path: Path) -> None:
    path = tmp_path / ".env.remotecrawl"
    path.write_text("VAL=${HOME}/x\n", encoding="utf-8")
    assert parse_env_file(path)["VAL"] == "${HOME}/x"


# --- validate_remote_crawl_env -------------------------------------------


def test_valid_config_has_no_env_problems(tmp_path: Path) -> None:
    assert validate_remote_crawl_env(_valid_config(tmp_path)) == []


def test_missing_production_ack_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.pop("EGP_REMOTECRAWL_PRODUCTION_ACK")
    problems = validate_remote_crawl_env(config)
    assert any("ack" in p.lower() for p in problems)


def test_non_https_internal_api_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["EGP_INTERNAL_API_BASE_URL"] = "http://api.example.com"
    assert any("https" in p.lower() for p in validate_remote_crawl_env(config))


def test_non_supabase_artifact_store_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["EGP_ARTIFACT_STORE"] = "local"
    assert any("supabase" in p.lower() for p in validate_remote_crawl_env(config))


def test_missing_supabase_credentials_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.pop("SUPABASE_SERVICE_ROLE_KEY")
    assert any("supabase" in p.lower() for p in validate_remote_crawl_env(config))


def test_non_persistent_profile_mode_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["EGP_BROWSER_PROFILE_MODE"] = "per_run"
    assert any("persistent" in p.lower() for p in validate_remote_crawl_env(config))


def test_multi_worker_count_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["EGP_DISCOVERY_WORKER_COUNT"] = "2"
    assert any("worker" in p.lower() for p in validate_remote_crawl_env(config))


def test_profile_dir_in_synced_folder_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["EGP_BROWSER_PERSISTENT_PROFILE_DIR"] = "/Users/me/OneDrive/egp/profile"
    assert any("synced" in p.lower() or "onedrive" in p.lower() for p in validate_remote_crawl_env(config))


def test_missing_chrome_path_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.pop("EGP_BROWSER_CHROME_PATH")
    assert any("chrome" in p.lower() for p in validate_remote_crawl_env(config))


def test_missing_worker_token_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.pop("EGP_INTERNAL_WORKER_TOKEN")
    assert any("worker_token" in p.lower() or "token" in p.lower() for p in validate_remote_crawl_env(config))


def test_changeme_placeholder_value_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["SUPABASE_SERVICE_ROLE_KEY"] = "CHANGE_ME_SUPABASE_SERVICE_ROLE_KEY"
    assert any("change_me" in p.lower() for p in validate_remote_crawl_env(config))


def test_invalid_tunnel_port_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT"] = "not-a-port"
    assert any("tunnel_local_port" in p.lower() for p in validate_remote_crawl_env(config))


# --- validate_database_topology ------------------------------------------


def test_localdev_database_is_always_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql://egp:egp_dev@localhost:5434/egp"
    assert any("5434" in p or "localdev" in p.lower() for p in validate_database_topology(config))


def test_ssh_tunnel_loopback_port_is_allowed(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql://egp:pw@127.0.0.1:15432/egp"
    assert validate_database_topology(config) == []


def test_direct_remote_db_requires_sslmode(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql://u:p@db.ref.supabase.co:5432/postgres"
    assert any("ssl" in p.lower() for p in validate_database_topology(config))


def test_supabase_tls_direct_db_is_allowed(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = (
        "postgresql://u:p@db.ref.supabase.co:5432/postgres?sslmode=require"
    )
    assert validate_database_topology(config) == []


def test_missing_database_url_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.pop("DATABASE_URL")
    assert validate_database_topology(config) != []


def test_loopback_port_must_match_configured_tunnel_port(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql://egp:pw@127.0.0.1:5999/egp"  # != 15432
    assert any("tunnel" in p.lower() for p in validate_database_topology(config))


def test_loopback_without_explicit_port_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql://egp:pw@127.0.0.1/egp"
    assert any("explicit port" in p.lower() for p in validate_database_topology(config))


def test_hostless_database_url_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql:///egp"
    assert any("host" in p.lower() for p in validate_database_topology(config))


def test_malformed_db_port_is_refused(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql://egp:pw@127.0.0.1:notaport/egp"
    assert any("port" in p.lower() for p in validate_database_topology(config))


def test_build_ssh_tunnel_command_rejects_bad_port(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["EGP_REMOTECRAWL_TUNNEL_LOCAL_PORT"] = "70000"  # out of range
    with pytest.raises(RemoteCrawlGuardError):
        build_ssh_tunnel_command(config)


# --- build_ssh_tunnel_command --------------------------------------------


def test_build_ssh_tunnel_command_is_loopback_only(tmp_path: Path) -> None:
    argv = build_ssh_tunnel_command(_valid_config(tmp_path))
    joined = " ".join(argv)
    assert "-N" in argv
    assert "ubuntu@api.example.com" in argv
    assert "15432:127.0.0.1:15432" in joined
    assert "ExitOnForwardFailure=yes" in joined


# --- require_safe_remote_crawl + main ------------------------------------


def test_require_safe_remote_crawl_passes_for_valid(tmp_path: Path) -> None:
    require_safe_remote_crawl(_valid_config(tmp_path))  # must not raise


def test_require_safe_remote_crawl_raises_for_localdev(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["DATABASE_URL"] = "postgresql://egp:egp_dev@localhost:5434/egp"
    with pytest.raises(RemoteCrawlGuardError):
        require_safe_remote_crawl(config)


def test_main_check_returns_zero_for_valid(tmp_path: Path) -> None:
    assert main(["check"], env=_valid_config(tmp_path)) == 0


def test_main_check_returns_nonzero_for_invalid(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.pop("EGP_REMOTECRAWL_PRODUCTION_ACK")
    assert main(["check"], env=config) != 0


def test_main_tunnel_cmd_prints_ssh(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tunnel-cmd"], env=_valid_config(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "ssh" in out
    assert "15432:127.0.0.1:15432" in out


def test_main_print_env_emits_nul_delimited_after_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["print-env"], env=_valid_config(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "\0" in out, "print-env must NUL-delimit so the wrapper exports without shell eval"
    pairs = dict(item.split("=", 1) for item in out.split("\0") if item)
    assert pairs["EGP_ARTIFACT_STORE"] == "supabase"
    # A Chrome path WITH SPACES round-trips intact (the bash-source bug class).
    assert " " in pairs["EGP_BROWSER_CHROME_PATH"]


def test_main_print_env_refuses_invalid(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config.pop("EGP_REMOTECRAWL_PRODUCTION_ACK")
    assert main(["print-env"], env=config) != 0


def test_main_tunnel_exec_validates_then_execs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _fake_execvpe(file, args, env):
        captured["file"] = file
        captured["args"] = list(args)
        captured["env"] = dict(env)

    monkeypatch.setattr(remote_crawl_guard.os, "execvpe", _fake_execvpe)
    assert main(["tunnel-exec"], env=_valid_config(tmp_path)) == 0
    assert captured["file"] == "ssh"
    assert "15432:127.0.0.1:15432" in " ".join(captured["args"])
    # exec receives the parsed config as part of the environment.
    assert captured["env"]["DATABASE_URL"].endswith(":15432/egp")


def test_main_tunnel_exec_refuses_invalid_without_execing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = {"execed": False}
    monkeypatch.setattr(
        remote_crawl_guard.os,
        "execvpe",
        lambda *a, **k: called.__setitem__("execed", True),
    )
    config = _valid_config(tmp_path)
    config["EGP_ARTIFACT_STORE"] = "local"
    assert main(["tunnel-exec"], env=config) != 0
    assert called["execed"] is False


def test_main_check_loads_env_file(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.remotecrawl"
    lines = [f"{key}={value}" for key, value in _valid_config(tmp_path).items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["check", "--env-file", str(env_path)]) == 0
