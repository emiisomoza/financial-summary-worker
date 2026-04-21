"""
RabbitMQ message consumer.

This module orchestrates the full pipeline for each message:
    receive → validate → store → fetch history → chart → render → email → ACK

At-least-once delivery guarantee:
- We only ACK after the email is successfully sent.
- If any step fails, we NACK with requeue=False, sending the message to the
  Dead Letter Queue (DLQ) for manual inspection rather than losing it silently.
- This means in a crash scenario, the message may be processed twice.
  The email would be sent twice — acceptable for a financial summary
  (vs. the alternative: lost message, user never receives their summary).

Why pika (synchronous) instead of async libraries like aio-pika?
- Easier to read and reason about for learning Python.
- The workload is IO-bound (SMTP, SQLite) but low volume (one message per
  user per week/month). Sync is perfectly adequate.
- If throughput becomes a concern later, switching to aio-pika is straightforward.
"""

import json
import os

import pika
import pika.exceptions
import structlog
from pydantic import ValidationError

from worker import mailer, renderer, repository
from worker.models import SummaryMessage

log = structlog.get_logger()

_QUEUE = "summary.notifications"
_SUBJECT = "Your Financial Summary"


def _handle_message(
    channel: pika.channel.Channel,
    method: pika.spec.Basic.Deliver,
    _properties: pika.spec.BasicProperties,
    body: bytes,
    db_path: str,
) -> None:
    """
    Process one message from the queue.

    Steps:
    1. Parse JSON
    2. Validate with Pydantic (security gate — rejects malformed messages)
    3. Store snapshot in SQLite
    4. Fetch history for this user+currency (for charts)
    5. Render HTML email
    6. Send email
    7. ACK the message

    On any failure: NACK → message goes to DLQ.
    """
    try:
        # Step 1 — parse JSON
        data = json.loads(body)

        # Step 2 — validate (Pydantic raises ValidationError on bad input)
        # Note: we log the userId but NOT the email or name (PII)
        msg = SummaryMessage.model_validate(data)
        log.info("message.received", user_id=str(msg.user_id), currency=msg.currency)

        # Step 3 — persist snapshot
        repository.insert(msg, db_path)

        # Step 4 — fetch history (for charts); filtered by user_id + currency
        history = repository.get_history(msg.user_id, msg.currency, db_path)

        # Step 5 — render HTML (charts generated inside renderer if history >= 2)
        html = renderer.render(msg, history)

        # Step 6 — send email (recipient not logged)
        mailer.send(to=str(msg.user_email), subject=_SUBJECT, html_body=html)

        # Step 7 — ACK only after successful send
        channel.basic_ack(delivery_tag=method.delivery_tag)
        log.info("message.processed", user_id=str(msg.user_id))

    except ValidationError as exc:
        log.warning("message.invalid", error=str(exc))
        # NACK, no requeue — malformed messages go straight to DLQ
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    except Exception as exc:
        log.error("message.failed", error=str(exc))
        # NACK, no requeue — failed messages go to DLQ for manual inspection
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start(db_path: str) -> None:
    """
    Connect to RabbitMQ and start consuming messages.
    Blocks indefinitely (runs until the process is killed or connection drops).

    Connection parameters come from environment variables:
        RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USERNAME, RABBITMQ_PASSWORD
    """
    credentials = pika.PlainCredentials(
        username=os.environ.get("RABBITMQ_USERNAME", "guest"),
        password=os.environ["RABBITMQ_PASSWORD"],
    )
    params = pika.ConnectionParameters(
        host=os.environ.get("RABBITMQ_HOST", "localhost"),
        port=int(os.environ.get("RABBITMQ_PORT", "5672")),
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=300,
    )

    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    # Declare the queue and DLQ so the worker can start even if the Java app
    # hasn't declared them yet (idempotent — safe to call multiple times)
    channel.exchange_declare(exchange="summary.dlx", exchange_type="direct", durable=True)
    channel.queue_declare(queue="summary.notifications.dlq", durable=True)
    channel.queue_bind(queue="summary.notifications.dlq", exchange="summary.dlx", routing_key="summary.send")

    channel.queue_declare(
        queue=_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "summary.dlx",
            "x-dead-letter-routing-key": "summary.send",
        },
    )

    # prefetch_count=1: process one message at a time — simpler to reason about
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(
        queue=_QUEUE,
        on_message_callback=lambda ch, method, props, body: _handle_message(
            ch, method, props, body, db_path
        ),
    )

    log.info("consumer.started", queue=_QUEUE)
    channel.start_consuming()
