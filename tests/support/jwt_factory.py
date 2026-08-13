"""Strict positive machine-JWT fixtures shared by API tests."""

from __future__ import annotations

import time
from typing import Any

import jwt


TEST_JWT_ISSUER = "https://issuer.test.egp.local"
TEST_JWT_AUDIENCE = "egp-api-test"


def mint_machine_jwt(
    *,
    secret: str,
    tenant_id: str,
    subject: str = "user-123",
    role: str | None = None,
    lifetime_seconds: int = 300,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": TEST_JWT_ISSUER,
        "aud": TEST_JWT_AUDIENCE,
        "exp": now + lifetime_seconds,
        "iat": now,
        "sub": subject,
        "tenant_id": tenant_id,
    }
    if role is not None:
        claims["role"] = role
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, secret, algorithm="HS256")
