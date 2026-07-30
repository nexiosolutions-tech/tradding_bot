import pytest

from tradingbot.backtesting.engine import ClosedTrade
from tradingbot.backtesting.metrics import max_drawdown, profit_factor, win_rate


def _trade(pnl: float) -> ClosedTrade:
    return ClosedTrade(
        symbol="BTCUSDT",
        entry_ts=0,
        exit_ts=0,
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
