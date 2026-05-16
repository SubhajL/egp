from __future__ import annotations

import pytest

from egp_api.config import get_background_runtime_mode, get_discovery_worker_count
from egp_api.main import create_app


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
    assert app.state.discovery_dispatch_route_kick_enabled is False
    assert app.state.discovery_dispatch_processor.worker_count == 4
