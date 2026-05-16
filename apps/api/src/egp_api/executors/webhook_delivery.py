"""Standalone webhook delivery executor."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Protocol

from egp_api.config import get_database_url
from egp_db.connection import create_shared_engine
from egp_db.repositories.notification_repo import create_notification_repository
from egp_notifications.webhook_delivery import WebhookDeliveryProcessor


logger = logging.getLogger(__name__)


class PendingWebhookProcessor(Protocol):
    def process_pending(self, *, limit: int | None = None) -> int: ...


def build_webhook_delivery_processor(database_url: str | None = None) -> WebhookDeliveryProcessor:
    """Build a repository-backed webhook delivery processor for standalone execution."""

    resolved_database_url = get_database_url(database_url)
    shared_engine = create_shared_engine(resolved_database_url)
    repository = create_notification_repository(
        database_url=resolved_database_url,
        engine=shared_engine,
    )
    return WebhookDeliveryProcessor(repository=repository)


def run_webhook_delivery_once(
    *,
    processor: PendingWebhookProcessor,
    limit: int | None = None,
) -> int:
    """Process one batch of queued webhook deliveries."""

    return processor.process_pending(limit=limit)


async def run_webhook_delivery_loop(
    *,
    processor: PendingWebhookProcessor,
    stop_event: asyncio.Event,
    poll_interval_seconds: float,
    logger: logging.Logger | None = None,
) -> None:
    """Process queued webhook deliveries until `stop_event` is set."""

    resolved_logger = logger or globals()["logger"]
    while not stop_event.is_set():
        try:
            processor.process_pending()
        except Exception:
            resolved_logger.warning(
                "Failed to process pending webhook deliveries",
                exc_info=True,
            )
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=max(0.05, float(poll_interval_seconds)),
            )
        except TimeoutError:
            continue


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Drain queued e-GP webhook deliveries.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch and exit instead of polling forever.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum deliveries to claim in --once mode.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=1.0,
        help="Polling interval for long-running mode.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    processor_factory=build_webhook_delivery_processor,
) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    processor = processor_factory(args.database_url)
    if args.once:
        processed = run_webhook_delivery_once(processor=processor, limit=args.limit)
        logger.info("Processed %d pending webhook deliveries", processed)
        return 0

    try:
        asyncio.run(
            _run_forever(
                processor=processor,
                poll_interval_seconds=args.poll_interval_seconds,
            ),
        )
    except KeyboardInterrupt:
        logger.info("Webhook delivery executor stopped")
        return 130
    return 0


async def _run_forever(
    *,
    processor: PendingWebhookProcessor,
    poll_interval_seconds: float,
) -> None:
    stop_event = asyncio.Event()
    await run_webhook_delivery_loop(
        processor=processor,
        stop_event=stop_event,
        poll_interval_seconds=poll_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
