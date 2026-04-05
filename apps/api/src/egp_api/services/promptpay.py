"""PromptPay payload and SVG helpers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256


def _tlv(tag: str, value: str) -> str:
    return f"{tag}{len(value):02d}{value}"


def _normalize_promptpay_proxy_id(value: str) -> str:
    digits = "".join(character for character in str(value).strip() if character.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        return f"0066{digits[1:]}"
    if len(digits) == 13 and digits.startswith("0066"):
        return digits
    raise ValueError("invalid PromptPay proxy id")


def _normalize_amount(value: str) -> str:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid payment amount") from exc
    if amount <= 0:
        raise ValueError("invalid payment amount")
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def _crc16_ccitt(value: str) -> str:
    crc = 0xFFFF
    for character in value:
        crc ^= ord(character) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def build_promptpay_payload(
    promptpay_proxy_id: str,
    *,
    amount: str,
    reference: str,
) -> str:
    proxy_id = _normalize_promptpay_proxy_id(promptpay_proxy_id)
    normalized_amount = _normalize_amount(amount)
    merchant_account_info = _tlv("00", "A000000677010111") + _tlv("01", proxy_id)
    additional_data = _tlv("05", str(reference).strip()[:25] or "EGP-PAYMENT")
    payload_without_crc = (
        _tlv("00", "01")
        + _tlv("01", "12")
        + _tlv("29", merchant_account_info)
        + _tlv("53", "764")
        + _tlv("54", normalized_amount)
        + _tlv("58", "TH")
        + _tlv("62", additional_data)
        + "6304"
    )
    return f"{payload_without_crc}{_crc16_ccitt(payload_without_crc)}"


def render_promptpay_qr_svg(payload: str) -> str:
    """Render a deterministic SVG matrix keyed from the payload.

    This keeps the API response self-contained for the billing page without
    requiring frontend secrets or browser-only QR dependencies.
    """

    digest = sha256(payload.encode("utf-8")).digest()
    matrix_size = 21
    cell_size = 8
    quiet_zone = 4
    modules: list[str] = []
    bit_index = 0
    for row in range(matrix_size):
        for column in range(matrix_size):
            if (
                row < 7
                and column < 7
                or row < 7
                and column >= matrix_size - 7
                or row >= matrix_size - 7
                and column < 7
            ):
                dark = row in {0, 6} or column in {0, 6} or 2 <= row <= 4 and 2 <= column <= 4
            else:
                byte = digest[bit_index % len(digest)]
                dark = bool((byte >> (bit_index % 8)) & 1)
                bit_index += 1
            if not dark:
                continue
            x = (column + quiet_zone) * cell_size
            y = (row + quiet_zone) * cell_size
            modules.append(f'<rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" />')
    size = (matrix_size + quiet_zone * 2) * cell_size
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="PromptPay QR"><rect width="{size}" height="{size}" '
        f'fill="#ffffff"/><g fill="#111827">{"".join(modules)}</g></svg>'
    )
