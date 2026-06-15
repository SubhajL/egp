"""Enqueue targeted document backfill discovery jobs."""

from __future__ import annotations

import argparse
import logging
from typing import Protocol

from egp_api.config import get_database_url
from egp_db.repositories.discovery_job_repo import create_discovery_job_repository
from egp_db.repositories.document_capture_attempt_repo import (
    DocumentCaptureBackfillCandidate,
    create_document_capture_attempt_repository,
)
from egp_shared_types.enums import DocumentCaptureAttemptStatus, DocumentCaptureReason


logger = logging.getLogger(__name__)


class _CaptureAttemptStore(Protocol):
    def list_due_backfill_candidates(self, **kwargs) -> list[DocumentCaptureBackfillCandidate]: ...

    def record_attempt(self, **kwargs): ...


class _PendingDiscoveryJobStore(Protocol):
    def create_pending_discovery_job_if_absent(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        profile_type: str,
        keyword: str,
        trigger_type: str = ...,
        live: bool = ...,
    ): ...


def enqueue_document_backfill_jobs(
    *,
    database_url: str,
    capture_attempt_repository: _CaptureAttemptStore | None = None,
    discovery_job_repository: _PendingDiscoveryJobStore | None = None,
    now=None,
    limit: int = 50,
    max_attempts: int = 3,
    base_backoff_seconds: int = 3600,
    max_backoff_seconds: int = 86400,
    enqueued_stale_after_seconds: int = 10800,
    no_documents_retry_seconds: int = 86400,
    no_documents_max_age_days: int = 30,
) -> dict[str, int]:
    """Enqueue due project-number backfill jobs for zero invitation/TOR projects."""

    capture_repository = capture_attempt_repository or create_document_capture_attempt_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    discovery_repository = discovery_job_repository or create_discovery_job_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    candidates = capture_repository.list_due_backfill_candidates(
        now=now,
        max_attempts=max_attempts,
        base_backoff_seconds=base_backoff_seconds,
        max_backoff_seconds=max_backoff_seconds,
        enqueued_stale_after_seconds=enqueued_stale_after_seconds,
        no_documents_retry_seconds=no_documents_retry_seconds,
        no_documents_max_age_days=no_documents_max_age_days,
        limit=limit,
    )
    enqueued_count = 0
    created_count = 0
    skipped_count = 0
    for candidate in candidates:
        project_number = str(candidate.project_number or "").strip()
        if not project_number:
            skipped_count += 1
            continue
        result = discovery_repository.create_pending_discovery_job_if_absent(
            tenant_id=candidate.tenant_id,
            profile_id=candidate.profile_id,
            profile_type=candidate.profile_type,
            keyword=project_number,
            trigger_type="backfill",
            live=True,
        )
        enqueued_count += 1
        if not bool(getattr(result, "created", False)):
            continue
        created_count += 1
        capture_repository.record_attempt(
            tenant_id=candidate.tenant_id,
            project_id=candidate.project_id,
            status=DocumentCaptureAttemptStatus.ENQUEUED,
            reason=DocumentCaptureReason.BACKFILL_JOB_CREATED,
            doc_count=0,
            attempted_at=now,
        )
    return {
        "candidate_count": len(candidates),
        "enqueued_count": enqueued_count,
        "created_count": created_count,
        "skipped_count": skipped_count,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enqueue targeted document backfill jobs (no browser).",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--base-backoff-seconds", type=int, default=3600)
    parser.add_argument("--max-backoff-seconds", type=int, default=86400)
    parser.add_argument("--enqueued-stale-after-seconds", type=int, default=10800)
    parser.add_argument("--no-documents-retry-seconds", type=int, default=86400)
    parser.add_argument("--no-documents-max-age-days", type=int, default=30)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    enqueue=enqueue_document_backfill_jobs,
) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    summary = enqueue(
        database_url=get_database_url(args.database_url),
        limit=args.limit,
        max_attempts=args.max_attempts,
        base_backoff_seconds=args.base_backoff_seconds,
        max_backoff_seconds=args.max_backoff_seconds,
        enqueued_stale_after_seconds=args.enqueued_stale_after_seconds,
        no_documents_retry_seconds=args.no_documents_retry_seconds,
        no_documents_max_age_days=args.no_documents_max_age_days,
    )
    logger.info(
        "Enqueued document backfill jobs (new=%d of candidates=%d, attempts=%d, skipped=%d)",
        summary["created_count"],
        summary["candidate_count"],
        summary["enqueued_count"],
        summary["skipped_count"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
