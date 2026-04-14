"""Encryption helpers for tenant-owned storage credentials."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class StorageCredentialCipher:
    def __init__(self, secret: str | None) -> None:
        normalized_secret = (secret or "").strip()
        if not normalized_secret:
            raise ValueError("storage credentials secret is required")
        key = base64.urlsafe_b64encode(hashlib.sha256(normalized_secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt_dict(self, payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(encoded).decode("utf-8")

    def decrypt_dict(self, encrypted_payload: str) -> dict[str, Any]:
        try:
            decrypted = self._fernet.decrypt(encrypted_payload.encode("utf-8"))
        except InvalidToken as exc:
            raise ValueError("stored storage credentials could not be decrypted") from exc
        parsed = json.loads(decrypted.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("stored storage credentials are malformed")
        return parsed
