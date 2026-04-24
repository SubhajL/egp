"""Worker entrypoint package."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .browser_discovery import BrowserDiscoverySettings
from .scheduler import run_scheduled_discovery
from .workflows.close_check import run_close_check_workflow
from .workflows.discover import run_discover_workflow
from .workflows.document_ingest import ingest_document_artifact
from .workflows.timeout_sweep import evaluate_timeout_transition


def _parse_optional_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value))


def _run_discovery_job(payload: dict[str, object]) -> dict[str, object]:
    return run_worker_job(payload)


def _build_browser_settings(payload: dict[str, object]) -> BrowserDiscoverySettings | None:
    raw_settings = payload.get("browser_settings")
    settings_payload = dict(raw_settings) if isinstance(raw_settings, dict) else {}
    flat_key_map = {
        "browser_cdp_port": "cdp_port",
        "browser_profile_dir": "browser_profile_dir",
        "browser_nav_timeout_ms": "nav_timeout_ms",
        "browser_cloudflare_timeout_ms": "cloudflare_timeout_ms",
        "browser_cloudflare_reload_retries": "cloudflare_reload_retries",
        "browser_search_page_recovery_retries": "search_page_recovery_retries",
        "browser_max_pages_per_keyword": "max_pages_per_keyword",
        "browser_project_detail_timeout_s": "project_detail_timeout_s",
        "browser_chrome_path": "chrome_path",
    }
    for payload_key, setting_key in flat_key_map.items():
        if payload.get(payload_key) is not None:
            settings_payload[setting_key] = payload[payload_key]
    if not settings_payload:
        return None

    updates: dict[str, object] = {}
    int_fields = {
        "cdp_port",
        "nav_timeout_ms",
        "cloudflare_timeout_ms",
        "cloudflare_reload_retries",
        "search_page_recovery_retries",
        "max_pages_per_keyword",
    }
    for field in int_fields:
        if settings_payload.get(field) is not None:
            updates[field] = int(settings_payload[field])
    if settings_payload.get("project_detail_timeout_s") is not None:
        updates["project_detail_timeout_s"] = float(settings_payload["project_detail_timeout_s"])
    if settings_payload.get("browser_profile_dir") is not None:
        updates["browser_profile_dir"] = Path(str(settings_payload["browser_profile_dir"]))
    if settings_payload.get("chrome_path") is not None:
        updates["chrome_path"] = str(settings_payload["chrome_path"])
    return replace(BrowserDiscoverySettings(), **updates)


def run_worker_job(payload: dict[str, object]) -> dict[str, object]:
    command = str(payload.get("command") or "").strip()
    if command == "discover":
        result = run_discover_workflow(
            database_url=str(payload["database_url"]),
            tenant_id=str(payload["tenant_id"]),
            profile_id=(
                str(payload["profile_id"]) if payload.get("profile_id") is not None else None
            ),
            keyword=str(payload.get("keyword") or ""),
            discovered_projects=list(payload.get("discovered_projects") or []),
            trigger_type=str(payload.get("trigger_type") or "manual"),
            live=bool(payload.get("live", False)),
            profile=(str(payload["profile"]) if payload.get("profile") is not None else None),
            browser_settings=_build_browser_settings(payload),
            live_include_documents=bool(payload.get("live_include_documents", False)),
            artifact_root=Path(str(payload.get("artifact_root") or "artifacts")),
            storage_credentials_secret=(
                str(payload["storage_credentials_secret"])
                if payload.get("storage_credentials_secret") is not None
                else None
            ),
        )
        response = {
            "command": command,
            "run_id": result.run.run.id,
            "run_status": result.run.run.status,
            "project_count": len(result.projects),
            "project_ids": [project.id for project in result.projects],
        }
        if payload.get("profile_id") is not None:
            response["profile_id"] = str(payload["profile_id"])
        return response
    if command == "close_check":
        result = run_close_check_workflow(
            database_url=str(payload["database_url"]),
            tenant_id=str(payload["tenant_id"]),
            observations=list(payload.get("observations") or []),
            trigger_type=str(payload.get("trigger_type") or "manual"),
            live=bool(payload.get("live", False)),
        )
        return {
            "command": command,
            "run_id": result.run.run.id,
            "run_status": result.run.run.status,
            "updated_project_count": len(result.updated_projects),
            "updated_project_ids": [project.id for project in result.updated_projects],
        }
    if command == "document_ingest":
        file_bytes = bytes.fromhex(str(payload["file_bytes_hex"]))
        result = ingest_document_artifact(
            artifact_root=str(payload["artifact_root"]),
            database_url=str(payload["database_url"]),
            artifact_storage_backend=str(payload.get("artifact_storage_backend") or "local"),
            artifact_bucket=(
                str(payload["artifact_bucket"])
                if payload.get("artifact_bucket") is not None
                else None
            ),
            artifact_prefix=str(payload.get("artifact_prefix") or ""),
            supabase_url=(
                str(payload["supabase_url"]) if payload.get("supabase_url") is not None else None
            ),
            supabase_service_role_key=(
                str(payload["supabase_service_role_key"])
                if payload.get("supabase_service_role_key") is not None
                else None
            ),
            storage_credentials_secret=(
                str(payload["storage_credentials_secret"])
                if payload.get("storage_credentials_secret") is not None
                else None
            ),
            tenant_id=str(payload["tenant_id"]),
            project_id=str(payload["project_id"]),
            file_name=str(payload["file_name"]),
            file_bytes=file_bytes,
            source_label=str(payload.get("source_label") or ""),
            source_status_text=str(payload.get("source_status_text") or ""),
            source_page_text=str(payload.get("source_page_text") or ""),
            project_state=(
                str(payload["project_state"]) if payload.get("project_state") is not None else None
            ),
        )
        return {
            "command": command,
            "created": result.created,
            "document_id": result.document.id,
            "document_type": result.document.document_type.value,
            "document_phase": result.document.document_phase.value,
            "diff_count": len(result.diff_records),
        }
    if command == "timeout_evaluate":
        transition = evaluate_timeout_transition(
            procurement_type=payload.get("procurement_type"),
            project_state=str(payload["project_state"]),
            last_changed_at=_parse_optional_datetime(payload.get("last_changed_at")),
            now=_parse_optional_datetime(payload.get("now")),
        )
        return {
            "command": command,
            "transition": (
                {
                    "project_state": transition["project_state"].value,
                    "closed_reason": transition["closed_reason"].value,
                }
                if transition is not None
                else None
            ),
        }
    if command == "run_scheduled_discovery":
        database_url = str(payload["database_url"])
        result = run_scheduled_discovery(
            database_url=database_url,
            job_runner=lambda job: _run_discovery_job(
                {
                    "command": "discover",
                    "database_url": database_url,
                    **job,
                }
            ),
        )
        return {
            "command": command,
            "due_job_count": int(result["due_job_count"]),
            "executed_job_count": int(result["executed_job_count"]),
        }
    raise ValueError(f"Unsupported worker command: {command}")


def main(stdin_text: str | None = None) -> None:
    raw_input = stdin_text if stdin_text is not None else sys.stdin.read()
    payload = json.loads(raw_input) if raw_input.strip() else {"command": "noop"}
    if payload.get("command") == "noop":
        print(json.dumps({"service": "worker", "status": "idle"}, sort_keys=True))
        return
    try:
        result = run_worker_job(payload)
    except PermissionError as exc:
        print(
            json.dumps(
                {"error_type": "entitlement_denied", "detail": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
