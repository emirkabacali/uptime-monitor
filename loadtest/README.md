# Load test

[k6](https://k6.io/) scenario in `k6-login-list.js`:

- **list_monitors:** ramps to 50 virtual users and keeps them for 60 s; each iteration
  calls `GET /api/v1/monitors?limit=20` for a user with 20 monitors.
- **login:** 8 logins per minute in parallel (login is rate limited to 10/min per IP and
  Argon2 hashing is deliberately slow, so it is measured separately at a realistic rate).

Only run it against your own deployment:

```bash
docker run --rm -i --network uptime-monitor_default -e BASE_URL=http://api:8000 \
  grafana/k6 run - < loadtest/k6-login-list.js
```

## Results (local Docker stack, one API container = one uvicorn process)

| | Requests/s | avg | p95 | p99 | Errors |
|---|---|---|---|---|---|
| Before | 235 | 180 ms | 309 ms | 436 ms | 0% |
| After | 262–266 | 166 ms | 256–258 ms | 344–364 ms | 0% |

Thresholds (`p95 < 500 ms`, `errors < 1%`) pass in both runs.

## How the bottleneck was found

1. `docker stats` during the test: API container ~126% CPU, PostgreSQL ~16%. The database
   was not saturated.
2. Profiling the API under the same load with [py-spy](https://github.com/benfred/py-spy)
   showed most worker-thread time **waiting for database round trips**
   (`psycopg Connection.wait` ≈ 51% of samples). Each list request made four round trips:
   the connection pool's pre-ping (`SELECT 1`), loading the current user, `COUNT(*)` for
   the total, and the page query. Threads also queued for a connection: the pool had the
   default 5 + 10 connections for 40 threads.

## Changes

- The total count and the page now come from **one query** with a window function:
  `SELECT monitors.*, count(*) OVER () AS total ... LIMIT ... OFFSET ...`.
- The connection pool is sized for the thread pool (`DB_POOL_SIZE=20`,
  `DB_MAX_OVERFLOW=10`).

Result: about **+12% throughput** and **−17% p95 latency**. The remaining limit is the
single Python process (one CPU core for Python code); the next step is running more API
containers behind Caddy (ADR 0003), not more tuning inside one process.
