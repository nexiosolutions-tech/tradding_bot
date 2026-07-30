# 04 — Modelo de ML e Scoring

## Objetivo

Gerar, a partir do vetor de features, um score contínuo que representa a
probabilidade/confiança de uma oportunidade de trade — não uma decisão binária
direta.

## Definição do alvo (target)

- O modelo **não prevê preço exato**. Prevê algo como: *"probabilidade de
  movimento maior que X% na direção D nos próximos N minutos"*.
- X, D e N são parâmetros de configuração, documentados e versionados junto com
  o modelo — mudá-los é uma mudança de spec/`changes/`, não um ajuste solto.
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
