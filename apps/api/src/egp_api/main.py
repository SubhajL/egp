"""Packaged FastAPI application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from egp_api.auth import authenticate_request
from egp_api.config import (
    get_auth_required,
    get_artifact_bucket,
    get_artifact_prefix,
    get_artifact_root,
    get_artifact_storage_backend,
    get_database_url,
    get_jwt_secret,
    get_supabase_service_role_key,
    get_supabase_url,
)
from egp_api.routes.dashboard import router as dashboard_router
from egp_api.routes.documents import router as documents_router
from egp_api.routes.exports import router as exports_router
from egp_api.routes.projects import router as projects_router
from egp_api.routes.runs import router as runs_router
from egp_api.services.dashboard_service import DashboardService
from egp_api.services.document_ingest_service import DocumentIngestService
from egp_api.services.export_service import ExportService
from egp_api.services.project_service import ProjectService
from egp_api.services.run_service import RunService
from egp_db.connection import create_shared_engine
from egp_db.repositories.document_repo import create_document_repository
from egp_db.repositories.project_repo import create_project_repository
from egp_db.repositories.run_repo import create_run_repository


def create_app(
    *,
    artifact_root: Path | None = None,
    database_url: str | None = None,
    artifact_storage_backend: str | None = None,
    artifact_bucket: str | None = None,
    artifact_prefix: str | None = None,
    s3_client=None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_client=None,
    auth_required: bool | None = None,
    jwt_secret: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="e-GP Intelligence Platform",
        version="0.1.0",
        description="Thailand public procurement monitoring API",
    )

    resolved_artifact_root = get_artifact_root(artifact_root)
    resolved_database_url = get_database_url(database_url, artifact_root=resolved_artifact_root)
    resolved_auth_required = get_auth_required(auth_required)
    resolved_jwt_secret = get_jwt_secret(jwt_secret)
    shared_engine = create_shared_engine(resolved_database_url)
    repository = create_document_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
        storage_backend=get_artifact_storage_backend(artifact_storage_backend),
        artifact_root=resolved_artifact_root,
        s3_bucket=get_artifact_bucket(artifact_bucket),
        s3_prefix=get_artifact_prefix(artifact_prefix),
        s3_client=s3_client,
        supabase_url=get_supabase_url(supabase_url),
        supabase_service_role_key=get_supabase_service_role_key(supabase_service_role_key),
        supabase_client=supabase_client,
    )
    project_repository = create_project_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    run_repository = create_run_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    app.state.db_engine = shared_engine
    app.state.document_repository = repository
    app.state.document_ingest_service = DocumentIngestService(repository)
    app.state.project_repository = project_repository
    app.state.project_service = ProjectService(project_repository)
    app.state.run_repository = run_repository
    app.state.run_service = RunService(run_repository)
    app.state.dashboard_service = DashboardService(project_repository, run_repository)
    app.state.export_service = ExportService(project_repository)
    app.state.auth_required = resolved_auth_required
    app.state.jwt_secret = resolved_jwt_secret

    @app.middleware("http")
    async def auth_middleware(request, call_next):
        if request.url.path in {
            "/health",
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        }:
            request.state.auth_context = None
            return await call_next(request)

        if not app.state.auth_required:
            request.state.auth_context = None
            return await call_next(request)

        if not app.state.jwt_secret:
            return JSONResponse(status_code=503, content={"detail": "server auth not configured"})

        try:
            request.state.auth_context = authenticate_request(
                authorization_header=request.headers.get("authorization"),
                jwt_secret=app.state.jwt_secret,
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "invalid bearer token")
            return JSONResponse(status_code=status_code, content={"detail": detail})
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(dashboard_router)
    app.include_router(documents_router)
    app.include_router(exports_router)
    app.include_router(projects_router)
    app.include_router(runs_router)
    return app


app = create_app()
