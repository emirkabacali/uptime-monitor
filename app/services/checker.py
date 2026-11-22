"""Perform one HTTP check against a URL, safely.

- Redirects are followed manually (max 5) and every hop is validated against
  the SSRF rules, because a public site could redirect to an internal address.
- The response body is never read: only the status line and headers matter.
"""

import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.services.url_validator import URLValidationError, validate_target_url

MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
USER_AGENT = "UptimeMonitor/0.1 (+https://github.com/emirkabacali/uptime-monitor)"


@dataclass(frozen=True)
class CheckOutcome:
    is_up: bool
    status_code: int | None
    response_time_ms: int | None
    error: str | None


def _is_ssl_error(exc: BaseException) -> bool:
    # Walk the exception chain. Track visited exceptions: a chain can loop back
    # on itself, which would otherwise be an infinite loop.
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    text = str(exc).upper()
    return "SSL" in text or "CERTIFICATE" in text


def _failure(error: str, started: float | None = None) -> CheckOutcome:
    elapsed = None if started is None else int((time.perf_counter() - started) * 1000)
    return CheckOutcome(is_up=False, status_code=None, response_time_ms=elapsed, error=error)


def check_url(url: str, timeout: float, *, client: httpx.Client | None = None) -> CheckOutcome:
    """Request `url` and classify the result. Never raises for network errors.

    Success means a response arrived within the timeout with status 200-399.
    Error codes: timeout, dns_error, connection_error, ssl_error,
    too_many_redirects, ssrf_blocked, invalid_url, http_<status>.
    """
    own_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )
    started = time.perf_counter()
    current = url
    try:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                validate_target_url(current)
            except URLValidationError as exc:
                return _failure(exc.code)

            try:
                request = client.build_request("GET", current, timeout=timeout)
                response = client.send(request, stream=True, follow_redirects=False)
                response.close()  # do not download the body
            except httpx.TimeoutException:
                return _failure("timeout", started)
            except httpx.HTTPError as exc:
                return _failure("ssl_error" if _is_ssl_error(exc) else "connection_error", started)

            location = response.headers.get("location")
            if response.status_code in REDIRECT_STATUSES and location:
                current = urljoin(current, location)
                continue

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            code = response.status_code
            is_up = 200 <= code < 400
            return CheckOutcome(
                is_up=is_up,
                status_code=code,
                response_time_ms=elapsed_ms,
                error=None if is_up else f"http_{code}",
            )
        return _failure("too_many_redirects", started)
    finally:
        if own_client:
            client.close()
