# Consistência, resiliência e tolerância a falhas

**Observação:** esta parte descreve o que o código faz e o que esperamos observar. Ainda é necessário executar os testes e guardar as respostas HTTP e os logs.

## Como os dados são mantidos

- **Pedidos e estoque:** armazenados em dicionários Python em memória, sem banco transacional. Orders consulta e reserva estoque no Inventory por REST **antes** de registrar o pedido localmente. No fluxo normal, a chamada de reserva precede a criação do registro em Orders, mas não há transação distribuída entre ambos.
- **Notificações:** os eventos são publicados na fila RabbitMQ após o registro do pedido. O consumidor processa a mensagem **assíncronamente**, portanto a notificação pode acontecer depois da resposta do pedido. Nesse fluxo, a notificação pode ser processada em outro momento. É um exemplo de **consistência eventual**, mas não significa que todas as falhas de entrega estejam resolvidas.
- **Limitação importante:** um pedido pode ser criado e seu estoque reservado sem que o evento seja publicado. Nesse caso, `notification_status` permanece `pending` e não existe, no código atual, um mecanismo persistente de reenvio após o fim das 5 tentativas.
- **Sem persistência:** reiniciar o container do Inventory restaura o catálogo inicial, e reiniciar Orders esvazia os pedidos. Por isso, a implementação atual não mantém o estado dos dois serviços após reinicializações.

## Mecanismos presentes no código

1. Timeout HTTP de 10 s nas chamadas Middleware -> Orders e de 5 s nas chamadas Orders -> Inventory.
2. Até cinco tentativas de conexão/publicação RabbitMQ com intervalo fixo de dois segundos; **não** é backoff exponencial.
3. Notifications tenta reconectar a RabbitMQ na **conexão inicial**, em intervalos de cinco segundos.
4. Healthchecks no Compose para Orders, Inventory e RabbitMQ, e política `restart: unless-stopped` nos cinco serviços.
5. Mensagens persistentes e fila durável, além de `ack` para mensagem consumida.

## O que testar quando um serviço cair

| Cenário | Comportamento previsto pelo código | Evidência a coletar |
| --- | --- | --- |
| Inventory indisponível ao criar pedido | Orders tende a retornar `503` por erro de conexão; se houver resposta HTTP 5xx do Inventory, pode responder `502` | HTTP + logs de Orders/Middleware |
| RabbitMQ indisponível depois de criar/reservar pedido | Orders pode retornar `201`, com notificação `pending` depois de até 5 tentativas; espera no endpoint enquanto tenta publicar | resposta + `rabbitmq_publish_retry` + `order_event_publish_failed` |
| Orders indisponível | Middleware responde `503` por erro de conexão ou `504` se ocorrer timeout | HTTP + logs Middleware |
| RabbitMQ retorna | Novas publicações podem voltar a ocorrer; pedidos com publicação falha anterior **não** são reenviados automaticamente | logs e consulta de pedidos |
| Inventory retorna | Novos pedidos podem funcionar; estado do estoque em memória pode reiniciar se container foi reiniciado | health + estoque antes/depois |
| Notifications perde conexão durante consumo | Não há reconexão explícita envolvendo `start_consuming()`; processo pode sair e Docker tentar reiniciá-lo | logs, `docker compose ps`, eventos após reinício |

## Roteiro dos testes de falha

Os resultados podem variar conforme a execução. Para conferir, o grupo deve:

1. Subir os containers (`docker compose up --build`) e registrar `docker compose ps`.
2. Obter token admin e criar pedido com Inventory/RabbitMQ disponíveis. Guardar `X-Correlation-ID` e logs correlacionados.
3. Parar temporariamente Inventory (`docker compose stop inventory`), tentar pedido, registrar status/corpo/logs; reiniciar (`docker compose start inventory`) e repetir.
4. Parar temporariamente RabbitMQ (`docker compose stop rabbitmq`), tentar pedido válido, guardar logs das tentativas; reiniciar e testar novo pedido.
5. Verificar timeout com dependência lenta ou indisponível, anotando se ocorre `503`, `504` ou outro comportamento real.
6. Reiniciar Orders/Inventory e comparar registros para demonstrar a ausência de persistência.
7. Preencher tabela de evidências no relatório: data, cenário, requisição, resposta real, logs, conclusão.

## Possíveis melhorias

- Configuração de timeout/retry por variáveis de ambiente e backoff exponencial.
- Persistência em banco e padrão transactional outbox para garantir reenvio de eventos.
- Dead-letter queue e idempotência no consumidor.
- Tratamento de desconexões do consumidor já em execução.
- Tokens e credenciais fora do código; restrição de acesso direto aos serviços internos.

Para a apresentação, é importante mostrar pelo menos uma falha real, a resposta do sistema e a recuperação após reiniciar o serviço.
