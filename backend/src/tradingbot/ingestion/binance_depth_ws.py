"""Binance order book depth ingestion client — spec 02, 2026-08-15.

Mirrors binance_ws.py's BinanceKlineStream (reconnection with backoff, normalization
into MarketEvent before anything downstream sees it), for the partial-book-depth stream
instead of klines. The partial-book-depth message carries no exchange timestamp — only
`lastUpdateId`, a monotonic counter — so exchange_ts is approximated from local receipt
time and sequence_id uses lastUpdateId instead.

Unlike aggTrade, a skipped `lastUpdateId` is not backfillable/actionable the way a missing
trade id is: each partial-book-depth message is a complete, self-consistent top-N snapshot,
not a diff applied on top of a running book — missing some intermediate snapshots between
one 1-second update and the next loses nothing beyond that intermediate state, which this
capture (1 sample/minute, see depth_sampler.py) already discards by design. Only the
time-based liveness signal (2026-08-18, mirrored from BinanceKlineStream) applies here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import websockets

from tradingbot.ingestion.schema import DepthPayload, EventType, MarketEvent

logger = logging.getLogger(__name__)

MAINNET_WS_BASE = "wss://stream.binance.com:9443/stream"
TESTNET_WS_BASE = "wss://stream.testnet.binance.vision/stream"

INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
GAP_ALERT_THRESHOLD_SECONDS = 10.0


def _ws_base(testnet: bool) -> str:
    return TESTNET_WS_BASE if testnet else MAINNET_WS_BASE


def _stream_names(symbols: list[str], levels: int, update_speed_ms: int) -> list[str]:
    return [f"{s.lower()}@depth{levels}@{update_speed_ms}ms" for s in symbols]


def _parse_depth_message(msg: dict) -> tuple[str, DepthPayload] | None:
    stream = msg.get("stream")
    data = msg.get("data")
    if stream is None or data is None:
        return None
    symbol = stream.split("@")[0].upper()
    payload = DepthPayload(
        last_update_id=int(data["lastUpdateId"]),
        bids=[(float(p), float(q)) for p, q in data["bids"]],
        asks=[(float(p), float(q)) for p, q in data["asks"]],
    )
    return symbol, payload


class BinanceDepthStream:
    """Async iterator of MarketEvent (DEPTH) for a set of symbols. Reconnects on
    failure; the caller drives the loop with `async for event in stream:`.

    Also emits EventType.GAP (symbol="*", `payload["gap_seconds"]`) when no message
    arrived for GAP_ALERT_THRESHOLD_SECONDS before a (re)connect — a collector that goes
    quiet should not do so unnoticed (2026-08-18)."""

    def __init__(
        self,
        symbols: list[str],
        levels: int = 20,
        update_speed_ms: int = 1000,
        testnet: bool = False,
    ):
        self.symbols = symbols
        self.levels = levels
        self.update_speed_ms = update_speed_ms
        self.testnet = testnet
        self._last_event_local_ts: float | None = None

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
        url = f"{_ws_base(self.testnet)}?streams={'/'.join(_stream_names(self.symbols, self.levels, self.update_speed_ms))}"
        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("connected to %s", url)
                    backoff = INITIAL_BACKOFF_SECONDS

                    gap_event = self._maybe_gap_event()
                    if gap_event is not None:
                        logger.error("depth stream was silent for %.1fs before reconnecting", gap_event.payload["gap_seconds"])
                        yield gap_event

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            self._last_event_local_ts = time.time()
                            parsed = _parse_depth_message(msg)
                        except Exception:
                            logger.warning("failed to parse depth ws message, skipping: %.200r", raw)
                            continue
                        if parsed is None:
                            continue
                        symbol, payload = parsed
                        now_ms = int(time.time() * 1000)
                        yield MarketEvent(
                            symbol=symbol,
                            event_type=EventType.DEPTH,
                            exchange_ts=now_ms,
                            local_ts=now_ms,
                            sequence_id=payload.last_update_id,
                            payload=payload.as_dict(),
                        )
            except (websockets.exceptions.WebSocketException, OSError) as exc:
                logger.warning("depth ws connection lost (%s), reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(backoff + random.uniform(0, backoff * 0.1))
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
