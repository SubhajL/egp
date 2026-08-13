"""The single construction path for the notification stack.

Two processes send notifications: the API (`bootstrap/services.py`) and the
standalone crawler-agent inbox processor
(`executors/crawler_agent_results.py`). Before U8a they assembled that stack
independently, and the executor's version was assembled *incorrectly* — it had no
dispatcher at all, so a project first seen through an agent result envelope was
persisted without the ``NEW_PROJECT`` notification the API path sends. U7c
recorded that as a deliberate, logged gap.

The fix is not "wire a dispatcher into the executor too" — that just recreates the
same drift one layer down. The stack has five collaborators and two of them are
easy to omit silently:

* ``NotificationDispatcher.webhook_delivery_service`` is **optional and defaults to
  ``None``**, so a stack built without it still writes in-app rows and still sends
  email. Configured webhook subscriptions are simply never delivered, and nothing
  anywhere raises.
* ``EntitlementAwareNotificationDispatcher`` is what applies the ``notifications``
  capability check. A stack that returns the raw dispatcher notifies tenants whose
  plan does not include notifications.

So both processes now call this builder and neither one names the parts.

**Repositories, not environment.** Entitlement and recipient resolution are
repository-driven: the entitlement gate reads billing subscriptions and profiles,
and the recipient resolver reads users. The caller therefore supplies repositories
bound to *its own* engine — a builder that constructed them from ``DATABASE_URL``
would open a second engine in the executor and quietly diverge from the connection
its own transactions use.
"""

from __future__ import annotations

from dataclasses import dataclass

from egp_api.services.entitlement_service import (
    EntitlementAwareNotificationDispatcher,
    TenantEntitlementService,
)
from egp_notifications.dispatcher import NotificationDispatcher
from egp_notifications.service import EmailSender, NotificationService, SmtpConfig
from egp_notifications.webhook_delivery import (
    WebhookDeliveryProcessor,
    WebhookDeliveryService,
)
from egp_notifications.webhook_security import WebhookEndpointPolicy


@dataclass(frozen=True, slots=True)
class NotificationStack:
    """Every notification collaborator, assembled consistently.

    ``gated_dispatcher`` is what callers should hand to ingest services; the
    ungated ``notification_dispatcher`` is exposed only because the API binds the
    individual services to ``app.state`` for routes that legitimately need them.
    """

    notification_service: NotificationService
    webhook_delivery_service: WebhookDeliveryService
    webhook_delivery_processor: WebhookDeliveryProcessor
    notification_dispatcher: NotificationDispatcher
    entitlement_service: TenantEntitlementService
    gated_dispatcher: EntitlementAwareNotificationDispatcher
    endpoint_policy: WebhookEndpointPolicy


def build_notification_stack(
    *,
    notification_repository: object,
    billing_repository: object,
    profile_repository: object,
    run_repository: object | None = None,
    discovery_job_repository: object | None = None,
    tenant_entitlement_repository: object | None = None,
    smtp_config: SmtpConfig | None = None,
    email_sender: EmailSender | None = None,
    endpoint_policy: WebhookEndpointPolicy | None = None,
    security_audit_recorder: object | None = None,
) -> NotificationStack:
    """Assemble the notification stack. Pure construction; performs no I/O.

    ``smtp_config=None`` is a supported production configuration, not a
    degradation: ``NotificationService`` still stores the in-app row and webhook
    delivery is unaffected — only email is skipped.
    """

    if notification_repository is None:
        raise ValueError("notification_repository is required")
    if billing_repository is None:
        raise ValueError("billing_repository is required")
    if profile_repository is None:
        raise ValueError("profile_repository is required")

    resolved_endpoint_policy = endpoint_policy or WebhookEndpointPolicy()
    notification_service = NotificationService(
        smtp_config=smtp_config,
        in_app_store=notification_repository,
        email_sender=email_sender,
    )
    webhook_delivery_service = WebhookDeliveryService(repository=notification_repository)
    webhook_delivery_processor = WebhookDeliveryProcessor(
        repository=notification_repository,
        endpoint_policy=resolved_endpoint_policy,
        security_audit_recorder=security_audit_recorder,
    )
    notification_dispatcher = NotificationDispatcher(
        service=notification_service,
        recipient_resolver=notification_repository,
        # Not optional in practice. Omitting it is silent at every other layer:
        # in-app rows and email still work, and only webhook delivery disappears.
        webhook_delivery_service=webhook_delivery_service,
    )
    entitlement_service = TenantEntitlementService(
        billing_repository,
        profile_repository,
        run_repository=run_repository,
        discovery_job_repository=discovery_job_repository,
        tenant_entitlement_repository=tenant_entitlement_repository,
    )
    return NotificationStack(
        notification_service=notification_service,
        webhook_delivery_service=webhook_delivery_service,
        webhook_delivery_processor=webhook_delivery_processor,
        notification_dispatcher=notification_dispatcher,
        entitlement_service=entitlement_service,
        gated_dispatcher=EntitlementAwareNotificationDispatcher(
            notification_dispatcher,
            entitlement_service,
        ),
        endpoint_policy=resolved_endpoint_policy,
    )
