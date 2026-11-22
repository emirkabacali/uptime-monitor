# Uptime Monitor

Uptime monitoring service for websites and APIs: FastAPI, Celery, PostgreSQL, Redis, Docker,
Prometheus.

> Work in progress. The project is being built phase by phase.

## Quick start (Docker)

Requirements: Docker with Docker Compose.

```bash
cp .env.example .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -base64 48)|" .env
docker compose up -d --build
```

This starts PostgreSQL, Redis, a one-off migration job, the API, the check worker and the
scheduler. All application containers use the same image and run as a non-root user.
Only the API port (8000) is published.

- http://localhost:8000/docs — interactive API documentation (Swagger UI)
- http://localhost:8000/health — liveness check
- http://localhost:8000/ready — readiness check (database and Redis)

`docker compose ps` should show every service as `healthy` (and `migrate` as exited 0).

## Development without Docker for the app

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker (for PostgreSQL and Redis).

```bash
uv sync
cp .env.example .env   # and set JWT_SECRET as above

# PostgreSQL (localhost:5433) and Redis (localhost:6379), published on localhost only
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
uv run alembic upgrade head

uv run uvicorn app.main:app --reload
uv run celery -A app.worker.celery_app worker --pool=threads --concurrency=20 --loglevel=INFO
uv run celery -A app.worker.celery_app beat --loglevel=INFO   # run exactly one beat
```

## Using the API

1. `POST /api/v1/auth/register` with `{"email": "...", "password": "..."}` (min. 8 characters).
2. In Swagger, click **Authorize** and log in with your email and password
   (this calls `POST /api/v1/auth/login` and stores the JWT access token).
3. Manage monitors under `/api/v1/monitors`. Each user sees only their own monitors.

## Telegram notifications

The monitor sends a message when a site goes **DOWN** (after `FAILURE_THRESHOLD` failed
checks in a row) and when it **RECOVERS** (with the downtime). Nothing is sent while the
state does not change.

1. In Telegram, open **@BotFather**, send `/newbot` and follow the steps. Copy the token
   into `TELEGRAM_BOT_TOKEN` in `.env` and restart the API and the worker.
2. Open a chat with your new bot and send it any message (bots cannot write first).
3. Find your chat id: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy
   `result[0].message.chat.id`.
4. Save it: `PATCH /api/v1/users/me` with `{"telegram_chat_id": "<your chat id>"}`.
5. Test it: `POST /api/v1/users/me/test-notification`.

Notifications are sent by a separate Celery task with up to 5 retries and exponential
backoff, so a Telegram outage never blocks or breaks the checks.

All errors use the same JSON shape: `{"detail": "...", "code": "..."}`.

## Development

```bash
uv run pytest                 # run tests (needs postgres + redis from the dev compose file)
uv run ruff check . --fix     # lint
uv run ruff format .          # format
uv run pre-commit install     # run ruff automatically before every commit
```

Tests run against a separate PostgreSQL database (`uptime_test`, created automatically).
Each test runs in a transaction that is rolled back afterwards.

## Design decisions

Architecture decision records live in [`docs/decisions/`](docs/decisions/).

## License

MIT
