# Change Proposal — 2026-07-31 — Features de nível de preço em escala absoluta, não relativa

**Status:** aplicada

## Evidência (origem)
- Ligada a: revisão de features/target da Fase 2, feita a pedido do usuário
  após a base de backtest/promoção passar a significar algo real (ver
  commits de 2026-07-31 sobre stop-loss intrabar e critério de promoção).
- `features/engine.py` (`SymbolFeatureState.update`) expunha `ema_fast`,
  `ema_slow`, `macd`, `macd_signal`, `macd_hist`, `bollinger_mid`,
  `bollinger_upper`, `bollinger_lower` em **escala de preço absoluto**
  (dezenas de milhares de dólares para BTC) — 7 das 12 features do modelo.
  Só `rsi` (0-100), `bollinger_percent_b` e `relative_volume` já eram
  normalizadas.
- Risco real: um modelo (LightGBM, baseado em árvores) treinado
  majoritariamente numa janela de preço (ex. BTC a ~$60-70k) tende a
  aprender splits ancorados em níveis absolutos que não se transferem para
  um regime de preço muito diferente (~$20k ou ~$100k+) — o histórico do
  ativo cobre uma faixa de preço ampla, e o dataset de treino não
  necessariamente amostra essa faixa de forma equilibrada.

## Proposta
- `features/engine.py`: as 7 features de nível de preço são substituídas por
  6 versões relativas ao `close` (percentual):
  - `ema_fast_dist_pct = (close - ema_fast) / close`
  - `ema_slow_dist_pct = (close - ema_slow) / close`
  - `ema_cross_pct = (ema_fast - ema_slow) / close` (nova — cruzamento de
    médias em termos relativos, diretamente separável por uma árvore sem
    precisar de split composto sobre as duas features de distância)
  - `macd_pct = macd / close`
  - `macd_signal_pct = macd_signal / close`
  - `macd_hist_pct = macd_hist / close`
  - `bollinger_mid/upper/lower` (níveis absolutos) são removidas —
    `bollinger_percent_b` já captura a posição relativa à banda; a
    informação de largura de banda (regime de volatilidade) fica para uma
    iteração futura (feature de bandwidth, já listada como candidata
    separada).
- `model/dataset.py`: `FEATURE_NAMES` atualizado para o novo conjunto (10
  features, era 12) — nenhum outro lugar do pipeline depende de nome/posição
  fixos (treino, calibração e inferência ao vivo já são 100% orientados por
  nome via `TrainedModel.feature_names`/`ModelStrategy`), então a troca é
  transparente para o resto do sistema.
- **O que não muda:** `rsi`, `bollinger_percent_b`, `relative_volume`,
  `volatility` já eram normalizadas — permanecem exatamente como estavam.
  Nenhum parâmetro de risco/execução é afetado.

## Classificação de risco da mudança
- [x] Nova feature (requer revisão humana antes de entrar em specs/03)

## Validação proposta
- Teste de invariância de escala: rodar a mesma série relativa de preços em
  duas escalas absolutas diferentes (1x e 100x) e confirmar que as features
  normalizadas produzem valores idênticos — prova direta de que a escala
  absoluta deixou de vazar para o vetor de features.
- Suíte completa sem regressão (só um teste referenciava o nome antigo
  `ema_fast`, atualizado).
- Validação empírica: re-rodar walk-forward/promoção com o novo conjunto de
  features (junto com a recalibração de target da entrada separada em
  `changes/2026-07-31-recalibracao-target-move-threshold.md`) e comparar
  contra o critério de promoção de `07-backtesting-e-validacao.md`.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("vamos atuar na 1 e 2
  juntas"), após apresentação da lista priorizada de hipóteses de
  feature/target da Fase 2.
