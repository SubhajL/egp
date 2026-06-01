"""TDD: config getters for the residential-runner browser knobs.

Defaults must preserve current behaviour (per_run profiles, no proxy, no xvfb,
no explicit chrome path).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from egp_api.config import (
    get_browser_chrome_path,
    get_browser_persistent_profile_dir,
    get_browser_profile_mode,
    get_browser_proxy_server,
    get_browser_use_xvfb,
)


def test_get_browser_profile_mode_defaults_per_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EGP_BROWSER_PROFILE_MODE", raising=False)
    assert get_browser_profile_mode() == "per_run"


def test_get_browser_profile_mode_accepts_persistent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGP_BROWSER_PROFILE_MODE", "persistent")
    assert get_browser_profile_mode() == "persistent"


def test_get_browser_profile_mode_rejects_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGP_BROWSER_PROFILE_MODE", "bogus")
    with pytest.raises(RuntimeError):
        get_browser_profile_mode()


def test_get_browser_chrome_path_none_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EGP_BROWSER_CHROME_PATH", raising=False)
    assert get_browser_chrome_path() is None


def test_get_browser_chrome_path_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGP_BROWSER_CHROME_PATH", "/opt/chrome/chrome")
    assert get_browser_chrome_path() == "/opt/chrome/chrome"


def test_get_browser_proxy_server_none_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EGP_BROWSER_PROXY_SERVER", raising=False)
    assert get_browser_proxy_server() is None


def test_get_browser_proxy_server_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGP_BROWSER_PROXY_SERVER", " http://1.2.3.4:8000 ")
    assert get_browser_proxy_server() == "http://1.2.3.4:8000"


def test_get_browser_proxy_server_rejects_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EGP_BROWSER_PROXY_SERVER", "http://user:pass@1.2.3.4:8000")
    with pytest.raises(RuntimeError):
        get_browser_proxy_server()


def test_get_browser_use_xvfb_false_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EGP_BROWSER_USE_XVFB", raising=False)
    assert get_browser_use_xvfb() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_get_browser_use_xvfb_truthy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("EGP_BROWSER_USE_XVFB", value)
    assert get_browser_use_xvfb() is True


def test_get_browser_persistent_profile_dir_none_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", raising=False)
    assert get_browser_persistent_profile_dir() is None


def test_get_browser_persistent_profile_dir_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EGP_BROWSER_PERSISTENT_PROFILE_DIR", str(tmp_path / "warm"))
    assert get_browser_persistent_profile_dir() == (tmp_path / "warm").resolve()
