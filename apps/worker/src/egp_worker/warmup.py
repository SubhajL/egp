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

import os
import time
from collections.abc import Mapping
from pathlib import Path

from .browser_discovery import (
    MAIN_PAGE_URL,
    SEARCH_URL,
    BrowserDiscoverySettings,
    connect_playwright_to_chrome,
    launch_real_chrome,
    safe_shutdown,
    wait_for_cloudflare,
)


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
    )


def warm_page(page, settings: BrowserDiscoverySettings, *, wait=wait_for_cloudflare) -> None:
    """Navigate e-GP and REQUIRE Cloudflare clearance at each step.

    Raises ``RuntimeError`` if the search controls never become ready, so an
    unwarmed profile is never reported as warmed.
    """
    for url in (MAIN_PAGE_URL, SEARCH_URL):
        page.goto(url, timeout=settings.nav_timeout_ms, wait_until="domcontentloaded")
        if not wait(page, settings.cloudflare_timeout_ms, settings.cloudflare_reload_retries):
            raise RuntimeError(f"warm-up failed: Cloudflare not cleared on {url}")


def main() -> int:
    from playwright.sync_api import sync_playwright

    settings = warmup_settings_from_env()
    warm_seconds = float(os.getenv("EGP_BROWSER_WARMUP_SECONDS", "45"))
    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"WARMUP_START profile={settings.browser_profile_dir} "
        f"proxy={'set' if settings.proxy_server else 'none'} xvfb={settings.use_xvfb}",
        flush=True,
    )
    proc = launch_real_chrome(settings, clear_singleton_locks=True)
    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser, page = connect_playwright_to_chrome(pw, settings)
        warm_page(page, settings)
        time.sleep(warm_seconds)
        print(f"WARMUP_OK profile={settings.browser_profile_dir}", flush=True)
    finally:
        safe_shutdown(browser=browser, pw=pw, chrome_proc=proc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
