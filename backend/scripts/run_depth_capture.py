"""Order book capture — spec 02/03 (2026-08-15). Runs continuously, sampling one order
book snapshot per minute into order_book_snapshots. Read-only market data: no
BINANCE_API_KEY/SECRET needed, never imports tradingbot.execution — same isolation the
learning loop already follows (specs/09).

Testnet, not mainnet — reverted same-day (2026-08-18): mainnet is the right target in
principle (public market data, no execution/capital risk, testnet's book is thin and
doesn't carry real microstructure signal — see
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md), but Binance mainnet rejects every
connection from this Railway project's region with HTTP 451 (geoblock — same family of
issue already known for order execution, now confirmed for market-data WS too). Back on
testnet until that's resolved (different Railway region, or a proxy) — capturing something
low-signal beats capturing nothing. Every row is tagged `environment="testnet"` so this
can never silently mix with real mainnet data later.

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

# Single toggle point — flip to False once the geoblock (see module docstring) is
# resolved. Drives both the actual connection and the `environment` label persisted on
# every row, so the two can never drift apart.
USE_TESTNET = True


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    environment = "testnet" if USE_TESTNET else "mainnet"
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    sampler = DepthSampler()
    stream = BinanceDepthStream(symbols=[symbol], testnet=USE_TESTNET)

    print(
        f"Capturando order book de {symbol} ({environment} — mainnet bloqueado "
        "geograficamente pelo Railway, ver changes/), 1 amostra/minuto..."
    )
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
                environment=environment,
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
