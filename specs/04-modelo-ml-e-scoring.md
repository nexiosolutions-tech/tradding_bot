# 04 — Modelo de ML e Scoring

## Objetivo

Gerar, a partir do vetor de features, um score contínuo que representa a
probabilidade/confiança de uma oportunidade de trade — não uma decisão binária
direta.

## Definição do alvo (target)

- O modelo **não prevê preço exato**. Prevê a probabilidade de o trade dar
  lucro **dado que ele sempre é executado com stop-loss** (spec 05/06,
  CLAUDE.md regra 2) — o label reflete o resultado real da estratégia, não um
  cenário hipotético sem proteção.
- **Método da tripla barreira**: dentro de um horizonte de `N` candles à
  frente, existem três barreiras possíveis e o label é definido por qual delas
  é tocada **primeiro**, candle a candle:
  1. **Take-profit**: máxima do candle atinge `close_atual * (1 + X)`.
  2. **Stop-loss**: mínima do candle atinge `close_atual * (1 - stop_loss_pct)`.
  3. **Fim do horizonte**: nenhuma das duas é tocada dentro de `N` candles.
  - `label = 1` somente se a barreira de take-profit for tocada antes da de
    stop-loss. Tocar o stop-loss primeiro, ou não tocar nenhuma barreira, é
    `label = 0`.
- `X` (`move_threshold_pct`), `D` (direção — hoje sempre "alta"), `N`
  (`horizon_bars`) e `stop_loss_pct` são parâmetros de configuração,
  documentados e versionados junto com o modelo — mudar qualquer um deles é
  mudança de spec/`changes/`, não um ajuste solto. `stop_loss_pct` em
  particular deve ser o mesmo valor usado pela camada de execução para aquele
  símbolo/estratégia — treinar contra um stop-loss diferente do real invalida
  a calibração do modelo.
- Checar apenas a máxima futura (sem olhar a mínima) foi identificado como
  bug em auditoria técnica (2026-07-30, ver
  `changes/2026-07-30-label-tripla-barreira.md`): o modelo aprendia a
  reconhecer padrões que "eventualmente" alcançavam o alvo mesmo quando o
  preço teria caído e disparado o stop-loss antes — ou seja, era treinado
  para um mundo sem stop-loss, mas opera em um sistema que sempre tem um. O
  método da tripla barreira é a correção estrutural desse desalinhamento.
- Esse tipo de alvo generaliza melhor do que prever o valor exato do preço, e
  permite calibração posterior (ver seção de calibração).

### Calibração de `move_threshold_pct` vs. custo de round-trip (2026-07-31)

- `move_threshold_pct` (default anterior: 0.3%) estava **exatamente no
  breakeven do custo de round-trip** (~0.2% de taxa + ~0.1% de slippage,
  achado na investigação do backtest de `BTCUSDT_1m_7d` — ver
  `07-backtesting-e-validacao.md`). Isso significa que um "acerto" do label
  (`label=1`) mal cobria os custos de execução — lucro líquido perto de zero
  mesmo quando o modelo acerta a direção. Combinado com `stop_loss_pct` 5x
  maior (1.5%), a razão risco:retorno de 1:5 exigiria taxa de acerto bruta
  de ~83% só para empatar, uma barra alta demais mesmo para um modelo
  genuinamente preditivo.
- Novo default: `move_threshold_pct = 0.008` (0.8%, ~2.7x o custo de
  round-trip) — um `label=1` agora representa uma margem líquida real, não
  um empate contábil. Com `stop_loss_pct` inalterado (1.5%), a razão
  risco:retorno passa a ~1.875:1, exigindo taxa de acerto bruta de ~65% —
  ainda uma barra real, mas bem mais plausível.
- **O que este ajuste explicitamente NÃO faz:** não altera `stop_loss_pct`
  (1.5%), que é parâmetro de risco/execução real usado pela camada de
  execução (`05-gestao-de-risco.md`, `06-camada-de-execucao.md`) — só o alvo
  de lucro usado para *rotular* o dataset de treino muda. Se a validação
  empírica (backtest/walk-forward) mostrar que a razão risco:retorno ainda
  precisa de ajuste, isso é uma proposta separada, explicitamente
  classificada como mudança de parâmetro de risco (`CLAUDE.md` regra 6), não
  uma extensão silenciosa desta.
- Ver `changes/2026-07-31-recalibracao-target-move-threshold.md`.

## Filtro de regime de tendência (2026-07-31)

O score do modelo (calibrado, comparado contra `entry_threshold`) decide
"esse candle específico parece uma oportunidade?" — uma pergunta diferente
de "o regime de mercado atual favorece esta estratégia de forma alguma?".
Investigação de walk-forward (`11-roadmap-e-fases.md`) mostrou que a
segunda pergunta importa mais do que o esperado: PF médio 1.02 em folds de
mercado em alta, 0.29 em folds de baixa, com a estratégia sendo long-only
por design (`06-camada-de-execucao.md`) e sem forma estrutural de lucrar
ou se proteger numa tendência de baixa.

- `RegimeFilteredStrategy` (`model/strategy.py`) embrulha qualquer
  `Strategy` (o `ModelStrategy` ou o placeholder da Fase 1) e **suprime
  novos sinais de entrada** quando `trend_regime_pct` (spec 03) está abaixo
  de um limiar configurável (`min_trend_pct`). Saídas de posições já
  abertas (`should_exit`) nunca são bloqueadas pelo filtro — ele só afeta a
  decisão de *começar* uma posição nova.
- É um **gate explícito na camada de decisão**, não uma feature a mais para
  o modelo aprender sozinho. Testado empiricamente: `trend_regime_pct` como
  input direto do LightGBM (`model/dataset.FEATURE_NAMES`) faz o modelo
  "grudar" nesse sinal macro lento e disparar entradas em excesso e
  correlacionadas em qualquer período de tendência favorável (um fold foi
  de 12 para 98 trades, PF caindo de 1.17 para 0.21) — por isso
  `model/dataset.MODEL_FEATURE_NAMES` **exclui** `trend_regime_pct` do que
  o modelo treina, mesmo a feature continuando disponível no snapshot para
  o filtro ler.
- **Limiar não é 0.0, e não é mais uma constante fixa**: `trend_regime_pct`
  usa uma EMA de 240 candles (~4h), que atrasa e oscila levemente negativo
  em recuos normais dentro de uma tendência de alta real — um corte rígido
  em 0.0 mediu *pior* que não filtrar nada (PF médio 0.62 vs. 0.73 sem
  filtro, primeiro A/B de 2026-08-01). A primeira correção (`-0.005`) foi
  escolhida testando candidatos contra os mesmos folds de teste usados para
  medir o resultado — calibração dentro da amostra, o mesmo tipo de erro já
  advertido pela ressalva de `min_profit_factor`
  (`changes/2026-07-31-criterio-promocao-expectancia-positiva.md`).
  `choose_regime_threshold` (`model/strategy.py`) corrige isso: para cada
  fold do walk-forward, faz backtest de cada candidato de `min_trend_pct`
  só contra a **fatia de calibração** (o mesmo intervalo de tempo já usado
  por `choose_thresholds` para `entry_threshold`/`exit_threshold`, nunca o
  fold de teste) e mantém o de melhor profit factor — a mesma disciplina
  já aplicada aos outros dois thresholds, agora estendida a este. Se nenhum
  candidato atingir a amostra mínima na fatia de calibração, cai de volta
  no candidato mais permissivo (sem filtro) em vez de aplicar um limiar não
  validado. Ligado em `train_model.py` e `sweep_thresholds.py`; o valor
  escolhido por fold vai para `metadata.json` do modelo salvo
  (`model/versioning.py`) e é o que `execution/bootstrap.py` usa ao montar
  a estratégia ao vivo. O placeholder da Fase 1 (nunca treinado/calibrado)
  continua usando o fallback fixo `PLACEHOLDER_MIN_TREND_PCT = -0.005`.
- **O que não muda:** nenhum parâmetro de risco/execução (`stop_loss_pct`,
  sizing, circuit breaker) é afetado — o filtro só decide *quando* tentar
  uma entrada, nunca *como* dimensioná-la ou protegê-la uma vez aberta.
- Ver `changes/2026-07-31-filtro-regime-tendencia.md`.

## Modelo baseline

- **LightGBM/XGBoost** como baseline — bom desempenho em features tabulares de
  mercado, inferência rápida (compatível com o orçamento de latência de tempo
  real), e interpretável via importância de features/SHAP.
- Modelos mais pesados (LSTM/GRU, Transformers, Reinforcement Learning) são
  candidatos de evolução, propostos via `changes/` com justificativa baseada em
  dados (ex.: evidência de que dependência temporal de longo alcance não capturada
  pelo baseline está custando performance) — não adotados por padrão.

## Pipeline de treino

1. Dataset construído a partir do feature store (produção real) + backfill
   histórico via REST.
2. Split temporal (nunca aleatório) — treino, validação, teste em blocos
   cronológicos sequenciais.
3. Validação via **walk-forward** (ver `07-backtesting-e-validacao.md`) — nunca
   validação cruzada aleatória, que vaza informação do futuro para o passado.
4. Calibração do score (ex.: `CalibratedClassifierCV` ou calibração isotônica)
   para que "score 0.7" realmente signifique ~70% de acerto histórico — sem
   isso, o score não é utilizável de forma confiável pela camada de decisão.
5. Peso de classe (`scale_pos_weight`, 2026-07-31) calculado a partir do
   próprio desbalanceamento observado em cada fold de treino — `label=1` foi
   observado em 0.5-6% das linhas dependendo do horizonte, e sem
   compensação o treino podia otimizar a perda simplesmente prevendo a
   classe majoritária. Treino usa `random_state` fixo para que comparações
   de configuração (hiperparâmetros, sweeps) não sejam contaminadas por
   aleatoriedade interna do treino em si. Ver
   `changes/2026-07-31-peso-classe-e-seed-treino.md`.

## Orçamento de latência

- Inferência de produção deve rodar em milissegundos, compatível com o ciclo de
  decisão em tempo real. LightGBM/XGBoost atendem isso nativamente; qualquer
  modelo mais pesado precisa comprovar que cabe no orçamento antes de ser
  promovido.

## Versionamento e retreino

- Todo modelo treinado é salvo com: versão, timestamp, dataset usado (hash/range
  de datas), métricas de validação, e hiperparâmetros.
- Retreino periódico (cadência definida em `changes/` conforme observação de
  drift) gera uma nova versão candidata.
- Uma versão candidata **só é promovida a produção se superar a versão atual em
  backtest out-of-sample**, segundo os critérios objetivos de
  `07-backtesting-e-validacao.md`. Esse critério é o que permite automatizar o
  retreino com segurança, sem revisão humana a cada ciclo (diferente de mudança
  de arquitetura/target, que sempre passa por revisão — ver `CLAUDE.md`).
- Histórico de versões e a métrica de cada uma fica visível no dashboard
  (ver `08-dashboard-e-visualizacao.md`, view "Modelo").

## Observabilidade do modelo

- Toda inferência em produção é logada com: score gerado, versão do modelo,
  snapshot das features de entrada, e (retroativamente) o resultado real —
  permitindo medir calibração ao longo do tempo, não só acurácia agregada.
- Importância de features (ex. SHAP) é calculada periodicamente e exposta no
  dashboard para entender o que está pesando nas decisões recentes.

## Invariantes

- Nenhum treino usa dados com timestamp posterior ao "presente simulado" do
  respectivo ponto do dataset (mesma disciplina anti-leakage do motor de
  features).
- Promoção de modelo é sempre um evento auditável e reversível (é possível
  voltar à versão anterior).
