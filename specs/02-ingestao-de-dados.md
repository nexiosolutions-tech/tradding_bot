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

## Ambientes

- **Testnet:** `wss://testnet.binance.vision` — usado em todo desenvolvimento e
  validação antes de qualquer mudança ir para produção (ver `CLAUDE.md`).
- **Produção:** `wss://stream.binance.com` — só após aprovação explícita,
  conforme `06-camada-de-execucao.md`.

## Fora de escopo no MVP

- Múltiplas exchanges simultâneas (arquitetura deve permitir extensão futura via
  `ccxt`, mas não é requisito inicial).
- Dados alternativos (sentimento de notícias/redes sociais) — candidato a
  `changes/` futuro, não bloqueia o MVP.
