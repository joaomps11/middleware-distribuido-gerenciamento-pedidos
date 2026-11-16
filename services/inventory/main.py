
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="Inventory Service",
    description="Serviço responsável pelo gerenciamento de estoque.",
    version="1.0.0"
)

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


class StockRequest(BaseModel):
    quantity: int = Field(gt=0, description="Quantidade que será reservada")


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
def reserve_stock(product_id: int, request: StockRequest):
    product = products.get(product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado."
        )

    if product["stock"] < request.quantity:
        raise HTTPException(
            status_code=400,
            detail="Estoque insuficiente."
        )

    product["stock"] -= request.quantity

    return {
        "message": "Estoque reservado com sucesso.",
        "product": product["name"],
        "quantity_reserved": request.quantity,
        "remaining_stock": product["stock"]
    }