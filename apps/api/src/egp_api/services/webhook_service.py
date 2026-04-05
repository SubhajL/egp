"""Webhook subscription service for tenant-admin notification delivery."""

from __future__ import annotations

from dataclasses import dataclass

from egp_db.repositories.admin_repo import SqlAdminRepository
from egp_db.repositories.notification_repo import (
    SqlNotificationRepository,
    WebhookSubscriptionRecord,
)
from egp_shared_types.enums import NotificationType


@dataclass(frozen=True, slots=True)
class WebhookList:
    webhooks: list[WebhookSubscriptionRecord]


class WebhookService:
    def __init__(
        self,
        admin_repository: SqlAdminRepository,
        notification_repository: SqlNotificationRepository,
    ) -> None:
        self._admin_repository = admin_repository
        self._notification_repository = notification_repository

    def list_webhooks(self, *, tenant_id: str) -> WebhookList:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        return WebhookList(
            webhooks=self._notification_repository.list_webhook_subscriptions(
                tenant_id=tenant_id,
            )
        )

    def create_webhook(
        self,
        *,
        tenant_id: str,
        name: str,
        url: str,
        notification_types: list[NotificationType],
        signing_secret: str,
    ) -> WebhookSubscriptionRecord:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        return self._notification_repository.create_webhook_subscription(
            tenant_id=tenant_id,
            name=name,
            url=url,
            notification_types=notification_types,
            signing_secret=signing_secret,
        )

    def delete_webhook(self, *, tenant_id: str, webhook_id: str) -> None:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        deleted = self._notification_repository.deactivate_webhook_subscription(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
        )
        if not deleted:
            raise KeyError(webhook_id)
