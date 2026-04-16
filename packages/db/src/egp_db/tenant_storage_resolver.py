"""Tenant-aware artifact-store resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from egp_db.artifact_store import (
    ArtifactStore,
    GoogleDriveArtifactStore,
    OneDriveArtifactStore,
)
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig
from egp_db.repositories.admin_repo import SqlAdminRepository
from egp_db.storage_credentials import StorageCredentialCipher


GOOGLE_DRIVE_STORAGE_KEY_PREFIX = "google_drive:"
ONEDRIVE_STORAGE_KEY_PREFIX = "onedrive:"


class GoogleDriveRuntimeClient(Protocol):
    def refresh_access_token(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]: ...

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]: ...

    def download_file(self, *, access_token: str, file_id: str) -> bytes: ...

    def delete_file(self, *, access_token: str, file_id: str) -> None: ...

    def download_url(self, *, file_id: str) -> str: ...


class OneDriveRuntimeClient(Protocol):
    def refresh_access_token(
        self,
        *,
        config: OneDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]: ...

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]: ...

    def download_file(self, *, access_token: str, file_id: str) -> bytes: ...

    def delete_file(self, *, access_token: str, file_id: str) -> None: ...

    def download_url(self, *, access_token: str, file_id: str) -> str: ...


def encode_provider_storage_key(provider: str, storage_key: str) -> str:
    if provider == "google_drive":
        return f"{GOOGLE_DRIVE_STORAGE_KEY_PREFIX}{storage_key}"
    if provider == "onedrive":
        return f"{ONEDRIVE_STORAGE_KEY_PREFIX}{storage_key}"
    return storage_key


def decode_provider_storage_key(storage_key: str) -> tuple[str, str]:
    if storage_key.startswith(GOOGLE_DRIVE_STORAGE_KEY_PREFIX):
        return ("google_drive", storage_key[len(GOOGLE_DRIVE_STORAGE_KEY_PREFIX) :])
    if storage_key.startswith(ONEDRIVE_STORAGE_KEY_PREFIX):
        return ("onedrive", storage_key[len(ONEDRIVE_STORAGE_KEY_PREFIX) :])
    return ("managed", storage_key)


@dataclass(frozen=True, slots=True)
class ResolvedArtifactStore:
    provider: str
    store: ArtifactStore

    def encode_storage_key(self, storage_key: str) -> str:
        return encode_provider_storage_key(self.provider, storage_key)

    def decode_storage_key(self, storage_key: str) -> str:
        provider, decoded = decode_provider_storage_key(storage_key)
        if provider != self.provider:
            if self.provider == "managed" and provider == "managed":
                return decoded
            raise ValueError(
                f"storage key provider {provider!r} does not match resolved provider {self.provider!r}"
            )
        return decoded


@dataclass(frozen=True, slots=True)
class ResolvedDocumentWritePlan:
    primary: ResolvedArtifactStore
    managed_backup: ResolvedArtifactStore | None


class TenantArtifactStoreResolver:
    def __init__(
        self,
        *,
        admin_repository: SqlAdminRepository,
        managed_artifact_store: ArtifactStore,
        credential_cipher: StorageCredentialCipher | None = None,
        google_drive_oauth_config: GoogleDriveOAuthConfig | None = None,
        google_drive_client: GoogleDriveRuntimeClient | None = None,
        onedrive_oauth_config: OneDriveOAuthConfig | None = None,
        onedrive_client: OneDriveRuntimeClient | None = None,
    ) -> None:
        self._admin_repository = admin_repository
        self._managed_artifact_store = managed_artifact_store
        self._credential_cipher = credential_cipher
        self._google_drive_oauth_config = google_drive_oauth_config
        self._google_drive_client = google_drive_client
        self._onedrive_oauth_config = onedrive_oauth_config
        self._onedrive_client = onedrive_client

    def resolve_write_plan(self, *, tenant_id: str) -> ResolvedDocumentWritePlan:
        config = self._admin_repository.get_tenant_storage_config(tenant_id=tenant_id)
        primary = self._resolve_primary_for_config(tenant_id=tenant_id, config=config)
        managed_backup = (
            self._managed()
            if config.managed_backup_enabled and primary.provider != "managed"
            else None
        )
        return ResolvedDocumentWritePlan(
            primary=primary,
            managed_backup=managed_backup,
        )

    def resolve_for_write(self, *, tenant_id: str) -> ResolvedArtifactStore:
        return self.resolve_write_plan(tenant_id=tenant_id).primary

    def _resolve_primary_for_config(
        self, *, tenant_id: str, config
    ) -> ResolvedArtifactStore:
        if config.provider == "managed":
            return self._managed()
        if (
            config.provider == "google_drive"
            and config.connection_status == "connected"
        ):
            try:
                return self._google_drive(
                    tenant_id=tenant_id, folder_id=config.provider_folder_id
                )
            except Exception:
                if config.managed_fallback_enabled:
                    return self._managed()
                raise
        if config.provider == "onedrive" and config.connection_status == "connected":
            try:
                return self._onedrive(
                    tenant_id=tenant_id,
                    folder_id=config.provider_folder_id,
                )
            except Exception:
                if config.managed_fallback_enabled:
                    return self._managed()
                raise
        if config.managed_fallback_enabled:
            return self._managed()
        raise ValueError(
            f"tenant storage provider {config.provider!r} is not connected for document storage"
        )

    def resolve_for_storage_key(
        self,
        *,
        tenant_id: str,
        storage_key: str,
    ) -> ResolvedArtifactStore:
        provider, _ = decode_provider_storage_key(storage_key)
        if provider == "managed":
            return self._managed()
        if provider == "google_drive":
            return self._google_drive(tenant_id=tenant_id, folder_id=None)
        if provider == "onedrive":
            return self._onedrive(tenant_id=tenant_id, folder_id=None)
        raise ValueError(f"Unsupported document storage provider: {provider}")

    def _managed(self) -> ResolvedArtifactStore:
        return ResolvedArtifactStore(
            provider="managed", store=self._managed_artifact_store
        )

    def _google_drive(
        self,
        *,
        tenant_id: str,
        folder_id: str | None,
    ) -> ResolvedArtifactStore:
        if self._credential_cipher is None:
            raise ValueError(
                "Google Drive storage credentials secret is not configured"
            )
        if self._google_drive_oauth_config is None:
            raise ValueError("Google Drive OAuth is not configured")
        if self._google_drive_client is None:
            raise ValueError("Google Drive client is not configured")

        credential = self._admin_repository.get_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="google_drive",
        )
        if credential is None:
            raise ValueError("Google Drive storage credentials missing")
        credentials = self._credential_cipher.decrypt_dict(credential.encrypted_payload)
        refresh_token = str(credentials.get("refresh_token") or "").strip()
        if not refresh_token:
            raise ValueError("Google Drive refresh token is missing")

        refreshed = self._google_drive_client.refresh_access_token(
            config=self._google_drive_oauth_config,
            refresh_token=refresh_token,
        )
        access_token = str(refreshed.get("access_token") or "").strip()
        if not access_token:
            raise ValueError(
                "Google Drive refresh response did not include access_token"
            )

        updated_credentials: dict[str, Any] = dict(credentials)
        updated_credentials.update(refreshed)
        updated_credentials["refresh_token"] = refresh_token
        self._admin_repository.upsert_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="google_drive",
            credential_type=credential.credential_type,
            encrypted_payload=self._credential_cipher.encrypt_dict(updated_credentials),
        )

        return ResolvedArtifactStore(
            provider="google_drive",
            store=GoogleDriveArtifactStore(
                client=self._google_drive_client,
                access_token=access_token,
                folder_id=folder_id,
            ),
        )

    def _onedrive(
        self,
        *,
        tenant_id: str,
        folder_id: str | None,
    ) -> ResolvedArtifactStore:
        if self._credential_cipher is None:
            raise ValueError("OneDrive storage credentials secret is not configured")
        if self._onedrive_oauth_config is None:
            raise ValueError("OneDrive OAuth is not configured")
        if self._onedrive_client is None:
            raise ValueError("OneDrive client is not configured")

        credential = self._admin_repository.get_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="onedrive",
        )
        if credential is None:
            raise ValueError("OneDrive storage credentials missing")
        credentials = self._credential_cipher.decrypt_dict(credential.encrypted_payload)
        refresh_token = str(credentials.get("refresh_token") or "").strip()
        if not refresh_token:
            raise ValueError("OneDrive refresh token is missing")

        refreshed = self._onedrive_client.refresh_access_token(
            config=self._onedrive_oauth_config,
            refresh_token=refresh_token,
        )
        access_token = str(refreshed.get("access_token") or "").strip()
        if not access_token:
            raise ValueError("OneDrive refresh response did not include access_token")

        updated_credentials: dict[str, Any] = dict(credentials)
        updated_credentials.update(refreshed)
        updated_credentials["refresh_token"] = refresh_token
        self._admin_repository.upsert_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="onedrive",
            credential_type=credential.credential_type,
            encrypted_payload=self._credential_cipher.encrypt_dict(updated_credentials),
        )

        return ResolvedArtifactStore(
            provider="onedrive",
            store=OneDriveArtifactStore(
                client=self._onedrive_client,
                access_token=access_token,
                folder_id=folder_id,
            ),
        )
