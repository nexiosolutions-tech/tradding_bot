"""Normalized event schema — spec 02. The rest of the system never sees raw exchange payloads."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EventType(str, Enum):
    KLINE = "kline"
    TRADE = "trade"
    DEPTH = "depth"
    GAP = "gap"


@dataclass(frozen=True)
class MarketEvent:
    symbol: str
    event_type: EventType
    exchange_ts: int
    local_ts: int
    sequence_id: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class KlinePayload:
    open_time: int
    close_time: int
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "open_time": self.open_time,
            "close_time": self.close_time,
            "interval": self.interval,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "is_closed": self.is_closed,
        }


@dataclass(frozen=True)
class DepthPayload:
    """Partial book depth snapshot (top N levels) — spec 02, 2026-08-15. Unlike
    KlinePayload, the exchange gives no timestamp here, only `last_update_id` (a
    monotonic counter) — see MarketEvent construction in binance_depth_ws.py for how
    exchange_ts/sequence_id are derived from that."""

    last_update_id: int
    bids: list[tuple[float, float]]  # (price, qty), best first
    asks: list[tuple[float, float]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_update_id": self.last_update_id,
            "bids": [[p, q] for p, q in self.bids],
            "asks": [[p, q] for p, q in self.asks],
        }


@dataclass(frozen=True)
class AggTradePayload:
    """Aggregated trade — spec 02, 2026-08-18. Unlike DepthPayload, the exchange gives
    both an authoritative timestamp (`T`, trade_time) and a monotonic id (`a`,
    agg_trade_id), so MarketEvent.exchange_ts/sequence_id use those directly instead of
    local-receipt approximations. `is_buyer_maker` is the aggressor-side flag: True means
    the buyer was the resting order (maker) and the seller crossed the spread (a
    sell-initiated/aggressor-sell trade); False means the buyer was the aggressor."""

    agg_trade_id: int
    price: float
    quantity: float
    first_trade_id: int
    last_trade_id: int
    trade_time: int
    is_buyer_maker: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "agg_trade_id": self.agg_trade_id,
            "price": self.price,
            "quantity": self.quantity,
            "first_trade_id": self.first_trade_id,
            "last_trade_id": self.last_trade_id,
            "trade_time": self.trade_time,
            "is_buyer_maker": self.is_buyer_maker,
        }
