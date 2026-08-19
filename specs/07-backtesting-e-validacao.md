# 07 — Backtesting e Validação

## Objetivo

Garantir que qualquer resultado promissor observado em simulação tenha chance
real de se repetir em produção — o ponto onde a maioria dos projetos de trading
algorítmico falha silenciosamente.

## Requisitos da simulação

1. **Event-driven, não vetorizada.** A simulação processa eventos na ordem
   cronológica exata em que ocorreriam, respeitando a mesma lógica de
   decisão/execução usada em produção — não um cálculo vetorizado sobre a
   série histórica inteira de uma vez, que esconde efeitos de ordem e timing.
2. **Mesmo código de features e de modelo usado em produção** (ver
   `03-motor-de-features.md`) — nunca uma reimplementação separada "só para
   backtest".
3. **Custos realistas incluídos sempre:**
   - Taxas maker/taker da Binance.
   - Slippage (nunca assumir preço de execução perfeito ao preço do sinal).
   - Latência de rede simulada entre sinal e execução.
4. **Validação walk-forward:** treino em uma janela, teste na janela
   imediatamente seguinte (nunca vista no treino), avança a janela, repete.
   Nunca validação cruzada aleatória — vaza informação do futuro para o passado
   e infla resultado de forma enganosa.

## Critérios de promoção de modelo/estratégia

Uma nova versão (de modelo ou de parâmetro de decisão) só é promovida a
candidata de produção se, no backtest out-of-sample walk-forward:

- **Ter expectância líquida positiva por si só** (profit factor ≥ 1, líquido
  de taxas e slippage) — gate absoluto, independente de como o baseline
  performou. "Superar o baseline" não é suficiente sozinho: um candidato
  pode ser "menos ruim" que um baseline com expectância estruturalmente
  quebrada e ainda assim perder dinheiro líquido (ver limitação conhecida
  abaixo, adicionada em 2026-07-31 após achado real nesse sentido). Sem esse
  gate, o critério seguinte (superar o baseline) é necessário mas não
  suficiente.
  - **Ressalva sobre amostra pequena (2026-07-31):** `profit_factor ≥ 1.0` é
    o breakeven exato — um candidato com PF = 1.02 pode ser apenas ruído
    estatístico se o número de trades no fold for pequeno (as janelas reais
    testadas nesta investigação tinham 65-77 trades em 7 dias, e mesmo
    nessa ordem de grandeza um PF perto de 1.0 não é fortemente conclusivo).
    Este gate garante *direção* (candidato não é um perdedor líquido óbvio),
    não *significância* — quem dá a segunda parte é `decide_promotion`
    exigir vitória em **todos** os folds do walk-forward (não um resultado
    agregado isolado) e o piso mínimo de amostra por leitura, mesmo
    princípio do piso de ≥10 trades usado para validação ao vivo na Fase 4b
    (`11-roadmap-e-fases.md`,
    `changes/2026-07-30-criterios-sucesso-periodo-validacao.md`). Um PF
    marginal (perto de 1.0) que só passa em folds com poucas trades deve ser
    tratado com a mesma cautela que um resultado mensal com poucos trades ao
    vivo — não motivo para promoção automática sem revisão humana adicional.
- Superar a versão em produção nas métricas definidas como primárias (ex.:
  profit factor e drawdown máximo — a lista exata de métricas e limiares é
  definida em `changes/` e versionada).
- Não apresentar degradação de performance concentrada em um único regime de
  mercado (checar performance segmentada por volatilidade/tendência, não só
  agregada).
- Passar por um período mínimo de validação em testnet (ver
  `06-camada-de-execucao.md`) antes de qualquer capital real.

## Sinais de alerta de overfitting (a checar sempre)

- Performance "perfeita" ou muito acima de qualquer baseline simples.
- Sensibilidade alta a pequenas mudanças de hiperparâmetro (indica ajuste ao
  ruído do dataset específico, não a um padrão real).
- Divergência entre performance em backtest e em paper trading/testnet ao
  vivo — quando isso ocorre, a causa é investigada (bug de leakage, mudança de
  regime de mercado, ou diferença sutil entre implementação de backtest e
  produção) antes de qualquer nova promoção.

## Limitação conhecida: baseline placeholder estruturalmente fraco (2026-07-31)

Investigação de um backtest real (`BTCUSDT_1m_7d`, 65 trades, 0% win rate,
100% das saídas via `signal_exit`) confirmou que a regra-placeholder de
`backtesting/strategy.py` (`RsiBollingerPlaceholderStrategy`) **perde
estruturalmente**, não por bug de direção/custo/timing (essas hipóteses
foram checadas e descartadas — ver `changes/2026-07-31-stop-loss-intrabar-backtest-engine.md`
para o único bug real encontrado nessa investigação, que não é a causa
disto). A causa: a saída por "RSI voltou à linha média (50)" fecha a posição
assim que o momentum recupera, o que tipicamente acontece **antes** do preço
se mover o suficiente para cobrir o custo de round-trip (~0.3% = 0.2% de
taxa + ~0.1% de slippage nos dois lados). Reproduzido em 3 janelas históricas
distintas e não sobrepostas (30-37, 60-67 e 90-97 dias atrás): taxa de
acerto líquida entre 0% e 9%, mesmo em uma janela onde o buy-and-hold do
período foi levemente positivo — ou seja, não é característica de um
regime de mercado específico (tendência de baixa), é o próprio desenho da
regra de saída.

**Implicação para `specs/11-roadmap-e-fases.md`, critério de saída da Fase
2:** "superar o baseline ingênuo" é um critério fraco enquanto esse baseline
tiver expectância estruturalmente negativa — um modelo candidato pode vencer
essa régua só por ser "menos ruim", sem ter expectância líquida positiva de
verdade. Ver critério adicional de expectância líquida positiva,
proposto em `changes/2026-07-31-criterio-promocao-expectancia-positiva.md`.

## Limitação conhecida: testnet não cobra taxa real — ponto cego econômico da validação ao vivo (2026-08-10)

Primeira semana de operação real em testnet (Fase 4) gerou 22 trades reais
do baseline placeholder, todos via `signal_exit` (nenhum via `stop_loss`).
Números brutos, como persistidos (`trades.pnl`, sem custo): **77% de
acerto (17/22), PnL total +$1.87** — aparentemente contradizendo o achado
acima (expectância estruturalmente negativa em backtest).

Investigação: toda ordem preenchida na conta de testnet retorna
`commission: "0.00000000"` no `raw_response` da Binance, sem exceção —
**a testnet não cobra taxa real nenhuma**, ao contrário do
`backtesting.costs.FeeModel` (`taker_fee_pct=0.001`, 0.1% por lado) usado
em todo backtest. Recalculando o PnL desses mesmos 22 trades aplicando essa
mesma taxa retroativamente: **5% de acerto (1/22), PnL total -$6.93** — bate
exatamente com o padrão já documentado acima (movimentos pequenos demais
para cobrir custo de round-trip real).

- **Isto não é uma divergência entre backtest e produção** no sentido de
  "um dos dois está errado" — é uma diferença real e esperada de ambiente.
  O motor de backtest modela custo corretamente; a conta de testnet da
  Binance, coerente com ser dinheiro fictício, simplesmente não cobra nada.
- **Implicação estrutural para `CLAUDE.md` regra 1** ("testnet primeiro,
  sempre"): testnet valida corretitude **operacional** (o sistema coloca
  ordem certo, gerencia estado, reconcilia corretamente — exatamente o que
  a Fase 4 desta semana testou, incluindo o incidente de
  `changes/2026-08-09-posicao-travada-cancel-order-sem-tratamento.md`), mas
  **não valida lucratividade real** — qualquer leitura de PnL/win rate
  direto do testnet precisa ser recalculada com um custo realista
  (`FeeModel` do próprio backtest) antes de significar algo economicamente,
  do contrário superestima performance de forma sistemática e na direção
  errada (o baseline placeholder parece lucrativo quando na verdade não é).
- **Não é ação a tomar agora** — `fees_paid=0.0` já é uma lacuna conhecida
  e documentada no código (`execution/orchestrator.py::_finalize_exit`);
  esta seção só registra que, neste ambiente específico (testnet), esse
  valor é literalmente correto (a taxa real é zero), não uma lacuna de
  instrumentação — a lacuna real é não recalcular/exibir o PnL líquido de
  um custo realista em algum lugar (dashboard ou relatório), para quem olhar
  os números de testnet não precisar refazer essa conta manualmente.

## Métricas obrigatórias no relatório de backtest

- Equity curve completa (não só retorno final).
- Win rate, profit factor, drawdown máximo e duração do drawdown.
- Distribuição de resultados por horário/dia da semana.
- Número de trades (amostra pequena não sustenta conclusão estatística —
  limite mínimo de trades para considerar um resultado significativo é
  definido em `changes/`).

## Comparação contra benchmarks triviais (2026-08-19)

Superar `RsiBollingerPlaceholderStrategy` (o baseline usado em
`decide_promotion`) é necessário mas não suficiente — esse baseline já foi
encontrado estruturalmente fraco (ver limitação acima, 2026-07-31), então um
candidato pode vencê-lo e ainda assim não ter edge real. `scripts/run_benchmark_comparison.py`
roda a mesma pipeline walk-forward de `train_model.py` (mesmo modelo, mesmo
filtro de regime, mesmos folds) e compara o candidato, fold a fold — não só
no agregado, pela mesma razão de "Sinais de alerta de overfitting" acima —
contra dois benchmarks triviais:

- **Buy-and-hold**: `backtesting/metrics.py::buy_and_hold_equity_curve` —
  mark-to-market de uma compra única no primeiro candle do fold, mantida até
  o fim.
- **Flat**: `backtesting/metrics.py::flat_equity_curve` — capital parado, a
  régua de "não fazer nada" (nenhuma estratégia com custo de operação deveria
  perder para simplesmente não operar).

A comparação é ajustada a risco, não só retorno bruto: `BacktestMetrics`
ganhou os campos `total_return_pct`, `volatility_pct`,
`return_over_drawdown` (razão tipo Calmar), `return_over_volatility` (razão
tipo Sharpe sem taxa livre de risco — válida para comparar candidato vs.
benchmark no mesmo período, não como número absoluto isolado) e
`exposure_pct` (fração do período com posição aberta). Os três (candidato,
buy-and-hold, flat) passam pela mesma função `compute_metrics`, para que a
comparação seja de fato maçã-com-maçã e não três fórmulas diferentes
coincidentemente parecidas.

Duas ressalvas que `scripts/run_benchmark_comparison.py` imprime
explicitamente no relatório (texto e JSON), em vez de deixar implícitas
(2026-08-19):

- **Assimetria de custo**: buy-and-hold entra e sai de graça nesta
  comparação (um único mark-to-market, não uma ordem simulada); o candidato
  paga taxa/slippage reais em cada trade (`backtesting/costs.py`). Isso
  enviesa a comparação *contra* o candidato — o lado seguro — mas precisa
  ficar visível, não silenciosamente favorecendo o buy-and-hold.
- **Exposição**: buy-and-hold fica 100% exposto por definição, flat 0%, e o
  candidato o que `exposure_pct` calcular (tipicamente bem abaixo de 100%)
  — parte de qualquer diferença de retorno/risco entre eles se explica por
  quanto tempo cada um esteve de fato no mercado, não só por habilidade da
  estratégia.
- `return_over_volatility` é calculado sobre volatilidade por barra (do
  candle usado, ex. 1m), **não anualizada** — não é comparável a um Sharpe
  publicado sem essa conversão. Rotulado explicitamente na saída do script
  para não ser confundido com um número anualizado.

`BacktestMetrics.equity_curve` também deixou de ser descartado — persistido
no próprio campo, reaproveitado por `FoldSummary.equity_curve`
(`model/evaluation.py`) abaixo.

## Teste de nulidade — labels embaralhados, N permutações (2026-08-19)

Complementa o benchmark acima numa direção diferente: em vez de perguntar
"o candidato bate um benchmark ingênuo", pergunta "o harness em si vaza
informação". `model/evaluation.py::evaluate_config` ganhou
`shuffle_labels`/`shuffle_seed` — quando ativado, roda exatamente a mesma
pipeline (mesmos eventos, mesmos folds, mesmo treino/calibração/backtest),
substituindo os labels reais (construídos por triple-barrier em
`model/dataset.py`) por uma permutação de si mesmos, **depois** de
calculados — preserva a taxa de label exata, só quebra a correspondência
feature→label linha a linha.

**Uma semente só não é teste de nulidade — é um sorteio único.** Uma
permutação isolada não distingue "harness limpo" de "essa permutação em
particular calhou de parecer boa/ruim". `model/evaluation.py::run_nullity_test`
roda a avaliação real uma vez e N permutações (`n_permutations`, sementes
`base_seed..base_seed+N-1`), monta a distribuição nula de
`mean_profit_factor` e reporta onde o resultado real cai nela como um
**p-valor empírico**: `(nº de permutações que igualaram ou superaram o real
+ 1) / (N + 1)` — a correção `+1/+1` padrão de teste de permutação (Davison
& Hinkley) evita declarar um p=0.0 exato só porque N é finito.
`scripts/run_nullity_test.py` expõe isso via CLI (`--n-permutations`,
default 30).

Efeito colateral: essa distribuição nula é uma aproximação barata do que o
Deflated Sharpe Ratio (DSR, item ainda pendente na fila estatística) vai
responder depois — "quão bom é esse número comparado ao que o acaso produz
neste pipeline, com estes dados, com este número de folds" — sem o custo de
implementar o DSR ainda. Não o substitui, mas cobre parte da mesma pergunta
sem custo adicional.

**Interpretação (corrigida no mesmo dia em que foi implementada, depois de
uma primeira versão invertida — ver `changes/2026-08-19-benchmark-e-teste-
de-nulidade.md`).** A hipótese nula do teste é "as features não carregam
informação real sobre o label". **Um p-valor baixo (real muito acima da
distribuição nula) rejeita essa hipótese — é evidência de sinal preditivo
genuíno, o resultado desejado, não um alarme.** As permutações são as
execuções sem informação real, por construção; o real superá-las é
exatamente a cara de "as features são informativas".

Ressalva de precaução, não alarme: esse padrão (real muito acima do nulo)
também é compatível com vazamento de lookahead na construção de
features/labels — se uma feature ou o label enxergar informação futura além
de `knowledge_ts`, embaralhar o label não elimina esse vazamento (só muda
qual futuro o label aponta), e tanto as permutações quanto o real ficariam
afetados de formas diferentes. Por isso um p-valor baixo justifica conferir
o invariante anti-leakage (`03-motor-de-features.md`) e a purga na fronteira
do walk-forward (`model/training.py::walk_forward_splits`, `purge_bars` —
ver seção "Janela de dados fixa" abaixo... na verdade ver a seção de purga
em `04-modelo-ml-e-scoring.md`) — não porque o teste acusou algo, mas porque
ele não distingue sinal real de sinal vazado sozinho.

Um p-valor alto (real indistinguível do nulo) **não é conclusivamente
"sem sinal"** por si só: se algum outro mecanismo destrói a performance de
forma igual independente da qualidade do label (ex.: uma regra de saída que
dispara por ruído do score antes de qualquer trade se desenvolver — achado
real de 2026-08-19), tanto o real quanto as permutações ficam igualmente
estrangulados e o teste perde poder de detectar sinal genuíno por baixo
disso. Uma mediana da distribuição nula anormalmente baixa (bem abaixo do
que entradas aleatórias líquidas de custo produziriam) é sintoma disso —
vale rodar de novo depois de corrigir esse mecanismo, para que a distância
real-vs-nulo meça sinal, não sobrevivência ao mesmo estrangulamento.

## Série de retorno por fold, persistida (2026-08-19)

`FoldSummary` (`model/evaluation.py`) ganhou `equity_curve` — a série
(timestamp, equity) do fold, já computada internamente por `compute_metrics`
para derivar `volatility_pct` e antes descartada assim que o escalar saía.
Não é mudança de comportamento de nenhum critério de promoção — é parar de
jogar fora um dado que já estava em memória. Motivação: DSR e PBO/CSCV
(itens pendentes da fila estatística) precisam da série de retornos real por
fold, não só do profit factor agregado — sem isso, implementá-los mais
tarde exigiria re-rodar todo backtest de novo só para recuperar o dado.

## Janela de dados fixa para runs comparáveis (2026-08-19)

`--days N` relativo a `time.time()` (o padrão em praticamente todo script de
`scripts/`) não é reprodutível: dois runs do mesmo código minutos apart
buscam janelas de klines diferentes, o que desloca `len(rows)` e, com ele,
todo limite de fold do walk-forward — confirmado empiricamente
(`changes/2026-08-19-benchmark-e-teste-de-nulidade.md`, terceira rodada): o
mesmo fold, mesmo código, produziu 28 trades numa execução e 9 em outra,
~20 minutos depois. Resultados de janela relativa não são apenas
"não-comparáveis" entre execuções — são **inválidos** como leitura de
desempenho, porque não se sabe se uma diferença observada veio de uma
mudança real ou só da janela ter mudado.

`scripts/run_benchmark_comparison.py` e `scripts/run_nullity_test.py`
aceitam `--start-ms`/`--end-ms` para fixar a janela explicitamente
(mantêm o comportamento relativo por `--days` se omitidos, e sempre
imprimem a janela resolvida). Qualquer comparação entre execuções — antes
e depois de uma mudança, candidato vs. benchmark, leitura A vs. leitura B
— exige a mesma janela fixa nos dois lados. O mesmo padrão existe em outros
scripts do projeto (`train_model.py`, `sweep_thresholds.py`,
`backtesting/runner.py`, `run_agentic_learning.py`, entre outros) e não foi
corrigido em massa — resolver caso a caso quando cada um precisar de
reprodutibilidade.

## Relação com o dashboard e o motor de aprendizado

- Todo relatório de backtest gerado (seja de validação de mudança, seja
  automático no ciclo de retreino) é persistido e fica acessível na view
  "Modelo" do dashboard (`08-dashboard-e-visualizacao.md`).
- Divergência entre backtest e produção real é um dos inputs centrais do motor
  de aprendizado contínuo (`09-aprendizado-continuo.md`).
