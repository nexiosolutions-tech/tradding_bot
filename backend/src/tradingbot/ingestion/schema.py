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
