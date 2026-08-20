from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_SHA = "f1e8182cdabb07b8c890b5a2ad2d8f1672e0125a"
RELEASE_COMPOSE_PATH = REPO_ROOT / "docker-compose.release.yml"
API_IMAGE_SERVICES = (
    "migrate",
    "api",
    "webhook-executor",
    "crawler-agent-inbox-executor",
)
WORKER_IMAGE_SERVICES = ("discovery-executor",)


def _compose(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "dockerfile_name", ["apps/api/Dockerfile", "apps/worker/Dockerfile"]
)
def test_python_runtime_images_embed_release_revision(dockerfile_name: str) -> None:
    dockerfile = (REPO_ROOT / dockerfile_name).read_text(encoding="utf-8")

    runtime = dockerfile.split(" AS runtime", maxsplit=1)[1]
    assert "ARG EGP_RELEASE_SHA" in runtime
    assert "ARG EGP_RELEASE_SHA=unknown" not in runtime
    assert (
        "release revision must be localdev or an exact 40-character lowercase Git SHA"
        in runtime
    )
    assert 'org.opencontainers.image.revision="${EGP_RELEASE_SHA}"' in runtime
    assert 'EGP_RELEASE_SHA="${EGP_RELEASE_SHA}"' in runtime


def test_compose_builds_every_python_image_with_release_sha() -> None:
    production = _compose(REPO_ROOT / "docker-compose.yml")["services"]
    release = _compose(RELEASE_COMPOSE_PATH)["services"]
    localdev = _compose(REPO_ROOT / "docker-compose-localdev.yml")["services"]

    for service_name in (*API_IMAGE_SERVICES, *WORKER_IMAGE_SERVICES):
        production_args = production[service_name]["build"].get("args", {})
        release_arg = release[service_name]["build"]["args"]["EGP_RELEASE_SHA"]
        localdev_arg = localdev[service_name]["build"]["args"]["EGP_RELEASE_SHA"]
        assert "EGP_RELEASE_SHA" not in production_args
        assert release_arg.startswith("${EGP_RELEASE_SHA:?")
        assert "scripts/release_compose.sh" in release_arg
        assert localdev_arg == "localdev"
        expected_dockerfile = (
            "apps/worker/Dockerfile"
            if service_name in WORKER_IMAGE_SERVICES
            else "apps/api/Dockerfile"
        )
        assert release[service_name]["build"]["context"] == "."
        assert release[service_name]["build"]["dockerfile"] == expected_dockerfile
        assert release[service_name]["environment"]["EGP_RELEASE_SHA"] == release_arg
        assert "EGP_RELEASE_SHA" not in production[service_name].get("environment", {})
        assert "EGP_RELEASE_SHA" not in localdev[service_name].get("environment", {})


def test_ci_and_publish_workflows_stamp_exact_commit_sha() -> None:
    ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    steps = {step.get("name"): step for step in ci["jobs"]["build"]["steps"]}
    for step_name in ("Validate API Docker image", "Validate Worker Docker image"):
        assert "--build-arg EGP_RELEASE_SHA=${GITHUB_SHA}" in steps[step_name]["run"]
    assert steps["Smoke runtime images"]["env"]["EGP_EXPECTED_RELEASE_SHA"] == (
        "${{ github.sha }}"
    )

    publish = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/publish-images.yml").read_text()
    )
    publish_steps = {
        step.get("name"): step for step in publish["jobs"]["publish"]["steps"]
    }
    for step_name in ("Build and push API image", "Build and push Worker image"):
        assert (
            "EGP_RELEASE_SHA=${{ github.sha }}"
            in publish_steps[step_name]["with"]["build-args"]
        )


def test_runtime_image_smoke_rejects_release_mismatch() -> None:
    script = (REPO_ROOT / "scripts/smoke_runtime_images.sh").read_text(encoding="utf-8")

    assert "EGP_EXPECTED_RELEASE_SHA" in script
    assert "org.opencontainers.image.revision" in script
    assert ".Config.Env" in script
    assert "release revision" in script


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _minimal_release_services() -> str:
    names = (*API_IMAGE_SERVICES, *WORKER_IMAGE_SERVICES)
    return "services:\n" + "".join(f"  {name}: {{}}\n" for name in names)


def _release_compose_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "checkout"
    script = root / "scripts/release_compose.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts/release_compose.sh", script)
    (root / "docker-compose.yml").write_text(
        _minimal_release_services(), encoding="utf-8"
    )
    shutil.copy2(RELEASE_COMPOSE_PATH, root / "docker-compose.release.yml")
    (root / "docker-compose.override.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )

    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "git",
        f"""#!/bin/sh
case "$*" in
  *"rev-parse --verify HEAD"*) printf '%s\n' "${{FAKE_GIT_SHA:-{TARGET_SHA}}}" ;;
  *"diff --cached --quiet --"*) [ "${{FAKE_GIT_DIRTY:-}}" != staged ] ;;
  *"diff --quiet --"*) [ "${{FAKE_GIT_DIRTY:-}}" != unstaged ] ;;
  *"ls-files --others --ignored"*)
    [ -z "${{FAKE_IGNORED_RUNTIME:-}}" ] || printf '%s\n' 'apps/api/src/__pycache__/ignored.pyc'
    ;;
  *"ls-files --others"*)
    [ -z "${{FAKE_UNTRACKED_RUNTIME:-}}" ] || printf '%s\n' 'apps/api/src/untracked.py'
    ;;
  *) exit 0 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/bin/sh
printf 'release=%s\n' "$EGP_RELEASE_SHA"
printf 'args=%s\n' "$*"
printf 'cwd=%s\n' "$PWD"
""",
    )
    env = {
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "EGP_RELEASE_SHA": "caller-supplied-stale-value",
    }
    return script, env


def test_release_compose_derives_checkout_sha_and_overrides_caller(
    tmp_path: Path,
) -> None:
    script, env = _release_compose_fixture(tmp_path)

    result = subprocess.run(
        [str(script), "--env-file", "/etc/egp/egp.env", "up", "-d", "--build"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"release={TARGET_SHA}" in result.stdout
    assert "compose" in result.stdout
    assert "docker-compose.yml" in result.stdout
    assert "docker-compose.release.yml" in result.stdout
    assert "docker-compose.override.yml" in result.stdout
    assert "--env-file /etc/egp/egp.env up -d --build" in result.stdout
    assert f"cwd={script.parents[1]}" in result.stdout
    args = result.stdout.split("args=", maxsplit=1)[1].splitlines()[0]
    assert args.index("docker-compose.yml") < args.index("docker-compose.override.yml")
    assert args.index("docker-compose.override.yml") < args.index(
        "docker-compose.release.yml"
    )


def test_release_compose_can_target_clean_rollback_worktree(tmp_path: Path) -> None:
    script, env = _release_compose_fixture(tmp_path)
    rollback_root = tmp_path / "rollback-source"
    rollback_root.mkdir()
    (rollback_root / "docker-compose.yml").write_text(
        _minimal_release_services(), encoding="utf-8"
    )

    result = subprocess.run(
        [
            str(script),
            "--source-root",
            str(rollback_root),
            "--project-name",
            "egp",
            "build",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"cwd={rollback_root}" in result.stdout
    assert str(rollback_root / "docker-compose.yml") in result.stdout
    assert str(script.parents[1] / "docker-compose.release.yml") in result.stdout


def test_release_compose_refuses_incompatible_rollback_topology(tmp_path: Path) -> None:
    script, env = _release_compose_fixture(tmp_path)
    rollback_root = tmp_path / "pre_u7c_source"
    rollback_root.mkdir()
    (rollback_root / "docker-compose.yml").write_text(
        "services:\n  api: {}\n  discovery-executor: {}\n", encoding="utf-8"
    )

    result = subprocess.run(
        [str(script), "--source-root", str(rollback_root), "build"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "incompatible release topology" in result.stderr
    assert "release=" not in result.stdout


@pytest.mark.parametrize("dirty_state", ["staged", "unstaged"])
def test_release_compose_refuses_tracked_source_drift(
    tmp_path: Path, dirty_state: str
) -> None:
    script, env = _release_compose_fixture(tmp_path)
    env["FAKE_GIT_DIRTY"] = dirty_state

    result = subprocess.run(
        [str(script), "build", "api"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "tracked source is dirty" in result.stderr
    assert "release=" not in result.stdout


def test_release_compose_refuses_non_commit_revision(tmp_path: Path) -> None:
    script, env = _release_compose_fixture(tmp_path)
    env["FAKE_GIT_SHA"] = "not-a-commit"

    result = subprocess.run(
        [str(script), "build", "api"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "exact release revision" in result.stderr
    assert "release=" not in result.stdout


def test_release_compose_refuses_untracked_runtime_source(tmp_path: Path) -> None:
    script, env = _release_compose_fixture(tmp_path)
    env["FAKE_UNTRACKED_RUNTIME"] = "1"

    result = subprocess.run(
        [str(script), "build", "api"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "untracked runtime source" in result.stderr
    assert "release=" not in result.stdout


def test_release_compose_refuses_ignored_runtime_source(tmp_path: Path) -> None:
    script, env = _release_compose_fixture(tmp_path)
    env["FAKE_IGNORED_RUNTIME"] = "1"

    result = subprocess.run(
        [str(script), "build", "api"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ignored runtime source" in result.stderr
    assert "release=" not in result.stdout


def test_release_compose_refuses_override_mount_over_app(tmp_path: Path) -> None:
    script, env = _release_compose_fixture(tmp_path)
    (script.parents[1] / "docker-compose.override.yml").write_text(
        "services:\n  api:\n    volumes:\n      - ./apps:/app\n", encoding="utf-8"
    )

    result = subprocess.run(
        [str(script), "build", "api"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "runtime source mount" in result.stderr
    assert "release=" not in result.stdout


def test_runtime_image_smoke_rejects_malformed_expected_revision(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    _write_executable(fake_bin / "docker", "#!/bin/sh\nexit 99\n")
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "EGP_EXPECTED_RELEASE_SHA": "unknown",
    }

    result = subprocess.run(
        [str(REPO_ROOT / "scripts/smoke_runtime_images.sh"), "api:test", "worker:test"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "exact 40-character lowercase Git SHA" in result.stderr


def _remote_runner_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "checkout"
    script = root / "scripts/run_remote_crawl.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "scripts/run_remote_crawl.sh", script)
    (root / ".env.remotecrawl").write_text("SAFE=1\n", encoding="utf-8")

    _write_executable(
        root / ".venv/bin/python",
        """#!/bin/sh
case "$*" in
  *"remote_crawl_guard.py check"*) exit 0 ;;
  *"remote_crawl_guard.py print-env"*) printf 'EGP_RELEASE_SHA=stale\\0' ;;
  -m*) printf '%s' "$EGP_RELEASE_SHA" ;;
  *) exit 0 ;;
esac
""",
    )
    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "git",
        f"""#!/bin/sh
case "$*" in
  *"rev-parse --verify HEAD"*) printf '%s\\n' '{TARGET_SHA}' ;;
  *"diff --quiet"*) [ "${{FAKE_GIT_DIRTY:-0}}" = 0 ] ;;
  *"ls-files --others --ignored"*)
    [ -z "${{FAKE_IGNORED_RUNTIME:-}}" ] || printf '%s\n' 'apps/worker/src/__pycache__/ignored.pyc'
    ;;
  *"ls-files --others"*)
    [ -z "${{FAKE_UNTRACKED_RUNTIME:-}}" ] || printf '%s\n' 'apps/worker/src/untracked.py'
    ;;
  *) exit 0 ;;
esac
""",
    )
    env = {
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "EGP_REMOTECRAWL_ENV_FILE": str(root / ".env.remotecrawl"),
    }
    return script, env


def test_remote_runner_stamps_checkout_sha_before_runtime(tmp_path: Path) -> None:
    script, env = _remote_runner_fixture(tmp_path)

    result = subprocess.run(
        [str(script), "doctor"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == TARGET_SHA


def test_remote_runner_refuses_tracked_source_drift(tmp_path: Path) -> None:
    script, env = _remote_runner_fixture(tmp_path)
    env["FAKE_GIT_DIRTY"] = "1"

    result = subprocess.run(
        [str(script), "doctor"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "tracked source is dirty" in result.stderr
    assert TARGET_SHA not in result.stdout


def test_remote_runner_refuses_untracked_runtime_source(tmp_path: Path) -> None:
    script, env = _remote_runner_fixture(tmp_path)
    env["FAKE_UNTRACKED_RUNTIME"] = "1"

    result = subprocess.run(
        [str(script), "doctor"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "untracked runtime source" in result.stderr
    assert TARGET_SHA not in result.stdout


def test_remote_runner_refuses_ignored_runtime_source(tmp_path: Path) -> None:
    script, env = _remote_runner_fixture(tmp_path)
    env["FAKE_IGNORED_RUNTIME"] = "1"

    result = subprocess.run(
        [str(script), "doctor"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ignored runtime source" in result.stderr
    assert TARGET_SHA not in result.stdout
