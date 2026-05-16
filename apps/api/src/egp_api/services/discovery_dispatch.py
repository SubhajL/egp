"""Durable processing for queued discovery jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from egp_db.repositories.discovery_job_repo import DiscoveryJobRecord


class NonRetriableDiscoveryDispatchError(RuntimeError):
    """Raised when a discovery dispatch failure should not be retried."""


class DiscoveryJobStore(Protocol):
    def claim_pending_discovery_jobs(
        self,
        *,
        limit: int = 10,
        stale_after_seconds: float = 60.0,
    ) -> list[DiscoveryJobRecord]: ...

    def record_discovery_job_attempt(
        self,
        *,
        tenant_id: str,
        job_id: str,
        job_status: str,
        last_error: str | None = None,
        next_attempt_at: datetime | None = None,
        processing_started_at: datetime | None = None,
        dispatched: bool = False,
    ) -> DiscoveryJobRecord: ...


@dataclass(frozen=True, slots=True)
class DiscoveryDispatchRequest:
    tenant_id: str
    profile_id: str
    profile_type: str
    keyword: str


class DiscoveryDispatcher(Protocol):
    def dispatch(self, request: DiscoveryDispatchRequest) -> None: ...


@dataclass(frozen=True, slots=True)
class DiscoveryDispatchProcessor:
    repository: DiscoveryJobStore
    dispatcher: DiscoveryDispatcher
    max_attempts: int = 3
    retry_delay_seconds: float = 30.0
    claim_limit: int = 10
    claim_stale_after_seconds: float = 60.0

    def process_pending(self, *, limit: int | None = None) -> int:
        jobs = self.repository.claim_pending_discovery_jobs(
            limit=self.claim_limit if limit is None else max(1, int(limit)),
            stale_after_seconds=self.claim_stale_after_seconds,
        )
        processed = 0
        for job in jobs:
            self.process_job(job=job)
            processed += 1
        return processed

    def process_job(self, *, job: DiscoveryJobRecord) -> None:
        try:
            self.dispatcher.dispatch(
                DiscoveryDispatchRequest(
                    tenant_id=job.tenant_id,
                    profile_id=job.profile_id,
                    profile_type=job.profile_type,
                    keyword=job.keyword,
                )
            )
        except NonRetriableDiscoveryDispatchError as exc:
            self.repository.record_discovery_job_attempt(
                tenant_id=job.tenant_id,
                job_id=job.id,
                job_status="failed",
                last_error=str(exc),
                processing_started_at=None,
            )
            return
        except Exception as exc:
            next_attempt = job.attempt_count + 1
            if next_attempt >= self.max_attempts:
                self.repository.record_discovery_job_attempt(
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    job_status="failed",
                    last_error=str(exc),
                    processing_started_at=None,
                )
                return
            self.repository.record_discovery_job_attempt(
                tenant_id=job.tenant_id,
                job_id=job.id,
                job_status="pending",
                last_error=str(exc),
                next_attempt_at=datetime.now(UTC)
                + timedelta(seconds=max(0.0, self.retry_delay_seconds)),
                processing_started_at=None,
            )
            return

        self.repository.record_discovery_job_attempt(
            tenant_id=job.tenant_id,
            job_id=job.id,
            job_status="dispatched",
            last_error=None,
            processing_started_at=None,
            dispatched=True,
        )
