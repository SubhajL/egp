"""Tenant-scoped storage settings and credential orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

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
    ) -> None:
        self._repository = repository
        self._credential_cipher = credential_cipher
        self._audit_repository = audit_repository

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
        resolved_managed_fallback_enabled = managed_fallback_enabled
        resolved_last_validated_at = last_validated_at
        resolved_last_validation_error = last_validation_error

        if resolved_provider == "managed":
            resolved_connection_status = "managed"
            resolved_account_email = ""
            resolved_folder_label = ""
            resolved_folder_path_hint = ""
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
