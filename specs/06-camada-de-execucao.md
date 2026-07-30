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
