from __future__ import annotations

from egp_db.artifact_store import OneDriveArtifactStore


class FakeOneDriveClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, object]] = []
        self.deleted: list[str] = []
        self.download_url_calls: list[str] = []

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
        return {"id": "onedrive-item-id"}

    def download_file(self, *, access_token: str, file_id: str) -> bytes:
        assert access_token == "access-token"
        assert file_id == "onedrive-item-id"
        return b"stored-bytes"

    def delete_file(self, *, access_token: str, file_id: str) -> None:
        assert access_token == "access-token"
        self.deleted.append(file_id)

    def download_url(self, *, access_token: str, file_id: str) -> str:
        assert access_token == "access-token"
        self.download_url_calls.append(file_id)
        return f"https://onedrive.example/download/{file_id}"


def test_onedrive_artifact_store_put_get_delete_download_url() -> None:
    client = FakeOneDriveClient()
    store = OneDriveArtifactStore(
        client=client,
        access_token="access-token",
        folder_id="folder-id",
    )

    storage_key = store.put_bytes(
        key="tenants/acme/project/tor.pdf",
        data=b"stored-bytes",
        content_type="application/pdf",
    )

    assert storage_key == "onedrive-item-id"
    assert client.uploads == [
        {
            "access_token": "access-token",
            "folder_id": "folder-id",
            "name": "tor.pdf",
            "data": b"stored-bytes",
            "content_type": "application/pdf",
        }
    ]
    assert store.get_bytes("onedrive-item-id") == b"stored-bytes"
    assert store.download_url("onedrive-item-id") == (
        "https://onedrive.example/download/onedrive-item-id"
    )

    store.delete("onedrive-item-id")

    assert client.deleted == ["onedrive-item-id"]
    assert client.download_url_calls == ["onedrive-item-id"]
