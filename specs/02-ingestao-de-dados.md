# 02 — Ingestão de Dados

## Objetivo

Manter uma conexão confiável e de baixa latência com os dados de mercado da
Binance, entregando eventos normalizados e ordenados para o motor de features.

## Fontes de dados (Binance)

- **Klines (candles)** via WebSocket (`<symbol>@kline_<interval>`) — granularidade
  mínima a definir em `changes/` conforme necessidade (começar em 1m).
- **Trades agregados** (`<symbol>@aggTrade`) para granularidade sub-candle quando
  necessário.
- **Order book depth** (`<symbol>@depth`) para spread e liquidez — usado como
  feature de contexto, não como stream primário no MVP.
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
