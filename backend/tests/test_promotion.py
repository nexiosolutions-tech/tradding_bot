from dataclasses import dataclass

from tradingbot.backtesting.metrics import compute_metrics
from tradingbot.backtesting.strategy import TradeSignal
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.promotion import FoldResult, PromotionCriteria, decide_promotion, evaluate_fold


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


@dataclass
class NeverTradeStrategy:
    def on_features(self, snapshot):
        return None

    def should_exit(self, snapshot):
        return False


@dataclass
class AlwaysProfitableStrategy:
    """Buys every bar it's flat, sells on the very next bar — with a rising price series
    this produces a string of winning trades, enough to exercise the promotion comparison."""

    entry_count: int = 0

    def on_features(self, snapshot):
        self.entry_count += 1
        return TradeSignal(symbol=snapshot.symbol, confidence=0.9, stop_loss_pct=0.5)

    def should_exit(self, snapshot):
        return True  # exit on the very next bar after entry


def _rising_events(symbol="BTCUSDT", n=60, start=100.0, step=1.0):
    return [_closed_kline(symbol, start + i * step, (i + 1) * 60_000) for i in range(n)]


def test_evaluate_fold_fails_on_insufficient_sample():
    events = _rising_events(n=10)
    result = evaluate_fold(
        fold_index=0,
        candidate_strategy=NeverTradeStrategy(),
        baseline_strategy=NeverTradeStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=5),
    )
    assert result.candidate_wins is False
    assert "amostra insuficiente" in result.reason


def test_evaluate_fold_rejects_candidate_that_underperforms_zero_drawdown_baseline():
    """A baseline that never trades has, by construction, zero drawdown. Any strategy that
    actually trades incurs at least fee/slippage-driven dips, so it cannot beat a
    never-trade baseline on the drawdown axis alone — evaluate_fold must catch that
    instead of promoting on profit factor alone."""
    events = _rising_events(n=60)
    result = evaluate_fold(
        fold_index=0,
        candidate_strategy=AlwaysProfitableStrategy(),
        baseline_strategy=NeverTradeStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=5),
    )
    assert result.candidate_metrics.num_trades >= 5
    assert result.candidate_wins is False
    assert "drawdown" in result.reason


def test_evaluate_fold_promotes_on_profit_factor_when_drawdown_gate_is_relaxed():
    events = _rising_events(n=60)
    result = evaluate_fold(
        fold_index=0,
        candidate_strategy=AlwaysProfitableStrategy(),
        baseline_strategy=NeverTradeStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=5, max_drawdown_regression_pct=1.0),
    )
    assert result.candidate_metrics.num_trades >= 5
    assert result.candidate_wins is True


def _fold(wins: bool) -> FoldResult:
    empty_metrics = compute_metrics([], [])
    return FoldResult(0, empty_metrics, empty_metrics, wins, "stub")


def test_decide_promotion_requires_every_fold_to_win():
    assert decide_promotion([_fold(True), _fold(True), _fold(True)]) is True
    assert decide_promotion([_fold(True), _fold(False), _fold(True)]) is False


def test_decide_promotion_false_with_no_folds():
    assert decide_promotion([]) is False
