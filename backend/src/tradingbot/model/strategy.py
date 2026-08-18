"""ModelStrategy — spec 04's calibrated score wired into the same Strategy protocol used
by the backtest engine (spec 07) and, later, the execution layer (spec 06). This is what
replaces the Fase 1 placeholder rule once a model has been promoted.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.backtesting.strategy import Strategy, TradeSignal
from tradingbot.features.engine import FeatureSnapshot
from tradingbot.ingestion.schema import MarketEvent
from tradingbot.model.promotion import run_backtest
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


# -0.005, not 0.0: trend_regime_pct is close vs. a 240-candle (~4h) EMA, which lags and
# oscillates slightly negative during ordinary pullbacks inside an uptrend. This is only
# the fallback for when there's no calibration data to derive a fold-specific threshold
# from (e.g. the Fase 1 placeholder, which isn't trained/calibrated at all) — a real
# candidate model picks its own value from training-side data via choose_regime_threshold
# below.
PLACEHOLDER_MIN_TREND_PCT = -0.005


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
    min_trend_pct: float = PLACEHOLDER_MIN_TREND_PCT

    def on_features(self, snapshot: FeatureSnapshot) -> TradeSignal | None:
        trend = snapshot.features.get("trend_regime_pct")
        if trend is None or trend < self.min_trend_pct:
            return None
        return self.inner.on_features(snapshot)

    def should_exit(self, snapshot: FeatureSnapshot) -> bool:
        return self.inner.should_exit(snapshot)


# 2026-07-31's first cut picked -0.005 by sweeping candidates against the same five test
# folds used to report the result — in-sample calibration, the same mistake
# min_profit_factor's small-sample caveat already warned about
# (changes/2026-07-31-criterio-promocao-expectancia-positiva.md). This mirrors
# choose_thresholds (training.py): pick from calibration-slice events only, never the
# out-of-sample test fold.
DEFAULT_REGIME_THRESHOLD_CANDIDATES: tuple[float, ...] = (-0.02, -0.015, -0.01, -0.005, 0.0, 0.005, 0.01)


def choose_regime_threshold(
    inner_strategy: Strategy,
    calib_events: list[MarketEvent],
    min_trades: int,
    warmup_events: list[MarketEvent] | None = None,
    candidates: tuple[float, ...] = DEFAULT_REGIME_THRESHOLD_CANDIDATES,
    risk_config=None,
    reference_symbol: str | None = None,
) -> float:
    """Backtests each candidate min_trend_pct against the calibration-side events only and
    keeps whichever profit factor is best. Falls back to the most permissive candidate (the
    lowest — blocks the fewest entries) when none clears min_trades on this slice: an
    unvalidated filter is worse than none, exactly the failure mode this function exists to
    avoid repeating. risk_config should match whatever the candidate is ultimately evaluated
    under (spec 13) — calibrating against a different risk profile than it's tested with
    would be a subtle inconsistency."""
    best_threshold = min(candidates)
    best_pf = float("-inf")
    for candidate in candidates:
        strategy = RegimeFilteredStrategy(inner=inner_strategy, min_trend_pct=candidate)
        metrics = run_backtest(
            strategy, calib_events, warmup_events=warmup_events, risk_config=risk_config, reference_symbol=reference_symbol
        )
        if metrics.num_trades < min_trades:
            continue
        if metrics.profit_factor > best_pf:
            best_pf = metrics.profit_factor
            best_threshold = candidate
    return best_threshold
