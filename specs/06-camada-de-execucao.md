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
  estado antes de tomar qualquer nova decisão de entrada.
- **Ordem rejeitada pela exchange:** logar motivo, não retry automático "cego"
  (evitar reenvio em loop de uma ordem estruturalmente inválida).
- **Execução parcial:** tratada explicitamente — posição parcial ainda precisa
  de stop-loss proporcional ativo.
- **Latência anormal:** se o tempo entre decisão e confirmação de execução
  exceder um limite, o sinal pode estar obsoleto — a camada de execução deve
  poder cancelar/reavaliar em vez de insistir em executar a qualquer custo.

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
  → a exchange rejeita duplicata). Não cobre ainda o caso de crash do processo
  entre a exchange confirmar o fill e o sistema persistir isso localmente —
  reconciliação de ordens de entrada perdidas nesse intervalo é um follow-up,
  não implementado (a reconciliação de gap hoje cobre apenas stop-loss de
  posição já aberta).
