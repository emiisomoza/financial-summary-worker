"""
Publishes 4 monthly summary messages to summary.notifications for local testing.

Usage:
    python scripts/publish_test_messages.py

Requires RabbitMQ running on localhost:5672.
Load .env first (or export variables manually).

The worker processes each message sequentially:
  - January  → 1 snapshot in SQLite → email with no charts
  - February → 2 snapshots          → email with 2-month charts
  - March    → 3 snapshots          → email with 3-month trend
  - April    → 4 snapshots          → email with 4-month trend
"""

import json
import os
import time

import pika
from dotenv import load_dotenv

load_dotenv()

QUEUE    = "summary.notifications"
EXCHANGE = "summary.exchange"
ROUTING_KEY = "summary.send"

MESSAGES = [
    {
        "userId":             "123e4567-e89b-12d3-a456-426614174000",
        "userEmail":          "alice@example.com",
        "userName":           "Alice Doe",
        "totalAssetsValue":   110000.00,
        "monthlyIncome":       7500.00,
        "monthlyExpenses":     5800.00,
        "monthlySavings":      1700.00,
        "savingsRate":         0.2267,
        "unpricedAssetsCount": 0,
        "currency":           "AUD",
        "generatedAt":        "2026-01-01T09:00:00Z",
    },
    {
        "userId":             "123e4567-e89b-12d3-a456-426614174000",
        "userEmail":          "alice@example.com",
        "userName":           "Alice Doe",
        "totalAssetsValue":   115000.00,
        "monthlyIncome":       7800.00,
        "monthlyExpenses":     5500.00,
        "monthlySavings":      2300.00,
        "savingsRate":         0.2949,
        "unpricedAssetsCount": 0,
        "currency":           "AUD",
        "generatedAt":        "2026-02-01T09:00:00Z",
    },
    {
        "userId":             "123e4567-e89b-12d3-a456-426614174000",
        "userEmail":          "alice@example.com",
        "userName":           "Alice Doe",
        "totalAssetsValue":   121000.00,
        "monthlyIncome":       8000.00,
        "monthlyExpenses":     5200.00,
        "monthlySavings":      2800.00,
        "savingsRate":         0.3500,
        "unpricedAssetsCount": 1,
        "currency":           "AUD",
        "generatedAt":        "2026-03-01T09:00:00Z",
    },
    {
        "userId":             "123e4567-e89b-12d3-a456-426614174000",
        "userEmail":          "alice@example.com",
        "userName":           "Alice Doe",
        "totalAssetsValue":   125000.00,
        "monthlyIncome":       8200.00,
        "monthlyExpenses":     5100.00,
        "monthlySavings":      3100.00,
        "savingsRate":         0.3780,
        "unpricedAssetsCount": 0,
        "currency":           "AUD",
        "generatedAt":        "2026-04-01T09:00:00Z",
    },
]


def main() -> None:
    credentials = pika.PlainCredentials(
        username=os.environ.get("RABBITMQ_USERNAME", "guest"),
        password=os.environ.get("RABBITMQ_PASSWORD", "guest"),
    )
    params = pika.ConnectionParameters(
        host=os.environ.get("RABBITMQ_HOST", "localhost"),
        port=int(os.environ.get("RABBITMQ_PORT", "5672")),
        credentials=credentials,
    )

    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)
    channel.queue_declare(
        queue=QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange":    "summary.dlx",
            "x-dead-letter-routing-key": ROUTING_KEY,
        },
    )
    channel.queue_bind(queue=QUEUE, exchange=EXCHANGE, routing_key=ROUTING_KEY)

    for msg in MESSAGES:
        body = json.dumps(msg).encode()
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=ROUTING_KEY,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2,  # persistent
                content_type="application/json",
            ),
        )
        print(f"Published: {msg['generatedAt']}  assets={msg['totalAssetsValue']:,.0f}  savings_rate={msg['savingsRate']:.1%}")
        time.sleep(15)

    connection.close()
    print(f"\n{len(MESSAGES)} messages published to '{QUEUE}'. Check Mailtrap for the emails.")


if __name__ == "__main__":
    main()
