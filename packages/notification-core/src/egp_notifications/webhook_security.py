"""Fail-closed URL, address, redirect, and transport policy for tenant webhooks."""

from __future__ import annotations

import http.client
import ipaddress
import multiprocessing
import re
import socket
import ssl
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024
_DNS_ADMISSION = threading.BoundedSemaphore(4)


def _resolve_in_child(hostname: str, port: int, sender) -> None:
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
        )
        sender.send((True, [str(record[4][0]) for record in records]))
    except OSError:
        sender.send((False, []))
    finally:
        sender.close()


class WebhookEndpointError(RuntimeError):
    """Base class with a stable code and no destination details."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__("webhook endpoint is not allowed")


class WebhookEndpointRejected(WebhookEndpointError):
    """Terminal URL or address-policy rejection."""


class WebhookEndpointResolutionError(WebhookEndpointError):
    """Retryable DNS resolution failure."""


class WebhookRedirectRejected(WebhookEndpointRejected):
    """Terminal redirect-policy rejection."""


class WebhookDnsResolver(Protocol):
    def resolve(
        self, hostname: str, port: int, *, timeout_seconds: float
    ) -> Sequence[str]: ...


def _release_dns_process(process: multiprocessing.Process) -> None:
    """Reap a resolver child before returning its concurrency permit."""
    try:
        if process.is_alive():
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.join()
    finally:
        try:
            process.close()
        finally:
            _DNS_ADMISSION.release()


class SocketWebhookDnsResolver:
    """Resolve A/AAAA records through the platform resolver."""

    def resolve(
        self, hostname: str, port: int, *, timeout_seconds: float
    ) -> Sequence[str]:
        budget = float(timeout_seconds)
        if budget <= 0:
            raise WebhookEndpointResolutionError("dns_resolution_timeout")
        deadline = time.monotonic() + budget
        if not _DNS_ADMISSION.acquire(timeout=budget):
            raise WebhookEndpointResolutionError("dns_resolution_timeout")
        receiver = None
        sender = None
        process = None
        started = False
        permit_transferred = False
        try:
            context = multiprocessing.get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_resolve_in_child,
                args=(hostname, port, sender),
                daemon=True,
            )
            process.start()
            started = True
            sender.close()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not receiver.poll(remaining):
                raise WebhookEndpointResolutionError("dns_resolution_timeout")
            succeeded, raw_addresses = receiver.recv()
            if not succeeded:
                raise WebhookEndpointResolutionError("dns_resolution_failed")
            addresses = list(dict.fromkeys(raw_addresses))
            if not addresses:
                raise WebhookEndpointResolutionError("dns_resolution_failed")
            return addresses
        except WebhookEndpointError:
            raise
        except (EOFError, OSError, RuntimeError) as exc:
            raise WebhookEndpointResolutionError("dns_resolution_failed") from exc
        finally:
            if receiver is not None:
                receiver.close()
            if sender is not None:
                sender.close()
            if process is not None and not started:
                started = process.pid is not None
            if started and process is not None:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=0)
                if process.is_alive():
                    permit_transferred = True
                    reaper = threading.Thread(
                        target=_release_dns_process,
                        args=(process,),
                        daemon=True,
                    )
                    try:
                        reaper.start()
                    except RuntimeError:
                        _release_dns_process(process)
                else:
                    process.close()
            elif process is not None:
                process.close()
            if not permit_transferred:
                _DNS_ADMISSION.release()


@dataclass(frozen=True, slots=True)
class ApprovedWebhookEndpoint:
    canonical_url: str
    hostname: str
    port: int
    request_target: str
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]


def _reject(reason_code: str) -> WebhookEndpointRejected:
    return WebhookEndpointRejected(reason_code)


def _is_allowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return bool(
        address.is_global
        and not address.is_multicast
        and not (isinstance(address, ipaddress.IPv6Address) and address.is_site_local)
    )


def _has_forbidden_url_characters(value: str) -> bool:
    return (
        value != value.strip()
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _canonicalize_url_component(value: str, *, safe: str) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise _reject("invalid_url")
    try:
        return quote(value, safe=safe, encoding="utf-8", errors="strict")
    except UnicodeError as exc:
        raise _reject("invalid_url") from exc


class WebhookEndpointPolicy:
    def __init__(
        self,
        *,
        resolver: WebhookDnsResolver | None = None,
        dns_timeout_seconds: float = 2.0,
    ) -> None:
        self._resolver = resolver or SocketWebhookDnsResolver()
        self._dns_timeout_seconds = max(0.05, float(dns_timeout_seconds))

    def resolve(
        self, url: str, *, timeout_seconds: float | None = None
    ) -> ApprovedWebhookEndpoint:
        original_url = str(url)
        if _has_forbidden_url_characters(original_url):
            raise _reject("invalid_url")
        raw_url = original_url
        try:
            parsed = urlsplit(raw_url)
            port = parsed.port
        except ValueError as exc:
            raise _reject("invalid_url") from exc
        if parsed.scheme.casefold() != "https":
            raise _reject("https_required")
        if parsed.username is not None or parsed.password is not None:
            raise _reject("userinfo_not_allowed")
        if "#" in raw_url:
            raise _reject("fragment_not_allowed")
        if not parsed.hostname:
            raise _reject("invalid_hostname")
        if "%" in parsed.hostname:
            raise _reject("invalid_hostname")
        try:
            hostname = (
                parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
            )
        except UnicodeError as exc:
            raise _reject("invalid_hostname") from exc
        if not hostname or hostname == "localhost" or hostname.endswith(".localhost"):
            raise _reject("hostname_not_allowed")
        resolved_port = 443 if port is None else int(port)
        if not 1 <= resolved_port <= 65535:
            raise _reject("invalid_url")

        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            requested_budget = (
                self._dns_timeout_seconds
                if timeout_seconds is None
                else float(timeout_seconds)
            )
            budget = min(self._dns_timeout_seconds, requested_budget)
            if budget <= 0:
                raise WebhookEndpointResolutionError("dns_resolution_timeout")
            try:
                raw_addresses = self._resolver.resolve(
                    hostname, resolved_port, timeout_seconds=budget
                )
            except WebhookEndpointError:
                raise
            except (OSError, TimeoutError) as exc:
                raise WebhookEndpointResolutionError("dns_resolution_failed") from exc
            if not raw_addresses:
                raise WebhookEndpointResolutionError("dns_resolution_failed")
            try:
                addresses = tuple(
                    ipaddress.ip_address(value) for value in raw_addresses
                )
            except ValueError as exc:
                raise WebhookEndpointResolutionError("dns_resolution_failed") from exc
        else:
            addresses = (literal,)
        if any(not _is_allowed_address(address) for address in addresses):
            raise _reject("address_not_global")

        host_display = f"[{hostname}]" if ":" in hostname else hostname
        netloc = (
            host_display if resolved_port == 443 else f"{host_display}:{resolved_port}"
        )
        path = _canonicalize_url_component(
            parsed.path or "/",
            safe="/%:@-._~!$&'()*+,;=",
        )
        query = _canonicalize_url_component(
            parsed.query,
            safe="/%?:@-._~!$&'()*+,;=",
        )
        canonical_url = urlunsplit(("https", netloc, path, query, ""))
        request_target = path + (f"?{query}" if query else "")
        return ApprovedWebhookEndpoint(
            canonical_url=canonical_url,
            hostname=hostname,
            port=resolved_port,
            request_target=request_target,
            addresses=addresses,
        )


@dataclass(frozen=True, slots=True)
class WebhookHopResult:
    status_code: int
    headers: dict[str, str]
    body: str | None


class WebhookHopSender(Protocol):
    def __call__(
        self,
        *,
        endpoint: ApprovedWebhookEndpoint,
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> WebhookHopResult: ...


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self, *, endpoint: ApprovedWebhookEndpoint, address: str, timeout: float
    ):
        super().__init__(
            endpoint.hostname,
            endpoint.port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._approved_address = address
        self._socket_lock = threading.Lock()
        self._in_progress_socket: socket.socket | None = None
        self._aborted = False

    def _publish_socket(self, candidate: socket.socket, *, wrapped: bool) -> None:
        with self._socket_lock:
            if self._aborted:
                candidate.close()
                raise TimeoutError("webhook delivery timed out")
            if wrapped:
                self.sock = candidate
                self._in_progress_socket = None
            else:
                self._in_progress_socket = candidate

    def connect(self) -> None:
        approved_ip = ipaddress.ip_address(self._approved_address)
        family = socket.AF_INET6 if approved_ip.version == 6 else socket.AF_INET
        raw_socket = socket.socket(family, socket.SOCK_STREAM)
        self._publish_socket(raw_socket, wrapped=False)
        try:
            raw_socket.settimeout(self.timeout)
            destination: tuple[str, int] | tuple[str, int, int, int]
            if approved_ip.version == 6:
                destination = (self._approved_address, self.port, 0, 0)
            else:
                destination = (self._approved_address, self.port)
            raw_socket.connect(destination)
            wrapped_socket = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
                do_handshake_on_connect=False,
            )
        except Exception:
            with self._socket_lock:
                self._in_progress_socket = None
            raw_socket.close()
            raise
        self._publish_socket(wrapped_socket, wrapped=True)
        wrapped_socket.settimeout(self.timeout)
        wrapped_socket.do_handshake()

    def abort(self) -> None:
        with self._socket_lock:
            self._aborted = True
            active_socket = self.sock or self._in_progress_socket
        if active_socket is None:
            return
        try:
            active_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            active_socket.close()
        except OSError:
            pass


def send_pinned_https_hop(
    *,
    endpoint: ApprovedWebhookEndpoint,
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: float,
    max_response_bytes: int,
) -> WebhookHopResult:
    deadline = time.monotonic() + float(timeout_seconds)

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("webhook delivery timed out")
        return value

    connection = _PinnedHTTPSConnection(
        endpoint=endpoint,
        address=str(address),
        timeout=remaining(),
    )
    timed_out = threading.Event()

    def close_at_deadline() -> None:
        timed_out.set()
        connection.abort()

    watchdog = threading.Timer(remaining(), close_at_deadline)
    watchdog.daemon = True
    watchdog.start()
    try:
        connection.timeout = remaining()
        connection.request("POST", endpoint.request_target, body=body, headers=headers)
        if connection.sock is not None:
            connection.sock.settimeout(remaining())
        response = connection.getresponse()
        retained = bytearray()
        while len(retained) <= max_response_bytes:
            if connection.sock is not None:
                connection.sock.settimeout(remaining())
            chunk = response.read1(min(8192, max_response_bytes + 1 - len(retained)))
            if not chunk:
                break
            retained.extend(chunk)
        raw_body = bytes(retained)
        truncated = len(raw_body) > max_response_bytes
        text = raw_body[:max_response_bytes].decode("utf-8", errors="replace")
        if truncated:
            marker = " [truncated]"
            text = (text[: max(0, max_response_bytes - len(marker))] + marker)[
                :max_response_bytes
            ]
        if timed_out.is_set():
            raise TimeoutError("webhook delivery timed out")
        return WebhookHopResult(
            status_code=response.status,
            headers={key.casefold(): value for key, value in response.getheaders()},
            body=text,
        )
    finally:
        watchdog.cancel()
        connection.close()


class SafeWebhookTransport:
    def __init__(
        self,
        *,
        endpoint_policy: WebhookEndpointPolicy,
        hop_sender: WebhookHopSender = send_pinned_https_hop,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._endpoint_policy = endpoint_policy
        self._hop_sender = hop_sender
        self._max_redirects = max(0, int(max_redirects))
        self._max_response_bytes = max(1, int(max_response_bytes))
        self._monotonic = monotonic

    def __call__(
        self,
        *,
        endpoint: ApprovedWebhookEndpoint,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> WebhookHopResult:
        deadline = self._monotonic() + float(timeout_seconds)
        current = endpoint
        visited = {current.canonical_url}
        for hop in range(self._max_redirects + 1):
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise TimeoutError("webhook delivery timed out")
            last_error: OSError | None = None
            result: WebhookHopResult | None = None
            for address in current.addresses:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise TimeoutError("webhook delivery timed out")
                try:
                    result = self._hop_sender(
                        endpoint=current,
                        address=address,
                        headers=headers,
                        body=body,
                        timeout_seconds=remaining,
                        max_response_bytes=self._max_response_bytes,
                    )
                    break
                except OSError as exc:
                    last_error = exc
            if result is None:
                raise last_error or OSError("webhook connection failed")
            if result.status_code not in {301, 302, 307, 308}:
                if result.status_code == 303:
                    raise WebhookRedirectRejected("invalid_redirect")
                return result
            location = result.headers.get("location")
            if not location:
                raise WebhookRedirectRejected("invalid_redirect")
            if hop >= self._max_redirects:
                raise WebhookRedirectRejected("redirect_limit_exceeded")
            if _has_forbidden_url_characters(location):
                raise WebhookRedirectRejected("invalid_redirect")
            try:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise TimeoutError("webhook delivery timed out")
                redirect_url = urljoin(current.canonical_url, location)
                next_endpoint = self._endpoint_policy.resolve(
                    redirect_url,
                    timeout_seconds=remaining,
                )
            except WebhookEndpointRejected as exc:
                raise WebhookRedirectRejected(exc.reason_code) from exc
            except (TypeError, ValueError) as exc:
                raise WebhookRedirectRejected("invalid_redirect") from exc
            if next_endpoint.canonical_url in visited:
                raise WebhookRedirectRejected("redirect_loop")
            visited.add(next_endpoint.canonical_url)
            current = next_endpoint
        raise WebhookRedirectRejected("redirect_limit_exceeded")
