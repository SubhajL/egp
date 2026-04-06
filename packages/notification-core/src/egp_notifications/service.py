"""Notification service for e-GP alerts (email + in-app)."""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol
from uuid import uuid4

from egp_shared_types.enums import NotificationType

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    def __call__(self, *, to: str, subject: str, body: str) -> None: ...


class NotificationStore(Protocol):
    def add(self, notification: Notification) -> None: ...

    def list_for_tenant(
        self, tenant_id: str, *, limit: int = 50
    ) -> list[Notification]: ...

    def mark_read(self, notification_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    tenant_id: str
    project_id: str | None
    notification_type: NotificationType
    channel: str
    subject: str
    body: str
    status: str
    created_at: str
    sent_at: str | None = None


@dataclass
class SmtpConfig:
    host: str = "localhost"
    port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = "noreply@egp-intelligence.th"
    use_tls: bool = True


class InAppNotificationStore:
    """Simple in-memory store for in-app notifications."""

    def __init__(self) -> None:
        self._notifications: list[Notification] = []

    def add(self, notification: Notification) -> None:
        self._notifications.append(notification)

    def list_for_tenant(self, tenant_id: str, *, limit: int = 50) -> list[Notification]:
        return [n for n in reversed(self._notifications) if n.tenant_id == tenant_id][
            :limit
        ]

    def mark_read(self, notification_id: str) -> bool:
        for i, n in enumerate(self._notifications):
            if n.id == notification_id:
                self._notifications[i] = Notification(
                    id=n.id,
                    tenant_id=n.tenant_id,
                    project_id=n.project_id,
                    notification_type=n.notification_type,
                    channel=n.channel,
                    subject=n.subject,
                    body=n.body,
                    status="read",
                    created_at=n.created_at,
                    sent_at=n.sent_at,
                )
                return True
        return False

    @property
    def count(self) -> int:
        return len(self._notifications)


NOTIFICATION_TEMPLATES: dict[NotificationType, tuple[str, str]] = {
    NotificationType.NEW_PROJECT: (
        "โครงการใหม่: {project_name}",
        "ระบบค้นพบโครงการใหม่\n\nชื่อโครงการ: {project_name}\nหน่วยงาน: {organization}\nงบประมาณ: {budget}\n\nเข้าสู่ระบบเพื่อดูรายละเอียด",
    ),
    NotificationType.WINNER_ANNOUNCED: (
        "ประกาศผู้ชนะ: {project_name}",
        "โครงการประกาศผู้ชนะแล้ว\n\nชื่อโครงการ: {project_name}\nหน่วยงาน: {organization}\n\nโครงการถูกปิดอัตโนมัติ",
    ),
    NotificationType.TOR_CHANGED: (
        "TOR เปลี่ยนแปลง: {project_name}",
        "พบการเปลี่ยนแปลงเอกสาร TOR\n\nชื่อโครงการ: {project_name}\nหน่วยงาน: {organization}\n\nกรุณาตรวจสอบเอกสารฉบับใหม่",
    ),
    NotificationType.RUN_FAILED: (
        "Crawl ล้มเหลว: Run {run_id}",
        "การทำงาน Crawl ล้มเหลว\n\nRun ID: {run_id}\nข้อผิดพลาด: {error_count} รายการ\n\nกรุณาตรวจสอบและลองใหม่",
    ),
    NotificationType.CONTRACT_SIGNED: (
        "ลงนามสัญญา: {project_name}",
        "โครงการลงนามสัญญาแล้ว\n\nชื่อโครงการ: {project_name}\nหน่วยงาน: {organization}",
    ),
    NotificationType.EXPORT_READY: (
        "ไฟล์ส่งออกพร้อมแล้ว",
        "ไฟล์ส่งออก Excel ของคุณพร้อมดาวน์โหลดแล้ว\n\nกรุณาเข้าสู่ระบบเพื่อดาวน์โหลด",
    ),
}


class NotificationService:
    """Delivers notifications via email and in-app store."""

    def __init__(
        self,
        *,
        smtp_config: SmtpConfig | None = None,
        in_app_store: NotificationStore | None = None,
        email_sender: EmailSender | None = None,
    ) -> None:
        self._smtp_config = smtp_config
        self._in_app_store = in_app_store or InAppNotificationStore()
        self._email_sender = email_sender

    def send(
        self,
        *,
        tenant_id: str,
        notification_type: NotificationType,
        project_id: str | None = None,
        recipient_email: str | None = None,
        recipient_emails: Sequence[str] | None = None,
        template_vars: dict[str, str] | None = None,
    ) -> Notification:
        template = NOTIFICATION_TEMPLATES.get(notification_type)
        variables = template_vars or {}
        recipients = _normalize_recipient_emails(recipient_email, recipient_emails)

        if template:
            subject = template[0].format_map(
                {
                    **variables,
                    **{
                        k: ""
                        for k in [
                            "project_name",
                            "organization",
                            "budget",
                            "run_id",
                            "error_count",
                        ]
                        if k not in variables
                    },
                }
            )
            body = template[1].format_map(
                {
                    **variables,
                    **{
                        k: ""
                        for k in [
                            "project_name",
                            "organization",
                            "budget",
                            "run_id",
                            "error_count",
                        ]
                        if k not in variables
                    },
                }
            )
        else:
            subject = f"แจ้งเตือน: {notification_type.value}"
            body = f"การแจ้งเตือนประเภท {notification_type.value}"

        now = datetime.now(UTC).isoformat()
        channels_used: list[str] = []

        # In-app notification (always)
        in_app = Notification(
            id=str(uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            notification_type=notification_type,
            channel="in_app",
            subject=subject,
            body=body,
            status="pending",
            created_at=now,
        )
        self._in_app_store.add(in_app)
        channels_used.append("in_app")

        # Email notification (if configured or a test sender is provided)
        email_sent = False
        if recipients and (
            self._smtp_config is not None or self._email_sender is not None
        ):
            for recipient in recipients:
                try:
                    self._send_email(
                        to=recipient,
                        subject=subject,
                        body=body,
                    )
                    email_sent = True
                except Exception:
                    logger.exception(
                        "Failed to send email notification to %s", recipient
                    )
            if email_sent:
                channels_used.append("email")

        return Notification(
            id=in_app.id,
            tenant_id=tenant_id,
            project_id=project_id,
            notification_type=notification_type,
            channel=",".join(channels_used),
            subject=subject,
            body=body,
            status="sent",
            created_at=now,
            sent_at=now,
        )

    def list_notifications(
        self, tenant_id: str, *, limit: int = 50
    ) -> list[Notification]:
        return self._in_app_store.list_for_tenant(tenant_id, limit=limit)

    def send_email_message(self, *, to: str, subject: str, body: str) -> bool:
        if self._smtp_config is None and self._email_sender is None:
            return False
        self._send_email(to=to, subject=subject, body=body)
        return True

    def _send_email(self, *, to: str, subject: str, body: str) -> None:
        if self._email_sender is not None:
            self._email_sender(to=to, subject=subject, body=body)
            return
        if not self._smtp_config:
            return
        cfg = self._smtp_config
        msg = MIMEMultipart()
        msg["From"] = cfg.from_address
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(cfg.host, cfg.port) as server:
            if cfg.use_tls:
                server.starttls()
            if cfg.username:
                server.login(cfg.username, cfg.password)
            server.sendmail(cfg.from_address, to, msg.as_string())


def _normalize_recipient_emails(
    recipient_email: str | None,
    recipient_emails: Sequence[str] | None,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    values = ([] if recipient_email is None else [recipient_email]) + list(
        recipient_emails or []
    )
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        ordered.append(normalized)
        seen.add(normalized)
    return ordered
