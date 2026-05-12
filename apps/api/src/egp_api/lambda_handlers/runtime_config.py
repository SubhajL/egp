"""Runtime configuration helpers for Lambda handlers."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

import boto3

from egp_shared_types.enums import BillingPaymentProvider


class LambdaConfigurationError(RuntimeError):
    """Raised when the Lambda runtime is missing required configuration."""


@dataclass(frozen=True, slots=True)
class LambdaRuntimeConfig:
    database_url: str
    payment_provider: str
    opn_secret_key: str
    opn_public_key: str | None


def _parse_json_bundle(raw_value: str, *, source: str) -> dict[str, str | None]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise LambdaConfigurationError(f"{source} must contain a JSON object") from exc
    if not isinstance(parsed, dict):
        raise LambdaConfigurationError(f"{source} must contain a JSON object")
    normalized: dict[str, str | None] = {}
    for key, value in parsed.items():
        normalized[str(key)] = None if value is None else str(value)
    return normalized


def _load_bundle_from_secrets_manager(
    secret_arn: str,
    *,
    secrets_client: Any | None = None,
) -> dict[str, str | None]:
    client = secrets_client or boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_arn)
    raw_secret = response.get("SecretString")
    if not raw_secret and response.get("SecretBinary"):
        raw_secret = base64.b64decode(response["SecretBinary"]).decode("utf-8")
    if not raw_secret:
        raise LambdaConfigurationError("Secrets Manager secret is empty")
    return _parse_json_bundle(raw_secret, source="Secrets Manager secret")


def _load_bundle_from_ssm_parameter(
    parameter_name: str,
    *,
    ssm_client: Any | None = None,
) -> dict[str, str | None]:
    client = ssm_client or boto3.client("ssm")
    response = client.get_parameter(Name=parameter_name, WithDecryption=True)
    value = response.get("Parameter", {}).get("Value")
    if not value:
        raise LambdaConfigurationError("SSM parameter is empty")
    return _parse_json_bundle(str(value), source="SSM parameter")


def load_runtime_config(
    *,
    env: Mapping[str, str] | None = None,
    secrets_client: Any | None = None,
    ssm_client: Any | None = None,
) -> LambdaRuntimeConfig:
    source_env = env or os.environ
    bundle: dict[str, str | None] = {}

    secret_arn = str(source_env.get("EGP_LAMBDA_CONFIG_SECRET_ARN") or "").strip()
    ssm_parameter = str(source_env.get("EGP_LAMBDA_CONFIG_SSM_PARAMETER") or "").strip()

    if secret_arn:
        bundle = _load_bundle_from_secrets_manager(
            secret_arn,
            secrets_client=secrets_client,
        )
    elif ssm_parameter:
        bundle = _load_bundle_from_ssm_parameter(
            ssm_parameter,
            ssm_client=ssm_client,
        )

    database_url = str(source_env.get("DATABASE_URL") or bundle.get("database_url") or "").strip()
    payment_provider = str(
        source_env.get("EGP_PAYMENT_PROVIDER")
        or bundle.get("payment_provider")
        or BillingPaymentProvider.OPN.value
    ).strip()
    opn_secret_key = str(
        source_env.get("EGP_OPN_SECRET_KEY") or bundle.get("opn_secret_key") or ""
    ).strip()
    opn_public_key = str(
        source_env.get("EGP_OPN_PUBLIC_KEY") or bundle.get("opn_public_key") or ""
    ).strip() or None

    if not database_url:
        raise LambdaConfigurationError("DATABASE_URL is required")
    if payment_provider == BillingPaymentProvider.OPN.value and not opn_secret_key:
        raise LambdaConfigurationError("EGP_OPN_SECRET_KEY is required")

    return LambdaRuntimeConfig(
        database_url=database_url,
        payment_provider=payment_provider,
        opn_secret_key=opn_secret_key,
        opn_public_key=opn_public_key,
    )
