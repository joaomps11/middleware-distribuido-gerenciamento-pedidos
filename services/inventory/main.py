
import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(
    title="Inventory Service",
    description="Serviço responsável pelo gerenciamento de estoque.",
    version="1.0.0"
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inventory")

# Estoque inicial simulado em memória
products = {
    1: {
        "id": 1,
        "name": "Notebook",
        "price": 3500.00,
        "stock": 10
    },
    2: {
        "id": 2,
        "name": "Mouse",
        "price": 80.00,
        "stock": 25
    },
    3: {
        "id": 3,
        "name": "Teclado",
        "price": 150.00,
        "stock": 15
    }
}


def log_event(event, **details):
    logger.info(json.dumps({
        "event": event,
        **details
    }, ensure_ascii=False))


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    correlation_id = (
        request.headers.get("X-Correlation-ID")
        or str(uuid.uuid4())
    )

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


class StockRequest(BaseModel):
    quantity: int = Field(
        gt=0,
        description="Quantidade que será reservada"
    )


@app.get("/")
def home():
    return {
        "service": "Inventory Service",
        "status": "online",
        "message": "Serviço de estoque funcionando."
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "inventory"
    }


@app.get("/products")
def list_products():
    return {
        "products": list(products.values())
    }


@app.get("/products/{product_id}")
def get_product(product_id: int):
    product = products.get(product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado."
        )

    return product


@app.post("/products/{product_id}/reserve")
def reserve_stock(
    product_id: int,
    request: StockRequest,
    http_request: Request
):
    correlation_id = http_request.headers.get(
        "X-Correlation-ID"
    )

    product = products.get(product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado."
        )

    if product["stock"] < request.quantity:
        log_event(
            "stock_reservation_failed",
            product_id=product_id,
            requested_quantity=request.quantity,
            correlation_id=correlation_id
        )

        raise HTTPException(
            status_code=400,
            detail="Estoque insuficiente."
        )

    product["stock"] -= request.quantity

    log_event(
        "stock_reserved",
        product_id=product_id,
        product=product["name"],
        quantity=request.quantity,
        remaining_stock=product["stock"],
        correlation_id=correlation_id
    )

    return {
        "message": "Estoque reservado com sucesso.",
        "product": product["name"],
        "quantity_reserved": request.quantity,
        "remaining_stock": product["stock"]
    }