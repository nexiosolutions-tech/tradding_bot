"""Direct unit coverage for RsiBollingerPlaceholderStrategy — previously only exercised
indirectly through real training runs, which is how a regression (removing
bollinger_lower from the shared features dict silently zeroed out every baseline trade)
went undetected by the test suite on 2026-07-31."""

from dataclasses import dataclass

from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy


@dataclass
class _FakeSnapshot:
    close: float
    features: dict
    symbol: str = "BTCUSDT"


def test_enters_when_oversold_and_at_or_below_lower_band():
    strategy = RsiBollingerPlaceholderStrategy()
    snapshot = _FakeSnapshot(close=100.0, features={"rsi": 25.0, "bollinger_percent_b": -0.05})
    signal = strategy.on_features(snapshot)
    assert signal is not None
    assert signal.stop_loss_pct == strategy.stop_loss_pct


def test_does_not_enter_when_oversold_but_price_within_bands():
    strategy = RsiBollingerPlaceholderStrategy()
    snapshot = _FakeSnapshot(close=100.0, features={"rsi": 25.0, "bollinger_percent_b": 0.4})
    assert strategy.on_features(snapshot) is None


def test_does_not_enter_when_at_lower_band_but_not_oversold():
    strategy = RsiBollingerPlaceholderStrategy()
    snapshot = _FakeSnapshot(close=100.0, features={"rsi": 45.0, "bollinger_percent_b": -0.05})
    assert strategy.on_features(snapshot) is None


def test_no_entry_signal_during_indicator_warmup():
    strategy = RsiBollingerPlaceholderStrategy()
    assert strategy.on_features(_FakeSnapshot(close=100.0, features={})) is None
    assert strategy.on_features(_FakeSnapshot(close=100.0, features={"rsi": 20.0})) is None


def test_exits_when_rsi_recovers_to_midline():
    strategy = RsiBollingerPlaceholderStrategy()
    assert strategy.should_exit(_FakeSnapshot(close=100.0, features={"rsi": 55.0})) is True
    assert strategy.should_exit(_FakeSnapshot(close=100.0, features={"rsi": 40.0})) is False
    assert strategy.should_exit(_FakeSnapshot(close=100.0, features={})) is False
