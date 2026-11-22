# Uptime Monitor

Uptime monitoring service for websites and APIs: FastAPI, Celery, PostgreSQL, Redis, Docker,
Prometheus.

> Work in progress. The project is being built phase by phase.

## Running locally

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker.

```bash
# Install dependencies (creates .venv from uv.lock)
uv sync

# Create your local configuration and set a random JWT secret
cp .env.example .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -base64 48)|" .env

# Start PostgreSQL and create the schema
docker compose up -d postgres redis
uv run alembic upgrade head

# Start the API with auto-reload
uv run uvicorn app.main:app --reload
```

In two more terminals, start the background worker and the scheduler:

```bash
docker compose up -d redis
uv run celery -A app.worker.celery_app worker --pool=threads --concurrency=20 --loglevel=INFO
uv run celery -A app.worker.celery_app beat --loglevel=INFO   # run exactly one beat
```

Then open:

- http://localhost:8000/health — liveness check
- http://localhost:8000/ready — readiness check (database and Redis)
- http://localhost:8000/docs — interactive API documentation (Swagger UI)

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
uv run pytest                 # run tests (needs the postgres container)
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
