# Uptime Monitor

Uptime monitoring service for websites and APIs: FastAPI, Celery, PostgreSQL, Redis, Docker,
Prometheus.

> Work in progress. The project is being built phase by phase.

## Running locally

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/).

```bash
# Install dependencies (creates .venv from uv.lock)
uv sync

# Create your local configuration
cp .env.example .env

# Start the API with auto-reload
uv run uvicorn app.main:app --reload
```

Then open:

- http://localhost:8000/health — liveness check
- http://localhost:8000/docs — interactive API documentation (Swagger UI)

## Development

```bash
uv run pytest                 # run tests
uv run ruff check . --fix     # lint
uv run ruff format .          # format
uv run pre-commit install     # run ruff automatically before every commit
```

## License

MIT
