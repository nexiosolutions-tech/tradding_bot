"""Order flow (buy/sell volume) capture — spec 02/03 (2026-08-18). Runs continuously,
persisting one buy/sell-volume bucket per minute into agg_trade_buckets. Read-only market
data: no BINANCE_API_KEY/SECRET needed, never imports tradingbot.execution — same
isolation the depth capture and learning loop already follow (specs/02, 09).

Required environment variables:
    SYMBOL          (default BTCUSDT)
    DATABASE_URL    (default: local sqlite under results/)

Usage:
    python scripts/run_aggtrade_capture.py
"""

from __future__ import annotations

import asyncio
import os

from tradingbot.ingestion.aggtrade_aggregator import AggTradeAggregator
from tradingbot.ingestion.binance_aggtrade_ws import BinanceAggTradeStream
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.models import AggTradeBucket
from tradingbot.persistence.repository import record_agg_trade_bucket


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    aggregator = AggTradeAggregator()
    stream = BinanceAggTradeStream(symbols=[symbol], testnet=True)

    print(f"Capturando fluxo de ordens (aggTrade) de {symbol} (testnet), 1 bucket/minuto...")
    async for event in stream:
        bucket = aggregator.add(event)
        if bucket is None:
            continue
        session = session_factory()
        record_agg_trade_bucket(
            session,
            AggTradeBucket(
                symbol=bucket.symbol,
                ts=bucket.ts,
                buy_volume=bucket.buy_volume,
                sell_volume=bucket.sell_volume,
                buy_count=bucket.buy_count,
                sell_count=bucket.sell_count,
                vwap=bucket.vwap,
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
