"""Placeholder trading strategy — spec 11, Fase 1.

A simple, documented rule used only to exercise the backtesting infrastructure end-to-end
before the ML model (spec 04) exists. Its purpose is to validate that features, costs, risk
sizing and metrics wire together correctly — not to inform any real capital decision.

Long-only: spot trading has no native short position without margin, which is outside the
current scope of spec 06.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tradingbot.features.engine import FeatureSnapshot


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    confidence: float
    stop_loss_pct: float


class Strategy(Protocol):
    def on_features(self, snapshot: FeatureSnapshot) -> TradeSignal | None:
        """Called only while flat."""

    def should_exit(self, snapshot: FeatureSnapshot) -> bool:
        """Called only while a position is open, in addition to the engine's own stop-loss check."""


@dataclass
class RsiBollingerPlaceholderStrategy:
    stop_loss_pct: float = 0.015
    rsi_oversold: float = 30.0
    rsi_exit_midline: float = 50.0

    def on_features(self, snapshot: FeatureSnapshot) -> TradeSignal | None:
        rsi = snapshot.features.get("rsi")
        lower = snapshot.features.get("bollinger_lower")
        if rsi is None or lower is None:
            return None
        if rsi < self.rsi_oversold and snapshot.close <= lower:
            return TradeSignal(
                symbol=snapshot.symbol,
                confidence=0.5,
                stop_loss_pct=self.stop_loss_pct,
            )
        return None

    def should_exit(self, snapshot: FeatureSnapshot) -> bool:
        rsi = snapshot.features.get("rsi")
        return rsi is not None and rsi >= self.rsi_exit_midline
