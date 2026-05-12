"""AWS Lambda entrypoint for OPN webhook ingestion.

This handler is intended for an API Gateway -> Lambda deployment where OPN can
reach a stable public HTTPS endpoint without exposing the full FastAPI app.
It reuses the existing billing repository and payment-provider parsing logic so
idempotency and settlement behavior stay aligned with the API service.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from egp_api.lambda_handlers.runtime_config import (
    LambdaConfigurationError,
    load_runtime_config,
)
from egp_api.services.billing_service import BillingService
from egp_api.services.payment_provider import build_payment_provider
from egp_db.repositories.billing_repo import create_billing_repository
from egp_shared_types.enums import BillingPaymentProvider

_JSON_HEADERS = {"content-type": "application/json"}
_CACHED_BILLING_SERVICE: BillingService | None = None


def _response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "isBase64Encoded": False,
    }


def _normalize_headers(event: dict[str, Any]) -> dict[str, str]:
    raw_headers = event.get("headers")
    if not isinstance(raw_headers, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in raw_headers.items():
        if value is None:
            continue
        normalized[str(key).lower()] = str(value)
    return normalized


def _read_raw_body(event: dict[str, Any]) -> str:
    body = event.get("body")
    if body is None:
        return ""
    if isinstance(body, bytes):
        raw_bytes = body
    else:
        raw_text = str(body)
        if event.get("isBase64Encoded"):
            raw_bytes = base64.b64decode(raw_text)
        else:
            raw_bytes = raw_text.encode("utf-8")
    return raw_bytes.decode("utf-8")


def _parse_payload(raw_body: str) -> dict[str, Any]:
    if not raw_body:
        raise ValueError("invalid json payload")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid json payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid json payload")
    return payload


def build_billing_service_from_env() -> BillingService:
    runtime_config = load_runtime_config()
    repository = create_billing_repository(
        database_url=runtime_config.database_url,
        bootstrap_schema=False,
    )
    provider = build_payment_provider(
        provider_name=runtime_config.payment_provider,
        base_url="https://api.omise.co",
        promptpay_proxy_id=None,
        opn_public_key=runtime_config.opn_public_key,
        opn_secret_key=runtime_config.opn_secret_key,
    )
    if provider is None:
        raise LambdaConfigurationError("payment provider is not configured")
    return BillingService(
        repository,
        payment_provider=provider,
    )


def get_billing_service() -> BillingService:
    global _CACHED_BILLING_SERVICE
    if _CACHED_BILLING_SERVICE is None:
        _CACHED_BILLING_SERVICE = build_billing_service_from_env()
    return _CACHED_BILLING_SERVICE


def handle_opn_webhook_event(
    event: dict[str, Any],
    *,
    billing_service: BillingService | None = None,
) -> dict[str, Any]:
    service = billing_service or get_billing_service()
    headers = _normalize_headers(event)
    raw_body = _read_raw_body(event)
    payload = _parse_payload(raw_body)
    detail = service.handle_provider_webhook(
        provider=BillingPaymentProvider.OPN,
        payload=payload,
        headers=headers,
        raw_body=raw_body,
        actor_subject="opn-lambda-webhook",
    )
    return _response(
        200,
        {
            "status": "processed",
            "billing_record_id": detail.record.id,
            "tenant_id": detail.record.tenant_id,
            "record_status": detail.record.status.value,
            "payment_request_count": len(detail.payment_requests),
            "payment_count": len(detail.payments),
        },
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    try:
        return handle_opn_webhook_event(event)
    except LambdaConfigurationError as exc:
        return _response(503, {"detail": str(exc)})
    except KeyError:
        return _response(404, {"detail": "payment request not found"})
    except ValueError as exc:
        return _response(400, {"detail": str(exc)})
    except RuntimeError as exc:
        return _response(502, {"detail": str(exc)})
    except Exception:
        return _response(500, {"detail": "internal server error"})
