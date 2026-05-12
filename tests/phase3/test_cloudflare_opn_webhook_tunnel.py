from scripts.cloudflare_opn_webhook_tunnel import (
    build_local_url,
    build_webhook_url,
    extract_trycloudflare_url,
)


def test_extract_trycloudflare_url_returns_url_from_cloudflared_output() -> None:
    line = "INF | +--------------------------------------------------------------------------------------------+\nINF | |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |\nINF | |  https://gentle-river-bank.trycloudflare.com                                                |\nINF | +--------------------------------------------------------------------------------------------+"

    assert (
        extract_trycloudflare_url(line)
        == "https://gentle-river-bank.trycloudflare.com"
    )


def test_extract_trycloudflare_url_returns_none_when_missing() -> None:
    assert extract_trycloudflare_url("no public url yet") is None


def test_build_local_url_uses_host_port_and_scheme() -> None:
    assert build_local_url(port=8010) == "http://127.0.0.1:8010"
    assert build_local_url(port=8443, host="0.0.0.0", scheme="https") == "https://0.0.0.0:8443"


def test_build_webhook_url_joins_path_cleanly() -> None:
    assert (
        build_webhook_url("https://gentle-river-bank.trycloudflare.com/")
        == "https://gentle-river-bank.trycloudflare.com/v1/billing/providers/opn/webhooks"
    )
    assert (
        build_webhook_url(
            "https://gentle-river-bank.trycloudflare.com",
            path="/custom/webhook",
        )
        == "https://gentle-river-bank.trycloudflare.com/custom/webhook"
    )
