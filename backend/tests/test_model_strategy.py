from dataclasses import dataclass

from tradingbot.features.engine import FeatureSnapshot
from tradingbot.model.dataset import FEATURE_NAMES
from tradingbot.model.strategy import ModelStrategy


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
