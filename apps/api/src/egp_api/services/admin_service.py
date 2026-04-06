"""Admin service for tenant settings, users, and billing visibility."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from egp_db.repositories.auth_repo import hash_password
from egp_db.repositories.audit_repo import SqlAuditRepository
from egp_db.repositories.admin_repo import (
    SqlAdminRepository,
    TenantRecord,
    TenantSettingsRecord,
)
from egp_db.repositories.billing_repo import (
    BillingRecordRecord,
    BillingSubscriptionRecord,
    BillingSummary,
    SqlBillingRepository,
)
from egp_db.repositories.notification_repo import SqlNotificationRepository, UserRecord
from egp_shared_types.enums import NotificationType, UserRole


@dataclass(frozen=True, slots=True)
class AdminUserView:
    id: str
    email: str
    full_name: str | None
    role: str
    status: str
    email_verified_at: str | None
    mfa_enabled: bool
    created_at: str
    updated_at: str
    notification_preferences: dict[str, bool]


@dataclass(frozen=True, slots=True)
class AdminBillingView:
    summary: BillingSummary
    current_subscription: BillingSubscriptionRecord | None
    records: list[BillingRecordRecord]


@dataclass(frozen=True, slots=True)
class AdminSnapshot:
    tenant: TenantRecord
    settings: TenantSettingsRecord
    users: list[AdminUserView]
    billing: AdminBillingView


def _user_view(user: UserRecord, *, notification_preferences: dict[str, bool]) -> AdminUserView:
    return AdminUserView(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
        email_verified_at=user.email_verified_at,
        mfa_enabled=user.mfa_enabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        notification_preferences=notification_preferences,
    )


class AdminService:
    def __init__(
        self,
        admin_repository: SqlAdminRepository,
        notification_repository: SqlNotificationRepository,
        billing_repository: SqlBillingRepository,
        audit_repository: SqlAuditRepository | None = None,
    ) -> None:
        self._admin_repository = admin_repository
        self._notification_repository = notification_repository
        self._billing_repository = billing_repository
        self._audit_repository = audit_repository

    def get_snapshot(self, *, tenant_id: str) -> AdminSnapshot:
        tenant = self._admin_repository.get_tenant(tenant_id=tenant_id)
        if tenant is None:
            raise KeyError(tenant_id)
        settings = self._admin_repository.get_tenant_settings(tenant_id=tenant_id)
        users = self._notification_repository.list_users(tenant_id=tenant_id)
        billing_page = self._billing_repository.list_billing_records(
            tenant_id=tenant_id,
            limit=5,
            offset=0,
        )
        subscriptions = self._billing_repository.list_subscriptions_for_tenant(tenant_id=tenant_id)
        return AdminSnapshot(
            tenant=tenant,
            settings=settings,
            users=[
                _user_view(
                    user,
                    notification_preferences=self._notification_repository.get_email_preferences(
                        tenant_id=tenant_id,
                        user_id=user.id,
                    ),
                )
                for user in users
            ],
            billing=AdminBillingView(
                summary=billing_page.summary,
                current_subscription=subscriptions[0] if subscriptions else None,
                records=[detail.record for detail in billing_page.items],
            ),
        )

    def create_user(
        self,
        *,
        tenant_id: str,
        email: str,
        full_name: str | None = None,
        role: UserRole | str = UserRole.VIEWER,
        status: str = "active",
        password: str | None = None,
        actor_subject: str | None = None,
    ) -> AdminUserView:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        created = self._notification_repository.create_user(
            tenant_id=tenant_id,
            email=email,
            full_name=full_name,
            role=role,
            status=status,
            password_hash=hash_password(password) if password is not None else None,
            email_verified_at=datetime.now(UTC).isoformat() if password is not None else None,
        )
        user = self._notification_repository.get_user(
            tenant_id=tenant_id,
            user_id=created["id"],
        )
        if user is None:
            raise KeyError(created["id"])
        if self._audit_repository is not None:
            self._audit_repository.record_event(
                tenant_id=tenant_id,
                source="admin",
                entity_type="user",
                entity_id=user.id,
                actor_subject=actor_subject or "manual-operator",
                event_type="user.created",
                summary=f"Created user {user.email}",
                metadata_json={
                    "email": user.email,
                    "role": user.role,
                    "status": user.status,
                },
            )
        return _user_view(
            user,
            notification_preferences=self._notification_repository.get_email_preferences(
                tenant_id=tenant_id,
                user_id=user.id,
            ),
        )

    def update_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        role: UserRole | str | None = None,
        status: str | None = None,
        full_name: str | None = None,
        password: str | None = None,
        actor_subject: str | None = None,
    ) -> AdminUserView:
        previous = self._notification_repository.get_user(tenant_id=tenant_id, user_id=user_id)
        if previous is None:
            raise KeyError(user_id)
        user = self._notification_repository.update_user(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            status=status,
            full_name=full_name,
            password_hash=hash_password(password) if password is not None else None,
            email_verified_at=(
                datetime.now(UTC).isoformat()
                if password is not None and previous.email_verified_at is None
                else None
            ),
        )
        if self._audit_repository is not None:
            self._audit_repository.record_event(
                tenant_id=tenant_id,
                source="admin",
                entity_type="user",
                entity_id=user.id,
                actor_subject=actor_subject or "manual-operator",
                event_type="user.updated",
                summary=f"Updated user {user.email}",
                metadata_json={
                    "role_before": previous.role,
                    "role_after": user.role,
                    "status_before": previous.status,
                    "status_after": user.status,
                    "full_name_before": previous.full_name,
                    "full_name_after": user.full_name,
                },
            )
        return _user_view(
            user,
            notification_preferences=self._notification_repository.get_email_preferences(
                tenant_id=tenant_id,
                user_id=user.id,
            ),
        )

    def update_user_notification_preferences(
        self,
        *,
        tenant_id: str,
        user_id: str,
        email_preferences: dict[str, bool],
        actor_subject: str | None = None,
    ) -> AdminUserView:
        valid_types = {notification_type.value for notification_type in NotificationType}
        invalid = sorted(set(email_preferences) - valid_types)
        if invalid:
            raise ValueError(f"unsupported notification types: {', '.join(invalid)}")
        preferences = self._notification_repository.replace_email_preferences(
            tenant_id=tenant_id,
            user_id=user_id,
            email_preferences=email_preferences,
        )
        user = self._notification_repository.get_user(tenant_id=tenant_id, user_id=user_id)
        if user is None:
            raise KeyError(user_id)
        if self._audit_repository is not None:
            self._audit_repository.record_event(
                tenant_id=tenant_id,
                source="admin",
                entity_type="user",
                entity_id=user.id,
                actor_subject=actor_subject or "manual-operator",
                event_type="user.notification_preferences_updated",
                summary=f"Updated notification preferences for {user.email}",
                metadata_json={"email_preferences": preferences},
            )
        return _user_view(user, notification_preferences=preferences)

    def update_settings(
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
        actor_subject: str | None = None,
    ) -> TenantSettingsRecord:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        previous = self._admin_repository.get_tenant_settings(tenant_id=tenant_id)
        updated = self._admin_repository.update_tenant_settings(
            tenant_id=tenant_id,
            support_email=support_email,
            billing_contact_email=billing_contact_email,
            timezone=timezone,
            locale=locale,
            daily_digest_enabled=daily_digest_enabled,
            weekly_digest_enabled=weekly_digest_enabled,
            crawl_interval_hours=crawl_interval_hours,
        )
        if self._audit_repository is not None:
            self._audit_repository.record_event(
                tenant_id=tenant_id,
                source="admin",
                entity_type="tenant_settings",
                entity_id=tenant_id,
                actor_subject=actor_subject or "manual-operator",
                event_type="tenant.settings_updated",
                summary="Updated tenant settings",
                metadata_json={
                    "before": {
                        "support_email": previous.support_email,
                        "billing_contact_email": previous.billing_contact_email,
                        "timezone": previous.timezone,
                        "locale": previous.locale,
                        "daily_digest_enabled": previous.daily_digest_enabled,
                        "weekly_digest_enabled": previous.weekly_digest_enabled,
                        "crawl_interval_hours": previous.crawl_interval_hours,
                    },
                    "after": {
                        "support_email": updated.support_email,
                        "billing_contact_email": updated.billing_contact_email,
                        "timezone": updated.timezone,
                        "locale": updated.locale,
                        "daily_digest_enabled": updated.daily_digest_enabled,
                        "weekly_digest_enabled": updated.weekly_digest_enabled,
                        "crawl_interval_hours": updated.crawl_interval_hours,
                    },
                },
            )
        return updated
