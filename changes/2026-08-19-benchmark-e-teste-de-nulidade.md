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

## Quarta rodada: causa raiz da causa raiz — calibração isotônica colapsa o score, thresholds passam a ranquear no score cru

Dois acréscimos do usuário sobre o achado de degenerescência de score da terceira rodada,
o primeiro decisivo:

- **Teste decisivo**: contar valores distintos do score *antes* da calibração isotônica e
  comparar com depois. Medido nos mesmos 5 folds da janela fixa: score cru tem 259 a 561
  valores distintos (3.5%-7.5% das ~7500 amostras); calibrado tem 8 a 31 (0.1%-0.4%) — uma
  razão de ~20-70x. Confirma a hipótese estrutural: regressão isotônica é uma função-degrau
  monotônica que resolve por blocos por construção, não o modelo (LightGBM) sendo
  degenerado — a calibração é quem colapsa, não o classificador de base.
- **Correção implementada, não só registrada**: como `entry_threshold`/`exit_threshold` só
  precisam de ordenação (são percentis), e a isotônica preserva ordem mas destrói
  granularidade, ranquear sobre o score cru remove a banda degenerada sem precisar
  entender/consertar a calibração em si.
  - `TrainedModel.predict_raw`/`predict_raw_batch` (`model/training.py`, novo): saída do
    LightGBM antes da isotônica.
  - `choose_thresholds` passou a ranquear sobre `predict_raw_batch`, não mais
    `predict_proba_batch`.
  - `ModelStrategy.on_features`/`should_exit` (`model/strategy.py`) comparam contra os
    thresholds via `predict_raw`, nunca mais `predict_proba`. `TradeSignal.confidence`
    continua vindo de `predict_proba` (calibrado) — só a decisão de entrada/saída muda de
    espaço, a leitura humana ("score 0.7 ≈ 70% de acerto") continua igual.
  - `brier_score` continua sobre `predict_proba_batch` — é a métrica de qualidade de
    calibração, deveria mesmo medir o calibrado.
  - Testes novos: `test_choose_thresholds_ranks_on_raw_score_not_calibrated` (regressão via
    stub sem `predict_proba_batch` — quebraria com `AttributeError` se o código voltasse a
    usar o calibrado), `test_predict_raw_bypasses_calibration`,
    `test_predict_raw_batch_has_at_least_as_many_distinct_values_as_calibrated`,
    `test_on_features_decides_on_raw_score_reports_calibrated_confidence`,
    `test_should_exit_decides_on_raw_score_not_calibrated`. Suíte completa: 349 passed (5
    novos).
  - `specs/04-modelo-ml-e-scoring.md` documenta a mudança e o raciocínio de por que o
    *conjunto* de linhas selecionado por "top 20% do score" não muda (percentil preserva
    ordem) — só a fronteira deixa de colidir nos empates que o calibrado cria.

## Duas notas do usuário sobre a leitura estatística do fold 2, registradas sem ação de código

- **Piso de custo, achado distinto de "sinal negativo"**: no fold 2 (único com amostra
  confiável), bruto médio por trade = -2.32, taxa média por trade = 3.92 — mesmo que o
  sinal estivesse com o lado certo (bruto invertido para +2.32), não pagaria a taxa. O
  movimento capturado por trade é estruturalmente pequeno demais para o custo de round-trip
  neste horizonte/parametrização — problema de desenho (permanência/movimento capturado),
  não só de qualidade do modelo. Entra como restrição de desenho na task #191, não corrigido
  nesta rodada (depende de decidir o que muda: horizonte, `move_threshold_pct`, ou ambos).
  A checagem foi replicada nos outros folds pós-correção do threshold — ver seção de
  revalidação abaixo.
- **Ressalva sobre o t=-12.65 do fold 2**: decisivo sobre *este fold* (67 trades, mesmo
  modelo, mesma janela, mesmo regime de mercado — mas não 67 observações independentes;
  amostra efetiva de episódios de mercado é bem menor). "Perdeu neste fold" é conclusão
  sólida; "perde em geral" não está demonstrado por este número sozinho. Registrado
  explicitamente para não deixar o t-stat carregar mais certeza do que sustenta.

## Revalidação empírica pós-correção do score cru (janela fixa) — resultado: PIOROU

Comparação, mesma janela fixa, mesmos 5 folds, único fator variando (thresholds no espaço
calibrado vs. cru):

| | pré-fix (calibrado) | pós-fix (cru, percentis 80/50 inalterados) |
|---|---|---|
| trades totais (5 folds) | 113 | **362** |
| pnl líquido total | -765.92 | **-2152.13** |
| gap entry−exit (ordem de grandeza) | ~1e-3 | **~1e-5** |
| razão stdev(score)/gap | 0.28 a 3.96 | **111 a 3187** |

O mecanismo diagnosticado (isotônica colapsa em poucos patamares) estava correto e ficou
confirmado de novo (score cru: 259-561 valores distintos; calibrado: 8-31 — mesma proporção
da terceira rodada). Mas resolver a granularidade não resolveu a banda entry/exit — piorou:
o score cru de um classificador de evento raro (label_rate 0.5-6%) fica concentrado perto de
um valor baixo para a maioria das barras, com separação real só numa cauda superior fina.
Os percentis 50 e 80 caem os dois dentro dessa massa concentrada — degenerescência por
concentração de classe, mecanismo diferente do isotônico, mesmo sintoma. **Mecanismo
correto, insuficiente sozinho, não validado como melhoria** (nas palavras do usuário) — o
commit `deaff5f` fica (o ranqueamento em score cru é pré-requisito necessário para qualquer
política de threshold funcionar — 8-31 valores não dão resolução nenhuma), mas não foi
suficiente e a política de threshold em cima dele precisa mudar.

## Critério de sucesso, escrito antes de rodar a próxima tentativa

Instrução explícita do usuário: "escreva o critério de sucesso antes de rodar... Sem isso, a
próxima rodada vira a mesma armadilha — a gente olha o resultado e constrói a explicação
depois." Critérios fixados **antes** da revalidação da quinta rodada (abaixo):

1. Trades totais (5 folds) não pode aumentar em relação ao baseline pré-fix (113) — idealmente
   cai bem abaixo, refletindo seletividade ancorada no label_rate real (0.5-6%), não um
   percentil fixo arbitrário.
2. Bruto médio por trade deve exceder a taxa média por trade (~3.9-4.0) em todo fold com
   amostra razoável (n≥20) — critério direto do achado do fold 2 (piso de custo).
3. Pnl líquido total não pode ficar pior que o baseline pré-fix (-765.92) — não precisa
   vencer o flat/buy&hold ainda (placeholder), só não regredir do que já existia antes desta
   rodada de correções.
4. Nenhum fold pode ter `exit_threshold` colapsado num valor absurdo (ex.: 0.0 cravado em
   todo fold) sem isso ser reportado explicitamente como achado, não aceito em silêncio.

## Quinta rodada: piso de entry ancorado no label_rate + saída por histerese de ruído

Duas correções de desenho sobre a causa raiz real (percentil fixo é ferramenta errada para
evento raro), escolhendo a versão mais simples que o usuário ofereceu como primeiro passo
(não o sweep completo de valor esperado — registrado como possível refinamento mais forte,
não implementado nesta rodada, para não expandir o raio de mudança em cima de um resultado
que ainda precisa se provar):

- **Entrada**: `choose_thresholds` (`model/training.py`) ganha um piso — o percentil efetivo
  usado nunca é mais permissivo que `100 - label_rate_floor_multiple × label_rate_pct` do
  próprio fold de calibração (`label_rate_floor_multiple` default 3.0). Um `entry_percentile`
  chamado com 80 (ou qualquer valor mais permissivo que o piso) é automaticamente apertado;
  um caller que já pede algo mais seletivo (ex.: os presets 95-99.5 de `risk_profiles.py`)
  não é afetado. Preserva 100% das assinaturas externas existentes (`evaluate_config`,
  `sweep_thresholds.py`, `risk_profiles.py`, o schema de ferramenta do loop agêntico em
  `learning_engine/tools.py`) — só muda o piso interno, não o parâmetro que os chamadores já
  passam.
- **Saída**: `exit_percentile` removido de `choose_thresholds` — substituído por
  `exit_hysteresis_stdevs` (default 3.0). `exit_threshold = max(0.0, entry_threshold -
  exit_hysteresis_stdevs × stdev(diff(score cru na fatia de calibração)))`. A saída passa a
  ser expressa em unidades do próprio ruído bar-a-bar já medido, não numa posição arbitrária
  na distribuição — não pode disparar por ruído por construção, independente do formato da
  distribuição do score. `scripts/train_model.py` e `scripts/run_benchmark_comparison.py`
  trocam `--exit-percentile` por `--exit-hysteresis-stdevs`/`--label-rate-floor-multiple`.

Follow-ups explicitamente registrados, não implementados: sweep completo de threshold por
valor esperado líquido (a versão "correta" mais forte, considerada mas adiada); orçamento
de trades/mês derivado de custo como restrição explícita (a inversão threshold←orçamento,
capturada em espírito pelo piso de label_rate, mas não como mecanismo separado); saída por
barreira temporal do horizonte do label como alternativa à histerese (exigiria estender o
protocolo `Strategy` com estado de duração de posição — mudança maior, fora de escopo aqui).

## Resultado do teste de nulidade na janela fixa (pré-correção de threshold) — e uma leitura invertida corrigida no mesmo dia

Rodou (código pré-quarta-rodada, mas isso não invalida o resultado — `shuffle_labels` só
mexe no label, nunca nas features, então o resultado não depende da política de
threshold):

```
Real: mean_profit_factor=0.250 (0/5 folds vencidos)
Distribuição nula (30 permutações): min=0.001 mediana=0.025 max=0.169
p-valor empírico: 0.032
```

0 das 30 permutações alcançou o resultado real (o p mínimo que N=30 permite). **Minha
primeira leitura deste resultado estava invertida** — tratei p<0.05 como alarme de
vazamento ("ATENÇÃO... isso não é sorte, é evidência de vazamento no harness"). Está
errado, e o usuário corrigiu: a hipótese nula do teste é "as features não carregam
informação real sobre o label". As permutações são as execuções sem informação real, por
construção (destroem a correspondência feature→label); o real superando todas elas é
exatamente a cara de "rejeita a hipótese nula" — **evidência de sinal preditivo genuíno,
o resultado desejado, não um alarme**. Corrigido nos docstrings de
`run_nullity_test`/`NullityTestResult`/`evaluate_config`, no `scripts/run_nullity_test.py`
(mensagem de saída) e em `specs/07-backtesting-e-validacao.md`.

Ressalva que sobrevive à correção, agora enquadrada como precaução e não como acusação: o
padrão "real muito acima do nulo" também é compatível com vazamento de lookahead na
construção de features/labels (embaralhar o label não elimina esse tipo de vazamento — só
muda qual futuro o label aponta). Por isso, mesmo sendo a leitura positiva, vale conferir
o invariante anti-leakage antes de comemorar — não porque o teste "acusou" (ele não
acusa), mas porque ele não distingue as duas fontes sozinho.

**Nota técnica do usuário, também registrada**: a mediana da nuvem nula (0,025) é baixa
demais para ser só "entrada aleatória com custo" — entrada aleatória com custo dá PF ruim,
não quase zero. Isso é evidência (pelo lado oposto) de que o mecanismo de saída
estrangula qualquer trade, real ou permutado, igualmente — os dois braços do teste estão
sob o mesmo estrangulamento que a quinta rodada tentou consertar. Vale re-rodar depois da
correção de threshold, para que a distância real-vs-nulo meça sinal, não sobrevivência.

## Auditoria de purga/embargo — vazamento real confirmado por inspeção de código

Prioridade levantada pelo usuário sobre o resultado acima: "real muito acima do nulo" é
compatível tanto com sinal genuíno quanto com vazamento de lookahead — e há um suspeito
concreto nunca verificado nesta investigação, o mesmo padrão clássico de walk-forward com
label sobreposto. Confirmado por leitura direta do código, não por medição:
`model/training.py::walk_forward_splits` (antes desta rodada) fazia
`train = rows[:train_end]`, `test = rows[train_end:test_end]` — limite exato, sem gap. O
label de uma linha (`model/dataset.py::_triple_barrier_label`) é calculado olhando até
`horizon_bars` (15, no default) candles à frente da própria linha. Logo, as últimas 15
linhas de `train_rows` em todo fold tinham label calculado usando preço que só existe
dentro do `test_rows` imediatamente seguinte — vazamento real, não hipotético.

**Correção**: `walk_forward_splits` ganhou `purge_bars` — remove as últimas `purge_bars`
linhas de `train_rows` antes de devolvê-la. Sem *embargo* correspondente do lado do teste
(o label de `test_rows` nunca é consultado — o backtest roda sobre preço real via
`BacktestEngine`, não sobre `DatasetRow.label`). Threadeado em todo chamador:
`evaluate_config` (`model/evaluation.py`), `scripts/train_model.py`,
`scripts/run_benchmark_comparison.py`, `model/importance.py` — todos passam
`purge_bars=target_config.horizon_bars`. Testes novos:
`test_walk_forward_splits_purges_trailing_train_rows_when_requested`,
`test_walk_forward_splits_purge_never_produces_negative_length_train`. `specs/04` documenta
o achado e a correção. Suíte completa: 353 passed.

Consequência prática: **todo resultado empírico desta investigação até aqui (benchmark,
diagnósticos, o p=0,032 acima) foi produzido sem a purga** — não invalida os achados sobre
mecanismo (banda de threshold, exit por ruído, piso de custo, degenerescência de score),
que são sobre a política de decisão e não dependem da purga, mas o teste de nulidade
especificamente precisa ser relido depois da correção, já que é exatamente o que a purga
poderia estar contaminando.

## Pendente

- Re-rodar o teste de nulidade com a purga aplicada — é a leitura que decide se o p=0,032
  acima é sinal genuíno ou vazamento de lookahead.
- Revalidação empírica da quinta rodada (threshold) contra os 4 critérios escritos acima —
  precisa rodar de novo com a purga também aplicada (fold splits mudam).
- Restrição de desenho identificada no fold 2 (piso de custo vs. movimento capturado) —
  critério #2 acima ataca isso diretamente; resultado a confirmar.
- Sweep de valor esperado líquido (versão mais forte da correção de entrada) — registrado,
  não implementado.
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
- Quarta rodada aprovada por: Brian, a partir da própria hipótese estrutural sobre por que
  isotônica colapsa em poucos patamares ("regressão isotônica... resolve por blocos e
  produz poucos patamares distintos por construção... É exatamente a faixa que você
  mediu") e da correção proposta como "vale mais que a guarda contra banda zero... isso
  remove a causa do sintoma". Implementação feita após confirmar a hipótese por medição
  (raw vs. calibrado), não antes — mesma disciplina de medir-antes-de-implementar do resto
  desta investigação. Duas notas adicionais do usuário (piso de custo do fold 2; ressalva
  de não-independência por trás do t=-12.65) registradas como achados/restrições, sem ação
  de código nesta rodada por não terem correção imediata associada.
- Sexta rodada (correção da leitura invertida do teste de nulidade + auditoria de
  purga/embargo): correção de leitura apontada por Brian ao ler o resultado do p=0,032 —
  "esse resultado não é o achado de vazamento — é o resultado limpo... rejeita a hipótese
  nula... a conclusão é: as features carregam sinal real". Prioridade de investigação
  (purga antes de qualquer outra coisa) também definida por ele: "auditoria de
  purga/embargo primeiro, porque é barata e é a única coisa que poderia invalidar
  retroativamente tudo o que vier depois". A purga em si (limite exato sem gap em
  `walk_forward_splits`, vazamento das últimas `horizon_bars` linhas de treino) foi
  confirmada por leitura direta do código nesta sessão, não pré-existente na conversa —
  a hipótese do usuário apontou exatamente onde olhar.
