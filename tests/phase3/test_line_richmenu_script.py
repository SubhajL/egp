"""Unit tests for the pure helpers in scripts/deploy_line_richmenu.py.

Only the spec builder is exercised — the deploy path performs live LINE API
calls and is not invoked here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "deploy_line_richmenu.py"


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location("deploy_line_richmenu", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_rich_menu_spec_has_three_tiled_areas(module) -> None:
    spec = module.build_rich_menu_spec(
        egp_billing_url="https://app.egptracker.com/billing",
        trading_url="https://trading.example.com/billing",
    )
    assert spec["size"] == {"width": 2500, "height": 1686}
    assert spec["selected"] is True
    areas = spec["areas"]
    assert len(areas) == 3
    # Areas tile left-to-right with no gaps and no overlap, covering full width.
    xs = [(a["bounds"]["x"], a["bounds"]["width"]) for a in areas]
    assert xs[0][0] == 0
    assert xs[0][0] + xs[0][1] == xs[1][0]
    assert xs[1][0] + xs[1][1] == xs[2][0]
    assert xs[2][0] + xs[2][1] == 2500
    for area in areas:
        assert area["bounds"]["y"] == 0
        assert area["bounds"]["height"] == 1686


def test_build_rich_menu_spec_actions(module) -> None:
    spec = module.build_rich_menu_spec(
        egp_billing_url="https://app.egptracker.com/billing",
        trading_url="https://trading.example.com/billing",
        contact_message="ติดต่อแอดมิน",
    )
    actions = [area["action"] for area in spec["areas"]]
    assert actions[0] == {"type": "uri", "uri": "https://app.egptracker.com/billing"}
    assert actions[1] == {"type": "uri", "uri": "https://trading.example.com/billing"}
    assert actions[2] == {"type": "message", "text": "ติดต่อแอดมิน"}
