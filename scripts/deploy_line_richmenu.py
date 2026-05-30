#!/usr/bin/env python3
"""Idempotently deploy the e-GP LINE OA rich menu (3 icons).

Phases (run once; re-running is safe):
  1. build the rich menu spec (3 tiled areas across 2500x1686)
  2. delete any existing rich menus on the channel
  3. create the new rich menu
  4. upload the menu image
  5. set it as the default rich menu for all users

Usage:
  EGP_LINE_CHANNEL_ACCESS_TOKEN=... \\
    ./.venv/bin/python scripts/deploy_line_richmenu.py \\
      --image artifacts/line_richmenu.png \\
      --egp-billing-url https://app.egptracker.com/billing \\
      --trading-url https://trading.example.com/billing

If --image is omitted the script tries to render one with Pillow (requires a
Thai-capable font via --font, e.g. Sarabun / Noto Sans Thai).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request as urllib_request

LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_DATA_API_BASE = "https://api-data.line.me/v2/bot"

MENU_WIDTH = 2500
MENU_HEIGHT = 1686


def build_rich_menu_spec(
    *,
    egp_billing_url: str,
    trading_url: str,
    contact_message: str = "ติดต่อแอดมิน",
    name: str = "e-GP Tracker Menu",
    chat_bar_text: str = "เมนู",
) -> dict:
    """Return the LINE rich menu spec with three full-height tiled areas."""
    third = MENU_WIDTH // 3
    last_width = MENU_WIDTH - third * 2  # absorb the rounding remainder
    return {
        "size": {"width": MENU_WIDTH, "height": MENU_HEIGHT},
        "selected": True,
        "name": name,
        "chatBarText": chat_bar_text,
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": third, "height": MENU_HEIGHT},
                "action": {"type": "uri", "uri": egp_billing_url},
            },
            {
                "bounds": {"x": third, "y": 0, "width": third, "height": MENU_HEIGHT},
                "action": {"type": "uri", "uri": trading_url},
            },
            {
                "bounds": {"x": third * 2, "y": 0, "width": last_width, "height": MENU_HEIGHT},
                "action": {"type": "message", "text": contact_message},
            },
        ],
    }


def render_rich_menu_image(out_path: str, *, font_path: str | None = None) -> str:
    """Render a simple 3-cell menu image with Pillow. Returns the output path."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            "Pillow is required to render the menu image; install it or pass --image"
        ) from exc

    image = Image.new("RGB", (MENU_WIDTH, MENU_HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    third = MENU_WIDTH // 3
    cells = [
        ("e-GP Tracker", "ชำระเงิน", "#4F46E5"),
        ("Online Trading", "ชำระเงิน", "#0EA5E9"),
        ("ติดต่อแอดมิน", "chat with us", "#06C755"),
    ]
    font = (
        ImageFont.truetype(font_path, 96)
        if font_path
        else ImageFont.load_default()
    )
    for index, (title, subtitle, color) in enumerate(cells):
        x0 = index * third
        x1 = MENU_WIDTH if index == 2 else x0 + third
        draw.rectangle([x0, 0, x1, MENU_HEIGHT], outline=color, width=8)
        center_x = (x0 + x1) // 2
        draw.text((center_x, MENU_HEIGHT // 2 - 80), title, fill=color, font=font, anchor="mm")
        draw.text(
            (center_x, MENU_HEIGHT // 2 + 80), subtitle, fill="#475569", font=font, anchor="mm"
        )
    image.save(out_path, format="PNG")
    return out_path


def _api_request(
    method: str, url: str, token: str, *, data: bytes | None = None, content_type: str | None = None
) -> bytes:  # pragma: no cover - network
    headers = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=30) as response:
            return response.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"LINE API {method} {url} failed: {exc.code} {body}") from exc


def list_rich_menus(token: str) -> list[dict]:  # pragma: no cover - network
    payload = _api_request("GET", f"{LINE_API_BASE}/richmenu/list", token)
    return json.loads(payload).get("richmenus", [])


def delete_rich_menu(token: str, rich_menu_id: str) -> None:  # pragma: no cover - network
    _api_request("DELETE", f"{LINE_API_BASE}/richmenu/{rich_menu_id}", token)


def create_rich_menu(token: str, spec: dict) -> str:  # pragma: no cover - network
    payload = _api_request(
        "POST",
        f"{LINE_API_BASE}/richmenu",
        token,
        data=json.dumps(spec).encode("utf-8"),
        content_type="application/json",
    )
    return json.loads(payload)["richMenuId"]


def upload_rich_menu_image(token: str, rich_menu_id: str, image_path: str) -> None:  # pragma: no cover - network
    with open(image_path, "rb") as handle:
        data = handle.read()
    content_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
    _api_request(
        "POST",
        f"{LINE_DATA_API_BASE}/richmenu/{rich_menu_id}/content",
        token,
        data=data,
        content_type=content_type,
    )


def set_default_rich_menu(token: str, rich_menu_id: str) -> None:  # pragma: no cover - network
    _api_request("POST", f"{LINE_API_BASE}/user/all/richmenu/{rich_menu_id}", token)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI glue
    parser = argparse.ArgumentParser(description="Deploy the e-GP LINE OA rich menu")
    parser.add_argument("--image", help="Path to the 2500x1686 menu image (PNG/JPEG)")
    parser.add_argument("--font", help="Path to a Thai-capable TTF font for auto-render")
    parser.add_argument(
        "--egp-billing-url", default="https://app.egptracker.com/billing"
    )
    parser.add_argument("--trading-url", default="https://app.egptracker.com/billing")
    parser.add_argument("--contact-message", default="ติดต่อแอดมิน")
    parser.add_argument(
        "--token",
        default=os.getenv("EGP_LINE_CHANNEL_ACCESS_TOKEN", ""),
        help="LINE channel access token (defaults to EGP_LINE_CHANNEL_ACCESS_TOKEN)",
    )
    args = parser.parse_args(argv)

    if not args.token:
        print("EGP_LINE_CHANNEL_ACCESS_TOKEN (or --token) is required", file=sys.stderr)
        return 2

    image_path = args.image
    if not image_path:
        image_path = render_rich_menu_image("line_richmenu.png", font_path=args.font)
        print(f"Rendered menu image -> {image_path}")

    spec = build_rich_menu_spec(
        egp_billing_url=args.egp_billing_url,
        trading_url=args.trading_url,
        contact_message=args.contact_message,
    )

    for existing in list_rich_menus(args.token):
        delete_rich_menu(args.token, existing["richMenuId"])
        print(f"Deleted existing rich menu {existing['richMenuId']}")

    rich_menu_id = create_rich_menu(args.token, spec)
    print(f"Created rich menu {rich_menu_id}")
    upload_rich_menu_image(args.token, rich_menu_id, image_path)
    print("Uploaded menu image")
    set_default_rich_menu(args.token, rich_menu_id)
    print(f"Set {rich_menu_id} as the default rich menu")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
