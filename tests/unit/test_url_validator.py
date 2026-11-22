import ipaddress

import pytest

from app.services.url_validator import (
    DNSResolutionError,
    UnsafeURLError,
    URLValidationError,
    is_blocked_ip,
    validate_target_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com:8080/path?q=1",
        "https://ipv6.example.com/",
        "http://93.184.215.14/",
        "HTTPS://EXAMPLE.COM/",
    ],
)
def test_public_urls_are_allowed(url: str) -> None:
    validate_target_url(url)  # does not raise


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://localhost:5432/",
        "http://127.0.0.1/",
        "http://127.1.2.3/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fc00::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://100.64.0.1/",
        "http://internal.example.com/",
        "http://metadata.example.com/",
        "http://mixed.example.com/",
    ],
)
def test_internal_targets_are_blocked(url: str) -> None:
    with pytest.raises(UnsafeURLError) as exc_info:
        validate_target_url(url)
    assert exc_info.value.code == "ssrf_blocked"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "javascript:alert(1)",
        "http://user:pass@example.com/",
        "http://user@example.com/",
        "http:///no-host",
        "http://example.com:99999/",
        "not a url",
    ],
)
def test_invalid_urls_are_rejected(url: str) -> None:
    with pytest.raises(URLValidationError) as exc_info:
        validate_target_url(url)
    assert exc_info.value.code == "invalid_url"


def test_unresolvable_host_raises_dns_error() -> None:
    with pytest.raises(DNSResolutionError) as exc_info:
        validate_target_url("https://does-not-exist.invalid/")
    assert exc_info.value.code == "dns_error"


def test_allow_private_skips_only_the_address_check() -> None:
    validate_target_url("http://127.0.0.1:8000/", allow_private=True)  # allowed

    with pytest.raises(URLValidationError):
        validate_target_url("ftp://127.0.0.1/", allow_private=True)
    with pytest.raises(URLValidationError):
        validate_target_url("http://u:p@127.0.0.1/", allow_private=True)


@pytest.mark.parametrize(
    ("address", "blocked"),
    [
        ("8.8.8.8", False),
        ("2001:4860:4860::8888", False),
        ("127.0.0.1", True),
        ("::ffff:10.0.0.1", True),
        ("::ffff:8.8.8.8", False),
        ("255.255.255.255", True),
    ],
)
def test_is_blocked_ip(address: str, blocked: bool) -> None:
    assert is_blocked_ip(ipaddress.ip_address(address)) is blocked
