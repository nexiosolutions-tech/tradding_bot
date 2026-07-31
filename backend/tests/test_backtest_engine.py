from dataclasses import dataclass

import pytest

from tradingbot.backtesting.costs import FeeModel, SlippageModel
from tradingbot.backtesting.engine import BacktestEngine
from tradingbot.backtesting.strategy import TradeSignal
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.risk.manager import RiskConfig


def _closed_kline(symbol, close, ts, low=None, high=None, volume=100.0):
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
            "high": close if high is None else high,
            "low": close if low is None else low,
            "close": close,
            "volume": volume,
            "is_closed": True,
        },
    )


@dataclass
class ScriptedStrategy:
    """Deterministic strategy for testing the engine in isolation from real indicator math."""

    entry_at_ts: int
    stop_loss_pct: float | None
    exit_at_ts: int | None = None

    def on_features(self, snapshot):
        if snapshot.knowledge_ts == self.entry_at_ts:
            return TradeSignal(symbol=snapshot.symbol, confidence=1.0, stop_loss_pct=self.stop_loss_pct)
        return None

    def should_exit(self, snapshot):
        return self.exit_at_ts is not None and snapshot.knowledge_ts == self.exit_at_ts


def _no_cost_engine(strategy, initial_capital=1_000.0, risk_config=None):
    return BacktestEngine(
        strategy=strategy,
        risk_config=risk_config or RiskConfig(risk_per_trade_pct=0.10, circuit_breaker_loss_pct=0.99),
        fee_model=FeeModel(taker_fee_pct=0.0),
        slippage_model=SlippageModel(slippage_bps=0.0),
        initial_capital=initial_capital,
    )


def test_signal_without_stop_loss_is_structurally_rejected():
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=None)
    engine = _no_cost_engine(strategy)

    events = [_closed_kline("BTCUSDT", 100.0, ts) for ts in (60_000, 120_000, 180_000)]
    engine.run(events)

    assert engine.trades == []
    assert "missing_stop_loss" in engine.rejected_signals


def test_stop_loss_hit_closes_position_at_stop_price():
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05)
    engine = _no_cost_engine(strategy)

    events = [
        _closed_kline("BTCUSDT", 100.0, 60_000),  # entry
        _closed_kline("BTCUSDT", 90.0, 120_000),  # drops through the 5% stop
    ]
    engine.run(events)

    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.pnl < 0


def test_stop_loss_triggers_on_intrabar_wick_even_if_candle_closes_above_it():
    """The blind spot test_stop_loss_hit_closes_position_at_stop_price didn't cover: a
    candle can wick through the stop and still close back above it. A real resting stop
    order fires on the wick, regardless of the close — the backtest must match that, not
    silently let the position ride because the candle happened to close green."""
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05)
    engine = _no_cost_engine(strategy)

    events = [
        _closed_kline("BTCUSDT", 100.0, 60_000),  # entry @ 100, stop @ 95
        # wicks down through 95 intrabar, but closes back above the stop at 98
        _closed_kline("BTCUSDT", 98.0, 120_000, low=93.0, high=100.0),
        _closed_kline("BTCUSDT", 99.0, 180_000),  # would never be reached if the bug persisted
    ]
    engine.run(events)

    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_ts == 120_000  # triggered on the wick's candle, not a later one
    assert trade.exit_price == pytest.approx(95.0)  # fills at the stop price, not the wick low
    assert trade.pnl < 0


def test_signal_exit_closes_at_market_price_with_no_stop_hit():
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05, exit_at_ts=180_000)
    engine = _no_cost_engine(strategy)

    events = [
        _closed_kline("BTCUSDT", 100.0, 60_000),
        _closed_kline("BTCUSDT", 105.0, 120_000),
        _closed_kline("BTCUSDT", 110.0, 180_000),
    ]
    engine.run(events)

    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "signal_exit"
    assert trade.exit_price == pytest.approx(110.0)
    assert trade.pnl > 0


def test_open_position_closed_at_end_of_data_if_never_exited():
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05)
    engine = _no_cost_engine(strategy)

    events = [_closed_kline("BTCUSDT", 100.0, 60_000), _closed_kline("BTCUSDT", 101.0, 120_000)]
    engine.run(events)

    assert len(engine.trades) == 1
    assert engine.trades[0].exit_reason == "end_of_data"


def test_fees_and_slippage_reduce_pnl():
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.05, exit_at_ts=120_000)
    engine = BacktestEngine(
        strategy=strategy,
        risk_config=RiskConfig(risk_per_trade_pct=0.10),
        fee_model=FeeModel(taker_fee_pct=0.01),
        slippage_model=SlippageModel(slippage_bps=100.0),
        initial_capital=1_000.0,
    )

    events = [
        _closed_kline("BTCUSDT", 100.0, 60_000),
        _closed_kline("BTCUSDT", 100.0, 120_000),  # flat price — a free market would be breakeven
    ]
    engine.run(events)

    assert len(engine.trades) == 1
    # flat price but costs applied on both legs -> guaranteed loss
    assert engine.trades[0].pnl < 0


@dataclass
class FeatureRecordingStrategy:
    seen_feature_keys: list = None

    def __post_init__(self):
        self.seen_feature_keys = []

    def on_features(self, snapshot):
        self.seen_feature_keys.append(set(snapshot.features))
        return None

    def should_exit(self, snapshot):
        return False


def test_warm_up_primes_indicators_without_recording_trades_or_equity():
    strategy = FeatureRecordingStrategy()
    engine = _no_cost_engine(strategy)

    warmup_events = [_closed_kline("BTCUSDT", 100.0 + i * 0.1, (i + 1) * 60_000) for i in range(35)]
    engine.warm_up(warmup_events)

    assert engine.trades == []
    assert engine.equity_curve == []
    assert engine.equity == 1_000.0

    real_events = [_closed_kline("BTCUSDT", 103.6, 36 * 60_000)]
    engine.run(real_events)

    assert len(strategy.seen_feature_keys) == 1
    assert "rsi" in strategy.seen_feature_keys[0]  # warmed up, not starting from scratch


def test_circuit_breaker_blocks_new_entries_after_drawdown():
    strategy = ScriptedStrategy(entry_at_ts=60_000, stop_loss_pct=0.50)
    engine = _no_cost_engine(
        strategy,
        risk_config=RiskConfig(
            risk_per_trade_pct=0.50,
            circuit_breaker_loss_pct=0.05,
            max_concurrent_exposure_pct=1.0,
        ),
    )

    events = [
        _closed_kline("BTCUSDT", 100.0, 60_000),  # entry, huge size due to 50% risk
        _closed_kline("BTCUSDT", 94.0, 120_000),  # 6% drop -> equity drawdown trips breaker
    ]
    engine.run(events)

    assert engine.risk.circuit_breaker_triggered is True

    # a second scripted entry after the breaker trips should never be taken
    strategy2 = ScriptedStrategy(entry_at_ts=180_000, stop_loss_pct=0.05)
    engine.strategy = strategy2
    engine.run([_closed_kline("BTCUSDT", 90.0, 180_000)])
    assert all(t.entry_ts != 180_000 for t in engine.trades)
