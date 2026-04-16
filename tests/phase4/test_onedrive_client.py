from __future__ import annotations

import urllib.request

from egp_db.onedrive import OneDriveClient


def test_upload_file_uses_chunked_upload_sessions_for_large_payloads(
    monkeypatch,
) -> None:
    client = OneDriveClient()
    client.upload_chunk_size = 4
    requests: list[urllib.request.Request] = []

    def fake_create_upload_session(**kwargs) -> dict[str, object]:
        assert kwargs["access_token"] == "access-token"
        assert kwargs["folder_id"] == "folder-id"
        assert kwargs["name"] == "artifact.bin"
        return {"uploadUrl": "https://upload.example/session"}

    def fake_request_json(request: urllib.request.Request) -> dict[str, object]:
        requests.append(request)
        content_range = dict(request.header_items())["Content-range"]
        if content_range == "bytes 8-9/10":
            return {"id": "onedrive-item-id"}
        return {"nextExpectedRanges": ["0-0"]}

    monkeypatch.setattr(client, "_create_upload_session", fake_create_upload_session)
    monkeypatch.setattr(client, "_request_json", fake_request_json)

    result = client.upload_file(
        access_token="access-token",
        folder_id="folder-id",
        name="artifact.bin",
        data=b"0123456789",
        content_type="application/octet-stream",
    )

    assert result == {"id": "onedrive-item-id"}
    assert [dict(request.header_items())["Content-range"] for request in requests] == [
        "bytes 0-3/10",
        "bytes 4-7/10",
        "bytes 8-9/10",
    ]
    assert [request.data for request in requests] == [b"0123", b"4567", b"89"]
