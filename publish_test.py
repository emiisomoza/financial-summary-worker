import pika
import json
from datetime import datetime, timezone

RABBITMQ_HOST = "localhost"
RABBITMQ_PORT = 5672
RABBITMQ_USER = "guest"
RABBITMQ_PASS = "guest"

message = {
    "userId": "00000000-0000-0000-0000-000000000001",
    "userEmail": "cincoknet@gmail.com",
    "userName": "Emiliano",
    "totalAssetsValue": 125000.00,
    "monthlyIncome": 8000.00,
    "monthlyExpenses": 5500.00,
    "monthlySavings": 2500.00,
    "savingsRate": 0.3125,
    "unpricedAssetsCount": 0,
    "currency": "AUD",
    "generatedAt": datetime.now(timezone.utc).isoformat(),
}

credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
connection = pika.BlockingConnection(
    pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials)
)
channel = connection.channel()
channel.queue_declare(
    queue="summary.notifications",
    durable=True,
    arguments={
        "x-dead-letter-exchange": "summary.dlx",
        "x-dead-letter-routing-key": "summary.send",
    },
)
channel.basic_publish(
    exchange="",
    routing_key="summary.notifications",
    body=json.dumps(message),
    properties=pika.BasicProperties(delivery_mode=2),
)
connection.close()
print("Message published to summary.notifications")
