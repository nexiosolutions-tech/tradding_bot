# 02 — Ingestão de Dados

## Objetivo

Manter uma conexão confiável e de baixa latência com os dados de mercado da
Binance, entregando eventos normalizados e ordenados para o motor de features.

## Fontes de dados (Binance)

- **Klines (candles)** via WebSocket (`<symbol>@kline_<interval>`) — granularidade
  mínima a definir em `changes/` conforme necessidade (começar em 1m).
- **Trades agregados** (`<symbol>@aggTrade`) para granularidade sub-candle quando
  necessário.
- **Order book depth** (`<symbol>@depth20@1000ms`) para spread e liquidez —
  usado como feature de contexto, não como stream primário. Captura ativa
  desde 2026-08-15 via serviço dedicado (ver seção própria abaixo); ainda
  não alimenta o motor de features (dado sendo acumulado antes de ter uso).
- **REST API** (via `python-binance` ou `ccxt`) apenas para: dados históricos
  (backfill), consulta de estado de conta/ordens, e como fallback se o WS cair.

## Requisitos funcionais

1. Conexão via WebSocket assíncrono (`asyncio` + `websockets`, evitar wrappers
   pesados no caminho crítico de latência).
2. **Reconexão automática** com backoff exponencial; ao reconectar, o sistema
   deve detectar e marcar o gap de dados perdido (não interpolar silenciosamente).
3. Cada evento recebido é normalizado para um schema interno único antes de
   entrar na fila — o resto do sistema nunca lida com o formato bruto da Binance.
4. Eventos entram em um buffer/fila que desacopla ingestão de processamento
   (MVP: fila em memória com `asyncio.Queue` ou `collections.deque`; evolução:
   Redis Streams se for necessário persistir/distribuir consumo).
5. Ordem cronológica por símbolo é garantida na fila de saída.

## Schema normalizado de evento (referência)

```
{
  "symbol": "BTCUSDT",
  "event_type": "kline" | "trade" | "depth",
  "exchange_ts": 1700000000000,   # timestamp da exchange
  "local_ts": 1700000000050,      # timestamp de recebimento local
  "sequence_id": 123456,          # para detecção de gap/duplicidade
  "payload": { ... }              # específico do tipo de evento
}
```

## Invariantes (não podem ser violadas)

- Nenhum evento é processado fora de ordem cronológica dentro do mesmo símbolo.
- Nenhum evento duplicado chega ao motor de features (deduplicação por
  `sequence_id`).
- Gaps de conexão maiores que N segundos (definir em `changes/`) disparam alerta
  visível no dashboard e, se durante posição aberta, acionam verificação de
  reconciliação com a exchange antes de qualquer nova decisão.

## Order book depth (2026-08-15)

`EventType.DEPTH` já existia no schema desde o desenho inicial (seção
anterior), mas nunca foi implementado — resposta direta ao teto de
capacidade preditiva encontrado em `11-roadmap-e-fases.md` (11ª rodada):
todas as features até aqui vêm só do próprio preço/volume da série OHLCV;
order book é a primeira fonte de informação genuinamente nova.

- **Stream**: `<symbol>@depth20@1000ms` (partial book depth, top 20 níveis,
  1 atualização/segundo) — não o stream de diffs (`@depth`) com
  reconciliação de book completo; não precisamos manter um book local vivo
  para decisão de trade nesta fase, só amostrar o estado periodicamente
  para features. Confirmado contra `testnet.binance.vision` (2026-08-15).
- **`DepthPayload`** (`ingestion/schema.py`, análogo a `KlinePayload`):
  ```
  {
    "last_update_id": 5304993,           # sequence_id da Binance para este stream
    "bids": [[preço, qty], ...],          # até 20 níveis, melhor preço primeiro
    "asks": [[preço, qty], ...]
  }
  ```
- **Sem `exchange_ts` autoritativo**: diferente do kline (que carrega o
  timestamp de fechamento do candle), a mensagem de partial-book-depth não
  traz nenhum campo de tempo — só `lastUpdateId`, um contador monotônico.
  `MarketEvent.exchange_ts` usa o horário de recebimento local
  (`time.time()*1000`) como aproximação; `sequence_id` usa `lastUpdateId`
  (serve para detectar gap/duplicidade da forma como a invariante desta
  spec já exige, só que por contador em vez de tempo).
- **Limitação estrutural, não uma escolha de implementação**: a Binance
  não expõe histórico de order book para consulta retroativa (confirmado
  2026-08-15 — `/api/v3/depth` rejeita parâmetro de timestamp passado).
  Isso significa que, ao contrário de klines (buscáveis para qualquer
  janela passada numa chamada REST), order book só existe a partir do
  momento em que começamos a capturar e persistir. A captura começa nesta
  data; não há como "voltar no tempo" e preencher o passado.
- **Amostragem, não stream primário**: `scripts/run_depth_capture.py`
  consome o stream continuamente mas só persiste 1 snapshot por minuto (na
  virada do minuto, mesmo padrão de bucket usado por
  `features/engine.py::_TimeframeAggregator`) — a granularidade de
  segundo-a-segundo não tem uso previsto e explodiria armazenamento sem
  necessidade. Ver `03-motor-de-features.md` para o que essa captura
  habilita (ainda sem features derivadas — é dado sendo acumulado, não
  uso imediato).

## Trades agregados / fluxo de ordens (2026-08-18)

`EventType.TRADE` já existia no schema desde o desenho inicial (nunca implementado, como
o `DEPTH` de 2026-08-15 antes de sua implementação) — resposta direta à discussão de
priorização de 2026-08-18 sobre estatística de overfitting e coleta de dado (captura tem
prazo de validade, cálculo sobre dado já persistido não tem — ver
`changes/2026-08-18-captura-aggtrade-fluxo-ordens.md` para o raciocínio completo).

- **Stream**: `<symbol>@aggTrade` (trades agregados pelo motor de casamento da Binance —
  múltiplos trades individuais no mesmo preço/ordem tomadora colapsados em 1 mensagem).
  Não o stream de trade bruto (`@trade`, 1 mensagem por trade individual) — aggTrade já é
  a granularidade certa para volume por lado, sem custo de banda desnecessário.
- **`AggTradePayload`** (`ingestion/schema.py`, análogo a `KlinePayload`/`DepthPayload`):
  ```
  {
    "agg_trade_id": 5304993,       # sequence_id — id monotônico da Binance p/ este stream
    "price": 65000.5,
    "quantity": 0.02,
    "first_trade_id": 1000,
    "last_trade_id": 1002,
    "trade_time": 1755500000000,   # exchange_ts — timestamp autoritativo da exchange
    "is_buyer_maker": true         # ver decisão de lado do agressor abaixo
  }
  ```
- **Diferente do depth: aggTrade tem timestamp e id autoritativos da exchange**
  (`T`/trade_time e `a`/agg_trade_id) — não precisa da aproximação por horário de
  recebimento local que `DepthPayload` precisou.
- **Lado do agressor**: `is_buyer_maker=true` significa que o comprador era a ordem que já
  estava no book (maker) e o vendedor cruzou o spread — ou seja, um trade **iniciado pelo
  vendedor** (aggressor sell). `is_buyer_maker=false` é o inverso (aggressor buy). É este
  campo, não o preço, que decide o lado em `AggTradeAggregator`.
- **Agregação em bucket de 1 segundo, não trade a trade**: `ingestion/aggtrade_aggregator.py`
  consome o stream continuamente e acumula `buy_volume`/`sell_volume`/`buy_count`/
  `sell_count`/`vwap`/`notional` por segundo, só emitindo o bucket quando o próximo já
  começou (mesmo padrão anti-vazamento do `_TimeframeAggregator` de
  `03-motor-de-features.md` — nunca emite um bucket ainda em formação). Persistir trade a
  trade explodiria armazenamento sem necessidade, e o uso pretendido (order flow
  imbalance) é uma métrica de janela, não de evento individual — mesma decisão de design
  que `depth_sampler.py` tomou para order book, adaptada de "amostrar" (o book é um estado
  instantâneo completo) para "acumular" (um trade é um incremento do período).
  - **Por que 1 segundo e não 1 minuto (como order book)**: bucket size é uma decisão
    irreversível — dá pra agregar mais grosso depois somando buckets finos (order flow
    imbalance de 1min/5min vira só um `SUM` sobre estas linhas), nunca mais fino a partir
    de um bucket já gravado. Custo estimado: BTCUSDT gera a ordem de dezenas de milhares
    de aggTrades/dia; mesmo a 1 bucket/segundo (~86 400 linhas/dia no pior caso) é
    volume trivial pro Postgres do Railway. `notional` (não só `vwap` já dividido) é
    persistido para que um merge de backfill (abaixo) recalcule o vwap exato, não uma
    média de médias.
- **Limitação estrutural, não escolha de implementação**: assim como order book, a Binance
  não expõe histórico de aggTrade além de uma janela recente via REST — a captura só
  existe a partir de quando começa a rodar, sem como preencher o passado retroativamente
  (com uma exceção parcial: gaps recentes/estreitos são recuperáveis via backfill, ver
  abaixo).
- **Detecção de gap por id + backfill via REST (2026-08-18)**: diferente do depth,
  `agg_trade_id` é um contador monotônico sem furos esperados — `BinanceAggTradeStream`
  compara cada novo id contra o último visto e emite um `MarketEvent(EventType.GAP,
  payload={"expected_from_id", "found_id", "missing_count"})` sempre que há um salto.
  `run_aggtrade_capture.py` reage a esse evento chamando
  `BinanceRestClient.fetch_agg_trades(symbol, from_id, to_id)` (paginado por `fromId`,
  rodado via `asyncio.to_thread` — é uma chamada síncrona e não pode bloquear o event
  loop que mantém o ping/pong do WebSocket vivo) para recuperar os trades perdidos e
  faz merge nos buckets já persistidos via `upsert_agg_trade_bucket` (soma os campos
  brutos — `buy_volume`/`sell_volume`/`notional`/contagens — e recalcula o vwap a
  partir do notional total, não a partir de uma média de vwaps já perdidos). Gaps maiores
  que `MAX_BACKFILL_TRADES` (50 000, a REST da Binance só serve uma janela recente) são
  logados e aceitos como buraco conhecido, não perseguidos indefinidamente.
- **Heartbeat de liveness por tempo (2026-08-18)**: tanto `BinanceAggTradeStream` quanto
  `BinanceDepthStream` agora espelham o `_maybe_gap_event` que `BinanceKlineStream` já
  tinha — se nenhuma mensagem chega por mais de `GAP_ALERT_THRESHOLD_SECONDS` (10s) antes
  de uma (re)conexão, emite `MarketEvent(GAP, payload={"gap_seconds"})` e loga via
  `logger.error` (bem visível no viewer de logs do Railway). É só sinal, não backfill —
  para aggTrade, a checagem de id acima já cobre o caso concreto de trade perdido; isto
  cobre o modo de falha "processo/stream ficou mudo" que um crash puro (coberto pelo
  `restartPolicyType=ALWAYS` do Railway) não cobre. **Limitação documentada, não
  resolvida**: sem canal de alerta externo configurado neste projeto (sem Slack/e-mail/
  pager), o sinal só é visível a quem olhar os logs do Railway ativamente — não há push
  notification automática hoje.
- **`scripts/run_aggtrade_capture.py`** roda continuamente, persiste 1 bucket/segundo na
  tabela `agg_trade_buckets`, faz flush do bucket parcial em formação num `finally` ao
  encerrar (evita perder até 1s de dado a cada restart/deploy). Ver
  `03-motor-de-features.md` para o que essa captura habilita (ainda sem feature derivada —
  é dado sendo acumulado, mesmo estágio em que order book está desde 2026-08-15).

## Ambientes

- **Testnet:** `wss://testnet.binance.vision` — usado em todo desenvolvimento e
  validação da **camada de execução** antes de qualquer mudança ir para produção
  (ver `CLAUDE.md`, regra 1). Continua sendo o ambiente da `tradding_bot`
  (orquestrador/ordens) hoje.
- **Produção:** `wss://stream.binance.com` — só após aprovação explícita para a
  camada de execução, conforme `06-camada-de-execucao.md`.
- **Captura de order book/fluxo de ordens: mainnet é o alvo certo, mas bloqueado na
  infra atual (2026-08-18)**: `depth-capture`/`aggtrade-capture` são serviços
  somente-leitura de market data pública — sem `BINANCE_API_KEY`/`SECRET`, nunca
  importam `tradingbot.execution` — logo a regra 1 do `CLAUDE.md` (testnet primeiro)
  não se aplica a eles; ela existe para a camada de execução, que continua em
  testnet. O motivo de mainnet ser o alvo certo: o livro de ofertas e o fluxo de
  trades do testnet são rasos, movidos por poucos outros bots em teste, não por
  participantes reais — não carregam o sinal de microestrutura que essa captura
  existe para acumular.
  - **Tentativa de migração revertida no mesmo dia**: apontar os dois serviços para
    mainnet resultou em `HTTP 451` (bloqueio geográfico) em toda tentativa de
    conexão a partir da região do projeto no Railway — mesma família de bloqueio já
    conhecida para execução de ordens (ver task histórica "bloqueio geográfico da
    Binance nas ordens"), agora confirmada também para WebSocket de market data.
    Os dois serviços entraram em loop de reconexão infinito, sem capturar nada (nem
    testnet nem mainnet) por ~15-20 minutos até o revert. Voltado para testnet como
    paliativo — captura de baixo sinal é melhor que nenhuma. Resolver o bloqueio de
    verdade (outra região do Railway, ou proxy) é trabalho futuro, não desta rodada.
  - **Consequência**: `order_book_snapshots` capturado entre 2026-08-15 (início da
    captura) e hoje é testnet, não usável para calibração de slippage/microestrutura
    (ver `03-motor-de-features.md`, seção de order book, e
    `changes/2026-08-18-captura-aggtrade-fluxo-ordens.md`) — as linhas não foram
    apagadas (decisão de manter vs. descartar fica para quando alguém for de fato
    consumir esse dado), mas continuará crescendo em testnet até o bloqueio
    geográfico ser resolvido.
  - **Coluna `environment` ("testnet"/"mainnet")**: adicionada a `order_book_snapshots`
    e `agg_trade_buckets` antes que dado de mainnet pudesse começar a fluir para as
    mesmas tabelas — sem isso, no dia em que o bloqueio geográfico for resolvido, não
    haveria como separar dado sintético de dado real na mesma tabela (o alçapão de
    irreversibilidade real aqui: retroativamente não dá pra reconstruir a origem de
    uma linha já gravada sem essa marca). `db.py::_ensure_capture_environment_column`
    faz a migração aditiva (este projeto não tem framework de migração — Alembic ou
    equivalente — só `Base.metadata.create_all`, que nunca altera tabela existente) e
    já backfilla toda linha antiga como `"testnet"`, o que é exatamente correto (era
    tudo testnet até aqui).

## Fora de escopo no MVP

- Múltiplas exchanges simultâneas (arquitetura deve permitir extensão futura via
  `ccxt`, mas não é requisito inicial).
- Dados alternativos (sentimento de notícias/redes sociais) — candidato a
  `changes/` futuro, não bloqueia o MVP.
