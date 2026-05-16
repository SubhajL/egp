from __future__ import annotations

import asyncio

import pytest

from egp_api.bootstrap import background
from egp_api.executors import webhook_delivery


class RecordingProcessor:
    def __init__(self, *, stop_event: asyncio.Event | None = None) -> None:
        self.stop_event = stop_event
        self.limits: list[int | None] = []

    def process_pending(self, *, limit: int | None = None) -> int:
        self.limits.append(limit)
        if self.stop_event is not None:
            self.stop_event.set()
        return 7


def test_run_webhook_delivery_once_passes_limit() -> None:
    processor = RecordingProcessor()

    processed = webhook_delivery.run_webhook_delivery_once(processor=processor, limit=3)

    assert processed == 7
    assert processor.limits == [3]


@pytest.mark.asyncio
async def test_run_webhook_delivery_loop_processes_until_stop_event() -> None:
    stop_event = asyncio.Event()
    processor = RecordingProcessor(stop_event=stop_event)

    await webhook_delivery.run_webhook_delivery_loop(
        processor=processor,
        stop_event=stop_event,
        poll_interval_seconds=0.01,
    )

    assert processor.limits == [None]


def test_main_once_builds_processor_from_database_url() -> None:
    built_urls: list[str] = []
    processor = RecordingProcessor()

    def processor_factory(database_url: str):
        built_urls.append(database_url)
        return processor

    exit_code = webhook_delivery.main(
        [
            "--database-url",
            "sqlite+pysqlite:///webhook-executor.sqlite3",
            "--once",
            "--limit",
            "4",
        ],
        processor_factory=processor_factory,
    )

    assert exit_code == 0
    assert built_urls == ["sqlite+pysqlite:///webhook-executor.sqlite3"]
    assert processor.limits == [4]


def test_background_lifespan_uses_standalone_webhook_executor_loop() -> None:
    assert (
        background.run_webhook_delivery_loop
        is webhook_delivery.run_webhook_delivery_loop
    )
