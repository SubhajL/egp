"""Repository for LINE-mediated manual PromptPay slip verification.

Backs the ฿0-fee bootstrap flow: customers pay a personal PromptPay QR and
forward the slip image via LINE OA; an admin verifies it to activate the
subscription. See ``line_payment_schema`` for the table definitions.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import desc, insert, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from egp_db.connection import create_shared_engine
from egp_db.db_utils import normalize_database_url, normalize_uuid_string

from .billing_utils import _now
from .line_payment_models import (
    LineAdminSubscriberRecord,
    LinePaymentContextRecord,
    PaymentSlipRecord,
)
from .line_payment_schema import (
    LINE_ADMIN_SUBSCRIBERS_TABLE,
    LINE_PAYMENT_CONTEXTS_TABLE,
    METADATA,
    PAYMENT_SLIPS_TABLE,
)


def _iso(value: datetime | date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).strip())


def _opt_uuid(value: str | None) -> str | None:
    return normalize_uuid_string(value) if value is not None else None


def _slip_from_mapping(row) -> PaymentSlipRecord:
    return PaymentSlipRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]) if row["tenant_id"] is not None else None,
        billing_record_id=(
            str(row["billing_record_id"]) if row["billing_record_id"] is not None else None
        ),
        payment_request_id=(
            str(row["payment_request_id"]) if row["payment_request_id"] is not None else None
        ),
        line_user_id=str(row["line_user_id"]),
        line_message_id=str(row["line_message_id"]),
        reference_code_match=row["reference_code_match"],
        image_object_key=row["image_object_key"],
        image_content_type=row["image_content_type"],
        image_sha256=row["image_sha256"],
        verification_status=str(row["verification_status"]),
        verified_by_user_id=(
            str(row["verified_by_user_id"]) if row["verified_by_user_id"] is not None else None
        ),
        verified_at=_iso(row["verified_at"]),
        verification_notes=row["verification_notes"],
        received_at=_iso(row["received_at"]),
        created_at=_iso(row["created_at"]),
        updated_at=_iso(row["updated_at"]),
    )


def _context_from_mapping(row) -> LinePaymentContextRecord:
    return LinePaymentContextRecord(
        id=str(row["id"]),
        line_user_id=str(row["line_user_id"]),
        reference_code=str(row["reference_code"]),
        tenant_id=str(row["tenant_id"]) if row["tenant_id"] is not None else None,
        billing_record_id=(
            str(row["billing_record_id"]) if row["billing_record_id"] is not None else None
        ),
        plan_code=row["plan_code"],
        source_message_id=str(row["source_message_id"]),
        expires_at=_iso(row["expires_at"]),
        created_at=_iso(row["created_at"]),
    )


def _subscriber_from_mapping(row) -> LineAdminSubscriberRecord:
    return LineAdminSubscriberRecord(
        id=str(row["id"]),
        line_user_id=str(row["line_user_id"]),
        tenant_id=str(row["tenant_id"]) if row["tenant_id"] is not None else None,
        display_name=row["display_name"],
        created_at=_iso(row["created_at"]),
    )


class LinePaymentRepository:
    """Persistence for LINE slips, parsed reference contexts, and admin subscribers."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
        bootstrap_schema: bool = False,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self._database_url = (
            normalize_database_url(database_url) if database_url is not None else None
        )
        self._engine = engine or create_shared_engine(self._database_url or "")
        if bootstrap_schema:
            METADATA.create_all(self._engine)

    # ------------------------------------------------------------------ slips
    def _get_slip(self, slip_id: str) -> PaymentSlipRecord | None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(PAYMENT_SLIPS_TABLE)
                    .where(PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id))
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _slip_from_mapping(row) if row is not None else None

    def _get_slip_by_message_id(self, line_message_id: str) -> PaymentSlipRecord | None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(PAYMENT_SLIPS_TABLE)
                    .where(PAYMENT_SLIPS_TABLE.c.line_message_id == str(line_message_id).strip())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _slip_from_mapping(row) if row is not None else None

    def get_slip(self, slip_id: str) -> PaymentSlipRecord | None:
        return self._get_slip(slip_id)

    def create_slip(
        self,
        *,
        line_user_id: str,
        line_message_id: str,
        received_at: str,
    ) -> tuple[PaymentSlipRecord, bool]:
        """Insert a slip row idempotently keyed on ``line_message_id``.

        Returns ``(record, created)`` where ``created`` is False when a slip
        for the same LINE message id already exists (webhook redelivery).
        """
        existing = self._get_slip_by_message_id(line_message_id)
        if existing is not None:
            return existing, False
        slip_id = str(uuid4())
        now = _now()
        received = _parse_dt(received_at) or now
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(PAYMENT_SLIPS_TABLE).values(
                        id=slip_id,
                        tenant_id=None,
                        billing_record_id=None,
                        payment_request_id=None,
                        line_user_id=str(line_user_id).strip(),
                        line_message_id=str(line_message_id).strip(),
                        reference_code_match=None,
                        image_object_key=None,
                        image_content_type=None,
                        image_sha256=None,
                        verification_status="pending",
                        verified_by_user_id=None,
                        verified_at=None,
                        verification_notes=None,
                        received_at=received,
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            # Concurrent redelivery raced us to the unique line_message_id.
            existing = self._get_slip_by_message_id(line_message_id)
            if existing is not None:
                return existing, False
            raise
        created = self._get_slip(slip_id)
        assert created is not None
        return created, True

    def attach_image(
        self,
        *,
        slip_id: str,
        image_object_key: str,
        image_content_type: str | None,
        image_sha256: str | None,
    ) -> PaymentSlipRecord:
        with self._engine.begin() as connection:
            connection.execute(
                update(PAYMENT_SLIPS_TABLE)
                .where(PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id))
                .values(
                    image_object_key=image_object_key,
                    image_content_type=image_content_type,
                    image_sha256=image_sha256,
                    updated_at=_now(),
                )
            )
        updated = self._get_slip(slip_id)
        if updated is None:
            raise KeyError(slip_id)
        return updated

    def match_slip(
        self,
        *,
        slip_id: str,
        tenant_id: str,
        billing_record_id: str,
        reference_code_match: str,
        payment_request_id: str | None = None,
    ) -> PaymentSlipRecord:
        with self._engine.begin() as connection:
            connection.execute(
                update(PAYMENT_SLIPS_TABLE)
                .where(PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id))
                .values(
                    tenant_id=normalize_uuid_string(tenant_id),
                    billing_record_id=normalize_uuid_string(billing_record_id),
                    payment_request_id=_opt_uuid(payment_request_id),
                    reference_code_match=str(reference_code_match).strip(),
                    verification_status="matched",
                    updated_at=_now(),
                )
            )
        updated = self._get_slip(slip_id)
        if updated is None:
            raise KeyError(slip_id)
        return updated

    def _mark(
        self, *, slip_id: str, status: str, verified_by_user_id: str | None, notes: str | None
    ) -> PaymentSlipRecord:
        with self._engine.begin() as connection:
            connection.execute(
                update(PAYMENT_SLIPS_TABLE)
                .where(PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id))
                .values(
                    verification_status=status,
                    verified_by_user_id=_opt_uuid(verified_by_user_id),
                    verified_at=_now(),
                    verification_notes=notes,
                    updated_at=_now(),
                )
            )
        updated = self._get_slip(slip_id)
        if updated is None:
            raise KeyError(slip_id)
        return updated

    def claim_slip_for_verification(self, *, slip_id: str) -> bool:
        """Atomically transition matched -> verifying; return True iff we won.

        The conditional ``WHERE verification_status = 'matched'`` serializes
        concurrent verify attempts: only one caller transitions the row, so only
        that caller settles the billing record. ``verified_at`` is set as a lease
        timestamp so a crash mid-settlement (slip left 'verifying') can be
        recovered once the lease goes stale. A loser gets False. Settlement is
        NOT marked 'verified' here — only after it succeeds (finalize).
        """
        with self._engine.begin() as connection:
            result = connection.execute(
                update(PAYMENT_SLIPS_TABLE)
                .where(
                    PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id),
                    PAYMENT_SLIPS_TABLE.c.verification_status == "matched",
                )
                .values(verification_status="verifying", verified_at=_now(), updated_at=_now())
            )
        return result.rowcount == 1

    def finalize_verification(
        self, *, slip_id: str, verified_by_user_id: str | None, notes: str | None
    ) -> PaymentSlipRecord:
        """Mark a claimed (verifying) slip as verified after settlement succeeds."""
        with self._engine.begin() as connection:
            connection.execute(
                update(PAYMENT_SLIPS_TABLE)
                .where(PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id))
                .values(
                    verification_status="verified",
                    verified_by_user_id=_opt_uuid(verified_by_user_id),
                    verified_at=_now(),
                    verification_notes=notes,
                    updated_at=_now(),
                )
            )
        updated = self._get_slip(slip_id)
        if updated is None:
            raise KeyError(slip_id)
        return updated

    def revert_stale_verifying_to_matched(self, *, slip_id: str, stale_before: datetime) -> bool:
        """Atomically reclaim a STALE 'verifying' slip back to 'matched'.

        Returns True iff this caller won the reclaim (conditional on the lease
        ``verified_at`` being older than ``stale_before``). This serializes
        concurrent recoveries of an abandoned claim: only one proceeds to
        re-settle. A fresh/already-reclaimed slip yields False.
        """
        with self._engine.begin() as connection:
            result = connection.execute(
                update(PAYMENT_SLIPS_TABLE)
                .where(
                    PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id),
                    PAYMENT_SLIPS_TABLE.c.verification_status == "verifying",
                    PAYMENT_SLIPS_TABLE.c.verified_at < stale_before,
                )
                .values(verification_status="matched", verified_at=None, updated_at=_now())
            )
        return result.rowcount == 1

    def revert_claim_to_matched(self, *, slip_id: str) -> None:
        """Undo a verification claim (verifying -> matched) if settlement failed."""
        with self._engine.begin() as connection:
            connection.execute(
                update(PAYMENT_SLIPS_TABLE)
                .where(
                    PAYMENT_SLIPS_TABLE.c.id == normalize_uuid_string(slip_id),
                    PAYMENT_SLIPS_TABLE.c.verification_status == "verifying",
                )
                .values(verification_status="matched", verified_at=None, updated_at=_now())
            )

    def mark_verified(
        self, *, slip_id: str, verified_by_user_id: str | None, notes: str | None
    ) -> PaymentSlipRecord:
        return self._mark(
            slip_id=slip_id, status="verified", verified_by_user_id=verified_by_user_id, notes=notes
        )

    def mark_rejected(
        self, *, slip_id: str, verified_by_user_id: str | None, notes: str | None
    ) -> PaymentSlipRecord:
        return self._mark(
            slip_id=slip_id, status="rejected", verified_by_user_id=verified_by_user_id, notes=notes
        )

    def list_pending_slips_for_user(self, line_user_id: str) -> list[PaymentSlipRecord]:
        """Pending (unmatched) slips from a LINE user, oldest first.

        Used to rematch slips whose image arrived before the reference text.
        """
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(PAYMENT_SLIPS_TABLE)
                    .where(
                        PAYMENT_SLIPS_TABLE.c.line_user_id == str(line_user_id).strip(),
                        PAYMENT_SLIPS_TABLE.c.verification_status == "pending",
                    )
                    .order_by(PAYMENT_SLIPS_TABLE.c.received_at)
                )
                .mappings()
                .all()
            )
        return [_slip_from_mapping(row) for row in rows]

    def list_slips(
        self, *, status: str | None = None, tenant_id: str | None = None, limit: int = 100
    ) -> list[PaymentSlipRecord]:
        query = select(PAYMENT_SLIPS_TABLE)
        if status is not None:
            query = query.where(PAYMENT_SLIPS_TABLE.c.verification_status == status)
        if tenant_id is not None:
            query = query.where(
                PAYMENT_SLIPS_TABLE.c.tenant_id == normalize_uuid_string(tenant_id)
            )
        query = query.order_by(desc(PAYMENT_SLIPS_TABLE.c.received_at)).limit(max(1, int(limit)))
        with self._engine.begin() as connection:
            rows = connection.execute(query).mappings().all()
        return [_slip_from_mapping(row) for row in rows]

    # --------------------------------------------------------------- contexts
    def record_context(
        self,
        *,
        line_user_id: str,
        reference_code: str,
        source_message_id: str,
        tenant_id: str | None = None,
        billing_record_id: str | None = None,
        plan_code: str | None = None,
        expires_at: str | None = None,
        created_at: str | None = None,
    ) -> LinePaymentContextRecord:
        context_id = str(uuid4())
        created = _parse_dt(created_at) or _now()
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(LINE_PAYMENT_CONTEXTS_TABLE).values(
                        id=context_id,
                        line_user_id=str(line_user_id).strip(),
                        reference_code=str(reference_code).strip(),
                        tenant_id=_opt_uuid(tenant_id),
                        billing_record_id=_opt_uuid(billing_record_id),
                        plan_code=plan_code,
                        source_message_id=str(source_message_id).strip(),
                        expires_at=_parse_dt(expires_at),
                        created_at=created,
                    )
                )
        except IntegrityError:
            with self._engine.begin() as connection:
                row = (
                    connection.execute(
                        select(LINE_PAYMENT_CONTEXTS_TABLE)
                        .where(
                            LINE_PAYMENT_CONTEXTS_TABLE.c.source_message_id
                            == str(source_message_id).strip()
                        )
                        .limit(1)
                    )
                    .mappings()
                    .one_or_none()
                )
            if row is not None:
                return _context_from_mapping(row)
            raise
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(LINE_PAYMENT_CONTEXTS_TABLE)
                    .where(LINE_PAYMENT_CONTEXTS_TABLE.c.id == context_id)
                    .limit(1)
                )
                .mappings()
                .one()
            )
        return _context_from_mapping(row)

    def latest_context_for_user(self, line_user_id: str) -> LinePaymentContextRecord | None:
        now = _now()
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(LINE_PAYMENT_CONTEXTS_TABLE)
                    .where(
                        LINE_PAYMENT_CONTEXTS_TABLE.c.line_user_id == str(line_user_id).strip(),
                        or_(
                            LINE_PAYMENT_CONTEXTS_TABLE.c.expires_at.is_(None),
                            LINE_PAYMENT_CONTEXTS_TABLE.c.expires_at > now,
                        ),
                    )
                    .order_by(desc(LINE_PAYMENT_CONTEXTS_TABLE.c.created_at))
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _context_from_mapping(row) if row is not None else None

    # ------------------------------------------------------------ subscribers
    def add_admin_subscriber(
        self, *, line_user_id: str, tenant_id: str | None = None, display_name: str | None = None
    ) -> LineAdminSubscriberRecord:
        normalized_user = str(line_user_id).strip()
        existing = self._get_subscriber(normalized_user)
        if existing is not None:
            return existing
        subscriber_id = str(uuid4())
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    insert(LINE_ADMIN_SUBSCRIBERS_TABLE).values(
                        id=subscriber_id,
                        line_user_id=normalized_user,
                        tenant_id=_opt_uuid(tenant_id),
                        display_name=display_name,
                        created_at=_now(),
                    )
                )
        except IntegrityError:
            existing = self._get_subscriber(normalized_user)
            if existing is not None:
                return existing
            raise
        created = self._get_subscriber(normalized_user)
        assert created is not None
        return created

    def _get_subscriber(self, line_user_id: str) -> LineAdminSubscriberRecord | None:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(LINE_ADMIN_SUBSCRIBERS_TABLE)
                    .where(LINE_ADMIN_SUBSCRIBERS_TABLE.c.line_user_id == str(line_user_id).strip())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        return _subscriber_from_mapping(row) if row is not None else None

    def list_admin_subscribers(
        self, *, tenant_id: str | None = None
    ) -> list[LineAdminSubscriberRecord]:
        """Return global (tenant_id IS NULL) subscribers plus tenant-specific ones."""
        condition = LINE_ADMIN_SUBSCRIBERS_TABLE.c.tenant_id.is_(None)
        if tenant_id is not None:
            condition = or_(
                condition,
                LINE_ADMIN_SUBSCRIBERS_TABLE.c.tenant_id == normalize_uuid_string(tenant_id),
            )
        with self._engine.begin() as connection:
            rows = (
                connection.execute(
                    select(LINE_ADMIN_SUBSCRIBERS_TABLE)
                    .where(condition)
                    .order_by(LINE_ADMIN_SUBSCRIBERS_TABLE.c.created_at)
                )
                .mappings()
                .all()
            )
        return [_subscriber_from_mapping(row) for row in rows]


def create_line_payment_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = False,
) -> LinePaymentRepository:
    return LinePaymentRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
