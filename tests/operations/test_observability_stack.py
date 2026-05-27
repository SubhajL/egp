"""Drift tests for the PR-E observability stack deployment overlay.

Three concerns:

1. ``docker-compose.monitoring.yml`` parses, pins image tags, binds to
   loopback only, declares named volumes, and configures Grafana with the
   required admin-password env var + anon/signup disabled.
2. ``deploy/prometheus.yml`` parses and scrapes the API service.
3. Grafana provisioning files exist + parse; the deployed dashboard JSON
   matches the canonical PR-01 dashboard byte-for-byte.

A second tier of tests optionally runs ``docker compose ... config -q`` if
the binary is available, to verify the overlay validates against the base
Compose file with env vars from the production template.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_BASE = REPO_ROOT / "docker-compose.yml"
COMPOSE_MONITORING = REPO_ROOT / "docker-compose.monitoring.yml"
PROMETHEUS_CONFIG = REPO_ROOT / "deploy" / "prometheus.yml"
GRAFANA_DS_CONFIG = (
    REPO_ROOT / "deploy" / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
)
GRAFANA_DASH_PROVIDER = (
    REPO_ROOT / "deploy" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"
)
DEPLOYED_DASHBOARD = (
    REPO_ROOT / "deploy" / "grafana" / "dashboards" / "egp-overview.json"
)
CANONICAL_DASHBOARD = REPO_ROOT / "infrastructure" / "grafana" / "dashboard.json"
ENV_TEMPLATE = REPO_ROOT / "deploy" / ".env.production.example"
OBSERVABILITY_DOC = REPO_ROOT / "docs" / "OBSERVABILITY.md"


def _load_compose(path: Path) -> dict[str, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Compose overlay structure
# ---------------------------------------------------------------------------


def test_monitoring_compose_defines_required_services() -> None:
    assert COMPOSE_MONITORING.exists(), f"missing {COMPOSE_MONITORING}"
    overlay = _load_compose(COMPOSE_MONITORING)
    services = overlay.get("services", {})
    assert "prometheus" in services
    assert "grafana" in services


def test_monitoring_compose_uses_pinned_image_tags() -> None:
    overlay = _load_compose(COMPOSE_MONITORING)
    services = overlay["services"]
    prom_image = services["prometheus"]["image"]
    graf_image = services["grafana"]["image"]
    assert ":" in prom_image and not prom_image.endswith(":latest"), (
        f"prometheus image must be pinned, got {prom_image!r}"
    )
    assert ":" in graf_image and not graf_image.endswith(":latest"), (
        f"grafana image must be pinned, got {graf_image!r}"
    )
    assert prom_image.startswith("prom/prometheus:")
    assert graf_image.startswith("grafana/grafana:")


def test_monitoring_compose_binds_to_loopback_only() -> None:
    overlay = _load_compose(COMPOSE_MONITORING)
    services = overlay["services"]
    for name in ("prometheus", "grafana"):
        for port in services[name].get("ports", []):
            assert port.startswith("127.0.0.1:"), (
                f"{name} port {port!r} must bind to 127.0.0.1 only "
                "(no public exposure; SSH tunnel pattern)"
            )


def test_monitoring_compose_uses_named_volumes() -> None:
    overlay = _load_compose(COMPOSE_MONITORING)
    volumes = overlay.get("volumes", {})
    assert "egp_prometheus_data" in volumes
    assert "egp_grafana_data" in volumes
    # Both volumes should reference state mount points in services.
    services = overlay["services"]
    prom_volumes = " ".join(services["prometheus"].get("volumes", []))
    graf_volumes = " ".join(services["grafana"].get("volumes", []))
    assert "egp_prometheus_data:" in prom_volumes
    assert "egp_grafana_data:" in graf_volumes


def test_monitoring_compose_grafana_requires_admin_password_env() -> None:
    raw = COMPOSE_MONITORING.read_text(encoding="utf-8")
    assert "EGP_GRAFANA_ADMIN_PASSWORD" in raw, (
        "monitoring overlay must reference EGP_GRAFANA_ADMIN_PASSWORD"
    )
    assert "${EGP_GRAFANA_ADMIN_PASSWORD:?" in raw, (
        "Grafana admin password must be REQUIRED (`:?` interpolation), "
        "not silently defaulted"
    )


def test_monitoring_compose_grafana_disables_anon_and_signup() -> None:
    overlay = _load_compose(COMPOSE_MONITORING)
    env = overlay["services"]["grafana"].get("environment", {})
    # Either dict or list form
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    assert str(env.get("GF_USERS_ALLOW_SIGN_UP", "")).lower() in {"false", "0"}, (
        "GF_USERS_ALLOW_SIGN_UP must be disabled in production"
    )
    assert str(env.get("GF_AUTH_ANONYMOUS_ENABLED", "")).lower() in {"false", "0"}, (
        "GF_AUTH_ANONYMOUS_ENABLED must be disabled in production"
    )


def test_monitoring_compose_has_no_cross_overlay_depends_on() -> None:
    """The overlay must NOT declare `depends_on: [api]` etc., because the
    overlay is loaded with `-f docker-compose.yml -f docker-compose.monitoring.yml`
    and cross-file depends_on can be brittle. Prometheus tolerates target-down.
    """
    overlay = _load_compose(COMPOSE_MONITORING)
    for name in ("prometheus", "grafana"):
        assert "depends_on" not in overlay["services"][name], (
            f"{name} must not declare depends_on in the overlay"
        )


# ---------------------------------------------------------------------------
# Prometheus config
# ---------------------------------------------------------------------------


def test_prometheus_config_parses() -> None:
    assert PROMETHEUS_CONFIG.exists()
    parsed = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))
    assert "scrape_configs" in parsed


def test_prometheus_config_scrapes_api() -> None:
    parsed = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))
    api_jobs = [
        job for job in parsed["scrape_configs"] if job.get("job_name") == "egp_api"
    ]
    assert len(api_jobs) == 1
    targets = [
        target
        for sc in api_jobs[0].get("static_configs", [])
        for target in sc.get("targets", [])
    ]
    assert "api:8000" in targets, (
        f"egp_api job must target api:8000 (Compose service-name DNS), got {targets}"
    )


def test_prometheus_config_scrape_interval_is_15s() -> None:
    parsed = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))
    assert parsed.get("global", {}).get("scrape_interval") == "15s"


# ---------------------------------------------------------------------------
# Grafana provisioning
# ---------------------------------------------------------------------------


def test_grafana_datasource_provisioning_parses() -> None:
    assert GRAFANA_DS_CONFIG.exists()
    parsed = yaml.safe_load(GRAFANA_DS_CONFIG.read_text(encoding="utf-8"))
    assert parsed.get("apiVersion") == 1
    assert isinstance(parsed.get("datasources"), list) and parsed["datasources"]


def test_grafana_datasource_points_at_prometheus() -> None:
    parsed = yaml.safe_load(GRAFANA_DS_CONFIG.read_text(encoding="utf-8"))
    prom_sources = [
        ds for ds in parsed["datasources"] if ds.get("type") == "prometheus"
    ]
    assert prom_sources, "expected a prometheus-type datasource"
    assert prom_sources[0]["url"] == "http://prometheus:9090", (
        f"datasource URL must use Compose service-name DNS, "
        f"got {prom_sources[0]['url']!r}"
    )


def test_grafana_dashboard_provider_parses() -> None:
    assert GRAFANA_DASH_PROVIDER.exists()
    parsed = yaml.safe_load(GRAFANA_DASH_PROVIDER.read_text(encoding="utf-8"))
    assert parsed.get("apiVersion") == 1
    providers = parsed.get("providers") or []
    assert providers, "expected at least one dashboard provider"
    # Must point at the in-container dashboards path
    paths = {p.get("options", {}).get("path") for p in providers}
    assert "/var/lib/grafana/dashboards" in paths, (
        f"provider must point at /var/lib/grafana/dashboards, got {paths}"
    )


# ---------------------------------------------------------------------------
# Dashboard JSON
# ---------------------------------------------------------------------------


def test_dashboard_json_is_valid_and_has_panels() -> None:
    assert DEPLOYED_DASHBOARD.exists()
    payload = json.loads(DEPLOYED_DASHBOARD.read_text(encoding="utf-8"))
    panels = payload.get("panels", [])
    assert isinstance(panels, list) and len(panels) >= 5, (
        f"dashboard must have >= 5 panels, got {len(panels)}"
    )


def test_deployed_dashboard_matches_canonical_source() -> None:
    """The deployed dashboard MUST be byte-identical to the canonical
    PR-01 source. Drift between the two paths is forbidden — operators
    edit the canonical source and a one-line `cp` keeps them in sync.
    """
    assert CANONICAL_DASHBOARD.exists(), (
        f"canonical dashboard missing: {CANONICAL_DASHBOARD}"
    )
    assert DEPLOYED_DASHBOARD.exists(), (
        f"deployed dashboard missing: {DEPLOYED_DASHBOARD}"
    )
    canonical_bytes = CANONICAL_DASHBOARD.read_bytes()
    deployed_bytes = DEPLOYED_DASHBOARD.read_bytes()
    assert canonical_bytes == deployed_bytes, (
        "dashboard drift: "
        f"{DEPLOYED_DASHBOARD.relative_to(REPO_ROOT)} is not byte-identical to "
        f"{CANONICAL_DASHBOARD.relative_to(REPO_ROOT)}. "
        "Run: cp infrastructure/grafana/dashboard.json deploy/grafana/dashboards/egp-overview.json"
    )


# ---------------------------------------------------------------------------
# End-to-end Compose validation (skip if docker missing)
# ---------------------------------------------------------------------------


def test_compose_with_monitoring_overlay_validates() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_TEMPLATE),
            "-f",
            str(COMPOSE_BASE),
            "-f",
            str(COMPOSE_MONITORING),
            "config",
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"docker compose config -q failed:\nstdout={completed.stdout}\n"
        f"stderr={completed.stderr}"
    )


# ---------------------------------------------------------------------------
# Docs coverage
# ---------------------------------------------------------------------------


def test_observability_doc_covers_ssh_tunnel_and_grafana_cloud() -> None:
    assert OBSERVABILITY_DOC.exists()
    text = OBSERVABILITY_DOC.read_text(encoding="utf-8")
    assert "ssh -L" in text, "doc must show the SSH tunnel command"
    assert "Grafana Cloud" in text, "doc must cover the Grafana Cloud Free alternative"
    assert "127.0.0.1:3000" in text or "127.0.0.1:3001" in text, (
        "doc must show the loopback Grafana port for tunneling"
    )
