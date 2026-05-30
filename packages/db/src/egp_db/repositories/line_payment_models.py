"""Record types for LINE-mediated manual PromptPay slip verification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PaymentSlipRecord:
    id: str
    tenant_id: str | None
    billing_record_id: str | None
    payment_request_id: str | None
    line_user_id: str
    line_message_id: str
    reference_code_match: str | None
    image_object_key: str | None
    image_content_type: str | None
    image_sha256: str | None
    verification_status: str
    verified_by_user_id: str | None
    verified_at: str | None
    verification_notes: str | None
    received_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class LinePaymentContextRecord:
    id: str
    line_user_id: str
    reference_code: str
    tenant_id: str | None
    billing_record_id: str | None
    plan_code: str | None
    source_message_id: str
    expires_at: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class LineAdminSubscriberRecord:
    id: str
    line_user_id: str
    tenant_id: str | None
    display_name: str | None
    created_at: str
