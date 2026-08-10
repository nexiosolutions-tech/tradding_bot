# 06 — Camada de Execução

## Objetivo

Traduzir uma intenção de trade (já aprovada pela gestão de risco) em ordens
reais na Binance, de forma confiável, e manter o estado do sistema sincronizado
com a realidade da exchange.

## Fluxo de execução

1. Orquestração recebe score do modelo → aplica filtros de decisão (threshold,
   confirmação por múltiplos sinais, se aplicável) → gera intenção de trade.
2. Intenção passa pela gestão de risco (`05-gestao-de-risco.md`) → recebe
   tamanho de posição e stop-loss definidos, ou é rejeitada.
3. Camada de execução envia ordem via API da Binance (`python-binance`/`ccxt`),
   com `client order id` idempotente.
4. Todo evento de ciclo de vida da ordem é persistido: enviada, confirmada,
   parcialmente executada, preenchida, cancelada, rejeitada.
5. Reconciliação periódica (polling ou stream de user data) entre estado local
   e estado real da conta na exchange.

## Ambientes

| Ambiente | Uso | Gate para promoção |
|---|---|---|
| **Testnet** (`testnet.binance.vision`) | Todo desenvolvimento e validação de lógica de execução | — |
| **Mainnet, capital simbólico** | Primeira validação com dinheiro real, valor mínimo | Testnet estável por período mínimo definido em `changes/` |
| **Mainnet, capital real** | Operação plena | Aprovação humana explícita, ver `CLAUDE.md` regra 6 |

Nenhuma mudança na lógica de execução pula etapas dessa tabela.

## Estados do sistema (refletidos no dashboard)

Ver máquina de estados completa em
[`01-arquitetura-sistema.md`](./01-arquitetura-sistema.md). Resumo relevante
para execução:

- `ANALISANDO` → `POSICAO_ABERTA`: transição só ocorre após confirmação real de
  fill pela exchange, não no momento do envio da ordem (execução parcial ou
  rejeição não deve ser tratada como sucesso).
- `POSICAO_ABERTA` → `ANALISANDO`: ao fechar posição (take-profit, stop-loss
  disparado, ou saída por sinal do modelo).
- Qualquer estado → `PARADO_CIRCUIT_BREAKER`: automático, conforme
  `05-gestao-de-risco.md`.
- Qualquer estado → `PAUSADO`: manual, via dashboard.

## Tratamento de falhas

- **Queda de conexão:** reconectar com backoff; ao reconectar, reconciliar
  estado antes de tomar qualquer nova decisão de entrada. Um payload de
  mensagem malformado/inesperado custa apenas essa mensagem (log e ignora) —
  não derruba a conexão inteira, já que o transporte em si continua saudável.
- **Ordem rejeitada pela exchange:** logar motivo, não retry automático "cego"
  (evitar reenvio em loop de uma ordem estruturalmente inválida).
- **Execução parcial:** tratada explicitamente — posição parcial ainda precisa
  de stop-loss proporcional ativo.
- **Latência anormal:** se o tempo entre decisão e confirmação de execução
  exceder um limite, o sinal pode estar obsoleto — a camada de execução deve
  poder cancelar/reavaliar em vez de insistir em executar a qualquer custo.
- **Falha ao colocar o stop-loss depois da entrada já preenchida:** cenário
  distinto de "ordem rejeitada" acima — aqui a entrada já é real e está aberta
  na exchange, então simplesmente desistir deixaria uma posição sem proteção
  (viola `CLAUDE.md` regra 2). A colocação do stop-loss é retentada um número
  limitado de vezes; se todas falharem, a posição é fechada de emergência a
  mercado. Se até o fechamento de emergência falhar, o motor se pausa
  (`PAUSADO`) e registra um alerta crítico — esse é o limite do que o software
  pode resolver sozinho, dali em diante é intervenção humana.
- **Exceção inesperada no processamento de um evento:** não pode derrubar a
  task que processa o stream de eventos para sempre — é capturada, logada, e o
  próximo evento ainda é processado normalmente.
- **Regras de lote/preço/notional mínimo da exchange (LOT_SIZE, PRICE_FILTER,
  MIN_NOTIONAL):** violá-las é rejeição dura pela Binance, não um aviso.
  Quantidade é arredondada para baixo no `stepSize` do símbolo e o preço do
  stop no `tickSize` (usando `Decimal`, nunca float puro, para evitar erro de
  precisão) antes de qualquer ordem ser enviada. Se o sinal, já arredondado,
  ficar abaixo do notional mínimo, a entrada é rejeitada com log claro em vez
  de gerar uma ordem fadada à rejeição pela exchange.
- **Ordem de stop-loss que a exchange não reconhece mais no momento de
  cancelar para sair por sinal** (2026-08-09, incidente real de produção —
  ver `changes/2026-08-09-posicao-travada-cancel-order-sem-tratamento.md`):
  cenário distinto de "falha ao colocar o stop-loss" acima — aqui a posição
  já está aberta com stop-loss ativo há tempo, e o próprio `should_exit` da
  estratégia decide sair, mas cancelar o stop antes de vender a mercado
  falha porque a exchange não reconhece mais aquela ordem (código -2011,
  "Unknown order sent" — já preenchida, já cancelada, ou perdida por algum
  motivo do lado da exchange, ex. reset de dado em testnet). Sem tratamento,
  isso travava a checagem de saída inteira indefinidamente — a posição
  nunca mais fechava, mesmo com um sinal de saída válido todo candle. Agora:
  falha ao cancelar dispara uma re-checagem do status da ordem — se foi de
  fato preenchida (a posição já fechou via stop-loss, não vender de novo),
  finaliza como `stop_loss`; se não foi preenchida e simplesmente sumiu,
  prossegue com a venda a mercado mesmo assim (a estratégia já decidiu
  sair e não há stop funcional para confiar). `get_order_status` também
  passou a distinguir "ordem não existe" (códigos -2011 e -2013 — Binance
  usa códigos diferentes no endpoint de cancelamento vs. consulta,
  confirmado direto contra a testnet real; resposta legítima `None`) de
  qualquer outra falha (rede, rate limit — propaga, em vez de ser
  silenciosamente tratada como "não preenchida").
- **Resposta da exchange ao colocar o stop-loss vinha sem `status`/`price`**
  (2026-08-09, descoberto durante a mesma investigação do incidente acima —
  ver `changes/2026-08-09-posicao-travada-cancel-order-sem-tratamento.md`):
  `create_order` para `STOP_LOSS_LIMIT` nunca pedia `newOrderRespType`
  explicitamente, e a Binance usa `ACK` (resposta mínima — só `symbol`,
  `orderId`, `clientOrderId`, `transactTime`) por padrão para esse tipo de
  ordem, ao contrário de `MARKET`, que já vem em `FULL`. Isso fazia
  `_extract_stop_price` (usado só na reconciliação de estado no restart)
  falhar silenciosamente pra **toda** ordem de stop-loss real colocada,
  desde sempre — só nunca tinha sido exercitado porque reconciliação de
  startup com posição real aberta é um caminho raro. Corrigido pedindo
  `newOrderRespType="RESULT"` (stop-loss) e `"FULL"` (mercado, explícito
  por consistência, já era o comportamento implícito).

## Fora de escopo no MVP

- Execução em múltiplas exchanges simultâneas.
- Ordens avançadas (OCO complexas, trailing stop nativo da exchange) — MVP usa
  stop-loss simples gerenciado pelo próprio sistema; evolução via `changes/`.

## Status de implementação (Fase 4)

Implementado em `backend/src/tradingbot/execution/`: `client.py` (interface
`ExchangeClient` + `BinanceTestnetClient` real via `python-binance`),
`idempotency.py`, `orchestrator.py` (máquina de estados + fluxo de
entrada/saída/circuit breaker/gap), `bootstrap.py` (wiring compartilhado entre
o script standalone `scripts/run_live.py` e o serviço da API). Testado com um
`FakeExchangeClient` em memória (`backend/tests/fakes.py`) — sem chaves de
testnet ainda, a validação contra a exchange real está pendente.

**Simplificação sobre `AGUARDANDO`:** a máquina de estados implementada usa
apenas `ANALISANDO`/`POSICAO_ABERTA`/`PAUSADO`/`PARADO_CIRCUIT_BREAKER` — o
estado `AGUARDANDO` descrito em `01-arquitetura-sistema.md` (score não atingiu
threshold) é um sub-caso de `ANALISANDO` sem transição própria, já que não
muda comportamento do sistema, só a leitura humana do que está acontecendo.

**Lacunas conhecidas, a fechar antes de qualquer capital real:**
- `fees_paid` é gravado como `0.0` nos trades reais — a Binance deduz a
  comissão do próprio fill (potencialmente em outro ativo) e isso ainda não é
  convertido/agregado. Sinalizado no código, não fabricado como zero "de
  verdade".
- Idempotência cobre retry de rede no envio da ordem (mesmo `client_order_id`
  → a exchange rejeita duplicata). **Ainda não cobre** o caso estreito de
  crash do processo exatamente entre a exchange confirmar o fill e o sistema
  persistir isso localmente (`_persist_order` nunca chega a rodar) — se não
  há nenhum `OrderRecord` da entrada, a reconciliação de startup (abaixo) não
  tem o que reconciliar. Janela de risco pequena na prática (seria um crash
  no meio de uma chamada de rede específica), mas ainda não fechada.

**Correções de 2026-07-30 (auditoria técnica), já implementadas:**
- Retry + fechamento de emergência para falha ao colocar stop-loss após entrada
  preenchida; captura ampla de exceção em torno do processamento de cada
  evento; parsing defensivo por mensagem no stream do WebSocket. Ver
  [`changes/2026-07-30-tratamento-excecao-execucao.md`](../changes/2026-07-30-tratamento-excecao-execucao.md).
- Validação de `LOT_SIZE`/`PRICE_FILTER`/`MIN_NOTIONAL` antes de qualquer envio
  de ordem (`ExchangeClient.get_symbol_filters`,
  `execution/rounding.py`). Ver
  [`changes/2026-07-30-validacao-regras-exchange.md`](../changes/2026-07-30-validacao-regras-exchange.md).
- Endpoints de comando do dashboard (`pause`/`resume`/`acknowledge_circuit_breaker`)
  e o WebSocket `/ws/engine` aceitam uma `DASHBOARD_API_KEY` opcional — ver
  [`08-dashboard-e-visualizacao.md`](./08-dashboard-e-visualizacao.md) e
  [`changes/2026-07-30-autenticacao-endpoints-controle.md`](../changes/2026-07-30-autenticacao-endpoints-controle.md).

**Reconciliação de estado no startup (2026-07-31):** um restart do processo
(reload local, redeploy no Railway, crash) nunca reconstruía `equity` nem
sabia se havia uma posição real ainda aberta na exchange — `Orchestrator`
sempre iniciava "flat" com o capital de configuração, independente da
realidade. Achado ao investigar se valia a pena rodar continuamente no
Railway em vez de localmente (a resposta acabou sendo: o gap existe nos
dois lugares igualmente, já que o Railway também reimplanta a cada push).
- `bootstrap.build_orchestrator` soma o P&L já realizado (persistido em
  `TradeRecord`) ao `INITIAL_EQUITY` de configuração, em vez de sempre
  resetar para o valor de configuração puro.
- `Orchestrator.reconcile_position_on_startup` (chamado uma vez, antes do
  stream de eventos começar, tanto em `api/app.py` quanto em
  `scripts/run_live.py`): procura a entrada preenchida mais recente sem
  `TradeRecord` correspondente e o stop-loss registrado depois dela.
  - Se não encontrar entrada pendente: segue flat, nada a fazer.
  - Se encontrar entrada mas nenhum stop-loss registrado depois: **alerta
    crítico e pausa** — mesmo princípio de `_emergency_close_unprotected`,
    não adivinha, exige intervenção humana.
  - Se o stop já disparou na exchange enquanto o processo estava fora do ar
    (checado via `get_order_status`, a exchange como fonte de verdade):
    finaliza o trade agora, com o mesmo caminho de código de
    `_finalize_exit` usado pela reconciliação de gap de WebSocket.
  - Se o stop ainda está ativo na exchange: reconstrói `OpenPositionLive` e
    volta a monitorar normalmente (transição para `POSICAO_ABERTA`, mesmo
    partindo de `PAUSADO` — a posição já existe de verdade na exchange
    independente do estado do software, então monitorá-la para fechamento
    não é o mesmo tipo de decisão autônoma que "boots paused" existe para
    evitar).
  - Não cobre o caso estreito descrito na lacuna acima (crash antes do
    `OrderRecord` da entrada ser persistido) — não há o que reconciliar sem
    nenhum registro local da entrada.
