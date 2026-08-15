"""Order book sampling — spec 02/03, 2026-08-15. Reduces a continuous depth stream
(~1 update/second) to one snapshot per minute, and computes the derived metrics
(spread/imbalance) once, at capture time, so a later feature-engineering pass doesn't
need to reprocess raw bid/ask levels. No persistence import here on purpose — this stays
a pure transformation, like the rest of ingestion/.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ingestion.schema import MarketEvent

SAMPLE_INTERVAL_MS = 60_000


@dataclass(frozen=True)
class DepthSnapshotFields:
    symbol: str
    ts: int
    best_bid: float
    best_ask: float
    spread_pct: float
    bid_depth_top20: float
    ask_depth_top20: float
    imbalance: float
    raw_bids: list[list[float]]
    raw_asks: list[list[float]]


def compute_snapshot_fields(event: MarketEvent) -> DepthSnapshotFields:
    bids = event.payload["bids"]
    asks = event.payload["asks"]
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    bid_depth = sum(q for _, q in bids)
    ask_depth = sum(q for _, q in asks)
    total_depth = bid_depth + ask_depth
    return DepthSnapshotFields(
        symbol=event.symbol,
        ts=event.exchange_ts,
        best_bid=best_bid,
        best_ask=best_ask,
        spread_pct=(best_ask - best_bid) / best_bid,
        bid_depth_top20=bid_depth,
        ask_depth_top20=ask_depth,
        imbalance=(bid_depth - ask_depth) / total_depth if total_depth else 0.0,
        raw_bids=[[p, q] for p, q in bids],
        raw_asks=[[p, q] for p, q in asks],
    )


class DepthSampler:
    """Keeps only 1 event per SAMPLE_INTERVAL_MS bucket. Emits the first event seen in
    each new bucket immediately (unlike features/engine.py's _TimeframeAggregator, there's
    no OHLC-style "wait for the bucket to close" concern here — each depth message is
    already a complete, instantaneous snapshot, not an aggregation over the bucket)."""

    def __init__(self, sample_interval_ms: int = SAMPLE_INTERVAL_MS):
        self._sample_interval_ms = sample_interval_ms
        self._last_sampled_bucket: int | None = None

    def sample(self, event: MarketEvent) -> MarketEvent | None:
        bucket = event.exchange_ts // self._sample_interval_ms
        if bucket == self._last_sampled_bucket:
            return None
        self._last_sampled_bucket = bucket
        return event
