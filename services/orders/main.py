
import json
import os
import time
from itertools import count

import httpx
import pika
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="Orders Service",
    description="Serviço responsável pelo gerenciamento de pedidos.",
    version="1.0.0"
)

INVENTORY_URL = os.getenv(
    "INVENTORY_URL",
    "http://127.0.0.1:8002"
)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
QUEUE_NAME = "orders_queue"

orders = {}
order_counter = count(1)


class OrderRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


def publish_order_event(order):
    event = {
        "event": "order_created",
        "order_id": order["id"],
        "product": order["product"],
        "quantity": order["quantity"],
        "total": order["total"]
    }

    for attempt in range(5):
        connection = None

        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    heartbeat=60,
                    socket_timeout=5
                )
            )

            channel = connection.channel()

            channel.queue_declare(
                queue=QUEUE_NAME,
                durable=True
            )

            channel.basic_publish(
                exchange="",
                routing_key=QUEUE_NAME,
                body=json.dumps(event),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json"
                )
            )

            print(
                f"Evento do pedido {order['id']} enviado ao RabbitMQ.",
                flush=True
            )

            return True

        except (pika.exceptions.AMQPConnectionError, OSError) as error:
            print(
                f"Tentativa {attempt + 1}/5: RabbitMQ indisponível: {error}",
                flush=True
            )

            time.sleep(2)

        finally:
            if connection is not None and connection.is_open:
                connection.close()

    print(
        f"Não foi possível publicar o evento do pedido {order['id']}.",
        flush=True
    )

    return False


@app.get("/")
def home():
    return {
        "service": "Orders Service",
        "status": "online",
        "message": "Serviço de pedidos funcionando."
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "orders"
    }


@app.post("/orders", status_code=201)
def create_order(request: OrderRequest):

    # Consulta o produto no Inventory
    try:
        product_response = httpx.get(
            f"{INVENTORY_URL}/products/{request.product_id}",
            timeout=5.0
        )

        if product_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="Produto não encontrado."
            )

        product_response.raise_for_status()
        product = product_response.json()

    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Serviço de estoque indisponível."
        )
    except httpx.HTTPStatusError:
        raise HTTPException(
            status_code=502,
            detail="Erro ao consultar o serviço de estoque."
        )

    # Reserva o estoque
    try:
        stock_response = httpx.post(
            f"{INVENTORY_URL}/products/{request.product_id}/reserve",
            json={"quantity": request.quantity},
            timeout=5.0
        )

        if stock_response.status_code == 400:
            raise HTTPException(
                status_code=400,
                detail="Estoque insuficiente."
            )

        if stock_response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail="Produto não encontrado no estoque."
            )

        stock_response.raise_for_status()

    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível reservar o estoque."
        )
    except httpx.HTTPStatusError:
        raise HTTPException(
            status_code=502,
            detail="Erro ao reservar o estoque."
        )

    # Registra o pedido
    order_id = next(order_counter)

    order = {
        "id": order_id,
        "product_id": product["id"],
        "product": product["name"],
        "quantity": request.quantity,
        "unit_price": product["price"],
        "total": product["price"] * request.quantity,
        "status": "confirmed",
        "notification_status": "pending"
    }

    orders[order_id] = order

    # Publica o evento no RabbitMQ
    event_sent = publish_order_event(order)

    if event_sent:
        order["notification_status"] = "sent"

    return {
        "message": "Pedido criado com sucesso.",
        "order": order
    }


@app.get("/orders")
def list_orders():
    return {
        "orders": list(orders.values())
    }


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    order = orders.get(order_id)

    if order is None:
        raise HTTPException(
            status_code=404,
            detail="Pedido não encontrado."
        )

    return order