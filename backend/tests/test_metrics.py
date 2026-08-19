import pytest

from tradingbot.backtesting.engine import ClosedTrade
from tradingbot.ingestion.schema import EventType, MarketEvent
from tradingbot.backtesting.metrics import (
    buy_and_hold_equity_curve,
    compute_metrics,
    exposure_pct,
    flat_equity_curve,
    gross_loss,
    gross_profit,
    max_drawdown,
    profit_factor,
    return_over_drawdown,
    return_over_volatility,
    total_return_pct,
    volatility_pct,
    win_rate,
)


def _trade(pnl: float, entry_ts: int = 0, exit_ts: int = 0) -> ClosedTrade:
    return ClosedTrade(
        symbol="BTCUSDT",
        entry_ts=entry_ts,
        exit_ts=exit_ts,
        entry_price=100,
        exit_price=100,
        size=1,
        pnl=pnl,
        fees_paid=0.1,
        exit_reason="signal_exit",
    )


def test_win_rate_counts_positive_pnl_trades():
    trades = [_trade(10), _trade(-5), _trade(3), _trade(-1)]
    assert win_rate(trades) == pytest.approx(0.5)


def test_win_rate_is_zero_with_no_trades():
    assert win_rate([]) == 0.0


def test_profit_factor_ratio_of_gross_profit_to_gross_loss():
    trades = [_trade(20), _trade(-10), _trade(-5)]
    assert profit_factor(trades) == pytest.approx(20 / 15)


def test_profit_factor_is_infinite_with_no_losses():
    trades = [_trade(20), _trade(5)]
    assert profit_factor(trades) == float("inf")


def test_gross_profit_sums_only_positive_pnl():
    trades = [_trade(20), _trade(-10), _trade(5), _trade(-3)]
    assert gross_profit(trades) == pytest.approx(25)


def test_gross_loss_sums_only_negative_pnl_as_a_positive_number():
    trades = [_trade(20), _trade(-10), _trade(5), _trade(-3)]
    assert gross_loss(trades) == pytest.approx(13)


def test_compute_metrics_exposes_gross_profit_and_gross_loss():
    trades = [_trade(20, entry_ts=0, exit_ts=1), _trade(-10, entry_ts=1, exit_ts=2)]
    metrics = compute_metrics(trades, [(0, 1000.0), (1, 1000.0), (2, 1000.0)], initial_capital=1000.0)
    assert metrics.gross_profit == pytest.approx(20)
    assert metrics.gross_loss == pytest.approx(10)


def test_max_drawdown_measures_largest_peak_to_trough_drop():
    equity_curve = [
        (0, 1000.0),
        (1, 1200.0),  # new peak
        (2, 900.0),  # -25% from peak
        (3, 1100.0),
        (4, 1150.0),
    ]
    result = max_drawdown(equity_curve)
    assert result.max_drawdown_pct == pytest.approx(0.25)


def test_max_drawdown_is_zero_for_monotonically_increasing_equity():
    equity_curve = [(0, 1000.0), (1, 1100.0), (2, 1200.0)]
    result = max_drawdown(equity_curve)
    assert result.max_drawdown_pct == 0.0


def test_total_return_pct_measures_change_from_initial_capital():
    equity_curve = [(0, 1000.0), (1, 1100.0), (2, 1250.0)]
    assert total_return_pct(equity_curve, initial_capital=1000.0) == pytest.approx(0.25)


def test_total_return_pct_is_zero_with_no_equity_curve():
    assert total_return_pct([], initial_capital=1000.0) == 0.0


def test_volatility_pct_is_zero_for_flat_equity():
    equity_curve = [(0, 1000.0), (1, 1000.0), (2, 1000.0)]
    assert volatility_pct(equity_curve) == 0.0


def test_volatility_pct_is_positive_for_bumpy_equity():
    equity_curve = [(0, 1000.0), (1, 1100.0), (2, 950.0), (3, 1080.0)]
    assert volatility_pct(equity_curve) > 0.0


def test_return_over_drawdown_is_calmar_like_ratio():
    assert return_over_drawdown(total_return=0.20, max_dd_pct=0.10) == pytest.approx(2.0)


def test_return_over_drawdown_is_infinite_with_no_drawdown_and_positive_return():
    assert return_over_drawdown(total_return=0.20, max_dd_pct=0.0) == float("inf")


def test_return_over_drawdown_is_zero_with_no_drawdown_and_no_return():
    assert return_over_drawdown(total_return=0.0, max_dd_pct=0.0) == 0.0


def test_return_over_volatility_is_sharpe_like_ratio():
    assert return_over_volatility(total_return=0.10, vol_pct=0.05) == pytest.approx(2.0)


def _kline(symbol: str, close: float, ts: int) -> MarketEvent:
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


def test_buy_and_hold_equity_curve_tracks_price_change_from_first_close():
    events = [_kline("BTCUSDT", 100.0, 60_000), _kline("BTCUSDT", 110.0, 120_000)]
    curve = buy_and_hold_equity_curve(events, initial_capital=1000.0)
    assert curve == [(60_000, pytest.approx(1000.0)), (120_000, pytest.approx(1100.0))]


def test_buy_and_hold_equity_curve_is_empty_with_no_kline_events():
    assert buy_and_hold_equity_curve([], initial_capital=1000.0) == []


def test_flat_equity_curve_holds_initial_capital_constant():
    events = [_kline("BTCUSDT", 100.0, 60_000), _kline("BTCUSDT", 110.0, 120_000)]
    curve = flat_equity_curve(events, initial_capital=1000.0)
    assert curve == [(60_000, 1000.0), (120_000, 1000.0)]


def test_compute_metrics_populates_risk_adjusted_fields_from_initial_capital():
    equity_curve = [(0, 1000.0), (1, 1100.0), (2, 1250.0)]
    metrics = compute_metrics([], equity_curve, initial_capital=1000.0)
    assert metrics.total_return_pct == pytest.approx(0.25)
    assert metrics.volatility_pct > 0.0
    # Monotonically increasing equity -> zero drawdown with a positive return -> inf, same
    # convention as profit_factor's own no-losses case.
    assert metrics.return_over_drawdown == float("inf")


def test_compute_metrics_persists_the_equity_curve_instead_of_discarding_it():
    equity_curve = [(0, 1000.0), (1, 1100.0)]
    metrics = compute_metrics([], equity_curve, initial_capital=1000.0)
    assert metrics.equity_curve == equity_curve


def test_exposure_pct_is_fraction_of_span_with_an_open_position():
    equity_curve = [(0, 1000.0), (100, 1000.0)]  # 100ms total span
    trades = [_trade(5, entry_ts=0, exit_ts=40)]  # 40ms in position
    assert exposure_pct(trades, equity_curve) == pytest.approx(0.4)


def test_exposure_pct_sums_multiple_non_overlapping_trades():
    equity_curve = [(0, 1000.0), (100, 1000.0)]
    trades = [_trade(5, entry_ts=0, exit_ts=20), _trade(3, entry_ts=50, exit_ts=70)]
    assert exposure_pct(trades, equity_curve) == pytest.approx(0.4)


def test_exposure_pct_is_zero_with_no_trades():
    equity_curve = [(0, 1000.0), (100, 1000.0)]
    assert exposure_pct([], equity_curve) == 0.0


def test_exposure_pct_is_zero_with_no_equity_curve():
    assert exposure_pct([_trade(5, entry_ts=0, exit_ts=40)], []) == 0.0


def test_exposure_pct_is_capped_at_one():
    equity_curve = [(0, 1000.0), (10, 1000.0)]
    trades = [_trade(5, entry_ts=0, exit_ts=1000)]  # far exceeds the curve's own span
    assert exposure_pct(trades, equity_curve) == pytest.approx(1.0)
