"""Fail-open HTTPS reporting for the out-of-process crawler runtime."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field

import httpx

from egp_shared_types.enums import CrawlerBlockerCode
from egp_api.config import get_crawler_heartbeat_interval_seconds


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CrawlerRuntimeReporter:
    base_url: str
    worker_token: str
    agent_id: str
    timeout_seconds: float = 5.0
    client: object | None = None
    minimum_interval_seconds: float = 30.0
    _last_payload: dict[str, object] | None = field(default=None, init=False)
    _last_report_at: float | None = field(default=None, init=False)
    _last_delivery_succeeded: bool = field(default=False, init=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def report(
        self,
        *,
        watcher_status: str,
        database_status: str,
        profile_status: str,
        circuit_state: str,
        blocker_code: CrawlerBlockerCode | str | None = None,
        circuit_reset_at: str | None = None,
        force: bool = False,
    ) -> bool:
        """Post sanitized state and never interrupt crawling on telemetry failure."""

        payload: dict[str, object] = {
            "agent_id": self.agent_id,
            "runtime_mode": "external",
            "watcher_status": watcher_status,
            "database_status": database_status,
            "blocker_code": (
                CrawlerBlockerCode(blocker_code).value
                if blocker_code is not None
                else None
            ),
            "profile_status": profile_status,
            "circuit_state": circuit_state,
            "circuit_reset_at": circuit_reset_at,
        }
        headers = {
            "Content-Type": "application/json",
            "X-EGP-Worker-Token": self.worker_token,
        }
        now = time.monotonic()
        with self._state_lock:
            within_minimum_interval = (
                self._last_report_at is not None
                and now - self._last_report_at < self.minimum_interval_seconds
            )
            if (
                not force
                and within_minimum_interval
                and (
                    payload == self._last_payload
                    or not self._last_delivery_succeeded
                )
            ):
                return self._last_delivery_succeeded
            # Rate-limit attempts, not only successes. A broken control plane
            # must not make the fail-open crawler hammer HTTP once per DB poll.
            self._last_payload = payload
            self._last_report_at = now
        try:
            if self.client is not None:
                response = self.client.post(
                    "/internal/worker/crawler-runtime/heartbeat",
                    json=payload,
                    headers=headers,
                )
            else:
                with httpx.Client(
                    base_url=self.base_url.rstrip("/"),
                    timeout=self.timeout_seconds,
                ) as client:
                    response = client.post(
                        "/internal/worker/crawler-runtime/heartbeat",
                        json=payload,
                        headers=headers,
                    )
            response.raise_for_status()
        except Exception:
            with self._state_lock:
                self._last_delivery_succeeded = False
            logger.warning("Crawler runtime heartbeat delivery failed", exc_info=True)
            return False
        with self._state_lock:
            self._last_delivery_succeeded = True
        return True


def build_crawler_runtime_reporter_from_env() -> CrawlerRuntimeReporter | None:
    base_url = os.getenv("EGP_INTERNAL_API_BASE_URL", "").strip()
    worker_token = os.getenv("EGP_INTERNAL_WORKER_TOKEN", "").strip()
    if not base_url or not worker_token:
        return None
    return CrawlerRuntimeReporter(
        base_url=base_url,
        worker_token=worker_token,
        agent_id=os.getenv("EGP_CRAWLER_AGENT_ID", "crawler-agent").strip()
        or "crawler-agent",
        minimum_interval_seconds=get_crawler_heartbeat_interval_seconds(),
    )
