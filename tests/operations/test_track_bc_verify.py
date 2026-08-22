from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import UUID

from psycopg import connect
import pytest

from egp_db.artifact_store import LocalArtifactStore
from egp_db.dev_postgres import TempPostgresCluster, postgres_binaries_available
from egp_db.migration_runner import apply_migrations
from egp_observability.subprocess_evidence import (
    BoundedEvidenceWriter,
    EvidenceCorrelation,
)


RELEASE_SHA = "a" * 40
PYTHON_ROLES = (
    "migrate",
    "api",
    "webhook-executor",
    "crawler-agent-inbox-executor",
    "discovery-executor",
)


def _actual_doctor_payload(reference: datetime | None = None) -> dict[str, object]:
    from egp_api.executors.discovery_doctor import (
        ProfileDoctorSnapshot,
        build_discovery_doctor_snapshot,
    )
    from egp_crawler_core.rate_limiter import RateLimiterCircuitSnapshot
    from egp_db.repositories.crawler_runtime_repo import CrawlerRuntimeSnapshot
    from egp_db.repositories.discovery_job_repo import DiscoveryQueueSnapshot

    resolved_reference = reference or datetime.now(UTC)
    snapshot = build_discovery_doctor_snapshot(
        database_probe=lambda: None,
        queue_probe=lambda: DiscoveryQueueSnapshot(
            pending_count=3,
            claimable_count=1,
            leased_count=0,
            retry_scheduled_count=2,
            oldest_claimable_age_seconds=120,
        ),
        heartbeat_probe=lambda: CrawlerRuntimeSnapshot(
            agent_id="mac-crawler",
            runtime_mode="external",
            heartbeat_status="online",
            watcher_status="running",
            database_status="connected",
            blocker_code=None,
            profile_status="ready",
            circuit_state="closed",
            circuit_reset_at=None,
            reported_at=resolved_reference.isoformat(),
            heartbeat_age_seconds=10,
        ),
        profile_probe=lambda: ProfileDoctorSnapshot(
            mode="persistent",
            status="ready",
            lock_status="free",
            state_present=True,
            last_success_at="2026-08-22T13:00:00+00:00",
            last_success_age_seconds=10,
            consecutive_warm_failures=0,
            operator_action_required=False,
        ),
        circuit_probe=lambda: RateLimiterCircuitSnapshot(
            is_open=False,
            reset_at=None,
            reset_in_seconds=0,
            last_outcome="site_success",
            consecutive_429=0,
            consecutive_site_errors=0,
            site_error_trip_count=0,
        ),
    )
    return asdict(snapshot)


def _accepted_runtime_evidence(reference: datetime | None = None) -> dict[str, object]:
    resolved_reference = reference or datetime.now(UTC)
    image_id = f"sha256:{'1' * 64}"
    return {
        "collected_at": resolved_reference.isoformat(),
        "source_release_sha": RELEASE_SHA,
        "role_revisions": {
            role: {
                "oci_revision": RELEASE_SHA,
                "baked_release_sha": RELEASE_SHA,
                "image_id": image_id,
                "container_image_id": image_id,
            }
            for role in PYTHON_ROLES
        },
        "mac_release_sha": RELEASE_SHA,
        "discovery_executor_replicas": 0,
        "crawler_agent_protocol": "off",
        "profile_execution_backend": "legacy",
        "pending_jobs_by_backend": {"legacy": 3, "agent": 0},
        "doctor": _actual_doctor_payload(resolved_reference),
        # Deliberately hostile extra input must never be reflected in output.
        "database_url": "postgresql://admin:super-secret@example.invalid/egp",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
    }


def test_runtime_verification_accepts_complete_track_bc_evidence() -> None:
    from scripts.track_bc_verify import verify_runtime_evidence

    reference = datetime(2026, 8, 22, 13, 0, tzinfo=UTC)
    report = verify_runtime_evidence(
        _accepted_runtime_evidence(reference),
        expected_release_sha=RELEASE_SHA,
        observed_at=reference,
    )

    assert report.schema_version == 1
    assert report.stage == "runtime"
    assert report.status == "accepted"
    assert report.release_sha == RELEASE_SHA
    assert report.errors == ()
    assert report.observed_at == "2026-08-22T13:00:00+00:00"
    assert report.checks
    assert all(report.checks.values())


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (lambda value: value.pop("source_release_sha"), "source_release_sha_mismatch"),
        (
            lambda value: value["role_revisions"].pop("api"),  # type: ignore[union-attr]
            "role_api_revision_mismatch",
        ),
        (
            lambda value: value["role_revisions"]["migrate"].update(  # type: ignore[index,union-attr]
                {"oci_revision": "b" * 40}
            ),
            "role_migrate_revision_mismatch",
        ),
        (
            lambda value: value["role_revisions"]["api"].update(  # type: ignore[index,union-attr]
                {"container_image_id": f"sha256:{'2' * 64}"}
            ),
            "role_api_image_identity_mismatch",
        ),
        (
            lambda value: value.update({"mac_release_sha": "b" * 40}),
            "mac_release_sha_mismatch",
        ),
        (
            lambda value: value.update({"discovery_executor_replicas": 1}),
            "discovery_executor_not_zero",
        ),
        (
            lambda value: value.update({"crawler_agent_protocol": "shadow"}),
            "crawler_agent_protocol_not_off",
        ),
        (
            lambda value: value.update({"profile_execution_backend": "agent"}),
            "profile_backend_not_legacy",
        ),
        (
            lambda value: value["pending_jobs_by_backend"].update({"agent": 1}),  # type: ignore[union-attr]
            "agent_jobs_pending",
        ),
        (
            lambda value: value["pending_jobs_by_backend"].pop("legacy"),  # type: ignore[union-attr]
            "legacy_jobs_count_invalid",
        ),
        (
            lambda value: value["doctor"].update({"status": "blocked"}),  # type: ignore[union-attr]
            "doctor_not_ready",
        ),
        (
            lambda value: value["doctor"].update({"blockers": ["profile_busy"]}),  # type: ignore[union-attr]
            "doctor_blocked",
        ),
        (
            lambda value: value["doctor"]["heartbeat"].update(  # type: ignore[index,union-attr]
                {"heartbeat_status": "offline"}
            ),
            "heartbeat_offline",
        ),
        (
            lambda value: value["doctor"]["heartbeat"].update(  # type: ignore[index,union-attr]
                {"heartbeat_age_seconds": 91}
            ),
            "heartbeat_stale",
        ),
        (
            lambda value: value["doctor"]["heartbeat"].update(  # type: ignore[index,union-attr]
                {"reported_at": "2026-08-20T13:00:00+00:00"}
            ),
            "heartbeat_reported_at_stale",
        ),
        (
            lambda value: value["doctor"]["profile"].update(  # type: ignore[index,union-attr]
                {"status": "warm_required"}
            ),
            "profile_not_ready",
        ),
        (
            lambda value: value["doctor"]["profile"].update(  # type: ignore[index,union-attr]
                {"lock_status": "busy"}
            ),
            "profile_locked",
        ),
        (
            lambda value: value["doctor"]["queue"].update(  # type: ignore[index,union-attr]
                {"oldest_claimable_age_seconds": 43_201}
            ),
            "claimable_queue_too_old",
        ),
        (
            lambda value: value["doctor"].pop("queue"),  # type: ignore[union-attr]
            "claimable_queue_age_missing",
        ),
    ],
)
def test_runtime_verification_fails_closed_for_each_required_invariant(
    mutate,
    error_code: str,
) -> None:
    from scripts.track_bc_verify import verify_runtime_evidence

    evidence = deepcopy(_accepted_runtime_evidence())
    mutate(evidence)

    report = verify_runtime_evidence(evidence, expected_release_sha=RELEASE_SHA)

    assert report.status == "rejected"
    assert error_code in report.errors


@pytest.mark.parametrize(
    "invalid_sha",
    ["", "a" * 39, "A" * 40, "g" * 40, "refs/heads/main"],
)
def test_runtime_verification_requires_exact_lowercase_commit_sha(
    invalid_sha: str,
) -> None:
    from scripts.track_bc_verify import verify_runtime_evidence

    with pytest.raises(ValueError, match="40-character lowercase Git SHA"):
        verify_runtime_evidence(
            _accepted_runtime_evidence(),
            expected_release_sha=invalid_sha,
        )


def test_runtime_verification_accepts_empty_claimable_queue_without_age() -> None:
    from scripts.track_bc_verify import verify_runtime_evidence

    evidence = _accepted_runtime_evidence()
    evidence["doctor"]["queue"] = {  # type: ignore[index]
        "claimable_count": 0,
        "oldest_claimable_age_seconds": None,
    }

    report = verify_runtime_evidence(evidence, expected_release_sha=RELEASE_SHA)

    assert report.status == "accepted"


def test_runtime_verification_uses_explicit_age_thresholds() -> None:
    from scripts.track_bc_verify import verify_runtime_evidence

    report = verify_runtime_evidence(
        _accepted_runtime_evidence(),
        expected_release_sha=RELEASE_SHA,
        max_heartbeat_age_seconds=5,
        max_oldest_claimable_age_seconds=100,
    )

    assert report.status == "rejected"
    assert "heartbeat_stale" in report.errors
    assert "claimable_queue_too_old" in report.errors


@pytest.mark.parametrize(
    ("collected_at", "error_code"),
    [
        ("2026-08-22T12:54:59+00:00", "runtime_evidence_stale"),
        ("2026-08-22T13:01:01+00:00", "runtime_evidence_future"),
        ("not-a-timestamp", "runtime_evidence_timestamp_invalid"),
    ],
)
def test_runtime_verification_rejects_replayed_or_future_evidence(
    collected_at: str,
    error_code: str,
) -> None:
    from scripts.track_bc_verify import verify_runtime_evidence

    reference = datetime(2026, 8, 22, 13, 0, tzinfo=UTC)
    evidence = _accepted_runtime_evidence(reference)
    evidence["collected_at"] = collected_at

    report = verify_runtime_evidence(
        evidence,
        expected_release_sha=RELEASE_SHA,
        observed_at=reference,
        max_evidence_age_seconds=300,
    )

    assert report.status == "rejected"
    assert error_code in report.errors


def test_runtime_verification_output_is_credential_and_identifier_safe() -> None:
    from dataclasses import asdict

    from scripts.track_bc_verify import verify_runtime_evidence

    output = json.dumps(
        asdict(
            verify_runtime_evidence(
                _accepted_runtime_evidence(),
                expected_release_sha=RELEASE_SHA,
            )
        ),
        sort_keys=True,
    )

    assert "super-secret" not in output
    assert "postgresql://" not in output
    assert "11111111-1111-1111-1111-111111111111" not in output
    assert "22222222-2222-2222-2222-222222222222" not in output


def test_runtime_cli_writes_only_sanitized_report(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.track_bc_verify import main

    evidence_path = tmp_path / "runtime-evidence.json"
    output_path = tmp_path / "accepted-runtime.json"
    evidence_path.write_text(json.dumps(_accepted_runtime_evidence()), encoding="utf-8")

    exit_code = main(
        [
            "runtime",
            "--evidence",
            str(evidence_path),
            "--expected-release-sha",
            RELEASE_SHA,
            "--output",
            str(output_path),
        ]
    )

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(stdout)["status"] == "accepted"
    written = output_path.read_text(encoding="utf-8")
    assert json.loads(written)["status"] == "accepted"
    assert "super-secret" not in stdout
    assert "super-secret" not in written


def test_runtime_cli_rejects_malformed_evidence_without_echoing_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.track_bc_verify import main

    evidence_path = tmp_path / "malformed.json"
    evidence_path.write_text('{"password":"do-not-echo"', encoding="utf-8")

    exit_code = main(
        [
            "runtime",
            "--evidence",
            str(evidence_path),
            "--expected-release-sha",
            RELEASE_SHA,
        ]
    )

    stdout = capsys.readouterr().out
    assert exit_code == 2
    assert json.loads(stdout) == {
        "schema_version": 1,
        "stage": "runtime",
        "status": "rejected",
        "errors": ["invalid_evidence_file"],
    }
    assert "do-not-echo" not in stdout


def _accepted_canary_evidence() -> dict[str, object]:
    return {
        "job_run_correlated": True,
        "job_status": "dispatched",
        "run_status": "succeeded",
        "run_finished_age_seconds": 1,
        "open_candidate_count": 0,
        "persisted_candidate_count": 1,
        "artifact_record_count": 1,
        "artifact_retrievable": True,
        "evidence_jsonl": True,
        "evidence_bounded": True,
        "evidence_redacted": True,
        "evidence_correlation_match": True,
        "evidence_release_sha": RELEASE_SHA,
        "evidence_terminal_event": True,
        "child_pid_alive": False,
        "profile_locked": False,
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "run_id": "33333333-3333-3333-3333-333333333333",
        "storage_key": "tenants/private/contract.pdf",
    }


def test_canary_verification_accepts_complete_chain() -> None:
    from scripts.track_bc_verify import verify_canary_evidence

    report = verify_canary_evidence(
        _accepted_canary_evidence(),
        expected_release_sha=RELEASE_SHA,
        observed_at=datetime(2026, 8, 22, 13, 30, tzinfo=UTC),
    )

    assert report.schema_version == 1
    assert report.stage == "canary"
    assert report.status == "accepted"
    assert report.release_sha == RELEASE_SHA
    assert report.errors == ()
    assert report.observed_at == "2026-08-22T13:30:00+00:00"
    assert report.checks
    assert all(report.checks.values())


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("job_run_correlated", False, "job_run_not_correlated"),
        ("job_status", "pending", "job_not_terminal"),
        ("run_status", "running", "run_not_successful"),
        ("run_finished_age_seconds", 3_601, "run_not_fresh"),
        ("open_candidate_count", 1, "open_candidates_remaining"),
        ("persisted_candidate_count", 0, "no_persisted_candidates"),
        ("artifact_record_count", 0, "artifact_record_missing"),
        ("artifact_retrievable", False, "artifact_not_retrievable"),
        ("evidence_jsonl", False, "evidence_not_jsonl"),
        ("evidence_bounded", False, "evidence_not_bounded"),
        ("evidence_redacted", False, "evidence_not_redacted"),
        ("evidence_correlation_match", False, "evidence_correlation_mismatch"),
        ("evidence_release_sha", "b" * 40, "evidence_release_sha_mismatch"),
        ("evidence_terminal_event", False, "evidence_terminal_event_missing"),
        ("child_pid_alive", True, "child_process_alive"),
        ("profile_locked", True, "profile_still_locked"),
    ],
)
def test_canary_verification_fails_closed_for_each_chain_invariant(
    field: str,
    value: object,
    error_code: str,
) -> None:
    from scripts.track_bc_verify import verify_canary_evidence

    evidence = _accepted_canary_evidence()
    evidence[field] = value

    report = verify_canary_evidence(evidence, expected_release_sha=RELEASE_SHA)

    assert report.status == "rejected"
    assert error_code in report.errors


def test_canary_verification_output_never_contains_sensitive_correlation() -> None:
    from dataclasses import asdict

    from scripts.track_bc_verify import verify_canary_evidence

    output = json.dumps(
        asdict(
            verify_canary_evidence(
                _accepted_canary_evidence(),
                expected_release_sha=RELEASE_SHA,
            )
        ),
        sort_keys=True,
    )

    assert "11111111-1111-1111-1111-111111111111" not in output
    assert "22222222-2222-2222-2222-222222222222" not in output
    assert "33333333-3333-3333-3333-333333333333" not in output
    assert "contract.pdf" not in output


def _seed_canary_chain(
    *,
    database_url: str,
    evidence_path: Path,
    storage_key: str,
) -> tuple[str, str, str]:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    profile_id = "22222222-2222-2222-2222-222222222222"
    job_id = "33333333-3333-3333-3333-333333333333"
    run_id = "44444444-4444-4444-4444-444444444444"
    project_id = "55555555-5555-5555-5555-555555555555"
    with connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, 'Canary', 'canary')",
                (tenant_id,),
            )
            cursor.execute(
                """
                INSERT INTO crawl_profiles (id, tenant_id, name, profile_type)
                VALUES (%s, %s, 'Canary profile', 'tor')
                """,
                (profile_id, tenant_id),
            )
            cursor.execute(
                """
                INSERT INTO discovery_jobs (
                    id, tenant_id, profile_id, profile_type, keyword, trigger_type,
                    live, job_status, execution_backend, attempt_count, next_attempt_at,
                    dispatched_at, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, 'tor', 'canary', 'profile_created',
                    TRUE, 'dispatched', 'legacy', 1, NOW(), NOW(), NOW(), NOW()
                )
                """,
                (job_id, tenant_id, profile_id),
            )
            cursor.execute(
                """
                INSERT INTO crawl_runs (
                    id, tenant_id, profile_id, discovery_job_id, trigger_type,
                    status, started_at, finished_at, summary_json, created_at
                ) VALUES (
                    %s, %s, %s, %s, 'manual', 'succeeded', NOW(), NOW(), %s, NOW()
                )
                """,
                (
                    run_id,
                    tenant_id,
                    profile_id,
                    job_id,
                    json.dumps({"worker_log_path": str(evidence_path)}),
                ),
            )
            cursor.execute(
                """
                INSERT INTO projects (id, tenant_id, canonical_project_id, project_name)
                VALUES (%s, %s, 'canary-project', 'Canary project')
                """,
                (project_id, tenant_id),
            )
            cursor.execute(
                """
                INSERT INTO discovery_candidate_attempts (
                    tenant_id, run_id, candidate_key, keyword,
                    candidate_status, project_id
                ) VALUES (%s, %s, 'canary-key', 'canary', 'persisted', %s)
                """,
                (tenant_id, run_id, project_id),
            )
            cursor.execute(
                """
                INSERT INTO documents (
                    tenant_id, project_id, document_type, document_phase,
                    source_label, source_status_text, file_name, size_bytes,
                    sha256, storage_key
                ) VALUES (%s, %s, 'tor', 'final', '', '', 'contract.pdf', 7, %s, %s)
                """,
                (tenant_id, project_id, "f" * 64, storage_key),
            )
            cursor.execute(
                """
                INSERT INTO document_capture_attempts (
                    tenant_id, project_id, run_id, status, doc_count
                ) VALUES (%s, %s, %s, 'succeeded', 1)
                """,
                (tenant_id, project_id, run_id),
            )
        connection.commit()
    return tenant_id, job_id, run_id


def test_canary_collector_probes_postgres_artifact_evidence_process_and_profile(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if not postgres_binaries_available():
        pytest.skip("PostgreSQL binaries are required for canary-chain verification")

    from scripts.track_bc_verify import collect_canary_evidence, verify_canary_evidence

    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    storage_key = artifacts.put_bytes(key="canary/contract.pdf", data=b"canary!")
    evidence_path = tmp_path / "worker.jsonl"
    impossible_child_pid = 99_999_999

    with TempPostgresCluster() as cluster:
        cluster.create_database("egp_track_bc_canary")
        database_url = cluster.database_url("egp_track_bc_canary")
        apply_migrations(
            database_url=database_url,
            migrations_dir=repo_root / "packages/db/src/migrations",
        )

        writer = BoundedEvidenceWriter(
            path=evidence_path,
            correlation=EvidenceCorrelation(
                tenant_id="11111111-1111-1111-1111-111111111111",
                run_id="44444444-4444-4444-4444-444444444444",
                job_id="33333333-3333-3333-3333-333333333333",
                owner_pid=None,
                child_pid=impossible_child_pid,
                execution_backend="legacy",
                release_sha=RELEASE_SHA,
            ),
        )
        writer.write_lifecycle("dispatch_started")
        writer.write_child("stderr", "Authorization: Bearer secret-token\n")
        writer.write_lifecycle("dispatch_finished")
        writer.close()

        tenant_id, job_id, run_id = _seed_canary_chain(
            database_url=database_url,
            evidence_path=evidence_path,
            storage_key=storage_key,
        )
        profile_dir = tmp_path / "chrome-profile"
        profile_dir.mkdir()

        evidence = collect_canary_evidence(
            database_url=database_url,
            artifact_store=artifacts,
            tenant_id=tenant_id,
            job_id=job_id,
            run_id=run_id,
            expected_release_sha=RELEASE_SHA,
            profile_dir=profile_dir,
        )

        request_path = tmp_path / "private-canary-request.json"
        output_path = tmp_path / "canary-receipt.json"
        request_path.write_text(
            json.dumps(
                {
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "run_id": run_id,
                }
            ),
            encoding="utf-8",
        )
        request_path.chmod(0o600)
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("EGP_ARTIFACT_STORE", "local")
        monkeypatch.setenv("EGP_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
        monkeypatch.setenv("EGP_BROWSER_PROFILE_MODE", "persistent")
        monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(profile_dir))
        from scripts.track_bc_verify import main

        exit_code = main(
            [
                "canary",
                "--request",
                str(request_path),
                "--expected-release-sha",
                RELEASE_SHA,
                "--output",
                str(output_path),
            ]
        )

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE documents
                    SET created_at = (
                        SELECT started_at - INTERVAL '1 second'
                        FROM crawl_runs
                        WHERE id = %s
                    )
                    WHERE tenant_id = %s
                    """,
                    (run_id, tenant_id),
                )
            connection.commit()
        old_artifact_evidence = collect_canary_evidence(
            database_url=database_url,
            artifact_store=artifacts,
            tenant_id=tenant_id,
            job_id=job_id,
            run_id=run_id,
            expected_release_sha=RELEASE_SHA,
            profile_dir=profile_dir,
        )

        with connect(database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM document_capture_attempts WHERE run_id = %s",
                    (run_id,),
                )
            connection.commit()
        uncorrelated_artifact_evidence = collect_canary_evidence(
            database_url=database_url,
            artifact_store=artifacts,
            tenant_id=tenant_id,
            job_id=job_id,
            run_id=run_id,
            expected_release_sha=RELEASE_SHA,
            profile_dir=profile_dir,
        )

    assert UUID(tenant_id)
    assert evidence["job_run_correlated"] is True
    assert evidence["run_finished_age_seconds"] is not None
    assert evidence["artifact_retrievable"] is True
    assert evidence["evidence_redacted"] is True
    assert evidence["child_pid_alive"] is False
    report = verify_canary_evidence(evidence, expected_release_sha=RELEASE_SHA)
    assert report.status == "accepted"
    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(stdout)["status"] == "accepted"
    assert json.loads(output_path.read_text(encoding="utf-8"))["stage"] == "canary"
    assert tenant_id not in stdout
    assert job_id not in stdout
    assert run_id not in stdout
    assert old_artifact_evidence["artifact_record_count"] == 0
    assert old_artifact_evidence["artifact_retrievable"] is False
    assert uncorrelated_artifact_evidence["artifact_record_count"] == 0
    assert uncorrelated_artifact_evidence["artifact_retrievable"] is False


def test_canary_request_uses_configured_profile_and_rejects_caller_override() -> None:
    from scripts.track_bc_verify import _parse_canary_request

    expected = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "run_id": "33333333-3333-3333-3333-333333333333",
    }

    assert _parse_canary_request(expected) == expected
    assert _parse_canary_request({**expected, "profile_dir": "/tmp/untrusted"}) is None


def test_private_canary_request_requires_regular_owned_mode_0600_uuid_file(
    tmp_path: Path,
) -> None:
    from scripts.track_bc_verify import _read_private_canary_request

    expected = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "run_id": "33333333-3333-3333-3333-333333333333",
    }
    request = tmp_path / "canary-request.json"
    request.write_text(json.dumps(expected), encoding="utf-8")
    request.chmod(0o600)

    assert _read_private_canary_request(request) == expected

    request.chmod(0o644)
    with pytest.raises(ValueError, match="invalid_canary_request"):
        _read_private_canary_request(request)

    request.chmod(0o600)
    symlink = tmp_path / "canary-request-link.json"
    symlink.symlink_to(request)
    with pytest.raises(ValueError, match="invalid_canary_request"):
        _read_private_canary_request(symlink)

    request.write_text(
        json.dumps({**expected, "run_id": "not-a-uuid"}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="invalid_canary_request"):
        _read_private_canary_request(request)


def test_canary_cli_rejects_non_private_request_before_runtime_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.track_bc_verify as verifier

    request = tmp_path / "public-canary-request.json"
    request.write_text(
        json.dumps(
            {
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "job_id": "22222222-2222-2222-2222-222222222222",
                "run_id": "33333333-3333-3333-3333-333333333333",
            }
        ),
        encoding="utf-8",
    )
    request.chmod(0o644)

    def unexpected_runtime_dependency() -> None:
        raise AssertionError("runtime dependency must not be constructed")

    monkeypatch.setattr(
        verifier,
        "_build_cli_canary_profile_dir",
        unexpected_runtime_dependency,
    )
    exit_code = verifier.main(
        [
            "canary",
            "--request",
            str(request),
            "--expected-release-sha",
            RELEASE_SHA,
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": 1,
        "stage": "canary",
        "status": "rejected",
        "errors": ["invalid_canary_request"],
    }


def _accepted_stage_receipt(stage: str, observed_at: str) -> dict[str, object]:
    observed = datetime.fromisoformat(observed_at)
    if stage == "runtime":
        from scripts.track_bc_verify import verify_runtime_evidence

        return asdict(
            verify_runtime_evidence(
                _accepted_runtime_evidence(observed),
                expected_release_sha=RELEASE_SHA,
                observed_at=observed,
            )
        )
    if stage == "canary":
        from scripts.track_bc_verify import verify_canary_evidence

        return asdict(
            verify_canary_evidence(
                _accepted_canary_evidence(),
                expected_release_sha=RELEASE_SHA,
                observed_at=observed,
            )
        )
    if stage == "supervised":
        return {
            "schema_version": 1,
            "stage": "supervised",
            "status": "accepted",
            "release_sha": RELEASE_SHA,
            "observed_at": observed_at,
            "deadline_reached": True,
            "process_group_reaped": True,
            "postflight_runtime_accepted": True,
            "errors": [],
        }
    raise ValueError(f"unsupported test stage {stage}")


def _accepted_bundle_evidence() -> dict[str, object]:
    return {
        "receipts": [
            _accepted_stage_receipt("runtime", "2026-08-22T14:00:00+00:00"),
            _accepted_stage_receipt("canary", "2026-08-22T14:01:00+00:00"),
            _accepted_stage_receipt("supervised", "2026-08-22T14:06:00+00:00"),
        ],
        "rollback": {
            "schema_version": 1,
            "stage": "rollback",
            "status": "rehearsed",
            "release_sha": RELEASE_SHA,
            "observed_at": "2026-08-22T14:07:00+00:00",
            "checks": {
                "launchd_uninstalled": True,
                "watcher_stopped": True,
                "tunnel_closed": True,
                "discovery_executor_zero": True,
            },
        },
        "database_url": "postgresql://admin:bundle-secret@example.invalid/egp",
    }


def test_bundle_verification_accepts_fresh_exact_sha_stages_and_rollback() -> None:
    from scripts.track_bc_verify import verify_acceptance_bundle

    report = verify_acceptance_bundle(
        _accepted_bundle_evidence(),
        expected_release_sha=RELEASE_SHA,
        observed_at=datetime(2026, 8, 22, 14, 8, tzinfo=UTC),
        max_age_seconds=3600,
    )

    assert report.schema_version == 1
    assert report.stage == "bundle"
    assert report.status == "accepted"
    assert report.release_sha == RELEASE_SHA
    assert report.errors == ()
    assert all(report.checks.values())


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (
            lambda value: value["receipts"].pop(),  # type: ignore[union-attr]
            "required_stage_missing",
        ),
        (
            lambda value: value["receipts"].append(  # type: ignore[union-attr]
                _accepted_stage_receipt("runtime", "2026-08-22T14:00:00+00:00")
            ),
            "duplicate_stage",
        ),
        (
            lambda value: value["receipts"][0].update({"status": "rejected"}),  # type: ignore[index,union-attr]
            "stage_not_accepted",
        ),
        (
            lambda value: value["receipts"][1].update({"release_sha": "b" * 40}),  # type: ignore[index,union-attr]
            "stage_release_sha_mismatch",
        ),
        (
            lambda value: value["receipts"][2].update(  # type: ignore[index,union-attr]
                {"observed_at": "2026-08-20T14:00:00+00:00"}
            ),
            "stage_receipt_stale",
        ),
        (
            lambda value: value["receipts"][0]["checks"].update(  # type: ignore[index,union-attr]
                {"doctor_ready": False}
            ),
            "stage_checks_invalid",
        ),
        (
            lambda value: value["receipts"][1]["checks"].pop(  # type: ignore[index,union-attr]
                "artifact_retrievable"
            ),
            "stage_checks_invalid",
        ),
        (
            lambda value: value["receipts"][2].update(  # type: ignore[index,union-attr]
                {"deadline_reached": False}
            ),
            "stage_checks_invalid",
        ),
        (
            lambda value: value["receipts"][2].update(  # type: ignore[index,union-attr]
                {"errors": ["watcher_exited_before_deadline"]}
            ),
            "stage_checks_invalid",
        ),
        (
            lambda value: value["rollback"].update({"status": "planned"}),  # type: ignore[union-attr]
            "rollback_not_rehearsed",
        ),
        (
            lambda value: value["rollback"]["checks"].update(  # type: ignore[index,union-attr]
                {"tunnel_closed": False}
            ),
            "rollback_checks_incomplete",
        ),
        (
            lambda value: value["receipts"][1].update(  # type: ignore[index,union-attr]
                {"observed_at": "2026-08-22T13:59:00+00:00"}
            ),
            "stage_order_invalid",
        ),
        (
            lambda value: value["rollback"].update(  # type: ignore[union-attr]
                {"observed_at": "2026-08-22T14:05:00+00:00"}
            ),
            "rollback_order_invalid",
        ),
        (
            lambda value: value["rollback"].update(  # type: ignore[union-attr]
                {"operator_note": "unexpected"}
            ),
            "rollback_invalid",
        ),
    ],
)
def test_bundle_verification_fails_closed_for_invalid_stage_or_rollback(
    mutate,
    error_code: str,
) -> None:
    from scripts.track_bc_verify import verify_acceptance_bundle

    evidence = deepcopy(_accepted_bundle_evidence())
    mutate(evidence)

    report = verify_acceptance_bundle(
        evidence,
        expected_release_sha=RELEASE_SHA,
        observed_at=datetime(2026, 8, 22, 14, 8, tzinfo=UTC),
        max_age_seconds=3600,
    )

    assert report.status == "rejected"
    assert error_code in report.errors


def test_bundle_cli_emits_only_sanitized_final_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.track_bc_verify import main

    evidence_path = tmp_path / "bundle-input.json"
    output_path = tmp_path / "bundle-receipt.json"
    evidence_path.write_text(json.dumps(_accepted_bundle_evidence()), encoding="utf-8")

    exit_code = main(
        [
            "bundle",
            "--evidence",
            str(evidence_path),
            "--expected-release-sha",
            RELEASE_SHA,
            "--output",
            str(output_path),
            "--max-age-seconds",
            "31536000",
        ]
    )

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(stdout)["stage"] == "bundle"
    written = output_path.read_text(encoding="utf-8")
    assert json.loads(written)["status"] == "accepted"
    assert "bundle-secret" not in stdout
    assert "bundle-secret" not in written
    assert "private host" not in stdout


def test_public_mvp_runbook_invokes_runtime_image_smoke_with_built_images() -> None:
    runbook = (
        Path(__file__).parents[2] / "docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md"
    ).read_text(encoding="utf-8")

    assert 'API_IMAGE="$(./scripts/release_compose.sh images -q api)"' in runbook
    assert (
        'WORKER_IMAGE="$(./scripts/release_compose.sh images -q discovery-executor)"'
        in runbook
    )
    assert 'EGP_EXPECTED_RELEASE_SHA="$TRACK_BC_SHA"' in runbook
    assert './scripts/smoke_runtime_images.sh "$API_IMAGE" "$WORKER_IMAGE"' in runbook
    assert './scripts/smoke_runtime_images.sh "$TRACK_BC_SHA"' not in runbook


def test_public_mvp_runbook_uses_reproducible_changed_python_format_gate() -> None:
    runbook = (
        Path(__file__).parents[2] / "docs/operations/PUBLIC_MVP_TRACK_BC_RUNBOOK.md"
    ).read_text(encoding="utf-8")

    assert 'TRACK_BC_BASE_SHA="846f82869945fb742eeba3c78ec5c52ece16b6b6"' in runbook
    assert (
        'git merge-base --is-ancestor "$TRACK_BC_BASE_SHA" "$TRACK_BC_SHA"' in runbook
    )
    assert "\"$TRACK_BC_BASE_SHA..$TRACK_BC_SHA\" -- '*.py'" in runbook
    assert "xargs -0 .venv/bin/python -m ruff format --check" in runbook
    assert (
        ".venv/bin/python -m ruff format --check apps packages tests scripts"
        not in runbook
    )
