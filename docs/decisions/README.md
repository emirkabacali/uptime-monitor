# Architecture decision records

Short documents that explain an important technical decision: the context, the decision,
the reasons and the consequences.

| ADR | Decision |
|---|---|
| [0001](0001-monitor-limit-response.md) | Respond with 409 Conflict when the monitor limit is reached |
| [0002](0002-celery-with-redis-for-checks.md) | Run checks with Celery (thread pool) and Redis, dispatched from the database |
| [0003](0003-one-process-per-container.md) | One image, one process per container |
| [0004](0004-prometheus-metrics-in-process.md) | Prometheus metrics from in-process counters, one process per role |
