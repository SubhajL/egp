"""Remote backup targets: ``RemoteBackupTarget`` protocol and concrete impls.

The local filesystem target mirrors archives to a directory and is used in
tests and on-disk backups; the R2 target uses ``boto3`` with the Cloudflare
R2 S3-compatible endpoint. Both implementations exclude ``.sha256`` sidecars
from ``list_objects`` (sidecars are paired with their archive on delete).
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import boto3

from egp_db.backup_files import parse_backup_name

SUPPORTED_TARGETS = ("r2", "local-fs")
_R2_REQUIRED_VARS = (
    "EGP_BACKUP_R2_ACCOUNT_ID",
    "EGP_BACKUP_R2_ACCESS_KEY_ID",
    "EGP_BACKUP_R2_SECRET_ACCESS_KEY",
    "EGP_BACKUP_R2_BUCKET",
)


@dataclass(frozen=True, slots=True)
class BackupObject:
    object_key: str
    timestamp: datetime | None
    size_bytes: int | None


class RemoteBackupTarget(Protocol):
    def put_file(self, *, local_path: Path, object_key: str) -> str: ...
    def get_file(self, *, object_key: str, dest_path: Path) -> Path: ...
    def list_objects(self) -> list[BackupObject]: ...
    def delete_file(self, *, object_key: str) -> None: ...


@dataclass
class LocalFilesystemBackupTarget:
    """Mirror archives + sidecars to a directory on local disk.

    Used in tests and as the operator-facing "backup to USB/EFS" path.
    """

    directory: Path

    def put_file(self, *, local_path: Path, object_key: str) -> str:
        dest = self.directory / object_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.resolve() == Path(local_path).resolve():
            # source already lives in the target directory (e.g. when the
            # local cache dir IS the local-fs backup destination); nothing
            # to do, the file IS the upload
            return object_key
        shutil.copy2(local_path, dest)
        return object_key

    def get_file(self, *, object_key: str, dest_path: Path) -> Path:
        source = self.directory / object_key
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if Path(dest_path).resolve() == source.resolve():
            return dest_path
        shutil.copy2(source, dest_path)
        return dest_path

    def list_objects(self) -> list[BackupObject]:
        items: list[BackupObject] = []
        for entry in self.directory.iterdir():
            if not entry.is_file():
                continue
            if entry.name.endswith(".sha256"):
                continue
            ts = parse_backup_name(entry.name)
            if ts is None:
                continue
            items.append(
                BackupObject(
                    object_key=entry.name,
                    timestamp=ts,
                    size_bytes=entry.stat().st_size,
                )
            )
        items.sort(key=lambda obj: obj.timestamp or datetime.min)
        return items

    def delete_file(self, *, object_key: str) -> None:
        archive = self.directory / object_key
        sidecar = self.directory / f"{object_key}.sha256"
        if archive.exists():
            archive.unlink()
        if sidecar.exists():
            sidecar.unlink()


@dataclass
class R2BackupTarget:
    """Cloudflare R2 backup target via boto3 with S3-compatible endpoint.

    ``object_prefix`` is prepended to every uploaded key and used when listing.
    Sidecar (``.sha256``) deletion is paired with the archive automatically.
    """

    client: Any
    bucket: str
    object_prefix: str = ""
    _prefix_warned: bool = field(default=False, init=False, repr=False, compare=False)

    def _full_key(self, object_key: str) -> str:
        if object_key.startswith(self.object_prefix):
            return object_key
        return f"{self.object_prefix}{object_key}"

    def put_file(self, *, local_path: Path, object_key: str) -> str:
        full_key = self._full_key(object_key)
        self.client.upload_file(
            Filename=str(local_path),
            Bucket=self.bucket,
            Key=full_key,
        )
        return full_key

    def get_file(self, *, object_key: str, dest_path: Path) -> Path:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(
            Bucket=self.bucket,
            Key=object_key,
            Filename=str(dest_path),
        )
        return dest_path

    def list_objects(self) -> list[BackupObject]:
        paginator = self.client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket, Prefix=self.object_prefix)
        items: list[BackupObject] = []
        for page in pages:
            for content in page.get("Contents", []) or []:
                key = content["Key"]
                if key.endswith(".sha256"):
                    continue
                base = key.rsplit("/", maxsplit=1)[-1]
                ts = parse_backup_name(base)
                if ts is None:
                    continue
                items.append(
                    BackupObject(
                        object_key=key,
                        timestamp=ts,
                        size_bytes=content.get("Size"),
                    )
                )
        items.sort(key=lambda obj: obj.timestamp or datetime.min)
        return items

    def delete_file(self, *, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)
        sidecar_key = (
            object_key if object_key.endswith(".sha256") else f"{object_key}.sha256"
        )
        self.client.delete_object(Bucket=self.bucket, Key=sidecar_key)


def build_target_from_env(env: Mapping[str, str]) -> RemoteBackupTarget:
    """Construct the configured backup target from environment variables."""
    kind = env.get("EGP_BACKUP_TARGET", "").strip()
    if kind == "local-fs":
        cache_dir = env.get("EGP_BACKUP_LOCAL_CACHE_DIR", "").strip()
        if not cache_dir:
            raise ValueError(
                "EGP_BACKUP_LOCAL_CACHE_DIR is required when EGP_BACKUP_TARGET=local-fs"
            )
        return LocalFilesystemBackupTarget(directory=Path(cache_dir))
    if kind == "r2":
        missing = [name for name in _R2_REQUIRED_VARS if not env.get(name, "").strip()]
        if missing:
            raise ValueError(
                f"Missing required env vars for R2 target: {', '.join(missing)}"
            )
        account_id = env["EGP_BACKUP_R2_ACCOUNT_ID"].strip()
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=env["EGP_BACKUP_R2_ACCESS_KEY_ID"].strip(),
            aws_secret_access_key=env["EGP_BACKUP_R2_SECRET_ACCESS_KEY"].strip(),
            region_name="auto",
        )
        return R2BackupTarget(
            client=client,
            bucket=env["EGP_BACKUP_R2_BUCKET"].strip(),
            object_prefix=env.get("EGP_BACKUP_R2_OBJECT_PREFIX", "").strip(),
        )
    if not kind:
        raise ValueError(
            "EGP_BACKUP_TARGET is required (one of: "
            + ", ".join(SUPPORTED_TARGETS)
            + ")"
        )
    raise ValueError(
        f"EGP_BACKUP_TARGET={kind!r} is not supported (expected one of: "
        + ", ".join(SUPPORTED_TARGETS)
        + ")"
    )


def _cli_upload(args: list[str], env: Mapping[str, str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="backup_targets upload")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    parsed = parser.parse_args(args)
    target = build_target_from_env(env)
    archive_key = target.put_file(
        local_path=parsed.archive, object_key=parsed.archive.name
    )
    sidecar_key = target.put_file(
        local_path=parsed.sidecar, object_key=parsed.sidecar.name
    )
    print(f"uploaded archive={archive_key} sidecar={sidecar_key}")
    return 0


def _cli_download(args: list[str], env: Mapping[str, str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="backup_targets download")
    parser.add_argument("--object-key", required=True)
    parser.add_argument("--dest-dir", required=True, type=Path)
    parsed = parser.parse_args(args)
    target = build_target_from_env(env)
    parsed.dest_dir.mkdir(parents=True, exist_ok=True)
    archive_name = parsed.object_key.rsplit("/", maxsplit=1)[-1]
    sidecar_key = (
        parsed.object_key
        if parsed.object_key.endswith(".sha256")
        else f"{parsed.object_key}.sha256"
    )
    sidecar_name = sidecar_key.rsplit("/", maxsplit=1)[-1]
    archive_dest = target.get_file(
        object_key=parsed.object_key, dest_path=parsed.dest_dir / archive_name
    )
    sidecar_dest = target.get_file(
        object_key=sidecar_key, dest_path=parsed.dest_dir / sidecar_name
    )
    print(f"archive={archive_dest} sidecar={sidecar_dest}")
    return 0


def _cli_rotate_remote(args: list[str], env: Mapping[str, str]) -> int:
    import argparse
    from datetime import UTC, timedelta

    parser = argparse.ArgumentParser(prog="backup_targets rotate-remote")
    parser.add_argument("--retention-days", required=True, type=int)
    parser.add_argument("--keep-min", default=3, type=int)
    parsed = parser.parse_args(args)
    if parsed.retention_days < 0:
        parser.error("--retention-days must be non-negative")
    if parsed.keep_min < 0:
        parser.error("--keep-min must be non-negative")
    target = build_target_from_env(env)
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=parsed.retention_days)
    listed = target.list_objects()
    listed_sorted = sorted(
        listed,
        key=lambda obj: obj.timestamp or datetime.min,
        reverse=True,
    )
    deleted: list[str] = []
    kept = 0
    for obj in listed_sorted:
        if obj.timestamp is None or obj.timestamp >= cutoff:
            kept += 1
            continue
        if kept < parsed.keep_min:
            kept += 1
            continue
        target.delete_file(object_key=obj.object_key)
        deleted.append(obj.object_key)
    print(f"rotated {len(deleted)} objects")
    for key in deleted:
        print(f"  {key}")
    return 0


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    import argparse
    import os

    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ if env is None else env)

    parser = argparse.ArgumentParser(prog="python -m egp_db.backup_targets")
    parser.add_argument("command", choices=("upload", "download", "rotate-remote"))
    if not argv:
        parser.print_help()
        return 2
    parsed = parser.parse_args(argv[:1])
    rest = argv[1:]
    if parsed.command == "upload":
        return _cli_upload(rest, env)
    if parsed.command == "download":
        return _cli_download(rest, env)
    if parsed.command == "rotate-remote":
        return _cli_rotate_remote(rest, env)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
