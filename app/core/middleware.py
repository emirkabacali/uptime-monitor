"""Request middleware: request id, one structured log line and metrics per request."""

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_var
from app.core.metrics import HTTP_REQUEST_DURATION, HTTP_REQUESTS

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
# Accept an incoming id only if it is short and harmless (it ends up in logs).
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _route_template(request: Request) -> str:
    """The matched route pattern, e.g. "/api/v1/monitors/{monitor_id}".

    Recent FastAPI versions keep an included router's prefix outside the
    route's own path ("/monitors/{monitor_id}"). The prefix is static text, so
    it is rebuilt from the leading segments of the real request path.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return "unmatched"
    # "/api/v1/monitors/5" -> ["api", "v1", "monitors", "5"]; template "/monitors/{id}" has 2.
    real_segments = [s for s in request.url.path.split("/") if s]
    template_segments = [s for s in template.split("/") if s]
    prefix_segments = real_segments[: max(len(real_segments) - len(template_segments), 0)]
    prefix = "/" + "/".join(prefix_segments) if prefix_segments else ""
    return prefix + template


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            route = _route_template(request)
            HTTP_REQUESTS.labels(request.method, route, str(status)).inc()
            HTTP_REQUEST_DURATION.labels(request.method, route).observe(duration)
            # Path only, never the query string or headers (they may hold secrets).
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "route": route,
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                    "client_ip": request.client.host if request.client else None,
                },
            )
            request_id_var.reset(token)
