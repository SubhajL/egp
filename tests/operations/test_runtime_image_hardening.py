from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DOCKERFILE = REPO_ROOT / "apps/api/Dockerfile"
WORKER_DOCKERFILE = REPO_ROOT / "apps/worker/Dockerfile"
COMPOSE_PATHS = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose-localdev.yml",
)


def _compose(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_api_image_is_non_root_and_excludes_browser_worker_runtime() -> None:
    dockerfile = API_DOCKERFILE.read_text(encoding="utf-8")

    assert "uv sync --frozen --package egp-api --no-dev --no-editable" in dockerfile
    assert "COPY apps/worker/src" not in dockerfile
    assert dockerfile.count("COPY apps/api/src apps/api/src") == 1
    assert "COPY apps/api/ apps/api/" not in dockerfile
    assert "COPY apps/worker/ apps/worker/" not in dockerfile
    assert "playwright install" not in dockerfile
    assert "ms-playwright" not in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "USER 10001:10001" in dockerfile


def test_worker_image_is_non_root_and_contains_api_executor_and_browser() -> None:
    dockerfile = WORKER_DOCKERFILE.read_text(encoding="utf-8")

    assert (
        "uv sync --frozen --package egp-api --package egp-worker --no-dev --no-editable"
        in dockerfile
    )
    assert "COPY apps/api/src apps/api/src" in dockerfile
    assert "COPY apps/worker/src apps/worker/src" in dockerfile
    assert "COPY apps/api/ apps/api/" not in dockerfile
    assert "COPY apps/worker/ apps/worker/" not in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "playwright install chromium" in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "XDG_CONFIG_HOME=/tmp/.config" in dockerfile
    assert "USER 10001:10001" in dockerfile


def test_compose_uses_control_plane_and_browser_images_for_correct_services() -> None:
    for compose_path in COMPOSE_PATHS:
        services = _compose(compose_path)["services"]

        for service_name in ("migrate", "api", "webhook-executor"):
            assert (
                services[service_name]["build"]["dockerfile"] == "apps/api/Dockerfile"
            )
        assert (
            services["discovery-executor"]["build"]["dockerfile"]
            == "apps/worker/Dockerfile"
        )


def test_compose_bounds_resources_and_rotates_logs_for_every_service() -> None:
    for compose_path in COMPOSE_PATHS:
        services = _compose(compose_path)["services"]

        for service_name, service in services.items():
            assert service.get("mem_limit"), (
                f"{compose_path.name}:{service_name} must bound memory"
            )
            assert service.get("cpus"), (
                f"{compose_path.name}:{service_name} must bound CPU"
            )
            assert service.get("pids_limit"), (
                f"{compose_path.name}:{service_name} must bound PIDs"
            )
            logging = service.get("logging", {})
            assert logging.get("driver") == "json-file"
            assert logging.get("options", {}).get("max-size")
            assert logging.get("options", {}).get("max-file")


def test_python_runtime_services_are_read_only_with_bounded_tmpfs() -> None:
    for compose_path in COMPOSE_PATHS:
        services = _compose(compose_path)["services"]

        for service_name in (
            "migrate",
            "api",
            "webhook-executor",
            "discovery-executor",
        ):
            service = services[service_name]
            assert service.get("read_only") is True
            tmpfs = service.get("tmpfs", [])
            assert any(str(entry).startswith("/tmp:") for entry in tmpfs)

        discovery = services["discovery-executor"]
        assert (
            discovery["environment"]["EGP_BROWSER_PROFILE_ROOT"]
            == "/var/lib/egp/browser-profiles"
        )
        browser_profile_tmpfs = next(
            str(entry)
            for entry in discovery["tmpfs"]
            if str(entry).startswith("/var/lib/egp/browser-profiles:")
        )
        runtime_tmpfs = next(
            str(entry) for entry in discovery["tmpfs"] if str(entry).startswith("/tmp:")
        )
        assert "size=256m" in runtime_tmpfs
        assert "size=256m" in browser_profile_tmpfs
        assert "uid=10001" in browser_profile_tmpfs
        assert "gid=10001" in browser_profile_tmpfs
        assert "mode=0700" in browser_profile_tmpfs


def test_ci_builds_named_images_and_runs_executable_smoke_contract() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    build_steps = workflow["jobs"]["build"]["steps"]
    named_steps = {step.get("name"): step for step in build_steps}

    assert "egp-api:ci" in named_steps["Validate API Docker image"]["run"]
    assert "egp-worker:ci" in named_steps["Validate Worker Docker image"]["run"]
    smoke_step = named_steps["Smoke runtime images"]
    assert (
        smoke_step["run"]
        == "./scripts/smoke_runtime_images.sh egp-api:ci egp-worker:ci"
    )

    smoke_script = REPO_ROOT / "scripts/smoke_runtime_images.sh"
    assert smoke_script.is_file()
    assert smoke_script.stat().st_mode & 0o111
    smoke_text = smoke_script.read_text(encoding="utf-8")
    assert "launch_real_chrome(" in smoke_text
    assert "connect_playwright_to_chrome(" in smoke_text
    assert "use_xvfb=True" in smoke_text
    assert "destination=/var/lib/egp/artifacts" in smoke_text
    assert "--tmpfs /var/lib/egp/browser-profiles:" in smoke_text
    assert "EGP_WORKER_IMAGE_MAX_BYTES" in smoke_text


def test_runtime_docs_describe_split_images_and_compose_profile_path() -> None:
    launch_guide = (REPO_ROOT / "docs/LIGHTSAIL_LOW_COST_LAUNCH.md").read_text(
        encoding="utf-8"
    )
    deployment_guide = (REPO_ROOT / "docs/DEPLOYMENT.md").read_text(encoding="utf-8")

    assert "API image excludes Chromium" in launch_guide
    assert "worker image contains Playwright and Chromium" in launch_guide
    assert "`/var/lib/egp/browser-profiles`" in deployment_guide
    assert "read-only root filesystems" in deployment_guide
    assert "existing named volumes" in deployment_guide
