"""Reusable notification dispatcher for platform events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from egp_notifications.service import Notification, NotificationService
from egp_notifications.webhook_delivery import WebhookDeliveryService
from egp_shared_types.enums import NotificationType


class NotificationRecipientResolver(Protocol):
    def list_recipient_emails(
        self,
        *,
        tenant_id: str,
        notification_type: NotificationType,
    ) -> list[str]: ...


@dataclass(slots=True)
class NotificationDispatcher:
    service: NotificationService
    recipient_resolver: NotificationRecipientResolver
    webhook_delivery_service: WebhookDeliveryService | None = None

    def dispatch(
        self,
        *,
        tenant_id: str,
        notification_type: NotificationType,
        project_id: str | None = None,
        template_vars: dict[str, str] | None = None,
    ) -> Notification:
        recipients = self.recipient_resolver.list_recipient_emails(
            tenant_id=tenant_id,
            notification_type=notification_type,
        )
        created = self.service.send(
            tenant_id=tenant_id,
            notification_type=notification_type,
            project_id=project_id,
            recipient_emails=recipients,
            template_vars=template_vars,
        )
        if self.webhook_delivery_service is None:
            return created
        queued = self.webhook_delivery_service.enqueue(
            notification=created,
            template_vars=template_vars,
        )
        if not queued or "webhook" in created.channel.split(","):
            return created
        return Notification(
            id=created.id,
            tenant_id=created.tenant_id,
            project_id=created.project_id,
            notification_type=created.notification_type,
            channel=f"{created.channel},webhook",
            subject=created.subject,
            body=created.body,
            status=created.status,
            created_at=created.created_at,
            sent_at=created.sent_at,
        )
