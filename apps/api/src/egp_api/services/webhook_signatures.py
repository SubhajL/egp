"""Shared webhook signature verification primitives.

Both the LINE webhook (X-Line-Signature) and the OPN legacy webhook
(x-opn-signature) authenticate with base64(HMAC-SHA256(secret, raw_body)).
Sharing one constant-time verifier keeps the unauthenticated public endpoints
on a single, vetted implementation rather than hand-rolled copies that can drift.
"""

from __future__ import annotations

import base64
import hashlib
import hmac


def verify_hmac_sha256_base64(
    *, secret: str | None, raw_body: bytes, signature: str | None
) -> bool:
    """Return True iff ``signature == base64(HMAC-SHA256(secret, raw_body))``.

    Fails closed (returns False) when the secret or signature is missing.
    Comparison is constant-time.
    """
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature.strip())
