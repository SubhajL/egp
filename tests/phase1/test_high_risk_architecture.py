from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from egp_api.main import create_app
from egp_db.artifact_store import S3ArtifactStore, SupabaseArtifactStore
from egp_db.repositories.project_repo import (
    PROJECTS_TABLE,
    SqlProjectRepository,
    build_project_upsert_record,
)
from egp_db.repositories.run_repo import SqlRunRepository
from egp_shared_types.enums import ProcurementType, ProjectState
from egp_worker.workflows.discover import run_discover_workflow

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "99999999-9999-9999-9999-999999999999"
JWT_SECRET = "phase1-test-secret"
REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeS3Client:
    def __init__(self) -> None:
        self.delete_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs):
        return kwargs

    def delete_object(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {}

    def generate_presigned_url(self, client_method: str, *, Params, ExpiresIn: int):
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}"


def test_worker_boundary_imports_no_api_services() -> None:
    worker_files = sorted((REPO_ROOT / "apps/worker/src").rglob("*.py"))
    forbidden_imports: list[str] = []
    for path in worker_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "egp_api.services"
            ):
                forbidden_imports.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("egp_api.services"):
                        forbidden_imports.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

    assert forbidden_imports == []


class FakeSupabaseBucket:
    def __init__(self) -> None:
        self.upload_calls: list[dict[str, object]] = []

    def upload(self, path: str, file, file_options: dict[str, object] | None = None):
        self.upload_calls.append(
            {
                "path": path,
                "file": file,
                "file_options": file_options or {},
            }
        )
        return {"path": path}

    def remove(self, paths: list[str]):
        return {"paths": paths}

    def create_signed_url(
        self, path: str, expires_in: int, options: dict[str, object] | None = None
    ):
        return {
            "signedURL": f"https://project.supabase.co/storage/v1/object/sign/egp-documents/{path}"
        }


class FakeSupabaseStorageClient:
    def __init__(self) -> None:
        self.bucket = FakeSupabaseBucket()

    def from_(self, bucket_name: str) -> FakeSupabaseBucket:
        return self.bucket


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.storage = FakeSupabaseStorageClient()


def _auth_headers(tenant_id: str = TENANT_ID) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "user-123",
            "tenant_id": tenant_id,
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def test_create_app_shares_one_engine_across_repositories(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"

    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        jwt_secret=JWT_SECRET,
    )

    assert app.state.project_repository._engine is app.state.run_repository._engine
    assert app.state.project_repository._engine is app.state.document_repository._engine


def test_create_app_exposes_expected_bootstrap_state(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"

    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        jwt_secret=JWT_SECRET,
    )

    for state_name in (
        "admin_repository",
        "auth_repository",
        "billing_repository",
        "document_repository",
        "project_repository",
        "profile_repository",
        "run_repository",
        "auth_service",
        "billing_service",
        "document_ingest_service",
        "project_ingest_service",
        "run_service",
        "rules_service",
        "discovery_dispatcher",
        "discover_spawner",
        "discovery_dispatch_processor",
        "session_cookie_name",
    ):
        assert hasattr(app.state, state_name), state_name

    assert (
        app.state.discovery_dispatch_processor.dispatcher
        is app.state.discovery_dispatcher
    )


def test_create_app_preserves_background_processor_flags_for_sqlite(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"

    app = create_app(
        artifact_root=tmp_path,
        database_url=database_url,
        jwt_secret=JWT_SECRET,
    )

    assert app.state.webhook_delivery_processor_enabled is False
    assert app.state.discovery_dispatch_processor_enabled is False


def test_create_app_requires_database_url(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        create_app(
            artifact_root=tmp_path,
            database_url="",
            auth_required=False,
        )


def test_projects_endpoint_requires_auth_and_uses_jwt_tenant(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    client = TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            jwt_secret=JWT_SECRET,
        )
    )
    repository = client.app.state.project_repository
    project = repository.upsert_project(
        build_project_upsert_record(
            tenant_id=TENANT_ID,
            project_number="EGP-2026-9001",
            search_name="secure project",
            detail_name="secure project",
            project_name="secure project",
            organization_name="กรมตัวอย่าง",
            proposal_submission_date="2026-05-01",
            budget_amount="1000.00",
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
        ),
        source_status_text="ประกาศเชิญชวน",
    )

    unauthenticated = client.get("/v1/projects", params={"tenant_id": TENANT_ID})
    authenticated = client.get(
        f"/v1/projects/{project.id}",
        params={"tenant_id": TENANT_ID},
        headers=_auth_headers(TENANT_ID),
    )
    forbidden = client.get(
        f"/v1/projects/{project.id}",
        params={"tenant_id": OTHER_TENANT_ID},
        headers=_auth_headers(TENANT_ID),
    )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert authenticated.json()["project"]["tenant_id"] == TENANT_ID
    assert forbidden.status_code == 403


def test_discover_workflow_accepts_injected_repositories(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase1.sqlite3'}"
    project_repository = SqlProjectRepository(
        database_url=database_url, bootstrap_schema=True
    )
    run_repository = SqlRunRepository(database_url=database_url, bootstrap_schema=False)

    result = run_discover_workflow(
        tenant_id=TENANT_ID,
        keyword="โรงพยาบาล",
        discovered_projects=[
            {
                "project_number": "EGP-2026-3001",
                "search_name": "ระบบข้อมูลกลาง",
                "detail_name": "โครงการระบบข้อมูลกลาง",
                "project_name": "โครงการระบบข้อมูลกลาง",
                "organization_name": "กรมตัวอย่าง",
                "proposal_submission_date": "2026-05-01",
                "budget_amount": "1500000.00",
                "procurement_type": ProcurementType.SERVICES.value,
                "project_state": ProjectState.OPEN_INVITATION.value,
                "source_status_text": "ประกาศเชิญชวน",
            }
        ],
        project_repository=project_repository,
        run_repository=run_repository,
    )

    project_page = project_repository.list_projects(tenant_id=TENANT_ID)
    run_detail = run_repository.get_run_detail(
        tenant_id=TENANT_ID, run_id=result.run.run.id
    )

    assert len(project_page.items) == 1
    assert run_detail is not None
    assert run_detail.tasks[0].task_type == "discover"


def test_s3_delete_uses_prefixed_key() -> None:
    client = FakeS3Client()
    store = S3ArtifactStore(bucket="egp-documents", prefix="dev/raw", client=client)

    stored_key = store.put_bytes(key="tenant/project/file.pdf", data=b"data")
    store.delete("tenant/project/file.pdf")
    store.delete(stored_key)

    assert stored_key == "dev/raw/tenant/project/file.pdf"
    assert client.delete_calls == [
        {"Bucket": "egp-documents", "Key": stored_key},
        {"Bucket": "egp-documents", "Key": stored_key},
    ]


def test_supabase_artifact_store_uses_boolean_upsert_flag() -> None:
    client = FakeSupabaseClient()
    store = SupabaseArtifactStore(
        project_url="https://project.supabase.co",
        service_role_key="service-role-key",
        bucket="egp-documents",
        prefix="dev/raw",
        client=client,
    )

    store.put_bytes(
        key="tenant/project/file.pdf", data=b"data", content_type="application/pdf"
    )

    assert client.storage.bucket.upload_calls[0]["file_options"]["upsert"] is False


def test_project_repository_tracks_migration_fields_in_sqlalchemy_model() -> None:
    columns = set(PROJECTS_TABLE.c.keys())

    assert {
        "currency",
        "invitation_announcement_date",
        "winner_announced_at",
        "contract_signed_at",
        "last_run_id",
        "is_active",
    }.issubset(columns)
