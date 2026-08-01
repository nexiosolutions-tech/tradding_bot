"""Feature engine — spec 03.

Consumes MarketEvent (kline) and emits a FeatureSnapshot only on candle close. This is the
anti-leakage invariant: a feature's knowledge_ts always equals the close time of the last
candle used to compute it, never a timestamp the decision layer couldn't have known yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from tradingbot.features.indicators import (
    ATR,
    EMA,
    MACD,
    RSI,
    BollingerBands,
    RealizedVolatility,
    RelativeVolume,
)
from tradingbot.ingestion.schema import EventType, MarketEvent

# 4h on 1-minute candles — long enough to characterize a trend regime distinct from the
# entry-timing EMAs (12/26 candles), short enough to react within a trading day.
TREND_REGIME_EMA_PERIOD = 240


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    knowledge_ts: int
    close: float
    features: dict[str, float]


def _cyclical_time_features(knowledge_ts: int) -> dict[str, float]:
    """Hour-of-day / day-of-week, encoded as sin/cos pairs so the model sees a continuous
    cycle (23h and 00h are one hour apart, not a huge jump). Zero leakage risk — the
    candle's own close time is always known in advance, unlike price-derived features.
    Weekday follows Python's datetime.weekday() convention (Monday=0), same as
    backtesting/metrics.py's pnl_by_weekday, so the two stay comparable."""
    dt = datetime.fromtimestamp(knowledge_ts / 1000, tz=timezone.utc)
    hour_frac = dt.hour + dt.minute / 60.0
    return {
        "hour_sin": math.sin(2 * math.pi * hour_frac / 24),
        "hour_cos": math.cos(2 * math.pi * hour_frac / 24),
        "dow_sin": math.sin(2 * math.pi * dt.weekday() / 7),
        "dow_cos": math.cos(2 * math.pi * dt.weekday() / 7),
    }


class SymbolFeatureState:
    def __init__(self):
        self.ema_fast = EMA(12)
        self.ema_slow = EMA(26)
        self.rsi = RSI(14)
        self.macd = MACD()
        self.bollinger = BollingerBands()
        self.rel_volume = RelativeVolume()
        self.volatility = RealizedVolatility()
        self.atr = ATR(14)
        self.trend_ema = EMA(TREND_REGIME_EMA_PERIOD)

    def update(self, close: float, high: float, low: float, volume: float) -> dict[str, float]:
        ema_fast = self.ema_fast.update(close)
        ema_slow = self.ema_slow.update(close)
        rsi = self.rsi.update(close)
        macd, signal, hist = self.macd.update(close)
        mid, upper, lower = self.bollinger.update(close)
        percent_b = self.bollinger.percent_b(close)
        rel_vol = self.rel_volume.update(volume)
        vol = self.volatility.update(close)
        atr = self.atr.update(high, low, close)
        trend_ema = self.trend_ema.update(close)

        # EMA/MACD/Bollinger/ATR level features are expressed relative to `close` (%
        # terms), not as raw price — a model trained mostly on one price regime (e.g. BTC
        # at ~$60k) would otherwise anchor on absolute levels that don't transfer to a
        # very different regime (~$20k or ~$100k+). `rsi`, `bollinger_percent_b`,
        # `relative_volume` and `volatility` are already scale-invariant, unchanged here.
        raw = {
            "ema_fast_dist_pct": (close - ema_fast) / close,
            "ema_slow_dist_pct": (close - ema_slow) / close,
            "ema_cross_pct": (ema_fast - ema_slow) / close,
            "rsi": rsi,
            "macd_pct": macd / close,
            "macd_signal_pct": signal / close,
            "macd_hist_pct": hist / close,
            "bollinger_percent_b": percent_b,
            "relative_volume": rel_vol,
            "volatility": vol,
            "atr_pct": None if atr is None else atr / close,
            "trend_regime_pct": (close - trend_ema) / close,
        }
        return {k: v for k, v in raw.items() if v is not None}


class FeatureEngine:
    def __init__(self):
        self._states: dict[str, SymbolFeatureState] = {}

    def on_event(self, event: MarketEvent) -> FeatureSnapshot | None:
        if event.event_type is not EventType.KLINE:
            return None
        payload = event.payload
        if not payload.get("is_closed", False):
            return None

        state = self._states.setdefault(event.symbol, SymbolFeatureState())
        close = float(payload["close"])
        high = float(payload["high"])
        low = float(payload["low"])
        volume = float(payload["volume"])
        features = state.update(close, high, low, volume)
        features.update(_cyclical_time_features(event.exchange_ts))

        return FeatureSnapshot(
            symbol=event.symbol,
            knowledge_ts=event.exchange_ts,
            close=close,
            features=features,
        )
