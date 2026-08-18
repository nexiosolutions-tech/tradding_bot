"""Order book capture — spec 02/03 (2026-08-15). Runs continuously, polling one order book
snapshot per minute into order_book_snapshots. Read-only market data: no
BINANCE_API_KEY/SECRET needed, never imports tradingbot.execution — same isolation the
learning loop already follows (specs/09).

REST polling against data-api.binance.vision, mainnet, not the WS stream against
stream.binance.com (2026-08-18): confirmed via direct probe
(changes/2026-08-18-captura-aggtrade-fluxo-ordens.md) that stream.binance.com/
api.binance.com are geoblocked (HTTP 451, including a real WS handshake) from this
project's Railway region, while data-api.binance.vision — the same public depth route,
no auth — is not, even from that same region. Testnet's book is thin and doesn't carry
real microstructure signal, so this is worth the WS-to-polling downgrade: real mainnet
order book, today, no region change. `limit=20` matches the depth the old WS stream
captured (`@depth20@1000ms`) — chosen deliberately so switching data source doesn't
silently shift what "the book" means to any feature built on this later.

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

from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.ingestion.depth_sampler import compute_snapshot_fields
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.models import OrderBookSnapshot
from tradingbot.persistence.repository import record_order_book_snapshot

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60
DEPTH_LIMIT = 20  # matches the old @depth20@1000ms WS stream — see module docstring.


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    rest_client = BinanceRestClient(testnet=False)

    print(
        f"Capturando order book de {symbol} (mainnet via data-api.binance.vision), "
        f"1 amostra/{POLL_INTERVAL_SECONDS}s, profundidade {DEPTH_LIMIT}..."
    )
    while True:
        try:
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
        except httpx.HTTPError as exc:
            logger.error("depth poll failed, will retry next interval: %r", exc)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
