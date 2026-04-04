from __future__ import annotations

from egp_db.repositories.notification_repo import SqlNotificationRepository
from egp_notifications.dispatcher import NotificationDispatcher
from egp_notifications.service import NotificationService
from egp_shared_types.enums import NotificationType, UserRole

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"


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
