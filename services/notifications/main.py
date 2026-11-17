
import json
import os
import time

import pika

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = "orders_queue"


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

            print("Conectado ao RabbitMQ.", flush=True)
            return connection

        except pika.exceptions.AMQPConnectionError:
            print(
                "RabbitMQ indisponível. Tentando novamente em 5 segundos...",
                flush=True
            )
            time.sleep(5)


def main():
    connection = connect_to_rabbitmq()
    channel = connection.channel()

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True
    )

    print(
        f"Aguardando mensagens na fila '{QUEUE_NAME}'...",
        flush=True
    )

    def process_message(ch, method, properties, body):
        try:
            event = json.loads(body.decode("utf-8"))

            print("\nNova notificação recebida!", flush=True)
            print(f"Evento: {event}", flush=True)

            print(
                f"Pedido #{event['order_id']} confirmado: "
                f"{event['quantity']} unidade(s) de "
                f"{event['product']}.",
                flush=True
            )

            ch.basic_ack(delivery_tag=method.delivery_tag)

        except (json.JSONDecodeError, KeyError, TypeError) as error:
            print(
                f"Erro ao processar mensagem: {error}",
                flush=True
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