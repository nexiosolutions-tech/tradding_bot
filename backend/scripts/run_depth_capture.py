"""Order book capture — spec 02/03 (2026-08-15, WebSocket direto retomado 2026-09-01).
Runs continuously, persisting one order book snapshot per minute into
order_book_snapshots. Read-only market data: no BINANCE_API_KEY/SECRET needed, never
imports tradingbot.execution — same isolation the learning loop already follows
(specs/09).

**Primário: WebSocket direto (`binance_depth_ws.py`), mainnet.** O motivo de ter saído
do WS em 2026-08-18 (HTTP 451 de `us-east4`, ver changes/2026-08-18-captura-aggtrade-
fluxo-ordens.md) deixou de valer quando este serviço foi movido para `europe-west4`
(inventário de 2026-09-01: `stream.binance.com` responde com handshake WS real de lá).

**Fallback: REST polling contra `data-api.binance.vision`, mantido, não removido.** Global,
não geo-restrito — funciona em qualquer região, inclusive se este serviço algum dia
precisar voltar para uma região bloqueada, ou se o WS cair por qualquer motivo. A cada
ciclo de amostragem, se o último evento recebido do WS estiver mais fresco que
`WS_STALENESS_THRESHOLD_SECONDS`, usa o WS; senão, cai para uma chamada REST avulsa
neste ciclo — nunca fica sem amostra, nunca persiste dado obsoleto do WS achando que é
atual.

`limit=20`/profundidade 20 preservados dos dois caminhos, para que trocar de fonte não
mude silenciosamente o que "o book" significa para qualquer feature construída em cima
disso depois (mesmo cuidado já registrado quando o REST-only foi adotado).

Required environment variables:
    SYMBOL          (default BTCUSDT)
    DATABASE_URL    (default: local sqlite under results/)

Usage:
    python scripts/run_depth_capture.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from tradingbot.ingestion.binance_depth_ws import BinanceDepthStream
from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.ingestion.depth_sampler import compute_snapshot_fields
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.models import OrderBookSnapshot
from tradingbot.persistence.repository import record_order_book_snapshot

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60
DEPTH_LIMIT = 20  # matches the old @depth20@1000ms WS stream — see module docstring.

# Maior que POLL_INTERVAL_SECONDS com folga: um evento do WS "fresco" pelo relógio local
# ainda pode ser o último antes de uma reconexão em andamento (backoff inicial de até
# MAX_BACKOFF_SECONDS=30s em binance_depth_ws.py) — folga evita cair pro REST à toa numa
# reconexão rápida e normal, sem deixar passar um WS de fato parado por um ciclo inteiro.
WS_STALENESS_THRESHOLD_SECONDS = 90


def deve_usar_ws(latest_local_ts: float | None, agora: float, limiar: float = WS_STALENESS_THRESHOLD_SECONDS) -> bool:
    """Pura, testável sem asyncio/rede: usa o último snapshot do WS só se ele existir e
    estiver mais fresco que o limiar — senão, o ciclo cai para o fallback REST."""
    if latest_local_ts is None:
        return False
    return (agora - latest_local_ts) < limiar


def _persist(session_factory, event: MarketEvent) -> None:
    fields = compute_snapshot_fields(event)
    session = session_factory()
    record_order_book_snapshot(
        session,
        OrderBookSnapshot(
            symbol=fields.symbol,
            ts=fields.ts,
            environment="mainnet",
            best_bid=fields.best_bid,
            best_ask=fields.best_ask,
            spread_pct=fields.spread_pct,
            bid_depth_top20=fields.bid_depth_top20,
            ask_depth_top20=fields.ask_depth_top20,
            imbalance=fields.imbalance,
            raw_bids=fields.raw_bids,
            raw_asks=fields.raw_asks,
        ),
    )


async def _consume_ws(stream: BinanceDepthStream, state: dict) -> None:
    """Roda para sempre, em paralelo ao laço de amostragem — só atualiza
    state["latest"]/state["latest_local_ts"] em book de verdade (GAP é só log, nunca
    conta como book fresco). BinanceDepthStream já reconecta com backoff sozinho; se
    esta tarefa morrer por um motivo genuinamente inesperado, o laço principal degrada
    para o fallback REST sozinho assim que o último evento passar do limiar de frescor —
    nunca fica capturando nada."""
    try:
        async for event in stream:
            if event.event_type == EventType.GAP:
                logger.warning("depth WS ficou em silêncio por %.1fs antes de reconectar", event.payload["gap_seconds"])
                continue
            state["latest"] = event
            state["latest_local_ts"] = time.time()
    except Exception:
        logger.exception("depth WS consumer morreu inesperadamente — próximos ciclos caem no fallback REST")


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    rest_client = BinanceRestClient(testnet=False)
    stream = BinanceDepthStream(symbols=[symbol], levels=DEPTH_LIMIT, update_speed_ms=1000, testnet=False)

    print(
        f"Capturando order book de {symbol} (mainnet, WebSocket direto de "
        f"europe-west4, fallback data-api.binance.vision), 1 amostra/"
        f"{POLL_INTERVAL_SECONDS}s, profundidade {DEPTH_LIMIT}..."
    )

    ws_state: dict = {"latest": None, "latest_local_ts": None}
    asyncio.create_task(_consume_ws(stream, ws_state))

    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            if deve_usar_ws(ws_state["latest_local_ts"], time.time()):
                _persist(session_factory, ws_state["latest"])
            else:
                logger.warning("depth WS sem dado fresco — usando fallback REST (.vision) neste ciclo")
                payload = await asyncio.to_thread(rest_client.fetch_depth, symbol, DEPTH_LIMIT)
                now_ms = int(time.time() * 1000)
                event = MarketEvent(
                    symbol=symbol,
                    event_type=EventType.DEPTH,
                    exchange_ts=now_ms,
                    local_ts=now_ms,
                    sequence_id=payload.last_update_id,
                    payload=payload.as_dict(),
                )
                _persist(session_factory, event)
        except httpx.HTTPError as exc:
            logger.error("depth poll (fallback REST) failed, will retry next interval: %r", exc)
        except Exception:
            logger.exception("depth capture cycle failed unexpectedly, will retry next interval")


if __name__ == "__main__":
    asyncio.run(main())
