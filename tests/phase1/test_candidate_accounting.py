"""Tests for durable accepted-candidate accounting (PR-CANARY-03)."""

from __future__ import annotations

import pytest

from egp_crawler_core.candidate_key import compute_candidate_key
from egp_db.repositories.candidate_attempt_repo import (
    CandidateTerminalConflictError,
    SqlCandidateAttemptRepository,
)
from egp_shared_types.enums import CandidateTerminalReason


TENANT_ID = "11111111-1111-1111-1111-111111111111"
RUN_ID = "22222222-2222-2222-2222-222222222222"
PROJECT_ID = "33333333-3333-3333-3333-333333333333"


def _create_repo(tmp_path) -> SqlCandidateAttemptRepository:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'candidate-accounting.sqlite3'}"
    return SqlCandidateAttemptRepository(
        database_url=database_url,
        bootstrap_schema=True,
    )


# -- Repository tests -------------------------------------------------------


def test_record_accepted_creates_candidate(tmp_path):
    repo = _create_repo(tmp_path)
    record = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
    )
    assert record.tenant_id == TENANT_ID
    assert record.run_id == RUN_ID
    assert record.candidate_key == "abc123"
    assert record.keyword == "analytics"
    assert record.page_number == 1
    assert record.row_ordinal == 3
    assert record.candidate_status == "accepted"
    assert record.terminal_reason is None
    assert record.project_id is None


def test_finalize_persisted_updates_accepted_candidate(tmp_path):
    repo = _create_repo(tmp_path)
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
    )
    result = repo.finalize_persisted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        project_id=PROJECT_ID,
    )
    assert result is not None
    assert result.candidate_status == "persisted"
    assert result.project_id == PROJECT_ID


def test_finalize_conflicting_terminal_state_raises_and_preserves_original(tmp_path):
    """F6/R6: a contradictory rewrite raises the typed conflict (was: None)."""
    repo = _create_repo(tmp_path)
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
    )
    # First finalization succeeds
    result = repo.finalize_persisted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        project_id=PROJECT_ID,
    )
    assert result is not None
    assert result.candidate_status == "persisted"

    # Second finalization with a different terminal state raises distinctly
    with pytest.raises(CandidateTerminalConflictError):
        repo.finalize_failed(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            candidate_key="abc123",
            terminal_reason=CandidateTerminalReason.PERSIST_ERROR.value,
        )

    # Verify original terminal state is preserved
    summary = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=RUN_ID)
    assert summary.persisted == 1
    assert summary.failed == 0


def test_record_accepted_is_idempotent(tmp_path):
    repo = _create_repo(tmp_path)
    first = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
    )
    # Same (tenant_id, run_id, candidate_key) -- should not raise
    second = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="abc123",
        keyword="analytics",
        page_number=1,
        row_ordinal=3,
    )
    assert first.id == second.id
    assert first.candidate_status == second.candidate_status

    # Summary shows exactly one row, not two
    summary = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=RUN_ID)
    assert summary.total == 1
    assert summary.accepted == 1


def test_reconcile_open_candidates_marks_accepted_as_unknown(tmp_path):
    repo = _create_repo(tmp_path)
    # Two accepted candidates
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="key1",
        keyword="analytics",
    )
    repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="key2",
        keyword="analytics",
    )
    # Finalize one as persisted
    repo.finalize_persisted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="key1",
        project_id=PROJECT_ID,
    )

    # Reconcile: only key2 (still accepted) should become unknown
    count = repo.reconcile_open_candidates(run_id=RUN_ID, terminal_reason="worker_lost")
    assert count == 1

    summary = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=RUN_ID)
    assert summary.persisted == 1
    assert summary.unknown == 1
    assert summary.accepted == 0
    assert summary.total == 2


# -- F6 replay / conflict semantics (T7-T9) ---------------------------------


def test_finalize_identical_replay_returns_existing_record(tmp_path):
    """T7/R6: an identical terminal replay returns the record, not None."""
    repo = _create_repo(tmp_path)
    repo.record_accepted(
        tenant_id=TENANT_ID, run_id=RUN_ID, candidate_key="k-t7", keyword="kw"
    )
    first = repo.finalize_failed(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="k-t7",
        terminal_reason=CandidateTerminalReason.PERSIST_ERROR.value,
        terminal_detail="x",
    )
    assert first is not None
    replay = repo.finalize_failed(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="k-t7",
        terminal_reason=CandidateTerminalReason.PERSIST_ERROR.value,
        terminal_detail="different",
    )
    assert replay is not None, "identical replay must return the record"
    assert replay.candidate_status == "failed"
    assert replay.terminal_detail == "x", "first detail wins (non-authoritative)"


@pytest.mark.parametrize(
    ("first_call", "second_call", "expect_conflict"),
    [
        # (a) status differs: persisted then failed
        (
            {"kind": "persisted", "project_id": PROJECT_ID},
            {"kind": "failed", "terminal_reason": "persist_error"},
            True,
        ),
        # (b) reason-only differs: failed(persist_error) then failed(worker_lost)
        (
            {"kind": "failed", "terminal_reason": "persist_error"},
            {"kind": "failed", "terminal_reason": "worker_lost"},
            True,
        ),
        # (c) project-only differs: persisted(P1) then persisted(P2)
        (
            {"kind": "persisted", "project_id": PROJECT_ID},
            {"kind": "persisted", "project_id": "44444444-4444-4444-4444-444444444444"},
            True,
        ),
        # (d) same project in a different textual form: NOT a conflict
        (
            {"kind": "persisted", "project_id": PROJECT_ID},
            {"kind": "persisted", "project_id": PROJECT_ID.upper()},
            False,
        ),
    ],
)
def test_finalize_contradiction_raises_typed_conflict(
    tmp_path, first_call, second_call, expect_conflict
):
    """T8/R6: any single-field divergence raises; normalized equality does not."""
    repo = _create_repo(tmp_path)
    repo.record_accepted(
        tenant_id=TENANT_ID, run_id=RUN_ID, candidate_key="k-t8", keyword="kw"
    )

    def _finalize(call):
        if call["kind"] == "persisted":
            return repo.finalize_persisted(
                tenant_id=TENANT_ID,
                run_id=RUN_ID,
                candidate_key="k-t8",
                project_id=call["project_id"],
            )
        return repo.finalize_failed(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            candidate_key="k-t8",
            terminal_reason=call["terminal_reason"],
        )

    assert _finalize(first_call) is not None
    if expect_conflict:
        with pytest.raises(CandidateTerminalConflictError) as excinfo:
            _finalize(second_call)
        conflict = excinfo.value
        assert conflict.candidate_key == "k-t8"
        assert conflict.existing_status == first_call["kind"]
        assert conflict.requested_status == second_call["kind"]
    else:
        replay = _finalize(second_call)
        assert replay is not None
        assert replay.candidate_status == first_call["kind"]


def test_finalize_missing_row_returns_none(tmp_path):
    """T9/R6: finalizing a never-accepted key stays None (no raise)."""
    repo = _create_repo(tmp_path)
    result = repo.finalize_failed(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="never-accepted",
        terminal_reason=CandidateTerminalReason.PERSIST_ERROR.value,
    )
    assert result is None


# -- F6 provenance + typed vocabulary (T10-T11) -----------------------------


def test_record_accepted_stores_provenance_columns(tmp_path):
    """T10/R8: project_number and row_marker round-trip; omitted stores NULL."""
    repo = _create_repo(tmp_path)
    stored = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="k-t10",
        keyword="kw",
        project_number="EGP-66-123",
        row_marker='{"a":1}',
    )
    assert stored.project_number == "EGP-66-123"
    assert stored.row_marker == '{"a":1}'
    bare = repo.record_accepted(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="k-t10-bare",
        keyword="kw",
    )
    assert bare.project_number is None
    assert bare.row_marker is None


def test_finalize_failed_stores_typed_reason_and_detail_and_rejects_nonvocab(tmp_path):
    """T11/R3c+R5: typed reason + detail stored; non-vocab reason rejected pre-SQL."""
    repo = _create_repo(tmp_path)
    repo.record_accepted(
        tenant_id=TENANT_ID, run_id=RUN_ID, candidate_key="k-t11", keyword="kw"
    )
    result = repo.finalize_failed(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        candidate_key="k-t11",
        terminal_reason=CandidateTerminalReason.PERSIST_ERROR.value,
        terminal_detail="Traceback: boom",
    )
    assert result is not None
    assert result.terminal_reason == "persist_error"
    assert result.terminal_detail == "Traceback: boom"

    repo.record_accepted(
        tenant_id=TENANT_ID, run_id=RUN_ID, candidate_key="k-t11-b", keyword="kw"
    )
    with pytest.raises(ValueError):
        repo.finalize_failed(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            candidate_key="k-t11-b",
            terminal_reason="Boom: raw traceback text",
        )
    summary = repo.get_run_candidate_summary(tenant_id=TENANT_ID, run_id=RUN_ID)
    assert summary.accepted == 1, "rejected reason must not mutate the row"


def test_sqlite_mirror_enforces_vocab_and_shape_checks(tmp_path):
    """The SQLAlchemy mirror carries the 039 CHECKs and SQLite ENFORCES them,
    so even raw SQL that bypasses the Python validator cannot store free-text
    reasons or invalid status shapes in the unit-test tier."""
    from sqlalchemy import text

    repo = _create_repo(tmp_path)
    with pytest.raises(Exception, match="(?i)constraint"):
        with repo._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO discovery_candidate_attempts"
                    " (id, tenant_id, run_id, candidate_key, keyword,"
                    "  candidate_status, terminal_reason, created_at, updated_at)"
                    " VALUES ('x', 't', 'r', 'k', 'kw', 'failed', 'FREE TEXT',"
                    "  '2026-01-01', '2026-01-01')"
                )
            )
    with pytest.raises(Exception, match="(?i)constraint"):
        with repo._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO discovery_candidate_attempts"
                    " (id, tenant_id, run_id, candidate_key, keyword,"
                    "  candidate_status, terminal_reason, created_at, updated_at)"
                    " VALUES ('y', 't', 'r', 'k2', 'kw', 'accepted', 'worker_lost',"
                    "  '2026-01-01', '2026-01-01')"
                )
            )


# -- Candidate key tests ----------------------------------------------------


def _expected_content_key(
    keyword: str,
    project_name: str,
    project_number: str | None = None,
    organization_name: str = "",
    budget_text: str = "",
    source_status_text: str = "",
) -> str:
    """Golden-vector oracle: the R7 spec formula (v2) recomputed via hashlib.

    Deliberately independent of ``compute_candidate_key``'s implementation
    path — a constant-hash or wrong-formula implementation fails these tests.
    v2: JSON-encoded fields (delimiter-injection-proof) and a visible row
    signature (name/org/budget/status) as the no-number fallback identity.
    """
    import hashlib
    import json

    normalized_keyword = keyword.strip().casefold()
    if project_number:
        parts = ["num", project_number.casefold()]
    else:
        parts = [
            "name",
            project_name.casefold(),
            organization_name.casefold(),
            budget_text.casefold(),
            source_status_text.casefold(),
        ]
    payload = json.dumps(
        ["egp-candidate-key.v2", normalized_keyword, *parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_candidate_key_golden_vectors():
    """T12/R7: exact digests from the spec formula; no positional parameters."""
    import inspect

    key = compute_candidate_key(
        keyword="analytics",
        project_name="Test Project",
        project_number="EGP-66-123",
    )
    assert key == _expected_content_key(
        "analytics", "Test Project", project_number="EGP-66-123"
    )
    assert len(key) == 64

    name_key = compute_candidate_key(
        keyword="analytics",
        project_name="Test Project",
        organization_name="Dept of Works",
    )
    assert name_key == _expected_content_key(
        "analytics", "Test Project", organization_name="Dept of Works"
    )

    params = set(inspect.signature(compute_candidate_key).parameters)
    assert params == {
        "keyword",
        "project_name",
        "project_number",
        "organization_name",
        "budget_text",
        "source_status_text",
    }, "position (page/ordinal) must not be part of candidate identity"


def test_candidate_key_normalization_and_identity_partition():
    """T13/R7: keyword strip+casefold; identity finer than (never coarser
    than) the run dedupe key str(project_number or project_name).casefold()."""
    # (a) keyword normalization: authorization-style strip + casefold.
    assert compute_candidate_key(
        keyword=" TOR ", project_name="P"
    ) == compute_candidate_key(keyword="tor", project_name="P")

    # (b) same display name, different organization, no number: DISTINCT.
    key_org_a = compute_candidate_key(
        keyword="k", project_name="Same Name", organization_name="Org A"
    )
    key_org_b = compute_candidate_key(
        keyword="k", project_name="Same Name", organization_name="Org B"
    )
    assert key_org_a != key_org_b

    # (c) project_number dominates: same number, different name/org → SAME.
    assert compute_candidate_key(
        keyword="k",
        project_name="Name 1",
        project_number="EGP-9",
        organization_name="Org A",
    ) == compute_candidate_key(
        keyword="k",
        project_name="Name 2",
        project_number="EGP-9",
        organization_name="Org B",
    )

    # (d) name identity is casefold-ONLY — no whitespace collapsing — so the
    # key partition never merges rows the dedupe key keeps apart.
    assert compute_candidate_key(
        keyword="k", project_name="Two  Spaces"
    ) != compute_candidate_key(keyword="k", project_name="Two Spaces")

    # (e) domain separation: a name that LOOKS like a number identity can
    # never collide with a real project-number identity.
    assert compute_candidate_key(
        keyword="k", project_name="num:EGP-9"
    ) != compute_candidate_key(
        keyword="k", project_name="whatever", project_number="EGP-9"
    )

    # (f) empty-string number falls back to name identity (mirrors the
    # truthiness of the dedupe key's `project_number or project_name`).
    assert compute_candidate_key(
        keyword="k", project_name="P", project_number=""
    ) == compute_candidate_key(keyword="k", project_name="P")

    # (g) delimiter injection (QCHECK Tier-2 attack): scraped text containing
    # the old separator tokens must NOT collide two dedupe-distinct rows.
    assert compute_candidate_key(
        keyword="k", project_name="x|org:y", organization_name=""
    ) != compute_candidate_key(
        keyword="k", project_name="x", organization_name="y|org:"
    )
    assert compute_candidate_key(
        keyword="k", project_name='x","y', organization_name="z"
    ) != compute_candidate_key(keyword="k", project_name="x", organization_name='y","z')

    # (h) visible-signature identity: same name AND org but a different
    # budget or status column still yields DISTINCT keys (two physically
    # distinct rows must not share a ledger row when ANY visible column
    # separates them — Tier-1 finding on detail-only project numbers).
    assert compute_candidate_key(
        keyword="k",
        project_name="Same",
        organization_name="Org",
        budget_text="1,000,000",
    ) != compute_candidate_key(
        keyword="k",
        project_name="Same",
        organization_name="Org",
        budget_text="2,000,000",
    )
    assert compute_candidate_key(
        keyword="k",
        project_name="Same",
        organization_name="Org",
        source_status_text="ประกาศเชิญชวน",
    ) != compute_candidate_key(
        keyword="k",
        project_name="Same",
        organization_name="Org",
        source_status_text="ร่างประกาศ",
    )
