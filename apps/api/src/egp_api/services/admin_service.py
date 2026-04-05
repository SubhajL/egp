"""Admin service for tenant settings, users, and billing visibility."""

from __future__ import annotations

from dataclasses import dataclass

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


def _user_view(
    user: UserRecord, *, notification_preferences: dict[str, bool]
) -> AdminUserView:
    return AdminUserView(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        status=user.status,
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
    ) -> None:
        self._admin_repository = admin_repository
        self._notification_repository = notification_repository
        self._billing_repository = billing_repository

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
    ) -> AdminUserView:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        created = self._notification_repository.create_user(
            tenant_id=tenant_id,
            email=email,
            full_name=full_name,
            role=role,
            status=status,
        )
        user = self._notification_repository.get_user(
            tenant_id=tenant_id,
            user_id=created["id"],
        )
        if user is None:
            raise KeyError(created["id"])
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
    ) -> AdminUserView:
        user = self._notification_repository.update_user(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            status=status,
            full_name=full_name,
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
    ) -> TenantSettingsRecord:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        return self._admin_repository.update_tenant_settings(
            tenant_id=tenant_id,
            support_email=support_email,
            billing_contact_email=billing_contact_email,
            timezone=timezone,
            locale=locale,
            daily_digest_enabled=daily_digest_enabled,
            weekly_digest_enabled=weekly_digest_enabled,
        )
