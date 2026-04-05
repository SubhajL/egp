"""Tenant-scoped notification persistence and recipient lookup."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    Table,
    UniqueConstraint,
    and_,
    desc,
)
from sqlalchemy import Column, insert, select, update
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_notifications.service import Notification
from egp_shared_types.enums import NotificationType, UserRole


DEFAULT_EMAIL_ENABLED_ROLES = {
    UserRole.OWNER.value,
    UserRole.ADMIN.value,
    UserRole.ANALYST.value,
}

METADATA = DB_METADATA

USERS_TABLE = Table(
    "users",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("email", String, nullable=False),
    Column("full_name", String, nullable=True),
    Column("role", String, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "email", name="users_tenant_email_uq"),
    CheckConstraint(
        "role IN ('owner', 'admin', 'analyst', 'viewer')",
        name="users_role_check",
    ),
    CheckConstraint(
        "status IN ('active', 'suspended', 'deactivated')",
        name="users_status_check",
    ),
)

NOTIFICATIONS_TABLE = Table(
    "notifications",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=True),
    Column("notification_type", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("status", String, nullable=False),
    Column("payload", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=True),
)

NOTIFICATION_PREFERENCES_TABLE = Table(
    "notification_preferences",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("user_id", UUID_SQL_TYPE, nullable=False),
    Column("notification_type", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("is_enabled", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "user_id",
        "notification_type",
        "channel",
        name="notification_prefs_uq",
    ),
    CheckConstraint(
        "channel IN ('email', 'in_app', 'webhook', 'line')",
        name="notification_prefs_channel_check",
    ),
)


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: str
    tenant_id: str
    email: str
    full_name: str | None
    role: str
    status: str
    created_at: str
    updated_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _from_notification_row(row: RowMapping) -> Notification:
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    return Notification(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        notification_type=NotificationType(str(row["notification_type"])),
        channel=str(row["channel"]),
        subject=str(payload.get("subject") or ""),
        body=str(payload.get("body") or ""),
        status=str(row["status"]),
        created_at=_to_iso(row["created_at"]) or "",
        sent_at=_to_iso(row["sent_at"]),
    )


def _from_user_row(row: RowMapping) -> UserRecord:
    return UserRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]) if row["full_name"] is not None else None,
        role=str(row["role"]),
        status=str(row["status"]),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
    )


class SqlNotificationRepository:
    """Persistent notification store plus recipient lookup."""

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

    def add(self, notification: Notification) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                insert(NOTIFICATIONS_TABLE).values(
                    id=normalize_uuid_string(notification.id),
                    tenant_id=normalize_uuid_string(notification.tenant_id),
                    project_id=(
                        normalize_uuid_string(notification.project_id)
                        if notification.project_id is not None
                        else None
                    ),
                    notification_type=notification.notification_type.value,
                    channel=notification.channel,
                    status=notification.status,
                    payload={
                        "subject": notification.subject,
                        "body": notification.body,
                    },
                    created_at=datetime.fromisoformat(notification.created_at),
                    sent_at=(
                        datetime.fromisoformat(notification.sent_at)
                        if notification.sent_at is not None
                        else None
                    ),
                )
            )

    def list_for_tenant(self, tenant_id: str, *, limit: int = 50) -> list[Notification]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(NOTIFICATIONS_TABLE)
                    .where(NOTIFICATIONS_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(desc(NOTIFICATIONS_TABLE.c.created_at))
                    .limit(max(1, int(limit)))
                )
                .mappings()
                .all()
            )
        return [_from_notification_row(row) for row in rows]

    def mark_read(self, notification_id: str) -> bool:
        normalized_notification_id = normalize_uuid_string(notification_id)
        with self._engine.begin() as connection:
            result = connection.execute(
                update(NOTIFICATIONS_TABLE)
                .where(NOTIFICATIONS_TABLE.c.id == normalized_notification_id)
                .values(status="read")
            )
        return bool(result.rowcount)

    def create_user(
        self,
        *,
        tenant_id: str,
        email: str,
        role: UserRole | str = UserRole.VIEWER,
        status: str = "active",
        full_name: str | None = None,
    ) -> dict[str, str]:
        now = _now()
        user_id = str(uuid4())
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_role = role.value if isinstance(role, UserRole) else str(role)
        with self._engine.begin() as connection:
            connection.execute(
                insert(USERS_TABLE).values(
                    id=user_id,
                    tenant_id=normalized_tenant_id,
                    email=str(email).strip(),
                    full_name=full_name,
                    role=normalized_role,
                    status=str(status).strip(),
                    created_at=now,
                    updated_at=now,
                )
            )
        return {
            "id": user_id,
            "tenant_id": normalized_tenant_id,
            "email": str(email).strip(),
        }

    def list_users(self, *, tenant_id: str) -> list[UserRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(USERS_TABLE)
                    .where(USERS_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(USERS_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
        return [_from_user_row(row) for row in rows]

    def get_user(self, *, tenant_id: str, user_id: str) -> UserRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_user_id = normalize_uuid_string(user_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(USERS_TABLE).where(
                        and_(
                            USERS_TABLE.c.tenant_id == normalized_tenant_id,
                            USERS_TABLE.c.id == normalized_user_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _from_user_row(row)

    def update_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: UserRole | str | None = None,
        status: str | None = None,
        full_name: str | None = None,
    ) -> UserRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_user_id = normalize_uuid_string(user_id)
        existing = self.get_user(tenant_id=normalized_tenant_id, user_id=normalized_user_id)
        if existing is None:
            raise KeyError(normalized_user_id)
        normalized_role = (
            role.value if isinstance(role, UserRole) else str(role).strip()
            if role is not None
            else existing.role
        )
        normalized_status = (
            str(status).strip() if status is not None else existing.status
        )
        next_full_name = existing.full_name if full_name is None else str(full_name).strip() or None
        with self._engine.begin() as connection:
            connection.execute(
                update(USERS_TABLE)
                .where(
                    and_(
                        USERS_TABLE.c.tenant_id == normalized_tenant_id,
                        USERS_TABLE.c.id == normalized_user_id,
                    )
                )
                .values(
                    role=normalized_role,
                    status=normalized_status,
                    full_name=next_full_name,
                    updated_at=_now(),
                )
            )
        updated = self.get_user(tenant_id=normalized_tenant_id, user_id=normalized_user_id)
        if updated is None:
            raise KeyError(normalized_user_id)
        return updated

    def set_email_preference(
        self,
        *,
        tenant_id: str,
        user_id: str,
        notification_type: NotificationType | str,
        enabled: bool,
    ) -> None:
        now = _now()
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_user_id = normalize_uuid_string(user_id)
        normalized_type = (
            notification_type.value
            if isinstance(notification_type, NotificationType)
            else str(notification_type).strip()
        )
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(NOTIFICATION_PREFERENCES_TABLE.c.id).where(
                        and_(
                            NOTIFICATION_PREFERENCES_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            NOTIFICATION_PREFERENCES_TABLE.c.user_id
                            == normalized_user_id,
                            NOTIFICATION_PREFERENCES_TABLE.c.notification_type
                            == normalized_type,
                            NOTIFICATION_PREFERENCES_TABLE.c.channel == "email",
                        )
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(
                    insert(NOTIFICATION_PREFERENCES_TABLE).values(
                        id=str(uuid4()),
                        tenant_id=normalized_tenant_id,
                        user_id=normalized_user_id,
                        notification_type=normalized_type,
                        channel="email",
                        is_enabled=bool(enabled),
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            connection.execute(
                update(NOTIFICATION_PREFERENCES_TABLE)
                .where(NOTIFICATION_PREFERENCES_TABLE.c.id == existing["id"])
                .values(is_enabled=bool(enabled), updated_at=now)
            )

    def list_recipient_emails(
        self,
        *,
        tenant_id: str,
        notification_type: NotificationType,
    ) -> list[str]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            users = (
                connection.execute(
                    select(USERS_TABLE)
                    .where(USERS_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(USERS_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
            preferences = (
                connection.execute(
                    select(NOTIFICATION_PREFERENCES_TABLE).where(
                        and_(
                            NOTIFICATION_PREFERENCES_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            NOTIFICATION_PREFERENCES_TABLE.c.notification_type
                            == notification_type.value,
                            NOTIFICATION_PREFERENCES_TABLE.c.channel == "email",
                        )
                    )
                )
                .mappings()
                .all()
            )

        preference_by_user_id = {
            str(row["user_id"]): bool(row["is_enabled"]) for row in preferences
        }
        recipients: list[str] = []
        for row in users:
            user = _from_user_row(row)
            if user.status != "active":
                continue
            explicit = preference_by_user_id.get(user.id)
            if explicit is False:
                continue
            if explicit is True or user.role in DEFAULT_EMAIL_ENABLED_ROLES:
                recipients.append(user.email)
        return recipients

    def get_email_preferences(self, *, tenant_id: str, user_id: str) -> dict[str, bool]:
        user = self.get_user(tenant_id=tenant_id, user_id=user_id)
        if user is None:
            raise KeyError(normalize_uuid_string(user_id))
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_user_id = normalize_uuid_string(user_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(NOTIFICATION_PREFERENCES_TABLE).where(
                        and_(
                            NOTIFICATION_PREFERENCES_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            NOTIFICATION_PREFERENCES_TABLE.c.user_id
                            == normalized_user_id,
                            NOTIFICATION_PREFERENCES_TABLE.c.channel == "email",
                        )
                    )
                )
                .mappings()
                .all()
            )
        explicit_by_type = {
            str(row["notification_type"]): bool(row["is_enabled"]) for row in rows
        }
        defaults_enabled = user.role in DEFAULT_EMAIL_ENABLED_ROLES
        return {
            notification_type.value: explicit_by_type.get(notification_type.value, defaults_enabled)
            for notification_type in NotificationType
        }

    def replace_email_preferences(
        self,
        *,
        tenant_id: str,
        user_id: str,
        email_preferences: dict[str, bool],
    ) -> dict[str, bool]:
        normalized_user_id = normalize_uuid_string(user_id)
        user = self.get_user(tenant_id=tenant_id, user_id=normalized_user_id)
        if user is None:
            raise KeyError(normalized_user_id)
        for notification_type, enabled in email_preferences.items():
            self.set_email_preference(
                tenant_id=tenant_id,
                user_id=normalized_user_id,
                notification_type=notification_type,
                enabled=enabled,
            )
        return self.get_email_preferences(tenant_id=tenant_id, user_id=normalized_user_id)


def create_notification_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlNotificationRepository:
    return SqlNotificationRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
