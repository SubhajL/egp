"""Durable processing for queued discovery jobs."""

from __future__ import annotations

from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import threading
import time
from typing import Callable, Protocol

from egp_db.repositories.discovery_job_repo import (
    DiscoveryJobRecord,
    DiscoveryQueueSnapshot,
    StaleDiscoveryJobClaimError,
)
from egp_shared_types.enums import CrawlerBlockerCode, DiscoveryFailureCode


class NonRetriableDiscoveryDispatchError(RuntimeError):
    """Raised when a discovery dispatch failure should not be retried."""

    def __init__(
        self,
        message: str,
        *,
        failure_code: DiscoveryFailureCode = DiscoveryFailureCode.ENTITLEMENT_DENIED,
    ) -> None:
        self.failure_code = failure_code
        super().__init__(message)


class DiscoveryJobStore(Protocol):
    def get_discovery_queue_snapshot(self) -> DiscoveryQueueSnapshot: ...

    def has_claimable_discovery_jobs(
        self,
        *,
        exclude_job_ids: Collection[str] | None = None,
    ) -> bool: ...

    def claim_pending_discovery_jobs(
        self,
        *,
        limit: int = 10,
        lease_seconds: float = 60.0,
        exclude_job_ids: Collection[str] | None = None,
    ) -> list[DiscoveryJobRecord]: ...

    def renew_discovery_job_lease(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str,
        lease_seconds: float = 60.0,
    ) -> DiscoveryJobRecord: ...

    def record_discovery_job_attempt(
        self,
        *,
        tenant_id: str,
        job_id: str,
        claim_token: str | None = None,
        job_status: str,
        last_error: str | None = None,
        last_error_code: DiscoveryFailureCode | str | None = None,
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
    trigger_type: str = "manual"
    live: bool = True
    discovery_job_id: str | None = None
    recrawl_request_id: str | None = None


class DiscoveryDispatcher(Protocol):
    def dispatch(self, request: DiscoveryDispatchRequest) -> None: ...


class DiscoveryPreDispatchPreparer(Protocol):
    def prepare_for_dispatch(self) -> DiscoveryPreDispatchResult: ...


@dataclass(frozen=True, slots=True)
class DiscoveryPreDispatchResult:
    should_dispatch: bool
    blocker: CrawlerBlockerCode | None = None
    circuit_reset_at: str | None = None

    @classmethod
    def ready(cls) -> DiscoveryPreDispatchResult:
        return cls(should_dispatch=True)

    @classmethod
    def blocked(
        cls,
        blocker: CrawlerBlockerCode,
        *,
        circuit_reset_at: str | None = None,
    ) -> DiscoveryPreDispatchResult:
        return cls(
            should_dispatch=False,
            blocker=blocker,
            circuit_reset_at=circuit_reset_at,
        )


@dataclass(frozen=True, slots=True)
class DiscoveryJobDispatchDisposition:
    job_id: str
    outcome: str
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryDispatchBatchResult:
    requested_limit: int
    dispositions: tuple[DiscoveryJobDispatchDisposition, ...]
    blocker: CrawlerBlockerCode | None = None
    circuit_reset_at: str | None = None
    queue_snapshot: DiscoveryQueueSnapshot = field(
        default_factory=DiscoveryQueueSnapshot.empty
    )

    @property
    def processed_count(self) -> int:
        return len(self.dispositions)


class DiscoveryJobLeaseKeeper:
    """Renew one claimed job while its blocking worker call is in progress."""

    def __init__(
        self,
        *,
        repository: DiscoveryJobStore,
        job: DiscoveryJobRecord,
        lease_seconds: float,
        heartbeat_seconds: float,
    ) -> None:
        self._repository = repository
        self._job = job
        self._lease_seconds = max(0.01, float(lease_seconds))
        self._heartbeat_seconds = max(0.005, float(heartbeat_seconds))
        self._stop = threading.Event()
        self._cancellation = threading.Event()
        self._thread: threading.Thread | None = None
        self._renew_error: BaseException | None = None
        self._lease_deadline = self._deadline_from_record(job)

    def __enter__(self) -> DiscoveryJobLeaseKeeper:
        if not self._job.claim_token or self._lease_deadline is None:
            raise StaleDiscoveryJobClaimError(
                f"discovery job {self._job.id} has no valid lease"
            )
        self._thread = threading.Thread(
            target=self._renew_loop,
            daemon=True,
            name=f"egp-discovery-lease-{self._job.id[:8]}",
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._heartbeat_seconds * 2))

    def ensure_owned(self) -> None:
        if self._renew_error is not None:
            raise StaleDiscoveryJobClaimError(
                f"discovery job lease renewal failed for job {self._job.id}"
            ) from self._renew_error

    @property
    def cancellation_event(self) -> threading.Event:
        return self._cancellation

    def _renew_loop(self) -> None:
        assert self._lease_deadline is not None
        while True:
            remaining_seconds = self._lease_deadline - time.monotonic()
            if remaining_seconds <= 0:
                self._mark_lost(
                    StaleDiscoveryJobClaimError(
                        f"discovery job lease expired for job {self._job.id}"
                    )
                )
                return
            if self._stop.wait(min(self._heartbeat_seconds, remaining_seconds)):
                return
            try:
                renewed = self._repository.renew_discovery_job_lease(
                    tenant_id=self._job.tenant_id,
                    job_id=self._job.id,
                    claim_token=self._job.claim_token or "",
                    lease_seconds=self._lease_seconds,
                )
            except StaleDiscoveryJobClaimError as exc:
                self._mark_lost(exc)
                return
            except Exception:
                # A transient database/network error does not prove ownership
                # was lost. Retry until the last confirmed lease expires.
                continue
            renewed_deadline = self._deadline_from_record(renewed)
            if renewed_deadline is None:
                self._mark_lost(
                    StaleDiscoveryJobClaimError(
                        f"lease renewal returned no expiry for job {self._job.id}"
                    )
                )
                return
            self._lease_deadline = renewed_deadline

    def _mark_lost(self, exc: BaseException) -> None:
        self._renew_error = exc
        self._cancellation.set()
        self._stop.set()

    @staticmethod
    def _deadline_from_record(job: DiscoveryJobRecord) -> float | None:
        raw_expiry = str(job.lease_expires_at or "").strip()
        if not raw_expiry:
            return None
        try:
            expiry = datetime.fromisoformat(raw_expiry)
        except ValueError:
            return None
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        else:
            expiry = expiry.astimezone(UTC)
        remaining_seconds = max(0.0, (expiry - datetime.now(UTC)).total_seconds())
        return time.monotonic() + remaining_seconds


@dataclass(frozen=True, slots=True)
class DiscoveryDispatchProcessor:
    repository: DiscoveryJobStore
    dispatcher: DiscoveryDispatcher
    pre_dispatch_preparer: DiscoveryPreDispatchPreparer | None = None
    max_attempts: int = 3
    retry_delay_seconds: float = 30.0
    claim_limit: int = 10
    lease_seconds: float = 60.0
    lease_heartbeat_seconds: float = 20.0
    worker_count: int = 1

    def process_pending(
        self,
        *,
        limit: int | None = None,
    ) -> DiscoveryDispatchBatchResult:
        return self._process_pending(
            limit=limit,
            on_pre_dispatch_ready=None,
        )

    def process_pending_with_observer(
        self,
        *,
        limit: int | None = None,
        on_pre_dispatch_ready: Callable[[], None],
    ) -> DiscoveryDispatchBatchResult:
        """Process jobs and notify once pre-dispatch proves the runtime ready."""

        return self._process_pending(
            limit=limit,
            on_pre_dispatch_ready=on_pre_dispatch_ready,
        )

    def _process_pending(
        self,
        *,
        limit: int | None,
        on_pre_dispatch_ready: Callable[[], None] | None,
    ) -> DiscoveryDispatchBatchResult:
        worker_count = max(1, int(self.worker_count))
        requested_limit = self.claim_limit if limit is None else max(1, int(limit))
        dispositions: list[DiscoveryJobDispatchDisposition] = []
        processed_job_ids: set[str] = set()
        blocker: CrawlerBlockerCode | None = None
        circuit_reset_at: str | None = None
        while len(dispositions) < requested_limit:
            batch_limit = min(worker_count, requested_limit - len(dispositions))
            if not self.repository.has_claimable_discovery_jobs(
                exclude_job_ids=processed_job_ids,
            ):
                break
            if self.pre_dispatch_preparer is not None:
                preparation = self.pre_dispatch_preparer.prepare_for_dispatch()
                if not preparation.should_dispatch:
                    blocker = preparation.blocker
                    circuit_reset_at = preparation.circuit_reset_at
                    break
            if on_pre_dispatch_ready is not None:
                on_pre_dispatch_ready()
            jobs = self.repository.claim_pending_discovery_jobs(
                limit=batch_limit,
                lease_seconds=self.lease_seconds,
                exclude_job_ids=processed_job_ids,
            )
            if not jobs:
                break
            processed_job_ids.update(job.id for job in jobs)
            dispositions.extend(
                self._process_claimed_jobs(jobs=jobs, worker_count=worker_count)
            )
            if len(jobs) < batch_limit:
                break
        return DiscoveryDispatchBatchResult(
            requested_limit=requested_limit,
            dispositions=tuple(dispositions),
            blocker=blocker,
            circuit_reset_at=circuit_reset_at,
            queue_snapshot=self.repository.get_discovery_queue_snapshot(),
        )

    def _process_claimed_jobs(
        self,
        *,
        jobs: list[DiscoveryJobRecord],
        worker_count: int,
    ) -> list[DiscoveryJobDispatchDisposition]:
        if worker_count == 1 or len(jobs) == 1:
            return [self.process_job(job=job) for job in jobs]

        max_workers = min(worker_count, len(jobs))
        dispositions: list[DiscoveryJobDispatchDisposition] = []
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="egp-discovery-dispatch",
        ) as executor:
            futures = [executor.submit(self.process_job, job=job) for job in jobs]
            for future in as_completed(futures):
                dispositions.append(future.result())
        return dispositions

    def process_job(
        self,
        *,
        job: DiscoveryJobRecord,
    ) -> DiscoveryJobDispatchDisposition:
        dispatch_error: Exception | None = None
        try:
            with DiscoveryJobLeaseKeeper(
                repository=self.repository,
                job=job,
                lease_seconds=self.lease_seconds,
                heartbeat_seconds=self.lease_heartbeat_seconds,
            ) as lease_keeper:
                try:
                    request = DiscoveryDispatchRequest(
                        tenant_id=job.tenant_id,
                        profile_id=job.profile_id,
                        profile_type=job.profile_type,
                        keyword=job.keyword,
                        trigger_type=job.trigger_type,
                        live=job.live,
                        discovery_job_id=job.id,
                        recrawl_request_id=job.recrawl_request_id,
                    )
                    cancellable_dispatch = getattr(
                        self.dispatcher,
                        "dispatch_cancellable",
                        None,
                    )
                    if callable(cancellable_dispatch):
                        cancellable_dispatch(
                            request,
                            cancellation_event=lease_keeper.cancellation_event,
                        )
                    else:
                        self.dispatcher.dispatch(request)
                except Exception as exc:
                    dispatch_error = exc
                lease_keeper.ensure_owned()
        except StaleDiscoveryJobClaimError:
            return DiscoveryJobDispatchDisposition(
                job_id=job.id,
                outcome="stale_claim",
                failure_code=DiscoveryFailureCode.LEASE_LOST,
            )

        if dispatch_error is None:
            return self._record_disposition(
                job=job,
                job_status="dispatched",
                outcome="dispatched",
                last_error=None,
                last_error_code=None,
                dispatched=True,
            )

        if isinstance(dispatch_error, NonRetriableDiscoveryDispatchError):
            return self._record_disposition(
                job=job,
                job_status="failed",
                outcome="failed",
                last_error=str(dispatch_error),
                last_error_code=dispatch_error.failure_code,
            )

        failure_code = getattr(
            dispatch_error,
            "failure_code",
            DiscoveryFailureCode.DISPATCH_EXCEPTION,
        )
        next_attempt = job.attempt_count + 1
        if next_attempt >= self.max_attempts:
            return self._record_disposition(
                job=job,
                job_status="failed",
                outcome="failed",
                last_error=str(dispatch_error),
                last_error_code=failure_code,
            )
        return self._record_disposition(
            job=job,
            job_status="pending",
            outcome="retrying",
            last_error=str(dispatch_error),
            last_error_code=failure_code,
            next_attempt_at=datetime.now(UTC)
            + timedelta(seconds=max(0.0, self.retry_delay_seconds)),
        )

    def _record_disposition(
        self,
        *,
        job: DiscoveryJobRecord,
        job_status: str,
        outcome: str,
        last_error: str | None,
        last_error_code: DiscoveryFailureCode | str | None,
        next_attempt_at: datetime | None = None,
        dispatched: bool = False,
    ) -> DiscoveryJobDispatchDisposition:
        try:
            self.repository.record_discovery_job_attempt(
                tenant_id=job.tenant_id,
                job_id=job.id,
                claim_token=job.claim_token,
                job_status=job_status,
                last_error=last_error,
                last_error_code=last_error_code,
                next_attempt_at=next_attempt_at,
                processing_started_at=None,
                dispatched=dispatched,
            )
        except StaleDiscoveryJobClaimError:
            return DiscoveryJobDispatchDisposition(
                job_id=job.id,
                outcome="stale_claim",
                failure_code=DiscoveryFailureCode.LEASE_LOST,
            )
        return DiscoveryJobDispatchDisposition(
            job_id=job.id,
            outcome=outcome,
            failure_code=(
                last_error_code.value
                if isinstance(last_error_code, DiscoveryFailureCode)
                else last_error_code
            ),
        )
