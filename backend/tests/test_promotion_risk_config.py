"""spec 13: run_backtest/evaluate_fold must actually use a custom RiskConfig, not always
fall back to the default — proven by observable behavior (fewer trades once the circuit
breaker trips earlier), not by peeking at engine internals.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.backtesting.strategy import TradeSignal
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.promotion import evaluate_fold, run_backtest
from tradingbot.model.promotion import PromotionCriteria
from tradingbot.risk.manager import RiskConfig


def _kline(symbol, close, ts, low=None):
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
            "low": close if low is None else low,
            "close": close,
            "volume": 100.0,
            "is_closed": True,
        },
    )


@dataclass
class AlwaysEnterWithTightStopStrategy:
    """Enters every bar it's flat with a real 2% stop-loss, never exits voluntarily — the
    only way a position closes is the engine's own stop-loss check, so each closed trade
    loses (by construction of RiskManager.position_size) exactly risk_per_trade_pct of
    equity at the time, independent of anything the strategy itself decides."""

    def on_features(self, snapshot):
        return TradeSignal(symbol=snapshot.symbol, confidence=0.9, stop_loss_pct=0.02)

    def should_exit(self, snapshot):
        return False


def _stop_loss_round_trip_events(symbol="BTCUSDT", n_round_trips=15):
    """Each round trip: bar 1 (flat -> enters at 100, stop_loss_price=98), bar 2 (low=90,
    well under 98 -> stop-loss fires)."""
    events = []
    ts = 0
    for _ in range(n_round_trips):
        ts += 60_000
        events.append(_kline(symbol, 100.0, ts))
        ts += 60_000
        events.append(_kline(symbol, 100.0, ts, low=90.0))
    return events


def test_run_backtest_default_risk_config_matches_no_risk_config_passed():
    events = _stop_loss_round_trip_events(n_round_trips=15)
    explicit_default = run_backtest(AlwaysEnterWithTightStopStrategy(), events, risk_config=RiskConfig())
    implicit_default = run_backtest(AlwaysEnterWithTightStopStrategy(), events, risk_config=None)
    assert explicit_default.num_trades == implicit_default.num_trades


def test_run_backtest_tighter_circuit_breaker_trips_earlier_with_fewer_trades():
    events = _stop_loss_round_trip_events(n_round_trips=15)

    tight_metrics = run_backtest(
        AlwaysEnterWithTightStopStrategy(), events, risk_config=RiskConfig(circuit_breaker_loss_pct=0.02)
    )
    loose_metrics = run_backtest(
        AlwaysEnterWithTightStopStrategy(), events, risk_config=RiskConfig(circuit_breaker_loss_pct=0.50)
    )

    assert tight_metrics.num_trades < loose_metrics.num_trades


def test_evaluate_fold_runs_candidate_and_baseline_under_the_same_risk_config():
    events = _stop_loss_round_trip_events(n_round_trips=15)
    tight = RiskConfig(circuit_breaker_loss_pct=0.02)

    result = evaluate_fold(
        fold_index=0,
        candidate_strategy=AlwaysEnterWithTightStopStrategy(),
        baseline_strategy=AlwaysEnterWithTightStopStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=1),
        risk_config=tight,
    )

    # Same strategy, same events, same risk_config on both sides -> identical trade counts.
    assert result.candidate_metrics.num_trades == result.baseline_metrics.num_trades
    loose_result = evaluate_fold(
        fold_index=0,
        candidate_strategy=AlwaysEnterWithTightStopStrategy(),
        baseline_strategy=AlwaysEnterWithTightStopStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=1),
        risk_config=RiskConfig(circuit_breaker_loss_pct=0.50),
    )
    assert result.candidate_metrics.num_trades < loose_result.candidate_metrics.num_trades
