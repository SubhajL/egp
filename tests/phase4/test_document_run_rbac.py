from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import text

from tests.support.app_factory import create_test_app as create_app
from egp_db.repositories.project_repo import build_project_upsert_record
from egp_shared_types.enums import ProcurementType, ProjectState


TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
JWT_SECRET = "document-run-rbac-secret-at-least-32-bytes"
WORKER_TOKEN = "document-run-worker-token"


def _client(tmp_path: Path) -> TestClient:
    artifact_root = tmp_path / "artifacts"
    app = create_app(
        artifact_root=artifact_root,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'rbac.sqlite3'}",
        auth_required=True,
        jwt_secret=JWT_SECRET,
        internal_worker_token=WORKER_TOKEN,
    )
    app.state.rbac_test_artifact_root = artifact_root
    return TestClient(app)


def _auth_headers(
    *, tenant_id: str = TENANT_ID, role: str = "analyst"
) -> dict[str, str]:
    token = jwt.encode(
        {"sub": f"{role}-subject", "tenant_id": tenant_id, "role": role},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_tenant(client: TestClient, tenant_id: str, slug: str) -> None:
    now = datetime.now(UTC).isoformat()
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (id, name, slug, plan_code, is_active, created_at, updated_at)
                VALUES (:id, :name, :slug, 'monthly_membership', 1, :now, :now)
                """
            ),
            {"id": tenant_id, "name": f"Tenant {slug}", "slug": slug, "now": now},
        )


def _seed_subscription(client: TestClient, tenant_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    today = date.today()
    start = (today - timedelta(days=1)).isoformat()
    end = (today + timedelta(days=29)).isoformat()
    billing_id = str(uuid4())
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO billing_records (
                    id, tenant_id, record_number, plan_code, status, billing_period_start,
                    billing_period_end, currency, amount_due, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :number, 'monthly_membership', 'paid', :start, :end,
                    'THB', '1500.00', :now, :now
                )
                """
            ),
            {
                "id": billing_id,
                "tenant_id": tenant_id,
                "number": f"INV-{billing_id[:8]}",
                "start": start,
                "end": end,
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO billing_subscriptions (
                    id, tenant_id, billing_record_id, plan_code, status, billing_period_start,
                    billing_period_end, keyword_limit, activated_at, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :billing_id, 'monthly_membership', 'active', :start, :end,
                    5, :now, :now, :now
                )
                """
            ),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "billing_id": billing_id,
                "start": start,
                "end": end,
                "now": now,
            },
        )


def _seed_profile_keyword(client: TestClient, tenant_id: str) -> str:
    now = datetime.now(UTC).isoformat()
    profile_id = str(uuid4())
    with client.app.state.db_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO crawl_profiles (
                    id, tenant_id, name, profile_type, is_active, max_pages_per_keyword,
                    close_consulting_after_days, close_stale_after_days, created_at, updated_at
                ) VALUES (:id, :tenant_id, 'RBAC', 'tor', 1, 15, 30, 45, :now, :now)
                """
            ),
            {"id": profile_id, "tenant_id": tenant_id, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO crawl_profile_keywords (id, profile_id, keyword, position, created_at)
                VALUES (:id, :profile_id, 'rbac', 1, :now)
                """
            ),
            {"id": str(uuid4()), "profile_id": profile_id, "now": now},
        )
    return profile_id


def _seed_project(client: TestClient, tenant_id: str, suffix: str) -> str:
    project = client.app.state.project_repository.upsert_project(
        build_project_upsert_record(
            tenant_id=tenant_id,
            project_number=f"EGP-RBAC-{suffix}",
            search_name=f"RBAC {suffix}",
            detail_name=f"RBAC detail {suffix}",
            project_name=f"RBAC project {suffix}",
            organization_name="RBAC Department",
            proposal_submission_date="2026-08-30",
            budget_amount="100000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )
    return project.id


def _seed_base(client: TestClient) -> tuple[str, str]:
    _seed_tenant(client, TENANT_ID, "rbac-primary")
    _seed_tenant(client, OTHER_TENANT_ID, "rbac-other")
    _seed_subscription(client, TENANT_ID)
    _seed_profile_keyword(client, TENANT_ID)
    return (
        _seed_project(client, TENANT_ID, "PRIMARY"),
        _seed_project(client, OTHER_TENANT_ID, "OTHER"),
    )


def _ingest_payload(
    project_id: str, *, tenant_id: str | None = None
) -> dict[str, object]:
    return {
        **({"tenant_id": tenant_id} if tenant_id is not None else {}),
        "project_id": project_id,
        "file_name": "tor.pdf",
        "content_base64": base64.b64encode(b"rbac-tor-content").decode("ascii"),
        "source_label": "เอกสารประกวดราคา",
        "source_status_text": "ประกาศเชิญชวน",
    }


def _route_cases(
    project_id: str, run_id: str, review_id: str, document_id: str, diff_id: str
):
    missing_id = str(uuid4())
    return [
        ("POST", "/v1/documents/ingest", {}, _ingest_payload(project_id)),
        ("GET", f"/v1/documents/projects/{project_id}", {}, None),
        ("GET", f"/v1/documents/projects/{project_id}/diffs", {}, None),
        ("GET", f"/v1/documents/projects/{project_id}/reviews", {}, None),
        (
            "POST",
            f"/v1/documents/reviews/{review_id}/actions",
            {},
            {"action": "approve", "note": "rbac"},
        ),
        ("GET", f"/v1/documents/{document_id}/diff/{missing_id}", {}, None),
        ("GET", f"/v1/documents/{document_id}/download", {}, None),
        ("GET", f"/v1/documents/{document_id}/download-link", {}, None),
        ("POST", "/v1/runs", {}, {"trigger_type": "manual"}),
        ("POST", f"/v1/runs/{run_id}/tasks", {}, {"task_type": "update"}),
        ("POST", f"/v1/runs/{run_id}/finish", {}, {"status": "succeeded"}),
        ("GET", "/v1/runs", {}, None),
        ("GET", f"/v1/runs/{run_id}/log", {}, None),
    ]


def _request(
    client: TestClient,
    case: tuple[str, str, dict[str, str], dict[str, object] | None],
    *,
    headers: dict[str, str] | None = None,
):
    method, path, params, payload = case
    return client.request(method, path, params=params, json=payload, headers=headers)


def _seed_documents_and_run(client: TestClient, project_id: str) -> dict[str, str]:
    service = client.app.state.document_ingest_service
    first = service.ingest_document_bytes(
        tenant_id=TENANT_ID,
        project_id=project_id,
        file_name="tor-draft.pdf",
        file_bytes=b"draft tor",
        source_label="ร่างขอบเขตของงาน",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )
    second = service.ingest_document_bytes(
        tenant_id=TENANT_ID,
        project_id=project_id,
        file_name="tor-final.pdf",
        file_bytes=b"final changed tor",
        source_label="เอกสารประกวดราคา",
        source_status_text="ประกาศเชิญชวน",
    )
    assert second.diff_records
    reviews = service.list_document_reviews(tenant_id=TENANT_ID, project_id=project_id)
    assert reviews.reviews
    run_id = str(uuid4())
    log_path = (
        Path(client.app.state.rbac_test_artifact_root)
        / "tenants"
        / TENANT_ID
        / "runs"
        / run_id
        / "worker.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("rbac worker log\n", encoding="utf-8")
    run = client.app.state.run_repository.create_run(
        tenant_id=TENANT_ID,
        trigger_type="manual",
        run_id=run_id,
        summary_json={"worker_log_path": str(log_path)},
    )
    return {
        "document_id": first.document.id,
        "other_document_id": second.document.id,
        "diff_id": second.diff_records[0].id,
        "review_id": reviews.reviews[0].id,
        "run_id": run.id,
    }


def _count_rows(client: TestClient, tables: tuple[str, ...]) -> dict[str, int]:
    with client.app.state.db_engine.connect() as connection:
        return {
            table: int(
                connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            )
            for table in tables
        }


def _artifact_snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_every_document_and_run_route_rejects_missing_authentication(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    project_id, _ = _seed_base(client)
    seeded = _seed_documents_and_run(client, project_id)

    for case in _route_cases(
        project_id,
        seeded["run_id"],
        seeded["review_id"],
        seeded["document_id"],
        seeded["diff_id"],
    ):
        response = _request(client, case)
        assert response.status_code == 401, (case, response.text)
        assert response.json() == {"detail": "missing authentication"}


def test_reads_reject_unknown_role_and_allow_viewer(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id, _ = _seed_base(client)
    seeded = _seed_documents_and_run(client, project_id)
    reads = [
        ("GET", f"/v1/documents/projects/{project_id}", {}, None),
        ("GET", f"/v1/documents/projects/{project_id}/diffs", {}, None),
        ("GET", f"/v1/documents/projects/{project_id}/reviews", {}, None),
        (
            "GET",
            f"/v1/documents/{seeded['document_id']}/diff/{seeded['other_document_id']}",
            {},
            None,
        ),
        ("GET", f"/v1/documents/{seeded['document_id']}/download", {}, None),
        ("GET", f"/v1/documents/{seeded['document_id']}/download-link", {}, None),
        ("GET", "/v1/runs", {}, None),
        ("GET", f"/v1/runs/{seeded['run_id']}/log", {}, None),
    ]

    for case in reads:
        denied = _request(client, case, headers=_auth_headers(role="unknown-role"))
        allowed = _request(client, case, headers=_auth_headers(role="viewer"))
        assert denied.status_code == 403, (case, denied.text)
        assert denied.json() == {"detail": "authenticated role required"}
        assert allowed.status_code == 200, (case, allowed.text)


def test_mutations_reject_viewer_and_allow_analyst(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id, _ = _seed_base(client)
    seeded = _seed_documents_and_run(client, project_id)
    viewer_cases = [
        ("POST", "/v1/documents/ingest", {}, _ingest_payload(project_id)),
        (
            "POST",
            f"/v1/documents/reviews/{seeded['review_id']}/actions",
            {},
            {"action": "approve"},
        ),
        ("POST", "/v1/runs", {}, {"trigger_type": "manual"}),
        (
            "POST",
            f"/v1/runs/{seeded['run_id']}/tasks",
            {},
            {"task_type": "update", "project_id": project_id},
        ),
        ("POST", f"/v1/runs/{seeded['run_id']}/finish", {}, {"status": "succeeded"}),
    ]
    for case in viewer_cases:
        denied = _request(client, case, headers=_auth_headers(role="viewer"))
        assert denied.status_code == 403, (case, denied.text)
        assert denied.json() == {"detail": "run operator role required"}

    analyst_ingest = client.post(
        "/v1/documents/ingest",
        headers=_auth_headers(),
        json={**_ingest_payload(project_id), "file_name": "analyst.pdf"},
    )
    analyst_run = client.post(
        "/v1/runs", headers=_auth_headers(), json={"trigger_type": "manual"}
    )
    analyst_task = client.post(
        f"/v1/runs/{analyst_run.json()['run']['id']}/tasks",
        headers=_auth_headers(),
        json={"task_type": "update", "project_id": project_id},
    )
    analyst_finish = client.post(
        f"/v1/runs/{analyst_run.json()['run']['id']}/finish",
        headers=_auth_headers(),
        json={"status": "succeeded"},
    )
    assert analyst_ingest.status_code == 201
    assert analyst_run.status_code == 201
    assert analyst_task.status_code == 201
    assert analyst_finish.status_code == 200


@pytest.mark.parametrize("role", ["owner", "admin", "support", "analyst"])
def test_each_canonical_operator_role_can_read_and_create_runs(
    tmp_path: Path, role: str
) -> None:
    client = _client(tmp_path)
    _seed_base(client)

    read = client.get("/v1/runs", headers=_auth_headers(role=role))
    mutation = client.post(
        "/v1/runs",
        headers=_auth_headers(role=role),
        json={"trigger_type": "manual"},
    )

    assert read.status_code == 200
    assert mutation.status_code == 201


def test_every_route_rejects_explicit_tenant_mismatch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    project_id, _ = _seed_base(client)
    seeded = _seed_documents_and_run(client, project_id)
    cases = _route_cases(
        project_id,
        seeded["run_id"],
        seeded["review_id"],
        seeded["document_id"],
        seeded["diff_id"],
    )
    for method, path, _, payload in cases:
        if method == "POST" and path in {"/v1/documents/ingest", "/v1/runs"}:
            mismatched_payload = {**(payload or {}), "tenant_id": OTHER_TENANT_ID}
            case = (method, path, {}, mismatched_payload)
        elif method == "POST" and "/reviews/" in path:
            case = (method, path, {}, {**(payload or {}), "tenant_id": OTHER_TENANT_ID})
        else:
            case = (method, path, {"tenant_id": OTHER_TENANT_ID}, payload)
        response = _request(client, case, headers=_auth_headers())
        assert response.status_code == 403, (case, response.text)
        assert response.json() == {"detail": "tenant mismatch"}


def test_worker_token_does_not_authenticate_or_elevate_public_mutations(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    project_id, _ = _seed_base(client)
    cases = [
        ("POST", "/v1/documents/ingest", {}, _ingest_payload(project_id)),
        ("POST", "/v1/runs", {}, {"trigger_type": "manual"}),
    ]
    for case in cases:
        worker_only = _request(
            client, case, headers={"X-EGP-Worker-Token": WORKER_TOKEN}
        )
        viewer_plus_worker = _request(
            client,
            case,
            headers={
                **_auth_headers(role="viewer"),
                "X-EGP-Worker-Token": WORKER_TOKEN,
            },
        )
        assert worker_only.status_code == 401
        assert worker_only.json() == {"detail": "missing authentication"}
        assert viewer_plus_worker.status_code == 403
        assert viewer_plus_worker.json() == {"detail": "run operator role required"}


@pytest.mark.parametrize("project_kind", ["foreign", "missing"])
def test_document_ingest_rejects_unowned_project_without_side_effects(
    tmp_path: Path, project_kind: str
) -> None:
    client = _client(tmp_path)
    _, foreign_project_id = _seed_base(client)
    project_id = foreign_project_id if project_kind == "foreign" else str(uuid4())
    tables = (
        "documents",
        "document_diffs",
        "document_diff_reviews",
        "document_review_events",
        "audit_log_events",
    )
    before_rows = _count_rows(client, tables)
    artifact_root = Path(client.app.state.rbac_test_artifact_root)
    before_artifacts = _artifact_snapshot(artifact_root)

    response = client.post(
        "/v1/documents/ingest",
        headers=_auth_headers(),
        json=_ingest_payload(project_id),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "project not found"}
    assert _count_rows(client, tables) == before_rows
    assert _artifact_snapshot(artifact_root) == before_artifacts


@pytest.mark.parametrize("project_kind", ["foreign", "missing"])
def test_task_rejects_unowned_project_without_task_or_run_mutation(
    tmp_path: Path, project_kind: str
) -> None:
    client = _client(tmp_path)
    _, foreign_project_id = _seed_base(client)
    project_id = foreign_project_id if project_kind == "foreign" else str(uuid4())
    run = client.app.state.run_repository.create_run(
        tenant_id=TENANT_ID,
        trigger_type="manual",
        summary_json={"sentinel": "unchanged"},
    )
    before = client.app.state.run_repository.find_run_by_id(run.id)
    assert before is not None
    before_tasks = _count_rows(client, ("crawl_tasks",))

    response = client.post(
        f"/v1/runs/{run.id}/tasks",
        headers=_auth_headers(),
        json={"task_type": "update", "project_id": project_id},
    )

    after = client.app.state.run_repository.find_run_by_id(run.id)
    assert response.status_code == 404
    assert response.json() == {"detail": "project not found"}
    assert _count_rows(client, ("crawl_tasks",)) == before_tasks
    assert after == before


def test_document_ingest_maps_malformed_project_id_to_422_without_side_effects(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _seed_base(client)
    tables = ("documents", "audit_log_events")
    before_rows = _count_rows(client, tables)
    artifact_root = Path(client.app.state.rbac_test_artifact_root)
    before_artifacts = _artifact_snapshot(artifact_root)

    response = client.post(
        "/v1/documents/ingest",
        headers=_auth_headers(),
        json=_ingest_payload("not-a-uuid"),
    )

    assert response.status_code == 422
    assert _count_rows(client, tables) == before_rows
    assert _artifact_snapshot(artifact_root) == before_artifacts


@pytest.mark.parametrize("profile_kind", ["foreign", "missing"])
def test_run_creation_rejects_unowned_profile_without_side_effects(
    tmp_path: Path, profile_kind: str
) -> None:
    client = _client(tmp_path)
    _seed_base(client)
    foreign_profile_id = _seed_profile_keyword(client, OTHER_TENANT_ID)
    profile_id = foreign_profile_id if profile_kind == "foreign" else str(uuid4())
    before_runs = _count_rows(client, ("crawl_runs",))

    response = client.post(
        "/v1/runs",
        headers=_auth_headers(),
        json={"trigger_type": "manual", "profile_id": profile_id},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "profile not found"}
    assert _count_rows(client, ("crawl_runs",)) == before_runs


def test_run_creation_maps_malformed_profile_id_to_422_without_side_effects(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _seed_base(client)
    before_runs = _count_rows(client, ("crawl_runs",))

    response = client.post(
        "/v1/runs",
        headers=_auth_headers(),
        json={"trigger_type": "manual", "profile_id": "not-a-uuid"},
    )

    assert response.status_code == 422
    assert _count_rows(client, ("crawl_runs",)) == before_runs


def test_task_maps_malformed_project_id_to_422_without_side_effects(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _seed_base(client)
    run = client.app.state.run_repository.create_run(
        tenant_id=TENANT_ID,
        trigger_type="manual",
        summary_json={"sentinel": "unchanged"},
    )
    before = client.app.state.run_repository.find_run_by_id(run.id)
    before_tasks = _count_rows(client, ("crawl_tasks",))

    response = client.post(
        f"/v1/runs/{run.id}/tasks",
        headers=_auth_headers(),
        json={"task_type": "update", "project_id": "not-a-uuid"},
    )

    assert response.status_code == 422
    assert _count_rows(client, ("crawl_tasks",)) == before_tasks
    assert client.app.state.run_repository.find_run_by_id(run.id) == before


@pytest.mark.parametrize("operation", ["task", "finish", "log"])
def test_missing_and_foreign_run_ids_are_indistinguishable(
    tmp_path: Path, operation: str
) -> None:
    client = _client(tmp_path)
    _seed_base(client)
    foreign_run = client.app.state.run_repository.create_run(
        tenant_id=OTHER_TENANT_ID,
        trigger_type="manual",
        summary_json={"sentinel": "foreign"},
    )
    missing_run_id = str(uuid4())

    def request(run_id: str):
        if operation == "task":
            return client.post(
                f"/v1/runs/{run_id}/tasks",
                headers=_auth_headers(),
                json={"task_type": "update"},
            )
        if operation == "finish":
            return client.post(
                f"/v1/runs/{run_id}/finish",
                headers=_auth_headers(),
                json={"status": "succeeded"},
            )
        return client.get(f"/v1/runs/{run_id}/log", headers=_auth_headers())

    before = client.app.state.run_repository.find_run_by_id(foreign_run.id)
    missing = request(missing_run_id)
    foreign = request(foreign_run.id)
    after = client.app.state.run_repository.find_run_by_id(foreign_run.id)

    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json() == {"detail": "run not found"}
    assert after == before
