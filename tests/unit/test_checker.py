"""HTTP checker tests. respx mocks the network: no real request leaves the machine."""

import ssl

import httpx
import pytest
import respx

from app.services.checker import CheckOutcome, _is_ssl_error, check_url


@respx.mock
def test_successful_check() -> None:
    respx.get("https://example.com/").respond(200)

    outcome = check_url("https://example.com/", timeout=5)

    assert outcome.is_up is True
    assert outcome.status_code == 200
    assert outcome.error is None
    assert outcome.response_time_ms is not None and outcome.response_time_ms >= 0


@respx.mock
def test_non_redirect_3xx_counts_as_up() -> None:
    respx.get("https://example.com/").respond(304)

    assert check_url("https://example.com/", timeout=5).is_up is True


@respx.mock
@pytest.mark.parametrize("status", [400, 404, 500, 503])
def test_error_status_is_down(status: int) -> None:
    respx.get("https://example.com/").respond(status)

    outcome = check_url("https://example.com/", timeout=5)

    assert outcome == CheckOutcome(
        is_up=False,
        status_code=status,
        response_time_ms=outcome.response_time_ms,
        error=f"http_{status}",
    )


@respx.mock
def test_timeout() -> None:
    respx.get("https://example.com/").mock(side_effect=httpx.ReadTimeout("slow"))

    outcome = check_url("https://example.com/", timeout=1)

    assert outcome.is_up is False
    assert outcome.status_code is None
    assert outcome.error == "timeout"


def test_is_ssl_error_follows_exception_chain() -> None:
    try:
        try:
            raise ssl.SSLCertVerificationError("verify failed")
        except ssl.SSLError as exc:
            raise httpx.ConnectError("handshake failed") from exc
    except httpx.ConnectError as wrapped:
        assert _is_ssl_error(wrapped)


def test_is_ssl_error_survives_cyclic_chain() -> None:
    error = httpx.ConnectError("refused")
    error.__context__ = error  # a chain that loops back on itself

    assert _is_ssl_error(error) is False


@respx.mock
def test_connection_error() -> None:
    respx.get("https://example.com/").mock(side_effect=httpx.ConnectError("refused"))

    assert check_url("https://example.com/", timeout=5).error == "connection_error"


@respx.mock
def test_ssl_error() -> None:
    # httpx reports TLS failures as ConnectError with the OpenSSL message.
    error = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    respx.get("https://example.com/").mock(side_effect=error)

    assert check_url("https://example.com/", timeout=5).error == "ssl_error"


def test_dns_error_is_reported_without_a_request() -> None:
    outcome = check_url("https://does-not-exist.invalid/", timeout=5)

    assert outcome.is_up is False
    assert outcome.error == "dns_error"


@respx.mock
def test_follows_redirect_chain() -> None:
    respx.get("http://example.com/").respond(301, headers={"Location": "https://example.com/"})
    respx.get("https://example.com/").respond(302, headers={"Location": "/home"})
    respx.get("https://example.com/home").respond(200)

    outcome = check_url("http://example.com/", timeout=5)

    assert outcome.is_up is True
    assert outcome.status_code == 200


@respx.mock
def test_redirect_to_private_ip_is_blocked() -> None:
    respx.get("https://example.com/").respond(
        302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
    )
    metadata = respx.get("http://169.254.169.254/latest/meta-data/").respond(200)

    outcome = check_url("https://example.com/", timeout=5)

    assert outcome.is_up is False
    assert outcome.error == "ssrf_blocked"
    assert not metadata.called  # the internal address was never contacted


@respx.mock
def test_redirect_to_localhost_name_is_blocked() -> None:
    respx.get("https://example.com/").respond(302, headers={"Location": "http://localhost:6379/"})

    assert check_url("https://example.com/", timeout=5).error == "ssrf_blocked"


@respx.mock
def test_too_many_redirects() -> None:
    respx.get("https://example.com/loop").respond(
        302, headers={"Location": "https://example.com/loop"}
    )

    outcome = check_url("https://example.com/loop", timeout=5)

    assert outcome.is_up is False
    assert outcome.error == "too_many_redirects"


@respx.mock
def test_five_redirects_are_allowed() -> None:
    for i in range(5):
        respx.get(f"https://example.com/{i}").respond(
            302, headers={"Location": f"https://example.com/{i + 1}"}
        )
    respx.get("https://example.com/5").respond(200)

    assert check_url("https://example.com/0", timeout=5).is_up is True


@pytest.mark.parametrize(
    "url",
    ["http://localhost/", "http://127.0.0.1/", "http://user:pass@example.com/", "ftp://x.com/"],
)
def test_blocked_initial_url_is_never_requested(url: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.route().respond(200)
        outcome = check_url(url, timeout=5)

    assert outcome.is_up is False
    assert outcome.error in {"ssrf_blocked", "invalid_url"}
    assert not route.called


@respx.mock
def test_body_is_not_read() -> None:
    def huge_body():
        yield b"x" * 1024
        raise AssertionError("the body must not be consumed")

    respx.get("https://example.com/").respond(200, content=huge_body())

    assert check_url("https://example.com/", timeout=5).is_up is True


@respx.mock
def test_uses_given_client() -> None:
    respx.get("https://example.com/").respond(200)

    with httpx.Client() as client:
        assert check_url("https://example.com/", timeout=5, client=client).is_up is True
