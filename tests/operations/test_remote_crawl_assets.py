"""Validate the Track C remote-crawler ops assets (scripts, plists, units).

These are static deploy artifacts, so the contract is asserted structurally:
shell scripts parse, the tunnel overlay is loopback-only, launchd agents keep
alive and invoke the guarded runner, and the systemd timer drives the
enqueue-only producer.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _bash_syntax_ok(path: Path) -> None:
    completed = subprocess.run(
        ["bash", "-n", str(path)], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


def test_run_remote_crawl_sh_parses() -> None:
    _bash_syntax_ok(REPO_ROOT / "scripts" / "run_remote_crawl.sh")


def test_run_remote_crawl_sh_guards_before_dispatching() -> None:
    text = (REPO_ROOT / "scripts" / "run_remote_crawl.sh").read_text(encoding="utf-8")
    assert "remote_crawl_guard.py" in text
    assert "egp_api.executors.discovery_dispatch" in text
    # The crawl/watch paths must validate first (fail-closed): run_module calls
    # guard_check before exec'ing the module.
    assert "guard_check\n  load_validated_env\n  exec" in text
    assert "wait-database)" in text
    assert "egp_api.executors.discovery_doctor" in text


def test_run_remote_crawl_sh_never_sources_env_file() -> None:
    """The env file must be parsed by the Python guard, never bash-sourced
    (shell-eval'ing it breaks on values with spaces and runs arbitrary code).
    """
    text = (REPO_ROOT / "scripts" / "run_remote_crawl.sh").read_text(encoding="utf-8")
    assert 'source "$ENV_FILE"' not in text
    assert "print-env" in text  # safe NUL-delimited export instead
    assert "tunnel-exec" in text  # ssh argv exec'd directly, no word-split


def test_install_launchd_sh_parses_and_targets_both_agents() -> None:
    path = REPO_ROOT / "scripts" / "install_launchd.sh"
    _bash_syntax_ok(path)
    text = path.read_text(encoding="utf-8")
    assert "com.egp.pg-tunnel" in text
    assert "com.egp.remote-crawl" in text
    assert "launchctl" in text


def test_install_launchd_sh_keeps_warm_profile_timer_opt_in() -> None:
    text = (REPO_ROOT / "scripts" / "install_launchd.sh").read_text(encoding="utf-8")
    assert "DEFAULT_LABELS=(com.egp.pg-tunnel com.egp.remote-crawl)" in text
    assert "OPTIONAL_WARM_LABEL=com.egp.pg-warm" in text
    assert "--with-warm" in text
    assert "LABELS=(com.egp.pg-tunnel com.egp.remote-crawl com.egp.pg-warm)" not in text


def test_install_orders_tunnel_readiness_before_watcher() -> None:
    text = (REPO_ROOT / "scripts" / "install_launchd.sh").read_text(encoding="utf-8")
    wait_before_bootstrap = (
        'if [[ "$label" == "com.egp.remote-crawl" ]]; then\n'
        '      "$ROOT/scripts/run_remote_crawl.sh" wait-database\n'
        "    fi\n"
        '    launchctl bootstrap "gui/$uid" "$AGENT_DIR/$label.plist"'
    )

    assert wait_before_bootstrap in text


def test_pg_tunnel_overlay_binds_loopback_only() -> None:
    overlay = yaml.safe_load(
        (REPO_ROOT / "docker-compose.pg-tunnel.yml").read_text(encoding="utf-8")
    )
    ports = overlay["services"]["postgres"]["ports"]
    assert ports, "overlay must publish a port"
    for mapping in ports:
        assert str(mapping).startswith("127.0.0.1:"), (
            f"prod Postgres must bind loopback only, got {mapping!r}"
        )
        assert "0.0.0.0" not in str(mapping)
        assert str(mapping).endswith(":5432")


@pytest.mark.parametrize(
    "label", ["com.egp.pg-tunnel", "com.egp.remote-crawl"]
)
def test_launchd_plist_parses_keepalive_and_runs_guarded_runner(label: str) -> None:
    raw = (REPO_ROOT / "deploy" / "launchd" / f"{label}.plist").read_bytes()
    parsed = plistlib.loads(raw)
    assert parsed["Label"] == label
    assert parsed["KeepAlive"] is True
    program = " ".join(parsed["ProgramArguments"])
    assert "run_remote_crawl.sh" in program


def test_systemd_enqueue_service_is_oneshot_and_browserless() -> None:
    text = (
        REPO_ROOT / "deploy" / "systemd" / "egp-scheduled-enqueue.service"
    ).read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    assert "egp_api.executors.scheduled_discovery_enqueue" in text


def test_systemd_enqueue_timer_is_periodic() -> None:
    text = (
        REPO_ROOT / "deploy" / "systemd" / "egp-scheduled-enqueue.timer"
    ).read_text(encoding="utf-8")
    assert "[Timer]" in text
    assert "OnUnitActiveSec=" in text


def test_env_example_is_production_safe_template() -> None:
    text = (REPO_ROOT / ".env.remotecrawl.example").read_text(encoding="utf-8")
    # Artifacts go to Cloudflare R2 via the s3 backend (not Supabase).
    assert "EGP_ARTIFACT_STORE=s3" in text
    assert "r2.cloudflarestorage.com" in text
    assert "AWS_ENDPOINT_URL_S3" in text
    assert "CHANGE_ME" in text  # only placeholders, no real secrets
    assert "EGP_BROWSER_WARMUP_STALE_AFTER_SECONDS=1800" in text
    assert "EGP_BROWSER_PREDISPATCH_WARM_SECONDS=0" in text
    # The template must NOT pre-acknowledge production: copying it alone must not
    # satisfy the guard. The exact ack value appears only as comment guidance.
    assert "EGP_REMOTECRAWL_PRODUCTION_ACK=I_UNDERSTAND_THIS_WRITES_PRODUCTION" not in text
    assert "EGP_REMOTECRAWL_PRODUCTION_ACK=CHANGE_ME" in text
    assert "I_UNDERSTAND_THIS_WRITES_PRODUCTION" in text  # shown in a comment


def test_remote_crawl_runbook_documents_doctor_summary_and_typed_decisions() -> None:
    text = (REPO_ROOT / "docs" / "REMOTE_LOCAL_CRAWLER.md").read_text(
        encoding="utf-8"
    )

    assert "scripts/run_remote_crawl.sh doctor" in text
    assert "scripts/run_remote_crawl.sh wait-database" in text
    assert "remaining_pending_count" in text
    assert "limit_reached" in text
    assert "`agent_offline`" in text
    assert "`correlation_mismatch`" in text
    assert "semantic-failure burst" not in text
