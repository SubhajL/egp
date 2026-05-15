"""Repository and storage bootstrap for the API application."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from egp_api.config import (
    get_artifact_bucket,
    get_artifact_prefix,
    get_artifact_root,
    get_artifact_storage_backend,
    get_auth_required,
    get_database_url,
    get_google_drive_client_id,
    get_google_drive_client_secret,
    get_google_drive_redirect_uri,
    get_google_drive_scopes,
    get_internal_worker_token,
    get_jwt_secret,
    get_onedrive_client_id,
    get_onedrive_client_secret,
    get_onedrive_redirect_uri,
    get_onedrive_scopes,
    get_session_cookie_max_age_seconds,
    get_session_cookie_name,
    get_session_cookie_samesite,
    get_session_cookie_secure,
    get_storage_credentials_secret,
    get_supabase_service_role_key,
    get_supabase_url,
)
from egp_api.services.google_drive import (
    GoogleDriveClient,
    GoogleDriveOAuthConfig,
    normalize_google_drive_scopes,
)
from egp_api.services.onedrive import (
    OneDriveClient,
    OneDriveOAuthConfig,
    normalize_onedrive_scopes,
)
from egp_api.services.storage_credentials import StorageCredentialCipher
from egp_db.connection import create_shared_engine
from egp_db.repositories.audit_repo import create_audit_repository
from egp_db.repositories.admin_repo import create_admin_repository
from egp_db.repositories.auth_repo import create_auth_repository
from egp_db.repositories.billing_repo import create_billing_repository
from egp_db.repositories.discovery_job_repo import create_discovery_job_repository
from egp_db.repositories.document_repo import create_artifact_store, create_document_repository
from egp_db.repositories.notification_repo import create_notification_repository
from egp_db.repositories.profile_repo import create_profile_repository
from egp_db.repositories.project_repo import create_project_repository
from egp_db.repositories.run_repo import create_run_repository
from egp_db.repositories.support_repo import create_support_repository
from egp_db.tenant_storage_resolver import TenantArtifactStoreResolver


@dataclass(frozen=True, slots=True)
class RepositoryBundle:
    resolved_artifact_root: Path
    resolved_database_url: str
    resolved_auth_required: bool
    resolved_internal_worker_token: str | None
    resolved_jwt_secret: str
    resolved_storage_credentials_secret: str | None
    resolved_google_drive_oauth_config: GoogleDriveOAuthConfig | None
    resolved_google_drive_client: object
    resolved_onedrive_oauth_config: OneDriveOAuthConfig | None
    resolved_onedrive_client: object
    session_cookie_name: str
    session_cookie_max_age_seconds: int
    session_cookie_secure: bool
    session_cookie_samesite: str
    storage_credential_cipher: StorageCredentialCipher | None
    shared_engine: object
    admin_repository: object
    document_repository: object
    project_repository: object
    billing_repository: object
    auth_repository: object
    audit_repository: object
    profile_repository: object
    run_repository: object
    notification_repository: object
    discovery_job_repository: object
    support_repository: object


def build_repository_bundle(
    *,
    artifact_root: Path | None,
    database_url: str | None,
    artifact_storage_backend: str | None,
    artifact_bucket: str | None,
    artifact_prefix: str | None,
    s3_client: object | None,
    supabase_url: str | None,
    supabase_service_role_key: str | None,
    supabase_client: object | None,
    auth_required: bool | None,
    jwt_secret: str | None,
    storage_credentials_secret: str | None,
    google_drive_oauth_config: GoogleDriveOAuthConfig | None,
    google_drive_client: object | None,
    onedrive_oauth_config: OneDriveOAuthConfig | None,
    onedrive_client: object | None,
    internal_worker_token: str | None,
) -> RepositoryBundle:
    resolved_artifact_root = get_artifact_root(artifact_root)
    resolved_database_url = get_database_url(database_url, artifact_root=resolved_artifact_root)
    resolved_auth_required = get_auth_required(auth_required)
    resolved_internal_worker_token = get_internal_worker_token(internal_worker_token)
    resolved_jwt_secret = get_jwt_secret(jwt_secret)
    resolved_storage_credentials_secret = (
        get_storage_credentials_secret(storage_credentials_secret) or resolved_jwt_secret
    )
    resolved_google_drive_oauth_config = google_drive_oauth_config
    if resolved_google_drive_oauth_config is None:
        google_client_id = get_google_drive_client_id(None)
        google_client_secret = get_google_drive_client_secret(None)
        google_redirect_uri = get_google_drive_redirect_uri(None)
        if google_client_id and google_client_secret and google_redirect_uri:
            resolved_google_drive_oauth_config = GoogleDriveOAuthConfig(
                client_id=google_client_id,
                client_secret=google_client_secret,
                redirect_uri=google_redirect_uri,
                scopes=normalize_google_drive_scopes(get_google_drive_scopes(None)),
            )
    resolved_onedrive_oauth_config = onedrive_oauth_config
    if resolved_onedrive_oauth_config is None:
        onedrive_client_id = get_onedrive_client_id(None)
        onedrive_client_secret = get_onedrive_client_secret(None)
        onedrive_redirect_uri = get_onedrive_redirect_uri(None)
        if onedrive_client_id and onedrive_client_secret and onedrive_redirect_uri:
            resolved_onedrive_oauth_config = OneDriveOAuthConfig(
                client_id=onedrive_client_id,
                client_secret=onedrive_client_secret,
                redirect_uri=onedrive_redirect_uri,
                scopes=normalize_onedrive_scopes(get_onedrive_scopes(None)),
            )
    session_cookie_name = get_session_cookie_name(None)
    session_cookie_max_age_seconds = get_session_cookie_max_age_seconds(None)
    session_cookie_secure = get_session_cookie_secure(None)
    session_cookie_samesite = get_session_cookie_samesite(None)
    shared_engine = create_shared_engine(resolved_database_url)
    admin_repository = create_admin_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    managed_artifact_store = create_artifact_store(
        storage_backend=get_artifact_storage_backend(artifact_storage_backend),
        artifact_root=resolved_artifact_root,
        s3_bucket=get_artifact_bucket(artifact_bucket),
        s3_prefix=get_artifact_prefix(artifact_prefix),
        s3_client=s3_client,
        supabase_url=get_supabase_url(supabase_url),
        supabase_service_role_key=get_supabase_service_role_key(supabase_service_role_key),
        supabase_client=supabase_client,
    )
    storage_credential_cipher = (
        StorageCredentialCipher(resolved_storage_credentials_secret)
        if resolved_storage_credentials_secret is not None
        else None
    )
    resolved_google_drive_client = google_drive_client or GoogleDriveClient()
    resolved_onedrive_client = onedrive_client or OneDriveClient()
    tenant_artifact_store_resolver = TenantArtifactStoreResolver(
        admin_repository=admin_repository,
        managed_artifact_store=managed_artifact_store,
        credential_cipher=storage_credential_cipher,
        google_drive_oauth_config=resolved_google_drive_oauth_config,
        google_drive_client=resolved_google_drive_client,
        onedrive_oauth_config=resolved_onedrive_oauth_config,
        onedrive_client=resolved_onedrive_client,
    )
    document_repository = create_document_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
        artifact_store_resolver=tenant_artifact_store_resolver,
        storage_backend=get_artifact_storage_backend(artifact_storage_backend),
        artifact_root=resolved_artifact_root,
        s3_bucket=get_artifact_bucket(artifact_bucket),
        s3_prefix=get_artifact_prefix(artifact_prefix),
        s3_client=s3_client,
        supabase_url=get_supabase_url(supabase_url),
        supabase_service_role_key=get_supabase_service_role_key(supabase_service_role_key),
        supabase_client=supabase_client,
    )
    return RepositoryBundle(
        resolved_artifact_root=resolved_artifact_root,
        resolved_database_url=resolved_database_url,
        resolved_auth_required=resolved_auth_required,
        resolved_internal_worker_token=resolved_internal_worker_token,
        resolved_jwt_secret=resolved_jwt_secret,
        resolved_storage_credentials_secret=resolved_storage_credentials_secret,
        resolved_google_drive_oauth_config=resolved_google_drive_oauth_config,
        resolved_google_drive_client=resolved_google_drive_client,
        resolved_onedrive_oauth_config=resolved_onedrive_oauth_config,
        resolved_onedrive_client=resolved_onedrive_client,
        session_cookie_name=session_cookie_name,
        session_cookie_max_age_seconds=session_cookie_max_age_seconds,
        session_cookie_secure=session_cookie_secure,
        session_cookie_samesite=session_cookie_samesite,
        storage_credential_cipher=storage_credential_cipher,
        shared_engine=shared_engine,
        admin_repository=admin_repository,
        document_repository=document_repository,
        project_repository=create_project_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        billing_repository=create_billing_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        auth_repository=create_auth_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        audit_repository=create_audit_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        profile_repository=create_profile_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        run_repository=create_run_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        notification_repository=create_notification_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        discovery_job_repository=create_discovery_job_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
        support_repository=create_support_repository(
            database_url=resolved_database_url,
            engine=shared_engine,
        ),
    )
