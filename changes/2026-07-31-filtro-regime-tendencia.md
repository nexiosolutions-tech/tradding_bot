# Change Proposal — 2026-07-31 — Filtro explícito de regime/tendência (long-only)

**Status:** aplicada

## Evidência (origem)
- Ligada a: investigação de variação de profit factor (PF) por fold do
  walk-forward, pedida pelo usuário logo após o resultado do balanceamento
  de classe (`changes/2026-07-31-peso-classe-e-seed-treino.md`, primeiro PF
  acima de 1.0 num fold isolado).
- Para os mesmos 5 folds (`horizon_minutes=45`, `entry_percentile=99`, 90
  dias, `BTCUSDT_1m`), classificando cada fold pela tendência real do
  período: PF médio nos 3 folds de alta = **1.02**; PF médio nos 2 folds de
  baixa = **0.29**. Fold 3 e fold 4 têm range de preço parecido (~6-7%), mas
  PF muito diferente — a variável explicativa é a *direção* da tendência,
  não a volatilidade.
- Explicação mecanística: a estratégia é estruturalmente long-only (sem
  margem/short, `specs/06-camada-de-execucao.md`) — não tem como lucrar
  numa queda nem se proteger dela além do stop-loss. Deixar o modelo
  "tentar" operar igual em qualquer regime desperdiça capital em setups sem
  vantagem estrutural.

## Proposta
- Nova feature `trend_regime_pct` no `FeatureEngine`
  (`(close - EMA_240) / close`, ~4h de EMA sobre candles de 1min, sem
  warm-up gate) — `specs/03-motor-de-features.md`.
- Novo wrapper `RegimeFilteredStrategy` (`model/strategy.py`): suprime
  *novas entradas* quando `trend_regime_pct` está abaixo de um limiar;
  nunca bloqueia saídas de posição já aberta. Ligado em `train_model.py`,
  `sweep_thresholds.py` (candidato do backtest/promoção) e
  `execution/bootstrap.py` (estratégia realmente ativa em runtime, seja
  modelo promovido ou o placeholder da Fase 1) — a limitação long-only vale
  para qualquer estratégia ativa, não só o modelo ML.
- **`trend_regime_pct` fica de fora do conjunto de features que o próprio
  modelo treina** (`MODEL_FEATURE_NAMES` em `model/dataset.py`, excluindo
  essa feature de `FEATURE_NAMES`) — achado durante a validação empírica
  abaixo: dar essa feature de trend macro diretamente ao LightGBM faz o
  modelo "grudar" nela e disparar entradas em excesso, altamente
  correlacionadas, durante qualquer período de tendência favorável (um fold
  foi de 12 para 98 trades, PF caindo de 1.17 para 0.21). Gatear *quando*
  operar por essa feature funciona; deixar o modelo tratá-la como só mais
  um input, não.
- Limiar do filtro (`min_trend_pct`) calibrado em **-0.005**, não 0.0 — ver
  validação empírica abaixo para o porquê.

## Classificação de risco da mudança
- [x] Mudança de arquitetura/lógica de decisão da estratégia (requer
  processo SDD completo) — `CLAUDE.md` regra 7 (mudança de arquitetura do
  modelo/target não se qualifica como "retreino" simples).
- Não é mudança de parâmetro de risco/execução (`CLAUDE.md` regra 6): não
  mexe em sizing, stop-loss, circuit breaker nem client order ID. É lógica
  de *quando tentar uma entrada*, aplicada antes de qualquer decisão de
  risco/execução existente.
- Nenhum modelo está promovido em produção hoje — a mudança afeta o
  pipeline de treino/avaliação/execução ao vivo, mas não altera qual
  estratégia está de fato ativa agora (continua o placeholder da Fase 1,
  agora também passando pelo filtro de regime).

## Validação empírica
A/B controlado no cache de 90 dias (mesma seed, mesmos 5 folds, config já
validada em `changes/2026-07-31-peso-classe-e-seed-treino.md`:
`horizon_minutes=45`, `entry_percentile=99`, balanceamento de classe ligado,
`random_state=42`):

- **Sem filtro** (baseline, modelo já sem `trend_regime_pct` como input):
  PF por fold `[1.54, 0.38, 1.03, 0.50, 0.20]`, média **0.73**,
  `folds_won=2/5`. Reproduz exatamente o resultado documentado na 4ª rodada
  — confirma que excluir a feature do treino do modelo não regrediu nada
  que já funcionava.
- **Com filtro, limiar 0.0** (primeira tentativa): PF por fold
  `[1.17, 0.27, 1.06, 0.55, 0.07]`, média **0.62** — *pior* que sem filtro,
  inclusive nos dois folds de baixa que o filtro deveria ajudar (fold 1:
  0.38→0.27; fold 4: 0.20→0.07). Causa: `trend_regime_pct` usa EMA de 240
  candles, que atrasa e oscila levemente negativo em recuos normais dentro
  de uma alta — um corte rígido em 0.0 bloqueia essas entradas boas junto
  com as ruins.
- **Sweep do limiar** (`-0.01, -0.005, 0.0, +0.005, +0.01, +0.02`, mesmos
  folds pré-treinados): melhor ponto em **-0.005** — PF por fold
  `[1.54, 0.33, 1.41, 0.57, 0.19]`, média **0.81**, `folds_won=2/5`
  (inalterado — os folds que já venciam continuam vencendo, os que
  perdiam continuam perdendo, mas com folga um pouco maior/menor conforme
  o caso). Limiares positivos colapsam o número de trades a quase zero.
- **Ressalva estatística explícita**: o limiar `-0.005` foi escolhido
  testando 6 valores contra os *mesmos* 5 folds de teste usados para medir
  o resultado — isso é calibração dentro da amostra, não validação
  out-of-sample (o mesmo tipo de cuidado que motivou
  `changes/2026-07-31-criterio-promocao-expectancia-positiva.md` para
  `min_profit_factor`). Ainda não muda a decisão de promoção
  (`folds_won` continua 2/5 nos dois casos — nenhum modelo seria promovido
  hoje de qualquer forma), então o risco de aplicar agora é baixo, mas o
  valor de `-0.005` deve ser tratado como provisório até uma
  recalibração walk-forward-limpa (escolhido a partir de dados de
  treino/calibração, do mesmo jeito que `entry_threshold`/`exit_threshold`
  já são, não do fold de teste).
- Suíte completa: 163 passed, 1 deselected (rede) — incluindo teste de
  regressão para o default `min_trend_pct=-0.005`.

## Decisão
- Aprovado por: Brian (usuário, dono do projeto)
- Data: 2026-07-31
- Justificativa: aprovação explícita em conversa ("Podemos prosseguir com
  um filtro de regime/tendência explícito, em vez de deixar o modelo
  tentar (e falhar) operar igual em qualquer direção de mercado"), após a
  investigação de variação de PF por fold apontar a direção da tendência
  como variável explicativa.
- Nota para a próxima iteração: recalibrar `min_trend_pct` de forma
  out-of-sample (a partir de dados de treino, não do fold de teste) antes
  de tratar -0.005 como valor final.
