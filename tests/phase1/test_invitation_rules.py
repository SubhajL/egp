"""Eligibility-status rules for discovery (invitation + pre-award scope)."""

from __future__ import annotations

from egp_crawler_core.invitation_rules import (
    is_discoverable_stage_status,
    is_invitation_stage_status,
)


def test_invitation_status_is_discoverable_and_invitation() -> None:
    status = "หนังสือเชิญชวน/ประกาศเชิญชวน"
    assert is_discoverable_stage_status(status)
    assert is_invitation_stage_status(status)


def test_pre_award_statuses_are_discoverable() -> None:
    for status in (
        "จัดทำ TOR",
        "ร่างเอกสารประกวดราคา",
        "ประชาพิจารณ์",
        "ประกาศราคากลาง",
    ):
        assert is_discoverable_stage_status(status), status


def test_pre_award_drafting_is_discoverable_but_not_invitation_only() -> None:
    assert is_discoverable_stage_status("จัดทำ TOR")
    assert not is_invitation_stage_status("จัดทำ TOR")


def test_post_award_and_empty_statuses_are_not_discoverable() -> None:
    for status in (
        "จัดทำสัญญา/บริหารสัญญา",
        "อนุมัติสั่งซื้อสั่งจ้างและประกาศผู้ชนะการเสนอราคา",
        "ยกเลิกโครงการ",
        "-",
        "",
        None,
    ):
        assert not is_discoverable_stage_status(status), status
