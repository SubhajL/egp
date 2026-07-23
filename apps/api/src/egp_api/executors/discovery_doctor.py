"""Read-only, credential-safe diagnosis for the external discovery crawler."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

from egp_api.config import (
    get_browser_persistent_profile_dir,
    get_browser_profile_mode,
    get_browser_warmup_failure_pause_threshold,
    get_browser_warmup_stale_after_seconds,
    get_crawler_heartbeat_stale_after_seconds,
    get_database_url,
)
from egp_crawler_core.profile_lock import is_profile_locked
from egp_crawler_core.rate_limiter import (
    RateLimiterCircuitSnapshot,
    get_default_rate_limiter,
)
from egp_db.connection import create_shared_engine
from egp_db.repositories.crawler_runtime_repo import (
    CrawlerRuntimeSnapshot,
    SqlCrawlerRuntimeRepository,
)
from egp_db.repositories.discovery_job_repo import (
    DiscoveryQueueSnapshot,
    SqlDiscoveryJobRepository,
)
from egp_shared_types.enums import CrawlerBlockerCode


PROFILE_STATE_FILENAME = ".egp-profile-state.json"
DoctorStatus = Literal["ready", "deferred", "blocked"]


@dataclass(frozen=True, slots=True)
class ProfileDoctorSnapshot:
    mode: str
    status: str
    lock_status: str
    state_present: bool
    last_success_at: str | None
    last_success_age_seconds: int | None
    consecutive_warm_failures: int
    operator_action_required: bool


@dataclass(frozen=True, slots=True)
class DiscoveryDoctorSnapshot:
    status: DoctorStatus
    database_status: str
    profile: ProfileDoctorSnapshot
    circuit: RateLimiterCircuitSnapshot
    heartbeat: CrawlerRuntimeSnapshot | None
    queue: DiscoveryQueueSnapshot | None
    blockers: tuple[str, ...]
    defer_reasons: tuple[str, ...]


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_profile_state(profile_dir: Path) -> dict[str, object] | None:
    state_path = profile_dir / PROFILE_STATE_FILENAME
    if not state_path.is_file():
        return None
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def inspect_browser_profile(
    *,
    profile_mode: str,
    profile_dir: Path | None,
    stale_after_seconds: float,
    pause_threshold: int,
    now: datetime | None = None,
    lock_probe: Callable[[Path], bool] = is_profile_locked,
) -> ProfileDoctorSnapshot:
    """Inspect only sanitized profile metadata; never warm or create a profile."""

    normalized_mode = str(profile_mode).strip().lower()
    if normalized_mode != "persistent":
        return ProfileDoctorSnapshot(
            mode=normalized_mode or "unknown",
            status="not_applicable",
            lock_status="not_applicable",
            state_present=False,
            last_success_at=None,
            last_success_age_seconds=None,
            consecutive_warm_failures=0,
            operator_action_required=False,
        )
    if profile_dir is None:
        return ProfileDoctorSnapshot(
            mode="persistent",
            status="unconfigured",
            lock_status="unknown",
            state_present=False,
            last_success_at=None,
            last_success_age_seconds=None,
            consecutive_warm_failures=0,
            operator_action_required=False,
        )

    state = _read_profile_state(profile_dir)
    try:
        consecutive_failures = int(
            (state or {}).get("consecutive_warm_failures", 0)
        )
    except (TypeError, ValueError):
        consecutive_failures = 0
    operator_action_required = bool(
        (state or {}).get("operator_action_required") is True
        or (pause_threshold > 0 and consecutive_failures >= pause_threshold)
    )
    last_success = _parse_timestamp((state or {}).get("last_success_at"))
    resolved_now = now or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=UTC)
    else:
        resolved_now = resolved_now.astimezone(UTC)
    age_seconds = (
        max(0, int((resolved_now - last_success).total_seconds()))
        if last_success is not None
        else None
    )
    locked = lock_probe(profile_dir)
    if operator_action_required:
        status = "operator_action_required"
    elif locked:
        status = "busy"
    elif age_seconds is None or age_seconds >= max(0.0, stale_after_seconds):
        status = "warm_required"
    else:
        status = "ready"
    return ProfileDoctorSnapshot(
        mode="persistent",
        status=status,
        lock_status="busy" if locked else "free",
        state_present=state is not None,
        last_success_at=(
            last_success.isoformat() if last_success is not None else None
        ),
        last_success_age_seconds=age_seconds,
        consecutive_warm_failures=max(0, consecutive_failures),
        operator_action_required=operator_action_required,
    )


def _unknown_profile_snapshot() -> ProfileDoctorSnapshot:
    return ProfileDoctorSnapshot(
        mode="unknown",
        status="unknown",
        lock_status="unknown",
        state_present=False,
        last_success_at=None,
        last_success_age_seconds=None,
        consecutive_warm_failures=0,
        operator_action_required=False,
    )


def _unknown_circuit_snapshot() -> RateLimiterCircuitSnapshot:
    return RateLimiterCircuitSnapshot(
        is_open=False,
        reset_at=None,
        reset_in_seconds=0.0,
        last_outcome=None,
        consecutive_429=0,
        consecutive_site_errors=0,
        site_error_trip_count=0,
    )


def _initialization_failure_snapshot() -> DiscoveryDoctorSnapshot:
    return DiscoveryDoctorSnapshot(
        status="blocked",
        database_status="unreachable",
        profile=_unknown_profile_snapshot(),
        circuit=_unknown_circuit_snapshot(),
        heartbeat=None,
        queue=None,
        blockers=(CrawlerBlockerCode.DATABASE_UNREACHABLE.value,),
        defer_reasons=("doctor_initialization_failed",),
    )


def _require_postgresql_target(database_url: str) -> None:
    try:
        backend_name = make_url(database_url).get_backend_name()
    except Exception as exc:
        raise ValueError("doctor database target is invalid") from exc
    if backend_name != "postgresql":
        raise ValueError("doctor requires a PostgreSQL database target")


def build_discovery_doctor_snapshot(
    *,
    database_probe: Callable[[], None],
    queue_probe: Callable[[], DiscoveryQueueSnapshot],
    heartbeat_probe: Callable[[], CrawlerRuntimeSnapshot],
    profile_probe: Callable[[], ProfileDoctorSnapshot],
    circuit_probe: Callable[[], RateLimiterCircuitSnapshot],
) -> DiscoveryDoctorSnapshot:
    """Assemble diagnostics without exposing exceptions, URLs, paths, or secrets."""

    blockers: list[str] = []
    defer_reasons: list[str] = []
    try:
        profile = profile_probe()
    except Exception:
        profile = _unknown_profile_snapshot()
        defer_reasons.append("profile_unknown")
    try:
        circuit = circuit_probe()
    except Exception:
        circuit = _unknown_circuit_snapshot()
        defer_reasons.append("circuit_unknown")

    queue: DiscoveryQueueSnapshot | None = None
    heartbeat: CrawlerRuntimeSnapshot | None = None
    try:
        database_probe()
    except Exception:
        database_status = "unreachable"
        blockers.append(CrawlerBlockerCode.DATABASE_UNREACHABLE.value)
    else:
        database_status = "connected"
        try:
            queue = queue_probe()
        except Exception:
            blockers.append("queue_unavailable")
        try:
            heartbeat = heartbeat_probe()
        except Exception:
            blockers.append("heartbeat_unavailable")

    if circuit.is_open:
        blockers.append(CrawlerBlockerCode.CIRCUIT_OPEN.value)
    if profile.status == "operator_action_required":
        blockers.append(
            CrawlerBlockerCode.PROFILE_OPERATOR_ACTION_REQUIRED.value
        )
    elif profile.status == "busy":
        defer_reasons.append(CrawlerBlockerCode.PROFILE_BUSY.value)
    elif profile.status in {"warm_required", "unconfigured"}:
        defer_reasons.append(CrawlerBlockerCode.PROFILE_WARM_RETRY.value)

    if heartbeat is not None:
        heartbeat_blocker = (
            str(heartbeat.blocker_code) if heartbeat.blocker_code else None
        )
        if heartbeat.heartbeat_status == "offline":
            heartbeat_blocker = CrawlerBlockerCode.AGENT_OFFLINE.value
        if heartbeat_blocker in {
            CrawlerBlockerCode.AGENT_OFFLINE.value,
            CrawlerBlockerCode.DATABASE_UNREACHABLE.value,
            CrawlerBlockerCode.CIRCUIT_OPEN.value,
            CrawlerBlockerCode.PROFILE_OPERATOR_ACTION_REQUIRED.value,
        } and heartbeat_blocker not in blockers:
            blockers.append(heartbeat_blocker)

    status: DoctorStatus
    if blockers:
        status = "blocked"
    elif defer_reasons:
        status = "deferred"
    else:
        status = "ready"
    return DiscoveryDoctorSnapshot(
        status=status,
        database_status=database_status,
        profile=profile,
        circuit=circuit,
        heartbeat=heartbeat,
        queue=queue,
        blockers=tuple(blockers),
        defer_reasons=tuple(defer_reasons),
    )


def collect_discovery_doctor_snapshot(
    database_url: str | None = None,
    *,
    engine_factory: Callable[[str], Engine] = create_shared_engine,
) -> DiscoveryDoctorSnapshot:
    """Build the production read-only probe set and always dispose its engine."""

    engine: Engine | None = None
    try:
        resolved_database_url = get_database_url(database_url)
        _require_postgresql_target(resolved_database_url)
        engine = engine_factory(resolved_database_url)
        queue_repository = SqlDiscoveryJobRepository(
            database_url=resolved_database_url,
            engine=engine,
            bootstrap_schema=False,
        )
        runtime_repository = SqlCrawlerRuntimeRepository(
            database_url=resolved_database_url,
            engine=engine,
            bootstrap_schema=False,
        )

        def probe_database() -> None:
            assert engine is not None
            with engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()

        return build_discovery_doctor_snapshot(
            database_probe=probe_database,
            queue_probe=queue_repository.get_discovery_queue_snapshot,
            heartbeat_probe=lambda: runtime_repository.get_freshest_status(
                runtime_mode="external",
                stale_after_seconds=get_crawler_heartbeat_stale_after_seconds(),
            ),
            profile_probe=lambda: inspect_browser_profile(
                profile_mode=get_browser_profile_mode(),
                profile_dir=get_browser_persistent_profile_dir(),
                stale_after_seconds=get_browser_warmup_stale_after_seconds(),
                pause_threshold=get_browser_warmup_failure_pause_threshold(),
            ),
            circuit_probe=(
                get_default_rate_limiter().peek_circuit_snapshot
            ),
        )
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only diagnosis for the external discovery crawler."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL; never printed.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    snapshot_factory: Callable[[str | None], DiscoveryDoctorSnapshot] = (
        collect_discovery_doctor_snapshot
    ),
) -> int:
    args = _build_parser().parse_args(argv)
    try:
        snapshot = snapshot_factory(args.database_url)
    except Exception:
        snapshot = _initialization_failure_snapshot()
    print(json.dumps(asdict(snapshot), sort_keys=True, separators=(",", ":")))
    return 0 if snapshot.status == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
