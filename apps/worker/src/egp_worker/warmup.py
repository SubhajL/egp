"""One-shot browser-profile warm-up for persistent-mode crawling.

Loads the e-GP site through the configured browser (headful under Xvfb, via the
proxy relay when set) so Cloudflare grants a clearance that the PERSISTENT
profile keeps. Run ONCE before enabling persistent-mode crawling:

    python -m egp_worker.warmup

Requires EGP_BROWSER_PERSISTENT_PROFILE_DIR; honours EGP_BROWSER_USE_XVFB,
EGP_BROWSER_PROXY_SERVER (creds-free / IP-allowlist only), and the
EGP_BROWSER_*_TIMEOUT_MS knobs. See docs/CRAWLER_PROXY_RUNBOOK.md.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from egp_crawler_core.profile_lock import (
    acquire_profile_lock,
    ProfileLockedError,
    release_profile_lock,
)

from .browser_discovery import (
    MAIN_PAGE_URL,
    SEARCH_URL,
    BrowserDiscoverySettings,
    _wait_for_search_controls_ready,
    connect_playwright_to_chrome,
    launch_real_chrome,
    safe_shutdown,
    wait_for_cloudflare_or_operator,
)


PROFILE_STATE_FILENAME = ".egp-profile-state.json"


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def warmup_settings_from_env(env: Mapping[str, str] | None = None) -> BrowserDiscoverySettings:
    """Build warm-up BrowserDiscoverySettings from the environment (pure/testable)."""
    env = os.environ if env is None else env
    profile_dir = str(env.get("EGP_BROWSER_PERSISTENT_PROFILE_DIR", "")).strip()
    if not profile_dir:
        raise RuntimeError(
            "EGP_BROWSER_PERSISTENT_PROFILE_DIR is required to warm a persistent profile"
        )
    proxy_server = str(env.get("EGP_BROWSER_PROXY_SERVER", "")).strip() or None
    if proxy_server and "@" in proxy_server:
        raise RuntimeError(
            "EGP_BROWSER_PROXY_SERVER must not contain credentials (user:pass@); "
            "use an IP-allowlist proxy / the local relay"
        )
    return BrowserDiscoverySettings(
        cdp_port=int(str(env.get("EGP_BROWSER_WARMUP_CDP_PORT", "9320")).strip()),
        browser_profile_dir=Path(profile_dir).expanduser(),
        use_xvfb=_truthy(str(env.get("EGP_BROWSER_USE_XVFB", ""))),
        proxy_server=proxy_server,
        nav_timeout_ms=int(str(env.get("EGP_BROWSER_NAV_TIMEOUT_MS", "60000")).strip()),
        cloudflare_timeout_ms=int(
            str(env.get("EGP_BROWSER_CLOUDFLARE_TIMEOUT_MS", "120000")).strip()
        ),
        cloudflare_operator_wait_timeout_ms=int(
            str(env.get("EGP_BROWSER_CLOUDFLARE_OPERATOR_TIMEOUT_MS", "600000")).strip()
        ),
    )


def warmup_settings_from_browser_settings(
    browser_settings: Mapping[str, object],
) -> BrowserDiscoverySettings:
    """Build warm-up settings from the dispatcher browser payload."""

    profile_dir = str(browser_settings.get("browser_profile_dir", "")).strip()
    if not profile_dir:
        raise RuntimeError("browser_settings.browser_profile_dir is required to warm a profile")
    return BrowserDiscoverySettings(
        cdp_port=int(str(browser_settings.get("browser_cdp_port", "9320")).strip()),
        browser_profile_dir=Path(profile_dir).expanduser(),
        chrome_path=_optional_string(browser_settings.get("browser_chrome_path")),
        use_xvfb=bool(browser_settings.get("browser_use_xvfb", False)),
        proxy_server=_optional_string(browser_settings.get("browser_proxy_server")),
        nav_timeout_ms=int(str(browser_settings.get("browser_nav_timeout_ms", "60000")).strip()),
        cloudflare_timeout_ms=int(
            str(browser_settings.get("browser_cloudflare_timeout_ms", "120000")).strip()
        ),
        cloudflare_reload_retries=int(
            str(browser_settings.get("browser_cloudflare_reload_retries", "1")).strip()
        ),
        cloudflare_operator_wait_timeout_ms=int(
            str(
                browser_settings.get(
                    "browser_cloudflare_operator_wait_timeout_ms",
                    "600000",
                )
            ).strip()
        ),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _write_profile_success_state(
    profile_dir: Path,
    *,
    source: str,
    now: datetime | None = None,
) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    resolved_now = now or datetime.now(UTC)
    if resolved_now.tzinfo is None:
        resolved_now = resolved_now.replace(tzinfo=UTC)
    payload = {
        "consecutive_warm_failures": 0,
        "last_success_at": resolved_now.astimezone(UTC).isoformat(),
        "operator_action_required": False,
        "source": source,
    }
    (profile_dir / PROFILE_STATE_FILENAME).write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


def warm_page(
    page,
    settings: BrowserDiscoverySettings,
    *,
    wait=wait_for_cloudflare_or_operator,
    controls_ready=_wait_for_search_controls_ready,
) -> None:
    """Navigate e-GP and REQUIRE Cloudflare clearance at each step.

    Raises ``RuntimeError`` if the search controls never become ready, so an
    unwarmed profile is never reported as warmed.
    """
    for url in (MAIN_PAGE_URL, SEARCH_URL):
        page.goto(url, timeout=settings.nav_timeout_ms, wait_until="domcontentloaded")
        if not wait(page, settings, require_search_controls=url == SEARCH_URL):
            raise RuntimeError(f"warm-up failed: Cloudflare not cleared on {url}")
        if url == SEARCH_URL and not controls_ready(page, settings.nav_timeout_ms):
            raise RuntimeError("warm-up failed: search controls not enabled")


def run_profile_warmup(
    settings: BrowserDiscoverySettings,
    *,
    warm_seconds: float,
    acquire_lock: bool = True,
    status_prefix: str = "WARMUP",
) -> bool:
    """Warm or preflight a persistent browser profile.

    Returns ``False`` only when ``acquire_lock`` is requested and another process
    already owns the profile lock.
    """

    from playwright.sync_api import sync_playwright

    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    lock_handle = None
    if acquire_lock:
        try:
            lock_handle = acquire_profile_lock(settings.browser_profile_dir)
        except ProfileLockedError:
            print(
                f"{status_prefix}_SKIP profile busy (crawl active); skipping warm "
                f"profile={settings.browser_profile_dir}",
                flush=True,
            )
            return False

    print(
        f"{status_prefix}_START profile={settings.browser_profile_dir} "
        f"proxy={'set' if settings.proxy_server else 'none'} xvfb={settings.use_xvfb}",
        flush=True,
    )
    pw = None
    browser = None
    proc = None
    try:
        proc = launch_real_chrome(settings, clear_singleton_locks=True)
        pw = sync_playwright().start()
        browser, page = connect_playwright_to_chrome(pw, settings)
        warm_page(page, settings)
        if warm_seconds > 0:
            time.sleep(warm_seconds)
        _write_profile_success_state(settings.browser_profile_dir, source="warm")
        print(f"{status_prefix}_OK profile={settings.browser_profile_dir}", flush=True)
        return True
    finally:
        safe_shutdown(browser=browser, pw=pw, chrome_proc=proc)
        if acquire_lock:
            release_profile_lock(lock_handle)


def main() -> int:
    settings = warmup_settings_from_env()
    warm_seconds = float(os.getenv("EGP_BROWSER_WARMUP_SECONDS", "45"))
    run_profile_warmup(settings, warm_seconds=warm_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
