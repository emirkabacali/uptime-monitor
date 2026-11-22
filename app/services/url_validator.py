"""SSRF protection: decide whether the server may send a request to a URL.

A user gives us a URL and *our server* sends a request to it. Without checks, a
user could make the server call internal services (`http://redis:6379`,
`http://localhost:5432`) or the cloud metadata endpoint
(`http://169.254.169.254/`). This module rejects such targets.

Known limitation (DNS rebinding): the hostname is resolved here and again by the
HTTP client when it connects. A malicious DNS server could return a public IP
for the first lookup and a private IP for the second. Fully preventing this
requires connecting to the already-validated IP address.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import get_settings

ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_PORTS = {"http": 80, "https": 443}

# Indirection so tests can replace DNS resolution without touching the network.
_getaddrinfo = socket.getaddrinfo

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class URLValidationError(ValueError):
    """The URL must not be requested. `code` is a stable machine-readable reason."""

    code = "invalid_url"


class UnsafeURLError(URLValidationError):
    """The URL points to a private, internal or otherwise blocked address."""

    code = "ssrf_blocked"


class DNSResolutionError(URLValidationError):
    """The hostname could not be resolved."""

    code = "dns_error"


def is_blocked_ip(ip: IPAddress) -> bool:
    """True for any address that is not a normal public internet address."""
    # "::ffff:127.0.0.1" is an IPv6 wrapper around an IPv4 address; Python does
    # not report it as loopback, so unwrap it and check the IPv4 address.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        # Catches the remaining special ranges, e.g. 100.64.0.0/10 (carrier NAT).
        or not ip.is_global
    )


def resolve_host(host: str, port: int) -> list[IPAddress]:
    """Return every IP address the hostname resolves to."""
    try:
        infos = _getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise DNSResolutionError(f"Could not resolve hostname: {host}") from exc
    addresses = {ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos}
    if not addresses:
        raise DNSResolutionError(f"Could not resolve hostname: {host}")
    return sorted(addresses, key=str)


def validate_target_url(url: str, *, allow_private: bool | None = None) -> None:
    """Raise URLValidationError if the server must not request this URL.

    Checks: scheme is http/https, no credentials in the URL, and EVERY address the
    hostname resolves to is public. `allow_private` (default: the
    ALLOW_PRIVATE_TARGETS setting) disables only the address check, for tests.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise URLValidationError("Invalid URL") from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise URLValidationError("Only http and https URLs are allowed")
    if parts.username is not None or parts.password is not None:
        raise URLValidationError("URLs with a username or password are not allowed")
    host = parts.hostname
    if not host:
        raise URLValidationError("URL has no hostname")

    if allow_private is None:
        allow_private = get_settings().allow_private_targets
    if allow_private:
        return

    try:
        # An IP literal (e.g. http://127.0.0.1 or http://[::1]) needs no DNS lookup.
        addresses: list[IPAddress] = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = resolve_host(host, port or DEFAULT_PORTS[scheme])

    for address in addresses:
        if is_blocked_ip(address):
            raise UnsafeURLError(f"Target address is not allowed: {address}")
