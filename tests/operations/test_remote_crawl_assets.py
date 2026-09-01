"""Validate the Track C remote-crawler ops assets (scripts, plists, units).

These are static deploy artifacts, so the contract is asserted structurally:
shell scripts parse, the tunnel overlay is loopback-only, launchd agents keep
alive and invoke the guarded runner, and the systemd timer drives the
enqueue-only producer.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _stage_launchd_harness(
    tmp_path: Path,
) -> tuple[Path, dict[str, str], Path, Path, Path]:
    root = tmp_path / "repo"
    scripts_dir = root / "scripts"
    template_dir = root / "deploy" / "launchd"
    python_dir = root / ".venv" / "bin"
    fake_bin = tmp_path / "fake-bin"
    home = tmp_path / "home"
    state_dir = tmp_path / "launchctl-state"
    launchctl_log = tmp_path / "launchctl.log"
    runner_log = tmp_path / "runner.log"
    for directory in (scripts_dir, template_dir, python_dir, fake_bin, home, state_dir):
        directory.mkdir(parents=True, exist_ok=True)

    install_script = scripts_dir / "install_launchd.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "install_launchd.sh", install_script)
    install_script.chmod(0o755)
    for label in ("com.egp.pg-tunnel", "com.egp.remote-crawl", "com.egp.pg-warm"):
        (template_dir / f"{label}.plist").write_text(
            f"label={label}\nroot=__REPO_ROOT__\nhome=__HOME__\n",
            encoding="utf-8",
        )

    fake_python = python_dir / "python"
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    runner = scripts_dir / "run_remote_crawl.sh"
    runner.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$1" >> "$FAKE_RUNNER_LOG"\n'
        'if [[ "$1" == "doctor" && "${FAKE_WATCHER_DIES_DURING_DOCTOR:-}" == "1" ]]; then\n'
        '  rm -f "$FAKE_LAUNCHCTL_STATE/com.egp.remote-crawl"\n'
        "fi\n"
        '[[ "${FAKE_RUNNER_FAIL_COMMAND:-}" != "$1" ]]\n',
        encoding="utf-8",
    )
    runner.chmod(0o755)

    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"rev-parse --verify HEAD"* ]]; then\n'
        '  printf "%040d\\n" 1\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(
        "#!/usr/bin/env bash\n"
        'command="$1"\n'
        'target="${2:-}"\n'
        'label="${target##*/}"\n'
        'printf "%s:%s\\n" "$command" "$label" >> "$FAKE_LAUNCHCTL_LOG"\n'
        'if [[ "$command" == "bootstrap" ]]; then\n'
        '  label="$(basename "${3%.plist}")"\n'
        '  if [[ "${FAKE_LAUNCHCTL_FAIL_LABEL:-}" == "$label" ]]; then exit 70; fi\n'
        '  : > "$FAKE_LAUNCHCTL_STATE/$label"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$command" == "bootout" ]]; then\n'
        '  rm -f "$FAKE_LAUNCHCTL_STATE/$label"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$command" == "print" && -f "$FAKE_LAUNCHCTL_STATE/$label" ]]; then\n'
        "  printf 'state = running\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_launchctl.chmod(0o755)

    evidence = tmp_path / "acceptance.json"
    evidence.write_text("{}\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "FAKE_LAUNCHCTL_STATE": str(state_dir),
            "FAKE_LAUNCHCTL_LOG": str(launchctl_log),
            "FAKE_RUNNER_LOG": str(runner_log),
        }
    )
    return install_script, environment, evidence, state_dir, launchctl_log


def _bash_syntax_ok(path: Path) -> None:
    completed = subprocess.run(
        ["bash", "-n", str(path)], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr


def test_run_remote_crawl_sh_parses() -> None:
    _bash_syntax_ok(REPO_ROOT / "scripts" / "run_remote_crawl.sh")


def test_run_remote_crawl_disables_bytecode_writes_before_python_commands() -> None:
    text = (REPO_ROOT / "scripts" / "run_remote_crawl.sh").read_text(encoding="utf-8")

    export = "export PYTHONDONTWRITEBYTECODE=1"
    assert export in text
    assert text.index(export) < text.index("guard_check()")


def test_run_remote_crawl_reasserts_bytecode_guard_after_validated_env(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    scripts_dir = root / "scripts"
    python_dir = root / ".venv" / "bin"
    fake_bin = tmp_path / "fake-bin"
    for directory in (scripts_dir, python_dir, fake_bin):
        directory.mkdir(parents=True, exist_ok=True)

    runner = scripts_dir / "run_remote_crawl.sh"
    shutil.copy2(REPO_ROOT / "scripts" / "run_remote_crawl.sh", runner)
    runner.chmod(0o755)
    (scripts_dir / "remote_crawl_guard.py").write_text(
        "# fake guard\n", encoding="utf-8"
    )
    env_file = root / ".env.remotecrawl"
    env_file.write_text("placeholder=true\n", encoding="utf-8")
    observed_env = tmp_path / "bytecode-env.txt"

    fake_python = python_dir / "python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"print-env"* ]]; then\n'
        "  printf 'PYTHONDONTWRITEBYTECODE=\\0'\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-m" ]]; then\n'
        '  printf "%s" "${PYTHONDONTWRITEBYTECODE-unset}" > "$OBSERVED_ENV_FILE"\n'
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"rev-parse --verify HEAD"* ]]; then\n'
        "  printf '1111111111111111111111111111111111111111\\n'\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "EGP_REMOTECRAWL_ENV_FILE": str(env_file),
            "OBSERVED_ENV_FILE": str(observed_env),
            "PATH": f"{fake_bin}:{environment['PATH']}",
        }
    )
    completed = subprocess.run(
        [str(runner), "doctor"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert observed_env.read_text(encoding="utf-8") == "1"


def test_run_remote_crawl_sh_guards_before_dispatching() -> None:
    text = (REPO_ROOT / "scripts" / "run_remote_crawl.sh").read_text(encoding="utf-8")
    assert "remote_crawl_guard.py" in text
    assert "egp_api.executors.discovery_dispatch" in text
    # The crawl/watch paths must validate first, then derive immutable release
    # provenance from a clean tracked checkout before exec'ing the module.
    run_module = text.split("run_module()", maxsplit=1)[1].split("\n}\n", maxsplit=1)[0]
    ordered_steps = (
        "guard_check",
        "load_validated_env",
        'git -C "$ROOT" rev-parse --verify HEAD',
        'git -C "$ROOT" diff --quiet --',
        'git -C "$ROOT" diff --cached --quiet --',
        'git -C "$ROOT" ls-files --others --',
        "cd /",
        'export EGP_RELEASE_SHA="$release_sha"',
        'exec "$PY" -m "$@"',
    )
    positions = [run_module.index(step) for step in ordered_steps]
    assert positions == sorted(positions)
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


def test_run_remote_crawl_exposes_bounded_supervision_with_fixed_commands() -> None:
    text = (REPO_ROOT / "scripts" / "run_remote_crawl.sh").read_text(encoding="utf-8")

    assert "supervise)" in text
    assert "scripts/supervise_remote_crawl.py" in text
    assert "--duration-seconds" in text
    assert "--runtime-evidence" in text
    assert "--command-json" in text
    assert "--doctor-command-json" in text
    assert '"$ROOT/scripts/run_remote_crawl.sh" "watch"' in text
    assert '"$ROOT/scripts/run_remote_crawl.sh" "doctor"' in text
    assert "supervise <seconds> --evidence <runtime-evidence.json>" in text


def test_run_remote_crawl_exposes_exact_private_canary_target() -> None:
    text = (REPO_ROOT / "scripts" / "run_remote_crawl.sh").read_text(encoding="utf-8")

    assert "crawl-canary)" in text
    assert (
        "run_module egp_api.executors.discovery_dispatch --once --limit 1 "
        '--target-file "$target_file"'
    ) in text
    assert "crawl-canary <private-target.json>" in text


def test_run_remote_crawl_exposes_read_only_observation_canary() -> None:
    text = (REPO_ROOT / "scripts" / "run_remote_crawl.sh").read_text(encoding="utf-8")

    assert "observe-canary)" in text
    assert "--observation-canary" in text
    assert "--target-file" in text
    assert "--max-pages 15" in text
    assert "--receipt" in text
    observation = text.split("run_observation_canary()", maxsplit=1)[1].split(
        "\n}", maxsplit=1
    )[0]
    assert observation.index("guard_check") < observation.index("load_validated_env")
    assert observation.index("load_validated_env") < observation.index("EGP_RELEASE_SHA")
    assert "--attach" not in observation
    assert "DATABASE_URL" in observation
    assert "EGP_ARTIFACT_STORE" in observation
    assert "SUPABASE_URL" in observation
    assert "SUPABASE_SERVICE_ROLE_KEY" in observation
    assert "SUPABASE_STORAGE_BUCKET" in observation
    assert observation.index("DATABASE_URL") < observation.index(
        '"$ROOT/scripts/diagnose_search_rows.py"'
    )


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


def test_install_requires_managed_tunnel_running_before_database_and_watcher() -> None:
    text = (REPO_ROOT / "scripts" / "install_launchd.sh").read_text(encoding="utf-8")
    install_body = text.split("cmd_install()", maxsplit=1)[1].split(
        "\n}\n", maxsplit=1
    )[0]

    assert "wait_for_launchd_running()" in text
    assert "assert_launchd_running()" in text
    tunnel_bootstrap = 'launchctl bootstrap "gui/$uid" "$AGENT_DIR/$label.plist"'
    managed_tunnel_ready = 'wait_for_launchd_running "$label"'
    database_ready = '"$ROOT/scripts/run_remote_crawl.sh" wait-database'
    managed_tunnel_recheck = 'assert_launchd_running "$label"'
    watcher_guard = 'if [[ "$label" == "com.egp.pg-tunnel" ]]; then'
    assert watcher_guard in install_body
    assert install_body.index(tunnel_bootstrap) < install_body.index(
        managed_tunnel_ready
    )
    assert install_body.index(managed_tunnel_ready) < install_body.index(database_ready)
    assert install_body.index(database_ready) < install_body.index(
        managed_tunnel_recheck
    )


def test_install_warm_opt_in_hint_preserves_required_acceptance_evidence() -> None:
    text = (REPO_ROOT / "scripts" / "install_launchd.sh").read_text(encoding="utf-8")

    assert "install --acceptance-evidence '$acceptance_evidence' --with-warm" in text


def test_launchd_install_requires_accepted_exact_sha_bundle_before_mutation() -> None:
    text = (REPO_ROOT / "scripts" / "install_launchd.sh").read_text(encoding="utf-8")
    install_body = text.split("cmd_install()", maxsplit=1)[1].split(
        "\n}\n", maxsplit=1
    )[0]

    assert "--acceptance-evidence" in install_body
    assert "validate_acceptance_evidence" in install_body
    assert "track_bc_verify.py" in text
    assert " bundle " in text
    assert "--expected-release-sha" in text
    assert "git -C" in text and "rev-parse --verify HEAD" in text
    assert install_body.index("validate_acceptance_evidence") < install_body.index(
        'mkdir -p "$AGENT_DIR"'
    )
    assert install_body.index("validate_acceptance_evidence") < install_body.index(
        'render "$label"'
    )


def test_launchd_status_and_uninstall_remain_recovery_safe_without_bundle() -> None:
    text = (REPO_ROOT / "scripts" / "install_launchd.sh").read_text(encoding="utf-8")
    uninstall_body = text.split("cmd_uninstall()", maxsplit=1)[1].split(
        "\n}\n", maxsplit=1
    )[0]
    status_body = text.split("cmd_status()", maxsplit=1)[1].split("\n}\n", maxsplit=1)[
        0
    ]

    assert "validate_acceptance_evidence" not in uninstall_body
    assert "validate_acceptance_evidence" not in status_body


def test_launchd_install_proves_watcher_and_doctor_then_uninstalls_cleanly(
    tmp_path: Path,
) -> None:
    install_script, environment, evidence, state_dir, launchctl_log = (
        _stage_launchd_harness(tmp_path)
    )

    installed = subprocess.run(
        [str(install_script), "install", "--acceptance-evidence", str(evidence)],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert installed.returncode == 0, installed.stderr
    assert (tmp_path / "runner.log").read_text(encoding="utf-8").splitlines() == [
        "wait-database",
        "doctor",
    ]
    assert {path.name for path in state_dir.iterdir()} == {
        "com.egp.pg-tunnel",
        "com.egp.remote-crawl",
    }

    launchctl_log.write_text("", encoding="utf-8")
    removed = subprocess.run(
        [str(install_script), "uninstall"],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert removed.returncode == 0, removed.stderr
    assert not list(state_dir.iterdir())
    assert [
        line
        for line in launchctl_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("bootout:")
    ] == [
        "bootout:com.egp.pg-warm",
        "bootout:com.egp.remote-crawl",
        "bootout:com.egp.pg-tunnel",
    ]
    assert not list(
        (Path(environment["HOME"]) / "Library" / "LaunchAgents").glob("com.egp.*.plist")
    )


def test_launchd_partial_install_failure_rolls_back_loaded_labels_and_plists(
    tmp_path: Path,
) -> None:
    install_script, environment, evidence, state_dir, launchctl_log = (
        _stage_launchd_harness(tmp_path)
    )
    environment["FAKE_LAUNCHCTL_FAIL_LABEL"] = "com.egp.remote-crawl"

    result = subprocess.run(
        [str(install_script), "install", "--acceptance-evidence", str(evidence)],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert not list(state_dir.iterdir())
    bootouts = [
        line
        for line in launchctl_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("bootout:")
    ]
    assert bootouts[-2:] == [
        "bootout:com.egp.remote-crawl",
        "bootout:com.egp.pg-tunnel",
    ]
    assert not list(
        (Path(environment["HOME"]) / "Library" / "LaunchAgents").glob("com.egp.*.plist")
    )


def test_launchd_install_rolls_back_if_watcher_dies_during_doctor(
    tmp_path: Path,
) -> None:
    install_script, environment, evidence, state_dir, _ = _stage_launchd_harness(
        tmp_path
    )
    environment["FAKE_WATCHER_DIES_DURING_DOCTOR"] = "1"

    result = subprocess.run(
        [str(install_script), "install", "--acceptance-evidence", str(evidence)],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert "running recheck for com.egp.remote-crawl" in result.stderr
    assert not list(state_dir.iterdir())


def test_launchd_uninstall_waits_for_each_label_to_be_absent() -> None:
    text = (REPO_ROOT / "scripts" / "install_launchd.sh").read_text(encoding="utf-8")
    uninstall_body = text.split("cmd_uninstall()", maxsplit=1)[1].split(
        "\n}\n", maxsplit=1
    )[0]

    assert "wait_for_launchd_absent" in text
    assert uninstall_body.index(
        'launchctl bootout "gui/$uid/$label"'
    ) < uninstall_body.index('wait_for_launchd_absent "$label"')
    assert uninstall_body.index(
        'wait_for_launchd_absent "$label"'
    ) < uninstall_body.index('rm -f "$AGENT_DIR/$label.plist"')


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


@pytest.mark.parametrize("label", ["com.egp.pg-tunnel", "com.egp.remote-crawl"])
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
    text = (REPO_ROOT / "deploy" / "systemd" / "egp-scheduled-enqueue.timer").read_text(
        encoding="utf-8"
    )
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
    assert (
        "EGP_REMOTECRAWL_PRODUCTION_ACK=I_UNDERSTAND_THIS_WRITES_PRODUCTION" not in text
    )
    assert "EGP_REMOTECRAWL_PRODUCTION_ACK=CHANGE_ME" in text
    assert "I_UNDERSTAND_THIS_WRITES_PRODUCTION" in text  # shown in a comment


def test_remote_crawl_runbook_documents_doctor_summary_and_typed_decisions() -> None:
    text = (REPO_ROOT / "docs" / "REMOTE_LOCAL_CRAWLER.md").read_text(encoding="utf-8")

    assert "scripts/run_remote_crawl.sh doctor" in text
    assert "scripts/run_remote_crawl.sh wait-database" in text
    assert "remaining_pending_count" in text
    assert "limit_reached" in text
    assert "`agent_offline`" in text
    assert "`correlation_mismatch`" in text
    assert "semantic-failure burst" not in text
