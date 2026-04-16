"""Tenant admin persistence for tenant metadata and settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    Table,
    UniqueConstraint,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string


METADATA = DB_METADATA

TENANTS_TABLE = Table(
    "tenants",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("name", String, nullable=False),
    Column("slug", String, nullable=False, unique=True),
    Column("plan_code", String, nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

TENANT_SETTINGS_TABLE = Table(
    "tenant_settings",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("support_email", String, nullable=True),
    Column("billing_contact_email", String, nullable=True),
    Column("timezone", String, nullable=False, default="Asia/Bangkok"),
    Column("locale", String, nullable=False, default="th-TH"),
    Column("daily_digest_enabled", Boolean, nullable=False, default=True),
    Column("weekly_digest_enabled", Boolean, nullable=False, default=False),
    Column("crawl_interval_hours", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "crawl_interval_hours IS NULL OR crawl_interval_hours > 0",
        name="tenant_settings_crawl_interval_hours_check",
    ),
    UniqueConstraint("tenant_id", name="tenant_settings_tenant_uq"),
)

TENANT_STORAGE_SETTINGS_TABLE = Table(
    "tenant_storage_settings",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("provider", String, nullable=False, default="managed"),
    Column("connection_status", String, nullable=False, default="managed"),
    Column("account_email", String, nullable=True),
    Column("folder_label", String, nullable=True),
    Column("folder_path_hint", String, nullable=True),
    Column("managed_fallback_enabled", Boolean, nullable=False, default=False),
    Column("last_validated_at", DateTime(timezone=True), nullable=True),
    Column("last_validation_error", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "provider IN ('managed', 'google_drive', 'onedrive', 'local_agent')",
        name="tenant_storage_settings_provider_check",
    ),
    CheckConstraint(
        "connection_status IN ('managed', 'pending_setup', 'connected', 'error', 'disconnected')",
        name="tenant_storage_settings_connection_status_check",
    ),
    UniqueConstraint("tenant_id", name="tenant_storage_settings_tenant_uq"),
)

TENANT_STORAGE_CONFIGS_TABLE = Table(
    "tenant_storage_configs",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("provider", String, nullable=False, default="managed"),
    Column("connection_status", String, nullable=False, default="managed"),
    Column("account_email", String, nullable=True),
    Column("folder_label", String, nullable=True),
    Column("folder_path_hint", String, nullable=True),
    Column("provider_folder_id", String, nullable=True),
    Column("provider_folder_url", String, nullable=True),
    Column("managed_fallback_enabled", Boolean, nullable=False, default=False),
    Column("last_validated_at", DateTime(timezone=True), nullable=True),
    Column("last_validation_error", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "provider IN ('managed', 'google_drive', 'onedrive', 'local_agent')",
        name="tenant_storage_configs_provider_check",
    ),
    CheckConstraint(
        "connection_status IN ('managed', 'pending_setup', 'connected', 'error', 'disconnected')",
        name="tenant_storage_configs_connection_status_check",
    ),
    UniqueConstraint("tenant_id", name="tenant_storage_configs_tenant_uq"),
)

TENANT_STORAGE_CREDENTIALS_TABLE = Table(
    "tenant_storage_credentials",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("provider", String, nullable=False),
    Column("credential_type", String, nullable=False, default="oauth_tokens"),
    Column("encrypted_payload", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "provider IN ('google_drive', 'onedrive', 'local_agent')",
        name="tenant_storage_credentials_provider_check",
    ),
    UniqueConstraint(
        "tenant_id", "provider", name="tenant_storage_credentials_tenant_provider_uq"
    ),
)


@dataclass(frozen=True, slots=True)
class TenantRecord:
    id: str
    name: str
    slug: str
    plan_code: str
    is_active: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class TenantSettingsRecord:
    support_email: str | None
    billing_contact_email: str | None
    timezone: str
    locale: str
    daily_digest_enabled: bool
    weekly_digest_enabled: bool
    crawl_interval_hours: int | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class TenantStorageSettingsRecord:
    provider: str
    connection_status: str
    account_email: str | None
    folder_label: str | None
    folder_path_hint: str | None
    provider_folder_id: str | None
    provider_folder_url: str | None
    managed_fallback_enabled: bool
    last_validated_at: str | None
    last_validation_error: str | None
    has_credentials: bool
    credential_type: str | None
    credential_updated_at: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class TenantStorageConfigRecord:
    provider: str
    connection_status: str
    account_email: str | None
    folder_label: str | None
    folder_path_hint: str | None
    provider_folder_id: str | None
    provider_folder_url: str | None
    managed_fallback_enabled: bool
    last_validated_at: str | None
    last_validation_error: str | None
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class TenantStorageCredentialRecord:
    provider: str
    credential_type: str
    encrypted_payload: str
    created_at: str
    updated_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _tenant_from_mapping(row) -> TenantRecord:
    return TenantRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        plan_code=str(row["plan_code"]),
        is_active=bool(row["is_active"]),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
    )


def _settings_from_mapping(row) -> TenantSettingsRecord:
    return TenantSettingsRecord(
        support_email=str(row["support_email"])
        if row["support_email"] is not None
        else None,
        billing_contact_email=(
            str(row["billing_contact_email"])
            if row["billing_contact_email"] is not None
            else None
        ),
        timezone=str(row["timezone"]),
        locale=str(row["locale"]),
        daily_digest_enabled=bool(row["daily_digest_enabled"]),
        weekly_digest_enabled=bool(row["weekly_digest_enabled"]),
        crawl_interval_hours=(
            int(row["crawl_interval_hours"])
            if row["crawl_interval_hours"] is not None
            else None
        ),
        created_at=_to_iso(row["created_at"]),
        updated_at=_to_iso(row["updated_at"]),
    )


def _storage_settings_from_mapping(row) -> TenantStorageSettingsRecord:
    return TenantStorageSettingsRecord(
        provider=str(row["provider"]),
        connection_status=str(row["connection_status"]),
        account_email=str(row["account_email"])
        if row["account_email"] is not None
        else None,
        folder_label=str(row["folder_label"])
        if row["folder_label"] is not None
        else None,
        folder_path_hint=(
            str(row["folder_path_hint"])
            if row["folder_path_hint"] is not None
            else None
        ),
        provider_folder_id=(
            str(row["provider_folder_id"])
            if "provider_folder_id" in row and row["provider_folder_id"] is not None
            else None
        ),
        provider_folder_url=(
            str(row["provider_folder_url"])
            if "provider_folder_url" in row and row["provider_folder_url"] is not None
            else None
        ),
        managed_fallback_enabled=bool(row["managed_fallback_enabled"]),
        last_validated_at=_to_iso(row["last_validated_at"]),
        last_validation_error=(
            str(row["last_validation_error"])
            if row["last_validation_error"] is not None
            else None
        ),
        has_credentials=False,
        credential_type=None,
        credential_updated_at=None,
        created_at=_to_iso(row["created_at"]),
        updated_at=_to_iso(row["updated_at"]),
    )


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _storage_config_from_mapping(row) -> TenantStorageConfigRecord:
    return TenantStorageConfigRecord(
        provider=str(row["provider"]),
        connection_status=str(row["connection_status"]),
        account_email=str(row["account_email"])
        if row["account_email"] is not None
        else None,
        folder_label=str(row["folder_label"])
        if row["folder_label"] is not None
        else None,
        folder_path_hint=(
            str(row["folder_path_hint"])
            if row["folder_path_hint"] is not None
            else None
        ),
        provider_folder_id=(
            str(row["provider_folder_id"])
            if row["provider_folder_id"] is not None
            else None
        ),
        provider_folder_url=(
            str(row["provider_folder_url"])
            if row["provider_folder_url"] is not None
            else None
        ),
        managed_fallback_enabled=bool(row["managed_fallback_enabled"]),
        last_validated_at=_to_iso(row["last_validated_at"]),
        last_validation_error=(
            str(row["last_validation_error"])
            if row["last_validation_error"] is not None
            else None
        ),
        created_at=_to_iso(row["created_at"]),
        updated_at=_to_iso(row["updated_at"]),
    )


def _storage_credential_from_mapping(row) -> TenantStorageCredentialRecord:
    return TenantStorageCredentialRecord(
        provider=str(row["provider"]),
        credential_type=str(row["credential_type"]),
        encrypted_payload=str(row["encrypted_payload"]),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
    )


def _compose_storage_settings(
    *,
    config: TenantStorageConfigRecord,
    credential: TenantStorageCredentialRecord | None,
) -> TenantStorageSettingsRecord:
    return TenantStorageSettingsRecord(
        provider=config.provider,
        connection_status=config.connection_status,
        account_email=config.account_email,
        folder_label=config.folder_label,
        folder_path_hint=config.folder_path_hint,
        provider_folder_id=config.provider_folder_id,
        provider_folder_url=config.provider_folder_url,
        managed_fallback_enabled=config.managed_fallback_enabled,
        last_validated_at=config.last_validated_at,
        last_validation_error=config.last_validation_error,
        has_credentials=credential is not None,
        credential_type=credential.credential_type if credential is not None else None,
        credential_updated_at=credential.updated_at if credential is not None else None,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


class SqlAdminRepository:
    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        if bootstrap_schema:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def create_tenant(
        self,
        *,
        name: str,
        slug: str,
        plan_code: str = "free_trial",
        is_active: bool = True,
    ) -> TenantRecord:
        tenant_id = str(uuid4())
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                insert(TENANTS_TABLE).values(
                    id=tenant_id,
                    name=name,
                    slug=slug,
                    plan_code=plan_code,
                    is_active=is_active,
                    created_at=now,
                    updated_at=now,
                )
            )
        result = self.get_tenant(tenant_id=tenant_id)
        if result is None:
            raise RuntimeError(f"tenant {tenant_id} not found after creation")
        return result

    def get_tenant_by_slug(self, *, slug: str) -> TenantRecord | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(TENANTS_TABLE).where(TENANTS_TABLE.c.slug == slug)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _tenant_from_mapping(row)

    def get_tenant(self, *, tenant_id: str) -> TenantRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(TENANTS_TABLE).where(
                        TENANTS_TABLE.c.id == normalized_tenant_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _tenant_from_mapping(row)

    def list_active_tenants(self) -> list[TenantRecord]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(TENANTS_TABLE)
                    .where(TENANTS_TABLE.c.is_active.is_(True))
                    .order_by(TENANTS_TABLE.c.created_at, TENANTS_TABLE.c.id)
                )
                .mappings()
                .all()
            )
        return [_tenant_from_mapping(row) for row in rows]

    def get_tenant_settings(self, *, tenant_id: str) -> TenantSettingsRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(TENANT_SETTINGS_TABLE).where(
                        TENANT_SETTINGS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return TenantSettingsRecord(
                support_email=None,
                billing_contact_email=None,
                timezone="Asia/Bangkok",
                locale="th-TH",
                daily_digest_enabled=True,
                weekly_digest_enabled=False,
                crawl_interval_hours=None,
                created_at=None,
                updated_at=None,
            )
        return _settings_from_mapping(row)

    def update_tenant_settings(
        self,
        *,
        tenant_id: str,
        support_email: str | None = None,
        billing_contact_email: str | None = None,
        timezone: str | None = None,
        locale: str | None = None,
        daily_digest_enabled: bool | None = None,
        weekly_digest_enabled: bool | None = None,
        crawl_interval_hours: int | None = None,
    ) -> TenantSettingsRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        now = _now()
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(TENANT_SETTINGS_TABLE).where(
                        TENANT_SETTINGS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(
                    insert(TENANT_SETTINGS_TABLE).values(
                        id=str(uuid4()),
                        tenant_id=normalized_tenant_id,
                        support_email=support_email,
                        billing_contact_email=billing_contact_email,
                        timezone=timezone or "Asia/Bangkok",
                        locale=locale or "th-TH",
                        daily_digest_enabled=(
                            True
                            if daily_digest_enabled is None
                            else bool(daily_digest_enabled)
                        ),
                        weekly_digest_enabled=(
                            False
                            if weekly_digest_enabled is None
                            else bool(weekly_digest_enabled)
                        ),
                        crawl_interval_hours=crawl_interval_hours,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    update(TENANT_SETTINGS_TABLE)
                    .where(TENANT_SETTINGS_TABLE.c.id == existing["id"])
                    .values(
                        support_email=(
                            existing["support_email"]
                            if support_email is None
                            else support_email
                        ),
                        billing_contact_email=(
                            existing["billing_contact_email"]
                            if billing_contact_email is None
                            else billing_contact_email
                        ),
                        timezone=existing["timezone"] if timezone is None else timezone,
                        locale=existing["locale"] if locale is None else locale,
                        daily_digest_enabled=(
                            existing["daily_digest_enabled"]
                            if daily_digest_enabled is None
                            else bool(daily_digest_enabled)
                        ),
                        weekly_digest_enabled=(
                            existing["weekly_digest_enabled"]
                            if weekly_digest_enabled is None
                            else bool(weekly_digest_enabled)
                        ),
                        crawl_interval_hours=(
                            existing["crawl_interval_hours"]
                            if crawl_interval_hours is None
                            else int(crawl_interval_hours)
                        ),
                        updated_at=now,
                    )
                )
        return self.get_tenant_settings(tenant_id=normalized_tenant_id)

    def get_tenant_storage_settings(
        self, *, tenant_id: str
    ) -> TenantStorageSettingsRecord:
        config = self.get_tenant_storage_config(tenant_id=tenant_id)
        credential = (
            self.get_tenant_storage_credentials(
                tenant_id=tenant_id, provider=config.provider
            )
            if config.provider != "managed"
            else None
        )
        return _compose_storage_settings(config=config, credential=credential)

    def get_tenant_storage_config(self, *, tenant_id: str) -> TenantStorageConfigRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(TENANT_STORAGE_CONFIGS_TABLE).where(
                        TENANT_STORAGE_CONFIGS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return TenantStorageConfigRecord(
                provider="managed",
                connection_status="managed",
                account_email=None,
                folder_label=None,
                folder_path_hint=None,
                provider_folder_id=None,
                provider_folder_url=None,
                managed_fallback_enabled=False,
                last_validated_at=None,
                last_validation_error=None,
                created_at=None,
                updated_at=None,
            )
        return _storage_config_from_mapping(row)

    def update_tenant_storage_settings(
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
    ) -> TenantStorageSettingsRecord:
        self.update_tenant_storage_config(
            tenant_id=tenant_id,
            provider=provider,
            connection_status=connection_status,
            account_email=account_email,
            folder_label=folder_label,
            folder_path_hint=folder_path_hint,
            provider_folder_id=provider_folder_id,
            provider_folder_url=provider_folder_url,
            managed_fallback_enabled=managed_fallback_enabled,
            last_validated_at=last_validated_at,
            last_validation_error=last_validation_error,
        )
        return self.get_tenant_storage_settings(tenant_id=tenant_id)

    def update_tenant_storage_config(
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
    ) -> TenantStorageConfigRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        now = _now()
        normalized_account_email = _normalize_optional_text(account_email)
        normalized_folder_label = _normalize_optional_text(folder_label)
        normalized_folder_path_hint = _normalize_optional_text(folder_path_hint)
        normalized_provider_folder_id = _normalize_optional_text(provider_folder_id)
        normalized_provider_folder_url = _normalize_optional_text(provider_folder_url)
        normalized_last_validation_error = _normalize_optional_text(
            last_validation_error
        )
        resolved_last_validated_at = (
            datetime.fromisoformat(last_validated_at) if last_validated_at else None
        )
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(TENANT_STORAGE_CONFIGS_TABLE).where(
                        TENANT_STORAGE_CONFIGS_TABLE.c.tenant_id == normalized_tenant_id
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(
                    insert(TENANT_STORAGE_CONFIGS_TABLE).values(
                        id=str(uuid4()),
                        tenant_id=normalized_tenant_id,
                        provider=provider or "managed",
                        connection_status=connection_status or "managed",
                        account_email=normalized_account_email,
                        folder_label=normalized_folder_label,
                        folder_path_hint=normalized_folder_path_hint,
                        provider_folder_id=normalized_provider_folder_id,
                        provider_folder_url=normalized_provider_folder_url,
                        managed_fallback_enabled=(
                            False
                            if managed_fallback_enabled is None
                            else bool(managed_fallback_enabled)
                        ),
                        last_validated_at=resolved_last_validated_at,
                        last_validation_error=normalized_last_validation_error,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    update(TENANT_STORAGE_CONFIGS_TABLE)
                    .where(TENANT_STORAGE_CONFIGS_TABLE.c.id == existing["id"])
                    .values(
                        provider=existing["provider"] if provider is None else provider,
                        connection_status=(
                            existing["connection_status"]
                            if connection_status is None
                            else connection_status
                        ),
                        account_email=(
                            existing["account_email"]
                            if account_email is None
                            else normalized_account_email
                        ),
                        folder_label=(
                            existing["folder_label"]
                            if folder_label is None
                            else normalized_folder_label
                        ),
                        folder_path_hint=(
                            existing["folder_path_hint"]
                            if folder_path_hint is None
                            else normalized_folder_path_hint
                        ),
                        provider_folder_id=(
                            existing["provider_folder_id"]
                            if provider_folder_id is None
                            else normalized_provider_folder_id
                        ),
                        provider_folder_url=(
                            existing["provider_folder_url"]
                            if provider_folder_url is None
                            else normalized_provider_folder_url
                        ),
                        managed_fallback_enabled=(
                            existing["managed_fallback_enabled"]
                            if managed_fallback_enabled is None
                            else bool(managed_fallback_enabled)
                        ),
                        last_validated_at=(
                            existing["last_validated_at"]
                            if last_validated_at is None
                            else resolved_last_validated_at
                        ),
                        last_validation_error=(
                            existing["last_validation_error"]
                            if last_validation_error is None
                            else normalized_last_validation_error
                        ),
                        updated_at=now,
                    )
                )
        return self.get_tenant_storage_config(tenant_id=normalized_tenant_id)

    def get_tenant_storage_credentials(
        self,
        *,
        tenant_id: str,
        provider: str,
    ) -> TenantStorageCredentialRecord | None:
        if provider == "managed":
            return None
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(TENANT_STORAGE_CREDENTIALS_TABLE).where(
                        TENANT_STORAGE_CREDENTIALS_TABLE.c.tenant_id
                        == normalized_tenant_id,
                        TENANT_STORAGE_CREDENTIALS_TABLE.c.provider == provider,
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _storage_credential_from_mapping(row)

    def upsert_tenant_storage_credentials(
        self,
        *,
        tenant_id: str,
        provider: str,
        credential_type: str,
        encrypted_payload: str,
    ) -> TenantStorageCredentialRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        now = _now()
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(TENANT_STORAGE_CREDENTIALS_TABLE).where(
                        TENANT_STORAGE_CREDENTIALS_TABLE.c.tenant_id
                        == normalized_tenant_id,
                        TENANT_STORAGE_CREDENTIALS_TABLE.c.provider == provider,
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(
                    insert(TENANT_STORAGE_CREDENTIALS_TABLE).values(
                        id=str(uuid4()),
                        tenant_id=normalized_tenant_id,
                        provider=provider,
                        credential_type=credential_type,
                        encrypted_payload=encrypted_payload,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                connection.execute(
                    update(TENANT_STORAGE_CREDENTIALS_TABLE)
                    .where(TENANT_STORAGE_CREDENTIALS_TABLE.c.id == existing["id"])
                    .values(
                        credential_type=credential_type,
                        encrypted_payload=encrypted_payload,
                        updated_at=now,
                    )
                )
        result = self.get_tenant_storage_credentials(
            tenant_id=normalized_tenant_id,
            provider=provider,
        )
        if result is None:
            raise RuntimeError("tenant storage credentials missing after upsert")
        return result

    def delete_tenant_storage_credentials(
        self,
        *,
        tenant_id: str,
        provider: str,
    ) -> None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(TENANT_STORAGE_CREDENTIALS_TABLE).where(
                        TENANT_STORAGE_CREDENTIALS_TABLE.c.tenant_id
                        == normalized_tenant_id,
                        TENANT_STORAGE_CREDENTIALS_TABLE.c.provider == provider,
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                return
            connection.execute(
                TENANT_STORAGE_CREDENTIALS_TABLE.delete().where(
                    TENANT_STORAGE_CREDENTIALS_TABLE.c.id == existing["id"]
                )
            )


def create_admin_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlAdminRepository:
    return SqlAdminRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
