"""Dataset construction — spec 04.

Pairs each feature snapshot with a forward-looking label: whether price moves up by more
than `move_threshold_pct` at any point in the next `horizon_bars` candles. The label uses
future prices by construction — that's the target we're trying to predict, not an input
feature — while the features backing each row still obey spec 03's anti-leakage invariant
(they only ever reflect information available at `knowledge_ts`).
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.features.engine import FeatureEngine
from tradingbot.ingestion.schema import EventType, MarketEvent

FEATURE_NAMES = (
    "ema_fast",
    "ema_slow",
    "rsi",
    "macd",
    "macd_signal",
    "macd_hist",
    "bollinger_mid",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_percent_b",
    "relative_volume",
    "volatility",
)


@dataclass(frozen=True)
class TargetConfig:
    horizon_minutes: int = 15
    candle_minutes: int = 1
    move_threshold_pct: float = 0.003

    @property
    def horizon_bars(self) -> int:
        return max(1, self.horizon_minutes // self.candle_minutes)


@dataclass(frozen=True)
class DatasetRow:
    symbol: str
    knowledge_ts: int
    close: float
    features: dict[str, float]
    label: int


def build_dataset(events: list[MarketEvent], target: TargetConfig) -> list[DatasetRow]:
    engine = FeatureEngine()
    snapshots = []
    future_highs = []

    for event in events:
        if event.event_type is not EventType.KLINE:
            continue
        snapshot = engine.on_event(event)
        if snapshot is None:
            continue
        if not all(name in snapshot.features for name in FEATURE_NAMES):
            continue  # indicators still warming up
        snapshots.append(snapshot)
        future_highs.append(float(event.payload["high"]))

    horizon = target.horizon_bars
    rows: list[DatasetRow] = []
    for i in range(len(snapshots) - horizon):
        snapshot = snapshots[i]
        window = future_highs[i + 1 : i + 1 + horizon]
        label = 1 if max(window) >= snapshot.close * (1 + target.move_threshold_pct) else 0
        rows.append(
            DatasetRow(
                symbol=snapshot.symbol,
                knowledge_ts=snapshot.knowledge_ts,
                close=snapshot.close,
                features={name: snapshot.features[name] for name in FEATURE_NAMES},
                label=label,
            )
        )
    return rows
