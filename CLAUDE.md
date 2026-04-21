# financial-summary-worker

Python worker that consumes financial summary snapshots from RabbitMQ and sends rich HTML emails with trend charts to users.

## What it does

1. Consumes messages from `summary.notifications` (published by the Java `finantial-profile-api`)
2. Validates and persists each snapshot in SQLite (historical data for charts)
3. Generates two matplotlib charts: savings rate trend + monthly income vs. expenses
4. Renders an HTML email via Jinja2 (auto-escaped, XSS-safe)
5. Sends the email over STARTTLS SMTP
6. ACKs the message — or NACKs to `summary.notifications.dlq` on any failure

## Project structure

```
src/worker/
  main.py         # Entry point: loads env, inits DB, starts consumer
  consumer.py     # RabbitMQ message loop and pipeline orchestration
  models.py       # Pydantic SummaryMessage (camelCase JSON → snake_case, full validation)
  repository.py   # SQLite: insert snapshot + get_history(user_id, currency)
  charts.py       # matplotlib: savings rate line chart + income/expense bar chart → base64 PNG
  renderer.py     # Jinja2 HTML render with embedded charts
  mailer.py       # smtplib STARTTLS send, credentials from env only
templates/
  summary_email.html   # Jinja2 email template
tests/
  test_models.py       # Pydantic validation (security gate)
  test_repository.py   # SQLite insert + history queries (in-memory DB)
  test_charts.py       # Chart generation (PNG output, None when < 2 data points)
  test_renderer.py     # HTML rendering, XSS escaping, chart/placeholder logic
  test_consumer.py     # ACK/NACK behaviour with mocked I/O
  test_mailer.py       # SMTP calls, TLS enforcement, missing env vars
```

## Environment variables

Copy `.env.example` to `.env` for local development:

```
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USERNAME=guest
RABBITMQ_PASSWORD=

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
EMAIL_FROM=

DB_PATH=./data/summaries.db
LOG_LEVEL=INFO
```

In Docker, variables are injected by the container runtime (`.env` is not used).

## Running locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Requires a running RabbitMQ and valid SMTP credentials in .env
PYTHONPATH=src python -m worker.main
```

## Running tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
```

No external services needed — tests use an in-memory SQLite DB and mock all I/O.

## Docker

Built and run as part of the `finantial-profile-api` Docker Compose stack:

```bash
# From finantial-profile-api/
docker compose up
```

The worker depends on the `rabbitmq` service and mounts a named volume (`summary_data`) for SQLite persistence across restarts.

## Message schema

JSON published to `summary.notifications` by the Java API:

```json
{
  "userId": "uuid",
  "userEmail": "user@example.com",
  "userName": "Alice Doe",
  "totalAssetsValue": 125000.00,
  "monthlyIncome": 8000.00,
  "monthlyExpenses": 5500.00,
  "monthlySavings": 2500.00,
  "savingsRate": 0.3125,
  "unpricedAssetsCount": 0,
  "currency": "AUD",
  "generatedAt": "2026-04-01T09:00:00Z"
}
```

## At-least-once delivery

- Message is ACKed **only after** the email is successfully sent
- Any failure (validation, DB, render, SMTP) → NACK with `requeue=False` → DLQ
- In a crash scenario the message may be processed twice (email sent twice) — acceptable vs. silent message loss

## Security

- PII (`user_email`, `user_name`) is never written to logs — only `user_id`
- Jinja2 `autoescape=True` prevents HTML injection in the email body
- SMTP always uses STARTTLS — no plaintext fallback
- SMTP credentials and RabbitMQ password come exclusively from environment variables
- Docker container runs as non-root user (UID 1000)
- Pydantic validates every incoming message before any processing
