"""Tenant-scoped storage settings and credential orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
import time
from typing import Any

from egp_api.services.google_drive import (
    GoogleDriveClient,
    GoogleDriveOAuthConfig,
    email_from_id_token,
)
from egp_api.services.onedrive import (
    OneDriveClient,
    OneDriveOAuthConfig,
    email_from_onedrive_id_token,
)
from egp_api.services.storage_credentials import StorageCredentialCipher
from egp_db.repositories.admin_repo import (
    SqlAdminRepository,
    TenantStorageSettingsRecord,
)
from egp_db.repositories.audit_repo import SqlAuditRepository


EXTERNAL_STORAGE_PROVIDERS = {"google_drive", "onedrive", "local_agent"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class StorageSettingsService:
    def __init__(
        self,
        repository: SqlAdminRepository,
        *,
        credential_cipher: StorageCredentialCipher | None,
        audit_repository: SqlAuditRepository | None = None,
        google_drive_oauth_config: GoogleDriveOAuthConfig | None = None,
        google_drive_client: GoogleDriveClient | None = None,
        onedrive_oauth_config: OneDriveOAuthConfig | None = None,
        onedrive_client: OneDriveClient | None = None,
    ) -> None:
        self._repository = repository
        self._credential_cipher = credential_cipher
        self._audit_repository = audit_repository
        self._google_drive_oauth_config = google_drive_oauth_config
        self._google_drive_client = google_drive_client
        self._onedrive_oauth_config = onedrive_oauth_config
        self._onedrive_client = onedrive_client

    def get_storage_settings(self, *, tenant_id: str) -> TenantStorageSettingsRecord:
        self._require_tenant(tenant_id)
        return self._repository.get_tenant_storage_settings(tenant_id=tenant_id)

    def update_config(
        self,
        *,
        tenant_id: str,
        provider: str | None = None,
        connection_status: str | None = None,
        account_email: str | None = None,
        folder_label: str | None = None,
        folder_path_hint: str | None = None,
        provider_folder_id: str | None = None,
        provider_folder_url: str | None = None,
        managed_fallback_enabled: bool | None = None,
        last_validated_at: str | None = None,
        last_validation_error: str | None = None,
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        self._require_tenant(tenant_id)
        previous = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        resolved_provider = provider
        resolved_connection_status = connection_status
        resolved_account_email = account_email
        resolved_folder_label = folder_label
        resolved_folder_path_hint = folder_path_hint
        resolved_provider_folder_id = provider_folder_id
        resolved_provider_folder_url = provider_folder_url
        resolved_managed_fallback_enabled = managed_fallback_enabled
        resolved_last_validated_at = last_validated_at
        resolved_last_validation_error = last_validation_error

        if resolved_provider == "managed":
            resolved_connection_status = "managed"
            resolved_account_email = ""
            resolved_folder_label = ""
            resolved_folder_path_hint = ""
            resolved_provider_folder_id = ""
            resolved_provider_folder_url = ""
            resolved_managed_fallback_enabled = False
            resolved_last_validated_at = ""
            resolved_last_validation_error = ""
        elif resolved_connection_status in {"connected", "error"}:
            raise ValueError(
                "connection_status values 'connected' and 'error' are reserved for validated integrations"
            )

        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            provider=resolved_provider,
            connection_status=resolved_connection_status,
            account_email=resolved_account_email,
            folder_label=resolved_folder_label,
            folder_path_hint=resolved_folder_path_hint,
            provider_folder_id=resolved_provider_folder_id,
            provider_folder_url=resolved_provider_folder_url,
            managed_fallback_enabled=resolved_managed_fallback_enabled,
            last_validated_at=resolved_last_validated_at,
            last_validation_error=resolved_last_validation_error,
        )
        self._clear_stale_credentials(
            tenant_id=tenant_id,
            previous_provider=previous.provider,
            updated_provider=updated.provider,
        )
        refreshed = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_settings_updated",
            summary="Updated tenant storage settings",
            before=previous,
            after=refreshed,
        )
        return refreshed

    def connect_provider(
        self,
        *,
        tenant_id: str,
        provider: str,
        credential_type: str,
        credentials: Mapping[str, Any],
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        self._require_tenant(tenant_id)
        if provider not in EXTERNAL_STORAGE_PROVIDERS:
            raise ValueError(f"provider {provider!r} does not support stored credentials")
        current = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        if current.provider != provider:
            raise ValueError(
                f"storage provider mismatch: configure {provider!r} on /admin/storage before connecting"
            )
        if not credentials:
            raise ValueError("credentials are required")

        encrypted_payload = self._require_cipher().encrypt_dict(credentials)
        self._repository.upsert_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider=provider,
            credential_type=credential_type,
            encrypted_payload=encrypted_payload,
        )
        updated = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_credentials_connected",
            summary=f"Stored {provider} credentials for tenant storage",
            before=current,
            after=updated,
        )
        return updated

    def start_google_drive_oauth(
        self,
        *,
        tenant_id: str,
    ) -> dict[str, str]:
        self._require_tenant(tenant_id)
        config = self._require_google_drive_oauth_config()
        state = self._require_cipher().encrypt_dict(
            {
                "tenant_id": tenant_id,
                "provider": "google_drive",
                "exp": int(time.time()) + 600,
            }
        )
        return {
            "provider": "google_drive",
            "authorization_url": self._require_google_drive_client().build_authorization_url(
                config=config,
                state=state,
            ),
            "state": state,
        }

    def handle_google_drive_oauth_callback(
        self,
        *,
        code: str,
        state: str,
        expected_tenant_id: str | None = None,
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        config = self._require_google_drive_oauth_config()
        state_payload = self._decode_google_drive_state(state)
        tenant_id = str(state_payload["tenant_id"])
        self._require_tenant(tenant_id)
        if expected_tenant_id is not None and tenant_id != expected_tenant_id:
            raise ValueError("Google Drive OAuth state tenant mismatch")

        previous = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        token_payload = self._require_google_drive_client().exchange_code(
            config=config,
            code=code,
        )
        refresh_token = token_payload.get("refresh_token")
        if not refresh_token:
            existing = self._repository.get_tenant_storage_credentials(
                tenant_id=tenant_id,
                provider="google_drive",
            )
            if existing is None:
                raise ValueError("Google Drive OAuth response did not include a refresh token")
            existing_payload = self._require_cipher().decrypt_dict(existing.encrypted_payload)
            refresh_token = existing_payload.get("refresh_token")
            if refresh_token:
                token_payload["refresh_token"] = refresh_token

        account_email = email_from_id_token(
            str(token_payload.get("id_token")) if token_payload.get("id_token") else None
        )
        encrypted_payload = self._require_cipher().encrypt_dict(token_payload)
        self._repository.upsert_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="google_drive",
            credential_type="oauth_tokens",
            encrypted_payload=encrypted_payload,
        )
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            provider="google_drive",
            connection_status="pending_setup",
            account_email=account_email,
            last_validated_at="",
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_google_drive_oauth_connected",
            summary="Connected Google Drive OAuth credentials",
            before=previous,
            after=updated,
        )
        return updated

    def select_google_drive_folder(
        self,
        *,
        tenant_id: str,
        folder_id: str,
        folder_label: str | None = None,
        folder_url: str | None = None,
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        self._require_tenant(tenant_id)
        if not folder_id.strip():
            raise ValueError("folder_id is required")
        previous = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            provider="google_drive",
            connection_status="pending_setup",
            folder_label=folder_label,
            folder_path_hint=folder_url,
            provider_folder_id=folder_id,
            provider_folder_url=folder_url,
            last_validated_at="",
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_google_drive_folder_selected",
            summary="Selected Google Drive folder for tenant storage",
            before=previous,
            after=updated,
        )
        return updated

    def start_onedrive_oauth(
        self,
        *,
        tenant_id: str,
    ) -> dict[str, str]:
        self._require_tenant(tenant_id)
        config = self._require_onedrive_oauth_config()
        state = self._require_cipher().encrypt_dict(
            {
                "tenant_id": tenant_id,
                "provider": "onedrive",
                "exp": int(time.time()) + 600,
            }
        )
        return {
            "provider": "onedrive",
            "authorization_url": self._require_onedrive_client().build_authorization_url(
                config=config,
                state=state,
            ),
            "state": state,
        }

    def handle_onedrive_oauth_callback(
        self,
        *,
        code: str,
        state: str,
        expected_tenant_id: str | None = None,
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        config = self._require_onedrive_oauth_config()
        state_payload = self._decode_onedrive_state(state)
        tenant_id = str(state_payload["tenant_id"])
        self._require_tenant(tenant_id)
        if expected_tenant_id is not None and tenant_id != expected_tenant_id:
            raise ValueError("OneDrive OAuth state tenant mismatch")

        previous = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        token_payload = self._require_onedrive_client().exchange_code(
            config=config,
            code=code,
        )
        refresh_token = token_payload.get("refresh_token")
        if not refresh_token:
            existing = self._repository.get_tenant_storage_credentials(
                tenant_id=tenant_id,
                provider="onedrive",
            )
            if existing is None:
                raise ValueError("OneDrive OAuth response did not include a refresh token")
            existing_payload = self._require_cipher().decrypt_dict(existing.encrypted_payload)
            refresh_token = existing_payload.get("refresh_token")
            if refresh_token:
                token_payload["refresh_token"] = refresh_token

        account_email = email_from_onedrive_id_token(
            str(token_payload.get("id_token")) if token_payload.get("id_token") else None
        )
        encrypted_payload = self._require_cipher().encrypt_dict(token_payload)
        self._repository.upsert_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="onedrive",
            credential_type="oauth_tokens",
            encrypted_payload=encrypted_payload,
        )
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            provider="onedrive",
            connection_status="pending_setup",
            account_email=account_email,
            last_validated_at="",
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_onedrive_oauth_connected",
            summary="Connected OneDrive OAuth credentials",
            before=previous,
            after=updated,
        )
        return updated

    def select_onedrive_folder(
        self,
        *,
        tenant_id: str,
        folder_id: str,
        folder_label: str | None = None,
        folder_url: str | None = None,
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        self._require_tenant(tenant_id)
        if not folder_id.strip():
            raise ValueError("folder_id is required")
        previous = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            provider="onedrive",
            connection_status="pending_setup",
            folder_label=folder_label,
            folder_path_hint=folder_url,
            provider_folder_id=folder_id,
            provider_folder_url=folder_url,
            last_validated_at="",
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_onedrive_folder_selected",
            summary="Selected OneDrive folder for tenant storage",
            before=previous,
            after=updated,
        )
        return updated

    def disconnect_provider(
        self,
        *,
        tenant_id: str,
        provider: str,
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        self._require_tenant(tenant_id)
        previous = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        if previous.provider != provider:
            raise ValueError(
                f"storage provider mismatch: current provider is {previous.provider!r}, not {provider!r}"
            )
        self._repository.delete_tenant_storage_credentials(tenant_id=tenant_id, provider=provider)
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            provider=provider,
            connection_status="disconnected",
            last_validated_at="",
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_credentials_disconnected",
            summary=f"Disconnected {provider} tenant storage credentials",
            before=previous,
            after=updated,
        )
        return updated

    def test_write(
        self,
        *,
        tenant_id: str,
        actor_subject: str | None = None,
    ) -> TenantStorageSettingsRecord:
        self._require_tenant(tenant_id)
        current = self._repository.get_tenant_storage_settings(tenant_id=tenant_id)
        if current.provider == "managed":
            return current
        if (
            current.provider == "google_drive"
            and self._google_drive_oauth_config is not None
            and self._google_drive_client is not None
        ):
            return self._test_google_drive_write(
                tenant_id=tenant_id,
                current=current,
                actor_subject=actor_subject,
            )
        if (
            current.provider == "onedrive"
            and self._onedrive_oauth_config is not None
            and self._onedrive_client is not None
        ):
            return self._test_onedrive_write(
                tenant_id=tenant_id,
                current=current,
                actor_subject=actor_subject,
            )

        missing_parts: list[str] = []
        if not current.account_email:
            missing_parts.append("account_email")
        if not current.folder_label and not current.folder_path_hint:
            missing_parts.append("folder destination")
        if missing_parts:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message=f"storage configuration incomplete: missing {', '.join(missing_parts)}",
                actor_subject=actor_subject,
            )

        credential = self._repository.get_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider=current.provider,
        )
        if credential is None:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message=f"storage credentials missing for provider {current.provider}",
                actor_subject=actor_subject,
            )

        try:
            decrypted_payload = self._require_cipher().decrypt_dict(credential.encrypted_payload)
        except ValueError as exc:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message=str(exc),
                actor_subject=actor_subject,
            )
        if not decrypted_payload:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message=f"storage credentials missing for provider {current.provider}",
                actor_subject=actor_subject,
            )

        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            connection_status="connected",
            last_validated_at=_now_iso(),
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_validation_succeeded",
            summary=f"Validated tenant storage for {current.provider}",
            before=current,
            after=updated,
        )
        return updated

    def _mark_validation_error(
        self,
        *,
        tenant_id: str,
        current: TenantStorageSettingsRecord,
        message: str,
        actor_subject: str | None,
    ) -> TenantStorageSettingsRecord:
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            connection_status="error",
            last_validated_at="",
            last_validation_error=message,
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_validation_failed",
            summary=f"Validation failed for tenant storage {current.provider}",
            before=current,
            after=updated,
        )
        raise ValueError(message)

    def _require_tenant(self, tenant_id: str) -> None:
        if self._repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)

    def _require_cipher(self) -> StorageCredentialCipher:
        if self._credential_cipher is None:
            raise ValueError("storage credentials secret is not configured")
        return self._credential_cipher

    def _require_google_drive_oauth_config(self) -> GoogleDriveOAuthConfig:
        if self._google_drive_oauth_config is None:
            raise ValueError("Google Drive OAuth is not configured")
        return self._google_drive_oauth_config

    def _require_google_drive_client(self) -> GoogleDriveClient:
        if self._google_drive_client is None:
            raise ValueError("Google Drive client is not configured")
        return self._google_drive_client

    def _require_onedrive_oauth_config(self) -> OneDriveOAuthConfig:
        if self._onedrive_oauth_config is None:
            raise ValueError("OneDrive OAuth is not configured")
        return self._onedrive_oauth_config

    def _require_onedrive_client(self) -> OneDriveClient:
        if self._onedrive_client is None:
            raise ValueError("OneDrive client is not configured")
        return self._onedrive_client

    def _decode_google_drive_state(self, state: str) -> dict[str, Any]:
        try:
            payload = self._require_cipher().decrypt_dict(state)
        except ValueError as exc:
            raise ValueError("invalid Google Drive OAuth state") from exc
        if payload.get("provider") != "google_drive" or not payload.get("tenant_id"):
            raise ValueError("invalid Google Drive OAuth state")
        expires_at = int(payload.get("exp") or 0)
        if expires_at < int(time.time()):
            raise ValueError("expired Google Drive OAuth state")
        return payload

    def _decode_onedrive_state(self, state: str) -> dict[str, Any]:
        try:
            payload = self._require_cipher().decrypt_dict(state)
        except ValueError as exc:
            raise ValueError("invalid OneDrive OAuth state") from exc
        if payload.get("provider") != "onedrive" or not payload.get("tenant_id"):
            raise ValueError("invalid OneDrive OAuth state")
        expires_at = int(payload.get("exp") or 0)
        if expires_at < int(time.time()):
            raise ValueError("expired OneDrive OAuth state")
        return payload

    def _test_google_drive_write(
        self,
        *,
        tenant_id: str,
        current: TenantStorageSettingsRecord,
        actor_subject: str | None,
    ) -> TenantStorageSettingsRecord:
        credential = self._repository.get_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="google_drive",
        )
        if credential is None:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message="storage credentials missing for provider google_drive",
                actor_subject=actor_subject,
            )
        if not current.provider_folder_id:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message="Google Drive folder_id is required before validation",
                actor_subject=actor_subject,
            )
        try:
            credentials = self._require_cipher().decrypt_dict(credential.encrypted_payload)
            refresh_token = str(credentials.get("refresh_token") or "").strip()
            if not refresh_token:
                raise ValueError("Google Drive refresh token is missing")
            refreshed = self._require_google_drive_client().refresh_access_token(
                config=self._require_google_drive_oauth_config(),
                refresh_token=refresh_token,
            )
            access_token = str(refreshed.get("access_token") or "").strip()
            if not access_token:
                raise ValueError("Google Drive refresh response did not include access_token")
            self._require_google_drive_client().upload_file(
                access_token=access_token,
                folder_id=current.provider_folder_id,
                name="egp-storage-validation.txt",
                data=b"e-GP Intelligence storage validation",
                content_type="text/plain",
            )
        except Exception as exc:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message=str(exc),
                actor_subject=actor_subject,
            )

        credentials.update(refreshed)
        credentials["refresh_token"] = refresh_token
        self._repository.upsert_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="google_drive",
            credential_type=credential.credential_type,
            encrypted_payload=self._require_cipher().encrypt_dict(credentials),
        )
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            connection_status="connected",
            last_validated_at=_now_iso(),
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_validation_succeeded",
            summary="Validated tenant storage for google_drive",
            before=current,
            after=updated,
        )
        return updated

    def _test_onedrive_write(
        self,
        *,
        tenant_id: str,
        current: TenantStorageSettingsRecord,
        actor_subject: str | None,
    ) -> TenantStorageSettingsRecord:
        credential = self._repository.get_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="onedrive",
        )
        if credential is None:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message="storage credentials missing for provider onedrive",
                actor_subject=actor_subject,
            )
        if not current.provider_folder_id:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message="OneDrive folder_id is required before validation",
                actor_subject=actor_subject,
            )
        try:
            credentials = self._require_cipher().decrypt_dict(credential.encrypted_payload)
            refresh_token = str(credentials.get("refresh_token") or "").strip()
            if not refresh_token:
                raise ValueError("OneDrive refresh token is missing")
            refreshed = self._require_onedrive_client().refresh_access_token(
                config=self._require_onedrive_oauth_config(),
                refresh_token=refresh_token,
            )
            access_token = str(refreshed.get("access_token") or "").strip()
            if not access_token:
                raise ValueError("OneDrive refresh response did not include access_token")
            self._require_onedrive_client().upload_file(
                access_token=access_token,
                folder_id=current.provider_folder_id,
                name="egp-storage-validation.txt",
                data=b"e-GP Intelligence storage validation",
                content_type="text/plain",
            )
        except Exception as exc:
            return self._mark_validation_error(
                tenant_id=tenant_id,
                current=current,
                message=str(exc),
                actor_subject=actor_subject,
            )

        credentials.update(refreshed)
        credentials["refresh_token"] = refresh_token
        self._repository.upsert_tenant_storage_credentials(
            tenant_id=tenant_id,
            provider="onedrive",
            credential_type=credential.credential_type,
            encrypted_payload=self._require_cipher().encrypt_dict(credentials),
        )
        updated = self._repository.update_tenant_storage_settings(
            tenant_id=tenant_id,
            connection_status="connected",
            last_validated_at=_now_iso(),
            last_validation_error="",
        )
        self._record_event(
            tenant_id=tenant_id,
            actor_subject=actor_subject,
            event_type="tenant.storage_validation_succeeded",
            summary="Validated tenant storage for onedrive",
            before=current,
            after=updated,
        )
        return updated

    def _clear_stale_credentials(
        self,
        *,
        tenant_id: str,
        previous_provider: str,
        updated_provider: str,
    ) -> None:
        if (
            previous_provider in EXTERNAL_STORAGE_PROVIDERS
            and previous_provider != updated_provider
        ):
            self._repository.delete_tenant_storage_credentials(
                tenant_id=tenant_id,
                provider=previous_provider,
            )
        if updated_provider == "managed":
            for provider in EXTERNAL_STORAGE_PROVIDERS:
                self._repository.delete_tenant_storage_credentials(
                    tenant_id=tenant_id,
                    provider=provider,
                )

    def _record_event(
        self,
        *,
        tenant_id: str,
        actor_subject: str | None,
        event_type: str,
        summary: str,
        before: TenantStorageSettingsRecord,
        after: TenantStorageSettingsRecord,
    ) -> None:
        if self._audit_repository is None:
            return
        self._audit_repository.record_event(
            tenant_id=tenant_id,
            source="admin",
            entity_type="tenant_storage_settings",
            entity_id=tenant_id,
            actor_subject=actor_subject or "manual-operator",
            event_type=event_type,
            summary=summary,
            metadata_json={
                "before": asdict(before),
                "after": asdict(after),
            },
        )
