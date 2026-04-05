from __future__ import annotations

import json

from egp_db.repositories.notification_repo import SqlNotificationRepository
from egp_notifications.dispatcher import NotificationDispatcher
from egp_notifications.service import Notification, NotificationService
from egp_notifications.webhook_delivery import (
    WebhookDeliveryService,
    WebhookTransportResult,
)
from egp_shared_types.enums import NotificationType, UserRole

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


class FakeWebhookTransport:
    def __init__(self, responses: list[WebhookTransportResult | Exception]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> WebhookTransportResult:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        response = self._responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def test_dispatch_uses_tenant_scoped_active_recipients_only(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_user(
        tenant_id=TENANT_ID,
        email="owner@example.com",
        role=UserRole.OWNER,
    )
    repository.create_user(
        tenant_id=TENANT_ID,
        email="viewer@example.com",
        role=UserRole.VIEWER,
    )
    repository.create_user(
        tenant_id=OTHER_TENANT_ID,
        email="other-owner@example.com",
        role=UserRole.OWNER,
    )
    repository.create_user(
        tenant_id=TENANT_ID,
        email="suspended-admin@example.com",
        role=UserRole.ADMIN,
        status="suspended",
    )

    sent: list[str] = []
    dispatcher = NotificationDispatcher(
        service=NotificationService(
            in_app_store=repository,
            email_sender=lambda *, to, subject, body: sent.append(to),
        ),
        recipient_resolver=repository,
    )

    created = dispatcher.dispatch(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.NEW_PROJECT,
        project_id="33333333-3333-3333-3333-333333333333",
        template_vars={"project_name": "โครงการใหม่", "organization": "กรมตัวอย่าง"},
    )

    assert sent == ["owner@example.com"]
    assert "email" in created.channel
    assert len(repository.list_for_tenant(TENANT_ID)) == 1


def test_dispatch_respects_preference_opt_out(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch-opt-out.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    user = repository.create_user(
        tenant_id=TENANT_ID,
        email="admin@example.com",
        role=UserRole.ADMIN,
    )
    repository.set_email_preference(
        tenant_id=TENANT_ID,
        user_id=user["id"],
        notification_type=NotificationType.RUN_FAILED,
        enabled=False,
    )

    sent: list[str] = []
    dispatcher = NotificationDispatcher(
        service=NotificationService(
            in_app_store=repository,
            email_sender=lambda *, to, subject, body: sent.append(to),
        ),
        recipient_resolver=repository,
    )

    created = dispatcher.dispatch(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.RUN_FAILED,
        template_vars={"run_id": "run-123", "error_count": "4"},
    )

    assert sent == []
    assert created.channel == "in_app"


def test_dispatch_defaults_to_operational_roles(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch-defaults.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_user(
        tenant_id=TENANT_ID, email="owner@example.com", role=UserRole.OWNER
    )
    repository.create_user(
        tenant_id=TENANT_ID, email="admin@example.com", role=UserRole.ADMIN
    )
    repository.create_user(
        tenant_id=TENANT_ID,
        email="analyst@example.com",
        role=UserRole.ANALYST,
    )
    repository.create_user(
        tenant_id=TENANT_ID,
        email="viewer@example.com",
        role=UserRole.VIEWER,
    )

    sent: list[str] = []
    dispatcher = NotificationDispatcher(
        service=NotificationService(
            in_app_store=repository,
            email_sender=lambda *, to, subject, body: sent.append(to),
        ),
        recipient_resolver=repository,
    )

    dispatcher.dispatch(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.EXPORT_READY,
    )

    assert sent == [
        "owner@example.com",
        "admin@example.com",
        "analyst@example.com",
    ]


def test_dispatch_delivers_webhook_for_matching_tenant_and_type(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch-webhook.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_webhook_subscription(
        tenant_id=TENANT_ID,
        name="Ops Receiver",
        url="https://hooks.example.com/egp",
        notification_types=[NotificationType.NEW_PROJECT],
        signing_secret="super-secret",
    )
    repository.create_webhook_subscription(
        tenant_id=OTHER_TENANT_ID,
        name="Other Receiver",
        url="https://hooks.example.com/other",
        notification_types=[NotificationType.NEW_PROJECT],
        signing_secret="other-secret",
    )
    transport = FakeWebhookTransport(
        [WebhookTransportResult(status_code=202, body="accepted")]
    )
    dispatcher = NotificationDispatcher(
        service=NotificationService(in_app_store=repository),
        recipient_resolver=repository,
        webhook_delivery_service=WebhookDeliveryService(
            repository=repository,
            transport=transport,
        ),
    )

    created = dispatcher.dispatch(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.NEW_PROJECT,
        project_id="33333333-3333-3333-3333-333333333333",
        template_vars={
            "project_name": "โครงการใหม่",
            "organization": "กรมตัวอย่าง",
        },
    )

    assert created.channel == "in_app,webhook"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    payload = json.loads(call["body"])
    assert call["url"] == "https://hooks.example.com/egp"
    assert call["headers"]["X-EGP-Event-Type"] == "new_project"
    assert call["headers"]["X-EGP-Event-ID"]
    assert call["headers"]["X-EGP-Signature-256"].startswith("sha256=")
    assert payload["event_type"] == "new_project"
    assert payload["tenant_id"] == TENANT_ID
    assert payload["project_id"] == "33333333-3333-3333-3333-333333333333"
    assert payload["template_vars"]["project_name"] == "โครงการใหม่"

    deliveries = repository.list_webhook_deliveries(tenant_id=TENANT_ID)
    assert len(deliveries) == 1
    assert deliveries[0].delivery_status == "delivered"
    assert deliveries[0].attempt_count == 1
    assert deliveries[0].last_response_status_code == 202


def test_dispatch_retries_retryable_webhook_failures_with_same_event_id(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch-webhook-retry.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_webhook_subscription(
        tenant_id=TENANT_ID,
        name="Ops Receiver",
        url="https://hooks.example.com/egp",
        notification_types=[NotificationType.RUN_FAILED],
        signing_secret="super-secret",
    )
    transport = FakeWebhookTransport(
        [
            WebhookTransportResult(status_code=503, body="try later"),
            WebhookTransportResult(status_code=200, body="ok"),
        ]
    )
    dispatcher = NotificationDispatcher(
        service=NotificationService(in_app_store=repository),
        recipient_resolver=repository,
        webhook_delivery_service=WebhookDeliveryService(
            repository=repository,
            transport=transport,
            max_attempts=2,
        ),
    )

    dispatcher.dispatch(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.RUN_FAILED,
        template_vars={"run_id": "run-123", "error_count": "2"},
    )

    assert len(transport.calls) == 2
    assert (
        transport.calls[0]["headers"]["X-EGP-Event-ID"]
        == transport.calls[1]["headers"]["X-EGP-Event-ID"]
    )
    deliveries = repository.list_webhook_deliveries(tenant_id=TENANT_ID)
    assert deliveries[0].delivery_status == "delivered"
    assert deliveries[0].attempt_count == 2
    assert deliveries[0].last_response_status_code == 200


def test_dispatch_does_not_retry_non_retryable_4xx_webhook_failure(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch-webhook-4xx.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_webhook_subscription(
        tenant_id=TENANT_ID,
        name="Ops Receiver",
        url="https://hooks.example.com/egp",
        notification_types=[NotificationType.EXPORT_READY],
        signing_secret="super-secret",
    )
    transport = FakeWebhookTransport(
        [WebhookTransportResult(status_code=410, body="gone")]
    )
    dispatcher = NotificationDispatcher(
        service=NotificationService(in_app_store=repository),
        recipient_resolver=repository,
        webhook_delivery_service=WebhookDeliveryService(
            repository=repository,
            transport=transport,
            max_attempts=3,
        ),
    )

    dispatcher.dispatch(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.EXPORT_READY,
    )

    assert len(transport.calls) == 1
    deliveries = repository.list_webhook_deliveries(tenant_id=TENANT_ID)
    assert deliveries[0].delivery_status == "failed"
    assert deliveries[0].attempt_count == 1
    assert deliveries[0].last_response_status_code == 410


def test_dispatch_webhook_failure_does_not_block_existing_notification_channels(
    tmp_path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch-webhook-fail-open.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_user(
        tenant_id=TENANT_ID,
        email="owner@example.com",
        role=UserRole.OWNER,
    )
    repository.create_webhook_subscription(
        tenant_id=TENANT_ID,
        name="Ops Receiver",
        url="https://hooks.example.com/egp",
        notification_types=[NotificationType.NEW_PROJECT],
        signing_secret="super-secret",
    )
    sent: list[str] = []
    transport = FakeWebhookTransport([TimeoutError("timed out")] * 3)
    dispatcher = NotificationDispatcher(
        service=NotificationService(
            in_app_store=repository,
            email_sender=lambda *, to, subject, body: sent.append(to),
        ),
        recipient_resolver=repository,
        webhook_delivery_service=WebhookDeliveryService(
            repository=repository,
            transport=transport,
            max_attempts=3,
        ),
    )

    created = dispatcher.dispatch(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.NEW_PROJECT,
        template_vars={
            "project_name": "โครงการใหม่",
            "organization": "กรมตัวอย่าง",
        },
    )

    assert sent == ["owner@example.com"]
    assert created.channel == "in_app,email"
    assert repository.list_for_tenant(TENANT_ID)[0].notification_type is NotificationType.NEW_PROJECT
    deliveries = repository.list_webhook_deliveries(tenant_id=TENANT_ID)
    assert deliveries[0].delivery_status == "failed"
    assert deliveries[0].attempt_count == 3


def test_webhook_delivery_skips_already_delivered_event_id(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dispatch-webhook-idempotent.sqlite3'}"
    repository = SqlNotificationRepository(
        database_url=database_url, bootstrap_schema=True
    )
    repository.create_webhook_subscription(
        tenant_id=TENANT_ID,
        name="Ops Receiver",
        url="https://hooks.example.com/egp",
        notification_types=[NotificationType.NEW_PROJECT],
        signing_secret="super-secret",
    )
    transport = FakeWebhookTransport(
        [WebhookTransportResult(status_code=200, body="ok")]
    )
    delivery_service = WebhookDeliveryService(
        repository=repository,
        transport=transport,
    )
    notification = Notification(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_id=TENANT_ID,
        project_id="33333333-3333-3333-3333-333333333333",
        notification_type=NotificationType.NEW_PROJECT,
        channel="in_app",
        subject="โครงการใหม่: ทดสอบ",
        body="body",
        status="sent",
        created_at="2026-04-05T00:00:00+00:00",
        sent_at="2026-04-05T00:00:00+00:00",
    )

    assert delivery_service.deliver(
        notification=notification,
        template_vars={"project_name": "ทดสอบ"},
    ) is True
    assert delivery_service.deliver(
        notification=notification,
        template_vars={"project_name": "ทดสอบ"},
    ) is True

    assert len(transport.calls) == 1
    deliveries = repository.list_webhook_deliveries(tenant_id=TENANT_ID)
    assert deliveries[0].delivery_status == "delivered"
    assert deliveries[0].attempt_count == 1
