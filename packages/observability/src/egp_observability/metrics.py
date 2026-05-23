"""Prometheus metric definitions and runtime instrumentation helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)
from prometheus_client import generate_latest

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

CONTENT_TYPE: Final[str] = CONTENT_TYPE_LATEST

API_HTTP_REQUESTS_TOTAL: Final[str] = "egp_api_http_requests_total"
API_HTTP_REQUEST_DURATION_SECONDS: Final[str] = "egp_api_http_request_duration_seconds"
WORKER_JOBS_TOTAL: Final[str] = "egp_worker_jobs_total"
WORKER_JOB_DURATION_SECONDS: Final[str] = "egp_worker_job_duration_seconds"
DISPATCH_DURATION_SECONDS: Final[str] = "egp_dispatch_duration_seconds"
WORKER_SUBPROCESS_COUNT: Final[str] = "egp_worker_subprocess_count"
EGP_REQUEST_TOTAL: Final[str] = "egp_egp_request_total"
RATE_LIMITER_WAIT_SECONDS: Final[str] = "egp_rate_limiter_wait_seconds"
PROJECT_UPSERT_CONFLICTS_TOTAL: Final[str] = "egp_project_upsert_conflicts_total"
DOCUMENT_UPSERT_CONFLICTS_TOTAL: Final[str] = "egp_document_upsert_conflicts_total"
DISCOVERY_QUEUE_DEPTH: Final[str] = "egp_discovery_queue_depth"
DISCOVERY_DISPATCH_TOTAL: Final[str] = "egp_discovery_dispatch_total"
DISCOVERY_INFLIGHT_RUNS: Final[str] = "egp_discovery_inflight_runs"

EXPECTED_METRIC_NAMES: Final[tuple[str, ...]] = (
    API_HTTP_REQUESTS_TOTAL,
    API_HTTP_REQUEST_DURATION_SECONDS,
    WORKER_JOBS_TOTAL,
    WORKER_JOB_DURATION_SECONDS,
    DISPATCH_DURATION_SECONDS,
    WORKER_SUBPROCESS_COUNT,
    EGP_REQUEST_TOTAL,
    RATE_LIMITER_WAIT_SECONDS,
    PROJECT_UPSERT_CONFLICTS_TOTAL,
    DOCUMENT_UPSERT_CONFLICTS_TOTAL,
    DISCOVERY_QUEUE_DEPTH,
    DISCOVERY_DISPATCH_TOTAL,
    DISCOVERY_INFLIGHT_RUNS,
)

_REQUEST_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)
_WORKER_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.1,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    300.0,
    900.0,
    3600.0,
    10800.0,
)
_KNOWN_WORKER_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "noop",
        "discover",
        "close_check",
        "document_ingest",
        "timeout_evaluate",
        "run_scheduled_discovery",
    }
)


@dataclass(frozen=True)
class MetricsBundle:
    registry: CollectorRegistry
    api_http_requests: Counter
    api_http_request_duration: Histogram
    worker_jobs: Counter
    worker_job_duration: Histogram
    dispatch_duration: Histogram
    worker_subprocess_count: Gauge
    egp_request_total: Counter
    rate_limiter_wait_seconds: Histogram
    project_upsert_conflicts: Counter
    document_upsert_conflicts: Counter
    discovery_queue_depth: Gauge
    discovery_dispatch_total: Counter
    discovery_inflight_runs: Gauge


_metrics: MetricsBundle | None = None


def metric_names_for_validation() -> tuple[str, ...]:
    """Return the stable metric names expected by dashboards, alerts, and tests."""

    return EXPECTED_METRIC_NAMES


def initialize_metrics() -> MetricsBundle:
    """Initialize the process-local Prometheus registry once and return it."""

    global _metrics
    if _metrics is not None:
        return _metrics

    registry = CollectorRegistry(auto_describe=True)
    _metrics = MetricsBundle(
        registry=registry,
        api_http_requests=Counter(
            API_HTTP_REQUESTS_TOTAL,
            "HTTP requests handled by the API.",
            ("method", "path", "status_class"),
            registry=registry,
        ),
        api_http_request_duration=Histogram(
            API_HTTP_REQUEST_DURATION_SECONDS,
            "HTTP request duration for the API.",
            ("method", "path", "status_class"),
            buckets=_REQUEST_DURATION_BUCKETS,
            registry=registry,
        ),
        worker_jobs=Counter(
            WORKER_JOBS_TOTAL,
            "Worker commands executed by the crawler worker.",
            ("command", "outcome"),
            registry=registry,
        ),
        worker_job_duration=Histogram(
            WORKER_JOB_DURATION_SECONDS,
            "Worker command duration.",
            ("command", "outcome"),
            buckets=_WORKER_DURATION_BUCKETS,
            registry=registry,
        ),
        dispatch_duration=Histogram(
            DISPATCH_DURATION_SECONDS,
            "Discovery dispatch loop duration.",
            ("outcome",),
            buckets=_WORKER_DURATION_BUCKETS,
            registry=registry,
        ),
        worker_subprocess_count=Gauge(
            WORKER_SUBPROCESS_COUNT,
            "Current discovery worker subprocess count.",
            registry=registry,
        ),
        egp_request_total=Counter(
            EGP_REQUEST_TOTAL,
            "Requests made to e-GP endpoints.",
            ("outcome",),
            registry=registry,
        ),
        rate_limiter_wait_seconds=Histogram(
            RATE_LIMITER_WAIT_SECONDS,
            "Seconds spent waiting for the host-level e-GP rate limiter.",
            buckets=_REQUEST_DURATION_BUCKETS,
            registry=registry,
        ),
        project_upsert_conflicts=Counter(
            PROJECT_UPSERT_CONFLICTS_TOTAL,
            "Project upsert conflicts by outcome.",
            ("outcome",),
            registry=registry,
        ),
        document_upsert_conflicts=Counter(
            DOCUMENT_UPSERT_CONFLICTS_TOTAL,
            "Document upsert conflicts by outcome.",
            ("outcome",),
            registry=registry,
        ),
        discovery_queue_depth=Gauge(
            DISCOVERY_QUEUE_DEPTH,
            "Pending discovery queue depth.",
            registry=registry,
        ),
        discovery_dispatch_total=Counter(
            DISCOVERY_DISPATCH_TOTAL,
            "Discovery jobs dispatched by outcome.",
            ("outcome",),
            registry=registry,
        ),
        discovery_inflight_runs=Gauge(
            DISCOVERY_INFLIGHT_RUNS,
            "Discovery runs currently in flight.",
            registry=registry,
        ),
    )
    return _metrics


def get_metrics_registry() -> CollectorRegistry:
    """Return the process-local Prometheus registry."""

    return initialize_metrics().registry


def reset_metrics_for_tests() -> None:
    """Reset the process-local registry for deterministic unit tests."""

    global _metrics
    _metrics = None
    initialize_metrics()


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Serialize the process-local registry in Prometheus text format."""

    return generate_latest(get_metrics_registry()), CONTENT_TYPE


def observe_api_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record one API request with intentionally low-cardinality labels."""

    metrics = initialize_metrics()
    status_class = f"{max(0, int(status_code)) // 100}xx"
    labels = {
        "method": method.upper(),
        "path": _normalize_label(path),
        "status_class": status_class,
    }
    metrics.api_http_requests.labels(**labels).inc()
    metrics.api_http_request_duration.labels(**labels).observe(
        max(0.0, duration_seconds)
    )


def record_worker_job(
    *,
    command: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    """Record one worker command execution."""

    metrics = initialize_metrics()
    labels = {
        "command": _normalize_worker_command(command),
        "outcome": _normalize_label(outcome or "unknown"),
    }
    metrics.worker_jobs.labels(**labels).inc()
    metrics.worker_job_duration.labels(**labels).observe(max(0.0, duration_seconds))


def record_egp_request(*, outcome: str) -> None:
    """Record one outbound e-GP interaction with a low-cardinality outcome."""

    metrics = initialize_metrics()
    metrics.egp_request_total.labels(
        outcome=_normalize_label(outcome or "unknown")
    ).inc()


def observe_rate_limiter_wait(*, duration_seconds: float) -> None:
    """Record seconds spent waiting for the host-level e-GP rate limiter."""

    metrics = initialize_metrics()
    metrics.rate_limiter_wait_seconds.observe(max(0.0, duration_seconds))


def record_document_upsert_conflict(*, outcome: str) -> None:
    """Record one document upsert conflict with a low-cardinality outcome label."""

    metrics = initialize_metrics()
    metrics.document_upsert_conflicts.labels(
        outcome=_normalize_label(outcome or "unknown")
    ).inc()


def instrument_fastapi_app(app: "FastAPI") -> None:
    """Register Prometheus middleware and the `/metrics` scrape endpoint."""

    from fastapi import Response

    if getattr(app.state, "egp_metrics_instrumented", False):
        return
    initialize_metrics()

    @app.middleware("http")
    async def prometheus_http_metrics(request: Request, call_next):
        started_at = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            status_code = response.status_code if response is not None else 500
            observe_api_request(
                method=request.method,
                path=_request_metric_path(request),
                status_code=status_code,
                duration_seconds=time.perf_counter() - started_at,
            )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        payload, content_type = render_prometheus_metrics()
        return Response(content=payload, headers={"Content-Type": content_type})

    app.state.egp_metrics_instrumented = True


def _request_metric_path(request: "Request") -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return str(route_path or "unmatched")


def _normalize_worker_command(command: str) -> str:
    normalized = _normalize_label(command)
    return normalized if normalized in _KNOWN_WORKER_COMMANDS else "unsupported"


def _normalize_label(value: str) -> str:
    normalized = str(value or "unknown").strip()
    return normalized if normalized else "unknown"
