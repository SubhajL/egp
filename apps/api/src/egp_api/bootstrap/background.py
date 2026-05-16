"""Background-loop bootstrap helpers for the API application."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI

from egp_api.config import BackgroundRuntimeMode
from egp_api.executors.discovery_dispatch import run_discovery_dispatch_loop
from egp_api.executors.webhook_delivery import run_webhook_delivery_loop
from egp_db.db_utils import is_sqlite_url


def discovery_dispatch_loop_enabled_for_database_url(
    database_url: str,
    *,
    background_runtime_mode: BackgroundRuntimeMode = "embedded",
) -> bool:
    if background_runtime_mode == "external":
        return False
    return not is_sqlite_url(database_url)


def discovery_dispatch_route_kick_enabled(
    database_url: str,
    *,
    background_runtime_mode: BackgroundRuntimeMode = "embedded",
) -> bool:
    if background_runtime_mode == "external":
        return False
    return not discovery_dispatch_loop_enabled_for_database_url(
        database_url,
        background_runtime_mode=background_runtime_mode,
    )


def build_lifespan(*, logger: logging.Logger):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        poller_task = None
        poller_stop_event = None
        discovery_task = None
        discovery_stop_event = None
        processor = getattr(app.state, "webhook_delivery_processor", None)
        discovery_processor = getattr(app.state, "discovery_dispatch_processor", None)
        if processor is not None and getattr(
            app.state, "webhook_delivery_processor_enabled", False
        ):
            poller_stop_event = asyncio.Event()
            poller_task = asyncio.create_task(
                run_webhook_delivery_loop(
                    processor=processor,
                    stop_event=poller_stop_event,
                    poll_interval_seconds=1.0,
                )
            )
        if discovery_processor is not None and getattr(
            app.state, "discovery_dispatch_processor_enabled", False
        ):
            discovery_stop_event = asyncio.Event()
            discovery_task = asyncio.create_task(
                run_discovery_dispatch_loop(
                    processor=discovery_processor,
                    run_service=app.state.run_service,
                    owner_pid=os.getpid(),
                    stop_event=discovery_stop_event,
                    poll_interval_seconds=1.0,
                    logger=logger,
                )
            )
        try:
            yield
        finally:
            if poller_stop_event is not None:
                poller_stop_event.set()
            if poller_task is not None:
                poller_task.cancel()
                with suppress(asyncio.CancelledError):
                    await poller_task
            if discovery_stop_event is not None:
                discovery_stop_event.set()
            if discovery_task is not None:
                discovery_task.cancel()
                with suppress(asyncio.CancelledError):
                    await discovery_task

    return lifespan
