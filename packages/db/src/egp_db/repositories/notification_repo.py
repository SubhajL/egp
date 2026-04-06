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
    Integer,
    String,
    Table,
    UniqueConstraint,
    and_,
    desc,
    or_,
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
    Column("password_hash", String, nullable=True),
    Column("email_verified_at", DateTime(timezone=True), nullable=True),
    Column("mfa_secret", String, nullable=True),
    Column("mfa_enabled", Boolean, nullable=False, default=False),
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

WEBHOOK_SUBSCRIPTIONS_TABLE = Table(
    "webhook_subscriptions",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("name", String, nullable=False),
    Column("url", String, nullable=False),
    Column("signing_secret", String, nullable=False),
    Column("notification_types", JSON, nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
)

WEBHOOK_DELIVERIES_TABLE = Table(
    "webhook_deliveries",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("webhook_subscription_id", UUID_SQL_TYPE, nullable=False),
    Column("notification_id", UUID_SQL_TYPE, nullable=False),
    Column("event_id", String, nullable=False),
    Column("notification_type", String, nullable=False),
    Column("project_id", UUID_SQL_TYPE, nullable=True),
    Column("payload", JSON, nullable=False),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("delivery_status", String, nullable=False, default="pending"),
    Column("last_response_status_code", Integer, nullable=True),
    Column("last_response_body", String, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_attempted_at", DateTime(timezone=True), nullable=True),
    Column("next_attempt_at", DateTime(timezone=True), nullable=True),
    Column("processing_started_at", DateTime(timezone=True), nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "webhook_subscription_id",
        "event_id",
        name="webhook_deliveries_subscription_event_uq",
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
    email_verified_at: str | None
    mfa_enabled: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WebhookSubscriptionRecord:
    id: str
    tenant_id: str
    name: str
    url: str
    notification_types: list[str]
    is_active: bool
    created_at: str
    updated_at: str
    last_delivery_status: str | None
    last_delivery_attempted_at: str | None
    last_delivered_at: str | None
    last_response_status_code: int | None


@dataclass(frozen=True, slots=True)
class WebhookDispatchTarget:
    id: str
    tenant_id: str
    name: str
    url: str
    signing_secret: str
    notification_types: list[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WebhookDeliveryRecord:
    id: str
    tenant_id: str
    webhook_subscription_id: str
    notification_id: str
    event_id: str
    notification_type: str
    project_id: str | None
    payload: dict[str, object]
    attempt_count: int
    delivery_status: str
    last_response_status_code: int | None
    last_response_body: str | None
    created_at: str
    updated_at: str
    last_attempted_at: str | None
    next_attempt_at: str | None
    processing_started_at: str | None
    delivered_at: str | None


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
        email_verified_at=_to_iso(row["email_verified_at"]),
        mfa_enabled=bool(row["mfa_enabled"]),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
    )


def _normalize_notification_types(
    notification_types: list[NotificationType | str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for notification_type in notification_types:
        normalized = (
            notification_type.value
            if isinstance(notification_type, NotificationType)
            else str(notification_type).strip()
        )
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _from_webhook_subscription_row(
    row: RowMapping,
    *,
    summary_by_subscription_id: dict[str, WebhookDeliveryRecord] | None = None,
) -> WebhookSubscriptionRecord:
    summary = (
        summary_by_subscription_id.get(str(row["id"]))
        if summary_by_subscription_id is not None
        else None
    )
    raw_types = (
        row["notification_types"] if isinstance(row["notification_types"], list) else []
    )
    return WebhookSubscriptionRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        name=str(row["name"]),
        url=str(row["url"]),
        notification_types=[str(value) for value in raw_types],
        is_active=bool(row["is_active"]),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
        last_delivery_status=summary.delivery_status if summary is not None else None,
        last_delivery_attempted_at=(
            summary.last_attempted_at if summary is not None else None
        ),
        last_delivered_at=summary.delivered_at if summary is not None else None,
        last_response_status_code=(
            summary.last_response_status_code if summary is not None else None
        ),
    )


def _from_webhook_dispatch_row(row: RowMapping) -> WebhookDispatchTarget:
    raw_types = (
        row["notification_types"] if isinstance(row["notification_types"], list) else []
    )
    return WebhookDispatchTarget(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        name=str(row["name"]),
        url=str(row["url"]),
        signing_secret=str(row["signing_secret"]),
        notification_types=[str(value) for value in raw_types],
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
    )


def _from_webhook_delivery_row(row: RowMapping) -> WebhookDeliveryRecord:
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    return WebhookDeliveryRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        webhook_subscription_id=str(row["webhook_subscription_id"]),
        notification_id=str(row["notification_id"]),
        event_id=str(row["event_id"]),
        notification_type=str(row["notification_type"]),
        project_id=str(row["project_id"]) if row["project_id"] is not None else None,
        payload=dict(payload),
        attempt_count=int(row["attempt_count"]),
        delivery_status=str(row["delivery_status"]),
        last_response_status_code=(
            int(row["last_response_status_code"])
            if row["last_response_status_code"] is not None
            else None
        ),
        last_response_body=(
            str(row["last_response_body"])
            if row["last_response_body"] is not None
            else None
        ),
        created_at=_to_iso(row["created_at"]) or "",
        updated_at=_to_iso(row["updated_at"]) or "",
        last_attempted_at=_to_iso(row["last_attempted_at"]),
        next_attempt_at=_to_iso(row["next_attempt_at"]),
        processing_started_at=_to_iso(row["processing_started_at"]),
        delivered_at=_to_iso(row["delivered_at"]),
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
        password_hash: str | None = None,
        email_verified_at: str | None = None,
    ) -> dict[str, str]:
        now = _now()
        user_id = str(uuid4())
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_role = role.value if isinstance(role, UserRole) else str(role)
        normalized_email = str(email).strip().lower()
        with self._engine.begin() as connection:
            connection.execute(
                insert(USERS_TABLE).values(
                    id=user_id,
                    tenant_id=normalized_tenant_id,
                    email=normalized_email,
                    full_name=full_name,
                    role=normalized_role,
                    status=str(status).strip(),
                    password_hash=password_hash,
                    email_verified_at=(
                        datetime.fromisoformat(email_verified_at)
                        if email_verified_at is not None
                        else None
                    ),
                    mfa_secret=None,
                    mfa_enabled=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        return {
            "id": user_id,
            "tenant_id": normalized_tenant_id,
            "email": normalized_email,
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
        password_hash: str | None = None,
        email_verified_at: str | None = None,
    ) -> UserRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_user_id = normalize_uuid_string(user_id)
        existing = self.get_user(
            tenant_id=normalized_tenant_id, user_id=normalized_user_id
        )
        if existing is None:
            raise KeyError(normalized_user_id)
        normalized_role = (
            role.value
            if isinstance(role, UserRole)
            else str(role).strip()
            if role is not None
            else existing.role
        )
        normalized_status = (
            str(status).strip() if status is not None else existing.status
        )
        next_full_name = (
            existing.full_name if full_name is None else str(full_name).strip() or None
        )
        values: dict[str, object] = {
            "role": normalized_role,
            "status": normalized_status,
            "full_name": next_full_name,
            "updated_at": _now(),
        }
        if password_hash is not None:
            values["password_hash"] = password_hash
        if email_verified_at is not None:
            values["email_verified_at"] = datetime.fromisoformat(email_verified_at)
        with self._engine.begin() as connection:
            connection.execute(
                update(USERS_TABLE)
                .where(
                    and_(
                        USERS_TABLE.c.tenant_id == normalized_tenant_id,
                        USERS_TABLE.c.id == normalized_user_id,
                    )
                )
                .values(**values)
            )
        updated = self.get_user(
            tenant_id=normalized_tenant_id, user_id=normalized_user_id
        )
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
            notification_type.value: explicit_by_type.get(
                notification_type.value, defaults_enabled
            )
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
        return self.get_email_preferences(
            tenant_id=tenant_id, user_id=normalized_user_id
        )

    def create_webhook_subscription(
        self,
        *,
        tenant_id: str,
        name: str,
        url: str,
        notification_types: list[NotificationType | str],
        signing_secret: str,
    ) -> WebhookSubscriptionRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        now = _now()
        normalized_types = _normalize_notification_types(notification_types)
        subscription_id = str(uuid4())
        with self._engine.begin() as connection:
            connection.execute(
                insert(WEBHOOK_SUBSCRIPTIONS_TABLE).values(
                    id=subscription_id,
                    tenant_id=normalized_tenant_id,
                    name=str(name).strip(),
                    url=str(url).strip(),
                    signing_secret=str(signing_secret),
                    notification_types=normalized_types,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                    deleted_at=None,
                )
            )
        return self.get_webhook_subscription(
            tenant_id=normalized_tenant_id,
            webhook_id=subscription_id,
        )

    def get_webhook_subscription(
        self,
        *,
        tenant_id: str,
        webhook_id: str,
    ) -> WebhookSubscriptionRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_webhook_id = normalize_uuid_string(webhook_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(WEBHOOK_SUBSCRIPTIONS_TABLE).where(
                        and_(
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.id == normalized_webhook_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(normalized_webhook_id)
        summaries = self._latest_webhook_delivery_by_subscription(
            tenant_id=normalized_tenant_id
        )
        return _from_webhook_subscription_row(
            row,
            summary_by_subscription_id=summaries,
        )

    def list_webhook_subscriptions(
        self, *, tenant_id: str
    ) -> list[WebhookSubscriptionRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(WEBHOOK_SUBSCRIPTIONS_TABLE)
                    .where(
                        and_(
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.is_active.is_(True),
                        )
                    )
                    .order_by(desc(WEBHOOK_SUBSCRIPTIONS_TABLE.c.created_at))
                )
                .mappings()
                .all()
            )
        summaries = self._latest_webhook_delivery_by_subscription(
            tenant_id=normalized_tenant_id
        )
        return [
            _from_webhook_subscription_row(
                row,
                summary_by_subscription_id=summaries,
            )
            for row in rows
        ]

    def list_active_webhook_subscriptions(
        self,
        *,
        tenant_id: str,
        notification_type: NotificationType | str,
    ) -> list[WebhookDispatchTarget]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_type = (
            notification_type.value
            if isinstance(notification_type, NotificationType)
            else str(notification_type).strip()
        )
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(WEBHOOK_SUBSCRIPTIONS_TABLE)
                    .where(
                        and_(
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.is_active.is_(True),
                        )
                    )
                    .order_by(WEBHOOK_SUBSCRIPTIONS_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
        return [
            _from_webhook_dispatch_row(row)
            for row in rows
            if normalized_type
            in [str(value) for value in (row["notification_types"] or [])]
        ]

    def deactivate_webhook_subscription(
        self,
        *,
        tenant_id: str,
        webhook_id: str,
    ) -> bool:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_webhook_id = normalize_uuid_string(webhook_id)
        now = _now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(WEBHOOK_SUBSCRIPTIONS_TABLE)
                .where(
                    and_(
                        WEBHOOK_SUBSCRIPTIONS_TABLE.c.tenant_id == normalized_tenant_id,
                        WEBHOOK_SUBSCRIPTIONS_TABLE.c.id == normalized_webhook_id,
                        WEBHOOK_SUBSCRIPTIONS_TABLE.c.is_active.is_(True),
                    )
                )
                .values(
                    is_active=False,
                    deleted_at=now,
                    updated_at=now,
                )
            )
        return bool(result.rowcount)

    def create_or_get_webhook_delivery(
        self,
        *,
        tenant_id: str,
        webhook_subscription_id: str,
        notification_id: str,
        event_id: str,
        notification_type: NotificationType | str,
        project_id: str | None,
        payload: dict[str, object],
    ) -> WebhookDeliveryRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_subscription_id = normalize_uuid_string(webhook_subscription_id)
        normalized_notification_id = normalize_uuid_string(notification_id)
        normalized_type = (
            notification_type.value
            if isinstance(notification_type, NotificationType)
            else str(notification_type).strip()
        )
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE).where(
                        and_(
                            WEBHOOK_DELIVERIES_TABLE.c.webhook_subscription_id
                            == normalized_subscription_id,
                            WEBHOOK_DELIVERIES_TABLE.c.event_id
                            == str(event_id).strip(),
                        )
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(
                    insert(WEBHOOK_DELIVERIES_TABLE).values(
                        id=str(uuid4()),
                        tenant_id=normalized_tenant_id,
                        webhook_subscription_id=normalized_subscription_id,
                        notification_id=normalized_notification_id,
                        event_id=str(event_id).strip(),
                        notification_type=normalized_type,
                        project_id=(
                            normalize_uuid_string(project_id)
                            if project_id is not None
                            else None
                        ),
                        payload=payload,
                        attempt_count=0,
                        delivery_status="pending",
                        last_response_status_code=None,
                        last_response_body=None,
                        created_at=_now(),
                        updated_at=_now(),
                        last_attempted_at=None,
                        next_attempt_at=_now(),
                        processing_started_at=None,
                        delivered_at=None,
                    )
                )
                existing = (
                    connection.execute(
                        select(WEBHOOK_DELIVERIES_TABLE).where(
                            and_(
                                WEBHOOK_DELIVERIES_TABLE.c.webhook_subscription_id
                                == normalized_subscription_id,
                                WEBHOOK_DELIVERIES_TABLE.c.event_id
                                == str(event_id).strip(),
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
        if existing is None:
            raise KeyError(normalized_subscription_id)
        return _from_webhook_delivery_row(existing)

    def record_webhook_delivery_attempt(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
        delivery_status: str,
        response_status_code: int | None = None,
        response_body: str | None = None,
        delivered: bool = False,
        next_attempt_at: datetime | None = None,
        processing_started_at: datetime | None = None,
    ) -> WebhookDeliveryRecord:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_delivery_id = normalize_uuid_string(delivery_id)
        now = _now()
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE).where(
                        and_(
                            WEBHOOK_DELIVERIES_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            WEBHOOK_DELIVERIES_TABLE.c.id == normalized_delivery_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                raise KeyError(normalized_delivery_id)
            connection.execute(
                update(WEBHOOK_DELIVERIES_TABLE)
                .where(WEBHOOK_DELIVERIES_TABLE.c.id == normalized_delivery_id)
                .values(
                    attempt_count=int(existing["attempt_count"]) + 1,
                    delivery_status=str(delivery_status).strip(),
                    last_response_status_code=response_status_code,
                    last_response_body=(
                        str(response_body)[:2000] if response_body is not None else None
                    ),
                    updated_at=now,
                    last_attempted_at=now,
                    next_attempt_at=next_attempt_at,
                    processing_started_at=processing_started_at,
                    delivered_at=now if delivered else existing["delivered_at"],
                )
            )
            row = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE).where(
                        WEBHOOK_DELIVERIES_TABLE.c.id == normalized_delivery_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise KeyError(normalized_delivery_id)
        return _from_webhook_delivery_row(row)

    def list_webhook_deliveries(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
    ) -> list[WebhookDeliveryRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE)
                    .where(WEBHOOK_DELIVERIES_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(desc(WEBHOOK_DELIVERIES_TABLE.c.updated_at))
                    .limit(max(1, int(limit)))
                )
                .mappings()
                .all()
            )
        return [_from_webhook_delivery_row(row) for row in rows]

    def get_webhook_dispatch_target(
        self,
        *,
        tenant_id: str,
        webhook_subscription_id: str,
    ) -> WebhookDispatchTarget | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_subscription_id = normalize_uuid_string(webhook_subscription_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(WEBHOOK_SUBSCRIPTIONS_TABLE).where(
                        and_(
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.tenant_id == normalized_tenant_id,
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.id == normalized_subscription_id,
                            WEBHOOK_SUBSCRIPTIONS_TABLE.c.is_active.is_(True),
                        )
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _from_webhook_dispatch_row(row)

    def claim_pending_webhook_deliveries(
        self,
        *,
        limit: int = 10,
        stale_after_seconds: float = 60.0,
    ) -> list[WebhookDeliveryRecord]:
        now = _now()
        stale_cutoff = now.timestamp() - max(1.0, float(stale_after_seconds))
        stale_started_at = datetime.fromtimestamp(stale_cutoff, UTC)
        normalized_limit = max(1, int(limit))
        claimed_ids: list[str] = []
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE)
                    .where(
                        and_(
                            WEBHOOK_DELIVERIES_TABLE.c.delivery_status == "pending",
                            WEBHOOK_DELIVERIES_TABLE.c.delivered_at.is_(None),
                            WEBHOOK_DELIVERIES_TABLE.c.next_attempt_at <= now,
                        )
                    )
                    .order_by(WEBHOOK_DELIVERIES_TABLE.c.next_attempt_at)
                    .limit(normalized_limit)
                )
                .mappings()
                .all()
            )
            for row in rows:
                delivery_id = str(row["id"])
                started_at = row["processing_started_at"]
                if started_at is not None and started_at > stale_started_at:
                    continue
                updated = connection.execute(
                    update(WEBHOOK_DELIVERIES_TABLE)
                    .where(
                        and_(
                            WEBHOOK_DELIVERIES_TABLE.c.id == delivery_id,
                            WEBHOOK_DELIVERIES_TABLE.c.delivery_status == "pending",
                            WEBHOOK_DELIVERIES_TABLE.c.delivered_at.is_(None),
                            WEBHOOK_DELIVERIES_TABLE.c.next_attempt_at <= now,
                            or_(
                                WEBHOOK_DELIVERIES_TABLE.c.processing_started_at.is_(None),
                                WEBHOOK_DELIVERIES_TABLE.c.processing_started_at
                                <= stale_started_at,
                            ),
                        )
                    )
                    .values(
                        processing_started_at=now,
                        updated_at=now,
                    )
                )
                if updated.rowcount:
                    claimed_ids.append(delivery_id)
            if not claimed_ids:
                return []
            claimed_rows = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE).where(
                        WEBHOOK_DELIVERIES_TABLE.c.id.in_(claimed_ids)
                    )
                )
                .mappings()
                .all()
            )
        claimed_by_id = {
            str(row["id"]): _from_webhook_delivery_row(row) for row in claimed_rows
        }
        return [claimed_by_id[delivery_id] for delivery_id in claimed_ids if delivery_id in claimed_by_id]

    def _latest_webhook_delivery_by_subscription(
        self,
        *,
        tenant_id: str,
    ) -> dict[str, WebhookDeliveryRecord]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(WEBHOOK_DELIVERIES_TABLE)
                    .where(WEBHOOK_DELIVERIES_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(
                        desc(WEBHOOK_DELIVERIES_TABLE.c.updated_at),
                        desc(WEBHOOK_DELIVERIES_TABLE.c.created_at),
                    )
                )
                .mappings()
                .all()
            )
        latest: dict[str, WebhookDeliveryRecord] = {}
        for row in rows:
            record = _from_webhook_delivery_row(row)
            latest.setdefault(record.webhook_subscription_id, record)
        return latest


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
