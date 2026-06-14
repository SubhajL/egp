"""Helpers for enforcing invitation-stage-only project discovery."""

from __future__ import annotations

import re


_INVITATION_STAGE_MARKER = "ประกาศเชิญชวน"

# Statuses that are in-scope for discovery: invitation + pre-award stages.
# Match is whitespace-insensitive + casefolded (for the latin "TOR" token).
# These markers are specific enough to NOT match post-award statuses such as
# "จัดทำสัญญา/บริหารสัญญา", "อนุมัติ…ประกาศผู้ชนะการเสนอราคา", or "ยกเลิกโครงการ".
_DISCOVERABLE_STAGE_MARKERS = (
    "ประกาศเชิญชวน",  # invitation announcement
    "หนังสือเชิญชวน",  # invitation letter
    "ร่างเอกสารประกวดราคา",  # draft bidding docs (public hearing)
    "ร่างขอบเขตของงาน",  # draft TOR (public hearing)
    "ประชาพิจารณ์",  # public hearing
    "รับฟังความคิดเห็น",  # public hearing
    "รับฟังคำวิจารณ์",  # public hearing
    "จัดทำ TOR",  # drafting TOR
    "จัดทำทีโออาร์",  # drafting TOR (Thai spelling)
    "ราคากลาง",  # median price announcement
)


def _compact_visible_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def is_invitation_stage_status(source_status_text: str | None) -> bool:
    """Return True when a status text denotes the invitation stage."""

    return _INVITATION_STAGE_MARKER in _compact_visible_text(source_status_text)


def is_discoverable_stage_status(source_status_text: str | None) -> bool:
    """Return True when a status text is an in-scope discovery stage.

    In-scope = invitation + pre-award (draft TOR / public hearing / median price).
    Post-award statuses (contract, winner, cancelled) return False.
    """

    compact = _compact_visible_text(source_status_text).casefold()
    return any(
        _compact_visible_text(marker).casefold() in compact
        for marker in _DISCOVERABLE_STAGE_MARKERS
    )
