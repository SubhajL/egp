"""LINE Messaging API integration primitives.

Pure helpers (signature verification, reference extraction, event parsing) plus
an HTTP messaging client implemented over stdlib ``urllib`` — mirroring the
``OpnProvider`` / ``StripeProvider`` pattern so there is no extra SDK dependency.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib import parse, request as urllib_request

from egp_api.services.webhook_signatures import verify_hmac_sha256_base64

LINE_CONTENT_URL = "https://api-data.line.me/v2/bot/message/{message_id}/content"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

# e-GP billing record numbers come in several shapes: INV-2026-0001 (manual),
# UPG-{PLAN}-{YYYYMMDD} (upgrades — note PLAN can contain underscores), and
# TRIAL-{hex}. Match those token shapes first; fall back to a labelled
# "Reference: <code>" capture (underscore-aware) for any operator-custom format.
_REFERENCE_PATTERN = re.compile(
    r"\b(?:INV|UPG|TRIAL)-[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*\b",
    re.IGNORECASE,
)
_LABELLED_PATTERN = re.compile(
    r"(?:reference|ref|อ้างอิง)\s*[:：]?\s*([A-Za-z0-9_\-]{4,})",
    re.IGNORECASE,
)


def verify_line_signature(
    *, channel_secret: str | None, raw_body: bytes, signature_header: str | None
) -> bool:
    """Return True iff ``X-Line-Signature`` matches HMAC-SHA256(secret, body).

    Fails closed when the secret or signature header is missing.
    """
    return verify_hmac_sha256_base64(
        secret=channel_secret, raw_body=raw_body, signature=signature_header
    )


def extract_reference_code(text: str | None) -> str | None:
    """Pull a billing reference code (record number) out of free LINE text."""
    if not text:
        return None
    match = _REFERENCE_PATTERN.search(text)
    if match:
        return match.group(0).upper()
    labelled = _LABELLED_PATTERN.search(text)
    if labelled:
        return labelled.group(1).strip().upper()
    return None


@dataclass(frozen=True, slots=True)
class LineMessageEvent:
    event_type: str
    message_type: str | None
    message_id: str | None
    text: str | None
    line_user_id: str | None
    timestamp: int | None


def parse_message_events(payload: object) -> list[LineMessageEvent]:
    """Extract message events (with a userId) from a LINE webhook payload."""
    events: list[LineMessageEvent] = []
    raw_events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(raw_events, list):
        return events
    for raw in raw_events:
        if not isinstance(raw, dict) or raw.get("type") != "message":
            continue
        message = raw.get("message") if isinstance(raw.get("message"), dict) else {}
        source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
        timestamp = raw.get("timestamp")
        events.append(
            LineMessageEvent(
                event_type="message",
                message_type=(
                    str(message.get("type")) if message.get("type") else None
                ),
                message_id=str(message.get("id")) if message.get("id") else None,
                text=message.get("text") if isinstance(message.get("text"), str) else None,
                line_user_id=str(source.get("userId")) if source.get("userId") else None,
                timestamp=int(timestamp) if isinstance(timestamp, (int, float)) else None,
            )
        )
    return events


class LineMessagingClient(Protocol):
    def get_message_content(self, message_id: str) -> tuple[bytes, str | None]: ...

    def push_message(self, *, to: str, text: str) -> None: ...


class HttpLineMessagingClient:
    """Concrete LINE Messaging API client over stdlib urllib."""

    _content_url = LINE_CONTENT_URL
    _push_url = LINE_PUSH_URL

    def __init__(self, *, channel_access_token: str, timeout_seconds: float = 10.0) -> None:
        self._token = channel_access_token.strip()
        self._timeout = timeout_seconds

    def get_message_content(self, message_id: str) -> tuple[bytes, str | None]:
        url = self._content_url.format(message_id=parse.quote(str(message_id), safe=""))
        request = urllib_request.Request(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        with urllib_request.urlopen(request, timeout=self._timeout) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type")
        return data, content_type

    def push_message(self, *, to: str, text: str) -> None:
        body = json.dumps(
            {"to": to, "messages": [{"type": "text", "text": text[:5000]}]}
        ).encode("utf-8")
        request = urllib_request.Request(
            self._push_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib_request.urlopen(request, timeout=self._timeout) as response:
            response.read()
