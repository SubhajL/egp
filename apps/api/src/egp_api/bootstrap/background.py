"""Background-loop bootstrap helpers for the API application."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI

from egp_api.services.discovery_dispatch import DiscoveryDispatchProcessor
from egp_db.db_utils import is_sqlite_url
from egp_notifications.webhook_delivery import WebhookDeliveryProcessor


async def _run_webhook_delivery_loop(
    *,
    processor: WebhookDeliveryProcessor,
    stop_event: asyncio.Event,
    poll_interval_seconds: float,
) -> None:
    while not stop_event.is_set():
        processor.process_pending()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, poll_interval_seconds))
        except TimeoutError:
            continue


async def _run_discovery_dispatch_loop(
    *,
    processor: DiscoveryDispatchProcessor,
    stop_event: asyncio.Event,
    poll_interval_seconds: float,
    tick_callback: Callable[[], None] | None = None,
) -> None:
    while not stop_event.is_set():
        if tick_callback is not None:
            tick_callback()
        processor.process_pending()
        if tick_callback is not None:
            tick_callback()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.05, poll_interval_seconds))
        except TimeoutError:
            continue


def discovery_dispatch_loop_enabled_for_database_url(database_url: str) -> bool:
    return not is_sqlite_url(database_url)


def discovery_dispatch_route_kick_enabled(database_url: str) -> bool:
    return not discovery_dispatch_loop_enabled_for_database_url(database_url)


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
                _run_webhook_delivery_loop(
                    processor=processor,
                    stop_event=poller_stop_event,
                    poll_interval_seconds=1.0,
                )
            )
        if discovery_processor is not None and getattr(
            app.state, "discovery_dispatch_processor_enabled", False
        ):

            def _reconcile_missing_workers() -> None:
                try:
                    failed_runs = app.state.run_service.reconcile_missing_workers(
                        owner_pid=os.getpid()
                    )
                except Exception:
                    logger.warning(
                        "Failed to reconcile missing discover workers",
                        exc_info=True,
                    )
                    return
                for failed_run in failed_runs:
                    logger.warning(
                        "Marked discover run %s failed (worker_lost)",
                        failed_run.id,
                    )

            discovery_stop_event = asyncio.Event()
            discovery_task = asyncio.create_task(
                _run_discovery_dispatch_loop(
                    processor=discovery_processor,
                    stop_event=discovery_stop_event,
                    poll_interval_seconds=1.0,
                    tick_callback=_reconcile_missing_workers,
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
