"""Orchestration for LINE-mediated manual PromptPay slip verification.

Receives LINE webhook events (text + image), stores slip images, matches them
to billing records via the reference code, notifies the operator, and exposes
admin verify/reject actions that activate the subscription.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from egp_db.repositories.billing_repo import SqlBillingRepository
from egp_db.repositories.line_payment_models import PaymentSlipRecord
from egp_db.repositories.line_payment_repo import LinePaymentRepository

from egp_api.services.billing_service import BillingService
from egp_api.services.line_integration import (
    LineMessageEvent,
    LineMessagingClient,
    extract_reference_code,
)

logger = logging.getLogger(__name__)

_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}


@dataclass(frozen=True, slots=True)
class LineWebhookSummary:
    text_events: int
    image_events: int
    slips_created: int
    slips_matched: int


def _ts_to_iso(timestamp_ms: int | None, *, fallback: datetime) -> str:
    if timestamp_ms is None:
        return fallback.isoformat()
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()


class LineSlipService:
    def __init__(
        self,
        *,
        line_repository: LinePaymentRepository,
        billing_repository: SqlBillingRepository,
        billing_service: BillingService,
        artifact_store: object,
        messaging_client: LineMessagingClient | None = None,
        admin_user_ids: Sequence[str] = (),
        admin_console_base_url: str = "",
        context_ttl_minutes: int = 720,
        slip_key_prefix: str = "line-slips",
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._line_repo = line_repository
        self._billing_repo = billing_repository
        self._billing_service = billing_service
        self._artifact_store = artifact_store
        self._messaging = messaging_client
        self._admin_user_ids = tuple(uid.strip() for uid in admin_user_ids if uid and uid.strip())
        self._admin_console_base_url = admin_console_base_url.rstrip("/")
        self._context_ttl_minutes = max(1, int(context_ttl_minutes))
        self._slip_key_prefix = slip_key_prefix.strip("/") or "line-slips"
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    # ----------------------------------------------------------- webhook flow
    def handle_webhook_events(self, events: list[LineMessageEvent]) -> LineWebhookSummary:
        text_events = image_events = slips_created = slips_matched = 0
        for event in events:
            if not event.line_user_id:
                continue
            if event.message_type == "text":
                text_events += 1
                self._handle_text(event)
            elif event.message_type == "image":
                image_events += 1
                created, matched = self._handle_image(event)
                slips_created += int(created)
                slips_matched += int(matched)
        return LineWebhookSummary(
            text_events=text_events,
            image_events=image_events,
            slips_created=slips_created,
            slips_matched=slips_matched,
        )

    def _resolve_reference(self, reference_code: str) -> tuple[str | None, str | None]:
        """Return ``(tenant_id, billing_record_id)`` only when exactly one match."""
        matches = self._billing_repo.find_billing_records_by_number(record_number=reference_code)
        if len(matches) == 1:
            return matches[0]
        return None, None

    def _handle_text(self, event: LineMessageEvent) -> None:
        reference = extract_reference_code(event.text)
        if not reference or not event.message_id:
            return
        tenant_id, record_id = self._resolve_reference(reference)
        expires_at = (self._now_fn() + timedelta(minutes=self._context_ttl_minutes)).isoformat()
        self._line_repo.record_context(
            line_user_id=event.line_user_id,
            reference_code=reference,
            source_message_id=event.message_id,
            tenant_id=tenant_id,
            billing_record_id=record_id,
            expires_at=expires_at,
        )

    def _handle_image(self, event: LineMessageEvent) -> tuple[bool, bool]:
        if not event.message_id:
            return False, False
        received_at = _ts_to_iso(event.timestamp, fallback=self._now_fn())
        slip, created = self._line_repo.create_slip(
            line_user_id=event.line_user_id,
            line_message_id=event.message_id,
            received_at=received_at,
        )
        if not created:
            return False, slip.verification_status == "matched"

        self._store_slip_image(slip, event.message_id)
        matched = self._match_slip(slip, event.line_user_id)
        self._notify_admins(slip, event.line_user_id, matched)
        return True, matched

    def _store_slip_image(self, slip: PaymentSlipRecord, message_id: str) -> None:
        if self._messaging is None:
            return
        try:
            data, content_type = self._messaging.get_message_content(message_id)
        except Exception:  # pragma: no cover - network failure path
            logger.exception("failed to download LINE slip image for message %s", message_id)
            return
        extension = _CONTENT_TYPE_EXTENSIONS.get((content_type or "").lower(), "bin")
        key = f"{self._slip_key_prefix}/{slip.id}.{extension}"
        digest = hashlib.sha256(data).hexdigest()
        self._artifact_store.put_bytes(key=key, data=data, content_type=content_type)
        self._line_repo.attach_image(
            slip_id=slip.id,
            image_object_key=key,
            image_content_type=content_type,
            image_sha256=digest,
        )

    def _match_slip(self, slip: PaymentSlipRecord, line_user_id: str) -> bool:
        context = self._line_repo.latest_context_for_user(line_user_id)
        if context is None:
            return False
        tenant_id = context.tenant_id
        record_id = context.billing_record_id
        if tenant_id is None or record_id is None:
            tenant_id, record_id = self._resolve_reference(context.reference_code)
        if tenant_id is None or record_id is None:
            return False
        self._line_repo.match_slip(
            slip_id=slip.id,
            tenant_id=tenant_id,
            billing_record_id=record_id,
            reference_code_match=context.reference_code,
        )
        return True

    def _notify_admins(self, slip: PaymentSlipRecord, line_user_id: str, matched: bool) -> None:
        if self._messaging is None:
            return
        recipients = self._admin_recipients()
        if not recipients:
            return
        reference = "(unmatched — ask customer for reference)"
        refreshed = self._line_repo.get_slip(slip.id) or slip
        if matched and refreshed.reference_code_match:
            reference = refreshed.reference_code_match
        link = (
            f"{self._admin_console_base_url}/admin?tab=slips"
            if self._admin_console_base_url
            else "(open admin console → สลิปการชำระเงิน)"
        )
        message = (
            "💰 สลิปการชำระเงินใหม่ผ่าน LINE\n"
            f"Reference: {reference}\n"
            f"จาก LINE user: {line_user_id}\n"
            f"ตรวจสอบ: {link}"
        )
        for recipient in recipients:
            try:
                self._messaging.push_message(to=recipient, text=message)
            except Exception:  # pragma: no cover - network failure path
                logger.exception("failed to push LINE admin notification to %s", recipient)

    def _admin_recipients(self) -> list[str]:
        recipients = list(self._admin_user_ids)
        try:
            for subscriber in self._line_repo.list_admin_subscribers():
                if subscriber.line_user_id not in recipients:
                    recipients.append(subscriber.line_user_id)
        except Exception:  # pragma: no cover - defensive
            logger.exception("failed to list LINE admin subscribers")
        return recipients

    # ------------------------------------------------------------- admin ops
    def list_slips(
        self, *, status: str | None = None, tenant_id: str | None = None, limit: int = 100
    ) -> list[PaymentSlipRecord]:
        return self._line_repo.list_slips(status=status, tenant_id=tenant_id, limit=limit)

    def get_slip(self, slip_id: str) -> PaymentSlipRecord | None:
        return self._line_repo.get_slip(slip_id)

    def get_slip_image(self, slip_id: str) -> tuple[bytes, str | None]:
        slip = self._line_repo.get_slip(slip_id)
        if slip is None:
            raise KeyError(slip_id)
        if not slip.image_object_key:
            raise FileNotFoundError(slip_id)
        data = self._artifact_store.get_bytes(slip.image_object_key)
        return data, slip.image_content_type

    def verify_slip(
        self, *, slip_id: str, admin_user_id: str | None, note: str | None = None
    ) -> PaymentSlipRecord:
        slip = self._line_repo.get_slip(slip_id)
        if slip is None:
            raise KeyError(slip_id)
        if slip.verification_status == "verified":
            # Idempotent: a re-click never settles a second payment. A truly
            # concurrent double-verify is additionally guarded by
            # verify_manual_payment raising once the record is PAID.
            return slip
        if slip.verification_status == "rejected":
            raise ValueError("slip was already rejected")
        if not slip.tenant_id or not slip.billing_record_id:
            raise ValueError("slip is not matched to a billing record")
        if not slip.image_object_key:
            # Never activate a subscription without the actual slip evidence
            # stored (e.g. the LINE image download failed).
            raise ValueError("slip has no stored image evidence")
        received_at = self._now_fn().isoformat()
        self._billing_service.verify_manual_payment(
            tenant_id=slip.tenant_id,
            billing_record_id=slip.billing_record_id,
            received_at=received_at,
            payment_request_id=slip.payment_request_id,
            note=note,
            actor_subject=admin_user_id,
        )
        verified = self._line_repo.mark_verified(
            slip_id=slip.id, verified_by_user_id=admin_user_id, notes=note
        )
        self._push_customer(slip.line_user_id, "✅ ยืนยันการชำระเงินเรียบร้อยแล้ว ขอบคุณครับ")
        return verified

    def reject_slip(
        self, *, slip_id: str, admin_user_id: str | None, note: str | None = None
    ) -> PaymentSlipRecord:
        slip = self._line_repo.get_slip(slip_id)
        if slip is None:
            raise KeyError(slip_id)
        rejected = self._line_repo.mark_rejected(
            slip_id=slip.id, verified_by_user_id=admin_user_id, notes=note
        )
        reason = f"\nเหตุผล: {note}" if note else ""
        self._push_customer(
            slip.line_user_id,
            "⚠️ ไม่สามารถยืนยันสลิปได้ กรุณาติดต่อแอดมินหรือส่งสลิปใหม่อีกครั้ง" + reason,
        )
        return rejected

    def _push_customer(self, line_user_id: str, text: str) -> None:
        if self._messaging is None:
            return
        try:
            self._messaging.push_message(to=line_user_id, text=text)
        except Exception:  # pragma: no cover - network failure path
            logger.exception("failed to push LINE confirmation to %s", line_user_id)
