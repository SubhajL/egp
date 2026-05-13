"""Provider-agnostic payment initiation helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from urllib import error, parse, request as urllib_request
from uuid import uuid4

from egp_api.services.promptpay import build_promptpay_payload, render_promptpay_qr_svg
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
)


@dataclass(frozen=True, slots=True)
class ProviderPaymentRequest:
    provider: BillingPaymentProvider
    payment_method: BillingPaymentMethod
    tenant_id: str
    billing_record_id: str
    record_number: str
    amount: str
    currency: str
    expires_in_minutes: int


@dataclass(frozen=True, slots=True)
class CreatedPaymentRequest:
    provider: BillingPaymentProvider
    payment_method: BillingPaymentMethod
    status: BillingPaymentRequestStatus
    provider_reference: str
    payment_url: str
    qr_payload: str
    qr_svg: str
    amount: str
    currency: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class ParsedPaymentCallback:
    provider_event_id: str
    provider_reference: str
    status: BillingPaymentRequestStatus
    amount: str
    currency: str
    occurred_at: str
    reference_code: str | None
    payload_json: str


class PaymentProvider(Protocol):
    def create_payment_request(
        self, *, request: ProviderPaymentRequest
    ) -> CreatedPaymentRequest: ...

    def parse_callback(
        self,
        *,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
        raw_body: str | None = None,
    ) -> ParsedPaymentCallback: ...


class MockPromptPayProvider:
    def __init__(self, *, base_url: str, promptpay_proxy_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._promptpay_proxy_id = promptpay_proxy_id

    def create_payment_request(self, *, request: ProviderPaymentRequest) -> CreatedPaymentRequest:
        if request.provider is not BillingPaymentProvider.MOCK_PROMPTPAY:
            raise ValueError("requested payment provider is not configured")
        if request.payment_method is not BillingPaymentMethod.PROMPTPAY_QR:
            raise ValueError("mock PromptPay only supports promptpay_qr")
        if request.currency != "THB":
            raise ValueError("PromptPay only supports THB")
        provider_reference = f"mockpp_{uuid4().hex[:20]}"
        qr_payload = build_promptpay_payload(
            self._promptpay_proxy_id,
            amount=request.amount,
            reference=request.record_number,
        )
        expires_at = (
            datetime.now(UTC) + timedelta(minutes=max(1, int(request.expires_in_minutes)))
        ).isoformat()
        return CreatedPaymentRequest(
            provider=BillingPaymentProvider.MOCK_PROMPTPAY,
            payment_method=BillingPaymentMethod.PROMPTPAY_QR,
            status=BillingPaymentRequestStatus.PENDING,
            provider_reference=provider_reference,
            payment_url=f"{self._base_url}/checkout/{provider_reference}",
            qr_payload=qr_payload,
            qr_svg=render_promptpay_qr_svg(qr_payload),
            amount=request.amount,
            currency=request.currency,
            expires_at=expires_at,
        )

    def parse_callback(
        self,
        *,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
        raw_body: str | None = None,
    ) -> ParsedPaymentCallback:
        del headers, raw_body
        provider_event_id = str(payload.get("provider_event_id") or "").strip()
        occurred_at = str(payload.get("occurred_at") or "").strip()
        if not provider_event_id:
            raise ValueError("provider_event_id is required")
        if not occurred_at:
            raise ValueError("occurred_at is required")
        status = BillingPaymentRequestStatus(str(payload.get("status") or "").strip())
        amount = f"{Decimal(str(payload.get('amount') or '0')).quantize(Decimal('0.01')):.2f}"
        currency = str(payload.get("currency") or "").strip() or "THB"
        reference_code = (
            str(payload.get("reference_code")).strip() if payload.get("reference_code") else None
        )
        return ParsedPaymentCallback(
            provider_event_id=provider_event_id,
            provider_reference=str(
                payload.get("provider_reference") or payload.get("reference_code") or ""
            ).strip(),
            status=status,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            reference_code=reference_code,
            payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
        )


class OpnProvider:
    _api_base_url = "https://api.omise.co"

    def __init__(
        self,
        *,
        secret_key: str,
        public_key: str | None = None,
        webhook_secret: str | None = None,
        base_url: str | None = None,
        web_base_url: str | None = None,
    ) -> None:
        self._secret_key = secret_key.strip()
        self._public_key = public_key.strip() if public_key else None
        self._webhook_secret = webhook_secret.strip() if webhook_secret else None
        self._base_url = base_url.strip().rstrip("/") if base_url else None
        self._web_base_url = web_base_url.strip().rstrip("/") if web_base_url else None

    @staticmethod
    def _normalized_headers(headers: dict[str, str] | None) -> dict[str, str]:
        if headers is None:
            return {}
        return {str(key).lower(): str(value) for key, value in headers.items()}

    @staticmethod
    def _decode_webhook_secret(secret: str) -> bytes:
        try:
            return base64.b64decode(secret, validate=True)
        except ValueError as exc:
            raise ValueError("invalid opn webhook secret") from exc

    def _verify_webhook_signature(
        self,
        *,
        headers: dict[str, str] | None,
        raw_body: str | None,
    ) -> None:
        if raw_body is None:
            raise ValueError("invalid opn webhook signature")

        normalized_headers = self._normalized_headers(headers)

        legacy_signature = str(normalized_headers.get("x-opn-signature") or "").strip()
        if legacy_signature:
            expected_legacy = base64.b64encode(
                hmac.new(
                    self._secret_key.encode("utf-8"),
                    raw_body.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("ascii")
            if hmac.compare_digest(legacy_signature, expected_legacy):
                return

        omise_signature_header = str(
            normalized_headers.get("omise-signature")
            or normalized_headers.get("x-omise-signature")
            or ""
        ).strip()
        omise_timestamp = str(
            normalized_headers.get("omise-signature-timestamp")
            or normalized_headers.get("x-omise-signature-timestamp")
            or ""
        ).strip()
        if omise_signature_header and omise_timestamp:
            signatures = [item.strip().lower() for item in omise_signature_header.split(",")]
            signatures = [item for item in signatures if item]
            signed_payload = f"{omise_timestamp}.{raw_body}".encode("utf-8")

            secret_candidates: list[bytes] = [self._secret_key.encode("utf-8")]
            if self._webhook_secret:
                secret_candidates.insert(0, self._decode_webhook_secret(self._webhook_secret))
            for secret in secret_candidates:
                expected_hex = hmac.new(secret, signed_payload, hashlib.sha256).hexdigest()
                if any(hmac.compare_digest(signature, expected_hex) for signature in signatures):
                    return

        raise ValueError("invalid opn webhook signature")

    @staticmethod
    def _flatten_payload(
        payload: dict[str, object],
        *,
        prefix: str | None = None,
    ) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for key, value in payload.items():
            if value is None:
                continue
            full_key = f"{prefix}[{key}]" if prefix else key
            if isinstance(value, dict):
                items.extend(OpnProvider._flatten_payload(value, prefix=full_key))
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    if item is None:
                        continue
                    items.append((f"{full_key}[]", str(item)))
                continue
            items.append((full_key, str(value)))
        return items

    def _request(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        encoded_payload = None
        headers = {
            "Authorization": f"Basic {base64.b64encode(f'{self._secret_key}:'.encode('utf-8')).decode('ascii')}",
            "Accept": "application/json",
        }
        if payload is not None:
            encoded_payload = parse.urlencode(self._flatten_payload(payload)).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib_request.Request(
            url=f"{self._api_base_url}{path}",
            data=encoded_payload,
            headers=headers,
            method=method,
        )
        try:
            with urllib_request.urlopen(req, timeout=15) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"opn api request failed: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError("opn api request failed") from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("opn api returned invalid json") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("opn api returned invalid payload")
        return parsed

    @staticmethod
    def _is_public_https_url(url: str | None) -> bool:
        if not url:
            return False
        parsed = parse.urlparse(url)
        hostname = (parsed.hostname or "").strip().lower()
        if parsed.scheme != "https":
            return False
        return hostname not in {"localhost", "127.0.0.1", "0.0.0.0"} and not hostname.endswith(
            ".local"
        )

    def _build_webhook_endpoint(self) -> str | None:
        if not self._is_public_https_url(self._base_url):
            return None
        return f"{self._base_url}/v1/billing/providers/opn/webhooks"

    def _build_billing_return_uri(self, *, billing_record_id: str) -> str | None:
        if not self._is_public_https_url(self._web_base_url):
            return None
        query = parse.urlencode({"record_id": billing_record_id, "payment_return": "opn"})
        return f"{self._web_base_url}/billing?{query}"

    @staticmethod
    def _to_subunits(amount: str) -> int:
        return int((Decimal(str(amount)) * Decimal("100")).quantize(Decimal("1")))

    @staticmethod
    def _from_subunits(amount: object) -> str:
        return f"{(Decimal(str(amount or '0')) / Decimal('100')).quantize(Decimal('0.01')):.2f}"

    @staticmethod
    def _normalize_status(
        status: str, *, event_key: str | None = None
    ) -> BillingPaymentRequestStatus:
        normalized = status.strip().lower()
        if normalized in {"successful", "paid"} or event_key == "charge.complete":
            return BillingPaymentRequestStatus.SETTLED
        if normalized in {"failed"}:
            return BillingPaymentRequestStatus.FAILED
        if normalized in {"expired"}:
            return BillingPaymentRequestStatus.EXPIRED
        if normalized in {"reversed", "cancelled"}:
            return BillingPaymentRequestStatus.CANCELLED
        return BillingPaymentRequestStatus.PENDING

    def create_payment_request(self, *, request: ProviderPaymentRequest) -> CreatedPaymentRequest:
        if request.provider is not BillingPaymentProvider.OPN:
            raise ValueError("requested payment provider is not configured")
        normalized_currency = request.currency.strip().upper() or "THB"
        amount_subunits = self._to_subunits(request.amount)
        if request.payment_method is BillingPaymentMethod.PROMPTPAY_QR:
            if normalized_currency != "THB":
                raise ValueError("PromptPay only supports THB")
            source = self._request(
                method="POST",
                path="/sources",
                payload={
                    "amount": amount_subunits,
                    "currency": normalized_currency.lower(),
                    "type": "promptpay",
                },
            )
            charge_payload: dict[str, object] = {
                "amount": amount_subunits,
                "currency": normalized_currency.lower(),
                "source": source.get("id"),
                "description": f"Billing record {request.record_number}",
                "metadata": {
                    "billing_record_id": request.billing_record_id,
                    "record_number": request.record_number,
                },
            }
            return_uri = self._build_billing_return_uri(
                billing_record_id=request.billing_record_id,
            )
            if return_uri:
                charge_payload["return_uri"] = return_uri
            webhook_endpoint = self._build_webhook_endpoint()
            if webhook_endpoint:
                charge_payload["webhook_endpoints"] = [webhook_endpoint]
            charge = self._request(
                method="POST",
                path="/charges",
                payload=charge_payload,
            )
            source_payload = (
                charge.get("source") if isinstance(charge.get("source"), dict) else source
            )
            scannable_code = (
                source_payload.get("scannable_code") if isinstance(source_payload, dict) else None
            )
            qr_payload = (
                str(scannable_code.get("value") or "").strip()
                if isinstance(scannable_code, dict)
                else ""
            )
            qr_image = ""
            if isinstance(scannable_code, dict):
                image = scannable_code.get("image")
                if isinstance(image, dict):
                    qr_image = str(image.get("download_uri") or image.get("uri") or "").strip()
            payment_url = str(charge.get("authorize_uri") or "").strip()
            if not payment_url:
                payment_url = qr_image or f"{self._api_base_url}/charges/{str(charge.get('id') or '').strip()}"
            return CreatedPaymentRequest(
                provider=BillingPaymentProvider.OPN,
                payment_method=BillingPaymentMethod.PROMPTPAY_QR,
                status=self._normalize_status(str(charge.get("status") or "pending")),
                provider_reference=str(charge.get("id") or "").strip(),
                payment_url=payment_url,
                qr_payload=qr_payload,
                qr_svg=render_promptpay_qr_svg(qr_payload) if qr_payload else "",
                amount=request.amount,
                currency=normalized_currency,
                expires_at=str(
                    source_payload.get("expires_at") or charge.get("expires_at") or ""
                ).strip(),
            )

        if request.payment_method is BillingPaymentMethod.CARD:
            link = self._request(
                method="POST",
                path="/links",
                payload={
                    "amount": amount_subunits,
                    "currency": normalized_currency.lower(),
                    "title": f"Invoice {request.record_number}",
                    "description": f"Billing record {request.record_number}",
                    "multiple": "false",
                    "metadata": {
                        "billing_record_id": request.billing_record_id,
                        "record_number": request.record_number,
                    },
                },
            )
            return CreatedPaymentRequest(
                provider=BillingPaymentProvider.OPN,
                payment_method=BillingPaymentMethod.CARD,
                status=self._normalize_status(str(link.get("status") or "pending")),
                provider_reference=str(link.get("id") or "").strip(),
                payment_url=str(link.get("payment_uri") or "").strip(),
                qr_payload="",
                qr_svg="",
                amount=request.amount,
                currency=normalized_currency,
                expires_at=str(link.get("expires_at") or "").strip(),
            )

        raise ValueError("unsupported payment method")

    def parse_callback(
        self,
        *,
        payload: dict[str, object],
        headers: dict[str, str] | None = None,
        raw_body: str | None = None,
    ) -> ParsedPaymentCallback:
        self._verify_webhook_signature(headers=headers, raw_body=raw_body)
        event_id = str(payload.get("id") or "").strip()
        event_key = str(payload.get("key") or "").strip()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            raise ValueError("invalid opn webhook payload")
        object_type = str(data.get("object") or "").strip().lower()
        provider_reference = str(data.get("id") or "").strip()
        reference_code = None
        if object_type == "charge":
            verified = self._request(method="GET", path=f"/charges/{provider_reference}")
            link_reference = verified.get("link")
            if isinstance(link_reference, dict):
                provider_reference = str(link_reference.get("id") or "").strip()
            else:
                provider_reference = str(link_reference or "").strip()
            if not provider_reference:
                provider_reference = str(verified.get("id") or provider_reference).strip()
            reference_code = str(verified.get("id") or "").strip() or None
            amount = self._from_subunits(verified.get("amount"))
            currency = (
                str(verified.get("currency") or data.get("currency") or "THB").strip().upper()
            )
            status = self._normalize_status(
                str(verified.get("status") or data.get("status") or ""), event_key=event_key or None
            )
            occurred_at = str(
                verified.get("paid_at") or payload.get("created") or data.get("created") or ""
            ).strip()
        elif object_type == "link":
            verified = self._request(method="GET", path=f"/links/{provider_reference}")
            provider_reference = str(verified.get("id") or provider_reference).strip()
            charges = verified.get("charges")
            first_charge = charges[0] if isinstance(charges, list) and charges else None
            if isinstance(first_charge, dict) and first_charge.get("id"):
                reference_code = str(first_charge.get("id")).strip()
            amount = self._from_subunits(verified.get("amount"))
            currency = (
                str(verified.get("currency") or data.get("currency") or "THB").strip().upper()
            )
            status = self._normalize_status(
                str(verified.get("status") or data.get("status") or ""), event_key=event_key or None
            )
            occurred_at = str(
                verified.get("paid_at") or payload.get("created") or data.get("created") or ""
            ).strip()
        else:
            raise ValueError("unsupported opn webhook payload")
        if not event_id:
            event_id = f"opn_{provider_reference}_{event_key or status.value}"
        if not provider_reference:
            raise ValueError("provider reference is required")
        if not occurred_at:
            raise ValueError("occurred_at is required")
        return ParsedPaymentCallback(
            provider_event_id=event_id,
            provider_reference=provider_reference,
            status=status,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            reference_code=reference_code,
            payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
        )


def build_payment_provider(
    *,
    provider_name: str,
    base_url: str,
    promptpay_proxy_id: str | None,
    opn_public_key: str | None = None,
    opn_secret_key: str | None = None,
    opn_webhook_secret: str | None = None,
    web_base_url: str | None = None,
) -> PaymentProvider | None:
    provider = BillingPaymentProvider(str(provider_name).strip())
    if provider is BillingPaymentProvider.MOCK_PROMPTPAY:
        if not promptpay_proxy_id:
            return None
        return MockPromptPayProvider(base_url=base_url, promptpay_proxy_id=promptpay_proxy_id)
    if provider is BillingPaymentProvider.OPN:
        if not opn_secret_key:
            return None
        return OpnProvider(
            secret_key=opn_secret_key,
            public_key=opn_public_key,
            webhook_secret=opn_webhook_secret,
            base_url=base_url,
            web_base_url=web_base_url,
        )
    return None
