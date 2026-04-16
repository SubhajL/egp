"""Worker-side document ingestion helpers."""

from __future__ import annotations

import os
from pathlib import Path

from egp_db.google_drive import (
    GoogleDriveClient,
    GoogleDriveOAuthConfig,
    normalize_google_drive_scopes,
)
from egp_db.onedrive import (
    OneDriveClient,
    OneDriveOAuthConfig,
    normalize_onedrive_scopes,
)
from egp_db.repositories.admin_repo import create_admin_repository
from egp_db.repositories.document_repo import (
    SqlDocumentRepository,
    StoreDocumentResult,
    create_artifact_store,
    create_document_repository,
)
from egp_db.storage_credentials import StorageCredentialCipher
from egp_db.tenant_storage_resolver import TenantArtifactStoreResolver


def _google_drive_config_from_env() -> GoogleDriveOAuthConfig | None:
    client_id = os.getenv("EGP_GOOGLE_DRIVE_CLIENT_ID", "").strip()
    client_secret = os.getenv("EGP_GOOGLE_DRIVE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("EGP_GOOGLE_DRIVE_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        return None
    raw_scopes = os.getenv("EGP_GOOGLE_DRIVE_SCOPES", "").strip()
    scopes = tuple(scope.strip() for scope in raw_scopes.split(",") if scope.strip())
    return GoogleDriveOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=normalize_google_drive_scopes(scopes),
    )


def _onedrive_config_from_env() -> OneDriveOAuthConfig | None:
    client_id = os.getenv("EGP_ONEDRIVE_CLIENT_ID", "").strip()
    client_secret = os.getenv("EGP_ONEDRIVE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("EGP_ONEDRIVE_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        return None
    raw_scopes = os.getenv("EGP_ONEDRIVE_SCOPES", "").strip()
    scopes = tuple(scope.strip() for scope in raw_scopes.split(",") if scope.strip())
    return OneDriveOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=normalize_onedrive_scopes(scopes),
    )


def ingest_document_artifact(
    *,
    artifact_root: Path | str,
    database_url: str | None = None,
    artifact_storage_backend: str = "local",
    artifact_bucket: str | None = None,
    artifact_prefix: str = "",
    s3_client=None,
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    supabase_client=None,
    storage_credentials_secret: str | None = None,
    google_drive_oauth_config: GoogleDriveOAuthConfig | None = None,
    google_drive_client=None,
    onedrive_oauth_config: OneDriveOAuthConfig | None = None,
    onedrive_client=None,
    repository: SqlDocumentRepository | None = None,
    tenant_id: str,
    project_id: str,
    file_name: str,
    file_bytes: bytes,
    source_label: str,
    source_status_text: str,
    source_page_text: str = "",
    project_state: str | None = None,
) -> StoreDocumentResult:
    resolved_artifact_root = Path(artifact_root)
    if repository is None:
        resolved_database_url = (
            database_url
            or f"sqlite+pysqlite:///{resolved_artifact_root / 'document_metadata.sqlite3'}"
        )
        managed_artifact_store = create_artifact_store(
            storage_backend=artifact_storage_backend,
            artifact_root=resolved_artifact_root,
            s3_bucket=artifact_bucket,
            s3_prefix=artifact_prefix,
            s3_client=s3_client,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            supabase_client=supabase_client,
        )
        resolved_storage_credentials_secret = (
            storage_credentials_secret
            if storage_credentials_secret is not None
            else os.getenv("EGP_STORAGE_CREDENTIALS_SECRET", "").strip() or None
        )
        credential_cipher = (
            StorageCredentialCipher(resolved_storage_credentials_secret)
            if resolved_storage_credentials_secret is not None
            else None
        )
        admin_repository = create_admin_repository(database_url=resolved_database_url)
        tenant_artifact_store_resolver = TenantArtifactStoreResolver(
            admin_repository=admin_repository,
            managed_artifact_store=managed_artifact_store,
            credential_cipher=credential_cipher,
            google_drive_oauth_config=google_drive_oauth_config or _google_drive_config_from_env(),
            google_drive_client=google_drive_client or GoogleDriveClient(),
            onedrive_oauth_config=onedrive_oauth_config or _onedrive_config_from_env(),
            onedrive_client=onedrive_client or OneDriveClient(),
        )
        repository = create_document_repository(
            database_url=resolved_database_url,
            storage_backend=artifact_storage_backend,
            artifact_root=resolved_artifact_root,
            s3_bucket=artifact_bucket,
            s3_prefix=artifact_prefix,
            s3_client=s3_client,
            supabase_url=supabase_url,
            supabase_service_role_key=supabase_service_role_key,
            supabase_client=supabase_client,
            artifact_store_resolver=tenant_artifact_store_resolver,
        )
    return repository.store_document(
        tenant_id=tenant_id,
        project_id=project_id,
        file_name=file_name,
        file_bytes=file_bytes,
        source_label=source_label,
        source_status_text=source_status_text,
        source_page_text=source_page_text,
        project_state=project_state,
    )
