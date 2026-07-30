"""ModelStrategy — spec 04's calibrated score wired into the same Strategy protocol used
by the backtest engine (spec 07) and, later, the execution layer (spec 06). This is what
replaces the Fase 1 placeholder rule once a model has been promoted.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.backtesting.strategy import TradeSignal
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
