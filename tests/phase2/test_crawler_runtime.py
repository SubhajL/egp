from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt

from egp_api.main import create_app
from egp_api.services.crawler_runtime_reporter import CrawlerRuntimeReporter
from egp_crawler_core.recovery_policy import evaluate_recovery_decision
from egp_db.repositories.crawler_runtime_repo import create_crawler_runtime_repository
from egp_shared_types.enums import CrawlerBlockerCode, DiscoveryFailureCode


def _auth_headers(*, role: str) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "runtime-user",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "role": role,
        },
        "runtime-jwt-secret",
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_internal_heartbeat_requires_worker_token(tmp_path) -> None:
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=f"sqlite+pysqlite:///{tmp_path / 'runtime-auth.sqlite3'}",
            auth_required=False,
            internal_worker_token="runtime-secret",
            background_runtime_mode="external",
        )
    )
    payload = {
        "agent_id": "mac-crawler-1",
        "runtime_mode": "external",
        "watcher_status": "running",
        "database_status": "connected",
        "profile_status": "ready",
        "circuit_state": "closed",
    }

    missing = client.post("/internal/worker/crawler-runtime/heartbeat", json=payload)
    invalid = client.post(
        "/internal/worker/crawler-runtime/heartbeat",
        headers={"X-EGP-Worker-Token": "wrong"},
        json=payload,
    )
    accepted = client.post(
        "/internal/worker/crawler-runtime/heartbeat",
        headers={"X-EGP-Worker-Token": "runtime-secret"},
        json=payload,
    )

    assert missing.status_code == 401
    assert invalid.status_code == 403
    assert accepted.status_code == 202
    assert accepted.json()["heartbeat_status"] == "online"
    runtime = client.get("/v1/rules/crawler-runtime")
    assert runtime.status_code == 200
    assert runtime.json()["agent_id"] == "mac-crawler-1"
    assert runtime.json()["heartbeat_status"] == "online"


def test_heartbeat_status_becomes_offline_when_stale(tmp_path) -> None:
    repository = create_crawler_runtime_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'runtime-stale.sqlite3'}",
    )
    reported_at = datetime(2026, 7, 23, 1, 0, tzinfo=UTC)
    repository.record_heartbeat(
        agent_id="mac-crawler-1",
        runtime_mode="external",
        watcher_status="running",
        database_status="connected",
        profile_status="ready",
        circuit_state="closed",
        reported_at=reported_at,
    )

    fresh = repository.get_freshest_status(
        runtime_mode="external",
        stale_after_seconds=90,
        now=reported_at + timedelta(seconds=89),
    )
    stale = repository.get_freshest_status(
        runtime_mode="external",
        stale_after_seconds=90,
        now=reported_at + timedelta(seconds=90, milliseconds=500),
    )

    assert fresh.heartbeat_status == "online"
    assert fresh.blocker_code is None
    assert stale.heartbeat_status == "offline"
    assert stale.blocker_code == "agent_offline"
    assert stale.heartbeat_age_seconds == 90


def test_runtime_status_requires_run_operator_role(tmp_path) -> None:
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=f"sqlite+pysqlite:///{tmp_path / 'runtime-role.sqlite3'}",
            auth_required=True,
            jwt_secret="runtime-jwt-secret",
            background_runtime_mode="embedded",
        )
    )

    viewer = client.get(
        "/v1/rules/crawler-runtime",
        headers=_auth_headers(role="viewer"),
    )
    analyst = client.get(
        "/v1/rules/crawler-runtime",
        headers=_auth_headers(role="analyst"),
    )

    assert viewer.status_code == 403
    assert analyst.status_code == 200
    assert analyst.json()["heartbeat_status"] == "embedded_ready"


def test_embedded_runtime_is_ready_without_external_heartbeat(tmp_path) -> None:
    repository = create_crawler_runtime_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'runtime-embedded.sqlite3'}",
    )

    status = repository.get_freshest_status(
        runtime_mode="embedded",
        stale_after_seconds=90,
    )

    assert status.heartbeat_status == "embedded_ready"
    assert status.database_status == "connected"
    assert status.blocker_code is None


class _RecordingResponse:
    def raise_for_status(self) -> None:
        return None


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def post(
        self,
        path: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
    ) -> _RecordingResponse:
        self.calls.append((path, json, headers))
        return _RecordingResponse()


class _FailingClient:
    def __init__(self) -> None:
        self.call_count = 0

    def post(self, *args: object, **kwargs: object) -> _RecordingResponse:
        del args, kwargs
        self.call_count += 1
        raise RuntimeError("control plane unavailable")


def test_reporter_posts_database_unreachable_without_database_access() -> None:
    client = _RecordingClient()
    reporter = CrawlerRuntimeReporter(
        base_url="https://api.example.com",
        worker_token="runtime-secret",
        agent_id="mac-crawler-1",
        client=client,
    )

    reported = reporter.report(
        watcher_status="error",
        database_status="unreachable",
        blocker_code="database_unreachable",
        profile_status="unknown",
        circuit_state="unknown",
    )

    assert reported is True
    assert client.calls == [
        (
            "/internal/worker/crawler-runtime/heartbeat",
            {
                "agent_id": "mac-crawler-1",
                "runtime_mode": "external",
                "watcher_status": "error",
                "database_status": "unreachable",
                "blocker_code": "database_unreachable",
                "profile_status": "unknown",
                "circuit_state": "unknown",
                "circuit_reset_at": None,
            },
            {
                "Content-Type": "application/json",
                "X-EGP-Worker-Token": "runtime-secret",
            },
        )
    ]


def test_reporter_rate_limits_repeated_delivery_failures() -> None:
    client = _FailingClient()
    reporter = CrawlerRuntimeReporter(
        base_url="https://api.example.com",
        worker_token="runtime-secret",
        agent_id="mac-crawler-1",
        client=client,
        minimum_interval_seconds=30,
    )
    payload = {
        "watcher_status": "running",
        "database_status": "connected",
        "profile_status": "ready",
        "circuit_state": "closed",
    }

    assert reporter.report(**payload) is False
    assert reporter.report(**payload) is False
    assert client.call_count == 1


def test_reporter_rate_limits_changed_payloads_after_delivery_failure() -> None:
    client = _FailingClient()
    reporter = CrawlerRuntimeReporter(
        base_url="https://api.example.com",
        worker_token="runtime-secret",
        agent_id="mac-crawler-1",
        client=client,
        minimum_interval_seconds=30,
    )

    assert reporter.report(
        watcher_status="running",
        database_status="connected",
        profile_status="ready",
        circuit_state="closed",
    ) is False
    assert reporter.report(
        watcher_status="running",
        database_status="connected",
        blocker_code=CrawlerBlockerCode.CIRCUIT_OPEN,
        profile_status="ready",
        circuit_state="open",
    ) is False
    assert client.call_count == 1


def test_two_heterogeneous_keyword_failures_do_not_stop_batch() -> None:
    decision = evaluate_recovery_decision(
        is_terminal=False,
        correlation_matches=True,
        runtime_blocker=None,
        job_failure_codes=(
            DiscoveryFailureCode.KEYWORD_NO_RESULTS,
            DiscoveryFailureCode.PROJECT_DETAIL_INVALID,
        ),
    )

    assert decision.action == "continue"
    assert decision.code == "jobs_retrying"


def test_terminal_request_completes_even_when_runtime_is_offline() -> None:
    decision = evaluate_recovery_decision(
        is_terminal=True,
        correlation_matches=True,
        runtime_blocker=CrawlerBlockerCode.AGENT_OFFLINE,
        job_failure_codes=(),
    )

    assert decision.action == "complete"
    assert decision.code == "request_complete"
    assert decision.blocker_code is None


def test_shared_runtime_blocker_and_correlation_mismatch_stop_batch() -> None:
    circuit = evaluate_recovery_decision(
        is_terminal=False,
        correlation_matches=True,
        runtime_blocker=CrawlerBlockerCode.CIRCUIT_OPEN,
        job_failure_codes=(),
    )
    mismatch = evaluate_recovery_decision(
        is_terminal=False,
        correlation_matches=False,
        runtime_blocker=None,
        job_failure_codes=(),
    )

    assert circuit.action == "stop"
    assert circuit.code == "circuit_open"
    assert mismatch.action == "stop"
    assert mismatch.code == "correlation_mismatch"
