"""Document hashing helpers."""

from __future__ import annotations

import hashlib


def hash_file(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
