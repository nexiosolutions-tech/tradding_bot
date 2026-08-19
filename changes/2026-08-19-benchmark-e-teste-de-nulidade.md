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

## Segunda rodada: N permutações + p-valor, série de retorno persistida, exposição/custo no benchmark

Três correções pedidas antes de rodar contra dado real (mais barato corrigir agora do que
rodar tudo de novo depois):

- **Teste de nulidade: uma semente não é um teste.** `evaluate_config(shuffle_labels=True)`
  com uma única semente é um sorteio único — "0 folds vencidos" nessas condições é evidência
  fraca, e o inverso também vale (um fold vencido não diz se é vazamento ou acaso normal de
  amostra). `model/evaluation.py::run_nullity_test` (novo) roda a avaliação real uma vez e
  N permutações (`n_permutations`, default 30, sementes `base_seed..base_seed+N-1`), monta a
  distribuição nula de `mean_profit_factor`, e reporta um **p-valor empírico**:
  `(permutações que igualaram/superaram o real + 1) / (N + 1)` — correção `+1/+1` padrão de
  teste de permutação, evita declarar p=0.0 exato por N ser finito. `scripts/run_nullity_test.py`
  reescrito para chamar `run_nullity_test` e imprimir a distribuição + p-valor.
  Efeito colateral notado pelo usuário: essa distribuição nula aproxima, sem custo adicional,
  parte da pergunta que o DSR (ainda pendente) vai responder depois.
- **Item "quase de graça": série de retorno por fold parou de ser descartada.**
  `compute_metrics` já recebia `equity_curve` para calcular `volatility_pct` e devolvia só o
  escalar — `BacktestMetrics` ganhou o campo `equity_curve` (persiste o que já estava em
  memória) e `FoldSummary` (`model/evaluation.py`) passou a carregar essa série também. Não
  muda nenhum critério de promoção; destrava DSR/PBO mais tarde sem precisar re-rodar backtest
  só para recuperar o dado.
- **Benchmark: exposição e assimetria de custo, antes implícitas.** `BacktestMetrics` ganhou
  `exposure_pct` (fração do período com posição aberta, via novo
  `backtesting/metrics.py::exposure_pct`). `scripts/run_benchmark_comparison.py` agora
  imprime exposição dos três (candidato via `exposure_pct`; buy&hold=100%, flat=0% por
  definição, já que nenhum dos dois é construído a partir de `ClosedTrade`) e declara
  explicitamente, em texto e no JSON salvo: buy-and-hold não paga taxa/slippage nesta
  comparação (o candidato paga — viés do lado seguro, mas precisa ficar visível) e
  `return_over_volatility` usa volatilidade por barra, não anualizada.

## Suíte

`uv run pytest -q` — 344 passed (10 testes novos nesta segunda rodada, sobre os 334 da
primeira: `exposure_pct` em `test_metrics.py`; `run_nullity_test`/`NullityTestResult`/
`FoldSummary.equity_curve` em `test_evaluation.py`).

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
- Segunda rodada aprovada por: Brian — "Push primeiro... Sobe, aplica as N sementes, e roda
  os dois" (2026-08-19), com a justificativa explícita de que uma semente única não
  constitui teste de nulidade (sorteio único, sem distribuição para comparar), e de que
  `equity_curve`/`exposure_pct` eram "quase de graça" porque a série de retornos já estava
  em memória dentro de `compute_metrics` antes de ser descartada.
