"""Subprocess-backed discovery worker dispatch implementation."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchRequest,
    NonRetriableDiscoveryDispatchError,
)


DISCOVER_WORKER_TIMEOUT_SECONDS = 3 * 60 * 60

_logger = logging.getLogger("egp_api.main")


def _resolve_browser_settings_payload(
    *,
    profile_repository,
    tenant_id: str,
    profile_id: str,
) -> dict[str, object] | None:
    if profile_repository is None:
        return None
    try:
        detail = profile_repository.get_profile_detail(
            tenant_id=tenant_id,
            profile_id=profile_id,
        )
    except Exception:
        _logger.warning(
            "Failed to resolve crawl profile settings for discover spawn (tenant_id=%s profile_id=%s)",
            tenant_id,
            profile_id,
            exc_info=True,
        )
        return None
    if detail is None:
        return None
    max_pages_per_keyword = getattr(detail.profile, "max_pages_per_keyword", None)
    if max_pages_per_keyword is None:
        return None
    try:
        normalized_max_pages = max(1, int(max_pages_per_keyword))
    except (TypeError, ValueError):
        _logger.warning(
            "Invalid max_pages_per_keyword on crawl profile (tenant_id=%s profile_id=%s value=%r)",
            tenant_id,
            profile_id,
            max_pages_per_keyword,
        )
        return None
    return {"max_pages_per_keyword": normalized_max_pages}


def _stderr_preview(stderr: bytes | str | None, *, limit: int = 500) -> str | None:
    if stderr is None:
        return None
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", errors="replace")
    else:
        text = str(stderr)
    normalized = text.strip()
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _parse_non_retriable_error(
    stderr: bytes | str | None,
) -> NonRetriableDiscoveryDispatchError | None:
    if stderr is None:
        return None
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", errors="replace")
    else:
        text = str(stderr)
    for raw_line in reversed(text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("error_type") != "entitlement_denied":
            continue
        detail = str(payload.get("detail") or "discover entitlement denied").strip()
        return NonRetriableDiscoveryDispatchError(detail)
    return None


class _NoopRunRepository:
    def create_run(self, **kwargs) -> None:
        del kwargs

    def fail_run_if_active(self, *args, **kwargs) -> None:
        del args, kwargs
        return None

    def update_run_summary(self, run_id: str, *, summary_json: dict[str, object] | None) -> None:
        del run_id, summary_json


class DiscoverySpawnError(RuntimeError):
    """Raised when a subprocess discovery worker fails for a retriable reason."""


class SubprocessDiscoveryDispatcher:
    """Dispatch discovery jobs by launching the existing worker subprocess."""

    def __init__(
        self,
        database_url: str,
        *,
        artifact_root: Path | None = None,
        run_repository=None,
        profile_repository=None,
        timeout_seconds: float = DISCOVER_WORKER_TIMEOUT_SECONDS,
    ) -> None:
        self._database_url = database_url
        self._artifact_root = (artifact_root or Path("artifacts")).expanduser().resolve()
        self._run_repository = run_repository or _NoopRunRepository()
        self._profile_repository = profile_repository
        self._timeout_seconds = timeout_seconds

    def __call__(
        self,
        *,
        tenant_id: str,
        profile_id: str,
        profile_type: str,
        keyword: str,
    ) -> None:
        self.dispatch(
            DiscoveryDispatchRequest(
                tenant_id=tenant_id,
                profile_id=profile_id,
                profile_type=profile_type,
                keyword=keyword,
            )
        )

    def dispatch(self, request: DiscoveryDispatchRequest) -> None:
        run_id = str(uuid4())
        browser_settings = _resolve_browser_settings_payload(
            profile_repository=self._profile_repository,
            tenant_id=request.tenant_id,
            profile_id=request.profile_id,
        )
        self._run_repository.create_run(
            tenant_id=request.tenant_id,
            profile_id=request.profile_id,
            trigger_type="manual",
            run_id=run_id,
        )
        log_path = (
            self._artifact_root / "tenants" / request.tenant_id / "runs" / run_id / "worker.log"
        ).resolve()
        log_handle = None
        if self._artifact_root is not None:
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_handle = log_path.open("ab")
            except Exception:
                _logger.warning(
                    "Failed to create discover worker log file (run_id=%s)",
                    run_id,
                    exc_info=True,
                )
                log_path = None
        payload = json.dumps(
            {
                "command": "discover",
                "database_url": self._database_url,
                "artifact_root": str(self._artifact_root),
                "tenant_id": request.tenant_id,
                "run_id": run_id,
                "profile_id": request.profile_id,
                "keyword": request.keyword,
                "profile": request.profile_type,
                "trigger_type": "manual",
                "live": True,
                "live_include_documents": True,
                **({"browser_settings": browser_settings} if browser_settings is not None else {}),
            },
            ensure_ascii=False,
        ).encode()
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "egp_worker.main"],
                stdin=subprocess.PIPE,
                stdout=log_handle or subprocess.DEVNULL,
                stderr=log_handle or subprocess.PIPE,
            )
            self._safe_update_run_summary(
                run_id=run_id,
                summary_json={
                    **({"worker_log_path": str(log_path)} if log_path is not None else {}),
                    "worker_owner_pid": os.getpid(),
                    **(
                        {"worker_pid": proc.pid}
                        if isinstance(getattr(proc, "pid", None), int)
                        else {}
                    ),
                },
            )
            _, stderr = proc.communicate(input=payload, timeout=self._timeout_seconds)
            if log_handle is not None:
                log_handle.flush()
            stderr_text = (
                self._read_log_tail(log_path) if log_path is not None else None
            ) or stderr
            if proc.returncode not in {0, None}:
                preview = _stderr_preview(stderr_text)
                _logger.warning(
                    "Discover worker exited non-zero for keyword %r (tenant_id=%s profile_id=%s returncode=%s stderr=%r)",
                    request.keyword,
                    request.tenant_id,
                    request.profile_id,
                    proc.returncode,
                    preview,
                )
                terminated = self._worker_termination_error(
                    returncode=int(proc.returncode),
                    run_id=run_id,
                    keyword=request.keyword,
                )
                if terminated is not None:
                    raise terminated
                non_retriable = _parse_non_retriable_error(stderr_text)
                if non_retriable is not None:
                    raise non_retriable
                raise DiscoverySpawnError(
                    f"discover worker exited non-zero for keyword {request.keyword!r}"
                )
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            _, stderr = proc.communicate()
            if log_handle is not None:
                log_handle.flush()
            stderr_text = (self._read_log_tail(log_path) if log_path is not None else None) or (
                stderr or exc.stderr
            )
            preview = _stderr_preview(stderr_text)
            error_message = f"discover worker timed out for keyword {request.keyword!r}"
            _logger.warning(
                "Discover worker timed out for keyword %r (tenant_id=%s profile_id=%s timeout_seconds=%s stderr=%r)",
                request.keyword,
                request.tenant_id,
                request.profile_id,
                exc.timeout,
                preview,
            )
            self._mark_active_run_failed(
                run_id=run_id,
                error=error_message,
                failure_reason="worker_timeout",
            )
            raise DiscoverySpawnError(error_message) from exc
        except DiscoverySpawnError:
            raise
        except Exception:
            _logger.warning(
                "Failed to spawn discover for keyword %r (tenant_id=%s profile_id=%s)",
                request.keyword,
                request.tenant_id,
                request.profile_id,
                exc_info=True,
            )
            raise
        finally:
            if log_handle is not None:
                log_handle.close()

    def _safe_update_run_summary(
        self,
        *,
        run_id: str,
        summary_json: dict[str, object],
    ) -> None:
        try:
            self._run_repository.update_run_summary(
                run_id,
                summary_json=summary_json,
            )
        except Exception:
            _logger.warning(
                "Failed to persist discover run summary metadata (run_id=%s)",
                run_id,
                exc_info=True,
            )

    def _read_log_tail(self, log_path: Path | None, *, limit: int = 8192) -> str | None:
        if log_path is None or not log_path.is_file():
            return None
        data = log_path.read_bytes()
        if len(data) > limit:
            data = data[-limit:]
        return data.decode("utf-8", errors="replace")

    def _mark_active_run_failed(
        self,
        *,
        run_id: str,
        error: str,
        failure_reason: str,
    ) -> None:
        try:
            failed_run = self._run_repository.fail_run_if_active(
                run_id,
                error=error,
                failure_reason=failure_reason,
            )
        except Exception:
            _logger.warning(
                "Failed to mark discover run failed (run_id=%s failure_reason=%s)",
                run_id,
                failure_reason,
                exc_info=True,
            )
            return
        if failed_run is not None:
            _logger.warning(
                "Marked discover run %s failed (%s)",
                failed_run.id,
                failure_reason,
            )

    def _worker_termination_error(
        self,
        *,
        returncode: int,
        run_id: str,
        keyword: str,
    ) -> NonRetriableDiscoveryDispatchError | None:
        if returncode >= 0:
            return None
        signal_number = abs(int(returncode))
        try:
            signal_name = signal.Signals(signal_number).name
        except ValueError:
            signal_name = f"SIG{signal_number}"
        error_message = (
            f"discover worker terminated by signal {signal_name} for keyword {keyword!r}"
        )
        self._mark_active_run_failed(
            run_id=run_id,
            error=error_message,
            failure_reason="worker_terminated",
        )
        return NonRetriableDiscoveryDispatchError(error_message)
