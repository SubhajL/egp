"""Tests for notification service."""

from egp_db.repositories.notification_repo import SqlNotificationRepository
from egp_notifications.service import InAppNotificationStore, NotificationService
from egp_shared_types.enums import NotificationType

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def test_send_creates_in_app_notification() -> None:
    service = NotificationService()
    result = service.send(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.NEW_PROJECT,
        project_id="project-123",
        template_vars={
            "project_name": "จัดซื้อระบบสารสนเทศ",
            "organization": "กรมสรรพากร",
            "budget": "฿12,500,000",
        },
    )
    assert result.status == "sent"
    assert "in_app" in result.channel
    assert "โครงการใหม่" in result.subject
    assert "จัดซื้อระบบสารสนเทศ" in result.body


def test_list_notifications_returns_tenant_scoped() -> None:
    store = InAppNotificationStore()
    service = NotificationService(in_app_store=store)

    service.send(tenant_id=TENANT_ID, notification_type=NotificationType.NEW_PROJECT)
    service.send(
        tenant_id="other-tenant", notification_type=NotificationType.NEW_PROJECT
    )
    service.send(
        tenant_id=TENANT_ID, notification_type=NotificationType.WINNER_ANNOUNCED
    )

    results = service.list_notifications(TENANT_ID)
    assert len(results) == 2
    assert all(n.tenant_id == TENANT_ID for n in results)


def test_winner_announced_notification_template() -> None:
    service = NotificationService()
    result = service.send(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.WINNER_ANNOUNCED,
        template_vars={"project_name": "โครงการทดสอบ", "organization": "กรมทดสอบ"},
    )
    assert "ประกาศผู้ชนะ" in result.subject
    assert "ปิดอัตโนมัติ" in result.body


def test_tor_changed_notification_template() -> None:
    service = NotificationService()
    result = service.send(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.TOR_CHANGED,
        template_vars={"project_name": "โครงการ TOR", "organization": "กรม"},
    )
    assert "TOR เปลี่ยนแปลง" in result.subject


def test_mark_read() -> None:
    store = InAppNotificationStore()
    service = NotificationService(in_app_store=store)
    result = service.send(
        tenant_id=TENANT_ID, notification_type=NotificationType.NEW_PROJECT
    )
    assert store.mark_read(result.id) is True
    notifications = store.list_for_tenant(TENANT_ID)
    assert notifications[0].status == "read"


def test_send_uses_injected_email_sender_for_all_recipients() -> None:
    sent: list[tuple[str, str, str]] = []

    def fake_sender(*, to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    service = NotificationService(email_sender=fake_sender)
    result = service.send(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.RUN_FAILED,
        recipient_emails=["ops-a@example.com", "ops-b@example.com"],
        template_vars={"run_id": "run-123", "error_count": "2"},
    )

    assert result.channel == "in_app,email"
    assert sent == [
        ("ops-a@example.com", "Crawl ล้มเหลว: Run run-123", result.body),
        ("ops-b@example.com", "Crawl ล้มเหลว: Run run-123", result.body),
    ]


def test_sql_notification_store_lists_and_marks_notifications(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'notifications.sqlite3'}"
    store = SqlNotificationRepository(database_url=database_url, bootstrap_schema=True)
    service = NotificationService(in_app_store=store)

    created = service.send(
        tenant_id=TENANT_ID,
        notification_type=NotificationType.NEW_PROJECT,
        project_id="33333333-3333-3333-3333-333333333333",
        template_vars={"project_name": "โครงการใหม่", "organization": "กรมตัวอย่าง"},
    )

    listed = service.list_notifications(TENANT_ID)

    assert len(listed) == 1
    assert listed[0].id == created.id
    assert listed[0].notification_type is NotificationType.NEW_PROJECT
    assert store.mark_read(created.id) is True
    assert store.list_for_tenant(TENANT_ID)[0].status == "read"
