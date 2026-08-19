"""Backtest metrics — spec 07. All money-related; each has a unit test."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from tradingbot.backtesting.engine import ClosedTrade
from tradingbot.ingestion.schema import EventType, MarketEvent


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
    # Risk-adjusted fields (2026-08-19, statistical-rigor thread) — a raw return or profit
    # factor can't be compared against a benchmark on its own; ret/dd and ret/vol let
    # candidate, buy-and-hold and flat all be judged on the same footing instead of just
    # "did it make more money" (see buy_and_hold_equity_curve/flat_equity_curve below).
    total_return_pct: float = 0.0
    volatility_pct: float = 0.0
    return_over_drawdown: float = 0.0
    return_over_volatility: float = 0.0
    # Fraction of the backtest's wall-clock span spent with an open position — a candidate
    # beating (or losing to) buy-and-hold is partly explained by how much of the period it
    # was even exposed to price risk, not just by strategy skill (2026-08-19).
    exposure_pct: float = 0.0
    # Persisted, not discarded (2026-08-19) — DSR/PBO (specs/11 fila estatística) need the
    # per-fold return series, not just the aggregate scalars above, and it was already being
    # computed here (volatility_pct) and thrown away before this field existed.
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    # Exposed directly (2026-08-19), not just folded into profit_factor's ratio — needed to
    # aggregate profit factor correctly *across* folds/runs (sum of gross_profit over sum of
    # gross_loss, never a mean of per-fold ratios — see profit_factor's own docstring below)
    # and to gate a fold with zero losing trades explicitly (model/promotion.py) instead of
    # letting it slip through as an accidentally-infinite profit_factor.
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    pnl_by_hour: dict[int, float] = field(default_factory=dict)
    pnl_by_weekday: dict[int, float] = field(default_factory=dict)


def win_rate(trades: list[ClosedTrade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def gross_profit(trades: list[ClosedTrade]) -> float:
    return sum(t.pnl for t in trades if t.pnl > 0)


def gross_loss(trades: list[ClosedTrade]) -> float:
    return sum(-t.pnl for t in trades if t.pnl < 0)


def profit_factor(trades: list[ClosedTrade]) -> float:
    """gross_loss == 0 (no losing trades in the sample) returns inf by the standard
    literature convention — not a bug, but a degenerate case a caller must not treat as
    strong evidence: a handful of winning trades with zero losses is far more likely to be
    a small, lucky sample than a real edge (2026-08-19 finding — model/promotion.py's
    evaluate_fold rejects a fold in exactly this state instead of letting an accidental
    inf sail through every downstream comparison). Also never average this across
    folds/runs — mean of ratios is not the profit factor of the combined sample; aggregate
    as sum(gross_profit(...) for each) / sum(gross_loss(...) for each) instead."""
    profit = gross_profit(trades)
    loss = gross_loss(trades)
    if loss == 0:
        return float("inf") if profit > 0 else 0.0
    return profit / loss


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


def total_return_pct(equity_curve: list[tuple[int, float]], initial_capital: float) -> float:
    if not equity_curve or initial_capital <= 0:
        return 0.0
    return (equity_curve[-1][1] - initial_capital) / initial_capital


def volatility_pct(equity_curve: list[tuple[int, float]]) -> float:
    """Population stdev of bar-to-bar equity returns — how bumpy the path to
    total_return_pct was, not just where it ended up."""
    if len(equity_curve) < 2:
        return 0.0
    returns = [
        (curr - prev) / prev
        for (_, prev), (_, curr) in zip(equity_curve, equity_curve[1:])
        if prev > 0
    ]
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return variance**0.5


def _ratio_or_inf(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return float("inf") if numerator > 0 else 0.0
    return numerator / denominator


def return_over_drawdown(total_return: float, max_dd_pct: float) -> float:
    """Calmar-like ratio — same inf/0 convention as profit_factor above for the
    no-drawdown edge case."""
    return _ratio_or_inf(total_return, max_dd_pct)


def return_over_volatility(total_return: float, vol_pct: float) -> float:
    """Sharpe-like ratio without a risk-free rate — valid for comparing candidate vs.
    benchmarks over the identical period, not as a standalone absolute figure. Computed
    from bar-to-bar volatility (whatever candle_minutes the caller used), not annualized —
    not comparable to a published annualized Sharpe without that conversion."""
    return _ratio_or_inf(total_return, vol_pct)


def exposure_pct(trades: list[ClosedTrade], equity_curve: list[tuple[int, float]]) -> float:
    """Fraction of the equity curve's wall-clock span spent with an open position. Only
    meaningful for strategies that report ClosedTrade objects — buy-and-hold (always
    exposed) and flat (never exposed) aren't, so callers comparing against those benchmarks
    report exposure for them directly (1.0 / 0.0 by definition) rather than through this
    function."""
    if not equity_curve:
        return 0.0
    total_span = equity_curve[-1][0] - equity_curve[0][0]
    if total_span <= 0:
        return 0.0
    time_in_position = sum(max(0, t.exit_ts - t.entry_ts) for t in trades)
    return min(1.0, time_in_position / total_span)


def buy_and_hold_equity_curve(
    events: list[MarketEvent], initial_capital: float = 10_000.0
) -> list[tuple[int, float]]:
    """Mark-to-market of a single buy at the first close, held through the last — same
    (ts, equity) shape as BacktestEngine.equity_curve, so it runs through the identical
    compute_metrics math as any real strategy: apples-to-apples, not a separate formula."""
    closes = [(e.exchange_ts, float(e.payload["close"])) for e in events if e.event_type is EventType.KLINE]
    if not closes:
        return []
    entry_price = closes[0][1]
    if entry_price <= 0:
        return []
    return [(ts, initial_capital * (close / entry_price)) for ts, close in closes]


def flat_equity_curve(events: list[MarketEvent], initial_capital: float = 10_000.0) -> list[tuple[int, float]]:
    """The trivial "do nothing" baseline — a candidate that can't beat holding cash net of
    costs has no edge worth deploying, regardless of what it beats RsiBollingerPlaceholderStrategy by."""
    return [(e.exchange_ts, initial_capital) for e in events if e.event_type is EventType.KLINE]


def compute_metrics(
    trades: list[ClosedTrade],
    equity_curve: list[tuple[int, float]],
    initial_capital: float = 10_000.0,
) -> BacktestMetrics:
    dd = max_drawdown(equity_curve)
    ret = total_return_pct(equity_curve, initial_capital)
    vol = volatility_pct(equity_curve)
    return BacktestMetrics(
        num_trades=len(trades),
        win_rate=win_rate(trades),
        profit_factor=profit_factor(trades),
        total_pnl=sum(t.pnl for t in trades),
        total_fees=sum(t.fees_paid for t in trades),
        max_drawdown_pct=dd.max_drawdown_pct,
        max_drawdown_duration_ms=dd.max_drawdown_duration_ms,
        total_return_pct=ret,
        volatility_pct=vol,
        return_over_drawdown=return_over_drawdown(ret, dd.max_drawdown_pct),
        return_over_volatility=return_over_volatility(ret, vol),
        exposure_pct=exposure_pct(trades, equity_curve),
        equity_curve=list(equity_curve),
        gross_profit=gross_profit(trades),
        gross_loss=gross_loss(trades),
        pnl_by_hour=pnl_by_hour(trades),
        pnl_by_weekday=pnl_by_weekday(trades),
    )
