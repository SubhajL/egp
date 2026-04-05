"""Webhook delivery for machine-consumable notification events."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

import httpx

from egp_notifications.service import Notification
from egp_shared_types.enums import NotificationType


@dataclass(frozen=True, slots=True)
class WebhookTransportResult:
    status_code: int
    body: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookDispatchTarget:
    id: str
    tenant_id: str
    name: str
    url: str
    signing_secret: str
    notification_types: list[str]


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
    delivered_at: str | None


class WebhookTransport(Protocol):
    def __call__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> WebhookTransportResult: ...


class WebhookDeliveryStore(Protocol):
    def list_active_webhook_subscriptions(
        self,
        *,
        tenant_id: str,
        notification_type: NotificationType | str,
    ) -> list[WebhookDispatchTarget]: ...

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
    ) -> WebhookDeliveryRecord: ...

    def record_webhook_delivery_attempt(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
        delivery_status: str,
        response_status_code: int | None = None,
        response_body: str | None = None,
        delivered: bool = False,
    ) -> WebhookDeliveryRecord: ...


def _default_transport(
    *,
    url: str,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: float,
) -> WebhookTransportResult:
    response = httpx.post(
        url,
        content=body,
        headers=headers,
        timeout=timeout_seconds,
    )
    return WebhookTransportResult(
        status_code=response.status_code,
        body=response.text,
    )


def _build_webhook_payload(
    notification: Notification,
    *,
    template_vars: dict[str, str] | None,
) -> dict[str, object]:
    return {
        "event_id": notification.id,
        "event_type": notification.notification_type.value,
        "tenant_id": notification.tenant_id,
        "project_id": notification.project_id,
        "created_at": notification.created_at,
        "notification": {
            "id": notification.id,
            "channel": notification.channel,
            "subject": notification.subject,
            "body": notification.body,
            "status": notification.status,
            "sent_at": notification.sent_at,
        },
        "template_vars": dict(template_vars or {}),
    }


def _build_signature(*, signing_secret: str, body: bytes) -> str:
    digest = hmac.new(
        str(signing_secret).encode("utf-8"),
        body,
        sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _is_success_status(status_code: int) -> bool:
    return 200 <= int(status_code) < 300


def _is_retryable_status(status_code: int) -> bool:
    return int(status_code) == 429 or int(status_code) >= 500


class WebhookDeliveryService:
    def __init__(
        self,
        *,
        repository: WebhookDeliveryStore,
        transport: WebhookTransport | None = None,
        timeout_seconds: float = 5.0,
        max_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._transport = transport or _default_transport
        self._timeout_seconds = float(timeout_seconds)
        self._max_attempts = max(1, int(max_attempts))

    def deliver(
        self,
        *,
        notification: Notification,
        template_vars: dict[str, str] | None = None,
    ) -> bool:
        targets = self._repository.list_active_webhook_subscriptions(
            tenant_id=notification.tenant_id,
            notification_type=notification.notification_type,
        )
        if not targets:
            return False

        delivered_any = False
        payload = _build_webhook_payload(notification, template_vars=template_vars)
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        for target in targets:
            delivery = self._repository.create_or_get_webhook_delivery(
                tenant_id=notification.tenant_id,
                webhook_subscription_id=target.id,
                notification_id=notification.id,
                event_id=notification.id,
                notification_type=notification.notification_type,
                project_id=notification.project_id,
                payload=payload,
            )
            if delivery.delivery_status == "delivered":
                delivered_any = True
                continue
            headers = {
                "Content-Type": "application/json",
                "X-EGP-Event-ID": notification.id,
                "X-EGP-Event-Type": notification.notification_type.value,
                "X-EGP-Tenant-ID": notification.tenant_id,
                "X-EGP-Signature-256": _build_signature(
                    signing_secret=target.signing_secret,
                    body=body,
                ),
            }

            for attempt_number in range(self._max_attempts):
                try:
                    result = self._transport(
                        url=target.url,
                        headers=headers,
                        body=body,
                        timeout_seconds=self._timeout_seconds,
                    )
                    if _is_success_status(result.status_code):
                        self._repository.record_webhook_delivery_attempt(
                            tenant_id=notification.tenant_id,
                            delivery_id=delivery.id,
                            delivery_status="delivered",
                            response_status_code=result.status_code,
                            response_body=result.body,
                            delivered=True,
                        )
                        delivered_any = True
                        break

                    retryable = _is_retryable_status(result.status_code)
                    self._repository.record_webhook_delivery_attempt(
                        tenant_id=notification.tenant_id,
                        delivery_id=delivery.id,
                        delivery_status=(
                            "pending"
                            if retryable and attempt_number + 1 < self._max_attempts
                            else "failed"
                        ),
                        response_status_code=result.status_code,
                        response_body=result.body,
                        delivered=False,
                    )
                    if not retryable:
                        break
                except Exception as exc:
                    self._repository.record_webhook_delivery_attempt(
                        tenant_id=notification.tenant_id,
                        delivery_id=delivery.id,
                        delivery_status=(
                            "pending"
                            if attempt_number + 1 < self._max_attempts
                            else "failed"
                        ),
                        response_status_code=None,
                        response_body=str(exc),
                        delivered=False,
                    )

        return delivered_any
