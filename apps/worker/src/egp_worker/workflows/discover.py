"""Event-emitting discover workflow extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from egp_crawler_core.discovery_authorization import (
    DiscoveryAuthorizationError,
    DiscoveryAuthorizationSnapshot,
    ProfileKeywordCandidate,
    build_discovery_authorization_snapshot,
    require_discovery_authorization,
)
from egp_crawler_core.invitation_rules import is_discoverable_stage_status
from egp_db.google_drive import GoogleDriveOAuthConfig
from egp_db.onedrive import OneDriveOAuthConfig
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
        return summary

    def _record_keyword_scan(event_snapshot: dict[str, object]) -> None:
        scan_keyword = str(event_snapshot.get("keyword") or keyword)
        keyword_scans[scan_keyword] = {
            key: value
            for key, value in event_snapshot.items()
            if key not in ("stage", "keyword")
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

    def _persist_discovered_project(discovered: dict[str, object]) -> ProjectRecord | None:
        nonlocal error_count, ignored_late_stage_projects, keyword_task_creation_blocked
        nonlocal project_task_count, run_failure_code, run_level_error
        source_status_text = str(discovered.get("source_status_text") or "")
        if not is_discoverable_stage_status(source_status_text):
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
            persisted_project_keys.add(project_key)
            persisted_projects.append(project)
            run_repository.update_run_summary(run.id, summary_json=_current_summary())
            return project
        except Exception as exc:
            error_count += 1
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
                _persist_discovered_project(live_project)

            crawl_live_discovery(
                keyword=keyword,
                profile=profile,
                settings=browser_settings,
                include_documents=live_include_documents,
                project_callback=_persist_live_project,
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
    if project_task_count == 0 and not keyword_task_creation_blocked:
        keyword_task_error = run_level_error or anomaly_error
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
    effective_error_count = error_count + live_crawl_anomaly_count
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
    run_repository.mark_run_finished(
        run.id,
        status="partial"
        if effective_error_count and persisted_projects
        else ("failed" if effective_error_count else "succeeded"),
        summary_json=summary_json,
        error_count=effective_error_count,
    )
    detail = run_repository.get_run_detail(tenant_id=tenant_id, run_id=run.id)
    if detail is None:
        raise KeyError(run.id)
    return DiscoverWorkflowResult(run=detail, projects=persisted_projects)
