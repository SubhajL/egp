"""Helpers for enforcing invitation-stage-only project discovery."""

from __future__ import annotations

import re


_INVITATION_STAGE_MARKER = "ประกาศเชิญชวน"


def _compact_visible_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def is_invitation_stage_status(source_status_text: str | None) -> bool:
    """Return True when a status text denotes the invitation stage."""

    return _INVITATION_STAGE_MARKER in _compact_visible_text(source_status_text)
