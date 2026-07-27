from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from egp_api.main import create_app


WORKER_TOKEN = "phase1-worker-token"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"

INTERNAL_ROUTE_CASES = (
    (
        "/internal/worker/projects/discover",
        {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "keyword": "analytics",
            "project_name": "Worker auth contract",
            "organization_name": "กรมตัวอย่าง",
            "procurement_type": "services",
            "project_state": "open_invitation",
            "source_status_text": "ประกาศเชิญชวน",
        },
        {200, 201},
    ),
    (
        "/internal/worker/projects/close-check",
        {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "project_id": PROJECT_ID,
            "closed_reason": "winner_announced",
            "source_status_text": "ประกาศผู้ชนะ",
        },
        {404},
    ),
    (
        "/internal/worker/projects/status-update",
        {
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "project_id": PROJECT_ID,
            "project_state": "winner_announced",
            "source_status_text": "ประกาศผู้ชนะ",
        },
        {404},
    ),
    (
        "/internal/worker/crawler-runtime/heartbeat",
        {
            "agent_id": "phase1-worker",
            "runtime_mode": "external",
            "watcher_status": "running",
            "database_status": "connected",
            "profile_status": "ready",
            "circuit_state": "closed",
        },
        {202},
    ),
)


@pytest.mark.parametrize(("path", "payload", "accepted_statuses"), INTERNAL_ROUTE_CASES)
def test_internal_worker_routes_apply_worker_token_matrix(
    tmp_path: Path,
    path: str,
    payload: dict[str, object],
    accepted_statuses: set[int],
) -> None:
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=f"sqlite+pysqlite:///{tmp_path / 'internal-worker-auth.sqlite3'}",
            auth_required=True,
            jwt_secret="phase1-user-jwt-secret",
            internal_worker_token=WORKER_TOKEN,
            background_runtime_mode="external",
        )
    )

    missing = client.post(path, json=payload)
    invalid = client.post(
        path,
        headers={"X-EGP-Worker-Token": "wrong"},
        json=payload,
    )
    accepted = client.post(
        path,
        headers={"X-EGP-Worker-Token": WORKER_TOKEN},
        json=payload,
    )

    assert missing.status_code == 401
    assert missing.json() == {"detail": "missing internal worker token"}
    assert invalid.status_code == 403
    assert invalid.json() == {"detail": "invalid internal worker token"}
    assert accepted.status_code in accepted_statuses


def test_internal_worker_route_inventory_is_covered(tmp_path: Path) -> None:
    app = create_app(
        artifact_root=tmp_path,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'internal-worker-inventory.sqlite3'}",
        auth_required=True,
        jwt_secret="phase1-user-jwt-secret",
        internal_worker_token=WORKER_TOKEN,
        background_runtime_mode="external",
    )

    registered_paths = {
        route.path for route in app.routes if route.path.startswith("/internal/worker/")
    }
    covered_paths = {path for path, _, _ in INTERNAL_ROUTE_CASES}

    assert registered_paths == covered_paths
