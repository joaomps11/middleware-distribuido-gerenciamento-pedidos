
import json
import os
import time
import logging

import pika

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = "orders_queue"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notifications")


def log_event(event, **details):
    logger.info(json.dumps({
        "event": event,
        **details
    }, ensure_ascii=False))


def connect_to_rabbitmq():
    while True:
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    heartbeat=60,
                    blocked_connection_timeout=30
                )
            )

            log_event("rabbitmq_connected")
            return connection

        except pika.exceptions.AMQPConnectionError as error:
            log_event(
                "rabbitmq_unavailable",
                error=str(error),
                retry_in_seconds=5
            )

            time.sleep(5)


def main():
    connection = connect_to_rabbitmq()
    channel = connection.channel()

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True
    )

    log_event(
        "waiting_for_messages",
        queue=QUEUE_NAME
    )

    def process_message(ch, method, properties, body):
        try:
            event = json.loads(body.decode("utf-8"))

            correlation_id = event.get("correlation_id")

            log_event(
                "notification_received",
                order_id=event["order_id"],
                product=event["product"],
                quantity=event["quantity"],
                total=event["total"],
                correlation_id=correlation_id
            )

            log_event(
                "notification_processed",
                order_id=event["order_id"],
                message=(
                    f"Pedido #{event['order_id']} confirmado: "
                    f"{event['quantity']} unidade(s) de "
                    f"{event['product']}."
                ),
                correlation_id=correlation_id
            )

            ch.basic_ack(
                delivery_tag=method.delivery_tag
            )

        except (json.JSONDecodeError, KeyError, TypeError) as error:
            log_event(
                "notification_processing_error",
                error=str(error)
            )

            ch.basic_nack(
                delivery_tag=method.delivery_tag,
                requeue=False
            )

    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=process_message
    )

    channel.start_consuming()


if __name__ == "__main__":
    main()