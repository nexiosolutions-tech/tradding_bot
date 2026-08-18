"""Order flow (buy/sell volume) capture — spec 02/03 (2026-08-18). Runs continuously,
persisting one buy/sell-volume bucket per second into agg_trade_buckets. Read-only market
data: no BINANCE_API_KEY/SECRET needed, never imports tradingbot.execution — same
isolation the depth capture and learning loop already follow (specs/02, 09).

Reacts to two kinds of gap the stream can emit: an id-sequence gap (exact, actionable —
backfilled via REST fromId) and a time-based liveness gap (informational only, logged by
the stream itself, nothing to backfill without a resumed id to anchor to).

Mainnet, not testnet (2026-08-18): this is public market data, no order-placing client —
no execution/capital risk, so CLAUDE.md's "testnet primeiro" rule (execution layer) doesn't
apply. Testnet's order flow is a handful of other bots in test, not real participants —
aggressor-side volume there carries no predictive signal, it's synthetic noise. See
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md.

Required environment variables:
    SYMBOL          (default BTCUSDT)
    DATABASE_URL    (default: local sqlite under results/)

Usage:
    python scripts/run_aggtrade_capture.py
"""

from __future__ import annotations

import asyncio
import logging
import os

from tradingbot.ingestion.aggtrade_aggregator import AggTradeAggregator, AggTradeBucketFields
from tradingbot.ingestion.binance_aggtrade_ws import BinanceAggTradeStream
from tradingbot.ingestion.schema import EventType
from tradingbot.ingestion.binance_rest import BinanceRestClient
from tradingbot.persistence.db import get_session_factory
from tradingbot.persistence.models import AggTradeBucket
from tradingbot.persistence.repository import upsert_agg_trade_bucket

logger = logging.getLogger(__name__)

# Binance's aggTrades REST endpoint only serves a limited recent window (not full history);
# a gap wider than this is not fully backfillable — logged and left as a known hole rather
# than looping forever trying to recover data the exchange no longer serves.
MAX_BACKFILL_TRADES = 50_000


def _persist_bucket(session_factory, bucket: AggTradeBucketFields) -> None:
    session = session_factory()
    upsert_agg_trade_bucket(
        session,
        AggTradeBucket(
            symbol=bucket.symbol,
            ts=bucket.ts,
            buy_volume=bucket.buy_volume,
            sell_volume=bucket.sell_volume,
            buy_count=bucket.buy_count,
            sell_count=bucket.sell_count,
            vwap=bucket.vwap,
            notional=bucket.notional,
        ),
    )


async def _backfill_gap(
    rest_client: BinanceRestClient,
    session_factory,
    symbol: str,
    expected_from_id: int,
    found_id: int,
    missing_count: int,
) -> None:
    if missing_count > MAX_BACKFILL_TRADES:
        logger.error(
            "aggTrade gap on %s too wide to backfill (%d trades, limit %d) — accepting the hole",
            symbol,
            missing_count,
            MAX_BACKFILL_TRADES,
        )
        return

    to_id = found_id - 1
    events = await asyncio.to_thread(rest_client.fetch_agg_trades, symbol, expected_from_id, to_id)
    if not events:
        logger.warning("aggTrade backfill for %s [%d, %d] returned nothing (window likely expired)", symbol, expected_from_id, to_id)
        return

    backfill_aggregator = AggTradeAggregator()
    for event in events:
        completed = backfill_aggregator.add(event)
        if completed is not None:
            _persist_bucket(session_factory, completed)
    trailing = backfill_aggregator.flush(symbol)
    if trailing is not None:
        _persist_bucket(session_factory, trailing)

    logger.info("aggTrade backfill for %s recovered %d/%d missing trade(s)", symbol, len(events), missing_count)


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    rest_client = BinanceRestClient(testnet=False)
    aggregator = AggTradeAggregator()
    stream = BinanceAggTradeStream(symbols=[symbol], testnet=False)

    print(f"Capturando fluxo de ordens (aggTrade) de {symbol} (mainnet), 1 bucket/segundo...")
    try:
        async for event in stream:
            if event.event_type == EventType.GAP:
                if "expected_from_id" in event.payload:
                    await _backfill_gap(
                        rest_client,
                        session_factory,
                        event.symbol,
                        event.payload["expected_from_id"],
                        event.payload["found_id"],
                        event.payload["missing_count"],
                    )
                continue

            bucket = aggregator.add(event)
            if bucket is not None:
                _persist_bucket(session_factory, bucket)
    finally:
        trailing = aggregator.flush(symbol)
        if trailing is not None:
            _persist_bucket(session_factory, trailing)


if __name__ == "__main__":
    asyncio.run(main())
