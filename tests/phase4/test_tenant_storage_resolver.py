from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from egp_db.artifact_store import LocalArtifactStore
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig
from egp_db.repositories import profile_repo as _profile_repo  # noqa: F401
from egp_db.repositories.admin_repo import create_admin_repository
from egp_db.storage_credentials import StorageCredentialCipher
from egp_db.tenant_storage_resolver import (
    GOOGLE_DRIVE_STORAGE_KEY_PREFIX,
    TenantArtifactStoreResolver,
    decode_provider_storage_key,
    encode_provider_storage_key,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class FakeGoogleDriveClient:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []
        self.upload_calls: list[dict[str, object]] = []
        self.refresh_exception: Exception | None = None

    def refresh_access_token(
        self,
        *,
        config: GoogleDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        if self.refresh_exception is not None:
            raise self.refresh_exception
        return {"access_token": f"access-for-{config.client_id}"}

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]:
        self.upload_calls.append(
            {
                "access_token": access_token,
                "folder_id": folder_id,
                "name": name,
                "data": data,
                "content_type": content_type,
            }
        )
        return {"id": "drive-file-id"}

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        return f"download:{access_token}:{file_id}".encode("utf-8")

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        return None

    def download_url(self, *, file_id: str) -> str:
        return f"https://drive.example/{file_id}"


class FakeOneDriveClient:
    def __init__(self) -> None:
        self.refresh_calls: list[str] = []
        self.upload_calls: list[dict[str, object]] = []
        self.refresh_exception: Exception | None = None

    def refresh_access_token(
        self,
        *,
        config: OneDriveOAuthConfig,
        refresh_token: str,
    ) -> dict[str, object]:
        self.refresh_calls.append(refresh_token)
        if self.refresh_exception is not None:
            raise self.refresh_exception
        return {"access_token": f"access-for-{config.client_id}"}

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]:
        self.upload_calls.append(
            {
                "access_token": access_token,
                "folder_id": folder_id,
                "name": name,
                "data": data,
                "content_type": content_type,
            }
        )
        return {"id": "onedrive-item-id"}

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        return f"download:{access_token}:{file_id}".encode("utf-8")

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        return None

    def download_url(self, *, access_token: str, file_id: str) -> str:
        return f"https://onedrive.example/{file_id}"


def _google_config() -> GoogleDriveOAuthConfig:
    return GoogleDriveOAuthConfig(
        client_id="google-client-id",
        client_secret="google-client-secret",
        redirect_uri="https://api.example/v1/admin/storage/google-drive/oauth/callback",
    )


def _onedrive_config() -> OneDriveOAuthConfig:
    return OneDriveOAuthConfig(
        client_id="onedrive-client-id",
        client_secret="onedrive-client-secret",
        redirect_uri="https://api.example/v1/admin/storage/onedrive/oauth/callback",
    )


def _seed_tenant_storage(
    repository,
    *,
    provider: str = "google_drive",
    connection_status: str = "connected",
    folder_id: str | None = "drive-folder-id",
    refresh_token: str | None = "google-refresh-token",
    fallback_enabled: bool = False,
    managed_backup_enabled: bool = False,
) -> None:
    now = datetime.now(UTC)
    cipher = StorageCredentialCipher("resolver-secret")
    with repository._engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO tenants (
                    id, name, slug, plan_code, is_active, created_at, updated_at
                ) VALUES (
                    :tenant_id, 'Acme', 'acme', 'monthly_membership', 1, :now, :now
                )
                """
            ),
            {"tenant_id": TENANT_ID, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO tenant_storage_configs (
                    id,
                    tenant_id,
                    provider,
                    connection_status,
                    provider_folder_id,
                    managed_fallback_enabled,
                    managed_backup_enabled,
                    created_at,
                    updated_at
                ) VALUES (
                    '33333333-3333-3333-3333-333333333333',
                    :tenant_id,
                    :provider,
                    :connection_status,
                    :folder_id,
                    :fallback_enabled,
                    :managed_backup_enabled,
                    :now,
                    :now
                )
                """
            ),
            {
                "tenant_id": TENANT_ID,
                "provider": provider,
                "connection_status": connection_status,
                "folder_id": folder_id,
                "fallback_enabled": 1 if fallback_enabled else 0,
                "managed_backup_enabled": 1 if managed_backup_enabled else 0,
                "now": now,
            },
        )
        if refresh_token is not None:
            connection.execute(
                text(
                    """
                    INSERT INTO tenant_storage_credentials (
                        id,
                        tenant_id,
                        provider,
                        credential_type,
                        encrypted_payload,
                        created_at,
                        updated_at
                    ) VALUES (
                        '44444444-4444-4444-4444-444444444444',
                        :tenant_id,
                        :provider,
                        'oauth_tokens',
                        :encrypted_payload,
                        :now,
                        :now
                    )
                    """
                ),
                {
                    "tenant_id": TENANT_ID,
                    "provider": provider,
                    "encrypted_payload": cipher.encrypt_dict(
                        {"refresh_token": refresh_token}
                    ),
                    "now": now,
                },
            )


def test_resolver_returns_google_drive_store_for_connected_tenant(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository)
    google_client = FakeGoogleDriveClient()
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
    )

    resolved = resolver.resolve_for_write(tenant_id=TENANT_ID)
    raw_key = resolved.store.put_bytes(
        key="tenants/t/projects/p/artifacts/hash/tor.pdf",
        data=b"tor",
        content_type="application/pdf",
    )

    assert resolved.provider == "google_drive"
    assert resolved.encode_storage_key(raw_key) == "google_drive:drive-file-id"
    assert google_client.refresh_calls == ["google-refresh-token"]
    assert google_client.upload_calls[0]["folder_id"] == "drive-folder-id"


def test_resolver_uses_managed_for_unprefixed_storage_key(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository)
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=FakeGoogleDriveClient(),
    )

    resolved = resolver.resolve_for_storage_key(
        tenant_id=TENANT_ID,
        storage_key="tenants/t/projects/p/artifacts/hash/tor.pdf",
    )

    assert resolved.provider == "managed"
    assert resolved.decode_storage_key(
        "tenants/t/projects/p/artifacts/hash/tor.pdf"
    ) == ("tenants/t/projects/p/artifacts/hash/tor.pdf")


def test_resolver_fails_closed_when_google_credentials_missing(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository, refresh_token=None)
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=FakeGoogleDriveClient(),
    )

    try:
        resolver.resolve_for_write(tenant_id=TENANT_ID)
    except ValueError as exc:
        assert "credentials missing" in str(exc)
    else:
        raise AssertionError("expected resolver to fail closed")


def test_resolver_uses_managed_fallback_when_enabled(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository, refresh_token=None, fallback_enabled=True)
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=FakeGoogleDriveClient(),
    )

    resolved = resolver.resolve_for_write(tenant_id=TENANT_ID)

    assert resolved.provider == "managed"


def test_resolver_returns_onedrive_store_for_connected_tenant(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(
        repository,
        provider="onedrive",
        folder_id="onedrive-folder-id",
        refresh_token="onedrive-refresh-token",
    )
    onedrive_client = FakeOneDriveClient()
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        onedrive_oauth_config=_onedrive_config(),
        onedrive_client=onedrive_client,
    )

    resolved = resolver.resolve_for_write(tenant_id=TENANT_ID)
    raw_key = resolved.store.put_bytes(
        key="tenants/t/projects/p/artifacts/hash/tor.pdf",
        data=b"tor",
        content_type="application/pdf",
    )

    assert resolved.provider == "onedrive"
    assert resolved.encode_storage_key(raw_key) == "onedrive:onedrive-item-id"
    assert onedrive_client.refresh_calls == ["onedrive-refresh-token"]
    assert onedrive_client.upload_calls[0]["folder_id"] == "onedrive-folder-id"


def test_resolver_uses_onedrive_for_prefixed_storage_key(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(
        repository,
        provider="onedrive",
        folder_id="onedrive-folder-id",
        refresh_token="onedrive-refresh-token",
    )
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        onedrive_oauth_config=_onedrive_config(),
        onedrive_client=FakeOneDriveClient(),
    )

    resolved = resolver.resolve_for_storage_key(
        tenant_id=TENANT_ID,
        storage_key="onedrive:onedrive-item-id",
    )

    assert resolved.provider == "onedrive"
    assert (
        resolved.decode_storage_key("onedrive:onedrive-item-id") == "onedrive-item-id"
    )


def test_resolver_uses_managed_fallback_on_google_refresh_failure(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository, fallback_enabled=True)
    google_client = FakeGoogleDriveClient()
    google_client.refresh_exception = RuntimeError("google refresh failed")
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
    )

    resolved = resolver.resolve_for_write(tenant_id=TENANT_ID)

    assert resolved.provider == "managed"


def test_provider_storage_key_helpers_round_trip_google_drive_key() -> None:
    encoded = encode_provider_storage_key("google_drive", "drive-file-id")

    assert encoded == f"{GOOGLE_DRIVE_STORAGE_KEY_PREFIX}drive-file-id"
    assert decode_provider_storage_key(encoded) == ("google_drive", "drive-file-id")
    assert decode_provider_storage_key("tenants/t/file.pdf") == (
        "managed",
        "tenants/t/file.pdf",
    )


def test_resolver_caches_google_drive_resolution_within_ttl(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository)
    google_client = FakeGoogleDriveClient()
    now = {"value": 1000.0}

    def clock() -> float:
        return now["value"]

    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
        clock=clock,
    )

    first = resolver.resolve_for_write(tenant_id=TENANT_ID)
    # Second call within the TTL window must reuse the cached resolution and
    # avoid hitting the OAuth refresh endpoint again — the per-request cost
    # this cache is designed to eliminate.
    second = resolver.resolve_for_write(tenant_id=TENANT_ID)

    assert first.provider == "google_drive"
    assert second is first
    assert google_client.refresh_calls == ["google-refresh-token"]


def test_resolver_refreshes_google_drive_after_ttl_expires(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository)
    google_client = FakeGoogleDriveClient()
    now = {"value": 1000.0}

    def clock() -> float:
        return now["value"]

    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
        clock=clock,
    )

    resolver.resolve_for_write(tenant_id=TENANT_ID)
    # Advance well past the default TTL (300s default minus 60s safety = 240s).
    now["value"] += 10_000
    resolver.resolve_for_write(tenant_id=TENANT_ID)

    assert google_client.refresh_calls == [
        "google-refresh-token",
        "google-refresh-token",
    ]


def test_resolver_clear_cache_forces_refresh(tmp_path) -> None:
    repository = create_admin_repository(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'resolver.sqlite3'}",
        bootstrap_schema=True,
    )
    _seed_tenant_storage(repository)
    google_client = FakeGoogleDriveClient()
    resolver = TenantArtifactStoreResolver(
        admin_repository=repository,
        managed_artifact_store=LocalArtifactStore(tmp_path / "managed"),
        credential_cipher=StorageCredentialCipher("resolver-secret"),
        google_drive_oauth_config=_google_config(),
        google_drive_client=google_client,
    )

    resolver.resolve_for_write(tenant_id=TENANT_ID)
    resolver.clear_resolution_cache()
    resolver.resolve_for_write(tenant_id=TENANT_ID)

    assert google_client.refresh_calls == [
        "google-refresh-token",
        "google-refresh-token",
    ]
