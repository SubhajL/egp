"""TDD: worker payload -> BrowserDiscoverySettings includes proxy + xvfb flags."""

from __future__ import annotations

from pathlib import Path

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


def test_build_browser_settings_parses_cloudflare_operator_timeout() -> None:
    settings = _build_browser_settings(
        {
            "browser_settings": {
                "browser_cdp_port": 9222,
                "browser_cloudflare_operator_wait_timeout_ms": "45000",
            }
        }
    )
    assert settings is not None
    assert settings.cloudflare_operator_wait_timeout_ms == 45_000


def test_build_browser_settings_parses_diagnostics_dir_from_payload(tmp_path) -> None:
    settings = _build_browser_settings(
        {"browser_settings": {"browser_diagnostics_dir": str(tmp_path / "d")}}
    )
    assert settings is not None
    assert settings.diagnostics_dir == Path(str(tmp_path / "d"))


def test_build_browser_settings_parses_diagnostics_dir_from_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("EGP_BROWSER_DIAGNOSTICS_DIR", str(tmp_path / "e"))
    settings = _build_browser_settings({})
    assert settings is not None
    assert settings.diagnostics_dir == Path(str(tmp_path / "e"))


def test_build_browser_settings_diagnostics_dir_defaults_none(monkeypatch) -> None:
    monkeypatch.delenv("EGP_BROWSER_DIAGNOSTICS_DIR", raising=False)
    settings = _build_browser_settings({"browser_settings": {"browser_cdp_port": 9222}})
    assert settings is not None
    assert settings.diagnostics_dir is None


def test_build_browser_settings_diagnostics_dir_empty_string_is_none(monkeypatch) -> None:
    # QCHECK T1-LOW2 fix: an empty-string payload value must resolve to None, never
    # Path("") (== cwd/repo path), which §0 MUST-NOT forbids.
    monkeypatch.delenv("EGP_BROWSER_DIAGNOSTICS_DIR", raising=False)
    settings = _build_browser_settings(
        {"browser_settings": {"browser_cdp_port": 9222, "browser_diagnostics_dir": ""}}
    )
    assert settings is not None
    assert settings.diagnostics_dir is None
