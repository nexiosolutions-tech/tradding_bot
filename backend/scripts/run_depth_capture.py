"""Order book capture — spec 02/03 (2026-08-15). Runs continuously, sampling one order
book snapshot per minute into order_book_snapshots. Read-only market data: no
BINANCE_API_KEY/SECRET needed, never imports tradingbot.execution — same isolation the
learning loop already follows (specs/09).

Mainnet, not testnet (2026-08-18): this is public market data, not an order-placing
client — there's no execution/capital risk here, so CLAUDE.md's "testnet primeiro" rule
(which governs the execution layer) doesn't apply. Testnet's book is thin and moved by a
handful of other bots in test, not real participants — it doesn't carry the microstructure
signal this capture exists to accumulate. See
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md for the full reasoning and the known
gap this leaves in the 2026-08-15..2026-08-18 window (captured on testnet, not usable).

Required environment variables:
    SYMBOL          (default BTCUSDT)
    DATABASE_URL    (default: local sqlite under results/)

Usage:
    python scripts/run_depth_capture.py
"""

from __future__ import annotations

import asyncio
import os

from tradingbot.ingestion.binance_depth_ws import BinanceDepthStream
from tradingbot.ingestion.depth_sampler import DepthSampler, compute_snapshot_fields
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.models import OrderBookSnapshot
from tradingbot.persistence.repository import record_order_book_snapshot


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    sampler = DepthSampler()
    stream = BinanceDepthStream(symbols=[symbol], testnet=False)

    print(f"Capturando order book de {symbol} (mainnet), 1 amostra/minuto...")
    async for event in stream:
        sampled = sampler.sample(event)
        if sampled is None:
            continue
        fields = compute_snapshot_fields(sampled)
        session = session_factory()
        record_order_book_snapshot(
            session,
            OrderBookSnapshot(
                symbol=fields.symbol,
                ts=fields.ts,
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


if __name__ == "__main__":
    asyncio.run(main())
