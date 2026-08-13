from __future__ import annotations

from collections.abc import Sequence
import ipaddress

import pytest

import egp_notifications.webhook_security as webhook_security
from egp_notifications.webhook_security import (
    ApprovedWebhookEndpoint,
    SafeWebhookTransport,
    SocketWebhookDnsResolver,
    WebhookEndpointPolicy,
    WebhookEndpointRejected,
    WebhookEndpointResolutionError,
    WebhookHopResult,
    WebhookRedirectRejected,
)


class FakeResolver:
    def __init__(self, answers: dict[str, Sequence[str]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int]] = []

    def resolve(self, hostname: str, port: int, *, timeout_seconds: float):
        self.calls.append((hostname, port))
        return self.answers[hostname]


@pytest.mark.parametrize(
    ("url", "reason_code"),
    [
        ("http://public.example/hook", "https_required"),
        ("https://user:secret@public.example/hook", "userinfo_not_allowed"),
        ("https://localhost/hook", "hostname_not_allowed"),
        ("https://service.localhost/hook", "hostname_not_allowed"),
        ("https://public.example/hook#fragment", "fragment_not_allowed"),
        ("https://public.example/hook#", "fragment_not_allowed"),
        ("https://127.0.0.1/hook", "address_not_global"),
        ("https://10.0.0.1/hook", "address_not_global"),
        ("https://169.254.169.254/latest/meta-data", "address_not_global"),
        ("https://192.0.2.10/hook", "address_not_global"),
        ("https://[::1]/hook", "address_not_global"),
        ("https://[fc00::1]/hook", "address_not_global"),
        ("https://[fe80::1]/hook", "address_not_global"),
        ("https://[::ffff:127.0.0.1]/hook", "address_not_global"),
        ("https://224.0.0.1/hook", "address_not_global"),
        ("https://[ff02::1]/hook", "address_not_global"),
        ("https://[fec0::1]/hook", "address_not_global"),
        (" https://public.example/hook", "invalid_url"),
        ("https://public.example/hook\n", "invalid_url"),
    ],
)
def test_policy_rejects_unsafe_urls(url: str, reason_code: str) -> None:
    policy = WebhookEndpointPolicy(resolver=FakeResolver({}))

    with pytest.raises(WebhookEndpointRejected) as caught:
        policy.resolve(url)

    assert caught.value.reason_code == reason_code
    assert url not in str(caught.value)


def test_policy_accepts_https_hostname_when_every_answer_is_global() -> None:
    resolver = FakeResolver(
        {"hooks.example.com": ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]}
    )
    policy = WebhookEndpointPolicy(resolver=resolver)

    approved = policy.resolve("https://Hooks.Example.com/events?tenant=1")

    assert approved.canonical_url == "https://hooks.example.com/events?tenant=1"
    assert approved.hostname == "hooks.example.com"
    assert approved.port == 443
    assert approved.request_target == "/events?tenant=1"
    assert tuple(str(address) for address in approved.addresses) == (
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    )
    assert resolver.calls == [("hooks.example.com", 443)]


def test_policy_canonicalizes_unicode_and_spaces_to_ascii_request_target() -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"public.example": ["93.184.216.34"]})
    )

    approved = policy.resolve("https://public.example/แจ้ง เตือน?ชื่อ=ทดสอบ ค่า")

    assert approved.request_target.isascii()
    assert " " not in approved.request_target
    assert "%E0%B9%81" in approved.request_target
    assert "%20" in approved.request_target


def test_policy_rejects_malformed_percent_escape() -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"public.example": ["93.184.216.34"]})
    )

    with pytest.raises(WebhookEndpointRejected) as caught:
        policy.resolve("https://public.example/hook%2")

    assert caught.value.reason_code == "invalid_url"


@pytest.mark.parametrize("surrogate", ["\ud800", "\udfff"])
def test_policy_rejects_lone_unicode_surrogate(surrogate: str) -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"public.example": ["93.184.216.34"]})
    )

    with pytest.raises(WebhookEndpointRejected) as caught:
        policy.resolve(f"https://public.example/{surrogate}")

    assert caught.value.reason_code == "invalid_url"


def test_policy_rejects_mixed_public_and_private_dns_answers() -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"mixed.example": ["93.184.216.34", "10.0.0.5"]})
    )

    with pytest.raises(WebhookEndpointRejected) as caught:
        policy.resolve("https://mixed.example/hook")

    assert caught.value.reason_code == "address_not_global"


def test_redirect_to_private_address_is_blocked_before_second_request() -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"public.example": ["93.184.216.34"]})
    )
    initial = policy.resolve("https://public.example/hook")
    calls: list[ApprovedWebhookEndpoint] = []

    def send_hop(**kwargs) -> WebhookHopResult:
        calls.append(kwargs["endpoint"])
        return WebhookHopResult(
            status_code=302,
            headers={"location": "https://127.0.0.1/internal"},
            body=None,
        )

    transport = SafeWebhookTransport(endpoint_policy=policy, hop_sender=send_hop)

    with pytest.raises(WebhookRedirectRejected) as caught:
        transport(
            endpoint=initial,
            headers={"Content-Type": "application/json"},
            body=b"{}",
            timeout_seconds=5.0,
        )

    assert caught.value.reason_code == "address_not_global"
    assert calls == [initial]


def test_transport_passes_only_approved_address_to_hop_sender() -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"public.example": ["93.184.216.34"]})
    )
    approved = policy.resolve("https://public.example/hook")
    observed: list[str] = []

    def send_hop(**kwargs) -> WebhookHopResult:
        observed.append(str(kwargs["address"]))
        return WebhookHopResult(status_code=204, headers={}, body="")

    result = SafeWebhookTransport(endpoint_policy=policy, hop_sender=send_hop)(
        endpoint=approved,
        headers={},
        body=b"{}",
        timeout_seconds=5.0,
    )

    assert result.status_code == 204
    assert observed == ["93.184.216.34"]


def test_malformed_redirect_is_terminal_policy_rejection() -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"public.example": ["93.184.216.34"]})
    )
    approved = policy.resolve("https://public.example/hook")

    def send_hop(**kwargs) -> WebhookHopResult:
        del kwargs
        return WebhookHopResult(
            status_code=302,
            headers={"location": "https://[invalid/hook"},
            body=None,
        )

    with pytest.raises(WebhookRedirectRejected) as caught:
        SafeWebhookTransport(endpoint_policy=policy, hop_sender=send_hop)(
            endpoint=approved,
            headers={},
            body=b"{}",
            timeout_seconds=5.0,
        )

    assert caught.value.reason_code == "invalid_redirect"


@pytest.mark.parametrize(
    "location",
    [
        " https://public.example/next",
        "https://public.example/next\t",
        "https://public.example/next\nignored",
        "https:\\public.example\\next",
    ],
)
def test_redirect_rejects_raw_controls_whitespace_and_backslashes(
    location: str,
) -> None:
    policy = WebhookEndpointPolicy(
        resolver=FakeResolver({"public.example": ["93.184.216.34"]})
    )
    approved = policy.resolve("https://public.example/hook")

    def send_hop(**kwargs) -> WebhookHopResult:
        del kwargs
        return WebhookHopResult(
            status_code=302, headers={"location": location}, body=None
        )

    with pytest.raises(WebhookRedirectRejected) as caught:
        SafeWebhookTransport(endpoint_policy=policy, hop_sender=send_hop)(
            endpoint=approved,
            headers={},
            body=b"{}",
            timeout_seconds=5.0,
        )

    assert caught.value.reason_code == "invalid_redirect"


def test_dns_resolver_releases_admission_when_worker_setup_fails(monkeypatch) -> None:
    events: list[str] = []

    class Admission:
        def acquire(self, *, timeout: float) -> bool:
            del timeout
            events.append("acquire")
            return True

        def release(self) -> None:
            events.append("release")

    class Context:
        def Pipe(self, *, duplex: bool):
            del duplex
            raise OSError("pipe unavailable")

    monkeypatch.setattr(webhook_security, "_DNS_ADMISSION", Admission())
    monkeypatch.setattr(
        webhook_security.multiprocessing,
        "get_context",
        lambda method: Context(),
    )

    with pytest.raises(WebhookEndpointResolutionError) as caught:
        SocketWebhookDnsResolver().resolve(
            "public.example", 443, timeout_seconds=0.01
        )

    assert caught.value.reason_code == "dns_resolution_failed"
    assert events == ["acquire", "release"]


def test_dns_resolver_preserves_timeout_reason_and_reaps_worker(monkeypatch) -> None:
    events: list[str] = []

    class Endpoint:
        def close(self) -> None:
            events.append("endpoint_close")

        def poll(self, timeout: float) -> bool:
            del timeout
            return False

    class Process:
        pid = 1

        def start(self) -> None:
            events.append("start")

        def is_alive(self) -> bool:
            return False

        def join(self, *, timeout: float) -> None:
            del timeout
            events.append("join")

        def close(self) -> None:
            events.append("process_close")

    class Context:
        def Pipe(self, *, duplex: bool):
            del duplex
            return Endpoint(), Endpoint()

        def Process(self, **kwargs):
            del kwargs
            return Process()

    monkeypatch.setattr(
        webhook_security.multiprocessing,
        "get_context",
        lambda method: Context(),
    )

    with pytest.raises(WebhookEndpointResolutionError) as caught:
        SocketWebhookDnsResolver().resolve(
            "public.example", 443, timeout_seconds=0.01
        )

    assert caught.value.reason_code == "dns_resolution_timeout"
    assert events == [
        "start",
        "endpoint_close",
        "endpoint_close",
        "endpoint_close",
        "join",
        "process_close",
    ]


def test_pinned_connection_publishes_socket_before_connect_and_handshake(
    monkeypatch,
) -> None:
    events: list[str] = []

    class RawSocket:
        def settimeout(self, timeout: float) -> None:
            del timeout

        def connect(self, destination) -> None:
            assert connection._in_progress_socket is self
            events.append(f"connect:{destination[0]}")

        def close(self) -> None:
            events.append("raw_close")

    class WrappedSocket(RawSocket):
        def do_handshake(self) -> None:
            assert connection.sock is self
            assert connection._in_progress_socket is None
            events.append("handshake")

    raw_socket = RawSocket()
    wrapped_socket = WrappedSocket()
    monkeypatch.setattr(webhook_security.socket, "socket", lambda *args: raw_socket)
    monkeypatch.setattr(
        webhook_security.ssl,
        "create_default_context",
        lambda: object(),
    )
    endpoint = ApprovedWebhookEndpoint(
        canonical_url="https://public.example/hook",
        hostname="public.example",
        port=443,
        request_target="/hook",
        addresses=(ipaddress.ip_address("93.184.216.34"),),
    )
    connection = webhook_security._PinnedHTTPSConnection(
        endpoint=endpoint,
        address="93.184.216.34",
        timeout=1.0,
    )
    connection._context = type(
        "Context",
        (),
        {
            "wrap_socket": lambda self, raw, **kwargs: (
                events.append("wrap") or wrapped_socket
            )
        },
    )()

    connection.connect()

    assert events == ["connect:93.184.216.34", "wrap", "handshake"]
