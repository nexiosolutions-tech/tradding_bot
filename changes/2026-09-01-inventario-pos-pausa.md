# 2026-09-01 — Inventário do bot de trading: estado real após a pausa

## Contexto

Rodada de medição e leitura de código, sem nenhuma mudança — três decisões (ambiente do
aggTrade, região das capturas, dimensionamento do walk-forward) dependem dos números
levantados aqui. Nada foi movido, corrigido, reiniciado ou ajustado.

---

## 1. O que foi capturado, por tabela e por ambiente

**`order_book_snapshots`** — consulta direta ao Postgres de produção:

| Ambiente | Linhas | Primeira | Última |
|---|---|---|---|
| mainnet | 19.496 | 2026-08-18 20:05:32 | 2026-09-01 12:33:12 |
| testnet | 4.257 | 2026-08-15 21:30:40 | 2026-08-18 20:05:00 |

Transição testnet→mainnet em 18/08 é contígua (a última linha testnet e a primeira
mainnet diferem em 32 segundos) — sem sobreposição, sem buraco na troca. Contagem diária
de mainnet, 19/08 a 31/08: 1420-1432 linhas/dia, estável (18/08 e 01/09 são dias
parciais, início/corte da consulta) — **nenhuma lacuna, captura contínua o período
inteiro.**

**`agg_trade_buckets`** — **100% testnet, zero linhas mainnet.** 546.872 linhas, 18/08 a
01/09, contagem diária entre 8.124 (dia parcial) e 47.687, sem dia zerado. Confirmado no
código (`run_aggtrade_capture.py:53`): `USE_TESTNET = True`, hardcoded, com o motivo já
documentado no próprio arquivo — geobloqueio de `us-east4` (onde o serviço roda). Ver
Seção 3 abaixo: esse motivo deixou de ser válido.

**Correção (2026-09-01, mesma rodada — apontada por Brian): a frase original desta
seção sobre backfill ("Binance não expõe aggTrade passado além da janela recente da
REST") estava errada, confundindo dois endpoints diferentes.** `/api/v3/aggTrades` (a
REST ao vivo, usada por `measure_aggtrade_rate.py` e pelo polling) de fato só devolve
os últimos ~1000 registros — mas o **arquivo histórico** (`data.binance.vision`, bucket
`data/spot/daily/aggTrades/BTCUSDT/`, já achado numa rodada anterior — `changes/2026-08-
18-captura-aggtrade-fluxo-ordens.md`) é outra coisa inteiramente, sem essa limitação.
Reconferido agora, por download direto (não pela página de listagem, que é uma UI
HTML e não reflete o conteúdo real do bucket): `BTCUSDT-aggTrades-2026-08-31.zip`
(17,8MB), `-2026-08-30.zip` (10,9MB) e `-2026-08-18.zip` (6,2MB) — os três `200`, os
três com conteúdo real, cobrindo exatamente a janela inteira que hoje só existe em
testnet. **As semanas de captura testnet são recuperáveis como dado mainnet real, via
download do arquivo — não é backfill parcial, é a série inteira.** Isso muda a resposta
da Pergunta 1 no fechamento deste documento; ver a seção "As três perguntas" abaixo,
também corrigida.

**Kline/candle**: não existe tabela dedicada — `backend/src/tradingbot/persistence/
models.py` não tem `Kline`/`Candle`. O treino busca klines direto da REST da Binance a
cada execução (`BinanceRestClient.fetch_klines`), nunca persiste localmente. Não há
"captura" de kline para inventariar; ver Seção 4.

**Backfill via `fromId` (agg_trade)**: o mecanismo existe e está ativo
(`run_aggtrade_capture.py::_backfill_gap`, acionado quando o stream reconecta com
`expected_from_id` no payload) — usa o mesmo `AggTradeAggregator` do caminho ao vivo
(ver Seção 5). Não há coluna de `agg_trade_id` em `agg_trade_buckets` (só volume/
contagem agregados por segundo), então não dá para checar buraco de ID diretamente na
tabela — precisaria dos logs do serviço, que não foram varridos nesta rodada (não
pedido explicitamente na Seção 1, e os logs do Railway não retêm o período inteiro).

**Resposta à pergunta da Seção 1**: `order_book_snapshots` é dado mainnet real e
utilizável (2 semanas contínuas). `agg_trade_buckets` é 100% testnet — sintético,
descartável para qualquer feature de fluxo de ordens real, mas útil para validar o
pipeline de captura em si.

---

## 2. Resultado do `measure-aggtrade-rate`

Rodado agora, sobre tudo que o serviço acumulou desde antes da pausa:

```
Símbolo: BTCUSDT
Amostras: 37.503, cobrindo 321,6h (~13,4 dias)
Taxa de chegada (trades/s): p50=10,5 p95=40,8 p99=89,6 pico=1.669,4
Latência da chamada (ms): p95=884
Peso usado (X-MBX-USED-WEIGHT-1M), pico observado: 168/6000 por minuto
Segundos de mercado cobertos por chamada de 1000 trades, no p99: 11,17s
Folga (cobertura / latência serial, p95): 12,6x
```

**Recomendação do script (critério de p99): folga confortável (≥3x) — polling como
fonte primária é defensável.**

**Mas o pico observado (1.669,4 trades/s) é a cauda de evento real que a amostra de 24h
original não tinha.** No pico, 1000 trades cobrem só 0,60s de mercado — contra 884ms de
latência de chamada no p95, isso é **folga de 0,68x, abaixo de 1x**: nesse segundo
específico, uma chamada não termina antes que o próximo lote de 1000 trades já tenha
saído do outro lado. O script não erra ao recomendar com base no p99 (a própria
docstring já registra que p99 é sempre um piso do pico, nunca o pico em si — a margem
de 3x existe pra cobrir exatamente essa lacuna); o que muda com mais amostra é que agora
dá pra ver o tamanho real da lacuna que a margem estava cobrindo às cegas. Decisão de
desenho (polling puro vs. arquivo diário + polling na cauda) não tomada aqui — os dois
números, p99 e pico, estão registrados para quem decidir.

---

## 3. Estado dos serviços e regiões

| Serviço | Região | Endpoint hoje |
|---|---|---|
| `depth-capture` | `us-east4-eqdc4a` | REST `data-api.binance.vision`, mainnet |
| `aggtrade-capture` | `us-east4-eqdc4a` | WS `stream.binance.com`, **testnet** (`USE_TESTNET=True`) |
| `measure-aggtrade-rate` | `us-east4-eqdc4a` | REST `data-api.binance.vision`, mainnet |
| `learning-daily-cron` | `us-east4-eqdc4a` | cron diário 03:00 UTC |
| `tradding_bot` | `europe-west4-drams3a` | execução real (testnet, `BINANCE_TESTNET`) |

**Teste pedido, de dentro de um container em `europe-west4` (via `tradding_bot`):**

```
api.binance.com/api/v3/ping   -> HTTP 200
api.binance.com/api/v3/time   -> HTTP 200, serverTime real devolvido
stream.binance.com:9443 (WS)  -> HTTP 101 Switching Protocols (handshake completo)
stream.binance.com:443  (WS)  -> HTTP 101 Switching Protocols (handshake completo)
```

**Os dois endpoints diretos respondem plenamente de `europe-west4` — REST e WebSocket,
handshake real, não só ping.** A sondagem anterior (`changes/2026-08-18-captura-
aggtrade-fluxo-ordens.md`) testou só `us-east4` e encontrou HTTP 451; nunca tinha sido
testado de onde o bot de fato roda. `USE_TESTNET = True` em `aggtrade-capture.py` cita
geobloqueio como motivo — o motivo é real para o serviço como está hoje (rodando em
`us-east4`), mas não é mais um limite físico da conta/IP: é um limite de região do
serviço.

**Heartbeats/liveness**: mecanismo existe e está ativo (`binance_aggtrade_ws.py::
_maybe_liveness_gap_event`, mesmo padrão em `binance_depth_ws.py`) — gera um evento de
log quando o stream fica em silêncio por tempo demais antes de reconectar. Não varrido
por incidente específico nesta rodada (não pedido); a continuidade dia-a-dia da Seção 1
(nenhum dia zerado em nenhuma das duas tabelas de captura) já é evidência indireta de
que nenhuma captura morreu calada — um coletor morto por dias apareceria como dias com
zero linha, e não apareceu nenhum.

---

## 4. Quanto histórico existe agora

Não há dado "acumulado" a medir — klines nunca são persistidos localmente (Seção 1). O
que existe é o que a própria Binance serve, testado agora:

```
Primeira kline 1m de BTCUSDT (startTime=0): 2017-08-17 04:00:00 UTC
Kline mais recente: agora
```

**~9 anos de histórico de 1 minuto disponíveis via REST, para o único símbolo em uso
(BTCUSDT)** — contra os 45 dias que `train_model.py`/`sweep_thresholds.py` usam hoje
por padrão (`--days 45`, `walk_forward_splits(n_splits=5)`). O limite de 45 dias/5 folds
nunca foi limite de dado disponível — é escolha de escopo, sem relação com quanto a
Binance guarda. **Não decidido aqui** se/quanto crescer — só registrado que o teto está
em anos, não em dias, para quem for decidir com o número na mão.

---

## 5. Leitura de código: pendências

**`run_agentic_learning.py` — janela ainda relativa a `time.time()`, bug não
corrigido.** Linhas 42-43:
```python
end_ms = int(time.time() * 1000)
start_ms = end_ms - args.days * 24 * 60 * 60 * 1000
```
Mesmo padrão já corrigido nos scripts de Ações (data-base fixa, não `time.time()` a
cada execução) — aqui continua relativo ao momento da chamada. Não corrigido nesta
rodada, só confirmado que segue presente.

**`experiment_log.py` — mecanismo existe, zero entradas para o domínio do bot.**
`learnings/experiments.jsonl` (o arquivo do domínio `bot`, `DOMAIN_BOT`) **não existe no
repositório** — só `learnings/experiments_acoes.jsonl` (470 bytes, módulo de Ações)
está presente. `append_experiment`/`load_experiments`/`already_tried` estão implementados
e testados (`test_experiment_log.py`), mas nunca foram exercitados de verdade para o bot
— consistente com o achado abaixo.

**`FoldSummary.equity_curve` é computada, mas não chega a lugar nenhum persistente.** O
campo existe e é preenchido (`evaluation.py:228`, "Persisted, not discarded", 2026-08-19)
— mas `learning_engine/tools.py::_evaluate_strategy_config` (a função que serializa um
resultado de `evaluate_config` para `ExperimentRecord.result_summary`, o único caminho
que escreve em `experiments.jsonl`) **não inclui `equity_curve` no dicionário
devolvido** — nem `total_pnl`, `gross_profit`, `gross_loss`, os outros três campos
adicionados na mesma data. Só `fold_index`, `profit_factor`, `num_trades`,
`max_drawdown_pct`, `won`, `reason` são serializados. `train_model.py`/
`sweep_thresholds.py` (uso manual, fora do loop agêntico) não persistem nada de
`FoldSummary` em disco — só o modelo final promovido (`save_model`). Resultado prático:
o dado que DSR/PBO precisam (spec 11) está computado em memória durante uma execução e
nunca sobrevive a ela.

**O loop agentic nunca rodou contra a API real.** Consequência direta do achado acima —
zero linhas em `experiments.jsonl` (domínio bot) significa zero ciclos completos, nunca
uma chamada real ao Anthropic. A própria docstring de `run_agentic_learning.py` já
avisava isso ("has not been exercised against the live Anthropic API... validate a real
cycle end to end before relying on it unattended") — continua verdade.

**Bucketização de `aggTrade` — compartilhada, confirmado no código.** `run_
aggtrade_capture.py` usa a mesma classe `AggTradeAggregator` nos dois caminhos: ao vivo
(linha 137, `aggregator.add(event)`) e no backfill de gap (linha 98-100,
`backfill_aggregator = AggTradeAggregator()`) — não é lógica duplicada, é a mesma classe
instanciada duas vezes. `test_aggtrade_aggregator.py` testa o comportamento da classe
(10 testes: acumulação, rollover, vwap, ts do bucket, símbolos independentes, flush) mas
não há um teste de integração dedicado comparando literalmente a saída dos dois
caminhos lado a lado — a garantia de saída idêntica vem de ser a mesma classe, não de um
teste que prove a equivalência entre os dois pontos de chamada.

---

## 6. Estado operacional do bot

**187 trades registrados**, 2026-08-01 a 2026-09-01 (hoje), todos em testnet
(`BINANCE_TESTNET`, confirmado pelos relatórios diários — "testnet não cobra taxa
real"). Cadência diária de 3 a 13 trades, sem dia zerado **exceto o hiato abaixo.**

**Circuit breaker: nunca disparou.** `circuit_breaker_events`: 0 linhas, em todo o
histórico.

**Incidente real encontrado, não visto até agora: hiato de 151,1 horas (6,3 dias) em
`engine_events`, entre 2026-08-03T20:04:44 e 2026-08-10T03:09:38.** Maior gap de toda a
série por larga margem (o segundo maior é 19,4h — ordem de grandeza diferente, não
ruído de horário de baixo movimento). O evento que encerra o hiato é `PAUSADO -> PAUSADO
("reconciliação de startup: preço de stop-loss desconhecido")`, `triggered_by_human:
false` — a assinatura de um processo que reinicia do zero e precisa redescobrir seu
próprio estado, não de uma pausa manual (que geraria `POSICAO_ABERTA -> PAUSADO` com
`triggered_by_human: true`, como aparece em todos os outros pausas registrados). Não
investigada a causa raiz nesta rodada (fora do escopo — só medição): o histórico de
deployments do Railway consultado não alcança 03-10/08 (a lista para neste projeto some
depois de ~12 dias), então não foi possível correlacionar com um deploy específico.
Fica como achado aberto, não como incidente explicado.

---

## As três perguntas

**1. O aggTrade precisa de backfill histórico, e de qual período?** *(corrigido — ver
nota na Seção 1)*
Sim, e do período inteiro: 18/08 até hoje, a janela inteira que existe só em testnet.
O arquivo `data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/` tem os dias
confirmados por download direto (18/08, 30/08, 31/08 — todos `200`, conteúdo real), sem
o limite de ~1000 registros da REST ao vivo. **As semanas de captura testnet podem ser
substituídas por dado mainnet real via download do arquivo, não descartadas.** Isso é
independente da mudança de região da Seção 3: o backfill resolve o passado; mover
`aggtrade-capture` para `europe-west4` resolve o futuro (captura direta, sem polling,
sem o teto de folga da Seção 2). Nenhum dos dois foi executado nesta rodada — os dois
são decisão de rodada própria, agora com o número na mão para as duas.

**2. Há dado suficiente para redimensionar o walk-forward, e quanto?**
Sim, com folga larga — ~9 anos de kline 1m disponíveis contra os 45 dias/5 folds atuais.
O teto não é dado disponível (Seção 4); é decisão de escopo, custo computacional, e
possivelmente regime de mercado (janela maior mistura mais regimes). Quanto usar não foi
decidido aqui.

**3. Existe caminho para captura direta de mainnet a partir de `europe-west4`?**
Sim, confirmado por teste direto, não inferência: REST (`api.binance.com`, HTTP 200) e
WebSocket (`stream.binance.com`, handshake completo `101 Switching Protocols`) nas
portas 9443 e 443. O caminho que falta hoje (`aggtrade-capture` em mainnet) existe
tecnicamente a partir da região onde o bot já roda — não foi testado a partir de onde o
serviço roda hoje (`us-east4`, já sabido bloqueado desde 18/08).

---

## O que não foi feito (por desenho desta rodada)

Nenhum serviço movido de região, nenhum endpoint trocado, nenhum backfill rodado,
nenhum parâmetro de modelo ajustado, o bug da janela relativa do loop agêntico não foi
corrigido, nenhum tuning iniciado. A causa raiz do hiato de 151h (Seção 6) não foi
investigada.

## Decisão

- Aprovado por: Brian — comando de inventário explícito, com a restrição de não mudar
  nada porque três decisões (ambiente do aggTrade, região das capturas, dimensionamento
  do walk-forward) dependiam destes números (2026-09-01).
- Justificativa: medir antes de decidir é a mesma disciplina já aplicada em todas as
  frentes deste projeto — aqui, aplicada preventivamente, antes de qualquer correção
  ser proposta, não depois de uma já ter saído errada.
