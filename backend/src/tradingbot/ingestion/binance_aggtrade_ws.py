"""Binance aggregated-trade ingestion client — spec 02, 2026-08-18.

Mirrors binance_depth_ws.py's BinanceDepthStream (reconnection with backoff,
normalization into MarketEvent before anything downstream sees it), for the aggTrade
stream instead of partial-book-depth. Unlike depth, aggTrade messages carry both an
authoritative exchange timestamp (`T`) and a genuine monotonic id (`a`), so no
local-receipt-time approximation is needed here — and that id enables a precision depth
lacks: an exact count of missing trades, not just "some update was skipped".
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
GAP_ALERT_THRESHOLD_SECONDS = 10.0


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
    """Async iterator of MarketEvent for a set of symbols. Reconnects on failure; the
    caller drives the loop with `async for event in stream:`.

    Emits two distinct kinds of EventType.GAP, both a `MarketEvent` a consumer can act on:
    - id-sequence gap (per symbol, `payload["expected_from_id"]` present): agg_trade_id is
      a monotonic counter, so any jump is an exact, actionable count of missing trades —
      the consumer (run_aggtrade_capture.py) uses it to drive a REST backfill via fromId.
    - time-based liveness gap (`payload["gap_seconds"]` present, symbol="*"): mirrors
      BinanceKlineStream's `_maybe_gap_event` — "no message arrived for N seconds", checked
      on each reconnect. Purely informational (nothing to backfill without a resumed id to
      anchor to); logged loudly so a collector that goes quiet doesn't do so unnoticed.
    """

    def __init__(self, symbols: list[str], testnet: bool = False):
        self.symbols = symbols
        self.testnet = testnet
        self._last_agg_trade_id: dict[str, int] = {}
        self._last_event_local_ts: float | None = None

    def _maybe_id_gap_event(self, symbol: str, agg_trade_id: int) -> MarketEvent | None:
        last_id = self._last_agg_trade_id.get(symbol)
        self._last_agg_trade_id[symbol] = agg_trade_id
        if last_id is None or agg_trade_id <= last_id:
            return None
        missing = agg_trade_id - last_id - 1
        if missing <= 0:
            return None
        now_ms = int(time.time() * 1000)
        return MarketEvent(
            symbol=symbol,
            event_type=EventType.GAP,
            exchange_ts=now_ms,
            local_ts=now_ms,
            sequence_id=agg_trade_id,
            payload={"expected_from_id": last_id + 1, "found_id": agg_trade_id, "missing_count": missing},
        )

    def _maybe_liveness_gap_event(self) -> MarketEvent | None:
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
        url = f"{_ws_base(self.testnet)}?streams={'/'.join(_stream_names(self.symbols))}"
        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("connected to %s", url)
                    backoff = INITIAL_BACKOFF_SECONDS

                    liveness_gap = self._maybe_liveness_gap_event()
                    if liveness_gap is not None:
                        logger.error("aggTrade stream was silent for %.1fs before reconnecting", liveness_gap.payload["gap_seconds"])
                        yield liveness_gap

                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                            self._last_event_local_ts = time.time()
                            parsed = _parse_aggtrade_message(msg)
                        except Exception:
                            logger.warning("failed to parse aggTrade ws message, skipping: %.200r", raw)
                            continue
                        if parsed is None:
                            continue
                        symbol, payload = parsed

                        id_gap = self._maybe_id_gap_event(symbol, payload.agg_trade_id)
                        if id_gap is not None:
                            logger.error(
                                "aggTrade id gap on %s: missing %d trade(s) from %d to %d",
                                symbol,
                                id_gap.payload["missing_count"],
                                id_gap.payload["expected_from_id"],
                                id_gap.payload["found_id"] - 1,
                            )
                            yield id_gap

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
