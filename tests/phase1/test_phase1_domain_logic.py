from __future__ import annotations

from datetime import UTC, datetime, timedelta

from egp_document_classifier.classifier import classify_document, derive_artifact_bucket
from egp_crawler_core.closure_rules import (
    check_consulting_timeout,
    check_stale_closure,
    check_winner_closure,
)
from egp_crawler_core.document_hasher import hash_file
from egp_shared_types.enums import (
    ArtifactBucket,
    ClosedReason,
    DocumentPhase,
    DocumentType,
    ProcurementType,
    ProjectState,
)
from egp_crawler_core.canonical_id import build_project_aliases, generate_canonical_id
from egp_crawler_core.project_lifecycle import transition_state


def test_generate_canonical_id_prefers_project_number() -> None:
    canonical_id = generate_canonical_id(
        project_number="EGP-2026-0001",
        organization_name="กรมตัวอย่าง",
        project_name="ระบบข้อมูลกลาง",
        proposal_submission_date="2026-04-30",
        budget_amount="1000000.00",
    )

    assert canonical_id == "project-number:EGP-2026-0001"


def test_generate_canonical_id_falls_back_to_normalized_fingerprint() -> None:
    first = generate_canonical_id(
        project_number="",
        organization_name="กรม ตัวอย่าง ",
        project_name=" ระบบข้อมูลกลาง  ",
        proposal_submission_date="2026-04-30",
        budget_amount="1000000.00",
    )
    second = generate_canonical_id(
        project_number=None,
        organization_name="กรม ตัวอย่าง",
        project_name="ระบบข้อมูลกลาง",
        proposal_submission_date="2026-04-30",
        budget_amount="1000000",
    )

    assert first == second
    assert first.startswith("fingerprint:")


def test_build_project_aliases_includes_searchable_keys() -> None:
    aliases = build_project_aliases(
        project_number="EGP-2026-0001",
        search_name="ระบบข้อมูลกลาง",
        detail_name="โครงการระบบข้อมูลกลาง",
        organization_name="กรมตัวอย่าง",
        project_name="โครงการระบบข้อมูลกลาง",
        proposal_submission_date="2026-04-30",
        budget_amount="1000000.00",
    )

    assert ("project_number", "EGP-2026-0001") in aliases
    assert ("search_name", "ระบบข้อมูลกลาง") in aliases
    assert ("detail_name", "โครงการระบบข้อมูลกลาง") in aliases
    assert any(alias_type == "fingerprint" for alias_type, _ in aliases)


def test_transition_state_rejects_illegal_backward_move() -> None:
    try:
        transition_state(
            current_state=ProjectState.WINNER_ANNOUNCED,
            next_state=ProjectState.OPEN_INVITATION,
        )
    except ValueError as exc:
        assert "illegal" in str(exc).lower()
    else:
        raise AssertionError("expected illegal transition to raise ValueError")


def test_transition_state_requires_closed_reason_for_closed_state() -> None:
    try:
        transition_state(
            current_state=ProjectState.OPEN_CONSULTING,
            next_state=ProjectState.CLOSED_TIMEOUT_CONSULTING,
        )
    except ValueError as exc:
        assert "closed_reason" in str(exc)
    else:
        raise AssertionError("expected missing closed_reason to raise ValueError")


def test_check_consulting_timeout_after_threshold() -> None:
    now = datetime(2026, 4, 2, tzinfo=UTC)
    last_changed_at = now - timedelta(days=31)

    assert (
        check_consulting_timeout(
            procurement_type=ProcurementType.CONSULTING,
            last_changed_at=last_changed_at,
            now=now,
        )
        == ClosedReason.CONSULTING_TIMEOUT_30D
    )


def test_check_consulting_timeout_accepts_string_procurement_type() -> None:
    now = datetime(2026, 4, 2, tzinfo=UTC)
    last_changed_at = now - timedelta(days=31)

    assert (
        check_consulting_timeout(
            procurement_type="consulting",
            last_changed_at=last_changed_at,
            now=now,
        )
        == ClosedReason.CONSULTING_TIMEOUT_30D
    )


def test_check_stale_closure_for_non_tor_project() -> None:
    now = datetime(2026, 4, 2, tzinfo=UTC)
    last_changed_at = now - timedelta(days=46)

    assert (
        check_stale_closure(
            procurement_type=ProcurementType.SERVICES,
            project_state=ProjectState.OPEN_INVITATION,
            last_changed_at=last_changed_at,
            now=now,
        )
        == ClosedReason.STALE_NO_TOR
    )


def test_transition_state_accepts_string_inputs_and_matching_reason() -> None:
    updated = transition_state(
        current_state="open_consulting",
        next_state="closed_timeout_consulting",
        closed_reason="consulting_timeout_30d",
    )

    assert updated["project_state"] is ProjectState.CLOSED_TIMEOUT_CONSULTING
    assert updated["closed_reason"] is ClosedReason.CONSULTING_TIMEOUT_30D


def test_check_winner_closure_detects_winner_and_contract_statuses() -> None:
    assert (
        check_winner_closure("ประกาศผู้ชนะการเสนอราคา") == ClosedReason.WINNER_ANNOUNCED
    )
    assert check_winner_closure("อยู่ระหว่างลงนามสัญญา") == ClosedReason.CONTRACT_SIGNED


def test_hash_file_returns_sha256_hex() -> None:
    digest = hash_file(b"phase-1-document")

    assert digest == "7871172059838d36d280a9ce748e1b5f68f8a89811fd8fbfe8708baf7819b147"


def test_classify_document_detects_public_hearing_tor() -> None:
    document_type, document_phase = classify_document(
        label="ร่างขอบเขตของงาน (TOR) สำหรับประชาพิจารณ์",
        source_status_text="เปิดรับฟังคำวิจารณ์",
    )

    assert document_type is DocumentType.TOR
    assert document_phase is DocumentPhase.PUBLIC_HEARING


def test_classify_document_detects_final_tor() -> None:
    document_type, document_phase = classify_document(
        label="เอกสารประกวดราคาโครงการระบบข้อมูลกลาง",
        source_status_text="ประกาศเชิญชวน",
    )

    assert document_type is DocumentType.TOR
    assert document_phase is DocumentPhase.FINAL


def test_classify_document_treats_draft_tor_labels_as_public_hearing() -> None:
    document_type, document_phase = classify_document(
        label="ร่างเอกสารประกวดราคาโครงการระบบข้อมูลกลาง",
        source_status_text="",
    )

    assert document_type is DocumentType.TOR
    assert document_phase is DocumentPhase.PUBLIC_HEARING


def test_classify_document_uses_project_state_as_phase_context() -> None:
    document_type, document_phase = classify_document(
        label="เอกสารประกวดราคาโครงการระบบข้อมูลกลาง",
        source_status_text="",
        project_state=ProjectState.OPEN_PUBLIC_HEARING,
    )

    assert document_type is DocumentType.TOR
    assert document_phase is DocumentPhase.PUBLIC_HEARING


def test_transition_state_requires_closed_reason_for_winner_announced() -> None:
    try:
        transition_state(
            current_state=ProjectState.OPEN_INVITATION,
            next_state=ProjectState.WINNER_ANNOUNCED,
        )
    except ValueError as exc:
        assert "closed_reason" in str(exc)
    else:
        raise AssertionError("expected missing closed_reason to raise ValueError")


def test_transition_state_requires_closed_reason_for_contract_signed() -> None:
    try:
        transition_state(
            current_state=ProjectState.OPEN_INVITATION,
            next_state=ProjectState.CONTRACT_SIGNED,
        )
    except ValueError as exc:
        assert "closed_reason" in str(exc)
    else:
        raise AssertionError("expected missing closed_reason to raise ValueError")


def test_transition_state_accepts_winner_announced_with_correct_reason() -> None:
    updated = transition_state(
        current_state=ProjectState.OPEN_INVITATION,
        next_state=ProjectState.WINNER_ANNOUNCED,
        closed_reason=ClosedReason.WINNER_ANNOUNCED,
    )

    assert updated["project_state"] is ProjectState.WINNER_ANNOUNCED
    assert updated["closed_reason"] is ClosedReason.WINNER_ANNOUNCED


def test_transition_state_accepts_contract_signed_with_correct_reason() -> None:
    updated = transition_state(
        current_state=ProjectState.OPEN_INVITATION,
        next_state=ProjectState.CONTRACT_SIGNED,
        closed_reason=ClosedReason.CONTRACT_SIGNED,
    )

    assert updated["project_state"] is ProjectState.CONTRACT_SIGNED
    assert updated["closed_reason"] is ClosedReason.CONTRACT_SIGNED


def test_transition_state_rejects_wrong_reason_for_winner_announced() -> None:
    try:
        transition_state(
            current_state=ProjectState.OPEN_INVITATION,
            next_state=ProjectState.WINNER_ANNOUNCED,
            closed_reason=ClosedReason.MANUAL,
        )
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("expected mismatched closed_reason to raise ValueError")


def test_classify_document_handles_non_tor_labels() -> None:
    document_type, document_phase = classify_document(
        label="ประกาศราคากลาง",
        source_status_text="ประกาศราคากลาง",
    )

    assert document_type is DocumentType.MID_PRICE
    assert document_phase is DocumentPhase.UNKNOWN


def test_derive_artifact_bucket_detects_pricing_only() -> None:
    bucket = derive_artifact_bucket(labels=["ประกาศราคากลาง"])

    assert bucket is ArtifactBucket.PRICING_ONLY


def test_derive_artifact_bucket_detects_invitation_plus_pricing() -> None:
    bucket = derive_artifact_bucket(labels=["ประกาศราคากลาง", "ประกาศเชิญชวน"])

    assert bucket is ArtifactBucket.INVITATION_PLUS_PRICING


def test_derive_artifact_bucket_detects_draft_plus_pricing() -> None:
    bucket = derive_artifact_bucket(
        labels=["ประกาศราคากลาง", "ร่างเอกสารประกวดราคาโครงการระบบข้อมูลกลาง"]
    )

    assert bucket is ArtifactBucket.DRAFT_PLUS_PRICING


def test_derive_artifact_bucket_detects_final_tor_from_document_rows() -> None:
    bucket = derive_artifact_bucket(
        documents=[
            {
                "document_type": DocumentType.MID_PRICE.value,
                "document_phase": DocumentPhase.UNKNOWN.value,
            },
            {
                "document_type": DocumentType.TOR.value,
                "document_phase": DocumentPhase.FINAL.value,
            },
        ]
    )

    assert bucket is ArtifactBucket.FINAL_TOR_DOWNLOADED
