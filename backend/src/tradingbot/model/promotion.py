"""Model promotion — spec 04 / spec 07.

A candidate model is promoted only if it beats the current baseline strategy on every
out-of-sample walk-forward fold, running through the exact same event-driven engine,
cost model, and risk rules used everywhere else in the system. Winning on average across
folds is not enough — spec 07 explicitly calls out checking for degradation concentrated
in a single market regime, which an aggregate metric would hide.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.backtesting.costs import FeeModel, SlippageModel
from tradingbot.backtesting.engine import BacktestEngine
from tradingbot.backtesting.metrics import BacktestMetrics, compute_metrics
from tradingbot.backtesting.strategy import Strategy
from tradingbot.ingestion.schema import MarketEvent
from tradingbot.risk.manager import RiskConfig


@dataclass(frozen=True)
class PromotionCriteria:
    min_trades: int = 20
    min_profit_factor_improvement: float = 0.0
    max_drawdown_regression_pct: float = 0.0


@dataclass(frozen=True)
class FoldResult:
    fold_index: int
    candidate_metrics: BacktestMetrics
    baseline_metrics: BacktestMetrics
    candidate_wins: bool
    reason: str


def run_backtest(
    strategy: Strategy,
    events: list[MarketEvent],
    initial_capital: float = 10_000.0,
    warmup_events: list[MarketEvent] | None = None,
) -> BacktestMetrics:
    engine = BacktestEngine(
        strategy=strategy,
        risk_config=RiskConfig(),
        fee_model=FeeModel(),
        slippage_model=SlippageModel(),
        initial_capital=initial_capital,
    )
    if warmup_events:
        engine.warm_up(warmup_events)
    engine.run(events)
    return compute_metrics(engine.trades, engine.equity_curve)


def evaluate_fold(
    fold_index: int,
    candidate_strategy: Strategy,
    baseline_strategy: Strategy,
    events: list[MarketEvent],
    criteria: PromotionCriteria,
    warmup_events: list[MarketEvent] | None = None,
) -> FoldResult:
    candidate_metrics = run_backtest(candidate_strategy, events, warmup_events=warmup_events)
    baseline_metrics = run_backtest(baseline_strategy, events, warmup_events=warmup_events)

    if candidate_metrics.num_trades < criteria.min_trades:
        return FoldResult(
            fold_index, candidate_metrics, baseline_metrics, False,
            f"amostra insuficiente ({candidate_metrics.num_trades} trades < {criteria.min_trades})",
        )

    if candidate_metrics.profit_factor <= baseline_metrics.profit_factor + criteria.min_profit_factor_improvement:
        return FoldResult(
            fold_index, candidate_metrics, baseline_metrics, False,
            f"profit factor ({candidate_metrics.profit_factor:.2f}) não superou o baseline "
            f"({baseline_metrics.profit_factor:.2f})",
        )

    if candidate_metrics.max_drawdown_pct > baseline_metrics.max_drawdown_pct + criteria.max_drawdown_regression_pct:
        return FoldResult(
            fold_index, candidate_metrics, baseline_metrics, False,
            f"drawdown máximo ({candidate_metrics.max_drawdown_pct:.1%}) pior que o baseline "
            f"({baseline_metrics.max_drawdown_pct:.1%})",
        )

    return FoldResult(fold_index, candidate_metrics, baseline_metrics, True, "supera o baseline")


def decide_promotion(fold_results: list[FoldResult]) -> bool:
    """Promotion requires the candidate to win in every fold, not just on average."""
    return bool(fold_results) and all(r.candidate_wins for r in fold_results)
