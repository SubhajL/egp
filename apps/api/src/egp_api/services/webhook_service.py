"""Webhook subscription service for tenant-admin notification delivery."""

from __future__ import annotations

from dataclasses import dataclass

from egp_db.repositories.audit_repo import SqlAuditRepository
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
        audit_repository: SqlAuditRepository | None = None,
    ) -> None:
        self._admin_repository = admin_repository
        self._notification_repository = notification_repository
        self._audit_repository = audit_repository

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
        actor_subject: str | None = None,
    ) -> WebhookSubscriptionRecord:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        created = self._notification_repository.create_webhook_subscription(
            tenant_id=tenant_id,
            name=name,
            url=url,
            notification_types=notification_types,
            signing_secret=signing_secret,
        )
        if self._audit_repository is not None:
            self._audit_repository.record_event(
                tenant_id=tenant_id,
                source="admin",
                entity_type="webhook",
                entity_id=created.id,
                actor_subject=actor_subject or "manual-operator",
                event_type="webhook.created",
                summary=f"Created webhook {created.name}",
                metadata_json={
                    "url": created.url,
                    "notification_types": created.notification_types,
                },
            )
        return created

    def delete_webhook(
        self,
        *,
        tenant_id: str,
        webhook_id: str,
        actor_subject: str | None = None,
    ) -> None:
        if self._admin_repository.get_tenant(tenant_id=tenant_id) is None:
            raise KeyError(tenant_id)
        existing = self._notification_repository.get_webhook_subscription(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
        )
        deleted = self._notification_repository.deactivate_webhook_subscription(
            tenant_id=tenant_id,
            webhook_id=webhook_id,
        )
        if not deleted:
            raise KeyError(webhook_id)
        if self._audit_repository is not None:
            self._audit_repository.record_event(
                tenant_id=tenant_id,
                source="admin",
                entity_type="webhook",
                entity_id=existing.id,
                actor_subject=actor_subject or "manual-operator",
                event_type="webhook.deleted",
                summary=f"Deleted webhook {existing.name}",
                metadata_json={
                    "url": existing.url,
                    "notification_types": existing.notification_types,
                },
            )
