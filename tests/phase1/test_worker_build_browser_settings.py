"""TDD: worker payload -> BrowserDiscoverySettings includes proxy + xvfb flags."""

from __future__ import annotations

from egp_worker.main import _build_browser_settings


def test_build_browser_settings_parses_proxy_and_xvfb() -> None:
    settings = _build_browser_settings(
        {
            "browser_settings": {
                "browser_cdp_port": 9333,
                "browser_proxy_server": "http://1.2.3.4:8000",
                "browser_use_xvfb": True,
            }
        }
    )
    assert settings is not None
    assert settings.proxy_server == "http://1.2.3.4:8000"
    assert settings.use_xvfb is True
    assert settings.cdp_port == 9333


def test_build_browser_settings_defaults_when_proxy_and_xvfb_absent() -> None:
    settings = _build_browser_settings({"browser_settings": {"browser_cdp_port": 9222}})
    assert settings is not None
    assert settings.proxy_server is None
    assert settings.use_xvfb is False


def test_build_browser_settings_blank_proxy_is_treated_as_none() -> None:
    settings = _build_browser_settings(
        {"browser_settings": {"browser_cdp_port": 9222, "browser_proxy_server": "   "}}
    )
    assert settings is not None
    assert settings.proxy_server is None
