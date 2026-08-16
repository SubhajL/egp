"""Ordered, redacted, bounded evidence for subprocess-backed work."""

from __future__ import annotations

import json
import os
import selectors
import signal
import stat as stat_module
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO

from egp_observability.logging import (
    RESULT_FRAME_BEGIN,
    RESULT_FRAME_END,
    redact_preview,
)


DEFAULT_MAX_LINE_BYTES = 16 * 1024
DEFAULT_MAX_RECORDS = 20_000
DEFAULT_LIFECYCLE_RESERVE_RECORDS = 64
DEFAULT_MAX_RESULT_BYTES = 256 * 1024
DEFAULT_MAX_TAIL_BYTES = 64 * 1024
DEFAULT_MAX_LOG_BYTES = 8 * 1024 * 1024
DEFAULT_LIFECYCLE_RESERVE_BYTES = 128 * 1024
DEFAULT_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_MAX_TENANT_BYTES = 512 * 1024 * 1024


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact_preview(value)
    if isinstance(value, dict):
        return {str(key): _redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class EvidenceCorrelation:
    tenant_id: str
    run_id: str
    job_id: str | None
    owner_pid: int | None
    child_pid: int | None
    execution_backend: str
    release_sha: str | None


class BoundedEvidenceWriter:
    """Serialize all child/lifecycle evidence through one ordered writer.

    Child text is converted to complete lines, redacted, encoded, and only then
    written. A reserved portion of the total budget remains available for final
    lifecycle evidence after noisy child output is truncated.
    """

    def __init__(
        self,
        *,
        path: Path,
        correlation: EvidenceCorrelation,
        max_total_bytes: int = DEFAULT_MAX_LOG_BYTES,
        lifecycle_reserve_bytes: int = DEFAULT_LIFECYCLE_RESERVE_BYTES,
        max_line_bytes: int = DEFAULT_MAX_LINE_BYTES,
        max_records: int = DEFAULT_MAX_RECORDS,
        lifecycle_reserve_records: int = DEFAULT_LIFECYCLE_RESERVE_RECORDS,
    ) -> None:
        self.path = path
        self._correlation = correlation
        self._max_total_bytes = max(1, int(max_total_bytes))
        self._lifecycle_reserve_bytes = min(
            self._max_total_bytes, max(0, int(lifecycle_reserve_bytes))
        )
        self._max_line_bytes = max(1, int(max_line_bytes))
        self._max_records = max(1, int(max_records))
        self._lifecycle_reserve_records = min(
            self._max_records,
            max(0, int(lifecycle_reserve_records)),
        )
        self._buffers = {"stdout": bytearray(), "stderr": bytearray()}
        self._line_overflow = {"stdout": False, "stderr": False}
        self._seq = 0
        self._records = 0
        self._child_truncated = False
        self._closed = False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle: BinaryIO = path.open("xb")
        self._written_bytes = 0

    def update_child_pid(self, child_pid: int | None) -> None:
        self._correlation = EvidenceCorrelation(
            **{**asdict(self._correlation), "child_pid": child_pid}
        )

    def write_child(self, stream: str, data: bytes | str) -> None:
        if self._closed:
            return
        if stream not in self._buffers:
            raise ValueError(f"unsupported child stream {stream!r}")
        raw = data if isinstance(data, bytes) else data.encode("utf-8", errors="replace")
        buffer = self._buffers[stream]
        while raw:
            if self._line_overflow[stream]:
                newline = raw.find(b"\n")
                if newline < 0:
                    return
                self._write_child_line(stream, bytes(buffer), line_truncated=True)
                buffer.clear()
                self._line_overflow[stream] = False
                raw = raw[newline + 1 :]
                continue

            newline = raw.find(b"\n")
            segment = raw if newline < 0 else raw[:newline]
            capacity = self._max_line_bytes - len(buffer)
            if len(segment) > capacity:
                buffer.extend(segment[:capacity])
                self._line_overflow[stream] = True
                if newline < 0:
                    return
                self._write_child_line(stream, bytes(buffer), line_truncated=True)
                buffer.clear()
                self._line_overflow[stream] = False
                raw = raw[newline + 1 :]
                continue

            buffer.extend(segment)
            if newline < 0:
                return
            self._write_child_line(stream, bytes(buffer), line_truncated=False)
            buffer.clear()
            raw = raw[newline + 1 :]

    def write_lifecycle(self, event: str, **extra: object) -> None:
        record = self._base_record(event=event)
        for key, value in extra.items():
            record[key] = value
        self._write_record(record, child=False)

    def close(self) -> None:
        if self._closed:
            return
        for stream, buffer in self._buffers.items():
            if buffer or self._line_overflow[stream]:
                self._write_child_line(
                    stream,
                    bytes(buffer),
                    line_truncated=self._line_overflow[stream],
                )
                buffer.clear()
                self._line_overflow[stream] = False
        try:
            self._handle.flush()
        finally:
            self._handle.close()
            self._closed = True

    def _write_child_line(
        self,
        stream: str,
        line: bytes,
        *,
        line_truncated: bool,
    ) -> None:
        if self._child_truncated:
            return
        decoded = line.decode("utf-8", errors="replace")
        encoded = decoded.encode("utf-8")
        if len(encoded) > self._max_line_bytes:
            decoded = encoded[: self._max_line_bytes].decode("utf-8", errors="ignore")
            line_truncated = True
        record = self._base_record(event="child_output")
        record.update(
            {
                "stream": stream,
                "message": redact_preview(decoded),
                "line_truncated": line_truncated,
            }
        )
        if not self._write_record(record, child=True):
            self._child_truncated = True
            self.write_lifecycle(
                "evidence_truncated",
                reason="child_output_budget",
            )

    def _base_record(self, *, event: str) -> dict[str, object]:
        return {
            "event": event,
            "tenant_id": self._correlation.tenant_id,
            "run_id": self._correlation.run_id,
            "job_id": self._correlation.job_id,
            "owner_pid": self._correlation.owner_pid,
            "child_pid": self._correlation.child_pid,
            "execution_backend": self._correlation.execution_backend,
            "release_sha": self._correlation.release_sha,
        }

    def _write_record(self, record: dict[str, object], *, child: bool) -> bool:
        record_limit = self._max_records
        if child:
            record_limit -= self._lifecycle_reserve_records
        if self._closed or self._records >= max(0, record_limit):
            return False
        next_seq = self._seq + 1
        payload = _redact_value({"seq": next_seq, **record})
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        limit = self._max_total_bytes
        if child:
            limit -= self._lifecycle_reserve_bytes
        if self._written_bytes + len(encoded) > max(0, limit):
            return False
        self._handle.write(encoded)
        self._handle.flush()
        self._written_bytes += len(encoded)
        self._seq = next_seq
        self._records += 1
        return True


class DiscardingEvidenceWriter:
    """No-persistence sink used when the durable evidence path is unavailable."""

    def update_child_pid(self, child_pid: int | None) -> None:
        del child_pid

    def write_child(self, stream: str, data: bytes | str) -> None:
        del stream, data

    def write_lifecycle(self, event: str, **extra: object) -> None:
        del event, extra

    def close(self) -> None:
        return None


class BoundedResultDecoder:
    """Keep only a bounded raw stdout tail and decode framed-first."""

    def __init__(self, *, max_bytes: int = DEFAULT_MAX_RESULT_BYTES) -> None:
        self._max_bytes = max(1, int(max_bytes))
        self._buffer = bytearray()
        self._frame_probe = bytearray()
        self._saw_frame = False

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes | str) -> None:
        raw = data if isinstance(data, bytes) else data.encode("utf-8", errors="replace")
        marker = RESULT_FRAME_BEGIN.encode()
        probe = bytes(self._frame_probe) + raw
        if marker in probe:
            self._saw_frame = True
        overlap = max(0, len(marker) - 1)
        self._frame_probe = bytearray(probe[-overlap:]) if overlap else bytearray()
        self._buffer.extend(raw)
        if len(self._buffer) > self._max_bytes:
            del self._buffer[: len(self._buffer) - self._max_bytes]

    def decode(self) -> dict[str, object] | None:
        text = self._buffer.decode("utf-8", errors="replace")
        begin_index = text.rfind(RESULT_FRAME_BEGIN)
        end_index = text.rfind(RESULT_FRAME_END)
        if self._saw_frame:
            if begin_index < 0 or end_index <= begin_index:
                return None
            candidate = text[begin_index + len(RESULT_FRAME_BEGIN) : end_index].strip()
            try:
                decoded = json.loads(candidate)
            except json.JSONDecodeError:
                return None
            return decoded if isinstance(decoded, dict) else None
        for line in reversed(text.splitlines()):
            try:
                decoded = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
        return None


@dataclass(frozen=True, slots=True)
class CollectedProcessResult:
    returncode: int
    stderr_tail: str | None


class ChildProcessCancelled(RuntimeError):
    """Raised after cancellation kills and reaps the child process group."""


def _kill_and_reap(proc: subprocess.Popen[bytes]) -> None:
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int):
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def observe_child_process(
    proc: subprocess.Popen[bytes],
    *,
    payload: bytes,
    writer: BoundedEvidenceWriter | DiscardingEvidenceWriter,
    result_decoder: BoundedResultDecoder,
    timeout_seconds: float,
    cancellation_event,
) -> CollectedProcessResult:
    """Drain stdout/stderr with one selector and one sequence authority."""

    if proc.stdin is None or proc.stdout is None or proc.stderr is None:
        raise ValueError("observed child requires stdin/stdout/stderr pipes")
    writer.update_child_pid(getattr(proc, "pid", None))
    try:
        proc.stdin.write(payload)
        proc.stdin.close()
    except BrokenPipeError:
        pass

    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    stderr_tail = ""
    try:
        while selector.get_map():
            if cancellation_event is not None and cancellation_event.is_set():
                _kill_and_reap(proc)
                raise ChildProcessCancelled("child process cancelled and reaped")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_and_reap(proc)
                raise subprocess.TimeoutExpired(proc.args, timeout_seconds)
            for key, _mask in selector.select(timeout=min(0.1, remaining)):
                stream = str(key.data)
                chunk = os.read(key.fileobj.fileno(), 65_536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if stream == "stdout":
                    result_decoder.feed(chunk)
                else:
                    stderr_tail = (stderr_tail + chunk.decode("utf-8", errors="replace"))[
                        -DEFAULT_MAX_TAIL_BYTES:
                    ]
                writer.write_child(stream, chunk)
        returncode = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        selector.close()
    return CollectedProcessResult(
        returncode=int(returncode),
        stderr_tail=redact_preview(stderr_tail).strip() or None,
    )


def safe_evidence_segment(value: str, *, field_name: str) -> str:
    """Reject path traversal and platform separator ambiguity."""

    normalized = str(value).strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or Path(normalized).name != normalized
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError(f"invalid {field_name}")
    return normalized


def build_run_log_path(*, artifact_root: Path, tenant_id: str, run_id: str) -> Path:
    """Build one contained run-log path from validated identity segments."""

    tenants_root = (artifact_root / "tenants").resolve()
    tenant_segment = safe_evidence_segment(tenant_id, field_name="tenant_id")
    run_segment = safe_evidence_segment(run_id, field_name="run_id")
    path = tenants_root / tenant_segment / "runs" / run_segment / "worker.log"
    path.parent.resolve(strict=False).relative_to(tenants_root)
    return path


def _open_evidence_runs_dir(*, artifact_root: Path, tenant_id: str) -> tuple[int, Path]:
    """Open the tenant runs directory one no-follow segment at a time."""

    tenant_segment = safe_evidence_segment(tenant_id, field_name="tenant_id")
    resolved_root = artifact_root.resolve()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    opened: list[int] = []
    try:
        current_fd = os.open(resolved_root, flags)
        opened.append(current_fd)
        for segment in ("tenants", tenant_segment, "runs"):
            current_fd = os.open(segment, flags, dir_fd=current_fd)
            opened.append(current_fd)
        runs_fd = opened.pop()
        return runs_fd, resolved_root / "tenants" / tenant_segment / "runs"
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _run_log_entries(*, runs_fd: int, runs_root: Path) -> list[tuple[float, int, str, Path]]:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    directory_flags = flags | os.O_DIRECTORY
    logs: list[tuple[float, int, str, Path]] = []
    for run_name in os.listdir(runs_fd):
        try:
            safe_evidence_segment(run_name, field_name="run_id")
            run_fd = os.open(run_name, directory_flags, dir_fd=runs_fd)
        except (OSError, ValueError):
            continue
        try:
            try:
                log_fd = os.open("worker.log", flags, dir_fd=run_fd)
            except OSError:
                continue
            try:
                log_stat = os.fstat(log_fd)
            finally:
                os.close(log_fd)
            if stat_module.S_ISREG(log_stat.st_mode):
                logs.append(
                    (
                        log_stat.st_mtime,
                        log_stat.st_size,
                        run_name,
                        runs_root / run_name / "worker.log",
                    )
                )
        finally:
            os.close(run_fd)
    return logs


def _unlink_run_log(*, runs_fd: int, run_name: str) -> bool:
    """Delete worker.log relative to a verified no-follow run directory."""

    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        safe_evidence_segment(run_name, field_name="run_id")
        run_fd = os.open(run_name, flags | os.O_DIRECTORY, dir_fd=runs_fd)
    except (OSError, ValueError):
        return False
    try:
        try:
            log_fd = os.open("worker.log", flags, dir_fd=run_fd)
        except OSError:
            return False
        try:
            if not stat_module.S_ISREG(os.fstat(log_fd).st_mode):
                return False
        finally:
            os.close(log_fd)
        os.unlink("worker.log", dir_fd=run_fd)
        return True
    except OSError:
        return False
    finally:
        os.close(run_fd)


def prune_run_evidence(
    *,
    artifact_root: Path,
    tenant_id: str,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    max_tenant_bytes: int = DEFAULT_MAX_TENANT_BYTES,
    now_timestamp: float | None = None,
) -> list[Path]:
    """Enforce age/quota on exact run logs, never profiles or manifests."""

    now = time.time() if now_timestamp is None else float(now_timestamp)
    removed: list[Path] = []
    remaining: list[tuple[float, int, str, Path]] = []
    try:
        runs_fd, runs_root = _open_evidence_runs_dir(
            artifact_root=artifact_root,
            tenant_id=tenant_id,
        )
    except FileNotFoundError:
        return removed
    try:
        for modified_at, size, run_name, path in _run_log_entries(
            runs_fd=runs_fd,
            runs_root=runs_root,
        ):
            if max_age_seconds >= 0 and now - modified_at > max_age_seconds:
                if _unlink_run_log(runs_fd=runs_fd, run_name=run_name):
                    removed.append(path)
                continue
            remaining.append((modified_at, size, run_name, path))

        total_bytes = sum(size for _mtime, size, _run_name, _path in remaining)
        for _mtime, size, run_name, path in sorted(remaining):
            if total_bytes <= max(0, int(max_tenant_bytes)):
                break
            if _unlink_run_log(runs_fd=runs_fd, run_name=run_name):
                removed.append(path)
                total_bytes -= size
    finally:
        os.close(runs_fd)
    return removed


def read_bounded_redacted_log(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_LOG_BYTES,
) -> str:
    """Read at most a bounded tail and redact legacy raw evidence defensively."""

    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max(1, int(max_bytes))))
        data = handle.read(max(1, int(max_bytes)))
    return redact_preview(data.decode("utf-8", errors="replace"))
