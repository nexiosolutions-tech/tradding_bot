# Change Proposal — 2026-08-02 — Timeframe (5m/15m) e par (ETHUSDT): nenhum melhora o gap de promoção

**Status:** aplicada

## Evidência (origem)
- Ligada a: `changes/2026-08-02-target-take-profit-escalado-por-volatilidade.md`
  (9ª rodada), cuja conclusão apontava "testar outro par/timeframe" como
  próximo passo depois que o alvo escalado por volatilidade neutralizou o
  atalho de `atr_pct` sem melhorar o profit factor.
- Pedido do usuário para continuar exaurindo frentes de melhoria de
  performance enquanto o engine roda sem interrupção por uma semana
  acumulando dado real.

## Proposta
- Corrigido `model/evaluation.py::evaluate_config` e
  `model/importance.py::compute_feature_importance`: faltava expor
  `candle_minutes`, então testar dado de intervalo diferente de 1 minuto
  interpretaria `horizon_minutes` errado (como número de candles de 1m, não
  minutos reais).
- Buscado dado real de 90 dias direto da Binance (não o cache anterior,
  específico de `BTCUSDT_1m`): `BTCUSDT` em 5m (25.920 candles) e 15m (8.640
  candles), e `ETHUSDT` em 1m (129.600 candles).
- Testado eixo timeframe (`BTCUSDT` 5m/15m, grade de `horizon_minutes` ×
  `entry_percentile`, sem filtro de regime) e eixo par (`ETHUSDT` 1m, nos
  mesmos pontos já validados para `BTCUSDT`), comparando contra o baseline
  conhecido (`BTCUSDT`/`1m`/`horizon=45`/`entry_pct=99`: `folds_won=2/5`,
  mean_pf 0.73, min_pf 0.20).

## Classificação de risco da mudança
- [ ] Não é mudança de parâmetro de risco/execução nem de arquitetura —
  correção de uma lacuna de wiring (`candle_minutes`) mais investigação
  empírica, sem nenhum default alterado. `train_model.py` continua usando
  `BTCUSDT`/1m.

## Validação proposta e resultado
- **Timeframe**: nenhuma combinação em 5m ou 15m superou o baseline de 1m.
  Melhor caso em 5m (`horizon=30` ou `45`, `entry_pct=99`) **empatou** em
  `folds_won=2/5`, não superou. 15m ficou **pior** (0/5 ou 1/5 em todas as 8
  combinações testadas) — 90 dias em candles de 15 minutos rende poucas
  barras totais, vários folds com 1-7 trades, ruído demais para confiar.
- **Par**: `ETHUSDT` no ponto já validado para `BTCUSDT`
  (`horizon=45`/`entry_pct=99`) chegou a `folds_won=1/5`, mean_pf 0.55, min_pf
  0.17 — **pior** que o mesmo ponto em `BTCUSDT` (2/5, 0.73, 0.20).
- **Conclusão**: nenhum dos dois eixos destrava o gap de promoção; ambos
  pioram em relação ao ponto de referência já conhecido. Reforça a hipótese
  de que a limitação pode estar no conjunto de features/arquitetura, não no
  recorte específico de par/timeframe — ver "Balanço consolidado após 10
  rodadas" em `specs/11-roadmap-e-fases.md` para a leitura completa,
  incluindo a hipótese alternativa (critério de promoção rigoroso demais
  para medir um edge real mas modesto com confiança em 90 dias).
- Suíte completa sem regressão (191 → ver commit).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-02
- Justificativa: continuação do trabalho de investigação pedido
  explicitamente ("vamos continuar exaurindo as frentes"). Resultado
  negativo reportado com a mesma transparência das rodadas anteriores — não
  altera nenhum default de produção.
