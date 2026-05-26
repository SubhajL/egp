from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from egp_db.backup_targets import (
    BackupObject,
    LocalFilesystemBackupTarget,
    R2BackupTarget,
    build_target_from_env,
    main as backup_targets_main,
)


def _make_archive_pair(directory: Path, name: str) -> tuple[Path, Path]:
    archive = directory / name
    archive.write_bytes(b"payload")
    sidecar = directory / f"{name}.sha256"
    sidecar.write_text(f"deadbeef  {name}\n", encoding="ascii")
    return archive, sidecar


def test_local_filesystem_target_round_trips_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    target_dir = tmp_path / "remote"
    target_dir.mkdir()
    archive, sidecar = _make_archive_pair(
        source_dir, "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    )
    target = LocalFilesystemBackupTarget(directory=target_dir)

    target.put_file(local_path=archive, object_key=archive.name)
    target.put_file(local_path=sidecar, object_key=sidecar.name)

    fetch_dir = tmp_path / "fetched"
    fetch_dir.mkdir()
    fetched_archive = target.get_file(
        object_key=archive.name, dest_path=fetch_dir / archive.name
    )
    fetched_sidecar = target.get_file(
        object_key=sidecar.name, dest_path=fetch_dir / sidecar.name
    )

    assert fetched_archive.read_bytes() == b"payload"
    assert fetched_sidecar.read_text(encoding="ascii").startswith("deadbeef ")


def test_local_filesystem_target_lists_objects_oldest_first(tmp_path: Path) -> None:
    target = LocalFilesystemBackupTarget(directory=tmp_path)
    _make_archive_pair(tmp_path, "egp-pg-2026-04-01T120000Z-aaa1111.dump.gz")
    _make_archive_pair(tmp_path, "egp-pg-2026-05-01T120000Z-bbb2222.dump.gz")
    _make_archive_pair(tmp_path, "egp-pg-2026-03-01T120000Z-ccc3333.dump.gz")

    listed = target.list_objects()
    names = [obj.object_key for obj in listed]
    assert names == [
        "egp-pg-2026-03-01T120000Z-ccc3333.dump.gz",
        "egp-pg-2026-04-01T120000Z-aaa1111.dump.gz",
        "egp-pg-2026-05-01T120000Z-bbb2222.dump.gz",
    ]
    assert all(isinstance(obj.timestamp, datetime) for obj in listed)


def test_local_filesystem_target_deletes_object_and_sidecar(tmp_path: Path) -> None:
    target = LocalFilesystemBackupTarget(directory=tmp_path)
    archive, sidecar = _make_archive_pair(
        tmp_path, "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    )
    target.delete_file(object_key=archive.name)
    assert archive.exists() is False
    assert sidecar.exists() is False


def test_r2_backup_target_uploads_with_fake_client_using_r2_endpoint(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    archive.write_bytes(b"payload")
    fake_client = MagicMock()
    target = R2BackupTarget(
        client=fake_client,
        bucket="egp-backups",
        object_prefix="prod/",
    )
    returned_key = target.put_file(local_path=archive, object_key=archive.name)
    fake_client.upload_file.assert_called_once()
    call_kwargs = fake_client.upload_file.call_args.kwargs
    assert call_kwargs["Filename"] == str(archive)
    assert call_kwargs["Bucket"] == "egp-backups"
    assert call_kwargs["Key"] == "prod/" + archive.name
    assert returned_key == "prod/" + archive.name


def test_r2_backup_target_downloads_to_dest_path(tmp_path: Path) -> None:
    fake_client = MagicMock()
    target = R2BackupTarget(client=fake_client, bucket="egp-backups", object_prefix="")
    dest = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    target.get_file(object_key=dest.name, dest_path=dest)
    fake_client.download_file.assert_called_once_with(
        Bucket="egp-backups", Key=dest.name, Filename=str(dest)
    )


def test_r2_backup_target_lists_objects_with_pagination(tmp_path: Path) -> None:
    fake_client = MagicMock()
    fake_paginator = MagicMock()
    fake_client.get_paginator.return_value = fake_paginator
    fake_paginator.paginate.return_value = iter(
        [
            {
                "Contents": [
                    {
                        "Key": "prod/egp-pg-2026-05-01T120000Z-aaa1111.dump.gz",
                        "Size": 100,
                    },
                    {
                        "Key": "prod/egp-pg-2026-05-02T120000Z-bbb2222.dump.gz.sha256",
                        "Size": 80,
                    },
                ]
            },
            {
                "Contents": [
                    {
                        "Key": "prod/egp-pg-2026-04-01T120000Z-ccc3333.dump.gz",
                        "Size": 90,
                    }
                ]
            },
        ]
    )
    target = R2BackupTarget(
        client=fake_client, bucket="egp-backups", object_prefix="prod/"
    )
    listed = target.list_objects()
    keys = [obj.object_key for obj in listed]
    # Sidecars excluded; oldest first; prefix preserved in returned keys
    assert keys == [
        "prod/egp-pg-2026-04-01T120000Z-ccc3333.dump.gz",
        "prod/egp-pg-2026-05-01T120000Z-aaa1111.dump.gz",
    ]
    fake_client.get_paginator.assert_called_once_with("list_objects_v2")
    fake_paginator.paginate.assert_called_once_with(
        Bucket="egp-backups", Prefix="prod/"
    )


def test_r2_backup_target_delete_removes_archive_and_sidecar(tmp_path: Path) -> None:
    fake_client = MagicMock()
    target = R2BackupTarget(
        client=fake_client, bucket="egp-backups", object_prefix="prod/"
    )
    target.delete_file(object_key="prod/egp-pg-2026-05-26T143045Z-abc1234.dump.gz")
    keys = [call.kwargs["Key"] for call in fake_client.delete_object.call_args_list]
    assert "prod/egp-pg-2026-05-26T143045Z-abc1234.dump.gz" in keys
    assert "prod/egp-pg-2026-05-26T143045Z-abc1234.dump.gz.sha256" in keys


def test_build_target_from_env_returns_local_for_local_fs_scheme(
    tmp_path: Path,
) -> None:
    env = {
        "EGP_BACKUP_TARGET": "local-fs",
        "EGP_BACKUP_LOCAL_CACHE_DIR": str(tmp_path),
    }
    target = build_target_from_env(env)
    assert isinstance(target, LocalFilesystemBackupTarget)


def test_build_target_from_env_returns_r2_when_all_r2_vars_set() -> None:
    env = {
        "EGP_BACKUP_TARGET": "r2",
        "EGP_BACKUP_R2_ACCOUNT_ID": "acct-123",
        "EGP_BACKUP_R2_ACCESS_KEY_ID": "key",
        "EGP_BACKUP_R2_SECRET_ACCESS_KEY": "secret",
        "EGP_BACKUP_R2_BUCKET": "egp-backups",
        "EGP_BACKUP_R2_OBJECT_PREFIX": "prod/",
    }
    with patch("egp_db.backup_targets.boto3") as fake_boto3:
        fake_client = MagicMock()
        fake_boto3.client.return_value = fake_client
        target = build_target_from_env(env)
    assert isinstance(target, R2BackupTarget)
    fake_boto3.client.assert_called_once()
    call_kwargs = fake_boto3.client.call_args.kwargs
    assert call_kwargs["endpoint_url"] == "https://acct-123.r2.cloudflarestorage.com"
    assert call_kwargs["aws_access_key_id"] == "key"
    assert call_kwargs["aws_secret_access_key"] == "secret"
    assert call_kwargs["region_name"] == "auto"


def test_build_target_from_env_raises_on_missing_credentials() -> None:
    env = {"EGP_BACKUP_TARGET": "r2", "EGP_BACKUP_R2_ACCOUNT_ID": "acct"}
    with pytest.raises(ValueError, match="EGP_BACKUP_R2_ACCESS_KEY_ID"):
        build_target_from_env(env)


def test_build_target_from_env_honors_object_prefix() -> None:
    env = {
        "EGP_BACKUP_TARGET": "r2",
        "EGP_BACKUP_R2_ACCOUNT_ID": "acct-123",
        "EGP_BACKUP_R2_ACCESS_KEY_ID": "key",
        "EGP_BACKUP_R2_SECRET_ACCESS_KEY": "secret",
        "EGP_BACKUP_R2_BUCKET": "egp-backups",
        "EGP_BACKUP_R2_OBJECT_PREFIX": "staging/",
    }
    with patch("egp_db.backup_targets.boto3"):
        target = build_target_from_env(env)
    assert isinstance(target, R2BackupTarget)
    assert target.object_prefix == "staging/"


def test_build_target_from_env_rejects_unknown_target_kind() -> None:
    env = {"EGP_BACKUP_TARGET": "ftp"}
    with pytest.raises(ValueError, match="EGP_BACKUP_TARGET"):
        build_target_from_env(env)


def test_local_filesystem_target_put_is_noop_when_source_already_in_directory(
    tmp_path: Path,
) -> None:
    # When the local cache dir IS the destination, put_file must not
    # invoke shutil.copy2 (which would raise SameFileError).
    target = LocalFilesystemBackupTarget(directory=tmp_path)
    archive = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    archive.write_bytes(b"payload")
    returned_key = target.put_file(local_path=archive, object_key=archive.name)
    assert returned_key == archive.name
    assert archive.read_bytes() == b"payload"


def test_local_filesystem_target_get_is_noop_when_dest_same_as_source(
    tmp_path: Path,
) -> None:
    target = LocalFilesystemBackupTarget(directory=tmp_path)
    archive = tmp_path / "egp-pg-2026-05-26T143045Z-abc1234.dump.gz"
    archive.write_bytes(b"payload")
    returned = target.get_file(object_key=archive.name, dest_path=archive)
    assert returned == archive
    assert archive.read_bytes() == b"payload"


def test_rotate_remote_cli_rejects_negative_retention_days(tmp_path: Path) -> None:
    env = {
        "EGP_BACKUP_TARGET": "local-fs",
        "EGP_BACKUP_LOCAL_CACHE_DIR": str(tmp_path),
    }
    with pytest.raises(SystemExit):
        backup_targets_main(argv=["rotate-remote", "--retention-days", "-7"], env=env)


def test_rotate_remote_cli_rejects_negative_keep_min(tmp_path: Path) -> None:
    env = {
        "EGP_BACKUP_TARGET": "local-fs",
        "EGP_BACKUP_LOCAL_CACHE_DIR": str(tmp_path),
    }
    with pytest.raises(SystemExit):
        backup_targets_main(
            argv=["rotate-remote", "--retention-days", "30", "--keep-min", "-1"],
            env=env,
        )


def test_backup_object_dataclass_is_frozen() -> None:
    obj = BackupObject(
        object_key="x.dump.gz",
        timestamp=datetime(2026, 5, 26, tzinfo=UTC),
        size_bytes=42,
    )
    with pytest.raises(Exception):
        obj.object_key = "other"  # type: ignore[misc]
