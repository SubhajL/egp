"""Tenant-scoped crawl profile persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine, RowMapping

from egp_db.connection import DB_METADATA, create_shared_engine
from egp_db.db_utils import UUID_SQL_TYPE, normalize_database_url, normalize_uuid_string


@dataclass(frozen=True, slots=True)
class CrawlProfileRecord:
    id: str
    tenant_id: str
    name: str
    profile_type: str
    is_active: bool
    max_pages_per_keyword: int
    close_consulting_after_days: int
    close_stale_after_days: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CrawlProfileKeywordRecord:
    id: str
    profile_id: str
    keyword: str
    position: int
    created_at: str


@dataclass(frozen=True, slots=True)
class CrawlProfileDetail:
    profile: CrawlProfileRecord
    keywords: list[CrawlProfileKeywordRecord]


METADATA = DB_METADATA

CRAWL_PROFILES_TABLE = Table(
    "crawl_profiles",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column("tenant_id", UUID_SQL_TYPE, nullable=False),
    Column("name", String, nullable=False),
    Column("profile_type", String, nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("max_pages_per_keyword", Integer, nullable=False, default=15),
    Column("close_consulting_after_days", Integer, nullable=False, default=30),
    Column("close_stale_after_days", Integer, nullable=False, default=45),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

CRAWL_PROFILE_KEYWORDS_TABLE = Table(
    "crawl_profile_keywords",
    METADATA,
    Column("id", UUID_SQL_TYPE, primary_key=True),
    Column(
        "profile_id",
        UUID_SQL_TYPE,
        ForeignKey("crawl_profiles.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("keyword", String, nullable=False),
    Column("position", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _now() -> datetime:
    return datetime.now(UTC)


def _profile_from_mapping(row: RowMapping) -> CrawlProfileRecord:
    return CrawlProfileRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        name=str(row["name"]),
        profile_type=str(row["profile_type"]),
        is_active=bool(row["is_active"]),
        max_pages_per_keyword=int(row["max_pages_per_keyword"]),
        close_consulting_after_days=int(row["close_consulting_after_days"]),
        close_stale_after_days=int(row["close_stale_after_days"]),
        created_at=_dt_to_iso(row["created_at"]) or "",
        updated_at=_dt_to_iso(row["updated_at"]) or "",
    )


def _keyword_from_mapping(row: RowMapping) -> CrawlProfileKeywordRecord:
    return CrawlProfileKeywordRecord(
        id=str(row["id"]),
        profile_id=str(row["profile_id"]),
        keyword=str(row["keyword"]),
        position=int(row["position"]),
        created_at=_dt_to_iso(row["created_at"]) or "",
    )


class SqlProfileRepository:
    """Relational crawl profile repository."""

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

    def list_profiles_with_keywords(
        self, *, tenant_id: str
    ) -> list[CrawlProfileDetail]:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        with self._engine.connect() as connection:
            profile_rows = (
                connection.execute(
                    select(CRAWL_PROFILES_TABLE)
                    .where(CRAWL_PROFILES_TABLE.c.tenant_id == normalized_tenant_id)
                    .order_by(
                        CRAWL_PROFILES_TABLE.c.created_at, CRAWL_PROFILES_TABLE.c.id
                    )
                )
                .mappings()
                .all()
            )
            if not profile_rows:
                return []
            profile_ids = [row["id"] for row in profile_rows]
            keyword_rows = (
                connection.execute(
                    select(CRAWL_PROFILE_KEYWORDS_TABLE)
                    .where(CRAWL_PROFILE_KEYWORDS_TABLE.c.profile_id.in_(profile_ids))
                    .order_by(
                        CRAWL_PROFILE_KEYWORDS_TABLE.c.profile_id,
                        CRAWL_PROFILE_KEYWORDS_TABLE.c.position,
                        CRAWL_PROFILE_KEYWORDS_TABLE.c.created_at,
                    )
                )
                .mappings()
                .all()
            )
        keywords_by_profile: dict[str, list[CrawlProfileKeywordRecord]] = {
            str(row["id"]): [] for row in profile_rows
        }
        for row in keyword_rows:
            keyword = _keyword_from_mapping(row)
            keywords_by_profile.setdefault(keyword.profile_id, []).append(keyword)
        return [
            CrawlProfileDetail(
                profile=_profile_from_mapping(row),
                keywords=keywords_by_profile.get(str(row["id"]), []),
            )
            for row in profile_rows
        ]

    def list_active_keywords(self, *, tenant_id: str) -> list[str]:
        profiles = self.list_profiles_with_keywords(tenant_id=tenant_id)
        ordered: list[str] = []
        seen: set[str] = set()
        for detail in profiles:
            if not detail.profile.is_active:
                continue
            for keyword in detail.keywords:
                normalized = str(keyword.keyword).strip()
                if not normalized:
                    continue
                dedupe_key = normalized.casefold()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                ordered.append(normalized)
        return ordered

    def get_profile_detail(self, *, tenant_id: str, profile_id: str) -> CrawlProfileDetail | None:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_profile_id = normalize_uuid_string(profile_id)
        with self._engine.connect() as connection:
            profile_row = (
                connection.execute(
                    select(CRAWL_PROFILES_TABLE)
                    .where(CRAWL_PROFILES_TABLE.c.tenant_id == normalized_tenant_id)
                    .where(CRAWL_PROFILES_TABLE.c.id == normalized_profile_id)
                )
                .mappings()
                .first()
            )
            if profile_row is None:
                return None
            keyword_rows = (
                connection.execute(
                    select(CRAWL_PROFILE_KEYWORDS_TABLE)
                    .where(CRAWL_PROFILE_KEYWORDS_TABLE.c.profile_id == normalized_profile_id)
                    .order_by(
                        CRAWL_PROFILE_KEYWORDS_TABLE.c.position,
                        CRAWL_PROFILE_KEYWORDS_TABLE.c.created_at,
                    )
                )
                .mappings()
                .all()
            )
        return CrawlProfileDetail(
            profile=_profile_from_mapping(profile_row),
            keywords=[_keyword_from_mapping(row) for row in keyword_rows],
        )

    def create_profile(
        self,
        *,
        tenant_id: str,
        name: str,
        profile_type: str,
        is_active: bool,
        max_pages_per_keyword: int,
        close_consulting_after_days: int,
        close_stale_after_days: int,
        keywords: list[str],
    ) -> CrawlProfileDetail:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        profile_id = str(uuid4())
        now = _now()
        with self._engine.begin() as connection:
            connection.execute(
                insert(CRAWL_PROFILES_TABLE).values(
                    id=profile_id,
                    tenant_id=normalized_tenant_id,
                    name=name,
                    profile_type=profile_type,
                    is_active=is_active,
                    max_pages_per_keyword=max_pages_per_keyword,
                    close_consulting_after_days=close_consulting_after_days,
                    close_stale_after_days=close_stale_after_days,
                    created_at=now,
                    updated_at=now,
                )
            )
            for position, keyword in enumerate(keywords, start=1):
                connection.execute(
                    insert(CRAWL_PROFILE_KEYWORDS_TABLE).values(
                        id=str(uuid4()),
                        profile_id=profile_id,
                        keyword=keyword,
                        position=position,
                        created_at=now,
                    )
                )
        detail = self.get_profile_detail(tenant_id=normalized_tenant_id, profile_id=profile_id)
        if detail is None:
            raise RuntimeError(f"profile {profile_id} not found after creation")
        return detail

    def update_profile(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        name: str | None = None,
        is_active: bool | None = None,
        keywords: list[str] | None = None,
        max_pages_per_keyword: int | None = None,
        close_consulting_after_days: int | None = None,
        close_stale_after_days: int | None = None,
    ) -> CrawlProfileDetail:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_profile_id = normalize_uuid_string(profile_id)
        now = _now()
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(CRAWL_PROFILES_TABLE)
                    .where(CRAWL_PROFILES_TABLE.c.tenant_id == normalized_tenant_id)
                    .where(CRAWL_PROFILES_TABLE.c.id == normalized_profile_id)
                )
                .mappings()
                .first()
            )
            if existing is None:
                raise KeyError(profile_id)
            connection.execute(
                update(CRAWL_PROFILES_TABLE)
                .where(CRAWL_PROFILES_TABLE.c.id == normalized_profile_id)
                .values(
                    name=existing["name"] if name is None else name,
                    is_active=existing["is_active"] if is_active is None else is_active,
                    max_pages_per_keyword=(
                        existing["max_pages_per_keyword"]
                        if max_pages_per_keyword is None
                        else max_pages_per_keyword
                    ),
                    close_consulting_after_days=(
                        existing["close_consulting_after_days"]
                        if close_consulting_after_days is None
                        else close_consulting_after_days
                    ),
                    close_stale_after_days=(
                        existing["close_stale_after_days"]
                        if close_stale_after_days is None
                        else close_stale_after_days
                    ),
                    updated_at=now,
                )
            )
            if keywords is not None:
                connection.execute(
                    delete(CRAWL_PROFILE_KEYWORDS_TABLE).where(
                        CRAWL_PROFILE_KEYWORDS_TABLE.c.profile_id == normalized_profile_id
                    )
                )
                for position, keyword in enumerate(keywords, start=1):
                    connection.execute(
                        insert(CRAWL_PROFILE_KEYWORDS_TABLE).values(
                            id=str(uuid4()),
                            profile_id=normalized_profile_id,
                            keyword=keyword,
                            position=position,
                            created_at=now,
                        )
                    )
        detail = self.get_profile_detail(
            tenant_id=normalized_tenant_id,
            profile_id=normalized_profile_id,
        )
        if detail is None:
            raise RuntimeError(f"profile {profile_id} not found after update")
        return detail


def create_profile_repository(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    bootstrap_schema: bool = True,
) -> SqlProfileRepository:
    return SqlProfileRepository(
        database_url=database_url, engine=engine, bootstrap_schema=bootstrap_schema
    )
