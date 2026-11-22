# ADR 0002: Run checks with Celery (thread pool) and Redis, dispatched from the database

- Status: Accepted
- Date: 2026-11-22

## Context

Every active monitor must be checked every `interval_seconds` (30–3600 s). A check is an
HTTP request that can take up to 30 seconds (timeout) and up to six hops (redirects).
Checks must run in the background, independent of API requests, and keep working when
the number of monitors grows.

## Decision

- **Celery** workers with **Redis** as the message broker run the checks.
- **Celery Beat** (one single instance) runs `dispatch_due_checks` every 10 seconds.
- The schedule lives in **PostgreSQL** (`monitors.next_check_at`), not in Beat: the
  dispatcher claims due monitors with `SELECT ... FOR UPDATE SKIP LOCKED`, moves
  `next_check_at` forward by the interval, commits, and enqueues one `check_monitor`
  task per monitor.
- Workers run with `--pool=threads --concurrency=20`.
- `task_acks_late=True`: a message is acknowledged after the task finishes.

## Reasons

- **Why a queue at all:** checks must not run inside API requests, and a queue lets us
  add workers (horizontal scaling) without changing code.
- **Why Celery:** the most common Python task queue, with periodic tasks (Beat), retries
  (used for notifications in Phase 6) and acks-late built in. Alternatives: RQ (simpler,
  no built-in scheduler), Dramatiq, or APScheduler inside the API (no separation, harder
  to scale).
- **Why Redis as broker:** small, fast, one container; also used for rate limiting.
  RabbitMQ is more robust for complex routing but is an extra service we do not need.
- **Why the schedule is in the database:** one Beat entry for all monitors instead of one
  per monitor; users can add or pause monitors without touching Beat; `SKIP LOCKED`
  guarantees that two dispatchers never enqueue the same monitor.
- **Why threads:** checks are I/O-bound (they wait for the network). Threads waiting on
  I/O release the GIL, so 20 threads in one process handle 20 checks at once with far
  less memory than 20 processes. One process also keeps Prometheus metrics consistent
  (Phase 11).

## Consequences

- At-least-once delivery means `check_monitor` can run twice for the same dispatch.
  It is made idempotent: a check is skipped if the monitor was checked in the first half
  of the current interval, the monitor row is locked (`FOR UPDATE`) while the state
  machine runs, and the partial unique index prevents a second open incident.
- The HTTP request is done **outside** the row lock and transaction, so slow sites do not
  hold database locks.
- Exactly one Beat instance must run; two would only cause extra (harmless) dispatches,
  because `SKIP LOCKED` and `next_check_at` still prevent double checks.
- Check timing has a resolution of about 10 seconds (the dispatch period).
