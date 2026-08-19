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

## Terceira rodada: execução real + achado de instabilidade de janela + diagnóstico da causa raiz

Execução contra BTCUSDT 1m real (`data-api.binance.vision`, mainnet). Três achados
encadeados, cada um corrigindo o anterior — registrados na ordem em que apareceram porque a
correção em si é parte do que fica valendo:

### 1. Benchmark inicial (janela relativa a `time.time()`, `--days 45`) — **INVÁLIDO**

Candidato perdeu de buy-and-hold e de flat em 5/5 folds
(`results/benchmark_comparison_BTCUSDT_1787110614258.json`, agora anotado com um campo
`INVALID` no próprio arquivo). PF≈0 no fold mais ativo (175 trades) inicialmente pareceu
sinal invertido; medição direta descartou isso (win rate cai monotonicamente com o número
de trades — 10.7%→10.0%→4.5%→0.6% —, e perda por trade cai na mesma direção, o oposto do
que sinal invertido produziria).

### 2. Achado que invalida a comparação: janela relativa não é reprodutível

`--days N` é relativo a `time.time()` no momento da chamada — dois runs do mesmo código,
~20 minutos apart, buscam janelas de klines diferentes, que produzem `len(rows)` diferente,
que desloca todo limite de fold do walk-forward. Confirmado empiricamente: o mesmo fold 0,
mesmo código, virou 28 trades numa rodada e 9 em outra; fold 2 foi 50 e depois 93. Esse
padrão está espalhado por praticamente todo `scripts/*.py` do projeto (mesma construção
`end_ms = int(time.time()*1000); start_ms = end_ms - days*...` em `run_agentic_learning.py`,
`train_model.py`, `sweep_thresholds.py`, `backtesting/runner.py` e outros) — registrado aqui
como achado a resolver caso a caso quando cada script precisar de reprodutibilidade, não
corrigido em massa nesta rodada (fora do escopo desta investigação).

**Correção aplicada**: `run_benchmark_comparison.py` e `run_nullity_test.py` ganharam
`--start-ms`/`--end-ms` opcionais (mantêm o comportamento antigo relativo se omitidos; o
script sempre imprime a janela resolvida). Janela fixa usada a partir daqui:
`start_ms=1783224227428 end_ms=1787112227428`.

### 3. Diagnóstico da causa raiz (janela fixa, reproduzida 3x com contagens de trade idênticas)

Encadeamento de hipóteses testadas e descartadas, nesta ordem:

- **Stop-loss apertado**: descartado — `stop_loss` é raro (0-2 trades/fold); `signal_exit`
  domina (66/67, 174/174 em runs anteriores da mesma investigação).
- **Descasamento de horizonte** (permanência muito menor que `horizon_minutes=15`):
  descartado depois de medido na janela fixa — permanência mediana ficou em cima do
  horizonte ou bem acima dele na maioria dos folds (0.87x a 50x), o oposto do padrão
  observado na janela instável (que sugeria 2min vs 15min). A hipótese só parecia forte
  por causa do artefato de janela do item 2 — retirada explicitamente.
- **Saída por ruído de banda estreita** (`score_diff_stdev` bar-a-bar ≥ `entry_threshold -
  exit_threshold`): parcialmente sustentada (4 de 5 folds, incluindo um caso degenerado —
  fold com `entry_threshold == exit_threshold` exatos, banda de largura zero), mas o fold
  com mais amostra (fold 2, n=67) tem banda mais larga que o ruído típico e ainda perde —
  não é a explicação completa.
- **Causa raiz identificada: distribuição de score degenerada.** O score do modelo assume
  8 a 31 valores distintos por fold, sobre ~7500 barras avaliadas — os 5 valores mais
  frequentes concentram 83.6% a 100% da massa (fold 2: 8 valores cobrem 100%). Um score
  quase discreto, com a maior parte da distribuição empilhada em poucos valores, é a
  assinatura de um classificador que não aprendeu estrutura real e prevê algo próximo da
  taxa base para quase toda amostra — a banda estreita entre `entry_threshold`/
  `exit_threshold` (item anterior) é sintoma dessa degenerescência, não causa
  independente; reparametrizar percentis não resolveria isso sozinho.
- **Dispersão real, não hipotética, no único fold com amostra**: fold 2 (n=67, o único com
  poder estatístico) — pnl médio -6.23, desvio-padrão real 4.03 (bem mais apertado que
  qualquer suposição inicial), t-estatística **-12.65** contra zero — resultado
  decisivamente negativo, não ruído de amostra pequena. Decomposição bruto/líquido do fold
  2: bruto -155.11, taxas 262.40, líquido -417.51 — o sinal já é negativo antes de
  qualquer custo (taxa quase triplica o prejuízo, mas não é a causa raiz). Mesmo padrão
  (bruto negativo, taxa amplificando) nos folds 0 e 3; fold 4 é a única exceção (bruto
  +11.45) mas com n=6, estatisticamente sem poder nenhum.
- **Poder estatístico da rodada, registrado explicitamente**: folds no formato 9/2/67/29/6
  trades — só o fold 2 (n=67) sustenta qualquer conclusão; fold 3 (n=29) é marginal; folds
  0/1/4 (n=9/2/6) não carregam informação (fold 1 em particular: 2 trades com permanência
  mediana de 2.6 dias — regime de operação diferente do resto, não amostra do mesmo
  comportamento). Nesta janela, o experimento inteiro tem poder estatístico para **uma**
  conclusão confiável, no máximo — reforça que acumulação de dado (não mais cálculo) segue
  sendo a restrição que decide o ritmo da fila estatística inteira.

### Referências de execução

- Reprodução da apuração de trades/exit_reason/thresholds/score/dispersão foi feita via um
  script de diagnóstico ad hoc (não commitado — investigação pontual, não instrumento
  permanente); os números estão fixados neste documento.
- Benchmark de referência (janela fixa): `results/benchmark_comparison_BTCUSDT_1787112227428.json`.
- Teste de nulidade, primeira leitura (janela relativa antiga, **não comparável** com o
  benchmark de referência acima — rotulado como tal para evitar ancoragem):
  `mean_profit_factor` real=0.090 (0/5 folds vencidos), distribuição nula de 30 permutações
  min=0.003 mediana=0.020 max=2.680, p-valor empírico=0.194 — não rejeita a hipótese nula
  (esperado). Segunda leitura, na janela fixa, em andamento — resultado a documentar quando
  terminar.

### Follow-ups registrados, não implementados nesta rodada

- Guarda em `choose_thresholds`/`training.py` contra banda `entry_threshold ≈
  exit_threshold` — proteção contra o sintoma (banda zero), não contra a causa raiz
  (distribuição de score degenerada).
- Investigar por que o score de `TrainedModel.predict_proba` (LightGBM + isotônica) colapsa
  em tão poucos valores distintos — candidatos: poucas folhas efetivamente distintas nas
  árvores, degeneração da regressão isotônica sobre poucos pontos de calibração, ou o
  próprio modelo não achando estrutura no dado disponível (volume de treino pequeno pela
  mesma restrição de amostra do item anterior).
- Aplicar `--start-ms`/`--end-ms` (ou equivalente) aos demais scripts com o mesmo padrão de
  janela relativa, caso/quando cada um precisar de reprodutibilidade — não corrigido em
  massa aqui.

## Pendente

- Resultado do teste de nulidade na janela fixa (rodando).
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
- Terceira rodada (diagnóstico do achado PF≈0/sinal negativo) conduzida a pedido de Brian,
  em três idas e voltas de hipótese-medição-correção: stop-loss apertado (descartado por
  medição), descasamento de horizonte (levantado, depois retirado pelo próprio Brian ao notar
  que os números vinham da janela instável), banda de threshold estreita/ruído (parcialmente
  sustentada), distribuição de score degenerada (causa raiz, identificada por Brian a partir
  do padrão "banda quase zero em vários folds" e confirmada por contagem de valores
  distintos). Instrução explícita sobre o achado de janela: "não são só 'não comparáveis' —
  são inválidos. Vale anotar isso nos changes/ e no JSON do primeiro benchmark" — cumprido
  via campo `INVALID` no JSON original e nesta seção. Instrução sobre o teste de nulidade em
  curso: deixar terminar como leitura da janela antiga (rotulada como tal) e relançar na
  janela fixa para o registro oficial, evitando ancoragem no primeiro número lido.
