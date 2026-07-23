from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import asdict
import json

import pytest

from egp_api.executors import discovery_doctor
from egp_api.executors.discovery_doctor import (
    ProfileDoctorSnapshot,
    build_discovery_doctor_snapshot,
    inspect_browser_profile,
)
from egp_crawler_core.rate_limiter import RateLimiterCircuitSnapshot
from egp_db.repositories.crawler_runtime_repo import CrawlerRuntimeSnapshot
from egp_db.repositories.discovery_job_repo import DiscoveryQueueSnapshot
from egp_shared_types.enums import CrawlerBlockerCode


def _closed_circuit() -> RateLimiterCircuitSnapshot:
    return RateLimiterCircuitSnapshot(
        is_open=False,
        reset_at=None,
        reset_in_seconds=0.0,
        last_outcome="site_success",
        consecutive_429=0,
        consecutive_site_errors=0,
        site_error_trip_count=0,
    )


def _online_heartbeat() -> CrawlerRuntimeSnapshot:
    return CrawlerRuntimeSnapshot(
        agent_id="mac-crawler-1",
        runtime_mode="external",
        heartbeat_status="online",
        watcher_status="running",
        database_status="connected",
        blocker_code=None,
        profile_status="ready",
        circuit_state="closed",
        circuit_reset_at=None,
        reported_at="2026-07-23T14:00:00+00:00",
        heartbeat_age_seconds=10,
    )


def test_doctor_reports_profile_circuit_queue_and_heartbeat() -> None:
    snapshot = build_discovery_doctor_snapshot(
        database_probe=lambda: None,
        queue_probe=lambda: DiscoveryQueueSnapshot(
            pending_count=4,
            claimable_count=2,
            leased_count=1,
            retry_scheduled_count=1,
        ),
        heartbeat_probe=_online_heartbeat,
        profile_probe=lambda: ProfileDoctorSnapshot(
            mode="persistent",
            status="ready",
            lock_status="free",
            state_present=True,
            last_success_at="2026-07-23T14:00:00+00:00",
            last_success_age_seconds=10,
            consecutive_warm_failures=0,
            operator_action_required=False,
        ),
        circuit_probe=_closed_circuit,
    )

    assert snapshot.status == "ready"
    assert snapshot.database_status == "connected"
    assert snapshot.blockers == ()
    assert snapshot.defer_reasons == ()
    assert snapshot.queue is not None
    assert snapshot.queue.pending_count == 4
    assert snapshot.heartbeat is not None
    assert snapshot.heartbeat.heartbeat_status == "online"
    assert snapshot.profile.status == "ready"
    assert snapshot.circuit.is_open is False


def test_doctor_sanitizes_database_failure_and_preserves_local_diagnostics() -> None:
    def unavailable_database() -> None:
        raise RuntimeError(
            "postgresql://operator:super-secret@127.0.0.1:15432/egp"
        )

    snapshot = build_discovery_doctor_snapshot(
        database_probe=unavailable_database,
        queue_probe=lambda: (_ for _ in ()).throw(AssertionError("must not query")),
        heartbeat_probe=lambda: (_ for _ in ()).throw(AssertionError("must not query")),
        profile_probe=lambda: ProfileDoctorSnapshot(
            mode="persistent",
            status="operator_action_required",
            lock_status="free",
            state_present=True,
            last_success_at=None,
            last_success_age_seconds=None,
            consecutive_warm_failures=2,
            operator_action_required=True,
        ),
        circuit_probe=lambda: RateLimiterCircuitSnapshot(
            is_open=True,
            reset_at="2026-07-23T14:05:00+00:00",
            reset_in_seconds=300.0,
            last_outcome="site_error",
            consecutive_429=0,
            consecutive_site_errors=0,
            site_error_trip_count=1,
        ),
    )

    encoded = json.dumps(asdict(snapshot), sort_keys=True)
    assert snapshot.status == "blocked"
    assert snapshot.database_status == "unreachable"
    assert snapshot.queue is None
    assert snapshot.heartbeat is None
    assert snapshot.blockers == (
        CrawlerBlockerCode.DATABASE_UNREACHABLE.value,
        CrawlerBlockerCode.CIRCUIT_OPEN.value,
        CrawlerBlockerCode.PROFILE_OPERATOR_ACTION_REQUIRED.value,
    )
    assert "super-secret" not in encoded
    assert "postgresql://" not in encoded


def test_profile_doctor_is_read_only_and_omits_paths_and_error_text(tmp_path) -> None:
    profile_dir = tmp_path / "profile-with-customer-name"
    profile_dir.mkdir()
    (profile_dir / ".egp-profile-state.json").write_text(
        json.dumps(
            {
                "consecutive_warm_failures": 2,
                "last_failure_at": "2026-07-23T13:59:00+00:00",
                "last_failure_error": "token=must-never-leak",
                "operator_action_required": True,
            }
        ),
        encoding="utf-8",
    )

    snapshot = inspect_browser_profile(
        profile_mode="persistent",
        profile_dir=profile_dir,
        stale_after_seconds=1_800,
        pause_threshold=2,
        now=datetime(2026, 7, 23, 14, 0, tzinfo=UTC),
        lock_probe=lambda path: False,
    )

    encoded = json.dumps(asdict(snapshot), sort_keys=True)
    assert snapshot.status == "operator_action_required"
    assert snapshot.consecutive_warm_failures == 2
    assert "must-never-leak" not in encoded
    assert str(profile_dir) not in encoded

    missing_dir = tmp_path / "missing-profile"
    missing = inspect_browser_profile(
        profile_mode="persistent",
        profile_dir=missing_dir,
        stale_after_seconds=1_800,
        pause_threshold=2,
        lock_probe=lambda path: False,
    )
    assert missing.status == "warm_required"
    assert missing_dir.exists() is False


def test_doctor_main_returns_nonzero_and_prints_sanitized_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = build_discovery_doctor_snapshot(
        database_probe=lambda: (_ for _ in ()).throw(
            RuntimeError("postgresql://operator:secret@127.0.0.1:15432/egp")
        ),
        queue_probe=lambda: (_ for _ in ()).throw(AssertionError("must not query")),
        heartbeat_probe=lambda: (_ for _ in ()).throw(AssertionError("must not query")),
        profile_probe=lambda: ProfileDoctorSnapshot(
            mode="persistent",
            status="ready",
            lock_status="free",
            state_present=True,
            last_success_at="2026-07-23T14:00:00+00:00",
            last_success_age_seconds=10,
            consecutive_warm_failures=0,
            operator_action_required=False,
        ),
        circuit_probe=_closed_circuit,
    )

    exit_code = discovery_doctor.main(
        ["--database-url", "postgresql://operator:secret@127.0.0.1/egp"],
        snapshot_factory=lambda database_url: snapshot,
    )

    encoded = capsys.readouterr().out
    assert exit_code == 1
    assert json.loads(encoded)["database_status"] == "unreachable"
    assert "secret" not in encoded
    assert "postgresql://" not in encoded


def test_doctor_main_sanitizes_initialization_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_snapshot_factory(
        database_url: str | None,
    ) -> discovery_doctor.DiscoveryDoctorSnapshot:
        del database_url
        raise RuntimeError(
            "postgresql://operator:must-never-leak@127.0.0.1:15432/egp"
        )

    exit_code = discovery_doctor.main(
        [
            "--database-url",
            "postgresql://operator:must-never-leak@127.0.0.1:15432/egp",
        ],
        snapshot_factory=fail_snapshot_factory,
    )

    encoded = capsys.readouterr().out
    payload = json.loads(encoded)
    assert exit_code == 1
    assert payload["status"] == "blocked"
    assert payload["database_status"] == "unreachable"
    assert payload["blockers"] == [CrawlerBlockerCode.DATABASE_UNREACHABLE.value]
    assert "must-never-leak" not in encoded
    assert "postgresql://" not in encoded


def test_doctor_rejects_sqlite_without_creating_database_artifacts(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "missing-parent" / "doctor.sqlite3"

    exit_code = discovery_doctor.main(
        ["--database-url", f"sqlite+pysqlite:///{database_path}"],
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "blocked"
    assert payload["database_status"] == "unreachable"
    assert database_path.exists() is False
    assert database_path.parent.exists() is False
