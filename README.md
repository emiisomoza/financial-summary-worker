# financial-summary-worker

A Python worker that consumes financial summary snapshots from RabbitMQ and delivers rich HTML emails with trend charts to users. Part of the [Financial Hub](https://github.com/emiisomoza/finantial-profile-api) platform.

## What it does

The Java API (`finantial-profile-api`) publishes a summary snapshot to `summary.notifications` whenever a user's scheduled summary is due. This worker picks it up and runs the full email pipeline:

```
RabbitMQ message
  → Pydantic validation    (security gate — rejects malformed messages → DLQ)
  → SQLite insert          (persist snapshot for historical charts)
  → fetch history          (last 12 snapshots for same user + currency)
  → matplotlib charts      (savings rate trend + income vs. expenses)
  → Jinja2 HTML render     (auto-escaped, XSS-safe)
  → SMTP send              (STARTTLS enforced)
  → ACK
```

On any failure: NACK with `requeue=False` → message routed to `summary.notifications.dlq`.

---

## Project structure

```
src/worker/
  models.py       # Pydantic SummaryMessage — first security gate
  repository.py   # SQLite persistence (insert + history queries)
  charts.py       # matplotlib chart generation → base64 PNG
  renderer.py     # Jinja2 HTML email rendering
  mailer.py       # smtplib STARTTLS email send
  consumer.py     # RabbitMQ pipeline orchestration
  main.py         # Entry point: env, logging, DB init, consumer start
templates/
  summary_email.html
tests/
scripts/
  publish_test_messages.py  # local end-to-end testing
```

---

## Design decisions

### `models.py` — Pydantic as the security gate

Every message from the queue is validated by Pydantic before any processing happens. Malformed messages never reach the database, charts, or mailer — they fail fast and go to the DLQ.

The Java API publishes camelCase JSON (`userId`, `userEmail`). Python conventionally uses snake_case. Rather than mapping each field manually, `alias_generator=to_camel` translates all fields automatically. `populate_by_name=True` lets tests use snake_case directly without building camelCase payloads.

### `repository.py` — SQLite over a separate database

SQLite was chosen deliberately:
- **Zero infrastructure**: no extra container, no network dependency
- **stdlib**: `sqlite3` is built into Python, no extra package needed
- **Sufficient for the load**: one record per user per week/month

History is always filtered by `(user_id, currency)`. If the user changes their preferred currency, the new currency starts fresh — values in different currencies are never mixed in the same chart. This is intentional and a key design constraint.

`get_history` queries `ORDER BY generated_at DESC LIMIT 12` then reverses the result in Python. The query gets the most recent 12 entries efficiently; the reverse gives the oldest-first order that chart rendering expects (left = older, right = newer).

### `charts.py` — base64 embedding over external hosting

Charts are embedded as base64 PNG strings directly in the email body. The alternative — hosting images at an external URL — was rejected because:
- Many email clients block external images by default
- External URLs can expire or become unavailable
- It would require additional infrastructure

The trade-off is ~60KB of extra email size for two charts, which is acceptable for a financial summary.

**`savings_rate_chart`** plots raw history points. Weekly granularity is valuable here — you can see how the savings rate evolves as the user records transactions throughout the month.

**`income_expense_chart`** collapses history to one point per calendar month (`_last_per_month`) before plotting. The reason: income and expenses are always monthly aggregates regardless of subscription frequency. Plotting 4 nearly identical weekly bars for January adds noise, not insight. The last snapshot of each month is the most complete picture of that month's figures.

The `Agg` matplotlib backend is required in a headless environment (Docker, CI). Without it, matplotlib tries to connect to a display and crashes.

### `renderer.py` — Jinja2 with autoescape

`autoescape=True` means every `{{ variable }}` in the template is HTML-escaped automatically. If `user_name` contained `<script>alert(1)</script>`, it would render as plain text — no XSS possible in the email body. This is non-negotiable: user-controlled data in an HTML document is a classic injection vector.

The templates directory is resolved with `Path(__file__).parent.parent.parent`, navigating from `src/worker/` to the project root. This makes the renderer work regardless of the working directory the process was started from.

### `mailer.py` — stdlib smtplib

`smtplib` was chosen over third-party libraries because it works with any SMTP provider (Mailtrap, Gmail, Resend, Sendgrid) by changing only environment variables. No library lock-in, no extra dependency.

`starttls()` is always called — there is no plaintext fallback. If the server doesn't support TLS the connection fails, which is preferable to sending credentials in the clear.

The recipient address and email body are never logged. Only the subject and outcome (success/error) appear in logs.

### `consumer.py` — ACK discipline

The message is ACKed **only after** the email is successfully sent. This guarantees at-least-once delivery: if the worker crashes between receiving and sending, RabbitMQ redelivers the message. The trade-off is that a crash between a successful send and the ACK would cause the email to be sent twice — acceptable for a financial summary versus silent message loss.

Any failure NACKs with `requeue=False`. A message that fails once will likely fail again (corrupt data, invalid email address), so infinite requeue loops are avoided. The DLQ allows manual inspection and replay.

`prefetch_count=1` processes one message at a time — simpler to reason about and sufficient for the expected volume.

### `main.py` — separated from consumer.py for testability

Tests import `consumer` and `repository` directly without triggering RabbitMQ connections or `.env` loading. If setup logic lived in `consumer.py`, any import would attempt a broker connection. The separation keeps the dependency graph clean.

The structlog PII processor redacts `user_email`, `user_name`, `to`, and `from` from every log entry. Only `user_id` (a UUID) is logged. Log field names (`level`, `timestamp`, `event`) match the Java project's structured log format for consistent log aggregation across services.

### `templates/summary_email.html` — CSS in `<head>` over inline styles

Inline CSS is the traditional approach for maximum email client compatibility (notably Outlook desktop). CSS in `<head>` was chosen here because:
- The target clients are modern (Gmail web/mobile, Apple Mail)
- `<style>` in the head is far more maintainable for a template of this complexity
- Media queries (used for mobile layout) cannot be inlined

The KPI grid uses CSS Grid collapsing from 2 columns to 1 column on mobile via `@media (max-width: 600px)`. The wrapper uses `width: 100%; max-width: 600px` to center correctly across email clients.

### Testing strategy — isolated unit tests, no integration tests

Each module has its own test file, mocking external dependencies:

| File | Approach |
|------|----------|
| `test_models.py` | No mocks — pure Pydantic validation |
| `test_repository.py` | In-memory SQLite (`:memory:`) — no files, no teardown |
| `test_charts.py` | Verifies PNG magic bytes (`\x89PNG`) — real matplotlib output |
| `test_renderer.py` | Real Jinja2 render — checks HTML output and XSS escaping |
| `test_consumer.py` | Mocks repository, renderer, mailer, and pika channel — tests ACK/NACK logic only |
| `test_mailer.py` | Mocks `smtplib.SMTP` — verifies STARTTLS, credentials, and missing env vars |

No end-to-end integration tests by design: they would require a live RabbitMQ and SMTP server, slowing CI and introducing flakiness. The unit tests cover all failure modes and the pipeline logic completely.

---

## Running locally

```bash
# 1. Create virtualenv (requires Python 3.12)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your RabbitMQ and SMTP credentials

# 3. Start RabbitMQ
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management

# 4. Run the worker
PYTHONPATH=src python -m worker.main
```

## Running tests

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

No external services needed — tests use in-memory SQLite and mock all I/O.

## Publishing test messages

```bash
# Publishes a mix of weekly and monthly snapshots (default)
python scripts/publish_test_messages.py

# Specific scenarios
python scripts/publish_test_messages.py monthly   # 4 monthly snapshots
python scripts/publish_test_messages.py weekly    # 8 weekly snapshots (2 months)
python scripts/publish_test_messages.py mixed     # 8 weekly + 2 monthly
```

## Running via Docker Compose

The worker is part of the `finantial-profile-api` Docker Compose stack:

```bash
# From finantial-profile-api/
docker compose up
```

A named volume (`summary_data`) persists the SQLite database across container restarts.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBITMQ_HOST` | `localhost` | RabbitMQ hostname |
| `RABBITMQ_PORT` | `5672` | RabbitMQ AMQP port |
| `RABBITMQ_USERNAME` | `guest` | RabbitMQ username |
| `RABBITMQ_PASSWORD` | — | RabbitMQ password (required) |
| `SMTP_HOST` | — | SMTP server hostname (required) |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username (required) |
| `SMTP_PASSWORD` | — | SMTP password (required) |
| `EMAIL_FROM` | — | Sender address (required) |
| `DB_PATH` | `./data/summaries.db` | SQLite database file path |
| `LOG_LEVEL` | `INFO` | Logging level |

---

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

---

## Security

| Concern | Mitigation |
|---------|-----------|
| Malformed queue messages | Pydantic rejects before any processing → DLQ |
| HTML injection in email | Jinja2 `autoescape=True` |
| PII in logs | structlog redacts `user_email`, `user_name` |
| SMTP credentials | Environment variables only, never hardcoded |
| Plaintext email transport | STARTTLS enforced, no fallback |
| Container privilege | Non-root user (UID 1000) in Dockerfile |
