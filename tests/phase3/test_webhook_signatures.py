"""Unit tests for the shared HMAC-SHA256/base64 webhook verifier."""

from __future__ import annotations

import base64
import hashlib
import hmac

from egp_api.services.webhook_signatures import verify_hmac_sha256_base64

SECRET = "shared-webhook-secret"


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_accepts_valid_signature() -> None:
    body = b'{"events":[1]}'
    assert verify_hmac_sha256_base64(secret=SECRET, raw_body=body, signature=_sign(SECRET, body))


def test_rejects_tampered_body_or_secret() -> None:
    body = b"abc"
    sig = _sign(SECRET, body)
    assert not verify_hmac_sha256_base64(secret=SECRET, raw_body=b"xyz", signature=sig)
    assert not verify_hmac_sha256_base64(secret="wrong", raw_body=body, signature=sig)


def test_fails_closed_on_missing_inputs() -> None:
    assert not verify_hmac_sha256_base64(secret=None, raw_body=b"x", signature="s")
    assert not verify_hmac_sha256_base64(secret=SECRET, raw_body=b"x", signature=None)
    assert not verify_hmac_sha256_base64(secret="", raw_body=b"x", signature="s")
