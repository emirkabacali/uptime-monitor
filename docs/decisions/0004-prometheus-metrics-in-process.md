# ADR 0004: Prometheus metrics from in-process counters, one process per role

- Status: Accepted
- Date: 2026-11-23

## Context

We want request metrics from the API (rate, latency, errors) and check metrics from the
worker (checks, check duration, notifications, active monitors). Prometheus uses a pull
model: it scrapes an HTTP endpoint on each target every 15 seconds.

`prometheus-client` keeps counters in the memory of the process that updates them. When
several processes serve one endpoint (uvicorn `--workers 4`, or Celery's prefork pool),
each scrape reaches one random process and sees only its share of the numbers, unless the
more complex multiprocess mode (shared files on disk) is used.

## Decision

- The API exposes `/metrics` from its single uvicorn process (ADR 0003).
- The Celery worker runs with the **thread pool** in a single process and starts a small
  metrics HTTP server on port 9101 when it boots (`worker_init` signal). All task threads
  update the same counters, so one endpoint shows the complete picture.
- Labels use bounded value sets only: HTTP method, route **template**
  (`/api/v1/monitors/{monitor_id}`), status code, check result (`up`/`down`) and
  notification status. Never raw paths, monitor ids, URLs or user ids.
- `/metrics` and port 9101 are reachable only on the internal Docker network; Caddy returns
  404 for `/metrics`.
- Prometheus and Grafana configuration live in the repository (`monitoring/`), including
  the dashboard JSON and alert rules ("dashboards as code").

## Reasons

- No multiprocess mode: simpler, no shared directory, no stale files after restarts.
- Bounded labels keep the number of time series small. A label with the monitored URL
  would create a new series for every monitor ever added (high cardinality), which slows
  down Prometheus and grows its memory without limit.
- Dashboards in Git are reviewed, versioned and recreated identically on a new server.

## Consequences

- Scaling the worker means more worker containers, each scraped separately; queries
  aggregate with `sum(...)`.
- The API process also imports the worker metric definitions (they share a module), so
  dashboards filter by `job` (`job="worker"`) for worker metrics.
- Counters reset when a process restarts; PromQL `rate()` and `increase()` handle resets.
