"""Unit tests for the pure LINE integration helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac

from egp_api.services.line_integration import (
    LineMessageEvent,
    extract_reference_code,
    parse_message_events,
    verify_line_signature,
)

CHANNEL_SECRET = "line-channel-secret-test"


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_verify_signature_accepts_valid_hmac() -> None:
    body = b'{"events":[]}'
    assert verify_line_signature(
        channel_secret=CHANNEL_SECRET, raw_body=body, signature_header=_sign(CHANNEL_SECRET, body)
    )


def test_verify_signature_rejects_tampered_body() -> None:
    body = b'{"events":[]}'
    sig = _sign(CHANNEL_SECRET, body)
    assert not verify_line_signature(
        channel_secret=CHANNEL_SECRET, raw_body=b'{"events":[1]}', signature_header=sig
    )


def test_verify_signature_fails_closed_without_secret_or_header() -> None:
    body = b"{}"
    assert not verify_line_signature(channel_secret=None, raw_body=body, signature_header="x")
    assert not verify_line_signature(
        channel_secret=CHANNEL_SECRET, raw_body=body, signature_header=None
    )


def test_extract_reference_finds_inv_pattern() -> None:
    assert extract_reference_code("ขอชำระเงิน Reference: INV-2026-0001 ครับ") == "INV-2026-0001"
    assert extract_reference_code("inv-2026-0123") == "INV-2026-0123"


def test_extract_reference_labelled_fallback() -> None:
    assert extract_reference_code("Reference: ABC-99-XYZ") == "ABC-99-XYZ"


def test_extract_reference_returns_none_when_absent() -> None:
    assert extract_reference_code("สวัสดีครับ") is None
    assert extract_reference_code(None) is None


def test_parse_message_events_extracts_text_and_image() -> None:
    payload = {
        "events": [
            {
                "type": "message",
                "timestamp": 1700000000000,
                "source": {"userId": "Uabc"},
                "message": {"type": "text", "id": "100", "text": "INV-2026-0001"},
            },
            {
                "type": "message",
                "source": {"userId": "Uabc"},
                "message": {"type": "image", "id": "101"},
            },
            {"type": "follow", "source": {"userId": "Uxyz"}},
        ]
    }
    events = parse_message_events(payload)
    assert len(events) == 2
    assert isinstance(events[0], LineMessageEvent)
    assert events[0].message_type == "text"
    assert events[0].text == "INV-2026-0001"
    assert events[0].line_user_id == "Uabc"
    assert events[1].message_type == "image"
    assert events[1].message_id == "101"


def test_parse_message_events_handles_malformed_payload() -> None:
    assert parse_message_events({}) == []
    assert parse_message_events({"events": "nope"}) == []
    assert parse_message_events("not-a-dict") == []
