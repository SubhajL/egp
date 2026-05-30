"""Integration tests for the LINE manual-PromptPay slip repository.

Uses the shared SQLAlchemy metadata bootstrapped onto a throwaway SQLite
database (the same pattern the billing API tests use), so the new tables are
created via ``METADATA.create_all`` alongside the billing tables.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from egp_db.connection import create_shared_engine
from egp_db.repositories.billing_repo import create_billing_repository
from egp_db.repositories.line_payment_repo import LinePaymentRepository

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture()
def engine(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'line-slips.sqlite3'}"
    eng = create_shared_engine(url)
    # Bootstrapping any repo on the shared metadata creates ALL registered
    # tables, including payment_slips / line_payment_contexts / subscribers.
    create_billing_repository(engine=eng, bootstrap_schema=True)
    return eng


@pytest.fixture()
def repo(engine):
    return LinePaymentRepository(engine=engine)


@pytest.fixture()
def billing(engine):
    return create_billing_repository(engine=engine, bootstrap_schema=False)


def _make_record(billing, *, tenant_id: str, record_number: str) -> str:
    start = date(2026, 5, 1)
    detail = billing.create_billing_record(
        tenant_id=tenant_id,
        record_number=record_number,
        plan_code="monthly_membership",
        status="awaiting_payment",
        billing_period_start=start.isoformat(),
        billing_period_end=(start + timedelta(days=30)).isoformat(),
        amount_due="1500.00",
        currency="THB",
    )
    return detail.record.id


def test_create_slip_is_idempotent_by_message_id(repo) -> None:
    first, created_first = repo.create_slip(
        line_user_id="Uabc", line_message_id="msg-1", received_at="2026-05-29T10:00:00+00:00"
    )
    second, created_second = repo.create_slip(
        line_user_id="Uabc", line_message_id="msg-1", received_at="2026-05-29T10:05:00+00:00"
    )
    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert first.verification_status == "pending"


def test_record_and_fetch_latest_context_for_user(repo) -> None:
    repo.record_context(
        line_user_id="Uabc",
        reference_code="INV-2026-0001",
        source_message_id="ctx-1",
        created_at="2026-05-29T09:00:00+00:00",
    )
    repo.record_context(
        line_user_id="Uabc",
        reference_code="INV-2026-0002",
        source_message_id="ctx-2",
        created_at="2026-05-29T09:30:00+00:00",
    )
    latest = repo.latest_context_for_user("Uabc")
    assert latest is not None
    assert latest.reference_code == "INV-2026-0002"


def test_latest_context_ignores_expired(repo) -> None:
    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    repo.record_context(
        line_user_id="Uexp",
        reference_code="INV-2026-0009",
        source_message_id="ctx-exp",
        created_at="2026-05-29T08:00:00+00:00",
        expires_at=past,
    )
    assert repo.latest_context_for_user("Uexp") is None


def test_match_slip_sets_tenant_and_record(repo, billing) -> None:
    record_id = _make_record(billing, tenant_id=TENANT_A, record_number="INV-2026-0100")
    slip, _ = repo.create_slip(
        line_user_id="Uabc", line_message_id="msg-2", received_at="2026-05-29T10:00:00+00:00"
    )
    matched = repo.match_slip(
        slip_id=slip.id,
        tenant_id=TENANT_A,
        billing_record_id=record_id,
        reference_code_match="INV-2026-0100",
    )
    assert matched.tenant_id == TENANT_A
    assert matched.billing_record_id == record_id
    assert matched.verification_status == "matched"


def test_attach_image_stores_object_key_and_hash(repo) -> None:
    slip, _ = repo.create_slip(
        line_user_id="Uabc", line_message_id="msg-3", received_at="2026-05-29T10:00:00+00:00"
    )
    updated = repo.attach_image(
        slip_id=slip.id,
        image_object_key="line-slips/msg-3.jpg",
        image_content_type="image/jpeg",
        image_sha256="a" * 64,
    )
    assert updated.image_object_key == "line-slips/msg-3.jpg"
    assert updated.image_sha256 == "a" * 64


def test_mark_verified_and_rejected_transitions(repo) -> None:
    slip, _ = repo.create_slip(
        line_user_id="Uabc", line_message_id="msg-4", received_at="2026-05-29T10:00:00+00:00"
    )
    verified = repo.mark_verified(
        slip_id=slip.id, verified_by_user_id=TENANT_B, notes="looks good"
    )
    assert verified.verification_status == "verified"
    assert verified.verified_at is not None

    other, _ = repo.create_slip(
        line_user_id="Uabc", line_message_id="msg-5", received_at="2026-05-29T10:00:00+00:00"
    )
    rejected = repo.mark_rejected(slip_id=other.id, verified_by_user_id=TENANT_B, notes="blurry")
    assert rejected.verification_status == "rejected"


def test_list_slips_filters_by_status(repo) -> None:
    a, _ = repo.create_slip(line_user_id="U1", line_message_id="m-a", received_at="2026-05-29T10:00:00+00:00")
    b, _ = repo.create_slip(line_user_id="U2", line_message_id="m-b", received_at="2026-05-29T11:00:00+00:00")
    repo.mark_verified(slip_id=b.id, verified_by_user_id=TENANT_B, notes=None)
    pending = repo.list_slips(status="pending")
    assert [s.id for s in pending] == [a.id]
    all_slips = repo.list_slips()
    assert {s.id for s in all_slips} == {a.id, b.id}


def test_find_billing_records_by_number_unique_vs_ambiguous(billing) -> None:
    # Unique across one tenant -> exactly one match (safe to auto-match).
    _make_record(billing, tenant_id=TENANT_A, record_number="INV-2026-0500")
    unique = billing.find_billing_records_by_number(record_number="INV-2026-0500")
    assert len(unique) == 1
    assert unique[0][0] == TENANT_A
    assert unique[0][2] == "awaiting_payment"

    # Same number issued under two tenants -> ambiguous (leave for manual select).
    _make_record(billing, tenant_id=TENANT_A, record_number="INV-2026-0600")
    _make_record(billing, tenant_id=TENANT_B, record_number="INV-2026-0600")
    ambiguous = billing.find_billing_records_by_number(record_number="INV-2026-0600")
    assert len(ambiguous) == 2
    assert {row[0] for row in ambiguous} == {TENANT_A, TENANT_B}

    assert billing.find_billing_records_by_number(record_number="INV-NONE") == []


def test_find_billing_records_by_number_is_status_agnostic(billing) -> None:
    # The lookup itself returns ALL rows regardless of status (with the status),
    # so the caller can enforce the cross-tenant uniqueness guard BEFORE applying
    # payability. (A paid duplicate elsewhere must not collapse an ambiguous
    # number into a false unique match.)
    record_id = _make_record(billing, tenant_id=TENANT_A, record_number="INV-2026-0700")
    payment = billing.record_payment(
        tenant_id=TENANT_A,
        billing_record_id=record_id,
        payment_method="promptpay_qr",
        amount="1500.00",
        currency="THB",
        received_at="2026-05-29T10:00:00+00:00",
    )
    billing.reconcile_payment(
        tenant_id=TENANT_A, payment_id=payment.id, status="reconciled"
    )
    rows = billing.find_billing_records_by_number(record_number="INV-2026-0700")
    assert len(rows) == 1
    assert rows[0][0] == TENANT_A
    assert rows[0][2] == "paid"


def test_admin_subscribers_add_and_list(repo) -> None:
    repo.add_admin_subscriber(line_user_id="Uadmin", tenant_id=None, display_name="Owner")
    repo.add_admin_subscriber(line_user_id="Uadmin", tenant_id=None, display_name="Owner-dup")
    subs = repo.list_admin_subscribers()
    assert [s.line_user_id for s in subs] == ["Uadmin"]
