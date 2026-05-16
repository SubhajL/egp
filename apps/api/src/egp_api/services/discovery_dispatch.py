"""Durable processing for queued discovery jobs."""

from __future__ import annotations

from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        exclude_job_ids: Collection[str] | None = None,
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
    worker_count: int = 1

    def process_pending(self, *, limit: int | None = None) -> int:
        worker_count = max(1, int(self.worker_count))
        requested_limit = self.claim_limit if limit is None else max(1, int(limit))
        processed = 0
        processed_job_ids: set[str] = set()
        while processed < requested_limit:
            batch_limit = min(worker_count, requested_limit - processed)
            jobs = self.repository.claim_pending_discovery_jobs(
                limit=batch_limit,
                stale_after_seconds=self.claim_stale_after_seconds,
                exclude_job_ids=processed_job_ids,
            )
            if not jobs:
                break
            processed_job_ids.update(job.id for job in jobs)
            self._process_claimed_jobs(jobs=jobs, worker_count=worker_count)
            processed += len(jobs)
            if len(jobs) < batch_limit:
                break
        return processed

    def _process_claimed_jobs(
        self,
        *,
        jobs: list[DiscoveryJobRecord],
        worker_count: int,
    ) -> None:
        if worker_count == 1 or len(jobs) == 1:
            for job in jobs:
                self.process_job(job=job)
            return

        max_workers = min(worker_count, len(jobs))
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="egp-discovery-dispatch",
        ) as executor:
            futures = [executor.submit(self.process_job, job=job) for job in jobs]
            for future in as_completed(futures):
                future.result()

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
