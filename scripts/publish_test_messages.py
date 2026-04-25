"""
Publishes test summary messages to summary.notifications for local testing.

Usage:
    python scripts/publish_test_messages.py           # default: mixed scenario
    python scripts/publish_test_messages.py monthly   # 4 monthly snapshots
    python scripts/publish_test_messages.py weekly    # 8 weekly snapshots (2 months)
    python scripts/publish_test_messages.py mixed     # 8 weekly (Jan-Feb) + 2 monthly (Mar-Apr)

Requires RabbitMQ running on localhost:5672 and a .env file with credentials.

Delay between messages defaults to 15s to stay within Mailtrap's free rate limit.
Each scenario is designed to exercise a specific chart behaviour:

  monthly  → bar chart: 4 monthly bars, line chart: 4 points
  weekly   → bar chart: 2 monthly bars (collapses 4 weeks per month),
             line chart: 8 weekly points showing intra-month variation
  mixed    → bar chart: 4 monthly bars (weekly Jan/Feb collapsed + monthly Mar/Apr),
             line chart: 10 points with dense Jan/Feb and sparse Mar/Apr
"""

import json
import os
import sys
import time

import pika
from dotenv import load_dotenv

load_dotenv()

QUEUE       = "summary.notifications"
EXCHANGE    = "summary.exchange"
ROUTING_KEY = "summary.send"
DELAY_S     = 15

# ── Scenarios ─────────────────────────────────────────────────────────────────

# 4 monthly snapshots — steady improvement month over month
MONTHLY = [
    {
        "generatedAt": "2026-01-01T09:00:00Z",
        "totalAssetsValue": 110000.00, "monthlyIncome": 7500.00,
        "monthlyExpenses": 5800.00, "monthlySavings": 1700.00, "savingsRate": 0.2267,
    },
    {
        "generatedAt": "2026-02-01T09:00:00Z",
        "totalAssetsValue": 115000.00, "monthlyIncome": 7800.00,
        "monthlyExpenses": 5500.00, "monthlySavings": 2300.00, "savingsRate": 0.2949,
    },
    {
        "generatedAt": "2026-03-01T09:00:00Z",
        "totalAssetsValue": 121000.00, "monthlyIncome": 8000.00,
        "monthlyExpenses": 5200.00, "monthlySavings": 2800.00, "savingsRate": 0.3500,
    },
    {
        "generatedAt": "2026-04-01T09:00:00Z",
        "totalAssetsValue": 125000.00, "monthlyIncome": 8200.00,
        "monthlyExpenses": 5100.00, "monthlySavings": 3100.00, "savingsRate": 0.3780,
    },
]

# 8 weekly snapshots across January and February.
# Values shift slightly each week as the user adds transactions during the month —
# this shows intra-month variation in the savings rate line chart.
# The bar chart will collapse these to 2 monthly bars (Jan + Feb).
WEEKLY = [
    # January — expenses spike mid-month (holiday spending) then recover
    {
        "generatedAt": "2026-01-05T09:00:00Z",
        "totalAssetsValue": 110000.00, "monthlyIncome": 7500.00,
        "monthlyExpenses": 4200.00, "monthlySavings": 3300.00, "savingsRate": 0.4400,
    },
    {
        "generatedAt": "2026-01-12T09:00:00Z",
        "totalAssetsValue": 110500.00, "monthlyIncome": 7500.00,
        "monthlyExpenses": 5100.00, "monthlySavings": 2400.00, "savingsRate": 0.3200,
    },
    {
        "generatedAt": "2026-01-19T09:00:00Z",
        "totalAssetsValue": 111000.00, "monthlyIncome": 7500.00,
        "monthlyExpenses": 5600.00, "monthlySavings": 1900.00, "savingsRate": 0.2533,
    },
    {
        "generatedAt": "2026-01-26T09:00:00Z",  # last Jan snapshot → used in bar chart
        "totalAssetsValue": 111500.00, "monthlyIncome": 7500.00,
        "monthlyExpenses": 5800.00, "monthlySavings": 1700.00, "savingsRate": 0.2267,
    },
    # February — more disciplined spending, savings rate climbs back
    {
        "generatedAt": "2026-02-02T09:00:00Z",
        "totalAssetsValue": 112000.00, "monthlyIncome": 7800.00,
        "monthlyExpenses": 4500.00, "monthlySavings": 3300.00, "savingsRate": 0.4231,
    },
    {
        "generatedAt": "2026-02-09T09:00:00Z",
        "totalAssetsValue": 112800.00, "monthlyIncome": 7800.00,
        "monthlyExpenses": 4900.00, "monthlySavings": 2900.00, "savingsRate": 0.3718,
    },
    {
        "generatedAt": "2026-02-16T09:00:00Z",
        "totalAssetsValue": 113500.00, "monthlyIncome": 7800.00,
        "monthlyExpenses": 5200.00, "monthlySavings": 2600.00, "savingsRate": 0.3333,
    },
    {
        "generatedAt": "2026-02-23T09:00:00Z",  # last Feb snapshot → used in bar chart
        "totalAssetsValue": 114000.00, "monthlyIncome": 7800.00,
        "monthlyExpenses": 5500.00, "monthlySavings": 2300.00, "savingsRate": 0.2949,
    },
]

# Weekly Jan + Feb (8 snapshots) then monthly Mar + Apr (2 snapshots).
# Bar chart → 4 monthly bars. Line chart → 10 points (dense then sparse).
MIXED = WEEKLY + [
    {
        "generatedAt": "2026-03-01T09:00:00Z",
        "totalAssetsValue": 121000.00, "monthlyIncome": 8000.00,
        "monthlyExpenses": 5200.00, "monthlySavings": 2800.00, "savingsRate": 0.3500,
    },
    {
        "generatedAt": "2026-04-01T09:00:00Z",
        "totalAssetsValue": 125000.00, "monthlyIncome": 8200.00,
        "monthlyExpenses": 5100.00, "monthlySavings": 3100.00, "savingsRate": 0.3780,
    },
]

SCENARIOS = {
    "monthly": MONTHLY,
    "weekly":  WEEKLY,
    "mixed":   MIXED,
}

_BASE = {
    "userId":             "123e4567-e89b-12d3-a456-426614174000",
    "userEmail":          "alice@example.com",
    "userName":           "Alice Doe",
    "unpricedAssetsCount": 0,
    "currency":           "AUD",
}


def _build(overrides: dict) -> dict:
    return {**_BASE, **overrides}


def main() -> None:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "mixed"
    if scenario not in SCENARIOS:
        print(f"Unknown scenario '{scenario}'. Choose from: {', '.join(SCENARIOS)}")
        sys.exit(1)

    messages = [_build(m) for m in SCENARIOS[scenario]]

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

    total = len(messages)
    print(f"Scenario: {scenario} — publishing {total} messages ({DELAY_S}s delay each, ~{total * DELAY_S}s total)\n")

    for i, msg in enumerate(messages, 1):
        channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=ROUTING_KEY,
            body=json.dumps(msg).encode(),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="application/json",
            ),
        )
        print(f"[{i}/{total}] Published: {msg['generatedAt']}  savings_rate={msg['savingsRate']:.1%}")
        if i < total:
            time.sleep(DELAY_S)

    connection.close()
    print(f"\nDone. Check Mailtrap for {total} emails.")


if __name__ == "__main__":
    main()
