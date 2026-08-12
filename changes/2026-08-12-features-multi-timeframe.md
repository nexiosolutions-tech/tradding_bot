# Change Proposal — 2026-08-12 — Features de confluência multi-timeframe (RSI/Bollinger 5m e 15m)

**Status:** aplicada

## Evidência (origem)
- Ligada a: 11ª rodada (`specs/11-roadmap-e-fases.md`) — análise de poder
  estatístico resolveu a favor da leitura de que o teto de `folds_won`
  observado em 10 rodadas é um limite real de capacidade preditiva do
  conjunto features/arquitetura, não falta de amostra ou gate rigoroso
  demais.
- Pedido explícito do usuário para avançar no item 2 (próxima alavanca de
  melhoria), seguindo a ordem sugerida: features multi-timeframe primeiro
  (mais barato, testável já), reformulação de regressão só se insuficiente.

## Proposta
- `rsi_5m`, `rsi_15m`, `bollinger_percent_b_5m`, `bollinger_percent_b_15m`
  (`features/engine.py::_TimeframeAggregator` + `SymbolFeatureState`,
  detalhamento completo em `03-motor-de-features.md`) — os mesmos
  indicadores já usados em 1 minuto, recalculados sobre candles sintéticos
  de 5 e 15 minutos agregados do stream de 1 minuto, para dar ao modelo
  contexto de prazos mais longos que o candle de entrada.
- Adicionadas a `FEATURE_NAMES`/`MODEL_FEATURE_NAMES`
  (`model/dataset.py`) — ao contrário de `move_threshold_atr_multiple`
  (9ª rodada), aqui não há mecanismo de opt-in/opt-out por config; a
  decisão de adotar ou não é sobre manter ou reverter as 4 linhas do
  tuple.
- Invariante de anti-vazamento reforçada: o valor de um bucket de 5/15 min
  só é exposto quando o primeiro candle do bucket seguinte chega — nunca
  durante a formação do próprio bucket.

## Classificação de risco da mudança
- [x] Mudança de arquitetura do modelo (novo conjunto de features de
  input, `CLAUDE.md` regra 7 — requer processo SDD completo, spec 03
  atualizada antes do código).
- Não é mudança de parâmetro de risco/execução.
- Nenhum modelo treinado com estas features foi promovido (nenhum fold
  bateu o gate em nenhuma das duas pernas testadas — ver Resultado) —
  nada muda em produção nesta rodada.

## Validação proposta e resultado
Para isolar o efeito das features novas de deriva de regime de mercado
(cada rodada busca dado numa data/hora diferente), buscado um único
conjunto de 90 dias de klines de 1 minuto (`BTCUSDT`, 129.600 candles) e
rodado `evaluate_config` duas vezes sobre o **mesmo dado exato**: uma vez
com `FEATURE_NAMES` revertido às 16 features anteriores (checkout
temporário), outra com as 20 atuais. Mesma config de referência
(`horizon_minutes=45`, `entry_percentile=99`, sem filtro de regime,
`min_trades=15`, `n_splits=5`).

| | fold 0 | fold 1 | fold 2 | fold 3 | fold 4 | mean_pf | min_pf | folds_won |
|---|---|---|---|---|---|---|---|---|
| sem multi-timeframe | 0.61 (33 trades) | 0.45 (21) | 0.71 (13) | 0.06 (8) | 0.18 (17) | 0.40 | 0.06 | 0/5 |
| com multi-timeframe | 0.56 (21 trades) | 0.34 (84) | 1.01 (10) | 0.05 (9) | 0.33 (10) | 0.46 | 0.05 | 0/5 |

- **`folds_won=0/5` nos dois casos** — as features novas não fecham o gap
  de promoção nesta janela.
- **O delta de `mean_pf` (+0.06) não é distinguível de ruído de janela**:
  a 11ª rodada já tinha rodado essa mesma config de referência horas antes,
  no mesmo dia, e obteve PF por fold `[0.89, 0.72, 0.58, 0.03, 0.23]` —
  bem diferente dos `[0.61, 0.45, 0.71, 0.06, 0.18]` encontrados aqui só
  pela janela de fetch ter avançado. Com folds de 7 a 84 trades, isso é
  esperado (poucos candles a mais/menos perto do limiar do percentil 99
  mudam quem entra), e essa variação natural é maior que o delta atribuído
  às features novas.
- Determinismo confirmado: reroda idêntica em bits dado o mesmo input
  (`random_state=42` do LightGBM se sustenta; a diferença encontrada entre
  a primeira tentativa ao vivo e o rerun em cache veio inteiramente da
  janela de fetch ter mudado, não de não-determinismo do pipeline).
- Suíte completa sem regressão (204 testes).

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-08-12
- Justificativa: continuação direta do plano acordado ("podemos seguir na
  ordem sugerida"). Resultado inconclusivo — nem claramente positivo, nem
  negativo. Mantido no pipeline (paralelo ao filtro de regime, 7ª rodada):
  motivação mecanística continua válida (RSI/Bollinger só em 1 minuto
  ignora confluência de prazo mais longo), não piora nada além do ruído já
  observado entre janelas, e não há resultado claramente pior que
  justifique reverter (diferente do target escalado por ATR, 9ª rodada,
  que teve resultado nitidamente pior e ficou como código não-default).
  Fica como questão em aberto — a próxima decisão de arquitetura deve ser
  avaliada contra este novo baseline de 20 features, não contra o antigo
  de 16.
