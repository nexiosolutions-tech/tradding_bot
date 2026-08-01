"""ModelStrategy — spec 04's calibrated score wired into the same Strategy protocol used
by the backtest engine (spec 07) and, later, the execution layer (spec 06). This is what
replaces the Fase 1 placeholder rule once a model has been promoted.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.backtesting.strategy import Strategy, TradeSignal
from tradingbot.features.engine import FeatureSnapshot
from tradingbot.model.training import TrainedModel


@dataclass
class ModelStrategy:
    model: TrainedModel
    entry_threshold: float
    exit_threshold: float
    stop_loss_pct: float

    def on_features(self, snapshot: FeatureSnapshot) -> TradeSignal | None:
        if not all(name in snapshot.features for name in self.model.feature_names):
            return None
        score = self.model.predict_proba(snapshot.features)
        if score >= self.entry_threshold:
            return TradeSignal(symbol=snapshot.symbol, confidence=score, stop_loss_pct=self.stop_loss_pct)
        return None

    def should_exit(self, snapshot: FeatureSnapshot) -> bool:
        if not all(name in snapshot.features for name in self.model.feature_names):
            return False
        return self.model.predict_proba(snapshot.features) < self.exit_threshold


@dataclass
class RegimeFilteredStrategy:
    """Wraps another strategy, suppressing new entries when the market's longer-term
    trend regime is unfavorable — spec 04, 2026-07-31. A long-only strategy has no
    structural way to profit from or protect against a downtrend (spec 06), and a
    walk-forward investigation found a real, mechanistically-explicable performance gap
    between uptrend and downtrend folds (mean PF 1.02 vs. 0.29). This is an explicit gate
    on *when* to try an entry, not a change to *how* the wrapped strategy decides among
    tradeable moments — exits are never blocked, only new entries."""

    inner: Strategy
    # Not 0.0: trend_regime_pct is close vs. a 240-candle (~4h) EMA, which lags and
    # oscillates slightly negative during ordinary pullbacks inside an uptrend. A hard
    # cutoff at 0.0 blocked those too, and measured *worse* than no filter at all (2026-
    # 08-01 A/B on the 90-day cache: mean PF 0.62 vs. 0.73 unfiltered). -0.005 was the
    # best of {-0.01, -0.005, 0.0, +0.005, +0.01, +0.02} tried against those same five
    # test folds (mean PF 0.81) — that's a coarse, in-sample calibration on one dataset,
    # not an out-of-sample validation, so treat this constant as provisional pending a
    # walk-forward-clean re-check (changes/2026-07-31-filtro-regime-tendencia.md).
    min_trend_pct: float = -0.005

    def on_features(self, snapshot: FeatureSnapshot) -> TradeSignal | None:
        trend = snapshot.features.get("trend_regime_pct")
        if trend is None or trend < self.min_trend_pct:
            return None
        return self.inner.on_features(snapshot)

    def should_exit(self, snapshot: FeatureSnapshot) -> bool:
        return self.inner.should_exit(snapshot)
