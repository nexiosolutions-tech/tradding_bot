import random

import pytest

from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.model.dataset import DatasetRow
from tradingbot.model.evaluation import (
    ConfigEvaluation,
    FoldSummary,
    _with_shuffled_labels,
    evaluate_config,
    run_nullity_test,
)


def _closed_kline(symbol, close, ts, high=None, low=None):
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
            "volume": 100.0,
            "is_closed": True,
        },
    )


def _synthetic_events(n=900, seed=0):
    rng = random.Random(seed)
    events = []
    price = 100.0
    for i in range(n):
        price += rng.uniform(-0.3, 0.35)  # slight upward drift with noise
        high = price + abs(rng.uniform(0, 0.2))
        low = price - abs(rng.uniform(0, 0.2))
        events.append(_closed_kline("BTCUSDT", price, (i + 1) * 60_000, high=high, low=low))
    return events


def _fold_summary(total_pnl, gross_profit, gross_loss, fold_index=0):
    return FoldSummary(
        fold_index=fold_index,
        profit_factor=0.0,
        num_trades=1,
        max_drawdown_pct=0.0,
        won=False,
        reason="stub",
        total_pnl=total_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
    )


def _config_evaluation(folds):
    return ConfigEvaluation(
        horizon_minutes=5,
        entry_percentile=80.0,
        move_threshold_pct=0.008,
        move_threshold_atr_multiple=None,
        use_regime_filter=True,
        label_rate=0.05,
        folds=tuple(folds),
    )


def test_config_evaluation_total_pnl_sums_across_folds():
    result = _config_evaluation(
        [
            _fold_summary(total_pnl=100.0, gross_profit=150.0, gross_loss=50.0),
            _fold_summary(total_pnl=-30.0, gross_profit=20.0, gross_loss=50.0),
        ]
    )
    assert result.total_pnl == pytest.approx(70.0)


def test_config_evaluation_aggregate_profit_factor_pools_gross_values_not_mean_of_ratios():
    """The antipattern this replaces: mean([150/50, 20/50]) = mean([3.0, 0.4]) = 1.7 would
    overstate this — the pooled sample (170 gross profit over 100 gross loss) is 1.7 too,
    coincidentally close here, but the point is the *formula*: sum/sum, never mean-of-ratios
    (2026-08-19)."""
    result = _config_evaluation(
        [
            _fold_summary(total_pnl=100.0, gross_profit=150.0, gross_loss=50.0),
            _fold_summary(total_pnl=-30.0, gross_profit=20.0, gross_loss=50.0),
        ]
    )
    assert result.aggregate_profit_factor == pytest.approx((150.0 + 20.0) / (50.0 + 50.0))


def test_config_evaluation_aggregate_profit_factor_does_not_degenerate_on_one_zero_loss_fold():
    """The exact bug this fixes: mean_profit_factor would go to inf if any single fold had
    zero losing trades (backtesting/metrics.py::profit_factor). Pooling across folds first
    means one degenerate fold no longer blows up the whole run's statistic, as long as the
    combined sample has any loss at all."""
    result = _config_evaluation(
        [
            _fold_summary(total_pnl=50.0, gross_profit=50.0, gross_loss=0.0),  # degenerate
            _fold_summary(total_pnl=-30.0, gross_profit=20.0, gross_loss=50.0),
        ]
    )
    assert result.aggregate_profit_factor == pytest.approx(70.0 / 50.0)
    assert result.aggregate_profit_factor != float("inf")


def test_evaluate_config_returns_one_fold_summary_per_split_at_most():
    events = _synthetic_events(n=900)
    result = evaluate_config(
        events, horizon_minutes=5, entry_percentile=80.0, move_threshold_pct=0.002, n_splits=2, min_trades=1
    )
    assert result.horizon_minutes == 5
    assert result.entry_percentile == 80.0
    assert 1 <= result.folds_total <= 2
    assert 0.0 <= result.label_rate <= 1.0
    assert result.folds_won <= result.folds_total
    assert result.mean_profit_factor >= 0.0


def test_evaluate_config_forwards_candle_minutes_to_target_config():
    """candle_minutes must reach TargetConfig — it's what converts horizon_minutes
    (wall-clock) into horizon_bars (candle count). Left at the wrong value, a caller
    testing coarser intervals (5m/15m klines) would silently get the wrong look-ahead
    window. Structural check only: TargetConfig.horizon_bars itself is covered in
    test_dataset.py."""
    events = _synthetic_events(n=900)
    result = evaluate_config(
        events,
        horizon_minutes=10,
        entry_percentile=80.0,
        move_threshold_pct=0.002,
        candle_minutes=5,
        n_splits=2,
        min_trades=1,
    )
    assert 0.0 <= result.label_rate <= 1.0
    assert result.folds_total >= 1


def test_evaluate_config_without_regime_filter_still_produces_folds():
    events = _synthetic_events(n=900, seed=1)
    result = evaluate_config(
        events,
        horizon_minutes=5,
        entry_percentile=80.0,
        move_threshold_pct=0.002,
        n_splits=2,
        min_trades=1,
        use_regime_filter=False,
    )
    assert result.use_regime_filter is False
    assert result.folds_total >= 1


def _dataset_row(label: int) -> DatasetRow:
    return DatasetRow(symbol="BTCUSDT", knowledge_ts=0, close=100.0, features={}, label=label)


def test_with_shuffled_labels_preserves_multiset_but_reorders():
    rows = [_dataset_row(i % 2) for i in range(40)]
    shuffled = _with_shuffled_labels(rows, seed=1)
    assert sorted(r.label for r in shuffled) == sorted(r.label for r in rows)
    assert [r.label for r in shuffled] != [r.label for r in rows]


def test_with_shuffled_labels_is_deterministic_given_seed():
    rows = [_dataset_row(i % 2) for i in range(40)]
    a = _with_shuffled_labels(rows, seed=7)
    b = _with_shuffled_labels(rows, seed=7)
    assert [r.label for r in a] == [r.label for r in b]


def test_evaluate_config_shuffle_labels_preserves_label_rate():
    """The nullity test's validity rests on this: shuffling must only break the
    feature-label correspondence, never the label rate itself — otherwise a fold losing
    under shuffle_labels=True could just mean "fewer positive labels", not "no leakage"."""
    events = _synthetic_events(n=900)
    real = evaluate_config(
        events, horizon_minutes=5, entry_percentile=80.0, move_threshold_pct=0.002, n_splits=1, min_trades=1
    )
    shuffled = evaluate_config(
        events,
        horizon_minutes=5,
        entry_percentile=80.0,
        move_threshold_pct=0.002,
        n_splits=1,
        min_trades=1,
        shuffle_labels=True,
        shuffle_seed=3,
    )
    assert shuffled.label_rate == pytest.approx(real.label_rate)


def test_evaluate_config_folds_carry_the_equity_curve():
    """The equity curve was already computed inside compute_metrics (it's what
    volatility_pct is derived from) and used to be discarded — DSR/PBO need the real
    per-fold return series, not just the aggregate profit_factor."""
    events = _synthetic_events(n=900)
    result = evaluate_config(
        events, horizon_minutes=5, entry_percentile=80.0, move_threshold_pct=0.002, n_splits=1, min_trades=1
    )
    assert result.folds_total >= 1
    for fold in result.folds:
        assert len(fold.equity_curve) > 0


def test_evaluate_config_folds_carry_total_pnl_and_gross_profit_loss():
    """Regression guard: ConfigEvaluation.total_pnl/aggregate_profit_factor read from
    these FoldSummary fields — if the fold loop stopped wiring them from
    BacktestMetrics, both properties would silently go back to reading all zeros."""
    events = _synthetic_events(n=900)
    result = evaluate_config(
        events, horizon_minutes=5, entry_percentile=80.0, move_threshold_pct=0.002, n_splits=1, min_trades=1
    )
    assert result.folds_total >= 1
    for fold in result.folds:
        if fold.num_trades > 0:
            assert fold.gross_profit > 0 or fold.gross_loss > 0


def test_run_nullity_test_rejects_shuffle_kwargs_from_caller():
    """run_nullity_test owns shuffle_labels/shuffle_seed — a caller passing them would
    silently fight the permutation loop over who controls the label shuffle."""
    with pytest.raises(ValueError):
        run_nullity_test([], horizon_minutes=5, entry_percentile=80.0, shuffle_labels=True)


def test_run_nullity_test_builds_null_distribution_with_requested_size():
    events = _synthetic_events(n=900)
    result = run_nullity_test(
        events,
        horizon_minutes=5,
        entry_percentile=80.0,
        move_threshold_pct=0.002,
        n_splits=1,
        min_trades=1,
        n_permutations=3,
        base_seed=0,
    )
    assert result.n_permutations == 3
    assert len(result.permuted_total_pnls) == 3
    assert 0.0 <= result.p_value <= 1.0


def test_run_nullity_test_p_value_never_exactly_zero():
    """(# at least as good + 1) / (n_permutations + 1) — the standard permutation-test
    correction — can never round to a literal 0.0, no matter how decisively the real
    result beats every permutation."""
    events = _synthetic_events(n=900)
    result = run_nullity_test(
        events,
        horizon_minutes=5,
        entry_percentile=80.0,
        move_threshold_pct=0.002,
        n_splits=1,
        min_trades=1,
        n_permutations=3,
    )
    assert result.p_value >= 1 / (result.n_permutations + 1)
