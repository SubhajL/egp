from __future__ import annotations

import pytest

from egp_shared_types.exact_canary import ExactIngestionCanaryTarget
from egp_worker.workflows.discover import LiveCanaryProofAccumulator


def _target() -> ExactIngestionCanaryTarget:
    return ExactIngestionCanaryTarget.from_mapping(
        {
            "contract_version": 1,
            "kind": "exact_ingestion_canary",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "job_id": "22222222-2222-2222-2222-222222222222",
            "profile_id": "33333333-3333-3333-3333-333333333333",
            "keyword": "วิเคราะห์ข้อมูล",
            "live": True,
            "execution_backend": "legacy",
            "browser_required": True,
            "max_pages_per_keyword": 15,
        }
    )


def _accepted_accumulator() -> LiveCanaryProofAccumulator:
    target = _target()
    accumulator = LiveCanaryProofAccumulator(target=target)
    accumulator.record_progress(
        {
            "stage": "browser_session_started",
            "browser_engine": "chrome_cdp",
            "browser_required": True,
        }
    )
    for page_num in range(1, 6):
        accumulator.record_progress(
            {
                "stage": "page_scan_finished",
                "keyword": target.keyword,
                "page_num": page_num,
            }
        )
    accumulator.record_progress(
        {
            "stage": "pagination_terminal",
            "keyword": target.keyword,
            "page_num": 5,
            "pagination_outcome": "next_control_absent",
        }
    )
    accumulator.record_persisted_candidate(page_number=2)
    return accumulator


def test_live_canary_proof_accepts_ordered_pages_under_pinned_cap() -> None:
    target = _target()

    assert _accepted_accumulator().build() == {
        "contract_version": 1,
        "target_digest": target.canonical_digest(),
        "browser_started": True,
        "page_sequence": [1, 2, 3, 4, 5],
        "max_pages_per_keyword": 15,
        "terminal_outcome": "next_control_absent",
        "later_page_persisted": True,
    }


def test_live_canary_proof_allows_page_one_candidate_when_later_page_persists() -> None:
    accumulator = _accepted_accumulator()

    accumulator.record_persisted_candidate(page_number=1)

    assert accumulator.build()["later_page_persisted"] is True


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda accumulator: accumulator.record_progress(
                {
                    "stage": "page_scan_finished",
                    "keyword": _target().keyword,
                    "page_num": 6,
                }
            ),
            "event_after_terminal",
        ),
        (
            lambda accumulator: setattr(accumulator, "page_sequence", [1, 2, 2, 4, 5]),
            "page_sequence_invalid",
        ),
        (
            lambda accumulator: setattr(accumulator, "later_page_persisted", False),
            "later_page_not_persisted",
        ),
        (
            lambda accumulator: setattr(accumulator, "terminal_outcome", "max_pages_reached"),
            "max_pages_before_pinned_cap",
        ),
    ],
)
def test_live_canary_proof_rejects_invalid_order_terminal_or_persistence(
    mutate,
    reason: str,
) -> None:
    accumulator = _accepted_accumulator()
    mutate(accumulator)

    with pytest.raises(ValueError, match=reason):
        accumulator.build()


def test_live_canary_proof_rejects_page_before_browser_and_wrong_keyword() -> None:
    target = _target()
    page_first = LiveCanaryProofAccumulator(target=target)
    page_first.record_progress(
        {"stage": "page_scan_finished", "keyword": target.keyword, "page_num": 1}
    )
    with pytest.raises(ValueError, match="browser_start_missing"):
        page_first.build()

    wrong_keyword = LiveCanaryProofAccumulator(target=target)
    wrong_keyword.record_progress(
        {"stage": "browser_session_started", "browser_required": True}
    )
    wrong_keyword.record_progress(
        {"stage": "page_scan_finished", "keyword": "wrong", "page_num": 1}
    )
    with pytest.raises(ValueError, match="keyword_mismatch"):
        wrong_keyword.build()
