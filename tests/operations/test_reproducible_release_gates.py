from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
UV_VERSION = "0.11.32"
SETUP_UV_ACTION = "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b"


def _read_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _workflow() -> dict[str, object]:
    with (REPO_ROOT / ".github/workflows/ci.yml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _named_step(job: dict[str, object], name: str) -> dict[str, object]:
    steps = job["steps"]
    assert isinstance(steps, list)
    return next(step for step in steps if step.get("name") == name)


def test_python_workspace_uses_one_frozen_lock_everywhere() -> None:
    root_config = _read_toml(REPO_ROOT / "pyproject.toml")
    api_config = _read_toml(REPO_ROOT / "apps/api/pyproject.toml")
    worker_config = _read_toml(REPO_ROOT / "apps/worker/pyproject.toml")

    assert (REPO_ROOT / "uv.lock").is_file()
    assert root_config["tool"]["uv"]["required-version"] == f"=={UV_VERSION}"
    assert root_config["tool"]["uv"]["workspace"]["members"] == [
        "apps/api",
        "apps/worker",
    ]

    for config in (api_config, worker_config):
        dependencies = config["project"]["dependencies"]
        assert "egp-monorepo" in dependencies
        assert config["tool"]["uv"]["sources"]["egp-monorepo"] == {"workspace": True}

    bootstrap = (REPO_ROOT / "scripts/bootstrap_python_env.sh").read_text(
        encoding="utf-8"
    )
    assert f'UV_VERSION="${{UV_VERSION:-{UV_VERSION}}}"' in bootstrap
    assert "uv sync --frozen --all-packages --all-extras" in bootstrap
    assert "pip install -e" not in bootstrap

    digest_source = re.compile(
        r"COPY --from=ghcr\.io/astral-sh/uv@sha256:[0-9a-f]{64} /uv /uvx /bin/"
    )
    for dockerfile_name in ("apps/api/Dockerfile", "apps/worker/Dockerfile"):
        dockerfile = (REPO_ROOT / dockerfile_name).read_text(encoding="utf-8")
        assert digest_source.search(dockerfile)
        assert "uv sync --frozen" in dockerfile
        assert "uv.lock" in dockerfile
        assert "pip install" not in dockerfile

    workflow_text = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert SETUP_UV_ACTION in workflow_text
    assert f"version: '{UV_VERSION}'" in workflow_text
    assert "uv sync --frozen --all-packages --all-extras" in workflow_text
    assert "pip install -e" not in workflow_text

    for instructions_name in ("AGENTS.md", "CLAUDE.md"):
        instructions = (REPO_ROOT / instructions_name).read_text(encoding="utf-8")
        assert "uv sync --frozen --all-packages --all-extras" in instructions
        assert "uv run --frozen" in instructions


def test_committed_migration_manifest_matches_every_sql_file() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_migration_manifest.py",
            "--check",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "migration manifest verified" in completed.stdout


def test_migration_manifest_checker_detects_content_drift(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_one.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (migrations_dir / "002_two.sql").write_text("SELECT 2;\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.sha256"
    command = [
        sys.executable,
        "scripts/check_migration_manifest.py",
        "--migrations-dir",
        str(migrations_dir),
        "--manifest",
        str(manifest_path),
    ]

    written = subprocess.run(
        [*command, "--write"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert written.returncode == 0, written.stdout + written.stderr

    verified = subprocess.run(
        [*command, "--check"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr

    (migrations_dir / "002_two.sql").write_text("SELECT 3;\n", encoding="utf-8")
    drifted = subprocess.run(
        [*command, "--check"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert drifted.returncode == 1
    assert "migration manifest mismatch" in drifted.stderr


def test_ci_enforces_postgres_browser_and_vulnerability_gates() -> None:
    jobs = _workflow()["jobs"]

    migration_job = jobs["db-migrations"]
    manifest_step = _named_step(migration_job, "Verify migration manifest")
    assert "python scripts/check_migration_manifest.py --check" in manifest_step["run"]
    postgres_step = _named_step(migration_job, "Run PostgreSQL API contracts")
    assert "tests/phase1/test_migration_runner.py" in postgres_step["run"]
    assert "tests/phase1/test_api_readiness.py" in postgres_step["run"]

    playwright_job = jobs["critical-playwright"]
    install_step = _named_step(playwright_job, "Install Chromium")
    assert "playwright install --with-deps chromium" in install_step["run"]
    browser_step = _named_step(playwright_job, "Run critical Playwright smoke")
    assert browser_step["run"] == "npm run test:e2e:critical"

    python_audit = _named_step(jobs["test-python"], "Audit Python dependencies")
    assert not python_audit.get("continue-on-error", False)
    assert "pip-audit --strict" in python_audit["run"]

    npm_audit = _named_step(jobs["test-frontend"], "Audit frontend dependencies")
    assert not npm_audit.get("continue-on-error", False)
    assert "npm audit --omit=dev --audit-level=high" in npm_audit["run"]
    assert "npm audit --audit-level=critical" in npm_audit["run"]


def test_critical_playwright_lane_covers_launch_paths() -> None:
    package_json = (REPO_ROOT / "apps/web/package.json").read_text(encoding="utf-8")
    assert (
        '"test:e2e:critical": "./scripts/run-playwright.sh --grep @critical"'
        in package_json
    )

    critical_titles: list[str] = []
    for spec_path in sorted((REPO_ROOT / "apps/web/tests/e2e").glob("*.spec.ts")):
        spec = spec_path.read_text(encoding="utf-8")
        critical_titles.extend(
            match.group(1)
            for match in re.finditer(r'test\("([^"]*@critical[^"]*)"', spec)
        )

    assert any("login" in title.lower() for title in critical_titles)
    assert any("recrawl" in title.lower() for title in critical_titles)
    assert any("promptpay" in title.lower() for title in critical_titles)


def test_web_image_excludes_host_build_artifacts() -> None:
    dockerignore = (REPO_ROOT / "apps/web/.dockerignore").read_text(encoding="utf-8")
    excluded_paths = {
        line.strip()
        for line in dockerignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {"node_modules", ".next", ".next-playwright"} <= excluded_paths


def test_next_type_declarations_do_not_capture_playwright_dist_dir() -> None:
    next_env = (REPO_ROOT / "apps/web/next-env.d.ts").read_text(encoding="utf-8")
    package_config = json.loads(
        (REPO_ROOT / "apps/web/package.json").read_text(encoding="utf-8")
    )
    playwright_wrapper = (REPO_ROOT / "apps/web/scripts/run-playwright.sh").read_text(
        encoding="utf-8"
    )

    assert ".next-playwright" not in next_env
    assert package_config["scripts"]["test"] == "./scripts/run-playwright.sh"
    assert package_config["scripts"]["test:e2e"] == "./scripts/run-playwright.sh"
    assert (
        package_config["scripts"]["test:e2e:critical"]
        == "./scripts/run-playwright.sh --grep @critical"
    )
    assert "trap cleanup EXIT HUP INT TERM" in playwright_wrapper
    assert 'cp "$next_env_backup" "$next_env_file"' in playwright_wrapper


def test_frontend_uses_patched_vercel_compatible_next_release() -> None:
    package_config = json.loads(
        (REPO_ROOT / "apps/web/package.json").read_text(encoding="utf-8")
    )
    vercel_config = json.loads(
        (REPO_ROOT / "apps/web/vercel.json").read_text(encoding="utf-8")
    )
    next_config = (REPO_ROOT / "apps/web/next.config.mjs").read_text(encoding="utf-8")
    release_build = "rm -rf .next && next build"

    assert package_config["dependencies"]["next"] == "^15.5.18"
    assert package_config["devDependencies"]["eslint-config-next"] == "^15.5.18"
    assert package_config["scripts"]["build"] == release_build
    assert "build:vercel" not in package_config["scripts"]
    assert vercel_config["buildCommand"] == "npm run build"
    assert 'output: "standalone"' in next_config
