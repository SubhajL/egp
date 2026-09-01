#!/usr/bin/env python3
"""Run a bounded remote-crawl supervision interval and postflight check."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import track_bc_verify
from scripts.track_bc_verify import verify_runtime_evidence


MIN_DURATION_SECONDS: float = 120.0
MAX_DURATION_SECONDS: float = 180.0
MAX_TERMINATION_GRACE_SECONDS: float = 30.0
DOCTOR_TIMEOUT_SECONDS: float = 30.0
POSTFLIGHT_SAFETY_MARGIN_SECONDS: float = 15.0
MAX_DOCTOR_OUTPUT_BYTES: int = 256 * 1024


@dataclass(frozen=True, slots=True)
class SupervisionReport:
    """Credential-safe result of one supervised interval."""

    schema_version: int
    stage: str
    status: str
    release_sha: str
    observed_at: str
    deadline_reached: bool
    process_group_reaped: bool
    postflight_runtime_accepted: bool
    errors: tuple[str, ...]


def _is_exact_release_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _observed_at(value: datetime | None) -> str:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=UTC)
    else:
        resolved = resolved.astimezone(UTC)
    return resolved.isoformat()


def _validate_duration(duration_seconds: float) -> None:
    if (
        isinstance(duration_seconds, bool)
        or not isinstance(duration_seconds, (int, float))
        or not math.isfinite(duration_seconds)
        or duration_seconds < MIN_DURATION_SECONDS
        or duration_seconds > MAX_DURATION_SECONDS
    ):
        raise ValueError(
            "duration must be between the configured minimum and maximum seconds"
        )


def _validate_grace(termination_grace_seconds: float) -> None:
    if (
        isinstance(termination_grace_seconds, bool)
        or not isinstance(termination_grace_seconds, (int, float))
        or not math.isfinite(termination_grace_seconds)
        or termination_grace_seconds <= 0
        or termination_grace_seconds > MAX_TERMINATION_GRACE_SECONDS
    ):
        raise ValueError("termination grace must be positive and bounded")


def _validate_command(command: Sequence[str], *, field_name: str) -> list[str]:
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise ValueError(f"{field_name} must be a non-empty command list")
    values = list(command)
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{field_name} must be a non-empty command list")
    return values


def _has_postflight_evidence_window(
    runtime_evidence: Mapping[str, object],
    *,
    duration_seconds: float,
    termination_grace_seconds: float,
) -> bool:
    collected_at = runtime_evidence.get("collected_at")
    if not isinstance(collected_at, str) or not collected_at.strip():
        return False
    try:
        collected_datetime = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if collected_datetime.tzinfo is None:
        return False

    required_seconds = (
        float(duration_seconds)
        + (2 * float(termination_grace_seconds))
        + DOCTOR_TIMEOUT_SECONDS
        + POSTFLIGHT_SAFETY_MARGIN_SECONDS
    )
    evidence_age_seconds = (
        datetime.now(UTC) - collected_datetime.astimezone(UTC)
    ).total_seconds()
    return (
        evidence_age_seconds + required_seconds
        <= track_bc_verify.RUNTIME_EVIDENCE_MAX_AGE_SECONDS
    )


def _group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _signal_group(process_group_id: int, signal_number: signal.Signals) -> None:
    try:
        os.killpg(process_group_id, signal_number)
    except ProcessLookupError:
        return
    except OSError:
        return


def _wait_for_process_group_absent(
    process: subprocess.Popen[bytes],
    *,
    process_group_id: int,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        if process.poll() is None:
            try:
                process.wait(timeout=min(0.05, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is not None and not _group_exists(process_group_id):
            return True
        time.sleep(0.01)
    if process.poll() is None:
        try:
            process.wait(timeout=0.05)
        except subprocess.TimeoutExpired:
            pass
    return process.poll() is not None and not _group_exists(process_group_id)


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    process_group_id: int,
    termination_grace_seconds: float,
) -> bool:
    _signal_group(process_group_id, signal.SIGTERM)
    if _wait_for_process_group_absent(
        process,
        process_group_id=process_group_id,
        timeout_seconds=termination_grace_seconds,
    ):
        return True

    _signal_group(process_group_id, signal.SIGKILL)
    return _wait_for_process_group_absent(
        process,
        process_group_id=process_group_id,
        timeout_seconds=termination_grace_seconds,
    )


def _install_interruption_handlers(
    interruption_event: threading.Event,
) -> tuple[object, object]:
    def _request_interruption(_signal_number: int, _frame: object) -> None:
        interruption_event.set()

    previous_sigterm = signal.signal(signal.SIGTERM, _request_interruption)
    try:
        previous_sighup = signal.signal(signal.SIGHUP, _request_interruption)
    except BaseException:  # noqa: BLE001
        signal.signal(signal.SIGTERM, previous_sigterm)
        raise
    return previous_sigterm, previous_sighup


def _restore_interruption_handlers(previous_handlers: tuple[object, object]) -> None:
    previous_sigterm, previous_sighup = previous_handlers
    signal.signal(signal.SIGTERM, previous_sigterm)
    signal.signal(signal.SIGHUP, previous_sighup)


def _run_bounded_doctor(
    command: Sequence[str],
    *,
    interruption_event: threading.Event | None = None,
) -> Mapping[str, object] | None:
    if interruption_event is not None and interruption_event.is_set():
        return None
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ValueError):
        return None

    process_group_id = int(process.pid)
    output = bytearray()
    selector = selectors.DefaultSelector()

    def _terminate_if_interrupted() -> bool:
        if interruption_event is None or not interruption_event.is_set():
            return False
        _terminate_process_group(
            process,
            process_group_id=process_group_id,
            termination_grace_seconds=1.0,
        )
        return True

    try:
        if process.stdout is None:
            _terminate_process_group(
                process,
                process_group_id=process_group_id,
                termination_grace_seconds=1.0,
            )
            return None
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + DOCTOR_TIMEOUT_SECONDS
        while selector.get_map():
            if _terminate_if_interrupted():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_group(
                    process,
                    process_group_id=process_group_id,
                    termination_grace_seconds=1.0,
                )
                return None
            for key, _mask in selector.select(timeout=min(0.05, remaining)):
                if _terminate_if_interrupted():
                    return None
                chunk = os.read(key.fileobj.fileno(), 65_536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if len(output) + len(chunk) > MAX_DOCTOR_OUTPUT_BYTES:
                    _terminate_process_group(
                        process,
                        process_group_id=process_group_id,
                        termination_grace_seconds=1.0,
                    )
                    return None
                output.extend(chunk)

        while process.poll() is None:
            if _terminate_if_interrupted():
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_group(
                    process,
                    process_group_id=process_group_id,
                    termination_grace_seconds=1.0,
                )
                return None
            try:
                process.wait(timeout=min(0.05, remaining))
            except subprocess.TimeoutExpired:
                continue
        if _terminate_if_interrupted():
            return None
        if process.returncode != 0 or _group_exists(process_group_id):
            if _group_exists(process_group_id):
                _terminate_process_group(
                    process,
                    process_group_id=process_group_id,
                    termination_grace_seconds=1.0,
                )
            return None
        decoded = json.loads(bytes(output).decode("utf-8"))
        return decoded if isinstance(decoded, Mapping) else None
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        _terminate_process_group(
            process,
            process_group_id=process_group_id,
            termination_grace_seconds=1.0,
        )
        return None
    finally:
        selector.close()


def _postflight(
    *,
    doctor_command: Sequence[str],
    runtime_evidence: Mapping[str, object],
    expected_release_sha: str,
    interruption_event: threading.Event | None = None,
) -> tuple[bool, str | None]:
    if interruption_event is not None and interruption_event.is_set():
        return False, None
    doctor = _run_bounded_doctor(
        doctor_command,
        interruption_event=interruption_event,
    )
    if interruption_event is not None and interruption_event.is_set():
        return False, None
    if doctor is None:
        return False, "postflight_doctor_invalid"
    try:
        evidence = deepcopy(dict(runtime_evidence))
        evidence["doctor"] = dict(doctor)
        report = verify_runtime_evidence(
            evidence,
            expected_release_sha=expected_release_sha,
        )
    except (TypeError, ValueError):
        return False, "postflight_runtime_rejected"
    if report.status != "accepted":
        return False, "postflight_runtime_rejected"
    return True, None


def supervise(
    command: Sequence[str],
    doctor_command: Sequence[str],
    duration_seconds: float,
    expected_release_sha: str,
    runtime_evidence: Mapping[str, object],
    termination_grace_seconds: float = 10.0,
    observed_at: datetime | None = None,
    interruption_event: threading.Event | None = None,
) -> SupervisionReport:
    """Supervise a process group for one bounded interval and run postflight."""

    _validate_duration(duration_seconds)
    _validate_grace(termination_grace_seconds)
    if not _is_exact_release_sha(expected_release_sha):
        raise ValueError(
            "expected release must be an exact 40-character lowercase Git SHA"
        )
    command_values = _validate_command(command, field_name="command")
    doctor_values = _validate_command(doctor_command, field_name="doctor_command")
    if not isinstance(runtime_evidence, Mapping):
        raise ValueError("runtime evidence must be a mapping")

    try:
        preflight_report = verify_runtime_evidence(
            runtime_evidence,
            expected_release_sha=expected_release_sha,
        )
    except (TypeError, ValueError):
        preflight_report = None
    if preflight_report is None or preflight_report.status != "accepted":
        return SupervisionReport(
            schema_version=1,
            stage="supervised",
            status="rejected",
            release_sha=expected_release_sha,
            observed_at=_observed_at(observed_at),
            deadline_reached=False,
            process_group_reaped=True,
            postflight_runtime_accepted=False,
            errors=("preflight_runtime_rejected",),
        )
    if not _has_postflight_evidence_window(
        runtime_evidence,
        duration_seconds=duration_seconds,
        termination_grace_seconds=termination_grace_seconds,
    ):
        return SupervisionReport(
            schema_version=1,
            stage="supervised",
            status="rejected",
            release_sha=expected_release_sha,
            observed_at=_observed_at(observed_at),
            deadline_reached=False,
            process_group_reaped=True,
            postflight_runtime_accepted=False,
            errors=("preflight_evidence_window_too_short",),
        )

    errors: list[str] = []
    deadline_reached = False
    process_group_reaped = False
    interrupted = False
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command_values,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        process_group_id = int(process.pid)
        deadline = time.monotonic() + float(duration_seconds)
        while True:
            if interruption_event is not None and interruption_event.is_set():
                interrupted = True
                _append_unique(errors, "supervision_interrupted")
                process_group_reaped = _terminate_process_group(
                    process,
                    process_group_id=process_group_id,
                    termination_grace_seconds=float(termination_grace_seconds),
                )
                break
            return_code = process.poll()
            now = time.monotonic()
            if return_code is not None:
                _append_unique(errors, "watcher_exited_before_deadline")
                break
            if now >= deadline:
                deadline_reached = True
                process_group_reaped = _terminate_process_group(
                    process,
                    process_group_id=process_group_id,
                    termination_grace_seconds=float(termination_grace_seconds),
                )
                break
            time.sleep(min(0.05, deadline - now))
    except (OSError, ValueError):
        _append_unique(errors, "watcher_start_failed")
    finally:
        if process is not None:
            process_group_id = int(process.pid)
            if not process_group_reaped or _group_exists(process_group_id):
                process_group_reaped = _terminate_process_group(
                    process,
                    process_group_id=process_group_id,
                    termination_grace_seconds=float(termination_grace_seconds),
                )
            try:
                process.wait(timeout=float(termination_grace_seconds))
            except (OSError, subprocess.TimeoutExpired):
                _append_unique(errors, "watcher_reap_failed")

    if interruption_event is not None and interruption_event.is_set():
        interrupted = True
        deadline_reached = False
        _append_unique(errors, "supervision_interrupted")

    postflight_runtime_accepted = False
    postflight_error = None
    if not interrupted and (not errors or "watcher_exited_before_deadline" in errors):
        postflight_runtime_accepted, postflight_error = _postflight(
            doctor_command=doctor_values,
            runtime_evidence=runtime_evidence,
            expected_release_sha=expected_release_sha,
            interruption_event=interruption_event,
        )
        if postflight_error is not None:
            _append_unique(errors, postflight_error)
        if interruption_event is not None and interruption_event.is_set():
            interrupted = True
            postflight_runtime_accepted = False
            _append_unique(errors, "supervision_interrupted")
    if interruption_event is not None and interruption_event.is_set():
        interrupted = True
        postflight_runtime_accepted = False
        _append_unique(errors, "supervision_interrupted")
    if not process_group_reaped:
        _append_unique(errors, "process_group_not_reaped")

    return SupervisionReport(
        schema_version=1,
        stage="supervised",
        status="accepted" if not errors and postflight_runtime_accepted else "rejected",
        release_sha=expected_release_sha,
        observed_at=_observed_at(observed_at),
        deadline_reached=deadline_reached,
        process_group_reaped=process_group_reaped,
        postflight_runtime_accepted=postflight_runtime_accepted,
        errors=tuple(errors),
    )


def _append_unique(errors: list[str], error: str) -> None:
    if error not in errors:
        errors.append(error)


def _error_payload(error: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": "supervised",
        "status": "rejected",
        "errors": [error],
    }


def _render_payload(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _load_json_file(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _load_command_json(raw: str) -> list[str] | None:
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    try:
        return _validate_command(payload, field_name="command")
    except ValueError:
        return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", required=True, type=float)
    parser.add_argument("--expected-release-sha", required=True)
    parser.add_argument("--runtime-evidence", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--command-json", required=True)
    parser.add_argument("--doctor-command-json", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the supervised interval CLI with sanitized output only."""

    args = _build_parser().parse_args(argv)
    if not _is_exact_release_sha(args.expected_release_sha):
        print(_render_payload(_error_payload("invalid_expected_release_sha")))
        return 2
    runtime_evidence = _load_json_file(args.runtime_evidence)
    command = _load_command_json(args.command_json)
    doctor_command = _load_command_json(args.doctor_command_json)
    if runtime_evidence is None:
        print(_render_payload(_error_payload("invalid_runtime_evidence")))
        return 2
    if command is None or doctor_command is None:
        print(_render_payload(_error_payload("invalid_command")))
        return 2

    interruption_event = threading.Event()
    previous_handlers = _install_interruption_handlers(interruption_event)
    try:
        try:
            report = supervise(
                command=command,
                doctor_command=doctor_command,
                duration_seconds=args.duration_seconds,
                expected_release_sha=args.expected_release_sha,
                runtime_evidence=runtime_evidence,
                interruption_event=interruption_event,
            )
        except ValueError:
            print(_render_payload(_error_payload("invalid_supervision_input")))
            return 2
        rendered = _render_payload(asdict(report))
        if args.output is not None:
            try:
                args.output.write_text(f"{rendered}\n", encoding="utf-8")
            except OSError:
                print(_render_payload(_error_payload("output_write_failed")))
                return 2
        print(rendered)
        return 0 if report.status == "accepted" else 1
    finally:
        _restore_interruption_handlers(previous_handlers)


if __name__ == "__main__":
    raise SystemExit(main())
