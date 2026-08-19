# 2026-08-19 — Benchmark ajustado a risco + teste de nulidade

## Contexto

Continuação da rodada de rigor estatístico (DSR, PBO/CSCV, benchmark, teste de nulidade,
meta-labeling, detecção de regime) discutida com o usuário em paralelo à captura de
aggTrade/depth (`changes/2026-08-18-captura-aggtrade-fluxo-ordens.md`). O usuário pediu
explicitamente para não esperar a janela de 24h do medidor de ritmo de aggTrade rodar antes
de começar isto — benchmark e teste de nulidade não dependem de captura nova nem da decisão
de arquitetura (a) vs (b) do aggtrade-capture, rodam sobre dado histórico/backtest que já
existe.

Dois itens implementados nesta rodada, ambos reaproveitando o harness de walk-forward já
testado (`model/evaluation.py::evaluate_config`, `model/promotion.py::run_backtest`), não
uma reimplementação paralela.

## 1. Benchmark ajustado a risco

Superar `RsiBollingerPlaceholderStrategy` não é suficiente — esse baseline já foi encontrado
estruturalmente fraco (`specs/07`, achado de 2026-07-31), então um candidato pode vencê-lo
sem ter edge real nenhum. Faltavam dois pontos que o usuário marcou explicitamente como
obrigatórios, não opcionais: comparação ajustada a vol/drawdown (não só retorno bruto) e um
baseline "sempre flat" (não só buy-and-hold).

- `backtesting/metrics.py`: `BacktestMetrics` ganhou `total_return_pct`, `volatility_pct`,
  `return_over_drawdown` (razão tipo Calmar) e `return_over_volatility` (razão tipo Sharpe
  sem taxa livre de risco — válida para comparar candidato vs. benchmark no mesmo período,
  não como número absoluto isolado). Novas funções puras `total_return_pct`,
  `volatility_pct`, `return_over_drawdown`, `return_over_volatility`,
  `buy_and_hold_equity_curve`, `flat_equity_curve` — todas com teste unitário
  (`tests/test_metrics.py`), seguindo a convenção do projeto de que toda função envolvendo
  dinheiro precisa de teste.
- `compute_metrics` passou a aceitar `initial_capital` (default 10_000.0, mesmo valor
  default já usado em todo o projeto) para calcular retorno percentual. `BacktestEngine`
  ganhou o atributo `initial_capital` (antes só usado para inicializar `self.equity`, sem
  ficar acessível depois) — `promotion.py::run_backtest` e `backtesting/report.py::build_report`
  agora passam `engine.initial_capital` em vez de depender do default, única fonte de
  verdade.
- `scripts/run_benchmark_comparison.py` (novo): roda a mesma pipeline walk-forward de
  `train_model.py` (mesmo modelo, mesmo filtro de regime, mesmos folds) e compara,
  **fold a fold** — não só no agregado, pela mesma razão que `promotion.py` já documenta
  ("winning on average across folds is not enough") — o candidato contra buy-and-hold e
  flat. Os três passam pela mesma `compute_metrics`, para que a comparação seja de fato
  maçã-com-maçã.
- `backtesting/report.py`: relatório markdown de qualquer backtest agora mostra retorno
  total, retorno/drawdown e retorno/volatilidade ao lado das métricas já existentes.

## 2. Teste de nulidade (labels embaralhados)

Pergunta diferente do benchmark: não "o candidato bate um baseline ingênuo", mas "o harness
em si vaza informação". Instrução explícita do usuário sobre como interpretar o resultado:
*"o resultado esperado é o pipeline não achar alfa em labels embaralhados. Se achar, o
achado é sobre o harness, e o valor do teste está em levá-lo a sério naquele momento."*

- `model/evaluation.py::evaluate_config` ganhou `shuffle_labels`/`shuffle_seed`. Quando
  ativado, os labels reais (construídos por triple-barrier em `model/dataset.py`, a partir
  de preços futuros) são substituídos por uma permutação de si mesmos — **depois** de
  calculados, então a taxa de label (`label_rate`) fica idêntica, só a correspondência
  feature→label linha a linha é destruída. É a mesma pipeline real (mesmos eventos, mesmos
  folds, mesmo treino/calibração/backtest) — não uma simulação separada.
- `scripts/run_nullity_test.py` (novo): expõe isso via CLI, imprime resultado por fold e um
  veredito explícito — 0 folds vencidos é o resultado esperado; qualquer fold vencido dispara
  um alerta apontando para investigação de vazamento em `03-motor-de-features.md`, não para
  "sorte do candidato".
- Testes (`tests/test_evaluation.py`): `_with_shuffled_labels` preserva o multiset de labels
  mas reordena, é determinística dado um seed, e `evaluate_config` com `shuffle_labels=True`
  produz o mesmo `label_rate` que a versão real — essa igualdade é a garantia de que o
  teste está isolando exatamente a variável que deveria (correspondência feature→label), sem
  confundir com uma mudança na taxa de positivos.

## Suíte

`uv run pytest -q` — 334 passed (15 testes novos entre `test_metrics.py` e
`test_evaluation.py`).

## Pendente

- Rodar `scripts/run_benchmark_comparison.py` e `scripts/run_nullity_test.py` contra dado
  real (BTCUSDT, 45-90 dias) e documentar o resultado aqui — implementação feita, ainda não
  executada contra klines reais nesta rodada.
- Itens da fila estatística que seguem inalterados: DSR, PBO/CSCV, meta-labeling, detecção
  de regime (ordem definida pelo usuário em `changes/2026-08-18-captura-aggtrade-fluxo-ordens.md`).

## Decisão

- Aprovado por: Brian (usuário, dono do projeto) — "Não fique parado esperando as 24h...
  Comece por eles agora" (2026-08-19), referindo-se a benchmark e teste de nulidade
  especificamente, com a ressalva de que o resultado esperado do teste de nulidade é
  ausência de alfa e que um resultado positivo deve ser levado a sério, não descartado.
- Justificativa: nenhum dos dois itens depende da medição de ritmo de aggTrade em
  andamento nem da decisão de arquitetura (a) vs (b) — rodam sobre backtest/histórico já
  disponível, então adiá-los até a janela de 24h terminar seria perder tempo sem motivo
  técnico.
