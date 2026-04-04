"""Reusable notification dispatcher for platform events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from egp_notifications.service import Notification, NotificationService
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
        return self.service.send(
            tenant_id=tenant_id,
            notification_type=notification_type,
            project_id=project_id,
            recipient_emails=recipients,
            template_vars=template_vars,
        )
