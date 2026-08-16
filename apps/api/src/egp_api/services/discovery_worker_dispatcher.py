"""Subprocess-backed discovery worker dispatch implementation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from egp_api.config import (
    get_artifact_bucket,
    get_artifact_prefix,
    get_artifact_storage_backend,
    get_browser_cdp_port_base,
    get_browser_cdp_port_range,
    get_browser_chrome_path,
    get_browser_cloudflare_operator_timeout_ms,
    get_browser_cloudflare_reload_retries,
    get_browser_cloudflare_timeout_ms,
    get_browser_nav_timeout_ms,
    get_browser_predispatch_warm_seconds,
    get_browser_persistent_profile_dir,
    get_browser_profile_mode,
    get_browser_profile_root,
    get_browser_project_detail_timeout_s,
    get_browser_proxy_server,
    get_browser_use_xvfb,
    get_browser_warmup_failure_pause_threshold,
    get_browser_warmup_stale_after_seconds,
)
from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchRequest,
    DiscoveryPreDispatchResult,
    NonRetriableDiscoveryDispatchError,
)
from egp_api.services.run_trigger_mapping import map_job_trigger_to_run_trigger
from egp_crawler_core.profile_lock import (
    acquire_profile_lock as _shared_acquire_profile_lock,
    ProfileLockedError,
    release_profile_lock as _shared_release_profile_lock,
)
from egp_db.repositories.candidate_attempt_repo import create_candidate_attempt_repository
from egp_db.abnormal_run_completion import (
    AbnormalRunCompletionReport,
    complete_abnormal_run,
)
from egp_crawler_core.rate_limiter import get_default_rate_limiter
from egp_observability.logging import (
    RESULT_FRAME_BEGIN,
    RESULT_FRAME_END,
    make_event,
    tail_bounded_preview,
)
from egp_observability.metrics import record_discovery_keyword_scan
from egp_observability.subprocess_evidence import (
    BoundedEvidenceWriter,
    BoundedResultDecoder,
    ChildProcessCancelled,
    DiscardingEvidenceWriter,
    EvidenceCorrelation,
    build_run_log_path,
    observe_child_process,
    prune_run_evidence,
)
from egp_shared_types.enums import (
    CandidateTerminalReason,
    CrawlerBlockerCode,
    DiscoveryFailureCode,
)


DISCOVER_WORKER_TIMEOUT_SECONDS = 3 * 60 * 60
FAULT_INJECTION_TIMEOUT_SECONDS = 1.0
FAULT_INJECTION_MODES = frozenset(
    {
        "worker_timeout",
        "nonzero_exit",
        "missing_result",
        "entitlement_denied",
        "worker_crash",
    }
)
_RELEASE_SHA: str | None = os.environ.get("EGP_RELEASE_SHA") or None


def _flush_log_events(log_handle: BinaryIO | None, events: list[str]) -> None:
    if log_handle is None or not events:
        return
    try:
        for event_line in events:
            log_handle.write(event_line.encode("utf-8") + b"\n")
        log_handle.flush()
    except Exception:
        pass


class _EvidenceEventBuffer(list[str]):
    """Compatibility list that writes lifecycle events at append time."""

    def __init__(self, writer: BoundedEvidenceWriter | None) -> None:
        super().__init__()
        self._writer = writer

    def append(self, event_line: str) -> None:
        if self._writer is None:
            super().append(event_line)
            return
        try:
            payload = json.loads(event_line)
            event = str(payload.pop("event"))
            payload.pop("ts", None)
            for key in (
                "tenant_id",
                "run_id",
                "job_id",
                "owner_pid",
                "child_pid",
                "execution_backend",
                "release_sha",
            ):
                payload.pop(key, None)
            self._writer.write_lifecycle(event, **payload)
        except Exception:
            pass


PROFILE_STATE_FILENAME = ".egp-profile-state.json"
WORKER_STDOUT_SPOOL_LIMIT_BYTES = 1_048_576
WORKER_RESULT_TAIL_BYTES = 65_536
WORKER_CANCELLATION_POLL_SECONDS = 0.5

_logger = logging.getLogger("egp_api.main")


class _DiscoveryLeaseCancellation(RuntimeError):
    """Internal signal raised after a lease-loss event kills the worker."""


def _browser_cdp_port_for_run_id(
    run_id: str,
    *,
    base: int,
    port_range: int,
) -> int:
    if port_range < 1:
        raise ValueError("port_range must be positive")
    digest = hashlib.sha256(str(run_id).encode("utf-8")).digest()
    return int(base) + (int.from_bytes(digest[:8], "big") % int(port_range))


def _browser_profile_dir_for_run_id(
    run_id: str,
    *,
    profile_root: Path,
) -> Path:
    resolved_root = profile_root.expanduser().resolve()
    profile_dir = (resolved_root / str(run_id)).resolve()
    try:
        profile_dir.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError("browser profile dir must stay under EGP_BROWSER_PROFILE_ROOT") from exc
    return profile_dir


def _cleanup_browser_profile_dir(
    profile_dir: Path | None,
    *,
    profile_root: Path,
) -> None:
    if profile_dir is None:
        return
    resolved_root = profile_root.expanduser().resolve()
    try:
        resolved_profile_dir = profile_dir.expanduser().resolve()
        resolved_profile_dir.relative_to(resolved_root)
    except Exception:
        _logger.warning(
            "Refusing to remove browser profile dir outside configured root (profile_dir=%s root=%s)",
            profile_dir,
            resolved_root,
        )
        return
    if resolved_profile_dir == resolved_root:
        _logger.warning("Refusing to remove browser profile root itself (%s)", resolved_root)
        return
    if not resolved_profile_dir.exists():
        return
    try:
        shutil.rmtree(resolved_profile_dir)
    except Exception:
        _logger.warning(
            "Failed to remove discovery worker browser profile dir (profile_dir=%s)",
            resolved_profile_dir,
            exc_info=True,
        )


_SYNC_FOLDER_MARKERS = (
    "onedrive",
    "icloud",
    "dropbox",
    "google drive",
    "library/mobile documents",
)


def _validate_persistent_profile_dir(profile_dir: Path) -> None:
    """Reject persistent profile dirs inside cloud-synced folders (corruption risk)."""
    lowered = str(profile_dir).lower()
    for marker in _SYNC_FOLDER_MARKERS:
        if marker in lowered:
            raise RuntimeError(
                "EGP_BROWSER_PERSISTENT_PROFILE_DIR must not be inside a synced folder "
                f"({marker!r}): {profile_dir}"
            )


def _profile_state_path(profile_dir: Path) -> Path:
    return profile_dir / PROFILE_STATE_FILENAME


def _parse_profile_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_profile_last_success_at(profile_dir: Path) -> datetime | None:
    payload = _read_profile_state(profile_dir)
    if payload is None:
        return None
    return _parse_profile_timestamp(payload.get("last_success_at"))


def _read_profile_state(profile_dir: Path) -> dict[str, object] | None:
    state_path = _profile_state_path(profile_dir)
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _profile_warm_needed(
    profile_dir: Path,
    *,
    stale_after_seconds: float,
    now: datetime | None = None,
) -> bool:
    if stale_after_seconds <= 0:
        return True
    last_success = _read_profile_last_success_at(profile_dir)
    if last_success is None:
        return True
    resolved_now = now or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=UTC)
    else:
        resolved_now = resolved_now.astimezone(UTC)
    return (resolved_now - last_success).total_seconds() >= stale_after_seconds


def _write_profile_success_state(
    profile_dir: Path,
    *,
    source: str,
    now: datetime | None = None,
) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    resolved_now = now or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=UTC)
    payload = {
        "consecutive_warm_failures": 0,
        "last_success_at": resolved_now.astimezone(UTC).isoformat(),
        "operator_action_required": False,
        "source": source,
    }
    _profile_state_path(profile_dir).write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def _write_profile_warm_failure_state(
    profile_dir: Path,
    *,
    error: BaseException,
    pause_threshold: int,
    now: datetime | None = None,
) -> int:
    state = _read_profile_state(profile_dir) or {}
    try:
        previous_failures = int(state.get("consecutive_warm_failures", 0))
    except (TypeError, ValueError):
        previous_failures = 0
    consecutive_failures = previous_failures + 1
    resolved_now = now or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=UTC)
    payload = {
        **state,
        "consecutive_warm_failures": consecutive_failures,
        "last_failure_at": resolved_now.astimezone(UTC).isoformat(),
        "last_failure_error": tail_bounded_preview(str(error), limit=300),
        "operator_action_required": (
            pause_threshold > 0 and consecutive_failures >= pause_threshold
        ),
    }
    profile_dir.mkdir(parents=True, exist_ok=True)
    _profile_state_path(profile_dir).write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    return consecutive_failures


def _write_profile_crawl_failure_state(
    profile_dir: Path,
    *,
    error: BaseException,
    now: datetime | None = None,
) -> None:
    state = _read_profile_state(profile_dir) or {}
    resolved_now = now or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=UTC)
    payload = {
        **state,
        "last_crawl_failure_at": resolved_now.astimezone(UTC).isoformat(),
        "last_crawl_failure_error": tail_bounded_preview(str(error), limit=300),
        "source": "crawl_failure",
    }
    payload.pop("last_success_at", None)
    profile_dir.mkdir(parents=True, exist_ok=True)
    _profile_state_path(profile_dir).write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def _profile_warm_operator_action_required(
    profile_dir: Path,
    *,
    pause_threshold: int,
) -> bool:
    if pause_threshold <= 0:
        return False
    state = _read_profile_state(profile_dir)
    if state is None:
        return False
    if state.get("operator_action_required") is True:
        return True
    try:
        return int(state.get("consecutive_warm_failures", 0)) >= pause_threshold
    except (TypeError, ValueError):
        return False


def _acquire_profile_lock(profile_dir: Path):
    """Take the shared exclusive profile lock; one warmed profile = one browser.

    Delegates to the cross-process lock in ``egp_crawler_core.profile_lock`` so
    the crawl and the keep-warm routine share the SAME lock file and can never
    use the persistent profile simultaneously. Returns the open lock-file handle
    (caller releases it). Raises ``DiscoverySpawnError`` (retriable) if the
    profile is already in use by another crawl.
    """
    try:
        return _shared_acquire_profile_lock(profile_dir)
    except ProfileLockedError as exc:
        raise DiscoverySpawnError(
            f"persistent browser profile is locked by another crawl ({profile_dir})"
        ) from exc


def _release_profile_lock(handle) -> None:
    _shared_release_profile_lock(handle)


def _kill_process_group(proc) -> None:
    """SIGKILL the worker and its descendants (Chrome/Xvfb) as a group.

    The worker is spawned with ``start_new_session=True`` so it leads its own
    process group; killing the group (not just the worker PID) prevents an
    orphaned Chrome from holding a persistent profile after the lock is released.
    """
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except Exception:
        pass


def _communicate_with_cancellation(
    proc,
    *,
    payload: bytes,
    timeout_seconds: float,
    cancellation_event: threading.Event | None,
) -> tuple[bytes | str | None, bytes | str | None]:
    if cancellation_event is None:
        return proc.communicate(input=payload, timeout=timeout_seconds)

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    pending_input: bytes | None = payload
    while True:
        if cancellation_event.is_set():
            _kill_process_group(proc)
            proc.communicate()
            raise _DiscoveryLeaseCancellation("discovery job lease ownership was lost")
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise subprocess.TimeoutExpired(
                cmd=getattr(proc, "args", "egp_worker"),
                timeout=timeout_seconds,
            )
        try:
            result = proc.communicate(
                input=pending_input,
                timeout=min(WORKER_CANCELLATION_POLL_SECONDS, remaining_seconds),
            )
        except subprocess.TimeoutExpired as exc:
            # The NORMAL path. This inner timeout is the poll interval, not a
            # failure: it just means the worker is still running and we should
            # check the cancellation event and wait again. Falling through from
            # here reached `return result` with `result` unassigned, so the first
            # poll killed any crawl that outlived one interval — i.e. all of them.
            pending_input = None
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(
                    cmd=getattr(proc, "args", exc.cmd),
                    timeout=timeout_seconds,
                    output=exc.output,
                    stderr=exc.stderr,
                ) from exc
            if cancellation_event.is_set():
                _kill_process_group(proc)
                proc.communicate()
                raise _DiscoveryLeaseCancellation("discovery job lease ownership was lost")
            continue
        if cancellation_event.is_set():
            _kill_process_group(proc)
            proc.communicate()
            raise _DiscoveryLeaseCancellation("discovery job lease ownership was lost")
        return result


def _resolve_browser_settings_payload(
    *,
    profile_repository,
    tenant_id: str,
    profile_id: str,
    run_id: str,
    browser_cdp_port_base: int,
    browser_cdp_port_range: int,
    browser_profile_dir: Path,
    chrome_path: str | None = None,
    proxy_server: str | None = None,
    use_xvfb: bool = False,
    nav_timeout_ms: int | None = None,
    cloudflare_timeout_ms: int | None = None,
    cloudflare_reload_retries: int | None = None,
    cloudflare_operator_timeout_ms: int | None = None,
    project_detail_timeout_s: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "browser_cdp_port": _browser_cdp_port_for_run_id(
            run_id,
            base=browser_cdp_port_base,
            port_range=browser_cdp_port_range,
        ),
        "browser_profile_dir": str(browser_profile_dir),
    }
    if chrome_path:
        payload["browser_chrome_path"] = chrome_path
    if proxy_server:
        payload["browser_proxy_server"] = proxy_server
    if use_xvfb:
        payload["browser_use_xvfb"] = True
    if nav_timeout_ms is not None:
        payload["browser_nav_timeout_ms"] = nav_timeout_ms
    if cloudflare_timeout_ms is not None:
        payload["browser_cloudflare_timeout_ms"] = cloudflare_timeout_ms
    if cloudflare_reload_retries is not None:
        payload["browser_cloudflare_reload_retries"] = cloudflare_reload_retries
    if cloudflare_operator_timeout_ms is not None:
        payload["browser_cloudflare_operator_wait_timeout_ms"] = cloudflare_operator_timeout_ms
    if project_detail_timeout_s is not None:
        payload["browser_project_detail_timeout_s"] = project_detail_timeout_s
    if profile_repository is None:
        return payload
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
        return payload
    if detail is None:
        return payload
    max_pages_per_keyword = getattr(detail.profile, "max_pages_per_keyword", None)
    if max_pages_per_keyword is None:
        return payload
    try:
        normalized_max_pages = max(1, int(max_pages_per_keyword))
    except (TypeError, ValueError):
        _logger.warning(
            "Invalid max_pages_per_keyword on crawl profile (tenant_id=%s profile_id=%s value=%r)",
            tenant_id,
            profile_id,
            max_pages_per_keyword,
        )
        return payload
    payload["max_pages_per_keyword"] = normalized_max_pages
    return payload


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

    def find_run_by_id_for_tenant(self, **kwargs) -> None:
        del kwargs
        return None


class _UnavailableCandidateRepository:
    def reconcile_open_candidates(self, **kwargs) -> int:
        del kwargs
        raise RuntimeError("candidate repository is unavailable")


class DiscoverySpawnError(RuntimeError):
    """Raised when a subprocess discovery worker fails for a retriable reason."""

    def __init__(
        self,
        message: str,
        *,
        failure_code: DiscoveryFailureCode = DiscoveryFailureCode.DISPATCH_EXCEPTION,
    ) -> None:
        self.failure_code = failure_code
        super().__init__(message)


def _decode_discovery_worker_result(stdout: bytes | str | None) -> dict[str, object] | None:
    if stdout is None:
        return None
    text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout
    for line in reversed(text.splitlines()):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _decode_framed_or_fallback_result(
    stdout: bytes | str | None,
) -> dict[str, object] | None:
    if stdout is None:
        return None
    text = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout
    begin_idx = text.rfind(RESULT_FRAME_BEGIN)
    end_idx = text.rfind(RESULT_FRAME_END)
    if begin_idx >= 0 and end_idx > begin_idx:
        between = text[begin_idx + len(RESULT_FRAME_BEGIN) : end_idx].strip()
        try:
            payload = json.loads(between)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        return None
    return _decode_discovery_worker_result(stdout)


def _validate_discovery_worker_result(
    result: dict[str, object],
    *,
    expected_run_id: str,
    keyword: str,
) -> tuple[str, DiscoveryFailureCode | None]:
    result_run_id = str(result.get("run_id") or "").strip()
    if result_run_id != expected_run_id:
        raise DiscoverySpawnError(
            "discover worker returned an invalid run_id "
            f"for keyword {keyword!r}: expected {expected_run_id!r}, got {result_run_id!r}",
            failure_code=DiscoveryFailureCode.WORKER_RESULT_INVALID,
        )
    run_status = str(result.get("run_status") or "").strip().casefold()
    if run_status not in {"succeeded", "partial", "failed"}:
        raise DiscoverySpawnError(
            f"discover worker returned invalid run_status {run_status!r} for keyword {keyword!r}",
            failure_code=DiscoveryFailureCode.WORKER_RESULT_INVALID,
        )
    raw_failure_code = str(result.get("failure_code") or "").strip()
    failure_code: DiscoveryFailureCode | None = None
    if raw_failure_code:
        try:
            failure_code = DiscoveryFailureCode(raw_failure_code)
        except ValueError as exc:
            raise DiscoverySpawnError(
                f"discover worker returned invalid failure_code {raw_failure_code!r} "
                f"for keyword {keyword!r}",
                failure_code=DiscoveryFailureCode.WORKER_RESULT_INVALID,
            ) from exc
    if run_status == "failed" and failure_code is None:
        raise DiscoverySpawnError(
            f"discover worker returned failed without failure_code for keyword {keyword!r}",
            failure_code=DiscoveryFailureCode.WORKER_RESULT_INVALID,
        )
    return run_status, failure_code


def _drain_worker_stdout(
    stdout_capture: BinaryIO,
    returned_stdout: bytes | str | None,
    *,
    log_handle: BinaryIO | None,
) -> bytes:
    if returned_stdout not in {None, b"", ""}:
        data = (
            returned_stdout
            if isinstance(returned_stdout, bytes)
            else returned_stdout.encode("utf-8")
        )
        if log_handle is not None:
            log_handle.write(data)
            if not data.endswith(b"\n"):
                log_handle.write(b"\n")
        return data[-WORKER_RESULT_TAIL_BYTES:]
    stdout_capture.flush()
    stdout_capture.seek(0)
    tail = b""
    while chunk := stdout_capture.read(65_536):
        if log_handle is not None:
            log_handle.write(chunk)
        tail = (tail + chunk)[-WORKER_RESULT_TAIL_BYTES:]
    if log_handle is not None and tail and not tail.endswith(b"\n"):
        log_handle.write(b"\n")
    return tail


def _fault_worker_command(fault_mode: str) -> list[str]:
    """Return the fixed internal harness command or fail closed."""

    if fault_mode not in FAULT_INJECTION_MODES:
        raise NonRetriableDiscoveryDispatchError(
            "unknown fault_mode",
            failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
        )
    return [sys.executable, "-m", "egp_worker.fault_injection", fault_mode]


def _fault_outcome_verified(
    *,
    fault_mode: str,
    returncode: int | None,
    failure_code: DiscoveryFailureCode,
) -> bool:
    expected = {
        "worker_timeout": (-signal.SIGKILL, DiscoveryFailureCode.WORKER_TIMEOUT),
        "nonzero_exit": (17, DiscoveryFailureCode.WORKER_EXIT_NONZERO),
        "missing_result": (0, DiscoveryFailureCode.WORKER_RESULT_MISSING),
        "entitlement_denied": (18, DiscoveryFailureCode.ENTITLEMENT_DENIED),
        "worker_crash": (-signal.SIGTERM, DiscoveryFailureCode.WORKER_TERMINATED),
    }.get(fault_mode)
    return expected == (returncode, failure_code)


def _verified_fault_exception(
    exc: DiscoverySpawnError | NonRetriableDiscoveryDispatchError,
    *,
    fault_mode: str,
    returncode: int | None,
    run_terminalized: bool,
    candidates_reconciled: bool,
) -> DiscoverySpawnError | NonRetriableDiscoveryDispatchError:
    if (
        run_terminalized
        and candidates_reconciled
        and _fault_outcome_verified(
            fault_mode=fault_mode,
            returncode=returncode,
            failure_code=exc.failure_code,
        )
    ):
        exc.fault_evidence_verified = True
        return exc
    return NonRetriableDiscoveryDispatchError(
        "fault injection outcome or durable cleanup was not verified",
        failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
    )


class SubprocessDiscoveryDispatcher:
    """Dispatch discovery jobs by launching the existing worker subprocess."""

    def __init__(
        self,
        database_url: str,
        *,
        artifact_root: Path | None = None,
        artifact_storage_backend: str | None = None,
        artifact_bucket: str | None = None,
        artifact_prefix: str | None = None,
        supabase_url: str | None = None,
        supabase_service_role_key: str | None = None,
        run_repository=None,
        profile_repository=None,
        timeout_seconds: float = DISCOVER_WORKER_TIMEOUT_SECONDS,
        fault_mode: str | None = None,
        fault_injection_authorized: bool = False,
        fault_timeout_seconds: float = FAULT_INJECTION_TIMEOUT_SECONDS,
        browser_cdp_port_base: int | str | None = None,
        browser_cdp_port_range: int | str | None = None,
        browser_profile_root: Path | str | None = None,
        browser_profile_mode: str | None = None,
        browser_persistent_profile_dir: Path | str | None = None,
        browser_chrome_path: str | None = None,
        browser_proxy_server: str | None = None,
        browser_use_xvfb: bool | None = None,
        browser_nav_timeout_ms: int | str | None = None,
        browser_cloudflare_timeout_ms: int | str | None = None,
        browser_cloudflare_reload_retries: int | str | None = None,
        browser_cloudflare_operator_timeout_ms: int | str | None = None,
        browser_project_detail_timeout_s: float | str | None = None,
        browser_warmup_stale_after_seconds: float | str | None = None,
        browser_warmup_failure_pause_threshold: int | str | None = None,
        browser_predispatch_warm_seconds: float | str | None = None,
    ) -> None:
        self._database_url = database_url
        self._artifact_root = (artifact_root or Path("artifacts")).expanduser().resolve()
        self._artifact_storage_backend = get_artifact_storage_backend(artifact_storage_backend)
        self._artifact_bucket = get_artifact_bucket(artifact_bucket)
        self._artifact_prefix = get_artifact_prefix(artifact_prefix)
        self._supabase_url = supabase_url.strip() if supabase_url else None
        self._supabase_service_role_key = (
            supabase_service_role_key.strip() if supabase_service_role_key else None
        )
        self._run_repository = run_repository or _NoopRunRepository()
        self._profile_repository = profile_repository
        self._timeout_seconds = timeout_seconds
        self._fault_mode = fault_mode
        self._fault_injection_authorized = fault_injection_authorized
        self._fault_timeout_seconds = max(0.01, float(fault_timeout_seconds))
        self._browser_cdp_port_base = get_browser_cdp_port_base(browser_cdp_port_base)
        self._browser_cdp_port_range = get_browser_cdp_port_range(browser_cdp_port_range)
        if self._browser_cdp_port_base + self._browser_cdp_port_range - 1 > 65_535:
            raise RuntimeError(
                "EGP_BROWSER_CDP_PORT_BASE + EGP_BROWSER_CDP_PORT_RANGE must not exceed 65535"
            )
        self._browser_profile_root = get_browser_profile_root(browser_profile_root)
        self._browser_profile_mode = get_browser_profile_mode(browser_profile_mode)
        self._browser_persistent_profile_dir = get_browser_persistent_profile_dir(
            browser_persistent_profile_dir
        )
        self._browser_chrome_path = get_browser_chrome_path(browser_chrome_path)
        self._browser_proxy_server = get_browser_proxy_server(browser_proxy_server)
        self._browser_use_xvfb = get_browser_use_xvfb(browser_use_xvfb)
        self._browser_nav_timeout_ms = get_browser_nav_timeout_ms(browser_nav_timeout_ms)
        self._browser_cloudflare_timeout_ms = get_browser_cloudflare_timeout_ms(
            browser_cloudflare_timeout_ms
        )
        self._browser_cloudflare_reload_retries = get_browser_cloudflare_reload_retries(
            browser_cloudflare_reload_retries
        )
        self._browser_cloudflare_operator_timeout_ms = get_browser_cloudflare_operator_timeout_ms(
            browser_cloudflare_operator_timeout_ms
        )
        self._browser_project_detail_timeout_s = get_browser_project_detail_timeout_s(
            browser_project_detail_timeout_s
        )
        self._browser_warmup_stale_after_seconds = get_browser_warmup_stale_after_seconds(
            browser_warmup_stale_after_seconds
        )
        self._browser_warmup_failure_pause_threshold = get_browser_warmup_failure_pause_threshold(
            browser_warmup_failure_pause_threshold
        )
        self._browser_predispatch_warm_seconds = get_browser_predispatch_warm_seconds(
            browser_predispatch_warm_seconds
        )
        if self._browser_profile_mode == "persistent":
            if self._browser_persistent_profile_dir is None:
                raise RuntimeError(
                    "EGP_BROWSER_PERSISTENT_PROFILE_DIR is required when "
                    "EGP_BROWSER_PROFILE_MODE=persistent"
                )
            _validate_persistent_profile_dir(self._browser_persistent_profile_dir)

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

    def _resolve_profile_dir_for_dispatch(self, run_id: str) -> tuple[Path, bool]:
        """Return (profile_dir, cleanup_after) for the configured profile mode."""
        if self._browser_profile_mode == "persistent":
            # Validated non-None in __init__.
            assert self._browser_persistent_profile_dir is not None
            return self._browser_persistent_profile_dir, False
        run_dir = _browser_profile_dir_for_run_id(run_id, profile_root=self._browser_profile_root)
        return run_dir, True

    def prepare_for_dispatch(self) -> DiscoveryPreDispatchResult:
        """Warm/preflight a stale persistent profile before claiming a job."""

        if self._fault_mode is not None and self._fault_injection_authorized:
            return DiscoveryPreDispatchResult.ready()
        circuit_snapshot = get_default_rate_limiter().get_circuit_snapshot()
        if circuit_snapshot.is_open:
            _logger.warning(
                "Host-shared e-GP circuit is open; deferring discovery job claim (reset_at=%s)",
                circuit_snapshot.reset_at,
            )
            return DiscoveryPreDispatchResult.blocked(
                CrawlerBlockerCode.CIRCUIT_OPEN,
                circuit_reset_at=circuit_snapshot.reset_at,
            )
        if self._browser_profile_mode != "persistent":
            return DiscoveryPreDispatchResult.ready()
        assert self._browser_persistent_profile_dir is not None
        try:
            profile_lock = _acquire_profile_lock(self._browser_persistent_profile_dir)
        except DiscoverySpawnError:
            _logger.info(
                "Persistent browser profile is busy; deferring discovery job claim "
                "(profile_dir=%s)",
                self._browser_persistent_profile_dir,
            )
            return DiscoveryPreDispatchResult.blocked(CrawlerBlockerCode.PROFILE_BUSY)
        try:
            self._warm_persistent_profile_if_stale(
                profile_dir=self._browser_persistent_profile_dir,
                browser_settings=self._build_persistent_warm_browser_settings(),
            )
            return DiscoveryPreDispatchResult.ready()
        except DiscoverySpawnError as exc:
            blocker = (
                CrawlerBlockerCode.PROFILE_OPERATOR_ACTION_REQUIRED
                if _profile_warm_operator_action_required(
                    self._browser_persistent_profile_dir,
                    pause_threshold=self._browser_warmup_failure_pause_threshold,
                )
                else CrawlerBlockerCode.PROFILE_WARM_RETRY
            )
            _logger.warning(
                "Persistent browser profile is not ready; deferring discovery job claim "
                "(profile_dir=%s blocker=%s error=%s)",
                self._browser_persistent_profile_dir,
                blocker,
                exc,
            )
            return DiscoveryPreDispatchResult.blocked(blocker)
        finally:
            _release_profile_lock(profile_lock)

    def _build_persistent_warm_browser_settings(self) -> dict[str, object]:
        assert self._browser_persistent_profile_dir is not None
        payload: dict[str, object] = {
            "browser_cdp_port": _browser_cdp_port_for_run_id(
                "predispatch-warm",
                base=self._browser_cdp_port_base,
                port_range=self._browser_cdp_port_range,
            ),
            "browser_profile_dir": str(self._browser_persistent_profile_dir),
        }
        if self._browser_chrome_path:
            payload["browser_chrome_path"] = self._browser_chrome_path
        if self._browser_proxy_server:
            payload["browser_proxy_server"] = self._browser_proxy_server
        if self._browser_use_xvfb:
            payload["browser_use_xvfb"] = True
        payload["browser_nav_timeout_ms"] = self._browser_nav_timeout_ms
        payload["browser_cloudflare_timeout_ms"] = self._browser_cloudflare_timeout_ms
        payload["browser_cloudflare_reload_retries"] = self._browser_cloudflare_reload_retries
        payload["browser_cloudflare_operator_wait_timeout_ms"] = (
            self._browser_cloudflare_operator_timeout_ms
        )
        return payload

    def dispatch(self, request: DiscoveryDispatchRequest) -> None:
        self.dispatch_cancellable(request, cancellation_event=None)

    def dispatch_cancellable(
        self,
        request: DiscoveryDispatchRequest,
        *,
        cancellation_event: threading.Event | None,
    ) -> dict[str, object] | None:
        requested_fault_mode = (
            request.fault_mode if request.fault_mode is not None else self._fault_mode
        )
        if (
            self._fault_mode is not None
            and request.fault_mode is not None
            and request.fault_mode != self._fault_mode
        ):
            raise NonRetriableDiscoveryDispatchError(
                "request fault mode does not match the authorized operator mode",
                failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
            )
        if requested_fault_mode is not None and not self._fault_injection_authorized:
            raise NonRetriableDiscoveryDispatchError(
                "fault injection requires an authorized standalone executor",
                failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
            )
        run_id = str(uuid4())
        run_trigger = map_job_trigger_to_run_trigger(request.trigger_type)
        if requested_fault_mode is not None:
            browser_profile_dir = _browser_profile_dir_for_run_id(
                run_id,
                profile_root=self._browser_profile_root,
            )
            cleanup_after = True
            browser_settings: dict[str, object] = {}
            profile_lock = None
        else:
            browser_profile_dir, cleanup_after = self._resolve_profile_dir_for_dispatch(run_id)
            browser_settings = _resolve_browser_settings_payload(
                profile_repository=self._profile_repository,
                tenant_id=request.tenant_id,
                profile_id=request.profile_id,
                run_id=run_id,
                browser_cdp_port_base=self._browser_cdp_port_base,
                browser_cdp_port_range=self._browser_cdp_port_range,
                browser_profile_dir=browser_profile_dir,
                chrome_path=self._browser_chrome_path,
                proxy_server=self._browser_proxy_server,
                use_xvfb=self._browser_use_xvfb,
                nav_timeout_ms=self._browser_nav_timeout_ms,
                cloudflare_timeout_ms=self._browser_cloudflare_timeout_ms,
                cloudflare_reload_retries=self._browser_cloudflare_reload_retries,
                cloudflare_operator_timeout_ms=self._browser_cloudflare_operator_timeout_ms,
                project_detail_timeout_s=self._browser_project_detail_timeout_s,
            )
            profile_lock = (
                _acquire_profile_lock(browser_profile_dir)
                if self._browser_profile_mode == "persistent"
                else None
            )
        try:
            if requested_fault_mode is None:
                self._warm_persistent_profile_if_stale(
                    profile_dir=browser_profile_dir,
                    browser_settings=browser_settings,
                )
            run_values: dict[str, object] = {
                "tenant_id": request.tenant_id,
                "profile_id": request.profile_id,
                "trigger_type": run_trigger,
                "run_id": run_id,
            }
            if request.discovery_job_id is not None:
                run_values["discovery_job_id"] = request.discovery_job_id
            if request.recrawl_request_id is not None:
                run_values["recrawl_request_id"] = request.recrawl_request_id
            self._run_repository.create_run(
                **run_values,
            )
            log_path = None
            log_handle = None
            evidence_writer = None
            if self._artifact_root is not None:
                try:
                    log_path = build_run_log_path(
                        artifact_root=self._artifact_root,
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                    )
                    evidence_writer = BoundedEvidenceWriter(
                        path=log_path,
                        correlation=EvidenceCorrelation(
                            tenant_id=request.tenant_id,
                            run_id=run_id,
                            job_id=request.discovery_job_id or request.evidence_job_id,
                            owner_pid=os.getpid(),
                            child_pid=None,
                            execution_backend=request.execution_backend,
                            release_sha=_RELEASE_SHA,
                        ),
                    )
                except Exception:
                    _logger.warning(
                        "Failed to create discover worker log file (run_id=%s)",
                        run_id,
                        exc_info=True,
                    )
                    log_path = None
            pending_log_events: list[str] = _EvidenceEventBuffer(evidence_writer)
            try:
                pending_log_events.append(
                    make_event(
                        "dispatch_started",
                        run_id=run_id,
                        job_id=request.discovery_job_id or request.evidence_job_id,
                        owner_pid=os.getpid(),
                        execution_backend=request.execution_backend,
                        release_sha=_RELEASE_SHA,
                    )
                )
            except Exception:
                pass
            fault_mode = requested_fault_mode
            fault_source = "test" if request.fault_mode is not None else "operator_cli"
            worker_command = [sys.executable, "-m", "egp_worker.main"]
            worker_timeout_seconds = self._timeout_seconds
            if fault_mode is not None:
                try:
                    worker_command = _fault_worker_command(fault_mode)
                except NonRetriableDiscoveryDispatchError as exc:
                    try:
                        pending_log_events.append(
                            make_event(
                                "fault_injection_invalid_mode",
                                run_id=run_id,
                                fault_mode="invalid",
                                source=fault_source,
                                release_sha=_RELEASE_SHA,
                            )
                        )
                    except Exception:
                        pass
                    self._terminalize_injected_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        fault_mode="invalid",
                        error=str(exc),
                        failure_code=exc.failure_code,
                        pending_log_events=pending_log_events,
                    )
                    _flush_log_events(log_handle, pending_log_events)
                    if log_handle is not None:
                        try:
                            log_handle.close()
                        except Exception:
                            pass
                    if evidence_writer is not None:
                        evidence_writer.close()
                    raise
                if fault_mode == "worker_timeout":
                    worker_timeout_seconds = self._fault_timeout_seconds
                try:
                    pending_log_events.append(
                        make_event(
                            "fault_injection_started",
                            run_id=run_id,
                            fault_mode=fault_mode,
                            source=fault_source,
                            owner_pid=os.getpid(),
                            release_sha=_RELEASE_SHA,
                        )
                    )
                except Exception:
                    pass
            try:
                payload = json.dumps(
                    {
                        "command": "discover",
                        "database_url": self._database_url,
                        "artifact_root": str(self._artifact_root),
                        "artifact_storage_backend": self._artifact_storage_backend,
                        "artifact_bucket": self._artifact_bucket,
                        "artifact_prefix": self._artifact_prefix,
                        "supabase_url": self._supabase_url,
                        "supabase_service_role_key": self._supabase_service_role_key,
                        "tenant_id": request.tenant_id,
                        "run_id": run_id,
                        "agent_job_id": request.discovery_job_id,
                        "agent_claim_token": request.claim_token,
                        "profile_id": request.profile_id,
                        "keyword": request.keyword,
                        "profile": request.profile_type,
                        "trigger_type": run_trigger,
                        "live": request.live,
                        "live_include_documents": True,
                        "browser_settings": browser_settings,
                    },
                    ensure_ascii=False,
                ).encode()
                if fault_mode is not None:
                    payload = json.dumps(
                        {
                            "command": "fault_injection",
                            "run_id": run_id,
                            "fault_mode": fault_mode,
                        },
                        ensure_ascii=False,
                    ).encode()
                stdout_capture = tempfile.SpooledTemporaryFile(
                    max_size=WORKER_STDOUT_SPOOL_LIMIT_BYTES,
                    mode="w+b",
                )
            except Exception as exc:
                if fault_mode is not None:
                    self._terminalize_injected_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        fault_mode=fault_mode,
                        error=str(exc),
                        failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
                        pending_log_events=pending_log_events,
                    )
                else:
                    self._complete_abnormal_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        error=str(exc),
                        failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
                        candidate_reason=CandidateTerminalReason.WORKER_LOST.value,
                    )
                _flush_log_events(log_handle, pending_log_events)
                if log_handle is not None:
                    try:
                        log_handle.close()
                    except Exception:
                        pass
                if evidence_writer is not None:
                    evidence_writer.close()
                raise
            proc = None
            try:
                proc = subprocess.Popen(
                    worker_command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                if evidence_writer is not None:
                    evidence_writer.update_child_pid(getattr(proc, "pid", None))
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
                        **(
                            {
                                "fault_injection": {
                                    "mode": fault_mode,
                                    "source": fault_source,
                                    "release_sha": _RELEASE_SHA,
                                }
                            }
                            if fault_mode is not None
                            else {}
                        ),
                    },
                )
                result_decoder = BoundedResultDecoder()
                has_real_pipes = all(
                    getattr(getattr(proc, name, None), "fileno", None) is not None
                    for name in ("stdin", "stdout", "stderr")
                )
                if has_real_pipes:
                    collected = observe_child_process(
                        proc,
                        payload=payload,
                        writer=evidence_writer or DiscardingEvidenceWriter(),
                        result_decoder=result_decoder,
                        timeout_seconds=worker_timeout_seconds,
                        cancellation_event=cancellation_event,
                    )
                    stderr_text = collected.stderr_tail
                    worker_result = result_decoder.decode()
                    stdout = b""
                else:
                    returned_stdout, stderr = _communicate_with_cancellation(
                        proc,
                        payload=payload,
                        timeout_seconds=worker_timeout_seconds,
                        cancellation_event=cancellation_event,
                    )
                    stdout = _drain_worker_stdout(
                        stdout_capture,
                        returned_stdout,
                        log_handle=None,
                    )
                    if evidence_writer is not None:
                        evidence_writer.write_child("stdout", stdout)
                        if stderr not in {None, b"", ""}:
                            evidence_writer.write_child("stderr", stderr)
                    stderr_text = stderr
                    worker_result = _decode_framed_or_fallback_result(stdout)
                if proc.returncode is not None and proc.returncode < 0:
                    terminated = self._worker_termination_error(
                        tenant_id=request.tenant_id,
                        returncode=int(proc.returncode),
                        run_id=run_id,
                        keyword=request.keyword,
                    )
                    if terminated is not None:
                        termination_error, run_terminalized, candidates_reconciled = terminated
                        if fault_mode is not None:
                            self._append_fault_terminalization_event(
                                pending_log_events=pending_log_events,
                                run_id=run_id,
                                fault_mode=fault_mode,
                                failure_code=termination_error.failure_code,
                                child_pid=getattr(proc, "pid", None),
                                run_terminalized=run_terminalized,
                                candidates_reconciled=candidates_reconciled,
                            )
                            termination_error = _verified_fault_exception(
                                termination_error,
                                fault_mode=fault_mode,
                                returncode=proc.returncode,
                                run_terminalized=run_terminalized,
                                candidates_reconciled=candidates_reconciled,
                            )
                        raise termination_error
                if worker_result is not None:
                    run_status, failure_code = _validate_discovery_worker_result(
                        worker_result,
                        expected_run_id=run_id,
                        keyword=request.keyword,
                    )
                    if run_status == "failed":
                        error = str(worker_result.get("error") or "").strip()
                        detail = f": {error}" if error else ""
                        semantic_error = DiscoverySpawnError(
                            "discover worker reported failed for keyword "
                            f"{request.keyword!r}{detail}",
                            failure_code=(
                                failure_code or DiscoveryFailureCode.WORKER_REPORTED_FAILURE
                            ),
                        )
                        if self._browser_profile_mode == "persistent":
                            self._record_persistent_profile_failure(
                                profile_dir=browser_profile_dir,
                                error=semantic_error,
                            )
                        raise semantic_error
                if proc.returncode not in {0, None}:
                    preview = tail_bounded_preview(stderr_text)
                    _logger.warning(
                        "Discover worker exited non-zero for keyword %r (tenant_id=%s profile_id=%s returncode=%s stderr=%r)",
                        request.keyword,
                        request.tenant_id,
                        request.profile_id,
                        proc.returncode,
                        preview,
                    )
                    non_retriable = _parse_non_retriable_error(stderr_text)
                    if non_retriable is not None:
                        raise non_retriable
                    raise DiscoverySpawnError(
                        f"discover worker exited non-zero for keyword {request.keyword!r}",
                        failure_code=DiscoveryFailureCode.WORKER_EXIT_NONZERO,
                    )
                if worker_result is None:
                    raise DiscoverySpawnError(
                        f"discover worker returned no result for keyword {request.keyword!r}",
                        failure_code=DiscoveryFailureCode.WORKER_RESULT_MISSING,
                    )
                self._emit_discovery_run_metrics(
                    tenant_id=request.tenant_id,
                    run_id=run_id,
                )
                try:
                    pending_log_events.append(
                        make_event(
                            "dispatch_finished",
                            run_id=run_id,
                            owner_pid=os.getpid(),
                            child_pid=getattr(proc, "pid", None),
                            release_sha=_RELEASE_SHA,
                        )
                    )
                except Exception:
                    pass
            except (_DiscoveryLeaseCancellation, ChildProcessCancelled) as exc:
                error_message = (
                    f"discover worker stopped because lease ownership was lost "
                    f"for keyword {request.keyword!r}"
                )
                try:
                    pending_log_events.append(
                        make_event(
                            "dispatch_failed",
                            run_id=run_id,
                            owner_pid=os.getpid(),
                            reason="lease_lost",
                            release_sha=_RELEASE_SHA,
                        )
                    )
                except Exception:
                    pass
                self._complete_abnormal_run(
                    tenant_id=request.tenant_id,
                    run_id=run_id,
                    error=error_message,
                    failure_code=DiscoveryFailureCode.LEASE_LOST,
                    candidate_reason=CandidateTerminalReason.LEASE_LOST.value,
                )
                raise DiscoverySpawnError(
                    error_message,
                    failure_code=DiscoveryFailureCode.LEASE_LOST,
                ) from exc
            except subprocess.TimeoutExpired as exc:
                _kill_process_group(proc)
                error_message = f"discover worker timed out for keyword {request.keyword!r}"
                try:
                    returned_stdout, stderr = proc.communicate()
                    stdout = _drain_worker_stdout(
                        stdout_capture,
                        returned_stdout,
                        log_handle=None,
                    )
                    if evidence_writer is not None:
                        evidence_writer.write_child("stdout", stdout)
                        if stderr not in {None, b"", ""}:
                            evidence_writer.write_child("stderr", stderr)
                    stderr_text = (stderr or exc.stderr) or (
                        self._read_log_tail(log_path) if log_path is not None else None
                    )
                    preview = tail_bounded_preview(stderr_text)
                    _logger.warning(
                        "Discover worker timed out for keyword %r (tenant_id=%s profile_id=%s timeout_seconds=%s stderr=%r)",
                        request.keyword,
                        request.tenant_id,
                        request.profile_id,
                        exc.timeout,
                        preview,
                    )
                except Exception:
                    _logger.warning(
                        "Failed to drain timed-out discover worker diagnostics (run_id=%s)",
                        run_id,
                        exc_info=True,
                    )
                try:
                    pending_log_events.append(
                        make_event(
                            "dispatch_failed",
                            run_id=run_id,
                            owner_pid=os.getpid(),
                            child_pid=getattr(proc, "pid", None),
                            reason="worker_timeout",
                            release_sha=_RELEASE_SHA,
                        )
                    )
                except Exception:
                    pass
                if fault_mode is not None:
                    run_terminalized, candidates_reconciled = self._terminalize_injected_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        fault_mode=fault_mode,
                        error=error_message,
                        failure_code=DiscoveryFailureCode.WORKER_TIMEOUT,
                        pending_log_events=pending_log_events,
                        child_pid=getattr(proc, "pid", None),
                    )
                else:
                    completion = self._complete_abnormal_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        error=error_message,
                        failure_code=DiscoveryFailureCode.WORKER_TIMEOUT,
                        candidate_reason=CandidateTerminalReason.WORKER_TIMEOUT.value,
                    )
                    candidates_reconciled = completion.candidate_reconciliation_succeeded
                    run_terminalized = (
                        completion.run_terminalized or completion.run_already_terminal
                    )
                timeout_error = DiscoverySpawnError(
                    error_message,
                    failure_code=DiscoveryFailureCode.WORKER_TIMEOUT,
                )
                if fault_mode is not None:
                    timeout_error = _verified_fault_exception(
                        timeout_error,
                        fault_mode=fault_mode,
                        returncode=getattr(proc, "returncode", None),
                        run_terminalized=run_terminalized,
                        candidates_reconciled=candidates_reconciled,
                    )
                raise timeout_error from exc
            except DiscoverySpawnError as exc:
                raised_exc: DiscoverySpawnError | NonRetriableDiscoveryDispatchError = exc
                if fault_mode is not None:
                    run_terminalized, candidates_reconciled = self._terminalize_injected_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        fault_mode=fault_mode,
                        error=str(exc),
                        failure_code=exc.failure_code,
                        pending_log_events=pending_log_events,
                        child_pid=(getattr(proc, "pid", None) if proc is not None else None),
                    )
                    raised_exc = _verified_fault_exception(
                        exc,
                        fault_mode=fault_mode,
                        returncode=getattr(proc, "returncode", None),
                        run_terminalized=run_terminalized,
                        candidates_reconciled=candidates_reconciled,
                    )
                else:
                    self._complete_abnormal_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        error=str(exc),
                        failure_code=exc.failure_code,
                        candidate_reason=CandidateTerminalReason.WORKER_LOST.value,
                    )
                try:
                    pending_log_events.append(
                        make_event(
                            "dispatch_failed",
                            run_id=run_id,
                            owner_pid=os.getpid(),
                            child_pid=getattr(proc, "pid", None) if proc is not None else None,
                            reason="spawn_error",
                            release_sha=_RELEASE_SHA,
                        )
                    )
                except Exception:
                    pass
                if raised_exc is exc:
                    raise
                raise raised_exc from exc
            except NonRetriableDiscoveryDispatchError as exc:
                raised_exc = exc
                if (
                    fault_mode is not None
                    and exc.failure_code != DiscoveryFailureCode.WORKER_TERMINATED
                ):
                    run_terminalized, candidates_reconciled = self._terminalize_injected_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        fault_mode=fault_mode,
                        error=str(exc),
                        failure_code=exc.failure_code,
                        pending_log_events=pending_log_events,
                        child_pid=(getattr(proc, "pid", None) if proc is not None else None),
                    )
                    raised_exc = _verified_fault_exception(
                        exc,
                        fault_mode=fault_mode,
                        returncode=getattr(proc, "returncode", None),
                        run_terminalized=run_terminalized,
                        candidates_reconciled=candidates_reconciled,
                    )
                else:
                    self._complete_abnormal_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        error=str(exc),
                        failure_code=exc.failure_code,
                        candidate_reason=(
                            CandidateTerminalReason.WORKER_TERMINATED.value
                            if exc.failure_code == DiscoveryFailureCode.WORKER_TERMINATED
                            else CandidateTerminalReason.WORKER_LOST.value
                        ),
                    )
                try:
                    pending_log_events.append(
                        make_event(
                            "dispatch_failed",
                            run_id=run_id,
                            owner_pid=os.getpid(),
                            child_pid=getattr(proc, "pid", None) if proc is not None else None,
                            reason="non_retriable_error",
                            release_sha=_RELEASE_SHA,
                        )
                    )
                except Exception:
                    pass
                if raised_exc is exc:
                    raise
                raise raised_exc from exc
            except Exception as exc:
                if fault_mode is not None:
                    self._terminalize_injected_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        fault_mode=fault_mode,
                        error=str(exc),
                        failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
                        pending_log_events=pending_log_events,
                        child_pid=getattr(proc, "pid", None) if proc is not None else None,
                    )
                else:
                    self._complete_abnormal_run(
                        tenant_id=request.tenant_id,
                        run_id=run_id,
                        error=str(exc),
                        failure_code=DiscoveryFailureCode.DISPATCH_EXCEPTION,
                        candidate_reason=CandidateTerminalReason.WORKER_LOST.value,
                    )
                try:
                    pending_log_events.append(
                        make_event(
                            "dispatch_failed",
                            run_id=run_id,
                            owner_pid=os.getpid(),
                            reason="unexpected_error",
                            release_sha=_RELEASE_SHA,
                        )
                    )
                except Exception:
                    pass
                _logger.warning(
                    "Failed to spawn discover for keyword %r (tenant_id=%s profile_id=%s)",
                    request.keyword,
                    request.tenant_id,
                    request.profile_id,
                    exc_info=True,
                )
                raise
            finally:
                # Last-resort reap: kill any surviving process group before
                # releasing the profile lock.  Observed in production: one bug
                # produced 27 stray Chrome processes and a permanently locked
                # persistent profile.
                try:
                    if getattr(proc, "poll", None) is not None and proc.poll() is None:
                        _kill_process_group(proc)
                        proc.communicate(timeout=5)
                except Exception:  # noqa: BLE001 - cleanup must never mask the original error
                    _logger.warning("failed to reap discover worker process group", exc_info=True)
                _flush_log_events(log_handle, pending_log_events)
                try:
                    stdout_capture.close()
                except Exception:
                    pass
                if log_handle is not None:
                    try:
                        log_handle.close()
                    except Exception:
                        pass
                if evidence_writer is not None:
                    try:
                        evidence_writer.close()
                    except Exception:
                        pass
                    try:
                        prune_run_evidence(
                            artifact_root=self._artifact_root,
                            tenant_id=request.tenant_id,
                        )
                    except Exception:
                        pass
            if self._browser_profile_mode == "persistent":
                self._record_persistent_profile_success(
                    profile_dir=browser_profile_dir,
                    source="crawl",
                )
            return worker_result
        finally:
            _release_profile_lock(profile_lock)
            if cleanup_after:
                _cleanup_browser_profile_dir(
                    browser_profile_dir,
                    profile_root=self._browser_profile_root,
                )

    def _warm_persistent_profile_if_stale(
        self,
        *,
        profile_dir: Path,
        browser_settings: dict[str, object],
    ) -> None:
        if self._browser_profile_mode != "persistent":
            return
        if not _profile_warm_needed(
            profile_dir,
            stale_after_seconds=self._browser_warmup_stale_after_seconds,
        ):
            _logger.info("Persistent browser profile is fresh; skipping pre-dispatch warm")
            return
        if _profile_warm_operator_action_required(
            profile_dir,
            pause_threshold=self._browser_warmup_failure_pause_threshold,
        ):
            raise DiscoverySpawnError(
                "persistent browser profile Cloudflare warm-up paused; "
                "operator action required: run scripts/run_remote_crawl.sh warm-profile "
                "in foreground and clear Cloudflare"
            )

        from egp_worker.warmup import (
            run_profile_warmup,
            warmup_settings_from_browser_settings,
        )

        _logger.info(
            "Persistent browser profile is stale; running pre-dispatch warm (profile_dir=%s)",
            profile_dir,
        )
        settings = warmup_settings_from_browser_settings(browser_settings)
        try:
            run_profile_warmup(
                settings,
                warm_seconds=self._browser_predispatch_warm_seconds,
                acquire_lock=False,
                status_prefix="PREDISPATCH_WARMUP",
            )
        except Exception as exc:
            consecutive_failures = _write_profile_warm_failure_state(
                profile_dir,
                error=exc,
                pause_threshold=self._browser_warmup_failure_pause_threshold,
            )
            _logger.warning(
                "Persistent browser profile pre-dispatch warm failed "
                "(profile_dir=%s consecutive_failures=%s pause_threshold=%s)",
                profile_dir,
                consecutive_failures,
                self._browser_warmup_failure_pause_threshold,
                exc_info=True,
            )
            if (
                self._browser_warmup_failure_pause_threshold > 0
                and consecutive_failures >= self._browser_warmup_failure_pause_threshold
            ):
                raise DiscoverySpawnError(
                    "persistent browser profile Cloudflare warm-up paused; "
                    "operator action required: run scripts/run_remote_crawl.sh warm-profile "
                    "in foreground and clear Cloudflare"
                ) from exc
            raise DiscoverySpawnError(
                "persistent browser profile pre-dispatch warm failed; "
                "deferring discovery until the next poll"
            ) from exc
        self._record_persistent_profile_success(profile_dir=profile_dir, source="warm")

    def _record_persistent_profile_success(self, *, profile_dir: Path, source: str) -> None:
        try:
            _write_profile_success_state(profile_dir, source=source)
        except Exception:
            _logger.warning(
                "Failed to write persistent browser profile state (profile_dir=%s source=%s)",
                profile_dir,
                source,
                exc_info=True,
            )

    def _record_persistent_profile_failure(
        self,
        *,
        profile_dir: Path,
        error: BaseException,
    ) -> None:
        try:
            _write_profile_crawl_failure_state(profile_dir, error=error)
        except Exception:
            _logger.warning(
                "Failed to invalidate persistent browser profile state after crawl failure "
                "(profile_dir=%s)",
                profile_dir,
                exc_info=True,
            )

    def _emit_discovery_run_metrics(self, *, tenant_id: str, run_id: str) -> None:
        """Emit discovery scan metrics from the worker-written run summary.

        The worker is a one-shot subprocess and cannot host a scrapeable
        ``/metrics`` endpoint, so the API control plane (which owns ``/metrics``)
        reads back the finished run's ``summary_json["keyword_scans"]`` and emits
        the WS2 anomaly/eligibility metrics. Must never fail dispatch.
        """
        try:
            detail = self._run_repository.get_run_detail(tenant_id=tenant_id, run_id=run_id)
        except Exception:
            _logger.warning(
                "Failed to read run detail for discovery metrics (run_id=%s)",
                run_id,
                exc_info=True,
            )
            return
        if detail is None:
            return
        try:
            summary = getattr(getattr(detail, "run", None), "summary_json", None)
            if not isinstance(summary, dict):
                return
            keyword_scans = summary.get("keyword_scans")
            if isinstance(keyword_scans, dict):
                scans: object = keyword_scans.values()
            elif isinstance(keyword_scans, list):
                scans = keyword_scans
            else:
                return
            for scan in scans:
                if isinstance(scan, dict):
                    record_discovery_keyword_scan(scan)
        except Exception:
            _logger.warning(
                "Failed to emit discovery scan metrics (run_id=%s)",
                run_id,
                exc_info=True,
            )

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
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - max(1, int(limit))))
            data = handle.read(max(1, int(limit)))
        return data.decode("utf-8", errors="replace")

    def _reconcile_candidate_attempts(
        self,
        *,
        tenant_id: str,
        run_id: str,
        terminal_reason: str = CandidateTerminalReason.WORKER_LOST.value,
    ) -> bool:
        """Mark any still-accepted discovery candidates as unknown."""
        try:
            repo = create_candidate_attempt_repository(
                database_url=self._database_url,
            )
            count = repo.reconcile_open_candidates(
                tenant_id=tenant_id,
                run_id=run_id,
                terminal_reason=terminal_reason,
            )
            if count > 0:
                _logger.info(
                    "Reconciled %d open candidate attempts for run %s (reason=%s)",
                    count,
                    run_id,
                    terminal_reason,
                )
            return True
        except Exception:
            _logger.warning(
                "Failed to reconcile candidate attempts for run %s",
                run_id,
                exc_info=True,
            )
            return False

    def _mark_active_run_failed(
        self,
        *,
        tenant_id: str,
        run_id: str,
        error: str,
        failure_reason: str,
    ) -> bool:
        try:
            failed_run = self._run_repository.fail_run_if_active(
                tenant_id=tenant_id,
                run_id=run_id,
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
            return False
        if failed_run is not None:
            _logger.warning(
                "Marked discover run %s failed (%s)",
                failed_run.id,
                failure_reason,
            )
        return failed_run is not None

    def _complete_abnormal_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        error: str,
        failure_code: DiscoveryFailureCode,
        candidate_reason: str,
    ) -> AbnormalRunCompletionReport:
        try:
            candidate_repository = create_candidate_attempt_repository(
                database_url=self._database_url,
            )
        except Exception:
            candidate_repository = _UnavailableCandidateRepository()
        report = complete_abnormal_run(
            tenant_id=tenant_id,
            run_id=run_id,
            failure_code=failure_code.value,
            candidate_reason=candidate_reason,
            error=error,
            candidate_repository=candidate_repository,
            run_repository=self._run_repository,
        )
        if not report.succeeded:
            _logger.warning(
                "Abnormal run completion was incomplete "
                "(tenant_id=%s run_id=%s candidate_error=%s run_error=%s)",
                tenant_id,
                run_id,
                report.candidate_reconciliation_error_type,
                report.run_terminalization_error_type,
            )
        return report

    def _terminalize_injected_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        fault_mode: str,
        error: str,
        failure_code: DiscoveryFailureCode,
        pending_log_events: list[str],
        child_pid: int | None = None,
    ) -> tuple[bool, bool]:
        terminal_reason = {
            DiscoveryFailureCode.WORKER_TIMEOUT: CandidateTerminalReason.WORKER_TIMEOUT.value,
            DiscoveryFailureCode.WORKER_TERMINATED: (
                CandidateTerminalReason.WORKER_TERMINATED.value
            ),
        }.get(failure_code, CandidateTerminalReason.WORKER_LOST.value)
        candidates_reconciled = self._reconcile_candidate_attempts(
            tenant_id=tenant_id,
            run_id=run_id,
            terminal_reason=terminal_reason,
        )
        run_terminalized = self._mark_active_run_failed(
            tenant_id=tenant_id,
            run_id=run_id,
            error=error,
            failure_reason=failure_code.value,
        )
        self._append_fault_terminalization_event(
            pending_log_events=pending_log_events,
            run_id=run_id,
            fault_mode=fault_mode,
            failure_code=failure_code,
            child_pid=child_pid,
            run_terminalized=run_terminalized,
            candidates_reconciled=candidates_reconciled,
        )
        return run_terminalized, candidates_reconciled

    @staticmethod
    def _append_fault_terminalization_event(
        *,
        pending_log_events: list[str],
        run_id: str,
        fault_mode: str,
        failure_code: DiscoveryFailureCode,
        child_pid: int | None,
        run_terminalized: bool,
        candidates_reconciled: bool,
    ) -> None:
        try:
            pending_log_events.append(
                make_event(
                    (
                        "fault_injection_terminalized"
                        if run_terminalized
                        else "fault_injection_terminalization_failed"
                    ),
                    run_id=run_id,
                    fault_mode=fault_mode,
                    owner_pid=os.getpid(),
                    child_pid=child_pid,
                    release_sha=_RELEASE_SHA,
                    failure_code=failure_code.value,
                    candidates_reconciled=candidates_reconciled,
                )
            )
        except Exception:
            pass

    def _worker_termination_error(
        self,
        *,
        tenant_id: str,
        returncode: int,
        run_id: str,
        keyword: str,
    ) -> tuple[NonRetriableDiscoveryDispatchError, bool, bool] | None:
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
        candidates_reconciled = self._reconcile_candidate_attempts(
            tenant_id=tenant_id,
            run_id=run_id,
            terminal_reason=CandidateTerminalReason.WORKER_TERMINATED.value,
        )
        run_terminalized = self._mark_active_run_failed(
            tenant_id=tenant_id,
            run_id=run_id,
            error=error_message,
            failure_reason="worker_terminated",
        )
        return (
            NonRetriableDiscoveryDispatchError(
                error_message,
                failure_code=DiscoveryFailureCode.WORKER_TERMINATED,
            ),
            run_terminalized,
            candidates_reconciled,
        )
