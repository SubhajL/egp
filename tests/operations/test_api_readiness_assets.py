from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "compose_name",
    ("docker-compose.yml", "docker-compose-localdev.yml"),
)
def test_api_compose_healthcheck_uses_readiness(compose_name: str) -> None:
    compose = yaml.safe_load((REPO_ROOT / compose_name).read_text(encoding="utf-8"))

    assert compose["services"]["api"]["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-f",
        "http://localhost:8000/ready",
    ]


def test_api_image_healthcheck_uses_readiness() -> None:
    dockerfile = (REPO_ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")

    assert "http://localhost:8000/ready" in dockerfile
    assert "http://localhost:8000/health" not in dockerfile


def test_launch_gate_checker_distinguishes_live_from_ready() -> None:
    launch_checker = (REPO_ROOT / "scripts/check_launch_gates.sh").read_text(
        encoding="utf-8"
    )

    assert '"$API_URL/live"' in launch_checker
    assert '"$API_URL/ready"' in launch_checker


@pytest.mark.parametrize(
    "template_name",
    (".env.example", "deploy/.env.production.example"),
)
def test_env_templates_select_external_postgres_topology(template_name: str) -> None:
    template = (REPO_ROOT / template_name).read_text(encoding="utf-8")

    assert "EGP_BACKGROUND_RUNTIME_MODE=external" in template
