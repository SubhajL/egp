"""Helpers for converting worker payloads into JSON-safe structures."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any


def make_json_safe(value: object) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return make_json_safe(value.value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [make_json_safe(item) for item in value]
    return str(value)
