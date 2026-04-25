# financial-summary-worker — Agent Documentation

> **Maintenance note:** This file and [README.md](README.md) must be kept up to date as the project evolves. When adding a new module, changing a design decision, or modifying the pipeline, update both documents to reflect the current state.

## Role in the system

`financial-summary-worker` is the **email notification agent** of the Financial Hub platform. It runs as a standalone Python service alongside the Java `finantial-profile-api` and is responsible for the entire email delivery pipeline: consuming summary snapshots from RabbitMQ, building historical trend charts, rendering an HTML email, and sending it to the user.

It has no REST API and no direct contact with the PostgreSQL database. Its only inputs are RabbitMQ messages; its only output is an SMTP email.

---

## System context

```
finantial-profile-api (Java)
  SummaryScheduler ──triggers──► SummaryService + UserService
                                        │
                                  SummaryPublisher
                                        │
                              RabbitMQ: summary.notifications
                                        │
                          ┌─────────────▼──────────────┐
                          │  financial-summary-worker   │
                          │  (this service)             │
                          │                             │
                          │  validate → store → chart   │
                          │  → render → send → ACK      │
                          └─────────────────────────────┘
                                        │
                                   SMTP email
                                   to the user

  On failure: NACK → summary.notifications.dlq
```

---

## Modules

### `worker/consumer.py`

Owns the RabbitMQ connection and the per-message pipeline. Entry point is `start(db_path)`, which blocks indefinitely consuming from `summary.notifications`.

**Pipeline per message:**
1. Parse JSON body
2. Validate with Pydantic (`SummaryMessage`) — rejects malformed messages to DLQ
3. Persist snapshot in SQLite via `repository.insert()`
4. Fetch historical snapshots for same `(user_id, currency)` via `repository.get_history()`
5. Render HTML email via `renderer.render()`
6. Send email via `mailer.send()`
7. ACK on success — NACK with `requeue=False` on any failure

**At-least-once delivery:** message is ACKed only after the email is sent. A crash may result in the email being sent twice — acceptable vs. silent loss.

---

### `worker/models.py`

Pydantic v2 model `SummaryMessage`. First and most critical security gate: every message from the queue is validated here before any processing. Malformed messages never reach the DB, charts, or mailer.

Maps camelCase JSON fields (published by Java) to snake_case Python attributes via `alias_generator=to_camel`.

**Key validations:**
- `user_email` — valid email format (Pydantic `EmailStr`)
- `user_id` — valid UUID
- `currency` — exactly 3 characters
- `total_assets_value`, `monthly_income`, `monthly_expenses` — non-negative
- `savings_rate` — bounded (-10 to 10) as a sanity check

---

### `worker/repository.py`

SQLite persistence layer. Uses the Python stdlib `sqlite3` — no extra dependency.

**Table:** `summary_history` — one row per received message, indexed on `(user_id, currency, generated_at)`.

**Key methods:**
- `init_db(db_path)` — creates table and index if not present; called once at startup
- `insert(msg, db_path)` — persists a snapshot before email generation
- `get_history(user_id, currency, db_path, limit=12)` — returns up to 12 snapshots for the same user + currency, oldest first (for chart rendering)

**Currency grouping:** history is always filtered by `(user_id, currency)`. If the user changes their preferred currency, the new currency starts fresh — incomparable values are never mixed in the same chart.

---

### `worker/charts.py`

Generates two matplotlib charts embedded as base64-encoded PNG strings in the email body. No external image hosting needed.

- `savings_rate_chart(history)` — line chart of savings rate (%) over time
- `income_expense_chart(history, currency)` — grouped bar chart of monthly income vs. expenses

Both return `None` if `len(history) < 2`. The renderer shows a placeholder message in that case.

Uses the `Agg` (non-interactive) matplotlib backend — no display required.

---

### `worker/renderer.py`

Jinja2 HTML renderer. Loads `templates/summary_email.html` with `autoescape=True` — all user-controlled values are HTML-escaped automatically (no XSS possible in the email body).

`render(msg, history)` returns a fully rendered HTML string ready to pass to `mailer.send()`.

---

### `worker/mailer.py`

smtplib SMTP sender. Always uses STARTTLS (port 587) — no plaintext fallback.

All credentials (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`) come exclusively from environment variables. The recipient address and email body are never written to logs.

---

### `worker/main.py`

Entry point. Loads `.env` (local development only — no-op in Docker), configures structlog with a PII redaction processor, initialises the SQLite database, then calls `consumer.start()`.

**PII in logs:** `user_email` and `user_name` are always redacted. Only `user_id` (a UUID) is logged.

---

## Dead-letter queue

Failed messages go to `summary.notifications.dlq` via the `summary.dlx` exchange (declared by both this worker and the Java `RabbitMQConfig`). Check the DLQ in the RabbitMQ management UI (`localhost:15672`) to inspect and replay failed messages.

---

## Security summary

| Concern | Mitigation |
|---------|-----------|
| Malformed queue messages | Pydantic rejects before any processing → DLQ |
| HTML injection in email | Jinja2 `autoescape=True` |
| PII in logs | structlog processor redacts `user_email`, `user_name` |
| SMTP credentials | Environment variables only, never hardcoded |
| Plaintext email transport | STARTTLS enforced, no fallback |
| Container privilege | Non-root user (UID 1000) in Dockerfile |

---

## Related services

| Service | Repo | Role |
|---------|------|------|
| `finantial-profile-api` | [emiisomoza/finantial-profile-api](https://github.com/emiisomoza/finantial-profile-api) | Publishes to `summary.notifications`; declares DLQ topology |
