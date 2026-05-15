"""Deterministic scheduled discovery job planning."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from egp_crawler_core.discovery_authorization import (
    DiscoveryAuthorizationSnapshot,
    build_discovery_authorization_snapshot,
    require_discovery_authorization,
)
from egp_db.repositories.admin_repo import SqlAdminRepository, create_admin_repository
from egp_db.repositories.billing_repo import SqlBillingRepository, create_billing_repository
from egp_db.repositories.profile_repo import SqlProfileRepository, create_profile_repository
from egp_db.repositories.run_repo import SqlRunRepository, create_run_repository


def build_scheduled_discovery_jobs(
    *,
    tenants: list[dict[str, object]],
    now: datetime | None = None,
) -> list[dict[str, object]]:
    reference_now = now or datetime.now(UTC)
    jobs: list[dict[str, object]] = []

    for tenant in tenants:
        if not _tenant_is_due(tenant=tenant, now=reference_now):
            continue
        tenant_id = str(tenant["tenant_id"])
        for profile in list(tenant.get("profiles") or []):
            if not bool(profile.get("is_active", False)):
                continue
            profile_id = str(profile["profile_id"])
            profile_type = str(profile.get("profile_type") or "custom")
            for keyword in list(profile.get("keywords") or []):
                normalized_keyword = str(keyword).strip()
                if not normalized_keyword:
                    continue
                jobs.append(
                    {
                        "tenant_id": tenant_id,
                        "profile_id": profile_id,
                        "profile": profile_type,
                        "keyword": normalized_keyword,
                        "trigger_type": "schedule",
                        "live": True,
                    }
                )
    return jobs


def run_scheduled_discovery(
    *,
    database_url: str,
    admin_repository: SqlAdminRepository | None = None,
    billing_repository: SqlBillingRepository | None = None,
    profile_repository: SqlProfileRepository | None = None,
    run_repository: SqlRunRepository | None = None,
    job_runner: Callable[[dict[str, object]], dict[str, object]] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    resolved_admin_repository = admin_repository or create_admin_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    resolved_billing_repository = billing_repository or create_billing_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    resolved_profile_repository = profile_repository or create_profile_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    resolved_run_repository = run_repository or create_run_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    runner = job_runner or (lambda job: job)

    tenants: list[dict[str, object]] = []
    for tenant in resolved_admin_repository.list_active_tenants():
        settings = resolved_admin_repository.get_tenant_settings(tenant_id=tenant.id)
        profiles = resolved_profile_repository.list_profiles_with_keywords(tenant_id=tenant.id)
        recent_runs = resolved_run_repository.list_runs(tenant_id=tenant.id, limit=50, offset=0)
        last_scheduled_run_at = _latest_scheduled_run_at(recent_runs.items)
        tenants.append(
            {
                "tenant_id": tenant.id,
                "crawl_interval_hours": settings.crawl_interval_hours,
                "last_scheduled_run_at": last_scheduled_run_at,
                "profiles": [
                    {
                        "profile_id": detail.profile.id,
                        "profile_type": detail.profile.profile_type,
                        "is_active": detail.profile.is_active,
                        "keywords": [keyword.keyword for keyword in detail.keywords],
                    }
                    for detail in profiles
                ],
            }
        )

    due_jobs = build_scheduled_discovery_jobs(tenants=tenants, now=now)
    filtered_jobs: list[dict[str, object]] = []
    authorization_snapshots: dict[str, DiscoveryAuthorizationSnapshot] = {}
    for job in due_jobs:
        tenant_id = str(job["tenant_id"])
        snapshot = authorization_snapshots.get(tenant_id)
        if snapshot is None:
            active_keywords = resolved_profile_repository.list_active_keywords(tenant_id=tenant_id)
            snapshot = build_discovery_authorization_snapshot(
                subscriptions=resolved_billing_repository.list_subscriptions_for_tenant(
                    tenant_id=tenant_id
                ),
                active_keywords=active_keywords,
            )
            authorization_snapshots[tenant_id] = snapshot
        try:
            require_discovery_authorization(snapshot=snapshot, keyword=str(job["keyword"]))
        except PermissionError:
            continue
        filtered_jobs.append(job)
    executed_jobs = [runner(job) for job in filtered_jobs]
    return {
        "due_job_count": len(filtered_jobs),
        "executed_job_count": len(executed_jobs),
        "jobs": filtered_jobs,
        "results": executed_jobs,
    }


def _tenant_is_due(*, tenant: dict[str, object], now: datetime) -> bool:
    interval_hours = int(tenant.get("crawl_interval_hours") or 24)
    last_run_raw = tenant.get("last_scheduled_run_at")
    if last_run_raw in {None, ""}:
        return True
    last_run = datetime.fromisoformat(str(last_run_raw))
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)
    return last_run <= now - timedelta(hours=interval_hours)


def _latest_scheduled_run_at(runs: list[object]) -> str | None:
    latest: datetime | None = None
    for run in runs:
        if str(getattr(run, "trigger_type", "")) != "schedule":
            continue
        raw_value = getattr(run, "created_at", None) or getattr(run, "started_at", None)
        if raw_value in {None, ""}:
            continue
        parsed = datetime.fromisoformat(str(raw_value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if latest is None or parsed > latest:
            latest = parsed
    return latest.isoformat() if latest is not None else None
