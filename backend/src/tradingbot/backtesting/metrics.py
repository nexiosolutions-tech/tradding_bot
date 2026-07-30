"""Backtest metrics — spec 07. All money-related; each has a unit test."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from tradingbot.backtesting.engine import ClosedTrade


@dataclass(frozen=True)
class DrawdownResult:
    max_drawdown_pct: float
    max_drawdown_duration_ms: int


@dataclass(frozen=True)
class BacktestMetrics:
    num_trades: int
    win_rate: float
    profit_factor: float
    total_pnl: float
    total_fees: float
    max_drawdown_pct: float
    max_drawdown_duration_ms: int
    pnl_by_hour: dict[int, float] = field(default_factory=dict)
    pnl_by_weekday: dict[int, float] = field(default_factory=dict)


def win_rate(trades: list[ClosedTrade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def profit_factor(trades: list[ClosedTrade]) -> float:
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = sum(-t.pnl for t in trades if t.pnl < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def max_drawdown(equity_curve: list[tuple[int, float]]) -> DrawdownResult:
    if not equity_curve:
        return DrawdownResult(0.0, 0)

    peak = equity_curve[0][1]
    peak_ts = equity_curve[0][0]
    max_dd_pct = 0.0
    max_dd_duration = 0

    for ts, equity in equity_curve:
        if equity >= peak:
            peak = equity
            peak_ts = ts
        else:
            dd_pct = (peak - equity) / peak if peak > 0 else 0.0
            max_dd_pct = max(max_dd_pct, dd_pct)
            max_dd_duration = max(max_dd_duration, ts - peak_ts)

    return DrawdownResult(max_dd_pct, max_dd_duration)


def pnl_by_hour(trades: list[ClosedTrade]) -> dict[int, float]:
    result: dict[int, float] = {}
    for t in trades:
        hour = datetime.fromtimestamp(t.exit_ts / 1000, tz=timezone.utc).hour
        result[hour] = result.get(hour, 0.0) + t.pnl
    return result


def pnl_by_weekday(trades: list[ClosedTrade]) -> dict[int, float]:
    result: dict[int, float] = {}
    for t in trades:
        weekday = datetime.fromtimestamp(t.exit_ts / 1000, tz=timezone.utc).weekday()
        result[weekday] = result.get(weekday, 0.0) + t.pnl
    return result


def compute_metrics(trades: list[ClosedTrade], equity_curve: list[tuple[int, float]]) -> BacktestMetrics:
    dd = max_drawdown(equity_curve)
    return BacktestMetrics(
        num_trades=len(trades),
        win_rate=win_rate(trades),
        profit_factor=profit_factor(trades),
        total_pnl=sum(t.pnl for t in trades),
        total_fees=sum(t.fees_paid for t in trades),
        max_drawdown_pct=dd.max_drawdown_pct,
        max_drawdown_duration_ms=dd.max_drawdown_duration_ms,
        pnl_by_hour=pnl_by_hour(trades),
        pnl_by_weekday=pnl_by_weekday(trades),
    )
