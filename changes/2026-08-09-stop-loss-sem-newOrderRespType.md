# Change Proposal — 2026-08-09 — Resposta da Binance ao stop-loss vinha sem status/price (newOrderRespType)

**Status:** aplicada

## Evidência (origem)
- Descoberto durante a mesma investigação de
  `changes/2026-08-09-posicao-travada-cancel-order-sem-tratamento.md`: após
  aplicar aquele fix e dar redeploy, a reconciliação de startup pausou o
  engine com um alerta diferente do esperado —
  `"ALERTA CRÍTICO: não foi possível recuperar o preço do stop-loss ...
  ao reiniciar"`.
- Consultado `raw_response` persistido da ordem de stop-loss real
  (`orders` no Postgres de produção): `{"symbol": "BTCUSDT", "orderId":
  ..., "orderListId": -1, "clientOrderId": "...", "transactTime": ...}` —
  **sem `status`, sem `price`, sem `stopPrice`**. Comparado com a ordem de
  entrada (`MARKET`) do mesmo par, que veio completa (`status`,
  `executedQty`, `fills`, etc.).

## Causa raiz
- `execution/client.py::place_stop_loss_order` chama `client.create_order(
  type="STOP_LOSS_LIMIT", ...)` sem especificar `newOrderRespType`. A API
  da Binance usa `ACK` (resposta mínima) por padrão para tipos de ordem
  diferentes de `MARKET`/`LIMIT` — que já vêm em `FULL` por padrão. Um `ACK`
  não inclui `status` nem `stopPrice`.
- `execution/orchestrator.py::_extract_stop_price` lê o preço do stop
  exatamente desse `raw_response` persistido
  (`raw.get("stopPrice", raw.get("stop_price"))`) — com `ACK`, essa leitura
  **sempre** falha (`None`), para qualquer ordem de stop-loss real já
  colocada, não só a desta semana. Isso só nunca tinha sido percebido
  porque esse código só roda em `reconcile_position_on_startup`, exercitado
  apenas quando o processo reinicia com uma posição real aberta — um
  caminho raro que, até este incidente, nunca tinha acontecido em produção
  com dado real.
- Efeito prático: a reconciliação de startup segue o caminho de
  `stop_price is None` → `CLAUDE.md` regra 2 tratada corretamente (pausa
  com alerta crítico em vez de prosseguir sem saber o preço do stop) — o
  sistema se protegeu como desenhado, mas nunca deveria ter chegado nessa
  situação para começo de conversa.

## Proposta
- `place_stop_loss_order`: adiciona `newOrderRespType="RESULT"` — inclui
  `status`/`price`/`stopPrice`, sem o custo extra de `fills` (irrelevante
  para uma ordem que acabou de ser criada como `NEW`).
- `place_market_order`: adiciona `newOrderRespType="FULL"` explicitamente
  — já era o comportamento implícito da Binance para `MARKET`, tornado
  explícito por consistência e para não depender de um default não
  documentado no nosso próprio código (exatamente o tipo de suposição
  implícita que causou o bug acima).
- **O que não muda**: nenhum parâmetro de risco/sizing/stop-loss real —
  isso é sobre o formato da resposta da API, não sobre o preço/quantidade
  enviados.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução nem de arquitetura —
  correção de bug de integração com a API da exchange, mesma classe dos
  incidentes anteriores.

## Validação proposta
- Dois testes novos em `test_execution_client.py`: confirmam
  `newOrderRespType` presente e correto (`"RESULT"` ou `"FULL"` para
  stop-loss, `"FULL"` para mercado) na chamada real a `create_order`.
- Suíte completa: 198 passed, 1 deselected (rede) — sem regressão.
- **Não corrige retroativamente** a ordem de stop-loss já malformada no
  banco de produção (`tb-020a7a743103ea5d6de3`) — só ordens novas, a
  partir deste deploy, vêm com resposta completa. A posição presa
  associada a essa ordem específica precisa de reconciliação manual, feita
  separadamente (não neste change).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-09
- Justificativa: bug real de produção, descoberto e corrigido no mesmo
  fluxo de investigação/deploy do incidente da posição travada. Mesma
  urgência.
