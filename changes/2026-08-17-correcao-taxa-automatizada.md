# Change Proposal — 2026-08-17 — Correção de taxa automatizada nas análises de produção

**Status:** aplicada

## Evidência (origem)
- Descoberta em 2026-08-01 (achado que motivou várias análises manuais
  ao longo desta sessão): `TradeRecord.fees_paid` é sempre `0.0`
  (`execution/orchestrator.py`) — não é um bug de dado, testnet
  genuinamente não cobra taxa, mas isso significa que `TradeRecord.pnl`
  (e qualquer relatório baseado nele) superestima sistematicamente o
  resultado que as mesmas operações teriam com taxa real.
- Toda vez que este projeto precisou de uma leitura honesta de produção
  nesta sessão, a correção (mesmo `FeeModel` do backtest, spec 07) foi
  aplicada manualmente, num script ad-hoc, dependente de alguém lembrar
  de fazer isso. Pedido explícito do usuário para automatizar.

## Proposta
- `backtesting/costs.py::net_trade_pnl(trade, fee_model=None)` (novo,
  público) — um único lugar para a correção, reusável por qualquer
  objeto com `entry_price`/`exit_price`/`size`/`pnl`
  (`TradeRecord` e `ClosedTrade` qualificam).
- `learning_engine/daily_report.py::DailyReport` ganha `net_win_rate`/
  `net_total_pnl`; achados de horário (`_find_underperforming_hours`)
  passam a usar P&L **líquido**, não bruto — o relatório automático que
  já roda todo dia via `learning-daily-cron` (specs/09) passa a refletir
  a economia real, não só a exibi-la calculada à parte por mim.
- `render_markdown` mostra bruto e líquido lado a lado, com o líquido em
  destaque e uma nota explicando a diferença — decisão consciente de não
  esconder o bruto (é o que o dashboard mostraria "cru"), só deixar
  claro qual dos dois importa.
- `scripts/analyze_production.py` (novo) — formaliza o script ad-hoc
  usado à mão a sessão toda: consolidação multi-dia, por motivo de
  saída, checagem de circuit breaker, tudo já com a correção aplicada.

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução — é correção de
  relatório/análise, não muda nenhum comportamento de trading. Não
  altera `execution/orchestrator.py` nem o `fees_paid=0.0` real (que
  continua correto para testnet); só corrige como o resultado é
  *reportado*.

## Validação
- 267 testes passando (13 novos: `net_trade_pnl` isolado, e em
  `daily_report.py` — inclusive um caso concreto onde a correção vira
  um "ganho" bruto em prejuízo líquido, e onde um achado de horário só é
  sinalizado depois da correção, não antes).
- 3 testes existentes (`test_change_proposals.py`) atualizados — só
  construíam `DailyReport` diretamente com o conjunto antigo de campos;
  nenhuma lógica deles mudou.
- Rodado contra produção real (`scripts/analyze_production.py --days
  30`): 97 trades, win rate líquido 1%, consistente com toda análise
  manual anterior desta sessão.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-17
- Justificativa: "vamos para o item 2" — segundo item do plano de
  evolução combinado. Próximo item: order book (sem ação ainda, esperar
  mais dado acumular).
