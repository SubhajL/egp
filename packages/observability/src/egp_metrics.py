"""Compatibility exports for e-GP Prometheus metrics."""

from egp_observability.metrics import (
    CONTENT_TYPE,
    EXPECTED_METRIC_NAMES,
    get_metrics_registry,
    initialize_metrics,
    instrument_fastapi_app,
    metric_names_for_validation,
    observe_api_request,
    observe_rate_limiter_wait,
    record_document_upsert_conflict,
    record_egp_request,
    record_worker_job,
    render_prometheus_metrics,
    reset_metrics_for_tests,
)

__all__ = [
    "CONTENT_TYPE",
    "EXPECTED_METRIC_NAMES",
    "get_metrics_registry",
    "initialize_metrics",
    "instrument_fastapi_app",
    "metric_names_for_validation",
    "observe_api_request",
    "observe_rate_limiter_wait",
    "record_document_upsert_conflict",
    "record_egp_request",
    "record_worker_job",
    "render_prometheus_metrics",
    "reset_metrics_for_tests",
]
