from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from egp_api.main import create_app
from egp_worker import main as worker_main

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - CI can validate JSON-subset YAML.
    yaml = None


EXPECTED_METRIC_NAMES = {
    "egp_api_http_requests_total",
    "egp_api_http_request_duration_seconds",
    "egp_worker_jobs_total",
    "egp_worker_job_duration_seconds",
    "egp_dispatch_duration_seconds",
    "egp_worker_subprocess_count",
    "egp_egp_request_total",
    "egp_rate_limiter_wait_seconds",
    "egp_project_upsert_conflicts_total",
    "egp_document_upsert_conflicts_total",
    "egp_document_capture_attempts_total",
    "egp_discovery_queue_depth",
    "egp_discovery_dispatch_total",
    "egp_discovery_inflight_runs",
}


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _create_client(tmp_path: Path, *, auth_required: bool = False) -> TestClient:
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=f"sqlite+pysqlite:///{tmp_path / 'observability.sqlite3'}",
            jwt_secret="observability-test-secret",
            payment_callback_secret="observability-callback-secret",
            auth_required=auth_required,
        )
    )


def _metric_output() -> str:
    from egp_observability.metrics import render_prometheus_metrics

    return render_prometheus_metrics()[0].decode("utf-8")


def test_metrics_endpoint_exposes_pr01_metric_names(tmp_path: Path) -> None:
    from egp_observability.metrics import reset_metrics_for_tests

    reset_metrics_for_tests()
    client = _create_client(tmp_path)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for metric_name in EXPECTED_METRIC_NAMES:
        assert metric_name in response.text


def test_metrics_endpoint_counts_api_requests(tmp_path: Path) -> None:
    from egp_observability.metrics import reset_metrics_for_tests

    reset_metrics_for_tests()
    client = _create_client(tmp_path)

    health_response = client.get("/health")
    metrics_response = client.get("/metrics")

    assert health_response.status_code == 200
    assert metrics_response.status_code == 200
    assert (
        'egp_api_http_requests_total{method="GET",path="/health",status_class="2xx"} 1.0'
        in (metrics_response.text)
    )


def test_metrics_endpoint_bypasses_auth_required(tmp_path: Path) -> None:
    from egp_observability.metrics import reset_metrics_for_tests

    reset_metrics_for_tests()
    client = _create_client(tmp_path, auth_required=True)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "egp_api_http_requests_total" in response.text


def test_worker_main_records_successful_command_metrics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from egp_observability.metrics import reset_metrics_for_tests

    reset_metrics_for_tests()

    worker_main.main('{"command":"noop"}')

    assert json.loads(capsys.readouterr().out) == {
        "service": "worker",
        "status": "idle",
    }
    metrics_text = _metric_output()
    assert 'egp_worker_jobs_total{command="noop",outcome="success"} 1.0' in metrics_text


def test_worker_main_records_failed_command_metrics() -> None:
    from egp_observability.metrics import reset_metrics_for_tests

    reset_metrics_for_tests()

    with pytest.raises(ValueError, match="Unsupported worker command"):
        worker_main.main('{"command":"unsupported"}')

    metrics_text = _metric_output()
    assert (
        'egp_worker_jobs_total{command="unsupported",outcome="error"} 1.0'
        in metrics_text
    )


def test_document_upsert_conflict_metric_records_resolved_outcome() -> None:
    from egp_observability.metrics import (
        record_document_upsert_conflict,
        reset_metrics_for_tests,
    )

    reset_metrics_for_tests()

    record_document_upsert_conflict(outcome="resolved")

    assert (
        'egp_document_upsert_conflicts_total{outcome="resolved"} 1.0'
        in _metric_output()
    )


def test_document_capture_attempt_metric_records_non_success_status() -> None:
    from egp_observability.metrics import (
        record_document_capture_attempt,
        reset_metrics_for_tests,
    )

    reset_metrics_for_tests()

    record_document_capture_attempt(status="failed")

    assert (
        'egp_document_capture_attempts_total{outcome="non_success",status="failed"} 1.0'
        in _metric_output()
    )


def test_egp_request_and_rate_limiter_metric_helpers_record_outcomes() -> None:
    from egp_observability.metrics import (
        observe_rate_limiter_wait,
        record_egp_request,
        reset_metrics_for_tests,
    )

    reset_metrics_for_tests()

    record_egp_request(outcome="429")
    observe_rate_limiter_wait(duration_seconds=0.25)

    metrics_text = _metric_output()
    assert 'egp_egp_request_total{outcome="429"} 1.0' in metrics_text
    assert "egp_rate_limiter_wait_seconds_count 1.0" in metrics_text
    assert "egp_rate_limiter_wait_seconds_sum 0.25" in metrics_text


def test_grafana_dashboard_json_validates(repo_root: Path) -> None:
    dashboard_path = repo_root / "infrastructure" / "grafana" / "dashboard.json"

    dashboard = json.loads(dashboard_path.read_text())
    serialized = json.dumps(dashboard)

    assert dashboard["title"] == "e-GP Observability Baseline"
    for metric_name in EXPECTED_METRIC_NAMES:
        assert metric_name in serialized


def test_grafana_alert_rules_yaml_validates(repo_root: Path) -> None:
    alerts_path = repo_root / "infrastructure" / "grafana" / "alerts.yml"
    raw_alerts = alerts_path.read_text()
    alerts = yaml.safe_load(raw_alerts) if yaml is not None else json.loads(raw_alerts)
    serialized = json.dumps(alerts)

    assert alerts["groups"][0]["name"] == "egp-observability"
    assert "EGPMetricsScrapeFailures" in serialized
    for metric_name in (
        "egp_api_http_requests_total",
        "egp_worker_jobs_total",
        "egp_worker_subprocess_count",
        "egp_egp_request_total",
        "egp_document_capture_attempts_total",
    ):
        assert metric_name in serialized
