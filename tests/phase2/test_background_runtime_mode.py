from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
import yaml

from egp_api.config import (
    get_background_runtime_mode,
    get_crawler_heartbeat_interval_seconds,
    get_crawler_heartbeat_stale_after_seconds,
    get_discovery_lease_heartbeat_seconds,
    get_discovery_lease_seconds,
    get_discovery_worker_count,
)
from egp_api.main import create_app
from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchRequest,
    DiscoveryPreDispatchResult,
)
from egp_db.connection import create_shared_engine
from egp_db.repositories.profile_repo import create_profile_repository


JWT_SECRET = "phase2-runtime-secret"


def test_get_background_runtime_mode_defaults_to_embedded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EGP_BACKGROUND_RUNTIME_MODE", raising=False)

    assert get_background_runtime_mode() == "embedded"


def test_get_background_runtime_mode_reads_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_BACKGROUND_RUNTIME_MODE", " external ")

    assert get_background_runtime_mode() == "external"


def test_get_background_runtime_mode_rejects_unknown_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_BACKGROUND_RUNTIME_MODE", "sidecar")

    with pytest.raises(RuntimeError, match="EGP_BACKGROUND_RUNTIME_MODE"):
        get_background_runtime_mode()


def test_get_discovery_worker_count_reads_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_WORKER_COUNT", " 3 ")

    assert get_discovery_worker_count() == 3


def test_get_discovery_worker_count_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_WORKER_COUNT", "0")

    with pytest.raises(RuntimeError, match="EGP_DISCOVERY_WORKER_COUNT"):
        get_discovery_worker_count()


def test_discovery_lease_configuration_reads_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_LEASE_SECONDS", " 90 ")
    monkeypatch.setenv("EGP_DISCOVERY_LEASE_HEARTBEAT_SECONDS", " 15 ")

    assert get_discovery_lease_seconds() == 90.0
    assert get_discovery_lease_heartbeat_seconds() == 15.0


def test_discovery_lease_configuration_requires_heartbeat_before_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_LEASE_SECONDS", "30")
    monkeypatch.setenv("EGP_DISCOVERY_LEASE_HEARTBEAT_SECONDS", "30")

    with pytest.raises(RuntimeError, match="must be less than EGP_DISCOVERY_LEASE_SECONDS"):
        get_discovery_lease_heartbeat_seconds(
            lease_seconds=get_discovery_lease_seconds()
        )


def test_crawler_runtime_heartbeat_configuration_reads_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_CRAWLER_HEARTBEAT_INTERVAL_SECONDS", "25")
    monkeypatch.setenv("EGP_CRAWLER_HEARTBEAT_STALE_AFTER_SECONDS", "75")

    assert get_crawler_heartbeat_interval_seconds() == 25.0
    assert get_crawler_heartbeat_stale_after_seconds() == 75.0


@pytest.mark.parametrize(
    "compose_name",
    ["docker-compose.yml", "docker-compose-localdev.yml"],
)
def test_discovery_executor_compose_wires_runtime_reporter(
    compose_name: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load(
        (repo_root / compose_name).read_text(encoding="utf-8")
    )
    environment = compose["services"]["discovery-executor"]["environment"]

    assert environment["EGP_INTERNAL_API_BASE_URL"] == "http://api:8000"
    assert "EGP_INTERNAL_WORKER_TOKEN" in environment
    assert "EGP_CRAWLER_AGENT_ID" in environment
    assert "EGP_CRAWLER_HEARTBEAT_INTERVAL_SECONDS" in environment


def test_create_app_external_background_mode_disables_api_background_work(
    tmp_path,
) -> None:
    app = create_app(
        artifact_root=tmp_path,
        database_url="postgresql://egp:egp_dev@localhost:5432/egp",
        jwt_secret=JWT_SECRET,
        payment_callback_secret="runtime-callback-secret",
        background_runtime_mode="external",
    )

    assert app.state.background_runtime_mode == "external"
    assert app.state.webhook_delivery_processor_enabled is False
    assert app.state.discovery_dispatch_processor_enabled is False
    assert app.state.discovery_dispatch_route_kick_enabled is False


def test_create_app_embedded_background_mode_preserves_database_defaults(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_DISCOVERY_WORKER_COUNT", "4")
    monkeypatch.setenv("EGP_DISCOVERY_LEASE_SECONDS", "120")
    monkeypatch.setenv("EGP_DISCOVERY_LEASE_HEARTBEAT_SECONDS", "20")

    app = create_app(
        artifact_root=tmp_path,
        database_url="postgresql://egp:egp_dev@localhost:5432/egp",
        jwt_secret=JWT_SECRET,
        payment_callback_secret="runtime-callback-secret",
        background_runtime_mode="embedded",
    )

    assert app.state.background_runtime_mode == "embedded"
    assert app.state.webhook_delivery_processor_enabled is True
    assert app.state.discovery_dispatch_processor_enabled is True
    assert app.state.discovery_dispatch_route_kick_enabled is True
    assert app.state.discovery_dispatch_processor.worker_count == 4
    assert app.state.discovery_dispatch_processor.lease_seconds == 120.0
    assert app.state.discovery_dispatch_processor.lease_heartbeat_seconds == 20.0


def test_create_app_embedded_dispatch_preserves_typed_preparation_result(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'embedded-dispatch.sqlite3'}"
    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        jwt_secret=JWT_SECRET,
        payment_callback_secret="runtime-callback-secret",
        background_runtime_mode="embedded",
    )
    dispatched: list[DiscoveryDispatchRequest] = []

    class TypedSpawner:
        def prepare_for_dispatch(self) -> DiscoveryPreDispatchResult:
            return DiscoveryPreDispatchResult.ready()

        def dispatch(self, request: DiscoveryDispatchRequest) -> None:
            dispatched.append(request)

    app.state.discover_spawner = TypedSpawner()
    engine = create_shared_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (
                    id, name, slug, plan_code, is_active, created_at, updated_at
                ) VALUES (
                    :id, 'Embedded', 'embedded', 'monthly_membership', 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"id": "11111111-1111-1111-1111-111111111111"},
        )
    profile = create_profile_repository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=False,
    ).create_profile(
        tenant_id="11111111-1111-1111-1111-111111111111",
        name="Embedded profile",
        profile_type="custom",
        max_pages_per_keyword=1,
        close_consulting_after_days=30,
        close_stale_after_days=45,
        keywords=["analytics"],
        is_active=True,
    )
    app.state.discovery_dispatch_processor.repository.create_discovery_job(
        tenant_id="11111111-1111-1111-1111-111111111111",
        profile_id=profile.profile.id,
        profile_type="custom",
        keyword="analytics",
    )

    result = app.state.discovery_dispatch_processor.process_pending(limit=1)

    assert result.processed_count == 1
    assert [request.keyword for request in dispatched] == ["analytics"]
