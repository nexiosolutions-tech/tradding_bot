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


def _rising_events_with_dips(symbol="BTCUSDT", n=60, start=100.0):
    """Net-upward overall (like _rising_events) but with a small real dip every 10 bars, so
    AlwaysProfitableStrategy has a handful of real losing trades among many winners —
    empirically verified (30 trades, win_rate 0.8, PF~3.8, gross_loss > 0) rather than
    reasoned about, since a single one-off dip at a fixed index proved too fragile against
    warm-up and the strategy's own 2-bar trade-cycle alignment, and a dip every 4 bars
    turned out to hit roughly half of all trades, not a small minority (2026-08-19). Keeps
    tests using it for drawdown/baseline behavior from accidentally also exercising the
    zero-loss gate (evaluate_fold) when that's not what they're testing — see
    test_evaluate_fold_rejects_fold_with_zero_losing_trades below for that gate on its
    own, using the pure _rising_events (never dips, always zero losses by construction)."""
    price = start
    prices = []
    for i in range(n):
        price += -0.3 if (i + 1) % 10 == 0 else 1.0
        prices.append(price)
    return [_closed_kline(symbol, p, (i + 1) * 60_000) for i, p in enumerate(prices)]


@dataclass
class AlwaysTradeStrategy:
    """Buys every bar it's flat, exits the very next bar — used with a mixed price series
    to produce a real trade set that's a partial (not total) net loser: some wins, but
    profit_factor still under 1."""

    def on_features(self, snapshot):
        return TradeSignal(symbol=snapshot.symbol, confidence=0.9, stop_loss_pct=0.5)

    def should_exit(self, snapshot):
        return True


def _mixed_result_events(symbol="BTCUSDT", start=100.0):
    # Mostly small losing steps with occasional larger winning ones — real profit_factor
    # ends up between 0 and 1 (some wins, net loser), not the all-losses 0.0 edge case.
    deltas = [-0.3, -0.3, -0.3, 2.0, -0.3, -0.3, -0.3, -0.3, 2.0, -0.3, -0.3, -0.3, -0.3, -0.3, 2.0, -0.3, -0.3, -0.3]
    price = start
    events = [_closed_kline(symbol, price, 60_000)]
    for i, delta in enumerate(deltas):
        price += delta
        events.append(_closed_kline(symbol, price, (i + 2) * 60_000))
    return events


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
    events = _rising_events_with_dips(n=60)
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
    events = _rising_events_with_dips(n=60)
    result = evaluate_fold(
        fold_index=0,
        candidate_strategy=AlwaysProfitableStrategy(),
        baseline_strategy=NeverTradeStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=5, max_drawdown_regression_pct=1.0),
    )
    assert result.candidate_metrics.num_trades >= 5
    assert result.candidate_wins is True


def test_evaluate_fold_rejects_candidate_with_negative_net_expectancy_even_if_it_beats_baseline():
    """The gap this closes: a candidate that is a net loser overall (profit_factor < 1)
    could still 'beat' an even-worse (or never-trading) baseline on the relative
    profit-factor-vs-baseline check alone — being 'less bad' than a broken baseline isn't
    the same as being profitable. The absolute min_profit_factor gate must catch this
    independently of whatever the baseline looks like."""
    events = _mixed_result_events()
    result = evaluate_fold(
        fold_index=0,
        candidate_strategy=AlwaysTradeStrategy(),
        baseline_strategy=NeverTradeStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=5),
    )
    assert result.candidate_metrics.num_trades >= 5
    assert 0.0 < result.candidate_metrics.profit_factor < 1.0  # a real, partial loser
    assert result.candidate_wins is False
    assert "expectância" in result.reason.lower()


def test_evaluate_fold_rejects_fold_with_zero_losing_trades():
    """Regression guard (2026-08-19): profit_factor is inf whenever gross_loss == 0
    (backtesting/metrics.py) — inf clears min_profit_factor, the beats-baseline check, and
    (if the fold also happened to have low drawdown) the drawdown check, all trivially,
    regardless of how few trades or how much luck produced the all-winning streak.
    min_trades alone doesn't guard against this: a fold with exactly min_trades winners and
    zero losers passes every other gate. Confirmed here with a real monotonically rising
    series where AlwaysProfitableStrategy's buy-then-sell-next-bar never loses — the exact
    shape that used to slip through before this gate existed (it broke this test's own
    sibling tests above, which is why they were moved to _rising_events_with_dips)."""
    events = _rising_events(n=60)
    result = evaluate_fold(
        fold_index=0,
        candidate_strategy=AlwaysProfitableStrategy(),
        baseline_strategy=NeverTradeStrategy(),
        events=events,
        criteria=PromotionCriteria(min_trades=5, max_drawdown_regression_pct=1.0),
    )
    assert result.candidate_metrics.num_trades >= 5
    assert result.candidate_metrics.gross_loss == 0.0
    assert result.candidate_wins is False
    assert "sem nenhuma perda" in result.reason


def _fold(wins: bool) -> FoldResult:
    empty_metrics = compute_metrics([], [])
    return FoldResult(0, empty_metrics, empty_metrics, wins, "stub")


def test_decide_promotion_requires_every_fold_to_win():
    assert decide_promotion([_fold(True), _fold(True), _fold(True)]) is True
    assert decide_promotion([_fold(True), _fold(False), _fold(True)]) is False


def test_decide_promotion_false_with_no_folds():
    assert decide_promotion([]) is False
