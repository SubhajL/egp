from __future__ import annotations

from egp_db.artifact_store import GoogleDriveArtifactStore


class FakeDriveClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, object]] = []
        self.deleted: list[str] = []

    def upload_file(
        self,
        *,
        access_token: str,
        folder_id: str | None,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> dict[str, object]:
        self.uploads.append(
            {
                "access_token": access_token,
                "folder_id": folder_id,
                "name": name,
                "data": data,
                "content_type": content_type,
            }
        )
        return {
            "id": "drive-file-id",
            "webContentLink": "https://drive.google.com/uc?id=drive-file-id",
        }

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        assert access_token == "access-token"
        assert file_id == "drive-file-id"
        return b"stored-bytes"

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        assert access_token == "access-token"
        self.deleted.append(file_id)

    def download_url(self, *, file_id: str) -> str:
        return f"https://drive.google.com/uc?id={file_id}&export=download"


def test_google_drive_artifact_store_put_get_delete_download_url() -> None:
    client = FakeDriveClient()
    store = GoogleDriveArtifactStore(
        client=client,
        access_token="access-token",
        folder_id="folder-id",
    )

    storage_key = store.put_bytes(
        key="tenants/acme/project/tor.pdf",
        data=b"stored-bytes",
        content_type="application/pdf",
    )

    assert storage_key == "drive-file-id"
    assert client.uploads == [
        {
            "access_token": "access-token",
            "folder_id": "folder-id",
            "name": "tor.pdf",
            "data": b"stored-bytes",
            "content_type": "application/pdf",
        }
    ]
    assert store.get_bytes("drive-file-id") == b"stored-bytes"
    assert store.download_url("drive-file-id") == (
        "https://drive.google.com/uc?id=drive-file-id&export=download"
    )

    store.delete("drive-file-id")

    assert client.deleted == ["drive-file-id"]
