
import json
import logging
import os
import time
import uuid
from itertools import count

import httpx
import pika
from fastapi import FastAPI, HTTPException, Request
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
RABBITMQ_MAX_ATTEMPTS = int(os.getenv("RABBITMQ_MAX_ATTEMPTS", "5"))
RABBITMQ_BACKOFF_SECONDS = float(os.getenv("RABBITMQ_BACKOFF_SECONDS", "0.5"))

orders = {}
order_counter = count(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orders")


def log_event(event, **details):
    logger.info(json.dumps({
        "event": event,
        **details
    }, ensure_ascii=False))


class OrderRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    correlation_id = (
        request.headers.get("X-Correlation-ID")
        or str(uuid.uuid4())
    )

    request.state.correlation_id = correlation_id
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        log_event(
            "request_error",
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path
        )
        raise

    latency_ms = (time.perf_counter() - start_time) * 1000

    log_event(
        "http_request",
        correlation_id=correlation_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        latency_ms=round(latency_ms, 2)
    )

    response.headers["X-Correlation-ID"] = correlation_id
    return response


def publish_order_event(order, correlation_id):
    event = {
        "event": "order_created",
        "order_id": order["id"],
        "product": order["product"],
        "quantity": order["quantity"],
        "total": order["total"],
        "correlation_id": correlation_id
    }

    for attempt in range(RABBITMQ_MAX_ATTEMPTS):
        connection = None

        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=RABBITMQ_HOST,
                    heartbeat=60,
                    socket_timeout=3,
                    stack_timeout=5,
                    blocked_connection_timeout=5,
                    connection_attempts=1
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

            log_event(
                "order_event_published",
                order_id=order["id"],
                correlation_id=correlation_id
            )

            return True

        except (
            pika.exceptions.AMQPConnectionError,
            OSError
        ) as error:
            log_event(
                "rabbitmq_publish_retry",
                attempt=attempt + 1,
                correlation_id=correlation_id,
                error=str(error)
            )

            if attempt < RABBITMQ_MAX_ATTEMPTS - 1:
                wait_seconds = RABBITMQ_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(wait_seconds)

        finally:
            if connection is not None and connection.is_open:
                connection.close()

    log_event(
        "order_event_publish_failed",
        order_id=order["id"],
        correlation_id=correlation_id
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
def create_order(request: OrderRequest, http_request: Request):
    correlation_id = http_request.state.correlation_id

    inventory_headers = {
        "X-Correlation-ID": correlation_id
    }

    # Consulta o produto no Inventory
    try:
        product_response = httpx.get(
            f"{INVENTORY_URL}/products/{request.product_id}",
            headers=inventory_headers,
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
            headers=inventory_headers,
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
        "notification_status": "pending",
        "correlation_id": correlation_id
    }

    orders[order_id] = order

    log_event(
        "order_created",
        order_id=order_id,
        product=product["name"],
        quantity=request.quantity,
        correlation_id=correlation_id
    )

    # Publica o evento no RabbitMQ
    event_sent = publish_order_event(order, correlation_id)

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