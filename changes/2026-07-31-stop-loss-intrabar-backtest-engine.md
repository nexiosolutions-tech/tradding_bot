# Change Proposal — 2026-07-31 — Backtest engine checa stop-loss só no close, ignora pavio intrabar

**Status:** aplicada

## Evidência (origem)
- Ligada a: investigação do usuário sobre 0% win rate no backtest
  `BTCUSDT_1m_7d` (65 trades, 0 vitórias, todas as saídas via `signal_exit`,
  nenhuma via `stop_loss`).
- `backtesting/engine.py`, `_check_exit`, checava
  `snapshot.close <= pos.stop_loss_price` — só o fechamento do candle, nunca
  a mínima (`low`) intrabar. Uma ordem de stop real na exchange dispara no
  instante em que o preço cruza o nível do stop, independente de onde o
  candle fecha. Um candle que fura o stop e fecha de volta acima dele fica
  invisível para o motor de backtest — a posição continua aberta quando, na
  realidade, já teria sido encerrada.
- Confirmado que nenhum teste existente cobria esse cenário:
  `test_backtest_engine.py`'s `_closed_kline` sempre fixava `low=close`,
  então um pavio abaixo do stop nunca era exercitado — mesmo padrão de ponto
  cego já corrigido no orquestrador ao vivo (auditoria de 30/07/2026).
- Não foi a causa raiz do 0% win rate no relatório original (a maior perda
  daquele período foi -1.20%, abaixo do stop de 1.5% configurado — ver
  investigação completa em conversa), mas é uma divergência real e
  documentada entre o que o backtest simula e como uma ordem de stop real se
  comporta, contrariando o próprio objetivo do motor ("not a vectorized
  backtest — vectorizing would hide ordering/timing effects that matter for
  a system meant to run live").
- Confirmado em janelas históricas diferentes (30-37d, 60-67d, 90-97d atrás)
  que `stop_loss` disparava raramente (1-3 vezes em 65-77 trades) — alguns
  desses disparos por `close` podem estar acontecendo mais tarde (ou não
  acontecendo) do que uma ordem real teria disparado pelo pavio.

## Proposta
- `_check_exit` passa a comparar a **mínima (`low`) do candle** contra
  `pos.stop_loss_price`, não o `close`. O preço de execução do stop continua
  sendo o preço do stop em si (`pos.stop_loss_price`), não a mínima do
  candle — mesmo comportamento de preenchimento de antes, só a condição de
  disparo muda.
- `run`/`_on_snapshot` passam a repassar o `low` do payload do candle até
  `_check_exit`.
- **O que não muda:** o preço de saída registrado continua sendo o preço do
  stop (não o pavio); a prioridade stop-loss-antes-de-signal_exit continua a
  mesma; nenhum parâmetro de risco (`stop_loss_pct`, `circuit_breaker_*`) é
  alterado.

## Classificação de risco da mudança
- [x] Parâmetro de risco/execução (requer revisão humana obrigatória) —
  trata-se da fidelidade do motor de backtest à lógica de stop-loss
  estrutural exigida por `CLAUDE.md` regra 2/`05-gestao-de-risco.md`.

## Validação proposta
- Teste reproduzindo exatamente o ponto cego: candle que fura o stop
  intrabar (`low` abaixo do stop) e fecha acima dele — confirma que a saída
  ocorre no candle do pavio, com `exit_reason="stop_loss"` e preço de saída
  igual ao preço do stop.
- Suíte completa de `backtesting/` sem regressão (comportamento em todos os
  testes existentes é preservado porque seus candles sintéticos sempre
  tinham `low == close`).

## Varredura por padrão semelhante em outros lugares (2026-07-31)

Como o mesmo tipo de ponto cego (checar só `close`, ignorar `low`/`high`
intrabar) já havia aparecido tanto no orquestrador ao vivo (auditoria de
30/07) quanto aqui no backtest, foi feita uma varredura por todo
`backend/src/` procurando o mesmo padrão em qualquer lugar que lide com
stop-loss/take-profit:

- `execution/orchestrator.py` (live): **não tem esse padrão** — o
  stop-loss ao vivo é uma ordem `STOP_LOSS_LIMIT` real na própria exchange
  (`_check_exit` só consulta `get_order_status`); é a exchange que dispara
  no cruzamento de preço em tempo real, não o nosso código comparando
  candles. Correto por construção.
- `model/dataset.py` (label de tripla barreira): já usa `future_highs` e
  `future_lows` desde a correção de 30/07/2026
  (`changes/2026-07-30-label-tripla-barreira.md`) — não repete o padrão.
- `execution/client.py`: `stop_price` é só o parâmetro repassado para a
  ordem real na exchange — mesma lógica do item acima, o disparo é da
  exchange, não nosso.
- `model/promotion.py`: reusa a mesma `BacktestEngine` (já corrigida aqui),
  não tem simulação de stop-loss própria.
- `backtesting/strategy.py:45` (`snapshot.close <= lower`): é a condição de
  **entrada** (preço fechou abaixo da banda de Bollinger), não uma checagem
  de stop-loss/take-profit — comparar o close com uma banda de indicador é
  desenho de estratégia normal, não o mesmo bug.
- `_mark_to_market` em `backtesting/engine.py` usa `snapshot.close` para
  marcação a mercado do equity curve/circuit breaker — correto usar o
  último preço conhecido para isso, não a mínima intrabar (não é uma
  checagem de disparo de stop, é uma valorização de posição em aberto).

**Conclusão da varredura:** o único outro lugar com o padrão era este motor
de backtest — não é recorrente além dos dois já corrigidos (orquestrador ao
vivo em 30/07, backtest engine aqui). Nenhuma ação adicional necessária.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("Ótima investigação,
  aprovado. Prossiga com: 1. Draft de changes/ + fix mecânico do stop-loss
  intrabar..."), após investigação conjunta do bug reportado no backtest de
  BTCUSDT_1m_7d.
