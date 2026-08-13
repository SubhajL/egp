"""Sanitized tenant audit events for outbound webhook policy blocks."""

from __future__ import annotations

import logging
from uuid import uuid4

from egp_db.repositories.audit_repo import SqlAuditRepository


logger = logging.getLogger(__name__)


class WebhookSecurityAuditRecorder:
    def __init__(self, repository: SqlAuditRepository) -> None:
        self._repository = repository

    def record_creation_rejected(
        self, *, tenant_id: str, actor_subject: str, reason_code: str
    ) -> None:
        self._record(
            tenant_id=tenant_id,
            entity_id=str(uuid4()),
            actor_subject=actor_subject,
            event_type="webhook.security_configuration_rejected",
            summary="Rejected webhook endpoint configuration",
            metadata={"reason_code": reason_code, "stage": "creation"},
        )

    def record_delivery_blocked(
        self,
        *,
        tenant_id: str,
        webhook_subscription_id: str,
        reason_code: str,
        stage: str,
        attempt_count: int,
    ) -> None:
        self._record(
            tenant_id=tenant_id,
            entity_id=webhook_subscription_id,
            actor_subject="system:webhook-delivery",
            event_type="webhook.security_delivery_blocked",
            summary="Blocked unsafe webhook delivery",
            metadata={
                "reason_code": reason_code,
                "stage": stage,
                "attempt_count": int(attempt_count),
            },
        )

    def _record(
        self,
        *,
        tenant_id: str,
        entity_id: str,
        actor_subject: str,
        event_type: str,
        summary: str,
        metadata: dict[str, object],
    ) -> None:
        try:
            self._repository.record_event(
                tenant_id=tenant_id,
                source="admin",
                entity_type="webhook",
                entity_id=entity_id,
                actor_subject=actor_subject,
                event_type=event_type,
                summary=summary,
                metadata_json=metadata,
            )
        except Exception:
            logger.warning("Failed to record webhook security audit event", exc_info=True)
