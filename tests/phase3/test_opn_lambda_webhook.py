from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from egp_api.lambda_handlers import opn_webhook, runtime_config
from egp_api.main import create_app
from egp_api.services.payment_provider import CreatedPaymentRequest, ParsedPaymentCallback
from egp_shared_types.enums import (
    BillingPaymentMethod,
    BillingPaymentProvider,
    BillingPaymentRequestStatus,
)

TENANT_ID = "11111111-1111-1111-1111-111111111111"


def _utc_today() -> date:
    return datetime.now(UTC).date()


class StubOpnProvider:
    def __init__(self) -> None:
        self.last_amount = "25.00"

    def create_payment_request(self, *, request):
        self.last_amount = str(request.amount)
        return CreatedPaymentRequest(
            provider=BillingPaymentProvider.OPN,
            payment_method=BillingPaymentMethod.PROMPTPAY_QR,
            status=BillingPaymentRequestStatus.PENDING,
            provider_reference="chrg_test_promptpay_001",
            payment_url="https://api.omise.co/charges/chrg_test_promptpay_001/qrcode.svg",
            qr_payload="0002010102121234",
            qr_svg="<svg></svg>",
            amount=request.amount,
            currency=request.currency,
            expires_at="2026-04-05T05:30:00+00:00",
        )

    def parse_callback(self, *, payload, headers=None, raw_body=None):
        signature = str((headers or {}).get("x-opn-signature") or "").strip()
        expected = _opn_signature("skey_test_opn", raw_body or "")
        if not signature or raw_body is None or signature != expected:
            raise ValueError("invalid opn webhook signature")
        return ParsedPaymentCallback(
            provider_event_id=str(payload.get("id") or "evt_test_promptpay_001"),
            provider_reference="chrg_test_promptpay_001",
            status=BillingPaymentRequestStatus.SETTLED,
            amount=f"{Decimal(self.last_amount):.2f}",
            currency="THB",
            occurred_at="2026-04-05T05:30:00+00:00",
            reference_code="chrg_test_promptpay_001",
            payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
        )


def _create_client(tmp_path, provider: StubOpnProvider) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase3-opn-lambda.sqlite3'}"
    return TestClient(
        create_app(
            artifact_root=tmp_path,
            database_url=database_url,
            auth_required=False,
            payment_provider=provider,
            payment_base_url="https://pay.egp.test",
            promptpay_proxy_id="0801234567",
            payment_callback_secret="top-secret",
            opn_secret_key="skey_test_opn",
        )
    )


def _create_billing_record(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/billing/records",
        json={
            "tenant_id": TENANT_ID,
            "record_number": "INV-2026-4001",
            "plan_code": "monthly_membership",
            "status": "awaiting_payment",
            "billing_period_start": _utc_today().isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_opn_payment_request(client: TestClient, *, record_id: str) -> dict[str, object]:
    response = client.post(
        f"/v1/billing/records/{record_id}/payment-requests",
        json={
            "tenant_id": TENANT_ID,
            "provider": "opn",
            "payment_method": "promptpay_qr",
            "expires_in_minutes": 30,
        },
    )
    assert response.status_code == 201
    return response.json()


class _FakeSecretsManagerClient:
    def __init__(self, secret_string: str) -> None:
        self._secret_string = secret_string

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        return {"SecretString": self._secret_string}


class _FakeSsmClient:
    def __init__(self, parameter_value: str) -> None:
        self._parameter_value = parameter_value

    def get_parameter(self, *, Name: str, WithDecryption: bool) -> dict[str, dict[str, str]]:
        return {"Parameter": {"Value": self._parameter_value}}


def _opn_signature(secret: str, raw_body: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def test_runtime_config_supports_secrets_manager_bundle(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("EGP_OPN_SECRET_KEY", raising=False)
    monkeypatch.setenv("EGP_LAMBDA_CONFIG_SECRET_ARN", "arn:aws:secretsmanager:ap-southeast-1:123456789012:secret:egp/opn")

    config = runtime_config.load_runtime_config(
        secrets_client=_FakeSecretsManagerClient(
            json.dumps(
                {
                    "database_url": "postgresql+psycopg://secret-user:secret-pass@db.example:5432/egp",
                    "opn_secret_key": "skey_test_secret_bundle",
                    "opn_public_key": "pkey_test_secret_bundle",
                    "opn_webhook_secret": "dGVzdC13ZWJob29rLXNlY3JldA==",
                }
            )
        )
    )

    assert config.database_url == "postgresql+psycopg://secret-user:secret-pass@db.example:5432/egp"
    assert config.opn_secret_key == "skey_test_secret_bundle"
    assert config.opn_public_key == "pkey_test_secret_bundle"
    assert config.opn_webhook_secret == "dGVzdC13ZWJob29rLXNlY3JldA=="


def test_runtime_config_supports_ssm_bundle(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("EGP_OPN_SECRET_KEY", raising=False)
    monkeypatch.delenv("EGP_LAMBDA_CONFIG_SECRET_ARN", raising=False)
    monkeypatch.setenv("EGP_LAMBDA_CONFIG_SSM_PARAMETER", "/egp/opn-webhook/config")

    config = runtime_config.load_runtime_config(
        ssm_client=_FakeSsmClient(
            json.dumps(
                {
                    "database_url": "postgresql+psycopg://ssm-user:ssm-pass@db.example:5432/egp",
                    "opn_secret_key": "skey_test_ssm_bundle",
                }
            )
        )
    )

    assert config.database_url == "postgresql+psycopg://ssm-user:ssm-pass@db.example:5432/egp"
    assert config.opn_secret_key == "skey_test_ssm_bundle"
    assert config.opn_public_key is None
    assert config.opn_webhook_secret is None


def test_lambda_handler_processes_opn_webhook_and_remains_idempotent(
    tmp_path, monkeypatch
) -> None:
    provider = StubOpnProvider()
    client = _create_client(tmp_path, provider)
    created = _create_billing_record(client)
    record_id = str(created["record"]["id"])
    _create_opn_payment_request(client, record_id=record_id)

    database_url = f"sqlite+pysqlite:///{tmp_path / 'phase3-opn-lambda.sqlite3'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("EGP_PAYMENT_PROVIDER", "opn")
    monkeypatch.setenv("EGP_OPN_SECRET_KEY", "skey_test_opn")
    monkeypatch.delenv("EGP_OPN_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(opn_webhook, "build_payment_provider", lambda **kwargs: provider)
    opn_webhook._CACHED_BILLING_SERVICE = None

    raw_body = json.dumps(
        {
            "id": "evt_test_promptpay_001",
            "key": "charge.complete",
            "data": {
                "object": "charge",
                "id": "chrg_test_promptpay_001",
            },
        },
        separators=(",", ":"),
    )
    event = {
        "headers": {
            "content-type": "application/json",
            "x-opn-signature": _opn_signature("skey_test_opn", raw_body),
        },
        "body": raw_body,
        "isBase64Encoded": False,
    }

    first = opn_webhook.lambda_handler(event, context={})
    second = opn_webhook.lambda_handler(event, context={})

    assert first["statusCode"] == 200
    assert second["statusCode"] == 200
    first_body = json.loads(first["body"])
    second_body = json.loads(second["body"])
    assert first_body["status"] == "processed"
    assert second_body["status"] == "processed"
    assert first_body["billing_record_id"] == record_id
    assert second_body["billing_record_id"] == record_id
    assert first_body["record_status"] == "paid"
    assert second_body["record_status"] == "paid"

    detail = client.app.state.billing_repository.get_billing_record_detail(
        tenant_id=TENANT_ID,
        record_id=record_id,
    )
    assert detail is not None
    assert detail.record.status.value == "paid"
    assert len(detail.payments) == 1
    assert detail.payment_requests[0].status.value == "settled"


def test_lambda_handler_returns_503_when_database_url_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("EGP_PAYMENT_PROVIDER", "opn")
    monkeypatch.setenv("EGP_OPN_SECRET_KEY", "skey_test_opn")
    opn_webhook._CACHED_BILLING_SERVICE = None

    response = opn_webhook.lambda_handler({"body": "{}", "headers": {}}, context={})

    assert response["statusCode"] == 503
    assert json.loads(response["body"]) == {"detail": "DATABASE_URL is required"}
