from dataclasses import dataclass

from tradingbot.backtesting.strategy import TradeSignal
from tradingbot.features.engine import FeatureSnapshot
from tradingbot.model.dataset import FEATURE_NAMES
from tradingbot.model.strategy import ModelStrategy, RegimeFilteredStrategy


@dataclass
class StubModel:
    """Duck-types TrainedModel: ModelStrategy only needs feature_names and predict_proba."""

    feature_names: tuple
    score: float

    def predict_proba(self, features):
        return self.score


def _snapshot(features=None):
    return FeatureSnapshot(
        symbol="BTCUSDT",
        knowledge_ts=1,
        close=100.0,
        features=features if features is not None else {name: 0.0 for name in FEATURE_NAMES},
    )


def test_on_features_emits_signal_above_entry_threshold():
    model = StubModel(feature_names=FEATURE_NAMES, score=0.8)
    strategy = ModelStrategy(model=model, entry_threshold=0.7, exit_threshold=0.4, stop_loss_pct=0.02)

    signal = strategy.on_features(_snapshot())
    assert signal is not None
    assert signal.confidence == 0.8
    assert signal.stop_loss_pct == 0.02


def test_on_features_returns_none_below_entry_threshold():
    model = StubModel(feature_names=FEATURE_NAMES, score=0.5)
    strategy = ModelStrategy(model=model, entry_threshold=0.7, exit_threshold=0.4, stop_loss_pct=0.02)

    assert strategy.on_features(_snapshot()) is None


def test_on_features_returns_none_when_features_incomplete():
    model = StubModel(feature_names=FEATURE_NAMES, score=0.9)
    strategy = ModelStrategy(model=model, entry_threshold=0.7, exit_threshold=0.4, stop_loss_pct=0.02)

    incomplete = {name: 0.0 for name in FEATURE_NAMES[:-1]}  # missing one required feature
    assert strategy.on_features(_snapshot(incomplete)) is None


def test_should_exit_below_exit_threshold():
    model = StubModel(feature_names=FEATURE_NAMES, score=0.3)
    strategy = ModelStrategy(model=model, entry_threshold=0.7, exit_threshold=0.4, stop_loss_pct=0.02)

    assert strategy.should_exit(_snapshot()) is True


def test_should_not_exit_above_exit_threshold():
    model = StubModel(feature_names=FEATURE_NAMES, score=0.6)
    strategy = ModelStrategy(model=model, entry_threshold=0.7, exit_threshold=0.4, stop_loss_pct=0.02)

    assert strategy.should_exit(_snapshot()) is False


@dataclass
class _AlwaysEnterStrategy:
    """Stub inner strategy — always signals, so tests isolate the wrapper's own gating
    logic instead of depending on some other strategy's decision."""

    def on_features(self, snapshot):
        return TradeSignal(symbol=snapshot.symbol, confidence=0.9, stop_loss_pct=0.02)

    def should_exit(self, snapshot):
        return True


def test_regime_filter_allows_entry_when_trend_is_at_or_above_threshold():
    inner = _AlwaysEnterStrategy()
    strategy = RegimeFilteredStrategy(inner=inner, min_trend_pct=0.0)

    signal = strategy.on_features(_snapshot({"trend_regime_pct": 0.01}))
    assert signal is not None
    assert signal.confidence == 0.9


def test_regime_filter_blocks_entry_when_trend_is_below_threshold():
    inner = _AlwaysEnterStrategy()
    strategy = RegimeFilteredStrategy(inner=inner, min_trend_pct=0.0)

    assert strategy.on_features(_snapshot({"trend_regime_pct": -0.01})) is None


def test_regime_filter_blocks_entry_when_trend_feature_missing():
    inner = _AlwaysEnterStrategy()
    strategy = RegimeFilteredStrategy(inner=inner, min_trend_pct=0.0)

    assert strategy.on_features(_snapshot({})) is None


def test_regime_filter_default_threshold_is_slightly_negative():
    """A hard 0.0 cutoff measured worse than no filter at all (2026-08-01 A/B on the
    90-day cache) because trend_regime_pct oscillates slightly negative during ordinary
    pullbacks inside an uptrend — -0.005 was the best of the thresholds tried. Regression
    guard so this doesn't silently drift back to 0.0."""
    inner = _AlwaysEnterStrategy()
    strategy = RegimeFilteredStrategy(inner=inner)

    assert strategy.min_trend_pct == -0.005


def test_regime_filter_never_blocks_exits():
    """The filter only gates new entries — a position already open must still be able to
    exit regardless of what the trend regime looks like now."""
    inner = _AlwaysEnterStrategy()
    strategy = RegimeFilteredStrategy(inner=inner, min_trend_pct=0.0)

    assert strategy.should_exit(_snapshot({"trend_regime_pct": -0.05})) is True
