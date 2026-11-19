# Contratos de API

Os serviços Middleware, Orders e Inventory usam FastAPI. As tabelas apresentam as rotas e os principais códigos de resposta. O FastAPI também pode retornar `422` quando os dados enviados não são válidos.

## 1. Middleware — http://localhost:8000

| Método | Rota | Acesso | Corpo | Resposta esperada / erros |
| --- | --- | --- | --- | --- |
| GET | `/` | Público | — | `200` com identificação/status |
| GET | `/health` | Público | — | `200` com `status: healthy` |
| POST | `/auth/token` | Público | `{"username":"admin","password":"admin123"}` | `200` com `access_token`, `token_type`, `expires_in`, `role`; `401` se credenciais inválidas |
| POST | `/orders` | `admin`, `customer` | `{"product_id":2,"quantity":1}` | `201` com pedido; outros erros propagados do Orders (`400`, `404`, `502`, `503`) |
| GET | `/orders` | `admin` | — | `200` com `orders` |
| GET | `/orders/{order_id}` | `admin` | — | `200` com pedido ou `404` |
| GET | `/metrics` | `admin` | — | `200` com métricas agregadas em memória |

Para rotas protegidas, o header é `Authorization: Bearer <token JWT>`. Sem token ou com token inválido: `401`. Sem permissão: `403`.

Exemplo de pedido de token:

```json
{"username": "admin", "password": "admin123"}
```

Formato da resposta, omitindo o token real:

```json
{"access_token": "<JWT>", "token_type": "bearer", "expires_in": 3600, "role": "admin"}
```

Exemplo de pedido (`POST /orders`):

```json
{"product_id": 2, "quantity": 1}
```

Pedido registrado inclui `id`, `product_id`, `product`, `quantity`, `unit_price`, `total`, `status`, `notification_status` e `correlation_id`, dentro do campo `order`. A mensagem do retorno é `Pedido criado com sucesso.`.

## 2. Orders — http://localhost:8001 (API interna)

| Método | Rota | Corpo | Resposta / erros |
| --- | --- | --- | --- |
| GET | `/` | — | `200` status |
| GET | `/health` | — | `200` health |
| POST | `/orders` | `{"product_id":2,"quantity":1}` | `201` pedido; `400` estoque insuficiente; `404` produto inexistente; `502` erro HTTP no estoque; `503` indisponibilidade do estoque |
| GET | `/orders` | — | `200` lista de pedidos |
| GET | `/orders/{order_id}` | — | `200` pedido ou `404` |

**Atenção:** na porta `8001`, o Orders não verifica o JWT. As permissões são aplicadas quando o pedido passa pelo Middleware, na porta `8000`.

Se RabbitMQ estiver indisponível, o código realiza até **5 tentativas** de publicação, com pausas fixas de **2 segundos** entre as tentativas falhas. Mesmo que a publicação falhe, o endpoint pode retornar `201` com `notification_status: pending`.

## 3. Inventory — http://localhost:8002 (API interna)

| Método | Rota | Corpo | Resposta / erros |
| --- | --- | --- | --- |
| GET | `/` | — | `200` status |
| GET | `/health` | — | `200` health |
| GET | `/products` | — | `200` lista de produtos |
| GET | `/products/{product_id}` | — | `200` produto; `404` inexistente |
| POST | `/products/{product_id}/reserve` | `{"quantity":1}` | `200` reserva; `400` insuficiente; `404` inexistente |

Catálogo inicial simulado: Notebook (`id=1`, preço 3500, estoque 10); Mouse (`id=2`, preço 80, estoque 25); Teclado (`id=3`, preço 150, estoque 15). Preços e quantidades são apenas dados de demonstração.

## 4. Notifications e RabbitMQ (sem API REST)

`notifications` é um trabalhador Pika, não uma API HTTP. Ele consome mensagens JSON da fila `orders_queue` e registra os eventos `notification_received` e `notification_processed` em logs.

Exemplo estrutural de mensagem gerada pelo Orders:

```json
{
  "event": "order_created",
  "order_id": 1,
  "product": "Mouse",
  "quantity": 1,
  "total": 80.0,
  "correlation_id": "<uuid-gerado-ou-propagado>"
}
```

O header `X-Correlation-ID` atravessa o fluxo HTTP; seu valor também segue no corpo do evento enviado ao RabbitMQ. Valores de ID, status e métricas devem ser conferidos na execução real.

## 5. Swagger automático

- http://localhost:8000/docs (Middleware)
- http://localhost:8001/docs (Orders)
- http://localhost:8002/docs (Inventory)

O Swagger mostra os campos das requisições. Esta documentação acrescenta o fluxo entre os serviços e as regras de acesso.
