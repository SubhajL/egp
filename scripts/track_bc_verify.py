#!/usr/bin/env python3
"""Verify sanitized runtime evidence for the Track B/C release gate."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID

from psycopg import connect

from egp_crawler_core.profile_lock import is_profile_locked
from egp_db.artifact_store import ArtifactStore
from egp_observability.logging import redact_preview
from egp_observability.subprocess_evidence import DEFAULT_MAX_LOG_BYTES


RELEASE_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
PYTHON_ROLES = (
    "migrate",
    "api",
    "webhook-executor",
    "crawler-agent-inbox-executor",
    "discovery-executor",
)
HEARTBEAT_MAX_AGE_SECONDS = 90
RUNTIME_EVIDENCE_MAX_AGE_SECONDS = 300
CLAIMABLE_QUEUE_MAX_AGE_SECONDS = 43_200
CANARY_RUN_MAX_AGE_SECONDS = 3_600
RECEIPT_FUTURE_SKEW_SECONDS = 60
ACCEPTANCE_BUNDLE_STAGES = ("runtime", "canary", "supervised")
ROLLBACK_CHECK_NAMES = (
    "launchd_uninstalled",
    "watcher_stopped",
    "tunnel_closed",
    "discovery_executor_zero",
)
ROLLBACK_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "status",
        "release_sha",
        "observed_at",
        "checks",
    }
)
BUNDLE_CHECK_NAMES = (
    "runtime_receipt",
    "canary_receipt",
    "supervised_receipt",
    "rollback_receipt",
    "rollback_checks",
)
CHECK_NAMES = (
    "source_release_sha",
    "runtime_evidence_fresh",
    "role_revisions",
    "mac_release_sha",
    "discovery_executor_replicas",
    "crawler_agent_protocol",
    "profile_execution_backend",
    "agent_pending_jobs",
    "doctor_ready",
    "doctor_unblocked",
    "heartbeat_online",
    "heartbeat_fresh",
    "profile_ready",
    "profile_unlocked",
    "claimable_queue_age",
)
CANARY_CHECK_NAMES = (
    "job_run_correlated",
    "job_status",
    "run_status",
    "run_fresh",
    "open_candidate_count",
    "persisted_candidate_count",
    "artifact_record_count",
    "artifact_retrievable",
    "evidence_jsonl",
    "evidence_bounded",
    "evidence_redacted",
    "evidence_correlation_match",
    "evidence_release_sha",
    "evidence_terminal_event",
    "child_process_stopped",
    "profile_unlocked",
)
CANARY_JOB_STATUSES = frozenset({"dispatched", "pending", "failed", "result_received"})
CANARY_RUN_STATUSES = frozenset(
    {"queued", "running", "succeeded", "partial", "failed", "cancelled"}
)
STAGE_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "status",
        "release_sha",
        "observed_at",
        "checks",
        "errors",
    }
)
SUPERVISED_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "status",
        "release_sha",
        "observed_at",
        "deadline_reached",
        "process_group_reaped",
        "postflight_runtime_accepted",
        "errors",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeVerificationReport:
    """Credential-safe result of the runtime evidence verification."""

    schema_version: int
    stage: str
    status: str
    release_sha: str
    observed_at: str
    checks: dict[str, bool]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CanaryVerificationReport:
    """Credential-safe result of the canary-chain verification."""

    schema_version: int
    stage: str
    status: str
    release_sha: str
    observed_at: str
    checks: dict[str, bool]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AcceptanceBundleReport:
    """Credential-safe result of the complete acceptance bundle verification."""

    schema_version: int
    stage: str
    status: str
    release_sha: str
    observed_at: str
    checks: dict[str, bool]
    errors: tuple[str, ...]


def _is_exact_release_sha(value: object) -> bool:
    return isinstance(value, str) and RELEASE_SHA_PATTERN.fullmatch(value) is not None


def _is_exact_image_id(value: object) -> bool:
    return isinstance(value, str) and IMAGE_ID_PATTERN.fullmatch(value) is not None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _observed_at(value: datetime | None) -> str:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=UTC)
    else:
        resolved = resolved.astimezone(UTC)
    return resolved.isoformat()


def _empty_checks() -> dict[str, bool]:
    return {name: False for name in CHECK_NAMES}


def _empty_canary_checks() -> dict[str, bool]:
    return {name: False for name in CANARY_CHECK_NAMES}


def _append_error(errors: list[str], error: str) -> None:
    if error not in errors:
        errors.append(error)


def _is_nonnegative_number(value: object, *, maximum: int) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
        and value <= maximum
    )


def verify_runtime_evidence(
    evidence: Mapping[str, object],
    *,
    expected_release_sha: str,
    observed_at: datetime | None = None,
    max_evidence_age_seconds: int = RUNTIME_EVIDENCE_MAX_AGE_SECONDS,
    max_heartbeat_age_seconds: int = HEARTBEAT_MAX_AGE_SECONDS,
    max_oldest_claimable_age_seconds: int = CLAIMABLE_QUEUE_MAX_AGE_SECONDS,
) -> RuntimeVerificationReport:
    """Verify the locked Track B/C runtime invariants without echoing evidence."""

    if not _is_exact_release_sha(expected_release_sha):
        raise ValueError(
            "expected release must be an exact 40-character lowercase Git SHA"
        )
    if type(max_evidence_age_seconds) is not int or max_evidence_age_seconds < 0:
        raise ValueError("max_evidence_age_seconds must be a nonnegative integer")

    checks = _empty_checks()
    errors: list[str] = []
    reference = _utc_datetime(observed_at)

    checks["runtime_evidence_fresh"] = _receipt_is_fresh(
        _parse_utc_timestamp(evidence.get("collected_at")),
        reference=reference,
        max_age_seconds=max_evidence_age_seconds,
        errors=errors,
        stale_error="runtime_evidence_stale",
        future_error="runtime_evidence_future",
        invalid_error="runtime_evidence_timestamp_invalid",
    )

    source_release_sha = evidence.get("source_release_sha")
    checks["source_release_sha"] = (
        _is_exact_release_sha(source_release_sha)
        and source_release_sha == expected_release_sha
    )
    if not checks["source_release_sha"]:
        _append_error(errors, "source_release_sha_mismatch")

    role_revisions = _as_mapping(evidence.get("role_revisions"))
    role_checks_pass = True
    for role in PYTHON_ROLES:
        role_evidence = (
            _as_mapping(role_revisions.get(role))
            if role_revisions is not None
            else None
        )
        revision_pass = role_evidence is not None and all(
            _is_exact_release_sha(role_evidence.get(field))
            and role_evidence.get(field) == expected_release_sha
            for field in ("oci_revision", "baked_release_sha")
        )
        if not revision_pass:
            _append_error(errors, f"role_{role}_revision_mismatch")
        image_pass = (
            role_evidence is not None
            and _is_exact_image_id(role_evidence.get("image_id"))
            and _is_exact_image_id(role_evidence.get("container_image_id"))
            and (
                role_evidence.get("image_id") == role_evidence.get("container_image_id")
            )
        )
        if not image_pass:
            _append_error(errors, f"role_{role}_image_identity_mismatch")
        role_checks_pass = role_checks_pass and revision_pass and image_pass
    checks["role_revisions"] = role_checks_pass

    mac_release_sha = evidence.get("mac_release_sha")
    checks["mac_release_sha"] = (
        _is_exact_release_sha(mac_release_sha)
        and mac_release_sha == expected_release_sha
    )
    if not checks["mac_release_sha"]:
        _append_error(errors, "mac_release_sha_mismatch")

    discovery_executor_replicas = evidence.get("discovery_executor_replicas")
    checks["discovery_executor_replicas"] = (
        type(discovery_executor_replicas) is int and discovery_executor_replicas == 0
    )
    if not checks["discovery_executor_replicas"]:
        _append_error(errors, "discovery_executor_not_zero")

    checks["crawler_agent_protocol"] = evidence.get("crawler_agent_protocol") == "off"
    if not checks["crawler_agent_protocol"]:
        _append_error(errors, "crawler_agent_protocol_not_off")

    checks["profile_execution_backend"] = (
        evidence.get("profile_execution_backend") == "legacy"
    )
    if not checks["profile_execution_backend"]:
        _append_error(errors, "profile_backend_not_legacy")

    pending_jobs_by_backend = _as_mapping(evidence.get("pending_jobs_by_backend"))
    legacy_pending_jobs = (
        pending_jobs_by_backend.get("legacy")
        if pending_jobs_by_backend is not None
        else None
    )
    if not (type(legacy_pending_jobs) is int and legacy_pending_jobs >= 0):
        _append_error(errors, "legacy_jobs_count_invalid")
    agent_pending_jobs = (
        pending_jobs_by_backend.get("agent")
        if pending_jobs_by_backend is not None
        else None
    )
    checks["agent_pending_jobs"] = (
        type(agent_pending_jobs) is int and agent_pending_jobs == 0
    )
    if not checks["agent_pending_jobs"]:
        _append_error(errors, "agent_jobs_pending")

    doctor = _as_mapping(evidence.get("doctor"))
    checks["doctor_ready"] = doctor is not None and doctor.get("status") == "ready"
    if not checks["doctor_ready"]:
        _append_error(errors, "doctor_not_ready")

    blockers = doctor.get("blockers") if doctor is not None else None
    defer_reasons = doctor.get("defer_reasons") if doctor is not None else None
    checks["doctor_unblocked"] = (
        isinstance(blockers, (list, tuple))
        and not blockers
        and isinstance(defer_reasons, (list, tuple))
        and not defer_reasons
    )
    if not checks["doctor_unblocked"]:
        _append_error(errors, "doctor_blocked")

    heartbeat = _as_mapping(doctor.get("heartbeat")) if doctor is not None else None
    checks["heartbeat_online"] = (
        heartbeat is not None and heartbeat.get("heartbeat_status") == "online"
    )
    if not checks["heartbeat_online"]:
        _append_error(errors, "heartbeat_offline")

    heartbeat_age = (
        heartbeat.get("heartbeat_age_seconds") if heartbeat is not None else None
    )
    heartbeat_age_fresh = _is_nonnegative_number(
        heartbeat_age,
        maximum=max_heartbeat_age_seconds,
    )
    if not heartbeat_age_fresh:
        _append_error(errors, "heartbeat_stale")
    heartbeat_reported_at_fresh = _receipt_is_fresh(
        _parse_utc_timestamp(
            heartbeat.get("reported_at") if heartbeat is not None else None
        ),
        reference=reference,
        max_age_seconds=max_heartbeat_age_seconds,
        errors=errors,
        stale_error="heartbeat_reported_at_stale",
        future_error="heartbeat_reported_at_future",
        invalid_error="heartbeat_reported_at_invalid",
    )
    checks["heartbeat_fresh"] = heartbeat_age_fresh and heartbeat_reported_at_fresh

    profile = _as_mapping(doctor.get("profile")) if doctor is not None else None
    checks["profile_ready"] = profile is not None and profile.get("status") == "ready"
    if not checks["profile_ready"]:
        _append_error(errors, "profile_not_ready")

    checks["profile_unlocked"] = (
        profile is not None and profile.get("lock_status") == "free"
    )
    if not checks["profile_unlocked"]:
        _append_error(errors, "profile_locked")

    queue = _as_mapping(doctor.get("queue")) if doctor is not None else None
    queue_age = queue.get("oldest_claimable_age_seconds") if queue is not None else None
    claimable_count = queue.get("claimable_count") if queue is not None else None
    if queue_age is None and claimable_count == 0:
        checks["claimable_queue_age"] = True
    elif queue_age is None:
        _append_error(errors, "claimable_queue_age_missing")
    else:
        checks["claimable_queue_age"] = _is_nonnegative_number(
            queue_age,
            maximum=max_oldest_claimable_age_seconds,
        )
        if not checks["claimable_queue_age"]:
            _append_error(errors, "claimable_queue_too_old")

    return RuntimeVerificationReport(
        schema_version=1,
        stage="runtime",
        status="accepted" if not errors else "rejected",
        release_sha=expected_release_sha,
        observed_at=_observed_at(reference),
        checks=checks,
        errors=tuple(errors),
    )


def verify_canary_evidence(
    evidence: Mapping[str, object],
    *,
    expected_release_sha: str,
    observed_at: datetime | None = None,
) -> CanaryVerificationReport:
    """Verify the canary chain without exposing its correlation identifiers."""

    if not _is_exact_release_sha(expected_release_sha):
        raise ValueError(
            "expected release must be an exact 40-character lowercase Git SHA"
        )

    checks = _empty_canary_checks()
    errors: list[str] = []

    checks["job_run_correlated"] = evidence.get("job_run_correlated") is True
    if not checks["job_run_correlated"]:
        _append_error(errors, "job_run_not_correlated")

    checks["job_status"] = evidence.get("job_status") == "dispatched"
    if not checks["job_status"]:
        _append_error(errors, "job_not_terminal")

    checks["run_status"] = evidence.get("run_status") == "succeeded"
    if not checks["run_status"]:
        _append_error(errors, "run_not_successful")

    run_finished_age_seconds = evidence.get("run_finished_age_seconds")
    checks["run_fresh"] = _is_nonnegative_number(
        run_finished_age_seconds,
        maximum=CANARY_RUN_MAX_AGE_SECONDS,
    )
    if not checks["run_fresh"]:
        _append_error(errors, "run_not_fresh")

    open_candidate_count = evidence.get("open_candidate_count")
    checks["open_candidate_count"] = (
        type(open_candidate_count) is int and open_candidate_count == 0
    )
    if not checks["open_candidate_count"]:
        _append_error(errors, "open_candidates_remaining")

    persisted_candidate_count = evidence.get("persisted_candidate_count")
    checks["persisted_candidate_count"] = (
        type(persisted_candidate_count) is int and persisted_candidate_count > 0
    )
    if not checks["persisted_candidate_count"]:
        _append_error(errors, "no_persisted_candidates")

    artifact_record_count = evidence.get("artifact_record_count")
    checks["artifact_record_count"] = (
        type(artifact_record_count) is int and artifact_record_count > 0
    )
    if not checks["artifact_record_count"]:
        _append_error(errors, "artifact_record_missing")

    checks["artifact_retrievable"] = evidence.get("artifact_retrievable") is True
    if not checks["artifact_retrievable"]:
        _append_error(errors, "artifact_not_retrievable")

    for field, error_code in (
        ("evidence_jsonl", "evidence_not_jsonl"),
        ("evidence_bounded", "evidence_not_bounded"),
        ("evidence_redacted", "evidence_not_redacted"),
        ("evidence_correlation_match", "evidence_correlation_mismatch"),
    ):
        checks[field] = evidence.get(field) is True
        if not checks[field]:
            _append_error(errors, error_code)

    evidence_release_sha = evidence.get("evidence_release_sha")
    checks["evidence_release_sha"] = (
        _is_exact_release_sha(evidence_release_sha)
        and evidence_release_sha == expected_release_sha
    )
    if not checks["evidence_release_sha"]:
        _append_error(errors, "evidence_release_sha_mismatch")

    checks["evidence_terminal_event"] = evidence.get("evidence_terminal_event") is True
    if not checks["evidence_terminal_event"]:
        _append_error(errors, "evidence_terminal_event_missing")

    checks["child_process_stopped"] = evidence.get("child_pid_alive") is False
    if not checks["child_process_stopped"]:
        _append_error(errors, "child_process_alive")

    checks["profile_unlocked"] = evidence.get("profile_locked") is False
    if not checks["profile_unlocked"]:
        _append_error(errors, "profile_still_locked")

    return CanaryVerificationReport(
        schema_version=1,
        stage="canary",
        status="accepted" if not errors else "rejected",
        release_sha=expected_release_sha,
        observed_at=_observed_at(observed_at),
        checks=checks,
        errors=tuple(errors),
    )


def _utc_datetime(value: datetime | None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=UTC)
    return resolved.astimezone(UTC)


def _parse_utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _receipt_is_fresh(
    timestamp: datetime | None,
    *,
    reference: datetime,
    max_age_seconds: int,
    errors: list[str],
    stale_error: str,
    future_error: str,
    invalid_error: str,
) -> bool:
    if timestamp is None:
        _append_error(errors, invalid_error)
        return False
    age_seconds = (reference - timestamp).total_seconds()
    if age_seconds < -RECEIPT_FUTURE_SKEW_SECONDS:
        _append_error(errors, future_error)
        return False
    if age_seconds > max_age_seconds:
        _append_error(errors, stale_error)
        return False
    return True


def _is_empty_sequence(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes))
        and not value
    )


def _stage_content_is_valid(
    receipt: Mapping[str, object],
    stage: str,
) -> bool:
    if stage == "supervised":
        return (
            set(receipt) == set(SUPERVISED_RECEIPT_KEYS)
            and all(
                receipt.get(field) is True
                for field in (
                    "deadline_reached",
                    "process_group_reaped",
                    "postflight_runtime_accepted",
                )
            )
            and _is_empty_sequence(receipt.get("errors"))
        )

    required_checks = CHECK_NAMES if stage == "runtime" else CANARY_CHECK_NAMES
    checks = _as_mapping(receipt.get("checks"))
    return (
        set(receipt) == set(STAGE_RECEIPT_KEYS)
        and checks is not None
        and set(checks) == set(required_checks)
        and all(checks.get(name) is True for name in required_checks)
        and _is_empty_sequence(receipt.get("errors"))
    )


def verify_acceptance_bundle(
    evidence: Mapping[str, object],
    *,
    expected_release_sha: str,
    observed_at: datetime | None = None,
    max_age_seconds: int = 86_400,
) -> AcceptanceBundleReport:
    """Verify the sanitized runtime, canary, supervision, and rollback receipts."""

    if not _is_exact_release_sha(expected_release_sha):
        raise ValueError(
            "expected release must be an exact 40-character lowercase Git SHA"
        )
    if type(max_age_seconds) is not int or max_age_seconds < 0:
        raise ValueError("max_age_seconds must be a nonnegative integer")

    checks = {name: False for name in BUNDLE_CHECK_NAMES}
    errors: list[str] = []
    reference = _utc_datetime(observed_at)
    seen_stages: set[str] = set()
    stage_timestamps: dict[str, datetime | None] = {}
    receipts = evidence.get("receipts")
    if isinstance(receipts, Sequence) and not isinstance(receipts, (str, bytes)):
        for receipt_value in receipts:
            receipt = _as_mapping(receipt_value)
            stage = receipt.get("stage") if receipt is not None else None
            if not isinstance(stage, str) or stage not in ACCEPTANCE_BUNDLE_STAGES:
                _append_error(errors, "unknown_stage")
                continue
            if stage in seen_stages:
                _append_error(errors, "duplicate_stage")
                continue
            seen_stages.add(stage)

            stage_valid = True
            if receipt is None or receipt.get("schema_version") != 1:
                stage_valid = False
                _append_error(errors, "stage_schema_invalid")
            if receipt is None or receipt.get("status") != "accepted":
                stage_valid = False
                _append_error(errors, "stage_not_accepted")
            if (
                receipt is None
                or not _is_exact_release_sha(receipt.get("release_sha"))
                or receipt.get("release_sha") != expected_release_sha
            ):
                stage_valid = False
                _append_error(errors, "stage_release_sha_mismatch")
            timestamp = (
                _parse_utc_timestamp(receipt.get("observed_at"))
                if receipt is not None
                else None
            )
            stage_timestamps[stage] = timestamp
            stage_valid = (
                _receipt_is_fresh(
                    timestamp,
                    reference=reference,
                    max_age_seconds=max_age_seconds,
                    errors=errors,
                    stale_error="stage_receipt_stale",
                    future_error="stage_receipt_future",
                    invalid_error="stage_receipt_invalid",
                )
                and stage_valid
            )
            if receipt is None or not _stage_content_is_valid(receipt, stage):
                stage_valid = False
                _append_error(errors, "stage_checks_invalid")
            checks[f"{stage}_receipt"] = stage_valid
    else:
        _append_error(errors, "required_stage_missing")

    for stage in ACCEPTANCE_BUNDLE_STAGES:
        if stage not in seen_stages:
            _append_error(errors, "required_stage_missing")

    runtime_timestamp = stage_timestamps.get("runtime")
    canary_timestamp = stage_timestamps.get("canary")
    supervised_timestamp = stage_timestamps.get("supervised")
    if (
        runtime_timestamp is not None
        and canary_timestamp is not None
        and supervised_timestamp is not None
        and not (runtime_timestamp <= canary_timestamp <= supervised_timestamp)
    ):
        _append_error(errors, "stage_order_invalid")

    rollback = _as_mapping(evidence.get("rollback"))
    rollback_valid = True
    rollback_timestamp: datetime | None = None
    if rollback is None:
        rollback_valid = False
        _append_error(errors, "rollback_missing")
    else:
        if set(rollback) != ROLLBACK_RECEIPT_KEYS:
            rollback_valid = False
            _append_error(errors, "rollback_invalid")
        if rollback.get("schema_version") != 1 or rollback.get("stage") != "rollback":
            rollback_valid = False
            _append_error(errors, "rollback_invalid")
        if rollback.get("status") != "rehearsed":
            rollback_valid = False
            _append_error(errors, "rollback_not_rehearsed")
        if (
            not _is_exact_release_sha(rollback.get("release_sha"))
            or rollback.get("release_sha") != expected_release_sha
        ):
            rollback_valid = False
            _append_error(errors, "rollback_release_sha_mismatch")
        rollback_timestamp = _parse_utc_timestamp(rollback.get("observed_at"))
        rollback_valid = (
            _receipt_is_fresh(
                rollback_timestamp,
                reference=reference,
                max_age_seconds=max_age_seconds,
                errors=errors,
                stale_error="rollback_receipt_stale",
                future_error="rollback_receipt_future",
                invalid_error="rollback_receipt_invalid",
            )
            and rollback_valid
        )
        rollback_checks = _as_mapping(rollback.get("checks"))
        rollback_checks_valid = (
            rollback_checks is not None
            and set(rollback_checks) == set(ROLLBACK_CHECK_NAMES)
            and all(rollback_checks.get(name) is True for name in ROLLBACK_CHECK_NAMES)
        )
        if not rollback_checks_valid:
            _append_error(errors, "rollback_checks_incomplete")
        checks["rollback_checks"] = rollback_checks_valid

    if (
        supervised_timestamp is not None
        and rollback_timestamp is not None
        and rollback_timestamp < supervised_timestamp
    ):
        _append_error(errors, "rollback_order_invalid")

    checks["rollback_receipt"] = rollback_valid
    return AcceptanceBundleReport(
        schema_version=1,
        stage="bundle",
        status="accepted" if not errors else "rejected",
        release_sha=expected_release_sha,
        observed_at=_observed_at(observed_at),
        checks=checks,
        errors=tuple(errors),
    )


def _psycopg_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


def _safe_status(value: object, allowed: frozenset[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _same_identity(value: object, expected: str) -> bool:
    return str(value) == expected


def _summary_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
        return _as_mapping(decoded)
    return None


def _process_is_alive(pid: int | None) -> bool:
    if type(pid) is not int or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _read_canary_evidence_log(
    *,
    worker_log_path: object,
    tenant_id: str,
    job_id: str,
    run_id: str,
    expected_release_sha: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "evidence_jsonl": False,
        "evidence_bounded": False,
        "evidence_redacted": False,
        "evidence_correlation_match": False,
        "evidence_release_sha": None,
        "evidence_terminal_event": False,
        "child_pid_alive": True,
    }
    if not isinstance(worker_log_path, str) or not worker_log_path.strip():
        return result

    try:
        path = Path(worker_log_path)
        if not path.is_file():
            return result
        if path.stat().st_size > DEFAULT_MAX_LOG_BYTES:
            return result
        raw = path.read_bytes()
        if len(raw) > DEFAULT_MAX_LOG_BYTES:
            return result
        result["evidence_bounded"] = True
        if not raw:
            return result

        lines = raw.splitlines()
        records: list[dict[str, object]] = []
        decoded_lines: list[str] = []
        for line in lines:
            if not line.strip():
                return result
            decoded_line = line.decode("utf-8")
            decoded = json.loads(decoded_line)
            record = _as_mapping(decoded)
            if record is None:
                return result
            records.append(dict(record))
            decoded_lines.append(decoded_line)
        if not records:
            return result
        result["evidence_jsonl"] = True

        result["evidence_redacted"] = all(
            redact_preview(line) == line for line in decoded_lines
        )
        previous_sequence = 0
        sequence_ordered = True
        correlations_match = True
        release_match = True
        events: list[str] = []
        latest_child_pid: int | None = None
        for record in records:
            sequence = record.get("seq")
            if type(sequence) is not int or sequence <= previous_sequence:
                sequence_ordered = False
            elif sequence > previous_sequence:
                previous_sequence = sequence
            correlations_match = correlations_match and all(
                (
                    _same_identity(record.get("tenant_id"), tenant_id),
                    _same_identity(record.get("job_id"), job_id),
                    _same_identity(record.get("run_id"), run_id),
                )
            )
            release_match = release_match and (
                _is_exact_release_sha(record.get("release_sha"))
                and record.get("release_sha") == expected_release_sha
            )
            event = record.get("event")
            if not isinstance(event, str):
                correlations_match = False
            else:
                events.append(event)
            child_pid = record.get("child_pid")
            if type(child_pid) is int:
                latest_child_pid = child_pid

        result["evidence_correlation_match"] = correlations_match and sequence_ordered
        result["evidence_release_sha"] = expected_release_sha if release_match else None
        result["evidence_terminal_event"] = events[-1:] == ["dispatch_finished"]
        result["child_pid_alive"] = _process_is_alive(latest_child_pid)
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError):
        return result
    return result


def _safe_canary_evidence() -> dict[str, object]:
    return {
        "job_run_correlated": False,
        "job_status": None,
        "run_status": None,
        "run_finished_age_seconds": None,
        "open_candidate_count": 0,
        "persisted_candidate_count": 0,
        "artifact_record_count": 0,
        "artifact_retrievable": False,
        "evidence_jsonl": False,
        "evidence_bounded": False,
        "evidence_redacted": False,
        "evidence_correlation_match": False,
        "evidence_release_sha": None,
        "evidence_terminal_event": False,
        "child_pid_alive": True,
        "profile_locked": True,
    }


def collect_canary_evidence(
    database_url: str,
    artifact_store: ArtifactStore,
    tenant_id: str,
    job_id: str,
    run_id: str,
    expected_release_sha: str,
    profile_dir: Path,
) -> dict[str, object]:
    """Collect the canary chain using one PostgreSQL read-only transaction."""

    result = _safe_canary_evidence()
    if not _is_exact_release_sha(expected_release_sha):
        return result

    summary_json: object = None
    job_run_correlated = False
    try:
        with connect(_psycopg_database_url(database_url)) as connection:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("BEGIN READ ONLY")
                    cursor.execute(
                        """
                        SELECT
                            j.job_status,
                            j.execution_backend,
                            r.status,
                            EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - r.finished_at))::double precision,
                            r.id,
                            r.discovery_job_id,
                            r.tenant_id,
                            r.summary_json
                        FROM discovery_jobs AS j
                        LEFT JOIN crawl_runs AS r
                            ON r.id = %s
                           AND r.tenant_id = j.tenant_id
                           AND r.discovery_job_id = j.id
                        WHERE j.id = %s AND j.tenant_id = %s
                        """,
                        (run_id, job_id, tenant_id),
                    )
                    row = cursor.fetchone()
                    if row is not None:
                        (
                            job_status,
                            execution_backend,
                            run_status,
                            run_finished_age_seconds,
                            linked_run_id,
                            linked_job_id,
                            linked_tenant_id,
                            summary_json,
                        ) = row
                        result["job_status"] = _safe_status(
                            job_status,
                            CANARY_JOB_STATUSES,
                        )
                        result["run_status"] = _safe_status(
                            run_status,
                            CANARY_RUN_STATUSES,
                        )
                        result["run_finished_age_seconds"] = (
                            float(run_finished_age_seconds)
                            if isinstance(run_finished_age_seconds, (int, float))
                            and not isinstance(run_finished_age_seconds, bool)
                            else None
                        )
                        job_run_correlated = (
                            execution_backend == "legacy"
                            and _same_identity(linked_run_id, run_id)
                            and _same_identity(linked_job_id, job_id)
                            and _same_identity(linked_tenant_id, tenant_id)
                        )
                        result["job_run_correlated"] = job_run_correlated

                    if job_run_correlated:
                        cursor.execute(
                            """
                            SELECT
                                COUNT(*) FILTER (WHERE candidate_status = 'accepted'),
                                COUNT(*) FILTER (WHERE candidate_status = 'persisted')
                            FROM discovery_candidate_attempts
                            WHERE tenant_id = %s AND run_id = %s
                            """,
                            (tenant_id, run_id),
                        )
                        open_count, persisted_count = cursor.fetchone() or (0, 0)
                        result["open_candidate_count"] = int(open_count or 0)
                        result["persisted_candidate_count"] = int(persisted_count or 0)

                        cursor.execute(
                            """
                            SELECT d.storage_key
                            FROM discovery_candidate_attempts AS a
                            JOIN crawl_runs AS r
                              ON r.tenant_id = a.tenant_id
                             AND r.id = a.run_id
                            JOIN projects AS p
                              ON p.tenant_id = a.tenant_id
                             AND p.id = a.project_id
                            JOIN documents AS d
                              ON d.tenant_id = p.tenant_id
                             AND d.project_id = p.id
                            JOIN document_capture_attempts AS c
                              ON c.tenant_id = a.tenant_id
                             AND c.project_id = a.project_id
                             AND c.run_id = r.id
                             AND c.status = 'succeeded'
                             AND c.doc_count > 0
                            WHERE a.tenant_id = %s
                              AND a.run_id = %s
                              AND a.candidate_status = 'persisted'
                              AND d.created_at >= r.started_at
                              AND d.created_at <= c.attempted_at
                            GROUP BY d.storage_key
                            ORDER BY MIN(d.created_at), d.storage_key
                            """,
                            (tenant_id, run_id),
                        )
                        storage_keys = [
                            row[0]
                            for row in cursor.fetchall()
                            if isinstance(row[0], str) and row[0]
                        ]
                        result["artifact_record_count"] = len(storage_keys)
                        retrievable = bool(storage_keys)
                        for storage_key in storage_keys:
                            try:
                                retrievable = (
                                    bool(artifact_store.exists(storage_key))
                                    and retrievable
                                )
                            except Exception:
                                retrievable = False
                        result["artifact_retrievable"] = retrievable

                        summary = _summary_mapping(summary_json)
                        result.update(
                            _read_canary_evidence_log(
                                worker_log_path=(
                                    summary.get("worker_log_path")
                                    if summary is not None
                                    else None
                                ),
                                tenant_id=tenant_id,
                                job_id=job_id,
                                run_id=run_id,
                                expected_release_sha=expected_release_sha,
                            )
                        )
            finally:
                connection.rollback()
    except Exception:
        pass

    try:
        result["profile_locked"] = bool(is_profile_locked(profile_dir))
    except Exception:
        result["profile_locked"] = True
    return result


def _parse_canary_request(value: object) -> dict[str, str] | None:
    request = _as_mapping(value)
    required_fields = {"tenant_id", "job_id", "run_id"}
    if request is None or set(request) != required_fields:
        return None
    parsed: dict[str, str] = {}
    for field in required_fields:
        field_value = request.get(field)
        if not isinstance(field_value, str) or not field_value.strip():
            return None
        parsed[field] = field_value
    return parsed


def _read_private_canary_request(path: Path) -> dict[str, str]:
    """Read one private canary request through a verified file descriptor."""

    fd = -1
    try:
        if path.is_symlink():
            raise ValueError
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(os.fspath(path), flags)
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError
        if metadata.st_uid != os.getuid():
            raise ValueError
        if metadata.st_mode & 0o077:
            raise ValueError
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            payload = json.load(handle)
    except Exception:
        raise ValueError("invalid_canary_request") from None
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                raise ValueError("invalid_canary_request") from None

    request = _parse_canary_request(payload)
    if request is None:
        raise ValueError("invalid_canary_request")
    try:
        return {
            field: str(UUID(request[field]))
            for field in ("tenant_id", "job_id", "run_id")
        }
    except (KeyError, ValueError):
        raise ValueError("invalid_canary_request") from None


def _build_cli_canary_profile_dir() -> Path:
    from egp_api.config import (
        get_browser_persistent_profile_dir,
        get_browser_profile_mode,
    )

    if get_browser_profile_mode() != "persistent":
        raise RuntimeError("persistent browser profile mode is required")
    profile_dir = get_browser_persistent_profile_dir()
    if profile_dir is None:
        raise RuntimeError("persistent browser profile directory is required")
    return profile_dir


def _build_cli_artifact_store() -> tuple[str, ArtifactStore]:
    from egp_api.config import (
        get_artifact_bucket,
        get_artifact_prefix,
        get_artifact_root,
        get_artifact_storage_backend,
        get_database_url,
        get_supabase_service_role_key,
        get_supabase_url,
    )
    from egp_db.repositories.document_repo import create_artifact_store

    artifact_root = get_artifact_root()
    database_url = get_database_url()
    artifact_store = create_artifact_store(
        storage_backend=get_artifact_storage_backend(),
        artifact_root=artifact_root,
        s3_bucket=get_artifact_bucket(),
        s3_prefix=get_artifact_prefix(),
        supabase_url=get_supabase_url(),
        supabase_service_role_key=get_supabase_service_role_key(),
    )
    return database_url, artifact_store


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    runtime = subparsers.add_parser("runtime", help="verify runtime evidence")
    runtime.add_argument("--evidence", required=True, type=Path)
    runtime.add_argument("--expected-release-sha", required=True)
    runtime.add_argument("--output", type=Path)
    canary = subparsers.add_parser("canary", help="verify canary evidence")
    canary.add_argument("--request", required=True, type=Path)
    canary.add_argument("--expected-release-sha", required=True)
    canary.add_argument("--output", type=Path)
    bundle = subparsers.add_parser("bundle", help="verify acceptance bundle evidence")
    bundle.add_argument("--evidence", required=True, type=Path)
    bundle.add_argument("--expected-release-sha", required=True)
    bundle.add_argument("--output", type=Path)
    bundle.add_argument("--max-age-seconds", type=int, default=86_400)
    return parser


def _error_payload(error: str, *, stage: str = "runtime") -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": stage,
        "status": "rejected",
        "errors": [error],
    }


def _render_payload(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _write_payload(path: Path, rendered: str) -> None:
    path.write_text(f"{rendered}\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected runtime verification command."""

    args = _build_parser().parse_args(argv)
    if not _is_exact_release_sha(args.expected_release_sha):
        print(
            _render_payload(
                _error_payload(
                    "invalid_expected_release_sha",
                    stage=args.command,
                )
            )
        )
        return 2

    if args.command == "canary":
        try:
            request = _read_private_canary_request(args.request)
        except ValueError:
            print(
                _render_payload(
                    _error_payload("invalid_canary_request", stage="canary")
                )
            )
            return 2
        try:
            profile_dir = _build_cli_canary_profile_dir()
            database_url, artifact_store = _build_cli_artifact_store()
            evidence_payload = collect_canary_evidence(
                database_url=database_url,
                artifact_store=artifact_store,
                tenant_id=request["tenant_id"],
                job_id=request["job_id"],
                run_id=request["run_id"],
                expected_release_sha=args.expected_release_sha,
                profile_dir=profile_dir,
            )
            report = verify_canary_evidence(
                evidence_payload,
                expected_release_sha=args.expected_release_sha,
            )
        except Exception:
            print(
                _render_payload(
                    _error_payload("canary_collection_failed", stage="canary")
                )
            )
            return 2
        rendered = _render_payload(asdict(report))
        if args.output is not None:
            try:
                _write_payload(args.output, rendered)
            except OSError:
                print(
                    _render_payload(
                        _error_payload("output_write_failed", stage="canary")
                    )
                )
                return 2
        print(rendered)
        return 0 if report.status == "accepted" else 1

    if args.command == "bundle":
        try:
            evidence_payload = json.loads(args.evidence.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            print(
                _render_payload(_error_payload("invalid_evidence_file", stage="bundle"))
            )
            return 2
        if not isinstance(evidence_payload, Mapping):
            print(
                _render_payload(_error_payload("invalid_evidence_file", stage="bundle"))
            )
            return 2
        try:
            report = verify_acceptance_bundle(
                evidence_payload,
                expected_release_sha=args.expected_release_sha,
                max_age_seconds=args.max_age_seconds,
            )
        except ValueError:
            print(
                _render_payload(
                    _error_payload("invalid_bundle_evidence", stage="bundle")
                )
            )
            return 2
        rendered = _render_payload(asdict(report))
        if args.output is not None:
            try:
                _write_payload(args.output, rendered)
            except OSError:
                print(
                    _render_payload(
                        _error_payload("output_write_failed", stage="bundle")
                    )
                )
                return 2
        print(rendered)
        return 0 if report.status == "accepted" else 1

    # Keep the original runtime command's behavior and output contract intact.
    try:
        evidence_payload = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        print(_render_payload(_error_payload("invalid_evidence_file")))
        return 2

    if not isinstance(evidence_payload, Mapping):
        print(_render_payload(_error_payload("invalid_evidence_file")))
        return 2

    report = verify_runtime_evidence(
        evidence_payload,
        expected_release_sha=args.expected_release_sha,
    )
    rendered = _render_payload(asdict(report))
    if args.output is not None:
        try:
            _write_payload(args.output, rendered)
        except OSError:
            print(_render_payload(_error_payload("output_write_failed")))
            return 2
    print(rendered)
    return 0 if report.status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
