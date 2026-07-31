# Change Proposal — 2026-07-31 — Duas features novas: ATR (range intrabar) e cíclicas de tempo

**Status:** aplicada

## Evidência (origem)
- Ligada a: lista priorizada de hipóteses de feature/target da Fase 2
  (apresentada em conversa após a normalização de escala e recalibração de
  target de 31/07), itens 3 e 4 — retomados após a revisão geral do projeto,
  aprovados explicitamente pelo usuário ("Sim, vamos seguir a sua
  recomendação").
- `RealizedVolatility` (stdev de log-retornos close-to-close) é cega a
  pavios: um candle com wick grande para os dois lados mas fechamento plano
  parece perfeitamente calmo para essa feature, mesmo tendo um range
  intrabar real — justamente o tipo de movimento que faltava considerar até
  o fix de stop-loss intrabar de ontem no motor de backtest.
- Os próprios relatórios de backtest já mostram `pnl_by_hour`/
  `pnl_by_weekday` desiguais (ex. -41.5 às 13h vs. -2.2 às 15h) — mercado
  cripto tem padrões conhecidos de volume/volatilidade por sessão
  (Ásia/Europa/EUA), mas o modelo não tinha nenhuma feature de tempo para
  aprender esse efeito, só ruído.

## Proposta
- Nova classe `ATR` (Average True Range, suavização de Wilder, mesmo estilo
  do RSI) em `features/indicators.py`. Exposta como `atr_pct` (ATR dividido
  pelo close) — segue a mesma regra de normalização de 31/07, nunca em
  escala de preço absoluto.
- `FeatureEngine`/`SymbolFeatureState.update` passam a receber `high`/`low`
  do candle (antes só recebiam `close`/`volume`), necessários para o
  cálculo de true range.
- Novas features `hour_sin`/`hour_cos`/`dow_sin`/`dow_cos`, calculadas
  diretamente do `knowledge_ts` em `FeatureEngine.on_event` (não dependem de
  estado por símbolo, são função pura do timestamp). Zero risco de leakage —
  o horário de fechamento do candle é sempre conhecido de antemão.
- `model/dataset.py`: `FEATURE_NAMES` ganha as 5 novas entradas (10 → 15).
- **O que não muda:** nenhuma feature existente é alterada; o buffer de
  candles do `Orchestrator` usado só para o gráfico de preço (adicionado
  ontem) continua com seus próprios indicadores em escala absoluta,
  propositalmente separados do vetor do modelo — não ganhou ATR nesta
  entrada (fora de escopo, é sobre features do modelo, não sobre o
  gráfico).

## Classificação de risco da mudança
- [x] Nova feature (requer revisão humana antes de entrar em specs/03)

## Validação proposta
- Testes unitários da classe `ATR` isolada (`test_indicators.py`): warm-up,
  captura de range intrabar que `RealizedVolatility` não vê, e o cálculo de
  true range incluindo gap em relação ao close anterior.
- Testes de integração no `FeatureEngine` (`test_feature_engine.py`):
  `atr_pct` ausente durante warm-up e presente/normalizado depois; features
  cíclicas sempre presentes e limitadas a [-1, 1]; 23h e 01h ficam próximas
  no espaço de features (não ~22h de distância, como um inteiro cru
  sugeriria).
- Suíte completa sem regressão.
- Validação empírica: re-rodar o pipeline de treino com o conjunto de
  features ampliado, junto com o sweep de `entry_percentile`/
  `horizon_minutes` (entrada separada), e comparar contra o critério de
  promoção.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("Sim, vamos seguir a sua
  recomendação"), após apresentação de revisão geral do projeto e lista
  priorizada de próximos passos para o modelo.
