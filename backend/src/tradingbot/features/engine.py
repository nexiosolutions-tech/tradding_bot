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
    ReturnOverWindow,
)
from tradingbot.ingestion.schema import EventType, MarketEvent

# 4h on 1-minute candles — long enough to characterize a trend regime distinct from the
# entry-timing EMAs (12/26 candles), short enough to react within a trading day.
TREND_REGIME_EMA_PERIOD = 240

# 2026-08-12: multi-timeframe confluence — a 1-minute RSI/Bollinger reading is easy for
# the model to overfit to microstructure noise (specs/11, 8ª/9ª/10ª rodadas). Pairing it
# with the same reading at 5m/15m tests whether "oversold on 1m AND on 15m" carries signal
# a single timeframe doesn't.
MULTI_TIMEFRAME_MINUTES = (5, 15)

# 2026-08-17: cross-asset relative strength (specs/03/11, 14ª rodada) — same short-term
# scale as the entry-timing EMAs, not trend_regime_pct's 4h. Same window used for both
# assets so the two returns are directly comparable.
RELATIVE_STRENGTH_WINDOW_MINUTES = 15
CROSS_ASSET_FEATURE_NAME = "eth_relative_strength_pct"


class _TimeframeAggregator:
    """Tracks which coarser-timeframe bucket the most recent 1-minute candle belongs to,
    and reports the closing price of a bucket the instant it's known to be complete (the
    first candle of the *next* bucket arrives) — never a still-forming bucket, so anything
    built from it only ever reflects fully-closed information (spec 03's anti-leakage
    invariant). RSI/Bollinger only need the close price, not full OHLC, so that's all this
    tracks."""

    def __init__(self, bucket_minutes: int):
        self._bucket_ms = bucket_minutes * 60_000
        self._current_bucket_id: int | None = None
        self._current_close: float | None = None

    def update(self, ts: int, close: float) -> float | None:
        bucket_id = ts // self._bucket_ms
        completed_close = None
        if self._current_bucket_id is not None and bucket_id != self._current_bucket_id:
            completed_close = self._current_close
        self._current_bucket_id = bucket_id
        self._current_close = close
        return completed_close


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
        # Multi-timeframe confluence (2026-08-12) — same RSI/Bollinger reading, recomputed
        # over synthetic 5m/15m candles aggregated from the 1m stream.
        self._mtf_aggregators = {m: _TimeframeAggregator(m) for m in MULTI_TIMEFRAME_MINUTES}
        self._mtf_rsi = {m: RSI(14) for m in MULTI_TIMEFRAME_MINUTES}
        self._mtf_bollinger = {m: BollingerBands() for m in MULTI_TIMEFRAME_MINUTES}
        self._mtf_rsi_value: dict[int, float | None] = {m: None for m in MULTI_TIMEFRAME_MINUTES}
        self._mtf_bb_pctb_value: dict[int, float | None] = {m: None for m in MULTI_TIMEFRAME_MINUTES}
        # Cross-asset relative strength (2026-08-17) — this symbol's own short-term return,
        # diffed against a reference symbol's return over the identical window (passed into
        # update() by FeatureEngine, which owns the reference symbol's stream).
        self._own_return = ReturnOverWindow(RELATIVE_STRENGTH_WINDOW_MINUTES)

    def update(
        self,
        close: float,
        high: float,
        low: float,
        volume: float,
        knowledge_ts: int,
        reference_return: float | None = None,
    ) -> dict[str, float]:
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
        own_return = self._own_return.update(close)

        for minutes in MULTI_TIMEFRAME_MINUTES:
            completed_close = self._mtf_aggregators[minutes].update(knowledge_ts, close)
            if completed_close is not None:
                self._mtf_rsi_value[minutes] = self._mtf_rsi[minutes].update(completed_close)
                self._mtf_bollinger[minutes].update(completed_close)
                self._mtf_bb_pctb_value[minutes] = self._mtf_bollinger[minutes].percent_b(completed_close)

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
            "rsi_5m": self._mtf_rsi_value[5],
            "rsi_15m": self._mtf_rsi_value[15],
            "bollinger_percent_b_5m": self._mtf_bb_pctb_value[5],
            "bollinger_percent_b_15m": self._mtf_bb_pctb_value[15],
            CROSS_ASSET_FEATURE_NAME: (
                None if own_return is None or reference_return is None else own_return - reference_return
            ),
        }
        return {k: v for k, v in raw.items() if v is not None}


class FeatureEngine:
    def __init__(self, reference_symbol: str | None = None):
        self._states: dict[str, SymbolFeatureState] = {}
        # Cross-asset relative strength (2026-08-17, opt-in — specs/03) — when set, events
        # for this symbol update a return tracker but never produce their own
        # FeatureSnapshot: it's context for whatever symbol IS being traded, not a second
        # tradeable symbol.
        self._reference_symbol = reference_symbol
        self._reference_return_tracker = (
            ReturnOverWindow(RELATIVE_STRENGTH_WINDOW_MINUTES) if reference_symbol is not None else None
        )
        self._reference_return_value: float | None = None

    def on_event(self, event: MarketEvent) -> FeatureSnapshot | None:
        if event.event_type is not EventType.KLINE:
            return None
        payload = event.payload
        if not payload.get("is_closed", False):
            return None

        if self._reference_symbol is not None and event.symbol == self._reference_symbol:
            self._reference_return_value = self._reference_return_tracker.update(float(payload["close"]))
            return None

        state = self._states.setdefault(event.symbol, SymbolFeatureState())
        close = float(payload["close"])
        high = float(payload["high"])
        low = float(payload["low"])
        volume = float(payload["volume"])
        features = state.update(close, high, low, volume, event.exchange_ts, self._reference_return_value)
        features.update(_cyclical_time_features(event.exchange_ts))

        return FeatureSnapshot(
            symbol=event.symbol,
            knowledge_ts=event.exchange_ts,
            close=close,
            features=features,
        )
