"""Binance aggregated-trade ingestion client — spec 02, 2026-08-18.

Mirrors binance_depth_ws.py's BinanceDepthStream (reconnection with backoff,
normalization into MarketEvent before anything downstream sees it), for the aggTrade
stream instead of partial-book-depth. Unlike depth, aggTrade messages carry both an
authoritative exchange timestamp (`T`) and a genuine monotonic id (`a`), so no
local-receipt-time approximation is needed here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import websockets

from tradingbot.ingestion.schema import AggTradePayload, EventType, MarketEvent

logger = logging.getLogger(__name__)

MAINNET_WS_BASE = "wss://stream.binance.com:9443/stream"
TESTNET_WS_BASE = "wss://stream.testnet.binance.vision/stream"

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0


def _ws_base(testnet: bool) -> str:
    return TESTNET_WS_BASE if testnet else MAINNET_WS_BASE


def _stream_names(symbols: list[str]) -> list[str]:
    return [f"{s.lower()}@aggTrade" for s in symbols]


def _parse_aggtrade_message(msg: dict) -> tuple[str, AggTradePayload] | None:
    stream = msg.get("stream")
    data = msg.get("data")
    if stream is None or data is None:
        return None
    symbol = stream.split("@")[0].upper()
    try:
        payload = AggTradePayload(
            agg_trade_id=int(data["a"]),
            price=float(data["p"]),
            quantity=float(data["q"]),
            first_trade_id=int(data["f"]),
            last_trade_id=int(data["l"]),
            trade_time=int(data["T"]),
            is_buyer_maker=bool(data["m"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    return symbol, payload


class BinanceAggTradeStream:
    """Async iterator of MarketEvent (TRADE) for a set of symbols. Reconnects on
    failure; the caller drives the loop with `async for event in stream:`."""

    def __init__(self, symbols: list[str], testnet: bool = False):
        self.symbols = symbols
        self.testnet = testnet

    async def __aiter__(self):
        url = f"{_ws_base(self.testnet)}?streams={'/'.join(_stream_names(self.symbols))}"
        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("connected to %s", url)
                    backoff = INITIAL_BACKOFF_SECONDS

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            parsed = _parse_aggtrade_message(msg)
                        except Exception:
                            logger.warning("failed to parse aggTrade ws message, skipping: %.200r", raw)
                            continue
                        if parsed is None:
                            continue
                        symbol, payload = parsed
                        yield MarketEvent(
                            symbol=symbol,
                            event_type=EventType.TRADE,
                            exchange_ts=payload.trade_time,
                            local_ts=int(time.time() * 1000),
                            sequence_id=payload.agg_trade_id,
                            payload=payload.as_dict(),
                        )
            except (websockets.exceptions.WebSocketException, OSError) as exc:
                logger.warning("aggTrade ws connection lost (%s), reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
