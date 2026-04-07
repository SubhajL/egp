"""Tenant-scoped password authentication and account lifecycle persistence."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    String,
    Table,
    and_,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string
from egp_db.repositories.admin_repo import TENANTS_TABLE
from egp_db.repositories.notification_repo import USERS_TABLE


METADATA = DB_METADATA

USER_SESSIONS_TABLE = Table(
    "user_sessions",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("user_id", UUID_SQL_TYPE, nullable=False),
    Column("session_token_hash", String, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=True),
)

Index(
    "idx_user_sessions_tenant_user",
    USER_SESSIONS_TABLE.c.tenant_id,
    USER_SESSIONS_TABLE.c.user_id,
    USER_SESSIONS_TABLE.c.created_at,
)

ACCOUNT_ACTION_TOKENS_TABLE = Table(
    "account_action_tokens",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("user_id", UUID_SQL_TYPE, nullable=False),
    Column("purpose", String, nullable=False),
    Column("delivery_email", String, nullable=True),
    Column("token_hash", String, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

Index(
    "idx_account_action_tokens_user_purpose",
    ACCOUNT_ACTION_TOKENS_TABLE.c.tenant_id,
    ACCOUNT_ACTION_TOKENS_TABLE.c.user_id,
    ACCOUNT_ACTION_TOKENS_TABLE.c.purpose,
    ACCOUNT_ACTION_TOKENS_TABLE.c.created_at,
)


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390000
SESSION_TOKEN_BYTES = 32
ACCOUNT_ACTION_PURPOSES = {"invite", "password_reset", "email_verification"}


@dataclass(frozen=True, slots=True)
class LoginUserRecord:
    user_id: str
    tenant_id: str
    tenant_name: str
    tenant_slug: str
    tenant_plan_code: str
    tenant_is_active: bool
    email: str
    full_name: str | None
    role: str
    status: str
    password_hash: str | None
    email_verified_at: str | None
    mfa_enabled: bool
    mfa_secret: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _hash_opaque_token(token: str) -> str:
    digest = hashlib.sha256(str(token).encode("utf-8")).digest()
    return _b64encode(digest)


def _normalize_email(value: str) -> str:
    return str(value).strip().lower()


def _normalize_password_hash(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_secret(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def hash_password(password: str) -> str:
    normalized = str(password)
    if len(normalized.strip()) < 12:
        raise ValueError("password must be at least 12 characters")
    salt = token_urlsafe(12)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt}${_b64encode(digest)}"


def verify_password(password: str, encoded_hash: str | None) -> bool:
    if encoded_hash is None:
        return False
    try:
        scheme, raw_iterations, salt, raw_hash = str(encoded_hash).split("$", 3)
        iterations = int(raw_iterations)
    except (TypeError, ValueError):
        return False
    if scheme != PASSWORD_SCHEME or iterations <= 0:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(_b64encode(digest), raw_hash)


def _login_user_from_mapping(row: RowMapping) -> LoginUserRecord:
    return LoginUserRecord(
        user_id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        tenant_name=str(row["name"]),
        tenant_slug=str(row["slug"]),
        tenant_plan_code=str(row["plan_code"]),
        tenant_is_active=bool(row["is_active"]),
        email=str(row["email"]),
        full_name=str(row["full_name"]) if row["full_name"] is not None else None,
        role=str(row["role"]),
        status=str(row["status"]),
        password_hash=_normalize_password_hash(row["password_hash"]),
        email_verified_at=_to_iso(row["email_verified_at"]),
        mfa_enabled=bool(row["mfa_enabled"]),
        mfa_secret=_normalize_secret(row["mfa_secret"]),
    )


class SqlAuthRepository:
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
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        METADATA.create_all(self._engine)

    def find_login_user(
        self, *, tenant_slug: str, email: str
    ) -> LoginUserRecord | None:
        normalized_slug = str(tenant_slug).strip().lower()
        normalized_email = _normalize_email(email)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        USERS_TABLE,
                        TENANTS_TABLE.c.name,
                        TENANTS_TABLE.c.slug,
                        TENANTS_TABLE.c.plan_code,
                        TENANTS_TABLE.c.is_active,
                    )
                    .select_from(
                        USERS_TABLE.join(
                            TENANTS_TABLE,
                            TENANTS_TABLE.c.id == USERS_TABLE.c.tenant_id,
                        )
                    )
                    .where(
                        and_(
                            TENANTS_TABLE.c.slug == normalized_slug,
                            func.lower(USERS_TABLE.c.email) == normalized_email,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _login_user_from_mapping(row)

    def list_login_users_by_email(self, *, email: str) -> list[LoginUserRecord]:
        normalized_email = _normalize_email(email)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(
                        USERS_TABLE,
                        TENANTS_TABLE.c.name,
                        TENANTS_TABLE.c.slug,
                        TENANTS_TABLE.c.plan_code,
                        TENANTS_TABLE.c.is_active,
                    )
                    .select_from(
                        USERS_TABLE.join(
                            TENANTS_TABLE,
                            TENANTS_TABLE.c.id == USERS_TABLE.c.tenant_id,
                        )
                    )
                    .where(func.lower(USERS_TABLE.c.email) == normalized_email)
                    .order_by(TENANTS_TABLE.c.slug, USERS_TABLE.c.id)
                )
                .mappings()
                .all()
            )
        return [_login_user_from_mapping(row) for row in rows]

    def find_login_user_by_email(self, *, email: str) -> LoginUserRecord | None:
        """Find a unique user with this email across all tenants, else fail closed."""
        rows = self.list_login_users_by_email(email=email)
        if len(rows) != 1:
            return None
        return rows[0]

    def get_user_by_id(self, *, tenant_id: str, user_id: str) -> LoginUserRecord | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_user_id = normalize_uuid_string(user_id)
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(
                        USERS_TABLE,
                        TENANTS_TABLE.c.name,
                        TENANTS_TABLE.c.slug,
                        TENANTS_TABLE.c.plan_code,
                        TENANTS_TABLE.c.is_active,
                    )
                    .select_from(
                        USERS_TABLE.join(
                            TENANTS_TABLE,
                            TENANTS_TABLE.c.id == USERS_TABLE.c.tenant_id,
                        )
                    )
                    .where(
                        and_(
                            USERS_TABLE.c.tenant_id == normalized_tenant_id,
                            USERS_TABLE.c.id == normalized_user_id,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _login_user_from_mapping(row)

    def create_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        expires_in_seconds: int,
    ) -> str:
        now = _now()
        raw_token = token_urlsafe(SESSION_TOKEN_BYTES)
        with self._engine.begin() as connection:
            connection.execute(
                insert(USER_SESSIONS_TABLE).values(
                    id=str(uuid4()),
                    tenant_id=normalize_uuid_string(tenant_id),
                    user_id=normalize_uuid_string(user_id),
                    session_token_hash=_hash_opaque_token(raw_token),
                    expires_at=now
                    + timedelta(seconds=max(60, int(expires_in_seconds))),
                    revoked_at=None,
                    created_at=now,
                    updated_at=now,
                    last_seen_at=now,
                )
            )
        return raw_token

    def revoke_session(self, *, session_token: str) -> bool:
        now = _now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(USER_SESSIONS_TABLE)
                .where(
                    and_(
                        USER_SESSIONS_TABLE.c.session_token_hash
                        == _hash_opaque_token(session_token),
                        USER_SESSIONS_TABLE.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now, updated_at=now)
            )
        return bool(result.rowcount)

    def revoke_all_sessions_for_user(self, *, tenant_id: str, user_id: str) -> int:
        now = _now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(USER_SESSIONS_TABLE)
                .where(
                    and_(
                        USER_SESSIONS_TABLE.c.tenant_id
                        == normalize_uuid_string(tenant_id),
                        USER_SESSIONS_TABLE.c.user_id == normalize_uuid_string(user_id),
                        USER_SESSIONS_TABLE.c.revoked_at.is_(None),
                    )
                )
                .values(revoked_at=now, updated_at=now)
            )
        return int(result.rowcount or 0)

    def get_session_user(self, *, session_token: str) -> LoginUserRecord | None:
        now = _now()
        session_token_hash = _hash_opaque_token(session_token)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        USERS_TABLE,
                        TENANTS_TABLE.c.name,
                        TENANTS_TABLE.c.slug,
                        TENANTS_TABLE.c.plan_code,
                        TENANTS_TABLE.c.is_active,
                        USER_SESSIONS_TABLE.c.id.label("session_id"),
                    )
                    .select_from(
                        USER_SESSIONS_TABLE.join(
                            USERS_TABLE,
                            USERS_TABLE.c.id == USER_SESSIONS_TABLE.c.user_id,
                        ).join(
                            TENANTS_TABLE,
                            TENANTS_TABLE.c.id == USER_SESSIONS_TABLE.c.tenant_id,
                        )
                    )
                    .where(
                        and_(
                            USER_SESSIONS_TABLE.c.session_token_hash
                            == session_token_hash,
                            USER_SESSIONS_TABLE.c.revoked_at.is_(None),
                            USER_SESSIONS_TABLE.c.expires_at > now,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            connection.execute(
                update(USER_SESSIONS_TABLE)
                .where(USER_SESSIONS_TABLE.c.session_token_hash == session_token_hash)
                .values(last_seen_at=now, updated_at=now)
            )
        return _login_user_from_mapping(row)

    def create_account_action_token(
        self,
        *,
        tenant_id: str,
        user_id: str,
        purpose: str,
        delivery_email: str | None,
        expires_in_seconds: int,
        revoke_existing: bool = True,
    ) -> str:
        normalized_purpose = str(purpose).strip()
        if normalized_purpose not in ACCOUNT_ACTION_PURPOSES:
            raise ValueError(
                f"unsupported account action token purpose: {normalized_purpose}"
            )
        now = _now()
        raw_token = token_urlsafe(SESSION_TOKEN_BYTES)
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_user_id = normalize_uuid_string(user_id)
        with self._engine.begin() as connection:
            if revoke_existing:
                connection.execute(
                    update(ACCOUNT_ACTION_TOKENS_TABLE)
                    .where(
                        and_(
                            ACCOUNT_ACTION_TOKENS_TABLE.c.tenant_id
                            == normalized_tenant_id,
                            ACCOUNT_ACTION_TOKENS_TABLE.c.user_id == normalized_user_id,
                            ACCOUNT_ACTION_TOKENS_TABLE.c.purpose == normalized_purpose,
                            ACCOUNT_ACTION_TOKENS_TABLE.c.consumed_at.is_(None),
                            ACCOUNT_ACTION_TOKENS_TABLE.c.expires_at > now,
                        )
                    )
                    .values(consumed_at=now, updated_at=now)
                )
            connection.execute(
                insert(ACCOUNT_ACTION_TOKENS_TABLE).values(
                    id=str(uuid4()),
                    tenant_id=normalized_tenant_id,
                    user_id=normalized_user_id,
                    purpose=normalized_purpose,
                    delivery_email=(
                        str(delivery_email).strip().lower()
                        if delivery_email is not None
                        else None
                    ),
                    token_hash=_hash_opaque_token(raw_token),
                    expires_at=now
                    + timedelta(seconds=max(60, int(expires_in_seconds))),
                    consumed_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return raw_token

    def consume_account_action_token(
        self, *, token: str, purpose: str
    ) -> LoginUserRecord | None:
        normalized_purpose = str(purpose).strip()
        if normalized_purpose not in ACCOUNT_ACTION_PURPOSES:
            raise ValueError(
                f"unsupported account action token purpose: {normalized_purpose}"
            )
        now = _now()
        token_hash = _hash_opaque_token(token)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        USERS_TABLE,
                        TENANTS_TABLE.c.name,
                        TENANTS_TABLE.c.slug,
                        TENANTS_TABLE.c.plan_code,
                        TENANTS_TABLE.c.is_active,
                        ACCOUNT_ACTION_TOKENS_TABLE.c.id.label("action_token_id"),
                    )
                    .select_from(
                        ACCOUNT_ACTION_TOKENS_TABLE.join(
                            USERS_TABLE,
                            USERS_TABLE.c.id == ACCOUNT_ACTION_TOKENS_TABLE.c.user_id,
                        ).join(
                            TENANTS_TABLE,
                            TENANTS_TABLE.c.id
                            == ACCOUNT_ACTION_TOKENS_TABLE.c.tenant_id,
                        )
                    )
                    .where(
                        and_(
                            ACCOUNT_ACTION_TOKENS_TABLE.c.token_hash == token_hash,
                            ACCOUNT_ACTION_TOKENS_TABLE.c.purpose == normalized_purpose,
                            ACCOUNT_ACTION_TOKENS_TABLE.c.consumed_at.is_(None),
                            ACCOUNT_ACTION_TOKENS_TABLE.c.expires_at > now,
                        )
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            connection.execute(
                update(ACCOUNT_ACTION_TOKENS_TABLE)
                .where(ACCOUNT_ACTION_TOKENS_TABLE.c.token_hash == token_hash)
                .values(consumed_at=now, updated_at=now)
            )
        return _login_user_from_mapping(row)

    def mark_email_verified(self, *, tenant_id: str, user_id: str) -> str:
        now = _now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(USERS_TABLE)
                .where(
                    and_(
                        USERS_TABLE.c.tenant_id == normalize_uuid_string(tenant_id),
                        USERS_TABLE.c.id == normalize_uuid_string(user_id),
                    )
                )
                .values(email_verified_at=now, updated_at=now)
            )
        if not result.rowcount:
            raise KeyError(user_id)
        return _to_iso(now) or ""

    def update_password(
        self, *, tenant_id: str, user_id: str, password_hash: str
    ) -> None:
        now = _now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(USERS_TABLE)
                .where(
                    and_(
                        USERS_TABLE.c.tenant_id == normalize_uuid_string(tenant_id),
                        USERS_TABLE.c.id == normalize_uuid_string(user_id),
                    )
                )
                .values(password_hash=password_hash, updated_at=now)
            )
        if not result.rowcount:
            raise KeyError(user_id)

    def set_mfa_secret(
        self, *, tenant_id: str, user_id: str, secret: str | None
    ) -> None:
        now = _now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(USERS_TABLE)
                .where(
                    and_(
                        USERS_TABLE.c.tenant_id == normalize_uuid_string(tenant_id),
                        USERS_TABLE.c.id == normalize_uuid_string(user_id),
                    )
                )
                .values(
                    mfa_secret=_normalize_secret(secret),
                    mfa_enabled=False,
                    updated_at=now,
                )
            )
        if not result.rowcount:
            raise KeyError(user_id)

    def set_mfa_enabled(self, *, tenant_id: str, user_id: str, enabled: bool) -> None:
        now = _now()
        with self._engine.begin() as connection:
            result = connection.execute(
                update(USERS_TABLE)
                .where(
                    and_(
                        USERS_TABLE.c.tenant_id == normalize_uuid_string(tenant_id),
                        USERS_TABLE.c.id == normalize_uuid_string(user_id),
                    )
                )
                .values(mfa_enabled=bool(enabled), updated_at=now)
            )
        if not result.rowcount:
            raise KeyError(user_id)


def create_auth_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlAuthRepository:
    return SqlAuthRepository(
        database_url=database_url,
        engine=engine,
        bootstrap_schema=bootstrap_schema,
    )
