"""Order flow (buy/sell volume) capture — spec 02/03 (2026-08-18). Runs continuously,
persisting one buy/sell-volume bucket per second into agg_trade_buckets. Read-only market
data: no BINANCE_API_KEY/SECRET needed, never imports tradingbot.execution — same
isolation the depth capture and learning loop already follow (specs/02, 09).

Reacts to two kinds of gap the stream can emit: an id-sequence gap (exact, actionable —
backfilled via REST fromId) and a time-based liveness gap (informational only, logged by
the stream itself, nothing to backfill without a resumed id to anchor to).

Mainnet, via WebSocket direto (2026-09-01) — o motivo original de ficar em testnet
(Binance mainnet rejeitava toda conexão desta região com HTTP 451, ver
changes/2026-08-18-captura-aggtrade-fluxo-ordens.md) deixou de valer quando este serviço
foi movido para `europe-west4` (inventário de 2026-09-01: `stream.binance.com`/
`api.binance.com` respondem plenamente de lá, handshake WS real confirmado). Sequência
seguida para nunca ter uma janela quebrada: região movida primeiro, sozinha, sem mudar
código (Railway reaproveita a imagem existente, sem downtime — só volume força
recriação, e este serviço não tem); só depois deste toggle, com o serviço já rodando na
região certa. Todo o histórico anterior a esta data (18/08 em diante) ficou em testnet —
recuperável via arquivo histórico (`data.binance.vision`, confirmado no mesmo
inventário), backfill de outra rodada. Toda linha gravada daqui em diante leva
`environment="mainnet"`, para nunca se misturar em silêncio com o histórico testnet
acima.

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

# Ponto único de troca — virou False em 2026-09-01, depois de mover este serviço para
# `europe-west4` (ver docstring do módulo). Comanda o stream WS, o cliente REST de
# backfill (têm que bater: sequências de aggTradeId de testnet e mainnet não têm
# relação) e o rótulo `environment` gravado em cada linha — os três nunca podem divergir
# entre si.
USE_TESTNET = False


def _persist_bucket(session_factory, bucket: AggTradeBucketFields, environment: str) -> None:
    session = session_factory()
    upsert_agg_trade_bucket(
        session,
        AggTradeBucket(
            symbol=bucket.symbol,
            ts=bucket.ts,
            environment=environment,
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
    environment: str,
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
            _persist_bucket(session_factory, completed, environment)
    trailing = backfill_aggregator.flush(symbol)
    if trailing is not None:
        _persist_bucket(session_factory, trailing, environment)

    logger.info("aggTrade backfill for %s recovered %d/%d missing trade(s)", symbol, len(events), missing_count)


async def main() -> None:
    symbol = os.environ.get("SYMBOL", "BTCUSDT")
    environment = "testnet" if USE_TESTNET else "mainnet"
    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    rest_client = BinanceRestClient(testnet=USE_TESTNET)
    aggregator = AggTradeAggregator()
    stream = BinanceAggTradeStream(symbols=[symbol], testnet=USE_TESTNET)

    print(
        f"Capturando fluxo de ordens (aggTrade) de {symbol} ({environment}, WebSocket "
        "direto de europe-west4, ver changes/2026-09-01), 1 bucket/segundo..."
    )
    try:
        async for event in stream:
            if event.event_type == EventType.GAP:
                if "expected_from_id" in event.payload:
                    await _backfill_gap(
                        rest_client,
                        session_factory,
                        environment,
                        event.symbol,
                        event.payload["expected_from_id"],
                        event.payload["found_id"],
                        event.payload["missing_count"],
                    )
                continue

            bucket = aggregator.add(event)
            if bucket is not None:
                _persist_bucket(session_factory, bucket, environment)
    finally:
        trailing = aggregator.flush(symbol)
        if trailing is not None:
            _persist_bucket(session_factory, trailing, environment)


if __name__ == "__main__":
    asyncio.run(main())
