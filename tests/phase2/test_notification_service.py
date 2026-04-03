"""Tests for notification service."""

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
    service.send(tenant_id="other-tenant", notification_type=NotificationType.NEW_PROJECT)
    service.send(tenant_id=TENANT_ID, notification_type=NotificationType.WINNER_ANNOUNCED)

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
    result = service.send(tenant_id=TENANT_ID, notification_type=NotificationType.NEW_PROJECT)
    assert store.mark_read(result.id) is True
    notifications = store.list_for_tenant(TENANT_ID)
    assert notifications[0].status == "read"
