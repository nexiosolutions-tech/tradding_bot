"""Dataset construction — spec 04.

Pairs each feature snapshot with a forward-looking label using the triple-barrier method:
within the next `horizon_bars` candles, whichever of {take-profit, stop-loss, end of
horizon} is touched *first* decides the label — not just whether the high "eventually"
reaches the target. This matters because every real trade always carries a stop-loss
(spec 05/06, CLAUDE.md rule 2); a label that only checks future highs would train the
model against a world where trades are never stopped out, which isn't how it actually
operates. The label uses future prices by construction — that's the target we're trying
to predict, not an input feature — while the features backing each row still obey spec
03's anti-leakage invariant (they only ever reflect information available at
`knowledge_ts`).
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.features.engine import FeatureEngine
from tradingbot.ingestion.schema import EventType, MarketEvent

FEATURE_NAMES = (
    "ema_fast_dist_pct",
    "ema_slow_dist_pct",
    "ema_cross_pct",
    "rsi",
    "macd_pct",
    "macd_signal_pct",
    "macd_hist_pct",
    "bollinger_percent_b",
    "relative_volume",
    "volatility",
    "atr_pct",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "trend_regime_pct",
)

# trend_regime_pct is stored on every DatasetRow (FEATURE_NAMES above) so
# RegimeFilteredStrategy can read it straight off the live snapshot, but it is
# deliberately excluded from what the model itself trains on. A/B test on the 90-day
# cache (2026-08-01) showed handing it to LightGBM directly causes the model to key on
# this slow-moving macro signal and fire far more, highly-correlated low-quality entries
# (e.g. one fold went from 12 trades / PF 1.17 to 98 trades / PF 0.21) — gating *when* to
# trade on it beats letting the model treat it as just another input. See
# changes/2026-07-31-filtro-regime-tendencia.md.
MODEL_FEATURE_NAMES = tuple(name for name in FEATURE_NAMES if name != "trend_regime_pct")


@dataclass(frozen=True)
class TargetConfig:
    horizon_minutes: int = 15
    candle_minutes: int = 1
    # 2026-07-31: was 0.003 (0.3%), exactly the round-trip cost (~0.2% fee + ~0.1%
    # slippage) — a "hit" barely broke even. Raised to ~2.7x cost so label=1 represents a
    # real net margin. stop_loss_pct deliberately untouched — that's a risk/execution
    # parameter, out of scope here (see specs/04-modelo-ml-e-scoring.md).
    move_threshold_pct: float = 0.008
    stop_loss_pct: float = 0.015

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


def _triple_barrier_label(
    entry_close: float, future_highs: list[float], future_lows: list[float], target: TargetConfig
) -> int:
    take_profit = entry_close * (1 + target.move_threshold_pct)
    stop_loss = entry_close * (1 - target.stop_loss_pct)
    for high, low in zip(future_highs, future_lows):
        hit_take_profit = high >= take_profit
        hit_stop_loss = low <= stop_loss
        if hit_take_profit and hit_stop_loss:
            # Both touched within the same candle — can't tell which came first from a
            # single OHLC bar, so assume the worse case (stop-loss first), never the
            # optimistic one.
            return 0
        if hit_take_profit:
            return 1
        if hit_stop_loss:
            return 0
    return 0  # neither barrier touched before the horizon ended


def build_dataset(events: list[MarketEvent], target: TargetConfig) -> list[DatasetRow]:
    engine = FeatureEngine()
    snapshots = []
    future_highs = []
    future_lows = []

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
        future_lows.append(float(event.payload["low"]))

    horizon = target.horizon_bars
    rows: list[DatasetRow] = []
    for i in range(len(snapshots) - horizon):
        snapshot = snapshots[i]
        highs_window = future_highs[i + 1 : i + 1 + horizon]
        lows_window = future_lows[i + 1 : i + 1 + horizon]
        label = _triple_barrier_label(snapshot.close, highs_window, lows_window, target)
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
