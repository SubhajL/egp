from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from egp_db.backup_files import (
    build_backup_name,
    parse_backup_name,
    rotate_local_backup_cache,
    sha256_file,
    verify_sha256_sidecar,
    write_sha256_sidecar,
)


def test_build_backup_name_uses_utc_iso_basic_with_short_sha(
    fixed_now: datetime, fake_git_sha: str
) -> None:
    name = build_backup_name(created_at=fixed_now, git_sha=fake_git_sha)
    assert name == "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"


def test_build_backup_name_rejects_invalid_git_sha(fixed_now: datetime) -> None:
    with pytest.raises(ValueError):
        build_backup_name(created_at=fixed_now, git_sha="not-hex!!")
    with pytest.raises(ValueError):
        build_backup_name(created_at=fixed_now, git_sha="abc")


def test_build_backup_name_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        build_backup_name(created_at=datetime(2026, 1, 1, 0, 0, 0), git_sha="abc1234")


def test_parse_backup_name_returns_utc_timestamp() -> None:
    ts = parse_backup_name("egp-pg-2026-05-26T143045Z-abc1234.dump.gz")
    assert ts == datetime(2026, 5, 26, 14, 30, 45, tzinfo=UTC)


def test_parse_backup_name_returns_none_for_unrelated_filename() -> None:
    assert parse_backup_name("random-file.txt") is None
    assert parse_backup_name("egp-pg-not-a-date.dump.gz") is None


def test_sha256_file_matches_known_digest_for_small_payload(tmp_path: Path) -> None:
    target = tmp_path / "payload.bin"
    target.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert sha256_file(target) == expected


def test_sha256_file_streams_large_payload(tmp_path: Path) -> None:
    target = tmp_path / "large.bin"
    chunk = b"x" * 1024
    expected_hasher = hashlib.sha256()
    with target.open("wb") as handle:
        for _ in range(4096):
            handle.write(chunk)
            expected_hasher.update(chunk)
    assert sha256_file(target, chunk_size=4096) == expected_hasher.hexdigest()


def test_write_sha256_sidecar_emits_hex_and_basename(tmp_path: Path) -> None:
    artifact = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    artifact.write_bytes(b"dummy")
    sidecar = write_sha256_sidecar(artifact, digest="d34db33f")
    assert sidecar == tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz.sha256"
    content = sidecar.read_text(encoding="ascii")
    assert content == "d34db33f  egp-pg-2026-05-26T143045Z-abc1234.dump.gz\n"


def test_verify_sha256_sidecar_passes_for_matching_digest(tmp_path: Path) -> None:
    artifact = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    artifact.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    sidecar = write_sha256_sidecar(artifact, digest=digest)
    verify_sha256_sidecar(artifact, sidecar)  # must not raise


def test_verify_sha256_sidecar_raises_on_tampered_dump(tmp_path: Path) -> None:
    artifact = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    artifact.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    sidecar = write_sha256_sidecar(artifact, digest=digest)
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256 mismatch"):
        verify_sha256_sidecar(artifact, sidecar)


def test_rotate_local_cache_deletes_old_pairs_by_filename_timestamp(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    old_ts = now - timedelta(days=30)
    keep_ts = now - timedelta(days=5)
    old_name = f"egp-pg-{old_ts:%Y-%m-%dT%H%M%SZ}-aaa1111.dump.gz"
    keep_name = f"egp-pg-{keep_ts:%Y-%m-%dT%H%M%SZ}-bbb2222.dump.gz"
    for name in (old_name, keep_name):
        (tmp_path / name).write_bytes(b"x")
        (tmp_path / f"{name}.sha256").write_text("x  " + name + "\n", encoding="ascii")
    deleted = rotate_local_backup_cache(
        tmp_path, retention_days=14, keep_min=0, now=now
    )
    deleted_names = sorted(p.name for p in deleted)
    assert deleted_names == sorted([old_name, f"{old_name}.sha256"])
    assert (tmp_path / keep_name).exists()
    assert (tmp_path / old_name).exists() is False


def test_rotate_local_cache_keeps_newest_minimum_even_when_all_old(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    names: list[str] = []
    for index in range(4):
        ts = now - timedelta(days=100 + index)
        sha = f"{index:07x}"
        name = f"egp-pg-{ts:%Y-%m-%dT%H%M%SZ}-{sha}.dump.gz"
        (tmp_path / name).write_bytes(b"x")
        (tmp_path / f"{name}.sha256").write_text("x  " + name + "\n", encoding="ascii")
        names.append(name)
    rotate_local_backup_cache(tmp_path, retention_days=14, keep_min=2, now=now)
    remaining = sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".gz")
    assert len(remaining) == 2
    expected_kept = sorted(names[:2])
    assert remaining == expected_kept


def test_rotate_local_cache_ignores_non_conforming_filenames(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    (tmp_path / "unrelated.txt").write_text("nope")
    deleted = rotate_local_backup_cache(tmp_path, retention_days=1, keep_min=0, now=now)
    assert deleted == []
    assert (tmp_path / "unrelated.txt").exists()


def test_rotate_local_cache_removes_orphan_sidecars(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
    orphan_ts = now - timedelta(days=30)
    orphan_name = f"egp-pg-{orphan_ts:%Y-%m-%dT%H%M%SZ}-aaa1111.dump.gz"
    (tmp_path / f"{orphan_name}.sha256").write_text("x  " + orphan_name + "\n")
    deleted = rotate_local_backup_cache(
        tmp_path, retention_days=14, keep_min=0, now=now
    )
    assert any(p.name == f"{orphan_name}.sha256" for p in deleted)
