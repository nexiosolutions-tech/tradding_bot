from dataclasses import dataclass

from tradingbot.backtesting.strategy import TradeSignal
from tradingbot.features.engine import FeatureSnapshot
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.dataset import FEATURE_NAMES
from tradingbot.model.promotion import run_backtest
from tradingbot.model.strategy import (
    DEFAULT_REGIME_THRESHOLD_CANDIDATES,
    ModelStrategy,
    RegimeFilteredStrategy,
    choose_regime_threshold,
)


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


def _closed_kline(symbol, close, ts):
    return MarketEvent(
        symbol=symbol,
        event_type=EventType.KLINE,
        exchange_ts=ts,
        local_ts=ts,
        sequence_id=ts,
        payload={
            "open_time": ts - 60_000,
            "close_time": ts,
            "interval": "1m",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 100.0,
            "is_closed": True,
        },
    )


def test_choose_regime_threshold_beats_no_filtering_on_a_down_then_up_calibration_window():
    """Regression test for the 2026-08-01 fix: min_trend_pct used to be picked by sweeping
    candidates against the same test folds used to report the result (in-sample). This
    builds a calibration window with a long decline (bad for an always-enter,
    exit-next-bar strategy) followed by a long climb (good for it) — the same shape as the
    real downtrend/uptrend folds — and checks the chosen threshold actually beats not
    filtering at all, using only this one (calibration-side) window."""
    prices = []
    price = 200.0
    for _ in range(320):  # long enough for the 240-candle trend EMA to reflect the decline
        price -= 0.5
        prices.append(price)
    for _ in range(320):  # then a symmetric climb back up
        price += 0.5
        prices.append(price)
    calib_events = [_closed_kline("BTCUSDT", p, (i + 1) * 60_000) for i, p in enumerate(prices)]

    inner = _AlwaysEnterStrategy()
    chosen = choose_regime_threshold(inner, calib_events, min_trades=5)

    no_filter = min(DEFAULT_REGIME_THRESHOLD_CANDIDATES)
    no_filter_pf = run_backtest(RegimeFilteredStrategy(inner=inner, min_trend_pct=no_filter), calib_events).profit_factor
    chosen_pf = run_backtest(RegimeFilteredStrategy(inner=inner, min_trend_pct=chosen), calib_events).profit_factor

    assert chosen_pf > no_filter_pf


def test_choose_regime_threshold_falls_back_to_most_permissive_when_nothing_clears_min_trades():
    """An unvalidated filter is worse than none — if every candidate starves out below
    min_trades on the calibration slice, fall back to the most permissive one rather than
    silently picking an arbitrary, unbacktested threshold."""
    events = [_closed_kline("BTCUSDT", 100.0, (i + 1) * 60_000) for i in range(3)]  # too short to trade much

    inner = _AlwaysEnterStrategy()
    chosen = choose_regime_threshold(inner, events, min_trades=1000)

    assert chosen == min(DEFAULT_REGIME_THRESHOLD_CANDIDATES)
