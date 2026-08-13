"""Deterministic lifespan ownership for test clients returned by helpers."""

from __future__ import annotations

from fastapi.testclient import TestClient


_ACTIVE_CLIENTS: list[TestClient] = []


def enter_test_client(client: TestClient) -> TestClient:
    client.__enter__()
    _ACTIVE_CLIENTS.append(client)
    return client


def close_active_test_clients() -> None:
    while _ACTIVE_CLIENTS:
        _ACTIVE_CLIENTS.pop().__exit__(None, None, None)
