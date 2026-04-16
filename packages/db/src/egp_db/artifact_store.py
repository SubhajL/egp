"""Artifact storage backends."""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Protocol


class ArtifactStore(Protocol):
    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str: ...

    def get_bytes(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def download_url(self, key: str, *, expires_in: int = 300) -> str: ...


class GoogleDriveClientProtocol(Protocol):
    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]: ...

    def download_file(self, *, access_token: str, file_id: str) -> bytes: ...

    def delete_file(self, *, access_token: str, file_id: str) -> None: ...

    def download_url(self, *, file_id: str) -> str: ...


class OneDriveClientProtocol(Protocol):
    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]: ...

    def download_file(self, *, access_token: str, file_id: str) -> bytes: ...

    def delete_file(self, *, access_token: str, file_id: str) -> None: ...

    def download_url(self, *, access_token: str, file_id: str) -> str: ...


class GoogleDriveArtifactStore:
    def __init__(
        self,
        *,
        client: GoogleDriveClientProtocol,
        access_token: str,
        folder_id: str | None = None,
    ) -> None:
        self._client = client
        self._access_token = access_token
        self._folder_id = folder_id

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        name = PurePosixPath(key.lstrip("/") or "artifact").name
        result = self._client.upload_file(
            access_token=self._access_token,
            folder_id=self._folder_id,
            name=name,
            data=data,
            content_type=content_type,
        )
        file_id = result.get("id")
        if not file_id:
            raise ValueError("Google Drive upload response did not include file id")
        return str(file_id)

    def get_bytes(self, key: str) -> bytes:
        return self._client.download_file(access_token=self._access_token, file_id=key)

    def delete(self, key: str) -> None:
        self._client.delete_file(access_token=self._access_token, file_id=key)

    def download_url(self, key: str, *, expires_in: int = 300) -> str:
        del expires_in
        return self._client.download_url(file_id=key)


class OneDriveArtifactStore:
    def __init__(
        self,
        *,
        client: OneDriveClientProtocol,
        access_token: str,
        folder_id: str | None = None,
    ) -> None:
        self._client = client
        self._access_token = access_token
        self._folder_id = folder_id

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        name = PurePosixPath(key.lstrip("/") or "artifact").name
        result = self._client.upload_file(
            access_token=self._access_token,
            folder_id=self._folder_id,
            name=name,
            data=data,
            content_type=content_type,
        )
        file_id = result.get("id")
        if not file_id:
            raise ValueError("OneDrive upload response did not include file id")
        return str(file_id)

    def get_bytes(self, key: str) -> bytes:
        return self._client.download_file(access_token=self._access_token, file_id=key)

    def delete(self, key: str) -> None:
        self._client.delete_file(access_token=self._access_token, file_id=key)

    def download_url(self, key: str, *, expires_in: int = 300) -> str:
        del expires_in
        return self._client.download_url(access_token=self._access_token, file_id=key)


class LocalArtifactStore:
    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        del content_type
        path = self._base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get_bytes(self, key: str) -> bytes:
        return (self._base_dir / key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._base_dir / key
        if path.exists():
            path.unlink()

    def download_url(self, key: str, *, expires_in: int = 300) -> str:
        del expires_in
        return str((self._base_dir / key).resolve())


class S3ArtifactStore:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        client=None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client

    @property
    def _s3_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def _qualified_key(self, key: str) -> str:
        cleaned = key.lstrip("/")
        if not self._prefix:
            return cleaned
        if cleaned == self._prefix or cleaned.startswith(f"{self._prefix}/"):
            return cleaned
        return f"{self._prefix}/{cleaned}"

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        qualified_key = self._qualified_key(key)
        payload = {
            "Bucket": self._bucket,
            "Key": qualified_key,
            "Body": data,
        }
        if content_type is not None:
            payload["ContentType"] = content_type
        self._s3_client.put_object(**payload)
        return qualified_key

    def get_bytes(self, key: str) -> bytes:
        response = self._s3_client.get_object(
            Bucket=self._bucket,
            Key=self._qualified_key(key),
        )
        body = response["Body"]
        return body.read() if hasattr(body, "read") else bytes(body)

    def delete(self, key: str) -> None:
        self._s3_client.delete_object(Bucket=self._bucket, Key=self._qualified_key(key))

    def download_url(self, key: str, *, expires_in: int = 300) -> str:
        return self._s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )


def _extract_supabase_signed_url(result: Any, *, project_url: str) -> str:
    if isinstance(result, str):
        candidate = result
    elif isinstance(result, dict):
        candidate = (
            result.get("signedURL")
            or result.get("signedUrl")
            or result.get("signed_url")
            or result.get("url")
        )
    else:
        candidate = None

    if not candidate:
        raise ValueError("Supabase signed URL response did not contain a URL")

    if candidate.startswith("http://") or candidate.startswith("https://"):
        return candidate
    base = project_url.rstrip("/")
    if candidate.startswith("/"):
        return f"{base}{candidate}"
    return f"{base}/{candidate}"


class SupabaseArtifactStore:
    def __init__(
        self,
        *,
        project_url: str,
        service_role_key: str,
        bucket: str,
        prefix: str = "",
        client=None,
    ) -> None:
        self._project_url = project_url.rstrip("/")
        self._service_role_key = service_role_key
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client

    @property
    def _supabase_client(self):
        if self._client is None:
            from supabase import create_client

            self._client = create_client(self._project_url, self._service_role_key)
        return self._client

    @property
    def _bucket_client(self):
        return self._supabase_client.storage.from_(self._bucket)

    def _qualified_key(self, key: str) -> str:
        cleaned = key.lstrip("/")
        if not self._prefix:
            return cleaned
        if cleaned == self._prefix or cleaned.startswith(f"{self._prefix}/"):
            return cleaned
        return f"{self._prefix}/{cleaned}"

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        qualified_key = self._qualified_key(key)
        file_options: dict[str, Any] = {"upsert": False}
        if content_type is not None:
            file_options["content-type"] = content_type
        self._bucket_client.upload(qualified_key, data, file_options)
        return qualified_key

    def get_bytes(self, key: str) -> bytes:
        result = self._bucket_client.download(key)
        if isinstance(result, bytes):
            return result
        if hasattr(result, "read"):
            return result.read()
        if isinstance(result, str):
            return result.encode("utf-8")
        raise TypeError("Unsupported Supabase download payload")

    def delete(self, key: str) -> None:
        self._bucket_client.remove([self._qualified_key(key)])

    def download_url(self, key: str, *, expires_in: int = 300) -> str:
        result = self._bucket_client.create_signed_url(
            key,
            expires_in,
            {"download": True},
        )
        return _extract_supabase_signed_url(result, project_url=self._project_url)
