"""TDD: Chrome launch-command construction for the residential-runner path.

Covers chrome-binary resolution (env > configured-if-exists > bundled Chromium),
proxy injection, headful-under-Xvfb wrapping, and proxy redaction. All defaults
must preserve the existing macOS-dev behaviour (no proxy, no Xvfb, no sandbox flag).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from egp_worker.browser_discovery import (
    BrowserDiscoverySettings,
    build_chrome_launch_command,
    redact_proxy_for_log,
    resolve_chrome_binary,
)


def test_browser_settings_defaults_are_backward_compatible() -> None:
    settings = BrowserDiscoverySettings()
    assert settings.proxy_server is None
    assert settings.use_xvfb is False
    assert settings.chrome_path == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def test_resolve_chrome_binary_prefers_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EGP_BROWSER_CHROME_PATH", "/opt/chrome/chrome")
    assert resolve_chrome_binary("/Applications/Google Chrome.app/...") == "/opt/chrome/chrome"


def test_resolve_chrome_binary_uses_configured_when_it_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("EGP_BROWSER_CHROME_PATH", raising=False)
    real = tmp_path / "chrome"
    real.write_text("#!/bin/sh\n", encoding="utf-8")
    assert resolve_chrome_binary(str(real)) == str(real)


def test_resolve_chrome_binary_falls_back_to_bundled_when_configured_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("EGP_BROWSER_CHROME_PATH", raising=False)
    # Fake a Playwright bundled Chromium under a fake HOME.
    bundled = tmp_path / ".cache" / "ms-playwright" / "chromium-1223" / "chrome-linux64" / "chrome"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    resolved = resolve_chrome_binary("/definitely/not/here/Google Chrome")
    assert resolved == str(bundled)


def test_build_launch_command_default_matches_existing_args() -> None:
    settings = replace(BrowserDiscoverySettings(), cdp_port=9222, browser_profile_dir=Path("/p"))
    command = build_chrome_launch_command(settings, "/bin/chrome")
    assert command[0] == "/bin/chrome"
    assert "--remote-debugging-port=9222" in command
    assert "--user-data-dir=/p" in command
    assert not any(arg.startswith("--proxy-server") for arg in command)
    assert "--no-sandbox" not in command
    assert "--disable-dev-shm-usage" not in command
    assert "xvfb-run" not in command


def test_build_launch_command_includes_proxy_when_set() -> None:
    settings = replace(BrowserDiscoverySettings(), proxy_server="http://1.2.3.4:8000")
    command = build_chrome_launch_command(settings, "/bin/chrome")
    assert "--proxy-server=http://1.2.3.4:8000" in command


def test_build_launch_command_wraps_with_xvfb_and_adds_no_sandbox() -> None:
    settings = replace(BrowserDiscoverySettings(), use_xvfb=True)
    command = build_chrome_launch_command(settings, "/bin/chrome")
    assert command[:4] == ["xvfb-run", "-a", "-s", "-screen 0 1280x900x24"]
    assert "/bin/chrome" in command
    assert "--no-sandbox" in command
    assert "--disable-dev-shm-usage" in command


def test_redact_proxy_for_log_masks_credentials() -> None:
    assert redact_proxy_for_log("http://user:pass@1.2.3.4:8000") == "http://***@1.2.3.4:8000"
    assert redact_proxy_for_log("socks5://user:pass@host:1080") == "socks5://***@host:1080"
    assert redact_proxy_for_log("user:pass@1.2.3.4:8000") == "***@1.2.3.4:8000"
    assert redact_proxy_for_log("http://1.2.3.4:8000") == "http://1.2.3.4:8000"
    assert redact_proxy_for_log(None) is None
