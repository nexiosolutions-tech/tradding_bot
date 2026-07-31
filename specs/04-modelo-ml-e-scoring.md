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
