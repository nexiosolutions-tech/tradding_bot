"""Feature engine — spec 03.

Consumes MarketEvent (kline) and emits a FeatureSnapshot only on candle close. This is the
anti-leakage invariant: a feature's knowledge_ts always equals the close time of the last
candle used to compute it, never a timestamp the decision layer couldn't have known yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.features.indicators import (
    EMA,
    MACD,
    RSI,
    BollingerBands,
    RealizedVolatility,
    RelativeVolume,
)
from tradingbot.ingestion.schema import EventType, MarketEvent


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    knowledge_ts: int
    close: float
    features: dict[str, float]


class SymbolFeatureState:
    def __init__(self):
        self.ema_fast = EMA(12)
        self.ema_slow = EMA(26)
        self.rsi = RSI(14)
        self.macd = MACD()
        self.bollinger = BollingerBands()
        self.rel_volume = RelativeVolume()
        self.volatility = RealizedVolatility()

    def update(self, close: float, volume: float) -> dict[str, float]:
        ema_fast = self.ema_fast.update(close)
        ema_slow = self.ema_slow.update(close)
        rsi = self.rsi.update(close)
        macd, signal, hist = self.macd.update(close)
        mid, upper, lower = self.bollinger.update(close)
        percent_b = self.bollinger.percent_b(close)
        rel_vol = self.rel_volume.update(volume)
        vol = self.volatility.update(close)

        raw = {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "rsi": rsi,
            "macd": macd,
            "macd_signal": signal,
            "macd_hist": hist,
            "bollinger_mid": mid,
            "bollinger_upper": upper,
            "bollinger_lower": lower,
            "bollinger_percent_b": percent_b,
            "relative_volume": rel_vol,
            "volatility": vol,
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
        volume = float(payload["volume"])
        features = state.update(close, volume)

        return FeatureSnapshot(
            symbol=event.symbol,
            knowledge_ts=event.exchange_ts,
            close=close,
            features=features,
        )
