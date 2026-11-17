
import json
import logging
import os
import time
import uuid

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from jose import JWTError, jwt
from pydantic import BaseModel


app = FastAPI(
    title="Middleware Distribuído",
    description="Componente central de comunicação e segurança do sistema.",
    version="1.0.0"
)

# Configurações
ORDERS_URL = os.getenv("ORDERS_URL", "http://127.0.0.1:8001")
SECRET_KEY = os.getenv("SECRET_KEY", "chave-de-desenvolvimento-alterar")
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60

# Usuários simulados para demonstração
USERS = {
    "admin": {
        "password": "admin123",
        "role": "admin"
    },
    "cliente": {
        "password": "cliente123",
        "role": "customer"
    }
}

# Métricas em memória
metrics = {
    "total_requests": 0,
    "successful_requests": 0,
    "error_requests": 0,
    "total_latency_ms": 0.0
}

# Configuração de logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("middleware")


class LoginRequest(BaseModel):
    username: str
    password: str


def create_access_token(username: str, role: str):
    expiration = time.time() + TOKEN_EXPIRE_MINUTES * 60

    payload = {
        "sub": username,
        "role": role,
        "exp": int(expiration)
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request):
    authorization = request.headers.get("Authorization")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Token de autenticação não informado."
        )

    token = authorization.split(" ", 1)[1]

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        username = payload.get("sub")
        role = payload.get("role")

        if not username or not role:
            raise HTTPException(
                status_code=401,
                detail="Token inválido."
            )

        return {
            "username": username,
            "role": role
        }

    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Token inválido ou expirado."
        )


def require_roles(*allowed_roles):
    def role_checker(user=Depends(get_current_user)):
        if user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail="Você não tem permissão para acessar este recurso."
            )

        return user

    return role_checker


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    correlation_id = request.headers.get(
        "X-Correlation-ID"
    ) or str(uuid.uuid4())

    request.state.correlation_id = correlation_id

    start_time = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code

    except Exception:
        logger.exception(
            json.dumps({
                "event": "request_error",
                "correlation_id": correlation_id,
                "path": request.url.path
            })
        )

        response = JSONResponse(
            status_code=500,
            content={"detail": "Erro interno no middleware."}
        )

    latency_ms = (time.perf_counter() - start_time) * 1000

    metrics["total_requests"] += 1
    metrics["total_latency_ms"] += latency_ms

    if status_code < 400:
        metrics["successful_requests"] += 1
    else:
        metrics["error_requests"] += 1

    logger.info(
        json.dumps({
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "latency_ms": round(latency_ms, 2),
            "correlation_id": correlation_id
        })
    )

    response.headers["X-Correlation-ID"] = correlation_id

    return response


async def forward_to_orders(request: Request, path: str):
    correlation_id = request.state.correlation_id

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {
            "host",
            "content-length",
            "connection"
        }
    }

    headers["X-Correlation-ID"] = correlation_id

    url = f"{ORDERS_URL}{path}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            service_response = await client.request(
                method=request.method,
                url=url,
                content=await request.body(),
                headers=headers
            )

        response_headers = {}

        if "content-type" in service_response.headers:
            response_headers["Content-Type"] = (
                service_response.headers["content-type"]
            )

        return Response(
            content=service_response.content,
            status_code=service_response.status_code,
            headers=response_headers
        )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Tempo limite excedido ao acessar o Orders Service."
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Orders Service indisponível."
        )


@app.get("/")
def home():
    return {
        "service": "Middleware Distribuído",
        "status": "online",
        "message": "Middleware funcionando."
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "middleware"
    }


@app.post("/auth/token")
def login(request: LoginRequest):
    user = USERS.get(request.username)

    if user is None or user["password"] != request.password:
        raise HTTPException(
            status_code=401,
            detail="Usuário ou senha incorretos."
        )

    token = create_access_token(
        username=request.username,
        role=user["role"]
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_EXPIRE_MINUTES * 60,
        "role": user["role"]
    }


@app.post("/orders", status_code=201)
async def create_order(
    request: Request,
    user=Depends(require_roles("admin", "customer"))
):
    return await forward_to_orders(request, "/orders")


@app.get("/orders")
async def list_orders(
    request: Request,
    user=Depends(require_roles("admin"))
):
    return await forward_to_orders(request, "/orders")


@app.get("/orders/{order_id}")
async def get_order(
    order_id: int,
    request: Request,
    user=Depends(require_roles("admin"))
):
    return await forward_to_orders(
        request,
        f"/orders/{order_id}"
    )


@app.get("/metrics")
def get_metrics(user=Depends(require_roles("admin"))):
    total = metrics["total_requests"]

    average_latency = (
        metrics["total_latency_ms"] / total
        if total > 0
        else 0
    )

    return {
        "total_requests": total,
        "successful_requests": metrics["successful_requests"],
        "error_requests": metrics["error_requests"],
        "average_latency_ms": round(average_latency, 2)
    }