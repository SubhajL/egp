#!/usr/bin/env python3
"""Route one crawl profile between the legacy crawler and the agent backend.

This is the canary control for U8, and the rollback for it.

**A flip is not self-reversing.** `discovery_jobs.execution_backend` is stamped per
job at insert and is immutable afterwards, and the in-flight dedupe is
backend-agnostic. So setting a profile back to `legacy` does NOT rescue jobs
already queued as `agent`: they stay agent-owned, and their presence *blocks*
creation of a replacement legacy job for the same (profile, keyword). Without
`--reroute-pending` the rollback silently leaves that profile's keywords
uncrawled by anyone.

Ordering that matters:

* Flip to `agent` only AFTER an agent runtime is actually claiming. Otherwise the
  profile's jobs queue up and nothing drains them — visible as a rising
  `agent_queue_pending_count` on `/v1/rules/crawler-agent-inbox`.
* Flip back to `legacy` WITH `--reroute-pending`, or the queue stays stuck.

Examples::

    # preview
    python scripts/set_profile_execution_backend.py \\
        --tenant-id <uuid> --profile-id <uuid> --backend agent --dry-run

    # canary on
    python scripts/set_profile_execution_backend.py \\
        --tenant-id <uuid> --profile-id <uuid> --backend agent --confirm

    # roll back, including work already queued
    python scripts/set_profile_execution_backend.py \\
        --tenant-id <uuid> --profile-id <uuid> --backend legacy \\
        --reroute-pending --confirm
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import and_, select, update

from egp_db.connection import create_shared_engine
from egp_db.db_utils import normalize_uuid_string
from egp_db.repositories.discovery_job_repo import DISCOVERY_JOBS_TABLE
from egp_db.repositories.profile_repo import CRAWL_PROFILES_TABLE
from egp_shared_types.enums import (
    IN_FLIGHT_DISCOVERY_JOB_STATUS_VALUES,
    DiscoveryJobStatus,
    ExecutionBackend,
)


def set_profile_execution_backend(
    *,
    database_url: str,
    tenant_id: str,
    profile_id: str,
    backend: str,
    dry_run: bool = False,
    reroute_pending: bool = False,
) -> dict[str, object]:
    """Flip one profile's backend, optionally rerouting its queued jobs.

    Returns a summary dict. Raises ``ValueError`` for an unknown backend or a
    profile that does not exist for this tenant — never a silent no-op, because a
    typo'd id during a rollback would otherwise look like success.
    """

    target = ExecutionBackend(backend)
    normalized_tenant_id = normalize_uuid_string(tenant_id)
    normalized_profile_id = normalize_uuid_string(profile_id)

    engine = create_shared_engine(database_url)
    with engine.begin() as connection:
        previous = (
            connection.execute(
                select(CRAWL_PROFILES_TABLE.c.execution_backend).where(
                    and_(
                        CRAWL_PROFILES_TABLE.c.tenant_id == normalized_tenant_id,
                        CRAWL_PROFILES_TABLE.c.id == normalized_profile_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if previous is None:
            raise ValueError(
                f"profile {profile_id} does not exist for tenant {tenant_id}"
            )

        # Only jobs that have not been executed can be rerouted. A job already
        # claimed, or whose result is awaiting application, is mid-flight and
        # rewriting its backend would strand its claimant.
        reroutable = and_(
            DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
            DISCOVERY_JOBS_TABLE.c.profile_id == normalized_profile_id,
            DISCOVERY_JOBS_TABLE.c.job_status == DiscoveryJobStatus.PENDING.value,
            DISCOVERY_JOBS_TABLE.c.execution_backend != target.value,
            DISCOVERY_JOBS_TABLE.c.claim_token.is_(None),
        )
        pending_count = len(
            connection.execute(
                select(DISCOVERY_JOBS_TABLE.c.id).where(reroutable)
            ).all()
        )
        # Mid-flight rows that cannot be rerouted, reported so the operator is not
        # surprised by a keyword that stays quiet after a rollback.
        stranded_count = len(
            connection.execute(
                select(DISCOVERY_JOBS_TABLE.c.id).where(
                    and_(
                        DISCOVERY_JOBS_TABLE.c.tenant_id == normalized_tenant_id,
                        DISCOVERY_JOBS_TABLE.c.profile_id == normalized_profile_id,
                        DISCOVERY_JOBS_TABLE.c.execution_backend != target.value,
                        DISCOVERY_JOBS_TABLE.c.job_status.in_(
                            IN_FLIGHT_DISCOVERY_JOB_STATUS_VALUES
                        ),
                        DISCOVERY_JOBS_TABLE.c.claim_token.is_not(None),
                    )
                )
            ).all()
        )

        rerouted = 0
        if not dry_run:
            connection.execute(
                update(CRAWL_PROFILES_TABLE)
                .where(
                    and_(
                        CRAWL_PROFILES_TABLE.c.tenant_id == normalized_tenant_id,
                        CRAWL_PROFILES_TABLE.c.id == normalized_profile_id,
                    )
                )
                .values(execution_backend=target.value)
            )
            if reroute_pending:
                rerouted = connection.execute(
                    update(DISCOVERY_JOBS_TABLE)
                    .where(reroutable)
                    .values(execution_backend=target.value)
                ).rowcount

    return {
        "tenant_id": normalized_tenant_id,
        "profile_id": normalized_profile_id,
        "previous": str(previous),
        "current": str(previous) if dry_run else target.value,
        "changed": (not dry_run) and str(previous) != target.value,
        "dry_run": dry_run,
        "reroutable_pending_jobs": pending_count,
        "rerouted_pending_jobs": rerouted,
        "stranded_inflight_jobs": stranded_count,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument(
        "--backend", required=True, choices=[b.value for b in ExecutionBackend]
    )
    parser.add_argument(
        "--reroute-pending",
        action="store_true",
        help=(
            "Also rewrite this profile's UNCLAIMED pending jobs to the target "
            "backend. Required for a working rollback: per-job backend is "
            "immutable and the backend-agnostic dedupe blocks replacements."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required for any write. Routing a profile changes who crawls it.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.dry_run and not args.confirm:
        print(
            "refusing to change routing without --confirm (use --dry-run to preview)",
            file=sys.stderr,
        )
        return 2
    try:
        summary = set_profile_execution_backend(
            database_url=args.database_url,
            tenant_id=args.tenant_id,
            profile_id=args.profile_id,
            backend=args.backend,
            dry_run=args.dry_run,
            reroute_pending=args.reroute_pending,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    if summary["stranded_inflight_jobs"]:
        print(
            f"WARNING: {summary['stranded_inflight_jobs']} claimed/in-flight job(s) "
            "keep the previous backend and cannot be rerouted; wait for their "
            "leases to resolve before expecting this profile to be fully switched.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
