"""TDD: warmup_settings_from_env — build warm-up BrowserDiscoverySettings from env."""

from __future__ import annotations

import pytest

from egp_worker.warmup import warm_page, warmup_settings_from_env


class _FakePage:
    def __init__(self) -> None:
        self.gotos: list[str] = []

    def goto(self, url, **kwargs):
        self.gotos.append(url)


def test_requires_persistent_profile_dir() -> None:
    with pytest.raises(RuntimeError):
        warmup_settings_from_env({})


def test_reads_profile_dir_xvfb_and_proxy(tmp_path) -> None:
    s = warmup_settings_from_env(
        {
            "EGP_BROWSER_PERSISTENT_PROFILE_DIR": str(tmp_path / "warm"),
            "EGP_BROWSER_USE_XVFB": "true",
            "EGP_BROWSER_PROXY_SERVER": "http://proxy-relay:8118",
        }
    )
    assert str(s.browser_profile_dir).endswith("warm")
    assert s.use_xvfb is True
    assert s.proxy_server == "http://proxy-relay:8118"


def test_rejects_credentialed_proxy(tmp_path) -> None:
    with pytest.raises(RuntimeError):
        warmup_settings_from_env(
            {
                "EGP_BROWSER_PERSISTENT_PROFILE_DIR": str(tmp_path / "warm"),
                "EGP_BROWSER_PROXY_SERVER": "http://user:pass@host:8118",
            }
        )


def test_defaults(tmp_path) -> None:
    s = warmup_settings_from_env(
        {"EGP_BROWSER_PERSISTENT_PROFILE_DIR": str(tmp_path / "warm")}
    )
    assert s.cdp_port == 9320
    assert s.nav_timeout_ms == 60_000
    assert s.cloudflare_timeout_ms == 120_000
    assert s.use_xvfb is False
    assert s.proxy_server is None


def test_reads_timeouts(tmp_path) -> None:
    s = warmup_settings_from_env(
        {
            "EGP_BROWSER_PERSISTENT_PROFILE_DIR": str(tmp_path / "warm"),
            "EGP_BROWSER_NAV_TIMEOUT_MS": "120000",
            "EGP_BROWSER_CLOUDFLARE_TIMEOUT_MS": "180000",
        }
    )
    assert s.nav_timeout_ms == 120_000
    assert s.cloudflare_timeout_ms == 180_000


def test_warm_page_succeeds_when_cloudflare_clears(tmp_path) -> None:
    page = _FakePage()
    settings = warmup_settings_from_env(
        {"EGP_BROWSER_PERSISTENT_PROFILE_DIR": str(tmp_path)}
    )
    warm_page(page, settings, wait=lambda *a, **k: True)
    assert len(page.gotos) == 2  # main + search


def test_warm_page_raises_when_cloudflare_never_clears(tmp_path) -> None:
    page = _FakePage()
    settings = warmup_settings_from_env(
        {"EGP_BROWSER_PERSISTENT_PROFILE_DIR": str(tmp_path)}
    )
    with pytest.raises(RuntimeError):
        warm_page(page, settings, wait=lambda *a, **k: False)
    assert len(page.gotos) == 1  # stops after the first failed clearance
