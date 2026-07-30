"""Binance WebSocket ingestion client — spec 02.

Owns reconnection with backoff, deduplication of already-closed candles, and explicit
gap marking on reconnect. Normalizes every message into a MarketEvent before it reaches
the queue — nothing downstream ever sees the raw Binance payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import websockets

from tradingbot.ingestion.schema import EventType, KlinePayload, MarketEvent

logger = logging.getLogger(__name__)

MAINNET_WS_BASE = "wss://stream.binance.com:9443/stream"
TESTNET_WS_BASE = "wss://testnet.binance.vision/stream"

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
GAP_ALERT_THRESHOLD_SECONDS = 10.0


def _ws_base(testnet: bool) -> str:
    return TESTNET_WS_BASE if testnet else MAINNET_WS_BASE


def _stream_names(symbols: list[str], interval: str) -> list[str]:
    return [f"{s.lower()}@kline_{interval}" for s in symbols]


def _parse_kline_message(msg: dict) -> tuple[str, KlinePayload] | None:
    data = msg.get("data", msg)
    if data.get("e") != "kline":
        return None
    k = data["k"]
    symbol = k["s"]
    payload = KlinePayload(
        open_time=int(k["t"]),
        close_time=int(k["T"]),
        interval=k["i"],
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
        is_closed=bool(k["x"]),
    )
    return symbol, payload


class BinanceKlineStream:
    """Async iterator of MarketEvent for a set of symbols. Reconnects on failure; the caller
    drives the loop with `async for event in stream:`."""

    def __init__(
        self,
        symbols: list[str],
        interval: str = "1m",
        testnet: bool = False,
    ):
        self.symbols = symbols
        self.interval = interval
        self.testnet = testnet
        self._last_closed_open_time: dict[str, int] = {}
        self._last_event_local_ts: float | None = None

    def _accept(self, symbol: str, payload: KlinePayload) -> bool:
        """Rejects a closed candle we've already delivered — the dedup invariant of spec 02.
        In-progress (non-closed) updates always pass through; the feature engine ignores them anyway."""
        if not payload.is_closed:
            return True
        last = self._last_closed_open_time.get(symbol, -1)
        if payload.open_time <= last:
            return False
        self._last_closed_open_time[symbol] = payload.open_time
        return True

    def _maybe_gap_event(self) -> MarketEvent | None:
        now = time.time()
        if self._last_event_local_ts is not None:
            gap = now - self._last_event_local_ts
            if gap > GAP_ALERT_THRESHOLD_SECONDS:
                self._last_event_local_ts = now
                return MarketEvent(
                    symbol="*",
                    event_type=EventType.GAP,
                    exchange_ts=int(now * 1000),
                    local_ts=int(now * 1000),
                    sequence_id=int(now * 1000),
                    payload={"gap_seconds": gap},
                )
        self._last_event_local_ts = now
        return None

    async def __aiter__(self):
        url = f"{_ws_base(self.testnet)}?streams={'/'.join(_stream_names(self.symbols, self.interval))}"
        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("connected to %s", url)
                    backoff = INITIAL_BACKOFF_SECONDS

                    gap_event = self._maybe_gap_event()
                    if gap_event is not None:
                        yield gap_event

                    async for raw in ws:
                        msg = json.loads(raw)
                        self._last_event_local_ts = time.time()
                        parsed = _parse_kline_message(msg)
                        if parsed is None:
                            continue
                        symbol, payload = parsed
                        if not self._accept(symbol, payload):
                            continue
                        yield MarketEvent(
                            symbol=symbol,
                            event_type=EventType.KLINE,
                            exchange_ts=payload.close_time,
                            local_ts=int(time.time() * 1000),
                            sequence_id=payload.open_time,
                            payload=payload.as_dict(),
                        )
            except (websockets.exceptions.WebSocketException, OSError) as exc:
                logger.warning("ws connection lost (%s), reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
