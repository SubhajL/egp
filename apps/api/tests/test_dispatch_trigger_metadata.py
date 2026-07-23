"""TDD: queued discovery jobs keep their trigger metadata through dispatch.

Previously ``SubprocessDiscoveryDispatcher`` hardcoded ``trigger_type="manual"``
on the run it created, so a ``schedule`` job produced a ``manual`` run and the
scheduler's due-tenant calculation (which only counts ``schedule`` runs) never
saw it — re-firing every tick. The processor must thread ``job.trigger_type`` /
``job.live`` into the dispatch request, and the subprocess dispatcher must write
the mapped run trigger into both ``create_run`` and the worker payload.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from egp_api.services.discovery_dispatch import (
    DiscoveryDispatchProcessor,
    DiscoveryDispatchRequest,
)
from egp_api.services.discovery_worker_dispatcher import SubprocessDiscoveryDispatcher
from egp_db.repositories.discovery_job_repo import DiscoveryJobRecord

TENANT_ID = "11111111-1111-1111-1111-111111111111"
PROFILE_ID = "22222222-2222-2222-2222-222222222222"


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        on_communicate: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self.returncode = returncode
        self.pid = 51515
        self.payload: bytes | None = None
        self._on_communicate = on_communicate

    def communicate(self, input=None, timeout=None):
        del timeout
        self.payload = input
        payload = json.loads((input or b"{}").decode("utf-8"))
        if self._on_communicate is not None:
            self._on_communicate(payload)
        result = {
            "command": "discover",
            "run_id": payload.get("run_id"),
            "run_status": "succeeded",
            "project_count": 0,
            "project_ids": [],
        }
        return (json.dumps(result).encode("utf-8"), b"")


class _RecordingRunRepository:
    def __init__(self) -> None:
        self.create_run_kwargs: dict[str, object] = {}

    def create_run(self, *, tenant_id, trigger_type, profile_id=None, summary_json=None, run_id=None):
        self.create_run_kwargs = {
            "tenant_id": tenant_id,
            "trigger_type": trigger_type,
            "profile_id": profile_id,
            "run_id": run_id,
        }

    def update_run_summary(self, run_id, *, summary_json=None):
        del run_id, summary_json

    def fail_run_if_active(self, *args, **kwargs):
        del args, kwargs
        return None


def _job(*, trigger_type: str, live: bool = True) -> DiscoveryJobRecord:
    return DiscoveryJobRecord(
        id="33333333-3333-3333-3333-333333333333",
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="analytics",
        trigger_type=trigger_type,
        live=live,
        job_status="pending",
        attempt_count=0,
        last_error=None,
        last_error_code=None,
        next_attempt_at="2026-04-07T00:00:00+00:00",
        processing_started_at=None,
        claim_token="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        lease_expires_at="2099-04-07T00:00:00+00:00",
        lease_heartbeat_at="2026-04-07T00:00:00+00:00",
        dispatched_at=None,
        created_at="2026-04-07T00:00:00+00:00",
        updated_at="2026-04-07T00:00:00+00:00",
    )


class _RecordingDispatcher:
    def __init__(self) -> None:
        self.requests: list[DiscoveryDispatchRequest] = []

    def dispatch(self, request: DiscoveryDispatchRequest) -> None:
        self.requests.append(request)


class _NoopJobStore:
    def record_discovery_job_attempt(self, **kwargs):
        del kwargs
        return None


def test_request_defaults_to_manual_live() -> None:
    request = DiscoveryDispatchRequest(
        tenant_id=TENANT_ID,
        profile_id=PROFILE_ID,
        profile_type="custom",
        keyword="x",
    )
    assert request.trigger_type == "manual"
    assert request.live is True


def test_process_job_threads_trigger_type_and_live() -> None:
    dispatcher = _RecordingDispatcher()
    processor = DiscoveryDispatchProcessor(repository=_NoopJobStore(), dispatcher=dispatcher)

    processor.process_job(job=_job(trigger_type="schedule", live=True))

    assert len(dispatcher.requests) == 1
    assert dispatcher.requests[0].trigger_type == "schedule"
    assert dispatcher.requests[0].live is True


def _dispatch_with_fakes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    trigger_type: str,
) -> tuple[_RecordingRunRepository, dict[str, object]]:
    run_repo = _RecordingRunRepository()
    captured_payload: dict[str, object] = {}

    monkeypatch.setenv("EGP_BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.uuid4",
        lambda: "00000000-0000-0000-0000-0000000000ab",
    )
    monkeypatch.setattr(
        "egp_api.services.discovery_worker_dispatcher.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(on_communicate=captured_payload.update),
    )

    dispatcher = SubprocessDiscoveryDispatcher(
        "postgresql://example.test/egp",
        artifact_root=tmp_path / "art",
        run_repository=run_repo,
    )
    dispatcher.dispatch(
        DiscoveryDispatchRequest(
            tenant_id=TENANT_ID,
            profile_id=PROFILE_ID,
            profile_type="custom",
            keyword="analytics",
            trigger_type=trigger_type,
            live=True,
        )
    )
    return run_repo, captured_payload


def test_subprocess_dispatch_preserves_schedule_trigger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_repo, payload = _dispatch_with_fakes(monkeypatch, tmp_path, trigger_type="schedule")
    assert run_repo.create_run_kwargs["trigger_type"] == "schedule"
    assert payload["trigger_type"] == "schedule"


def test_subprocess_dispatch_maps_unknown_trigger_to_manual(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_repo, payload = _dispatch_with_fakes(
        monkeypatch, tmp_path, trigger_type="profile_created"
    )
    assert run_repo.create_run_kwargs["trigger_type"] == "manual"
    assert payload["trigger_type"] == "manual"
