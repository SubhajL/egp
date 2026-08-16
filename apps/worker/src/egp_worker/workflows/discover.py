"""Event-emitting discover workflow extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from egp_crawler_core.discovery_authorization import (
    DiscoveryAuthorizationError,
    DiscoveryAuthorizationSnapshot,
    ProfileKeywordCandidate,
    build_discovery_authorization_snapshot,
    require_discovery_authorization,
)
from egp_crawler_core.candidate_key import compute_candidate_key
from egp_crawler_core.invitation_rules import is_discoverable_stage_status
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.abnormal_run_completion import complete_abnormal_run
from egp_db.onedrive import OneDriveOAuthConfig
from egp_db.repositories.candidate_attempt_repo import (
    CandidateTerminalConflictError,
    SqlCandidateAttemptRepository,
    create_candidate_attempt_repository,
)
from egp_db.repositories.document_capture_attempt_repo import (
    SqlDocumentCaptureAttemptRepository,
    create_document_capture_attempt_repository,
)
from egp_db.repositories.billing_repo import create_billing_repository
from egp_db.repositories.profile_repo import create_profile_repository
from egp_db.repositories.project_repo import ProjectRecord, SqlProjectRepository
from egp_db.repositories.run_repo import CrawlRunDetail, SqlRunRepository, create_run_repository
from egp_shared_types.project_events import DiscoveredProjectEvent
from egp_shared_types.enums import (
    CandidateTerminalReason,
    CrawlOutcomeReason,
    DiscoveryFailureCode,
    DocumentCaptureAttemptStatus,
    DocumentCaptureReason,
)
from egp_worker.browser_downloads import ingest_downloaded_documents
from egp_worker.browser_discovery import (
    BrowserDiscoverySettings,
    LiveDiscoveryPartialError,
    SearchPageStateError,
    crawl_live_discovery,
)
from egp_worker.json_safety import make_json_safe
from egp_worker.project_event_sink import (
    ProjectEventSink,
    create_project_event_sink,
    create_service_backed_project_event_sink_from_repository,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from egp_notifications.dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiscoverWorkflowResult:
    run: CrawlRunDetail
    projects: list[ProjectRecord]


LIVE_DOCUMENT_COLLECTION_STATUS = "deferred"
LIVE_DOCUMENT_COLLECTION_REASON = "live_discovery_metadata_first"
_LIVE_CRAWL_ALWAYS_ANOMALY_STAGES = frozenset(
    {
        "project_detail_invalid",
        "project_detail_missing_required_fields",
    }
)
_LIVE_CRAWL_TERMINAL_ANOMALY_STAGES = frozenset({"keyword_no_results"})
_KEYWORD_SCAN_SUMMARY_STAGE = "keyword_scan_summary"
_BACKFILL_TRIGGER_TYPE = "backfill"


def _log_candidate_terminal_conflict(
    *,
    tenant_id: str,
    run_id: str,
    conflict: CandidateTerminalConflictError,
) -> None:
    """Emit the distinct structured event for a contradictory finalize (F6/R11).

    Fail-open by design: the caller continues after logging. Making the
    conflict block or fail the run is F4's run-authority charter.
    """
    logger.error(
        "Candidate terminal conflict for %s",
        conflict.candidate_key,
        extra={
            "egp_event": "candidate_terminal_conflict",
            "tenant_id": tenant_id,
            "run_id": run_id,
            "candidate_key": conflict.candidate_key,
            "existing_status": conflict.existing_status,
            "existing_reason": conflict.existing_reason,
            "existing_project_id": conflict.existing_project_id,
            "requested_status": conflict.requested_status,
            "requested_reason": conflict.requested_reason,
            "requested_project_id": conflict.requested_project_id,
        },
    )


def _keyword_scan_is_canary_anomaly(event: dict[str, object]) -> bool:
    """True for a keyword_scan_summary that scanned rows but found none eligible.

    This is the WS2 canary: silent discovery misses (the column-drift failure
    mode) surface as a non-terminal anomaly instead of a plain `succeeded` run.
    Header-signature drift is deliberately NOT treated as a run-failing anomaly —
    WS1 made columns header-derived, so drift is an informational early warning.
    """
    if str(event.get("stage") or "") != _KEYWORD_SCAN_SUMMARY_STAGE:
        return False
    return str(event.get("reason_code") or "") == CrawlOutcomeReason.NO_ELIGIBLE_ROWS


def _load_discovery_authorization_snapshot(
    *, database_url: str, tenant_id: str
) -> DiscoveryAuthorizationSnapshot:
    billing_repository = create_billing_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    profile_repository = create_profile_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    subscriptions = billing_repository.list_subscriptions_for_tenant(tenant_id=tenant_id)
    profile_details = profile_repository.list_profiles_with_keywords(tenant_id=tenant_id)
    return build_discovery_authorization_snapshot(
        subscriptions=subscriptions,
        profiles=[
            ProfileKeywordCandidate(
                profile_id=detail.profile.id,
                profile_type=detail.profile.profile_type,
                enabled_by_user=detail.profile.enabled_by_user,
                created_at=detail.profile.created_at,
                keywords=[keyword.keyword for keyword in detail.keywords],
            )
            for detail in profile_details
        ],
    )


def _is_backfill_trigger(trigger_type: str | None) -> bool:
    return str(trigger_type or "").strip().lower() == _BACKFILL_TRIGGER_TYPE


def _require_backfill_authorization(snapshot: DiscoveryAuthorizationSnapshot) -> None:
    if not snapshot.has_active_subscription:
        raise DiscoveryAuthorizationError("active subscription required for runs")
    if snapshot.over_keyword_limit:
        raise DiscoveryAuthorizationError("active keyword configuration exceeds plan limit")


def _backfill_project_id_for_keyword(
    *,
    database_url: str | None,
    tenant_id: str,
    keyword: str,
    capture_attempt_repository: SqlDocumentCaptureAttemptRepository | None = None,
) -> str | None:
    if database_url is None:
        return None
    repository = capture_attempt_repository or create_document_capture_attempt_repository(
        database_url=database_url,
        bootstrap_schema=False,
    )
    return repository.find_project_by_number(tenant_id=tenant_id, project_number=keyword)


def _authorize_discovery_request(
    *,
    snapshot: DiscoveryAuthorizationSnapshot,
    database_url: str | None,
    tenant_id: str,
    profile_id: str | None,
    keyword: str,
    trigger_type: str,
) -> None:
    if _is_backfill_trigger(trigger_type) and _backfill_project_id_for_keyword(
        database_url=database_url,
        tenant_id=tenant_id,
        keyword=keyword,
    ):
        _require_backfill_authorization(snapshot)
        return
    require_discovery_authorization(
        snapshot=snapshot,
        keyword=keyword,
        profile_id=profile_id,
    )


def _task_safe_payload(discovered: dict[str, object]) -> dict[str, object]:
    safe_payload = make_json_safe(discovered)
    if not isinstance(safe_payload, dict):
        return {"value": safe_payload}
    downloaded_documents = list(discovered.get("downloaded_documents") or [])
    if downloaded_documents:
        safe_payload["downloaded_documents"] = [
            {
                "file_name": str(document.get("file_name") or ""),
                "source_label": str(document.get("source_label") or ""),
                "source_status_text": str(document.get("source_status_text") or ""),
                "source_page_text": str(document.get("source_page_text") or ""),
                "project_state": (
                    str(document["project_state"])
                    if document.get("project_state") is not None
                    else None
                ),
            }
            for document in downloaded_documents
        ]
    return safe_payload


def _mark_live_document_collection_deferred(
    discovered: dict[str, object],
) -> dict[str, object]:
    marked = dict(discovered)
    marked.setdefault("downloaded_documents", [])
    marked["document_collection_status"] = LIVE_DOCUMENT_COLLECTION_STATUS
    marked["document_collection_reason"] = LIVE_DOCUMENT_COLLECTION_REASON
    raw_snapshot = marked.get("raw_snapshot")
    if isinstance(raw_snapshot, dict):
        marked["raw_snapshot"] = {
            **raw_snapshot,
            "document_collection_status": LIVE_DOCUMENT_COLLECTION_STATUS,
            "document_collection_reason": LIVE_DOCUMENT_COLLECTION_REASON,
        }
    return marked


def _snapshot_live_progress_event(event: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in event.items()
        if value is not None and not (isinstance(value, str) and not value.strip())
    }


def _live_progress_is_crawl_anomaly(event: dict[str, object]) -> bool:
    if str(event.get("stage") or "") in _LIVE_CRAWL_ALWAYS_ANOMALY_STAGES:
        return True
    return _keyword_scan_is_canary_anomaly(event)


def _live_progress_is_terminal_crawl_anomaly(event: dict[str, object]) -> bool:
    return str(event.get("stage") or "") in _LIVE_CRAWL_TERMINAL_ANOMALY_STAGES


def _build_live_crawl_anomaly_error(latest_anomaly: dict[str, object]) -> str:
    stage = str(latest_anomaly.get("stage") or "unknown")
    if stage == _KEYWORD_SCAN_SUMMARY_STAGE:
        reason = str(latest_anomaly.get("reason_code") or stage)
        return f"live crawl anomaly: {reason}"
    return f"live crawl anomaly: {stage}"


def _live_crawl_anomaly_failure_code(
    latest_anomaly: dict[str, object],
) -> DiscoveryFailureCode:
    raw_code = str(
        latest_anomaly.get("reason_code")
        or latest_anomaly.get("stage")
        or DiscoveryFailureCode.WORKER_REPORTED_FAILURE
    )
    try:
        return DiscoveryFailureCode(raw_code)
    except ValueError:
        return DiscoveryFailureCode.WORKER_REPORTED_FAILURE


def _build_discover_task_failure_result(
    *,
    exc: Exception,
    artifact_root: Path | str,
    run_id: str,
    task_keyword: str,
    project_key: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "artifact_root": str(artifact_root),
        "error": str(exc),
        "error_type": exc.__class__.__name__,
        "project_key": project_key,
        "run_id": run_id,
        "task_keyword": task_keyword,
    }
    for field_name in (
        "document_id",
        "storage_key",
        "managed_backup_storage_key",
        "provider",
    ):
        field_value = getattr(exc, field_name, None)
        if field_value is not None:
            result[field_name] = field_value
    return result


def _document_capture_attempt_status_for_payload(
    *,
    discovered: dict[str, object],
    downloaded_documents: list[object],
    failed: bool = False,
) -> DocumentCaptureAttemptStatus:
    if failed:
        return DocumentCaptureAttemptStatus.FAILED
    collection_status = str(discovered.get("document_collection_status") or "").strip()
    if collection_status == "timeout":
        return DocumentCaptureAttemptStatus.TIMEOUT
    if collection_status == "failed":
        return DocumentCaptureAttemptStatus.FAILED
    if downloaded_documents:
        return DocumentCaptureAttemptStatus.SUCCEEDED
    return DocumentCaptureAttemptStatus.NO_DOCUMENTS


# Map worker-internal collection reasons to structured capture reason codes
# (WS3 arch#3). The raw exception text is intentionally NOT used as the reason
# (unbounded cardinality) — failure detail lives in the task/run result_json.
_COLLECTION_REASON_TO_CAPTURE_REASON: dict[str, DocumentCaptureReason] = {
    "document_collection_empty": DocumentCaptureReason.NO_DOCUMENTS,
    "document_collection_timeout": DocumentCaptureReason.TIMEOUT,
    "document_collection_failed": DocumentCaptureReason.FAILED,
    DocumentCaptureReason.LIVE_DISCOVERY_METADATA_FIRST.value: (
        DocumentCaptureReason.LIVE_DISCOVERY_METADATA_FIRST
    ),
}


def _document_capture_attempt_reason_for_payload(
    *,
    discovered: dict[str, object],
    failed_error: str | None = None,
) -> str | None:
    if failed_error:
        return DocumentCaptureReason.FAILED.value
    collection_status = str(discovered.get("document_collection_status") or "").strip()
    if collection_status == "timeout":
        return DocumentCaptureReason.TIMEOUT.value
    if collection_status == "failed":
        return DocumentCaptureReason.FAILED.value
    raw_reason = str(discovered.get("document_collection_reason") or "").strip()
    mapped = _COLLECTION_REASON_TO_CAPTURE_REASON.get(raw_reason)
    if mapped is not None:
        return mapped.value
    if list(discovered.get("downloaded_documents") or []):
        return None
    return DocumentCaptureReason.NO_DOCUMENTS.value


def run_discover_workflow(
    *,
    tenant_id: str,
    run_id: str | None = None,
    profile_id: str | None = None,
    keyword: str,
    discovered_projects: list[dict[str, object]],
    trigger_type: str = "manual",
    database_url: str | None = None,
    run_repository: SqlRunRepository | None = None,
    project_repository: SqlProjectRepository | None = None,
    project_event_sink: ProjectEventSink | None = None,
    notification_dispatcher: NotificationDispatcher | None = None,
    candidate_attempt_repo: SqlCandidateAttemptRepository | None = None,
    live: bool = False,
    profile: str | None = None,
    live_discovery: Callable[[str], list[dict[str, object]]] | None = None,
    browser_settings: BrowserDiscoverySettings | None = None,
    live_include_documents: bool = True,
    artifact_root: Path | str = Path("artifacts"),
    artifact_storage_backend: str = "local",
    artifact_bucket: str | None = None,
    artifact_prefix: str = "",
    supabase_url: str | None = None,
    supabase_service_role_key: str | None = None,
    storage_credentials_secret: str | None = None,
    google_drive_oauth_config: GoogleDriveOAuthConfig | None = None,
    google_drive_client: object | None = None,
    onedrive_oauth_config: OneDriveOAuthConfig | None = None,
    onedrive_client: object | None = None,
) -> DiscoverWorkflowResult:
    authorization_snapshot: DiscoveryAuthorizationSnapshot | None = None
    if database_url is not None:
        authorization_snapshot = _load_discovery_authorization_snapshot(
            database_url=database_url,
            tenant_id=tenant_id,
        )
        _authorize_discovery_request(
            snapshot=authorization_snapshot,
            database_url=database_url,
            tenant_id=tenant_id,
            profile_id=profile_id,
            keyword=keyword,
            trigger_type=trigger_type,
        )
    if run_repository is None:
        if database_url is None:
            raise ValueError("database_url is required when repositories are not provided")
        run_repository = create_run_repository(database_url=database_url)
    if project_event_sink is None:
        if project_repository is not None:
            project_event_sink = create_service_backed_project_event_sink_from_repository(
                repository=project_repository,
                notification_dispatcher=notification_dispatcher,
            )
        elif database_url is None:
            raise ValueError("database_url is required when project_event_sink is not provided")
        else:
            project_event_sink = create_project_event_sink(
                database_url=database_url,
                notification_dispatcher=notification_dispatcher,
            )
    if run_id is None:
        run = run_repository.create_run(
            tenant_id=tenant_id,
            trigger_type=trigger_type,
            profile_id=profile_id,
        )
        run = run_repository.mark_run_started(run.id)
    else:
        run = run_repository.mark_run_started(run_id)
    if candidate_attempt_repo is None and database_url is not None:
        try:
            UUID(str(run.id))
        except ValueError:
            # Custom/in-memory repositories may use non-durable test ids. They
            # cannot participate in the SQL candidate ledger.
            pass
        else:
            candidate_attempt_repo = create_candidate_attempt_repository(
                database_url=database_url,
                bootstrap_schema=False,
            )
    persisted_projects: list[ProjectRecord] = []
    persisted_project_keys: set[str] = set()
    ignored_late_stage_projects = 0
    error_count = 0
    run_level_error: str | None = None
    run_failure_code: DiscoveryFailureCode | None = None
    live_progress: dict[str, object] | None = None
    live_crawl_anomaly_count = 0
    live_crawl_latest_anomaly: dict[str, object] | None = None
    keyword_scans: dict[str, dict[str, object]] = {}
    backfill_recorded_project_ids: set[str] = set()
    project_task_count = 0
    keyword_task_creation_blocked = False
    finalization_error_count = 0
    conflict_count = 0
    candidate_ledger: dict[str, object] | None = None

    def _finalize_candidate(
        *,
        candidate_key: str | None,
        status: str,
        terminal_reason: CandidateTerminalReason | None = None,
        terminal_detail: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """Finalize one accepted candidate and retain authority failures for publication."""
        nonlocal conflict_count, finalization_error_count
        if candidate_attempt_repo is None or candidate_key is None:
            return True
        try:
            if status == "persisted":
                if project_id is None:
                    raise ValueError("persisted candidate finalization requires project_id")
                result = candidate_attempt_repo.finalize_persisted(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    candidate_key=candidate_key,
                    project_id=project_id,
                )
            elif status == "failed":
                if terminal_reason is None:
                    raise ValueError("failed candidate finalization requires terminal_reason")
                result = candidate_attempt_repo.finalize_failed(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    candidate_key=candidate_key,
                    terminal_reason=terminal_reason.value,
                    terminal_detail=terminal_detail,
                )
            elif status == "dropped":
                if terminal_reason is None:
                    raise ValueError("dropped candidate finalization requires terminal_reason")
                result = candidate_attempt_repo.finalize_dropped(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    candidate_key=candidate_key,
                    terminal_reason=terminal_reason.value,
                    terminal_detail=terminal_detail,
                )
            else:
                raise ValueError(f"unsupported candidate terminal status {status!r}")
            if result is None:
                finalization_error_count += 1
                logger.error(
                    "Candidate terminal finalization returned no record for %s",
                    candidate_key,
                    extra={
                        "egp_event": "candidate_terminal_finalization_error",
                        "tenant_id": tenant_id,
                        "run_id": run.id,
                        "candidate_key": candidate_key,
                        "requested_status": status,
                    },
                )
                return False
            return True
        except CandidateTerminalConflictError as conflict:
            conflict_count += 1
            _log_candidate_terminal_conflict(tenant_id=tenant_id, run_id=run.id, conflict=conflict)
            return False
        except Exception:
            finalization_error_count += 1
            logger.warning(
                "Failed to finalize candidate attempt as %s for %s",
                status,
                candidate_key,
                exc_info=True,
            )
            return False

    def _apply_candidate_ledger_authority() -> tuple[bool, bool]:
        """Return (force_failed, partial) after the durable ledger is re-read."""
        nonlocal candidate_ledger
        if candidate_attempt_repo is None:
            return False, False

        accepted_before = 0
        accepted_after = 0
        reconciled_count = 0
        summary = None
        authority_error_type: str | None = None
        try:
            summary = candidate_attempt_repo.get_run_candidate_summary(
                tenant_id=tenant_id,
                run_id=run.id,
            )
            accepted_before = summary.accepted
        except Exception as exc:
            authority_error_type = exc.__class__.__name__

        if authority_error_type is None and accepted_before > 0:
            try:
                reconciled_count = candidate_attempt_repo.reconcile_open_candidates(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    terminal_reason=CandidateTerminalReason.UNCLASSIFIED.value,
                )
                summary = candidate_attempt_repo.get_run_candidate_summary(
                    tenant_id=tenant_id,
                    run_id=run.id,
                )
                accepted_after = summary.accepted
            except Exception as exc:
                authority_error_type = exc.__class__.__name__
        elif summary is not None:
            accepted_after = summary.accepted

        counts = {
            "accepted": summary.accepted if summary is not None else 0,
            "persisted": summary.persisted if summary is not None else 0,
            "dropped": summary.dropped if summary is not None else 0,
            "failed": summary.failed if summary is not None else 0,
            "unknown": summary.unknown if summary is not None else 0,
            "total": summary.total if summary is not None else 0,
        }
        authority = "complete"
        force_failed = False
        partial = False
        if authority_error_type is not None:
            authority = "unavailable"
            force_failed = True
        elif finalization_error_count:
            authority = "finalization_error"
            force_failed = True
        elif conflict_count:
            authority = "terminal_conflict"
            force_failed = True
        elif accepted_before:
            # Reconciliation turns openings into unknown evidence, never success.
            authority = "reconciled_incomplete"
            force_failed = True
        elif accepted_after:
            authority = "open_candidates"
            force_failed = True
        elif counts["failed"] or counts["unknown"]:
            authority = "incomplete"
            partial = bool(counts["persisted"])
            force_failed = not partial

        candidate_ledger = {
            "authority": authority,
            "accepted_before_reconciliation": accepted_before,
            "accepted_after_reconciliation": accepted_after,
            "reconciled_count": reconciled_count,
            "finalization_error_count": finalization_error_count,
            "conflict_count": conflict_count,
            "counts": counts,
        }
        if authority_error_type is not None:
            candidate_ledger["authority_error_type"] = authority_error_type
        return force_failed, partial

    def _current_summary() -> dict[str, object]:
        summary: dict[str, object] = {"projects_seen": len(persisted_projects)}
        if ignored_late_stage_projects:
            summary["ignored_late_stage_projects"] = ignored_late_stage_projects
        if live_progress is not None:
            summary["live_progress"] = live_progress
        if live_crawl_anomaly_count:
            summary["live_crawl_anomaly_count"] = live_crawl_anomaly_count
        if live_crawl_latest_anomaly is not None:
            summary["live_crawl_latest_anomaly"] = live_crawl_latest_anomaly
        if keyword_scans:
            summary["keyword_scans"] = {name: dict(scan) for name, scan in keyword_scans.items()}
        if candidate_ledger is not None:
            summary["candidate_ledger"] = dict(candidate_ledger)
        return summary

    def _record_keyword_scan(event_snapshot: dict[str, object]) -> None:
        scan_keyword = str(event_snapshot.get("keyword") or keyword)
        keyword_scans[scan_keyword] = {
            key: value for key, value in event_snapshot.items() if key not in ("stage", "keyword")
        }
        if event_snapshot.get("header_signature_drift"):
            logger.warning(
                "Results-table header signature drift detected for keyword %s",
                scan_keyword,
                extra={
                    "egp_event": "results_header_signature_drift",
                    "tenant_id": tenant_id,
                    "keyword": scan_keyword,
                    "header_signature": event_snapshot.get("header_signature"),
                },
            )

    def _record_live_progress(event: dict[str, object]) -> None:
        nonlocal live_crawl_anomaly_count, live_crawl_latest_anomaly, live_progress
        event_snapshot = _snapshot_live_progress_event(event)
        live_progress = {
            **event_snapshot,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if str(event_snapshot.get("stage") or "") == _KEYWORD_SCAN_SUMMARY_STAGE:
            _record_keyword_scan(event_snapshot)
        if _live_progress_is_crawl_anomaly(event_snapshot):
            live_crawl_anomaly_count += 1
            live_crawl_latest_anomaly = event_snapshot
        run_repository.update_run_summary(run.id, summary_json=_current_summary())

    def _record_keyword_run_task(
        *,
        task_status: str,
        result_json: dict[str, object],
    ) -> None:
        task = run_repository.create_task(
            run_id=run.id,
            task_type="discover",
            keyword=keyword,
            payload={
                "keyword": keyword,
                "source": "keyword_run",
            },
        )
        run_repository.mark_task_started(task.id)
        run_repository.mark_task_finished(
            task.id,
            status=task_status,
            result_json=result_json,
        )

    def _discovered_project_key(discovered: dict[str, object]) -> str:
        return str(discovered.get("project_number") or discovered["project_name"]).casefold()

    def _record_backfill_capture_attempt(
        *,
        project_id: str,
        discovered: dict[str, object],
        downloaded_documents: list[object],
        failed: bool = False,
        failed_error: str | None = None,
    ) -> None:
        if not _is_backfill_trigger(trigger_type) or database_url is None:
            return
        repository = create_document_capture_attempt_repository(
            database_url=database_url,
            bootstrap_schema=False,
        )
        status = _document_capture_attempt_status_for_payload(
            discovered=discovered,
            downloaded_documents=downloaded_documents,
            failed=failed,
        )
        repository.record_attempt(
            tenant_id=tenant_id,
            project_id=project_id,
            run_id=run.id,
            status=status,
            reason=_document_capture_attempt_reason_for_payload(
                discovered=discovered,
                failed_error=failed_error,
            ),
            doc_count=len(downloaded_documents),
        )
        backfill_recorded_project_ids.add(project_id)

    def _persist_discovered_project(
        discovered: dict[str, object], *, candidate_key: str | None = None
    ) -> ProjectRecord | None:
        nonlocal error_count, ignored_late_stage_projects, keyword_task_creation_blocked
        nonlocal project_task_count, run_failure_code, run_level_error
        # F2: the authoritative pre-detail candidate key arrives ONLY via the
        # `candidate_key` parameter (set by the live browser path). Any candidate_key
        # FIELD carried in the payload is untrusted — pop it so it can neither leak
        # into the product task payload / event snapshot (worker/product boundary)
        # nor spoof prior acceptance on the direct/materialized path.
        discovered.pop("candidate_key", None)
        candidate_key_value: str | None = candidate_key
        source_status_text = str(discovered.get("source_status_text") or "")
        if not is_discoverable_stage_status(source_status_text):
            _finalize_candidate(
                candidate_key=candidate_key_value,
                status="dropped",
                terminal_reason=CandidateTerminalReason.LATE_STAGE,
            )
            ignored_late_stage_projects += 1
            logger.info(
                "Ignored discovery payload outside invitation stage for %s",
                discovered.get("project_number") or discovered.get("project_name"),
                extra={
                    "egp_event": "late_stage_discovery_ignored",
                    "tenant_id": tenant_id,
                    "keyword": str(discovered.get("keyword") or keyword),
                    "project_number": discovered.get("project_number"),
                    "project_name": discovered.get("project_name"),
                    "source_status_text": source_status_text,
                },
            )
            return None
        project_key = _discovered_project_key(discovered)
        if project_key in persisted_project_keys:
            _finalize_candidate(
                candidate_key=candidate_key_value,
                status="dropped",
                terminal_reason=CandidateTerminalReason.DUPLICATE_IN_RUN,
            )
            return None
        task_keyword = str(discovered.get("keyword") or keyword)
        safe_discovered = _task_safe_payload(discovered)
        task = None
        project: ProjectRecord | None = None
        if authorization_snapshot is not None:
            _authorize_discovery_request(
                snapshot=authorization_snapshot,
                database_url=database_url,
                tenant_id=tenant_id,
                profile_id=profile_id,
                keyword=task_keyword,
                trigger_type=trigger_type,
            )
        # -- candidate accounting: record acceptance before persistence --
        # Live browser rows already recorded acceptance pre-detail (candidate_key
        # threaded + popped above). Only the direct / materialized-payload path,
        # which has no detail-loss gap, records acceptance here.
        # F6/identity: content-based key (number, else the contracted direct
        # payload fields name+org+status). Browser-only budget_text is not
        # fabricated here. Coordinates are stored only when the payload really
        # carries them — never fabricated as 0,0.
        if candidate_key_value is None and candidate_attempt_repo is not None:
            page_num = discovered.get("page_number")
            row_ord = discovered.get("row_ordinal")
            direct_number_value = discovered.get("project_number")
            direct_number = str(direct_number_value) if direct_number_value else None
            candidate_key_value = compute_candidate_key(
                keyword=task_keyword,
                project_name=str(discovered.get("project_name") or ""),
                project_number=direct_number,
                organization_name=str(discovered.get("organization_name") or ""),
                source_status_text=str(discovered.get("source_status_text") or ""),
            )
            candidate_attempt_repo.record_accepted(
                tenant_id=tenant_id,
                run_id=run.id,
                candidate_key=candidate_key_value,
                keyword=task_keyword,
                page_number=int(page_num) if page_num is not None else None,
                row_ordinal=int(row_ord) if row_ord is not None else None,
                project_number=direct_number,
            )
        try:
            task = run_repository.create_task(
                run_id=run.id,
                task_type="discover",
                keyword=task_keyword,
                payload=safe_discovered,
            )
            project_task_count += 1
            run_repository.mark_task_started(task.id)
            event = DiscoveredProjectEvent(
                tenant_id=tenant_id,
                keyword=task_keyword,
                project_number=discovered.get("project_number"),
                search_name=discovered.get("search_name"),
                detail_name=discovered.get("detail_name"),
                project_name=str(discovered["project_name"]),
                organization_name=str(discovered["organization_name"]),
                proposal_submission_date=discovered.get("proposal_submission_date"),
                budget_amount=discovered.get("budget_amount"),
                procurement_type=discovered.get("procurement_type"),
                project_state=discovered.get("project_state", "discovered"),
                run_id=run.id,
                source_status_text=str(discovered.get("source_status_text") or ""),
                raw_snapshot=safe_discovered,
            )
            project = project_event_sink.record_discovery(event)
            downloaded_documents = list(discovered.get("downloaded_documents") or [])
            if downloaded_documents:
                logger.info(
                    "Project document ingest started for %s",
                    project.id,
                    extra={
                        "egp_event": "project_document_ingest_started",
                        "tenant_id": tenant_id,
                        "project_id": project.id,
                        "task_id": task.id,
                        "keyword": task_keyword,
                        "project_key": project_key,
                        "document_count": len(downloaded_documents),
                    },
                )
                ingest_downloaded_documents(
                    artifact_root=artifact_root,
                    database_url=database_url,
                    artifact_storage_backend=artifact_storage_backend,
                    artifact_bucket=artifact_bucket,
                    artifact_prefix=artifact_prefix,
                    supabase_url=supabase_url,
                    supabase_service_role_key=supabase_service_role_key,
                    storage_credentials_secret=storage_credentials_secret,
                    google_drive_oauth_config=google_drive_oauth_config,
                    google_drive_client=google_drive_client,
                    onedrive_oauth_config=onedrive_oauth_config,
                    onedrive_client=onedrive_client,
                    tenant_id=tenant_id,
                    project_id=project.id,
                    downloaded_documents=downloaded_documents,
                )
            _record_backfill_capture_attempt(
                project_id=project.id,
                discovered=discovered,
                downloaded_documents=downloaded_documents,
            )
            run_repository.mark_task_finished(
                task.id, status="succeeded", result_json={"project_id": project.id}
            )
            _finalize_candidate(
                candidate_key=candidate_key_value,
                status="persisted",
                project_id=project.id,
            )
            persisted_project_keys.add(project_key)
            persisted_projects.append(project)
            run_repository.update_run_summary(run.id, summary_json=_current_summary())
            return project
        except Exception as exc:
            error_count += 1
            # F6/R5: typed reason; the raw exception text is diagnostics and
            # lives in terminal_detail, never in terminal_reason.
            _finalize_candidate(
                candidate_key=candidate_key_value,
                status="failed",
                terminal_reason=CandidateTerminalReason.PERSIST_ERROR,
                terminal_detail=str(exc)[:500],
            )
            if project is not None and project.id not in backfill_recorded_project_ids:
                try:
                    _record_backfill_capture_attempt(
                        project_id=project.id,
                        discovered=discovered,
                        downloaded_documents=list(discovered.get("downloaded_documents") or []),
                        failed=True,
                        failed_error=str(exc),
                    )
                except Exception:
                    logger.warning(
                        "Failed to record document backfill capture failure for %s",
                        project.id,
                        exc_info=True,
                    )
            logger.exception(
                "Project persistence failed for %s",
                project_key,
                extra={
                    "egp_event": "project_document_ingest_failed",
                    "tenant_id": tenant_id,
                    "task_id": task.id if task is not None else None,
                    "keyword": task_keyword,
                    "project_key": project_key,
                    "document_count": len(discovered.get("downloaded_documents") or []),
                },
            )
            if task is not None:
                run_repository.mark_task_finished(
                    task.id,
                    status="failed",
                    result_json=_build_discover_task_failure_result(
                        exc=exc,
                        artifact_root=artifact_root,
                        run_id=run.id,
                        task_keyword=task_keyword,
                        project_key=project_key,
                    ),
                )
            else:
                run_level_error = str(exc)
                run_failure_code = DiscoveryFailureCode.WORKER_REPORTED_FAILURE
                keyword_task_creation_blocked = True
            return None

    try:
        resolved_projects = list(discovered_projects)
        if live_discovery is not None and not resolved_projects:
            resolved_projects = list(live_discovery(keyword))
        elif live:

            def _persist_live_project(discovered: dict[str, object]) -> None:
                live_project = (
                    discovered
                    if live_include_documents
                    else _mark_live_document_collection_deferred(discovered)
                )
                # F2: hand the browser-threaded candidate key to the persister with
                # provenance (a parameter), never as a trusted payload field.
                threaded_key = live_project.pop("candidate_key", None)
                _persist_discovered_project(
                    live_project,
                    candidate_key=str(threaded_key) if threaded_key is not None else None,
                )

            def _record_live_candidate(candidate_info: dict[str, object]) -> str | None:
                # F2: durable pre-detail candidate acceptance. Invoked for each
                # eligible row BEFORE detail navigation; raising stops the crawl
                # (fail-closed). Run-level authorization already gated browser
                # traffic at workflow entry, so no per-keyword re-authorization here.
                # F6/identity: the key is CONTENT-based (project number, else
                # name+organization from the row marker) so a browser-death
                # resume re-scan is idempotent instead of orphaning a second
                # position-keyed row; page/ordinal are stored as provenance only.
                if candidate_attempt_repo is None:
                    return None
                candidate_keyword = str(candidate_info.get("keyword") or keyword)
                page_number = candidate_info.get("page_number")
                eligible_ordinal = candidate_info.get("eligible_ordinal")
                marker = candidate_info.get("row_marker")
                marker_dict = marker if isinstance(marker, dict) else None
                project_number_value = candidate_info.get("project_number")
                project_number = str(project_number_value) if project_number_value else None
                candidate_key = compute_candidate_key(
                    keyword=candidate_keyword,
                    project_name=str(candidate_info.get("project_name") or ""),
                    project_number=project_number,
                    organization_name=str((marker_dict or {}).get("organization_name") or ""),
                    budget_text=str((marker_dict or {}).get("budget_text") or ""),
                    source_status_text=str(
                        (marker_dict or {}).get("source_status_text")
                        or candidate_info.get("source_status_text")
                        or ""
                    ),
                )
                candidate_attempt_repo.record_accepted(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    candidate_key=candidate_key,
                    keyword=candidate_keyword,
                    page_number=int(page_number) if page_number is not None else None,
                    row_ordinal=int(eligible_ordinal) if eligible_ordinal is not None else None,
                    project_number=project_number,
                    row_marker=(
                        json.dumps(
                            marker_dict,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if marker_dict is not None
                        else None
                    ),
                )
                return candidate_key

            def _record_live_candidate_terminal(
                candidate_key: str,
                status: str,
                terminal_reason: str,
            ) -> None:
                """Close a browser-terminal row against its pre-detail key."""
                try:
                    reason = CandidateTerminalReason(terminal_reason)
                except ValueError:
                    # This is an internal browser/workflow contract violation. Route
                    # it through the central finalizer so publication fails closed.
                    _finalize_candidate(
                        candidate_key=candidate_key,
                        status=status,
                        terminal_reason=None,
                    )
                    return
                _finalize_candidate(
                    candidate_key=candidate_key,
                    status=status,
                    terminal_reason=reason,
                )

            crawl_live_discovery(
                keyword=keyword,
                profile=profile,
                settings=browser_settings,
                include_documents=live_include_documents,
                project_callback=_persist_live_project,
                candidate_callback=_record_live_candidate,
                candidate_terminal_callback=_record_live_candidate_terminal,
                progress_callback=_record_live_progress,
            )
            resolved_projects = []

        for discovered in resolved_projects:
            _persist_discovered_project(discovered)
    except LiveDiscoveryPartialError as exc:
        run_level_error = str(exc)
        run_failure_code = DiscoveryFailureCode.LIVE_DISCOVERY_PARTIAL
        error_count += 1
    except SearchPageStateError as exc:
        run_level_error = str(exc)
        run_failure_code = DiscoveryFailureCode.SEARCH_PAGE_STATE_ERROR
        error_count += 1
    except Exception as exc:
        run_level_error = str(exc)
        run_failure_code = DiscoveryFailureCode.WORKER_REPORTED_FAILURE
        if candidate_attempt_repo is not None and all(
            hasattr(run_repository, method)
            for method in ("fail_run_if_active", "find_run_by_id_for_tenant")
        ):
            report = complete_abnormal_run(
                tenant_id=tenant_id,
                run_id=run.id,
                failure_code=run_failure_code.value,
                candidate_reason=CandidateTerminalReason.WORKER_LOST.value,
                error=run_level_error,
                candidate_repository=candidate_attempt_repo,
                run_repository=run_repository,
            )
            if not report.succeeded:
                logger.error(
                    "Direct workflow abnormal completion incomplete",
                    extra={
                        "tenant_id": tenant_id,
                        "run_id": run.id,
                        "abnormal_completion": report.evidence(),
                    },
                )
                try:
                    run_repository.update_run_summary(
                        run.id,
                        summary_json={"abnormal_completion": report.evidence()},
                    )
                except Exception:
                    logger.exception("Failed to persist abnormal completion report")
        else:
            run_repository.mark_run_finished(
                run.id,
                status="failed",
                summary_json={
                    "projects_seen": len(persisted_projects),
                    "error": run_level_error,
                    "failure_code": run_failure_code,
                },
                error_count=max(1, error_count),
            )
        raise

    terminal_live_anomaly = (
        live
        and not persisted_projects
        and live_progress is not None
        and _live_progress_is_terminal_crawl_anomaly(live_progress)
    )
    if terminal_live_anomaly and (
        live_crawl_latest_anomaly is None
        or live_crawl_latest_anomaly.get("stage") != live_progress.get("stage")
    ):
        live_crawl_anomaly_count += 1
        live_crawl_latest_anomaly = {
            key: value for key, value in live_progress.items() if key != "updated_at"
        }
    anomaly_error = (
        _build_live_crawl_anomaly_error(live_crawl_latest_anomaly)
        if live_crawl_latest_anomaly is not None
        else None
    )
    anomaly_failure_code = (
        _live_crawl_anomaly_failure_code(live_crawl_latest_anomaly)
        if live_crawl_latest_anomaly is not None
        else None
    )
    ledger_force_failed, ledger_partial = _apply_candidate_ledger_authority()
    ledger_error = (
        "candidate ledger authority failed"
        if ledger_force_failed
        else ("candidate ledger incomplete" if ledger_partial else None)
    )
    if ledger_force_failed or ledger_partial:
        ledger_outcome = "failed" if ledger_force_failed else "partial"
        for scan in keyword_scans.values():
            # The scan's browser observation is useful evidence, but it cannot
            # publish an `ok` aggregate once its candidate ledger is incomplete.
            scan["outcome"] = ledger_outcome
    summary_json = _current_summary()
    if run_level_error is not None:
        summary_json["error"] = run_level_error
        summary_json["failure_code"] = (
            run_failure_code or DiscoveryFailureCode.WORKER_REPORTED_FAILURE
        )
    elif anomaly_error is not None:
        summary_json["error"] = anomaly_error
        summary_json["failure_code"] = (
            anomaly_failure_code or DiscoveryFailureCode.WORKER_REPORTED_FAILURE
        )
    elif ledger_error is not None:
        summary_json["error"] = ledger_error
        summary_json["failure_code"] = DiscoveryFailureCode.WORKER_REPORTED_FAILURE
    if project_task_count == 0 and not keyword_task_creation_blocked:
        keyword_task_error = run_level_error or anomaly_error or ledger_error
        keyword_task_result: dict[str, object] = {"projects_seen": len(persisted_projects)}
        if keyword_task_error is not None:
            keyword_task_result["error"] = keyword_task_error
            keyword_task_result["failure_code"] = (
                run_failure_code
                or anomaly_failure_code
                or DiscoveryFailureCode.WORKER_REPORTED_FAILURE
            )
        try:
            _record_keyword_run_task(
                task_status="failed" if keyword_task_error is not None else "succeeded",
                result_json=keyword_task_result,
            )
        except Exception as exc:
            error_count += 1
            run_level_error = str(exc)
            run_failure_code = DiscoveryFailureCode.WORKER_REPORTED_FAILURE
            summary_json = _current_summary()
            summary_json["error"] = run_level_error
            summary_json["failure_code"] = run_failure_code
    ledger_error_count = 1 if ledger_error is not None else 0
    effective_error_count = error_count + live_crawl_anomaly_count + ledger_error_count
    if _is_backfill_trigger(trigger_type) and not persisted_projects and database_url is not None:
        existing_project_id = _backfill_project_id_for_keyword(
            database_url=database_url,
            tenant_id=tenant_id,
            keyword=keyword,
        )
        if (
            existing_project_id is not None
            and existing_project_id not in backfill_recorded_project_ids
        ):
            create_document_capture_attempt_repository(
                database_url=database_url,
                bootstrap_schema=False,
            ).record_attempt(
                tenant_id=tenant_id,
                project_id=existing_project_id,
                run_id=run.id,
                status=DocumentCaptureAttemptStatus.FAILED,
                reason=(
                    DocumentCaptureReason.FAILED.value
                    if (run_level_error or anomaly_error)
                    else DocumentCaptureReason.BACKFILL_PROJECT_NOT_REDISCOVERED.value
                ),
                doc_count=0,
            )
    if ledger_force_failed:
        terminal_status = "failed"
    elif effective_error_count:
        terminal_status = "partial" if persisted_projects else "failed"
    elif ledger_partial:
        terminal_status = "partial"
    else:
        terminal_status = "succeeded"
    run_repository.mark_run_finished(
        run.id,
        status=terminal_status,
        summary_json=summary_json,
        error_count=effective_error_count,
    )
    detail = run_repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)
    if detail is None:
        raise KeyError(run.id)
    return DiscoverWorkflowResult(run=detail, projects=persisted_projects)
