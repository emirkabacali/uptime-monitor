"""Prometheus metrics.

Labels are kept to small, fixed sets of values. The route TEMPLATE
("/api/v1/monitors/{monitor_id}") is used, never the real path or a URL:
every distinct label value creates a new time series, so user-controlled
values (ids, URLs) would make the number of series grow without limit.
"""

from prometheus_client import Counter, Gauge, Histogram

# ---- API (exposed at /metrics by the API process)
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled.", ["method", "route", "status"]
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# ---- Worker (exposed on WORKER_METRICS_PORT by the worker process)
CHECKS = Counter("uptime_checks_total", "Checks performed.", ["result"])  # result: up | down
CHECK_DURATION = Histogram(
    "uptime_check_duration_seconds",
    "Time to perform one check, including redirects.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
NOTIFICATIONS = Counter(
    "uptime_notifications_total", "Notification attempts.", ["status"]
)  # status: sent | failed | skipped
MONITORS_ACTIVE = Gauge("uptime_monitors_active", "Active (not paused) monitors.")
