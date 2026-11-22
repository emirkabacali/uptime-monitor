# ADR 0003: One image, one process per container

- Status: Accepted
- Date: 2026-11-23

## Context

The system has three application roles: the HTTP API (uvicorn), the check worker
(Celery worker) and the scheduler (Celery Beat). Uvicorn can start several worker
processes inside one container (`--workers N`), and the roles could be packed into one
container with a process supervisor.

## Decision

- Build **one Docker image** and run it in **three containers** with different commands
  (`api`, `worker`, `beat`), plus a one-off `migrate` container.
- Each API container runs **exactly one uvicorn process** (no `--workers`). To handle more
  traffic, run more API containers behind the reverse proxy.
- The worker uses one process with a thread pool (see ADR 0002).

## Reasons

- **Same code everywhere:** one build, one tag, one security scan. The worker can never
  run a different version of a model than the API.
- **Docker manages processes:** restart policies, health checks, logs and resource limits
  work per container. With several processes in one container, a crashed child process
  may go unnoticed.
- **Prometheus metrics (Phase 11):** `prometheus-client` keeps counters in process memory.
  With several uvicorn workers in one container, each scrape would hit a random process
  and return its own partial numbers. One process per container keeps metrics correct
  without the multiprocess mode.
- **Scaling by container count** is the model used by Docker Compose, Kubernetes and most
  platforms; it scales each role independently (more workers without more API).
- **Exactly one beat:** a separate container makes it easy to guarantee a single scheduler.

## Consequences

- More containers to run (api, worker, beat, migrate), but they share one image, so the
  extra cost is small.
- One API container uses one CPU core for Python code. On a small VPS this is enough; for
  more throughput, scale the `api` service.
- Migrations run once in their own container before the application starts
  (`depends_on: condition: service_completed_successfully`), instead of every API
  container racing to migrate on startup.
