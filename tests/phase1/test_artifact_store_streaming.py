"""Tests for the chunked-streaming additions to ArtifactStore implementations."""

from __future__ import annotations

import io

from egp_db.artifact_store import (
    DEFAULT_DOWNLOAD_CHUNK_SIZE,
    LocalArtifactStore,
    S3ArtifactStore,
    iter_artifact_bytes,
)


def test_local_artifact_store_iter_bytes_yields_multiple_chunks(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    payload = b"X" * (DEFAULT_DOWNLOAD_CHUNK_SIZE * 2 + 17)
    store.put_bytes(key="a/b.bin", data=payload)

    chunks = list(store.iter_bytes("a/b.bin"))

    # Three chunks: two full ones plus the 17-byte tail.
    assert len(chunks) == 3
    assert all(len(c) <= DEFAULT_DOWNLOAD_CHUNK_SIZE for c in chunks)
    assert b"".join(chunks) == payload


def test_local_artifact_store_iter_bytes_respects_custom_chunk_size(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    store.put_bytes(key="a.bin", data=b"abcdefghij")

    chunks = list(store.iter_bytes("a.bin", chunk_size=3))

    assert chunks == [b"abc", b"def", b"ghi", b"j"]


def test_iter_artifact_bytes_falls_back_to_get_bytes_when_no_iter_bytes() -> None:
    """A legacy store exposing only get_bytes should still stream as one chunk."""

    class LegacyStore:
        def get_bytes(self, key: str) -> bytes:
            assert key == "k"
            return b"legacy-payload"

    chunks = list(iter_artifact_bytes(LegacyStore(), "k"))

    assert chunks == [b"legacy-payload"]


class _FakeStreamingBody:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def iter_chunks(self, chunk_size: int):
        for offset in range(0, len(self._payload), chunk_size):
            yield self._payload[offset : offset + chunk_size]


class _FakeS3Client:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def get_object(self, *, Bucket: str, Key: str):  # noqa: N803 (boto API)
        return {"Body": _FakeStreamingBody(self._payload)}


def test_s3_artifact_store_iter_bytes_uses_iter_chunks_when_available() -> None:
    payload = b"S" * 8192
    store = S3ArtifactStore(bucket="test-bucket", client=_FakeS3Client(payload))

    chunks = list(store.iter_bytes("doc.bin", chunk_size=1024))

    assert len(chunks) == 8
    assert b"".join(chunks) == payload


def test_s3_artifact_store_iter_bytes_falls_back_to_read_for_plain_body() -> None:
    payload = b"plain-bytes"

    class _PlainBodyClient:
        def get_object(self, *, Bucket: str, Key: str):  # noqa: N803
            return {"Body": io.BytesIO(payload)}

    store = S3ArtifactStore(bucket="b", client=_PlainBodyClient())

    chunks = list(store.iter_bytes("k"))

    assert chunks == [payload]
