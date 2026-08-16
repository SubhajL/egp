from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from egp_observability.logging import RESULT_FRAME_BEGIN, RESULT_FRAME_END
from egp_observability.subprocess_evidence import (
    BoundedEvidenceWriter,
    BoundedResultDecoder,
    EvidenceCorrelation,
    build_run_log_path,
    observe_child_process,
    prune_run_evidence,
    read_bounded_redacted_log,
)


def _correlation() -> EvidenceCorrelation:
    return EvidenceCorrelation(
        tenant_id="tenant-1",
        run_id="run-1",
        job_id=None,
        owner_pid=101,
        child_pid=202,
        execution_backend="subprocess",
        release_sha=None,
    )


def test_evidence_writer_redacts_before_write_and_emits_complete_correlation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "worker.log"
    writer = BoundedEvidenceWriter(path=path, correlation=_correlation())

    writer.write_child(
        "stderr",
        b"Authorization: Bearer secret-token\nservice_role_key=raw-service-secret\n",
    )
    writer.write_lifecycle(
        "dispatch_failed",
        reason="boom",
        detail="api_key=lifecycle-secret",
    )
    writer.close()

    raw = path.read_text(encoding="utf-8")
    assert "secret-token" not in raw
    assert "raw-service-secret" not in raw
    assert "lifecycle-secret" not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    assert [record["seq"] for record in records] == [1, 2, 3]
    assert records[0]["message"] == "Authorization: [REDACTED]"
    assert records[1]["message"] == "service_role_key=[REDACTED]"
    for record in records:
        assert record["tenant_id"] == "tenant-1"
        assert record["run_id"] == "run-1"
        assert "job_id" in record and record["job_id"] is None
        assert record["owner_pid"] == 101
        assert record["child_pid"] == 202
        assert record["execution_backend"] == "subprocess"
        assert "release_sha" in record and record["release_sha"] is None


def test_evidence_writer_never_persists_long_line_secret_continuations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "worker.log"
    writer = BoundedEvidenceWriter(
        path=path,
        correlation=_correlation(),
        max_line_bytes=128,
    )

    writer.write_child(
        "stderr",
        b"service_role_key=" + (b"A" * 400) + b"LEAK-CANARY\nnext-line\n",
    )
    writer.close()

    raw = path.read_text(encoding="utf-8")
    assert "LEAK-CANARY" not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    assert records[0]["message"] == "service_role_key=[REDACTED]"
    assert records[0]["line_truncated"] is True
    assert records[1]["message"] == "next-line"


def test_evidence_writer_requires_a_fresh_log_path(tmp_path: Path) -> None:
    path = tmp_path / "worker.log"
    path.write_text('{"seq":99}\n', encoding="utf-8")

    with pytest.raises(FileExistsError):
        BoundedEvidenceWriter(path=path, correlation=_correlation())

    assert path.read_text(encoding="utf-8") == '{"seq":99}\n'


def test_evidence_writer_bounds_child_bytes_and_preserves_lifecycle_reserve(
    tmp_path: Path,
) -> None:
    path = tmp_path / "worker.log"
    writer = BoundedEvidenceWriter(
        path=path,
        correlation=_correlation(),
        max_total_bytes=900,
        lifecycle_reserve_bytes=600,
        max_line_bytes=80,
        max_records=20,
    )

    for index in range(30):
        writer.write_child("stdout", f"line-{index}-{'x' * 100}\n".encode())
    writer.write_lifecycle("dispatch_failed", reason="worker_timeout")
    writer.close()

    raw = path.read_bytes()
    assert len(raw) <= 900
    records = [json.loads(line) for line in raw.decode().splitlines()]
    assert any(record["event"] == "evidence_truncated" for record in records)
    assert records[-1]["event"] == "dispatch_failed"


def test_evidence_writer_reserves_record_slots_for_terminal_lifecycle(
    tmp_path: Path,
) -> None:
    path = tmp_path / "worker.log"
    writer = BoundedEvidenceWriter(
        path=path,
        correlation=_correlation(),
        max_total_bytes=10_000,
        lifecycle_reserve_bytes=1_000,
        max_records=4,
        lifecycle_reserve_records=2,
    )

    for index in range(20):
        writer.write_child("stdout", f"line-{index}\n".encode())
    writer.write_lifecycle("dispatch_failed", reason="worker_lost")
    writer.close()

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) <= 4
    assert records[-1]["event"] == "dispatch_failed"


def test_observer_captures_two_streams_through_one_ordered_writer(
    tmp_path: Path,
) -> None:
    script = (
        "import os,time; "
        "os.write(1,b'out-1\\n'); time.sleep(.03); "
        "os.write(2,b'err-1\\n'); time.sleep(.03); "
        "os.write(1,b'out-2\\n')"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    path = tmp_path / "worker.log"
    writer = BoundedEvidenceWriter(path=path, correlation=_correlation())
    result = observe_child_process(
        proc,
        payload=b"",
        writer=writer,
        result_decoder=BoundedResultDecoder(),
        timeout_seconds=5,
        cancellation_event=None,
    )
    writer.close()

    assert result.returncode == 0
    records = [json.loads(line) for line in path.read_text().splitlines()]
    child = [record for record in records if record["event"] == "child_output"]
    assert [record["seq"] for record in child] == sorted(
        record["seq"] for record in child
    )
    assert [(record["stream"], record["message"]) for record in child] in (
        [("stdout", "out-1"), ("stderr", "err-1"), ("stdout", "out-2")],
        [("stdout", "out-1"), ("stdout", "out-2"), ("stderr", "err-1")],
    )


def test_result_decoder_is_framed_first_bounded_and_fail_closed() -> None:
    decoder = BoundedResultDecoder(max_bytes=256)
    decoder.feed(b'{"legacy": true}\n')
    decoder.feed(
        f"{RESULT_FRAME_BEGIN}\n{{\"run_id\":\"r\"}}\n{RESULT_FRAME_END}\n".encode()
    )
    assert decoder.decode() == {"run_id": "r"}

    malformed = BoundedResultDecoder(max_bytes=256)
    malformed.feed(f"{RESULT_FRAME_BEGIN}\nnot-json\n{RESULT_FRAME_END}\n".encode())
    malformed.feed(b'{"legacy": true}\n')
    assert malformed.decode() is None

    bounded = BoundedResultDecoder(max_bytes=64)
    bounded.feed(b"x" * 10_000)
    assert bounded.buffered_bytes <= 64


def test_observer_cancels_and_reaps_child_group(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    cancellation = threading.Event()
    cancellation.set()
    writer = BoundedEvidenceWriter(
        path=tmp_path / "worker.log", correlation=_correlation()
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        observe_child_process(
            proc,
            payload=b"",
            writer=writer,
            result_decoder=BoundedResultDecoder(),
            timeout_seconds=5,
            cancellation_event=cancellation,
        )
    writer.close()
    assert proc.poll() is not None


def test_retention_only_deletes_exact_run_logs_and_bounded_reader_redacts(
    tmp_path: Path,
) -> None:
    tenant_root = tmp_path / "tenants" / "tenant-1"
    old_log = tenant_root / "runs" / "old-run" / "worker.log"
    new_log = tenant_root / "runs" / "new-run" / "worker.log"
    manifest = tenant_root / "manifest.json"
    profile = tenant_root / "profiles" / "browser.json"
    for path in (old_log, new_log, manifest, profile):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Bearer top-secret\n" + ("x" * 100), encoding="utf-8")
    os.utime(old_log, (1, 1))

    removed = prune_run_evidence(
        artifact_root=tmp_path,
        tenant_id="tenant-1",
        max_age_seconds=1,
        max_tenant_bytes=150,
        now_timestamp=10_000,
    )

    assert old_log in removed
    assert not old_log.exists()
    assert manifest.exists() and profile.exists()
    assert "top-secret" not in read_bounded_redacted_log(new_log, max_bytes=60)


def test_evidence_paths_reject_traversal_and_retention_never_follows_symlinks(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        build_run_log_path(
            artifact_root=tmp_path,
            tenant_id="../../outside",
            run_id="run-1",
        )
    with pytest.raises(ValueError, match="tenant_id"):
        prune_run_evidence(artifact_root=tmp_path, tenant_id="../../outside")

    outside_log = tmp_path / "outside" / "worker.log"
    outside_log.parent.mkdir()
    outside_log.write_text("preserve", encoding="utf-8")
    runs_root = tmp_path / "tenants" / "tenant-1" / "runs"
    runs_root.mkdir(parents=True)
    (runs_root / "linked-run").symlink_to(outside_log.parent, target_is_directory=True)

    removed = prune_run_evidence(
        artifact_root=tmp_path,
        tenant_id="tenant-1",
        max_age_seconds=0,
        now_timestamp=10_000,
    )

    assert removed == []
    assert outside_log.read_text(encoding="utf-8") == "preserve"


def test_retention_unlink_is_bound_to_verified_run_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_root = tmp_path / "tenants" / "tenant-1" / "runs"
    run_dir = runs_root / "old-run"
    original_log = run_dir / "worker.log"
    outside_log = tmp_path / "outside" / "worker.log"
    original_log.parent.mkdir(parents=True)
    outside_log.parent.mkdir()
    original_log.write_text("old", encoding="utf-8")
    outside_log.write_text("outside", encoding="utf-8")
    os.utime(original_log, (1, 1))
    original_unlink = os.unlink
    swapped = False

    def swap_then_unlink(path, *, dir_fd=None):
        nonlocal swapped
        if path == "worker.log" and dir_fd is not None and not swapped:
            swapped = True
            run_dir.rename(runs_root / "moved-old-run")
            run_dir.symlink_to(outside_log.parent, target_is_directory=True)
        return original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", swap_then_unlink)

    prune_run_evidence(
        artifact_root=tmp_path,
        tenant_id="tenant-1",
        max_age_seconds=1,
        now_timestamp=10_000,
    )

    assert swapped is True
    assert outside_log.read_text(encoding="utf-8") == "outside"
    assert not (runs_root / "moved-old-run" / "worker.log").exists()
