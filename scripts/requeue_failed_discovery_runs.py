"""Dry-run-first recovery for explicit failed manual discovery runs."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json

from sqlalchemy import and_, select

from egp_api.config import get_database_url
from egp_db.connection import create_shared_engine
from egp_db.db_utils import normalize_uuid_string
from egp_db.repositories.discovery_job_repo import DISCOVERY_JOBS_TABLE
from egp_db.repositories.profile_repo import CRAWL_PROFILES_TABLE
from egp_db.repositories.recrawl_request_repo import (
    RecrawlJobInput,
    RecrawlRequestCreateResult,
    SqlRecrawlRequestRepository,
)
from egp_db.repositories.run_repo import CRAWL_RUNS_TABLE, CRAWL_TASKS_TABLE


class RecoveryValidationError(ValueError):
    """Raised when an incident recovery manifest is not safe to execute."""


@dataclass(frozen=True, slots=True)
class RecoverySource:
    run_id: str
    profile_id: str
    profile_type: str
    keyword: str


@dataclass(frozen=True, slots=True)
class RecoveryJob:
    profile_id: str
    profile_type: str
    keyword: str
    source_run_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryConflict:
    job_id: str
    profile_id: str
    keyword: str
    trigger_type: str
    recrawl_request_id: str | None


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    tenant_id: str
    expected_count: int | None
    idempotency_key: str
    sources: tuple[RecoverySource, ...]
    jobs: tuple[RecoveryJob, ...]
    conflicts: tuple[RecoveryConflict, ...]

    @property
    def is_executable(self) -> bool:
        return not self.conflicts

    def to_dict(self, *, mode: str = "dry_run") -> dict[str, object]:
        return {
            "mode": mode,
            "tenant_id": self.tenant_id,
            "expected_count": self.expected_count,
            "idempotency_key": self.idempotency_key,
            "is_executable": self.is_executable,
            "source_run_count": len(self.sources),
            "recovery_job_count": len(self.jobs),
            "sources": [asdict(source) for source in self.sources],
            "jobs": [asdict(job) for job in self.jobs],
            "conflicts": [asdict(conflict) for conflict in self.conflicts],
        }


def _normalize_ids(*, tenant_id: str, run_ids: list[str]) -> tuple[str, list[str]]:
    try:
        normalized_tenant_id = normalize_uuid_string(tenant_id)
        normalized_run_ids = [normalize_uuid_string(run_id) for run_id in run_ids]
    except (TypeError, ValueError) as exc:
        raise RecoveryValidationError("tenant and run IDs must be UUIDs") from exc
    if not normalized_run_ids:
        raise RecoveryValidationError("at least one explicit run ID is required")
    if len(set(normalized_run_ids)) != len(normalized_run_ids):
        raise RecoveryValidationError("source run IDs must be unique")
    return normalized_tenant_id, normalized_run_ids


def _idempotency_key(
    *,
    tenant_id: str,
    sources: list[RecoverySource],
    jobs: list[RecoveryJob],
) -> str:
    payload = {
        "tenant_id": tenant_id,
        "source_run_ids": sorted(source.run_id for source in sources),
        "jobs": sorted(
            (job.profile_id, job.keyword.casefold())
            for job in jobs
        ),
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"failed-manual-runs-v1:{digest}"


def build_recovery_plan(
    *,
    database_url: str,
    tenant_id: str,
    run_ids: list[str],
    expected_count: int | None = 10,
) -> RecoveryPlan:
    """Validate explicit historical runs and return a read-only recovery plan."""

    normalized_tenant_id, normalized_run_ids = _normalize_ids(
        tenant_id=tenant_id,
        run_ids=run_ids,
    )
    if expected_count is not None and expected_count < 1:
        raise RecoveryValidationError("expected count must be positive")

    engine = create_shared_engine(database_url)
    with engine.connect() as connection:
        run_rows = connection.execute(
            select(CRAWL_RUNS_TABLE).where(
                CRAWL_RUNS_TABLE.c.id.in_(normalized_run_ids)
            )
        ).mappings().all()
        runs_by_id = {str(row["id"]): row for row in run_rows}
        missing_ids = [run_id for run_id in normalized_run_ids if run_id not in runs_by_id]
        if missing_ids:
            raise RecoveryValidationError(
                "source runs not found: " + ", ".join(missing_ids)
            )

        profile_ids: list[str] = []
        for run_id in normalized_run_ids:
            row = runs_by_id[run_id]
            if str(row["tenant_id"]) != normalized_tenant_id:
                raise RecoveryValidationError(f"source run {run_id} belongs to another tenant")
            if str(row["status"]) != "failed" or str(row["trigger_type"]) != "manual":
                raise RecoveryValidationError(
                    f"source run {run_id} must be a failed manual run"
                )
            if row["profile_id"] is None:
                raise RecoveryValidationError(f"source run {run_id} has no profile")
            profile_ids.append(str(row["profile_id"]))

        profile_rows = connection.execute(
            select(CRAWL_PROFILES_TABLE).where(
                CRAWL_PROFILES_TABLE.c.id.in_(set(profile_ids))
            )
        ).mappings().all()
        profiles_by_id = {str(row["id"]): row for row in profile_rows}
        task_rows = connection.execute(
            select(CRAWL_TASKS_TABLE).where(
                and_(
                    CRAWL_TASKS_TABLE.c.run_id.in_(normalized_run_ids),
                    CRAWL_TASKS_TABLE.c.task_type == "discover",
                )
            )
        ).mappings().all()
        tasks_by_run: dict[str, list] = {}
        for row in task_rows:
            tasks_by_run.setdefault(str(row["run_id"]), []).append(row)

        sources: list[RecoverySource] = []
        for run_id in normalized_run_ids:
            run_row = runs_by_id[run_id]
            profile_id = str(run_row["profile_id"])
            profile = profiles_by_id.get(profile_id)
            if profile is None or str(profile["tenant_id"]) != normalized_tenant_id:
                raise RecoveryValidationError(
                    f"source run {run_id} profile is not resolvable for tenant"
                )
            if not bool(profile["enabled_by_user"]) or not bool(profile["is_active"]):
                raise RecoveryValidationError(
                    f"source run {run_id} profile is paused"
                )
            run_tasks = tasks_by_run.get(run_id, [])
            if len(run_tasks) != 1:
                raise RecoveryValidationError(
                    f"source run {run_id} must have exactly one discover task"
                )
            keyword = str(run_tasks[0]["keyword"] or "").strip()
            if not keyword:
                raise RecoveryValidationError(
                    f"source run {run_id} discover task has no keyword"
                )
            sources.append(
                RecoverySource(
                    run_id=run_id,
                    profile_id=profile_id,
                    profile_type=str(profile["profile_type"]),
                    keyword=keyword,
                )
            )

        jobs_by_key: dict[tuple[str, str], RecoveryJob] = {}
        for source in sources:
            key = (source.profile_id, source.keyword.casefold())
            existing = jobs_by_key.get(key)
            if existing is None:
                jobs_by_key[key] = RecoveryJob(
                    profile_id=source.profile_id,
                    profile_type=source.profile_type,
                    keyword=source.keyword,
                    source_run_ids=(source.run_id,),
                )
            else:
                jobs_by_key[key] = RecoveryJob(
                    profile_id=existing.profile_id,
                    profile_type=existing.profile_type,
                    keyword=existing.keyword,
                    source_run_ids=(*existing.source_run_ids, source.run_id),
                )
        jobs = list(jobs_by_key.values())

        if expected_count is not None and (
            len(sources) != expected_count or len(jobs) != expected_count
        ):
            raise RecoveryValidationError(
                f"expected {expected_count} source runs and recovery jobs; "
                f"found {len(sources)} source runs and {len(jobs)} recovery jobs"
            )

        target_profile_ids = {job.profile_id for job in jobs}
        pending_rows = connection.execute(
            select(DISCOVERY_JOBS_TABLE).where(
                and_(
                    DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                    DISCOVERY_JOBS_TABLE.c.profile_id.in_(target_profile_ids),
                    DISCOVERY_JOBS_TABLE.c.live.is_(True),
                    DISCOVERY_JOBS_TABLE.c.job_status == "pending",
                )
            )
        ).mappings().all()

    target_keys = {(job.profile_id, job.keyword.casefold()) for job in jobs}
    conflicts = [
        RecoveryConflict(
            job_id=str(row["id"]),
            profile_id=str(row["profile_id"]),
            keyword=str(row["keyword"]),
            trigger_type=str(row["trigger_type"]),
            recrawl_request_id=(
                str(row["recrawl_request_id"])
                if row["recrawl_request_id"] is not None
                else None
            ),
        )
        for row in pending_rows
        if (str(row["profile_id"]), str(row["keyword"]).casefold()) in target_keys
    ]
    return RecoveryPlan(
        tenant_id=normalized_tenant_id,
        expected_count=expected_count,
        idempotency_key=_idempotency_key(
            tenant_id=normalized_tenant_id,
            sources=sources,
            jobs=jobs,
        ),
        sources=tuple(sources),
        jobs=tuple(jobs),
        conflicts=tuple(conflicts),
    )


def execute_recovery_plan(
    *,
    database_url: str,
    plan: RecoveryPlan,
) -> RecrawlRequestCreateResult:
    """Atomically enqueue a validated operator recovery request."""

    fresh_plan = build_recovery_plan(
        database_url=database_url,
        tenant_id=plan.tenant_id,
        run_ids=[source.run_id for source in plan.sources],
        expected_count=plan.expected_count,
    )
    if fresh_plan.idempotency_key != plan.idempotency_key:
        raise RecoveryValidationError("recovery plan changed since dry-run validation")
    repository = SqlRecrawlRequestRepository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    try:
        return repository.create_request(
            tenant_id=fresh_plan.tenant_id,
            jobs=[
                RecrawlJobInput(
                    profile_id=job.profile_id,
                    profile_type=job.profile_type,
                    keyword=job.keyword,
                )
                for job in fresh_plan.jobs
            ],
            source="operator_recovery",
            idempotency_key=fresh_plan.idempotency_key,
            trigger_type="retry",
            reject_existing_pending=True,
        )
    except ValueError as exc:
        raise RecoveryValidationError(str(exc)) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and optionally requeue explicit failed manual discovery runs.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--run-id",
        action="append",
        required=True,
        dest="run_ids",
        help="Explicit failed source run UUID. Repeat for every source run.",
    )
    parser.add_argument("--expected-count", type=int, default=10)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Create one recovery request. Without this flag the command is read-only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    mode = "execute" if args.execute else "dry_run"
    try:
        database_url = get_database_url(args.database_url)
        plan = build_recovery_plan(
            database_url=database_url,
            tenant_id=args.tenant_id,
            run_ids=args.run_ids,
            expected_count=args.expected_count,
        )
        output = plan.to_dict(mode=mode)
        if args.execute:
            result = execute_recovery_plan(database_url=database_url, plan=plan)
            output.update(
                request_id=result.request_id,
                queued_job_count=result.queued_job_count,
                queued_keywords=result.queued_keywords,
            )
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if args.execute or plan.is_executable else 2
    except (KeyError, RecoveryValidationError, RuntimeError) as exc:
        print(json.dumps({"mode": mode, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
