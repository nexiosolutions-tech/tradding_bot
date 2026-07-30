"""Live connectivity check against the real Binance testnet WebSocket — not mocked.

Exists because of a real bug: TESTNET_WS_BASE pointed at testnet.binance.vision instead of
stream.testnet.binance.vision (an HTTP 404, wrong subdomain) and nothing caught it — every
other ingestion test uses synthetic MarketEvents, never a live connection. This is slower
and network-dependent on purpose; it is the only test allowed to be that.
"""

from __future__ import annotations

import asyncio

import pytest

from tradingbot.ingestion.binance_ws import BinanceKlineStream
from tradingbot.ingestion.schema import EventType


@pytest.mark.asyncio
async def test_testnet_kline_stream_delivers_a_real_event():
    stream = BinanceKlineStream(symbols=["BTCUSDT"], interval="1m", testnet=True)
    agen = stream.__aiter__()
    try:
        event = await asyncio.wait_for(agen.__anext__(), timeout=15)
    finally:
        await agen.aclose()

    assert event.symbol in ("BTCUSDT", "*")
    assert event.event_type in (EventType.KLINE, EventType.GAP)
