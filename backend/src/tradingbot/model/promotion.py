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
    # "Beats the baseline" is not enough on its own — the Fase 1 placeholder baseline was
    # found to have structurally negative expectancy (2026-07-31), so a candidate could
    # clear the relative check above by merely being "less bad" than a broken baseline
    # while still losing money net of costs. This is an independent, absolute gate.
    min_profit_factor: float = 1.0


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
    risk_config: RiskConfig | None = None,
    reference_symbol: str | None = None,
) -> BacktestMetrics:
    engine = BacktestEngine(
        strategy=strategy,
        risk_config=risk_config or RiskConfig(),
        fee_model=FeeModel(),
        slippage_model=SlippageModel(),
        initial_capital=initial_capital,
        reference_symbol=reference_symbol,
    )
    if warmup_events:
        engine.warm_up(warmup_events)
    engine.run(events)
    return compute_metrics(engine.trades, engine.equity_curve, initial_capital=engine.initial_capital)


def evaluate_fold(
    fold_index: int,
    candidate_strategy: Strategy,
    baseline_strategy: Strategy,
    events: list[MarketEvent],
    criteria: PromotionCriteria,
    warmup_events: list[MarketEvent] | None = None,
    risk_config: RiskConfig | None = None,
    reference_symbol: str | None = None,
) -> FoldResult:
    # Both candidate and baseline run under the same risk_config/reference_symbol, same
    # reasoning as comparing them under the same fee/slippage model — an apples-to-apples
    # check of whether the candidate beats the baseline *at this configuration*. Without
    # reference_symbol threaded to the baseline too, a reference symbol's events mixed into
    # `events` would be mistaken for a second tradeable symbol under the baseline's own
    # engine (spec 03) — not just missing a feature, a real correctness bug.
    candidate_metrics = run_backtest(
        candidate_strategy, events, warmup_events=warmup_events, risk_config=risk_config, reference_symbol=reference_symbol
    )
    baseline_metrics = run_backtest(
        baseline_strategy, events, warmup_events=warmup_events, risk_config=risk_config, reference_symbol=reference_symbol
    )

    if candidate_metrics.num_trades < criteria.min_trades:
        return FoldResult(
            fold_index, candidate_metrics, baseline_metrics, False,
            f"amostra insuficiente ({candidate_metrics.num_trades} trades < {criteria.min_trades})",
        )

    # A fold with zero losing trades makes profit_factor infinite (backtesting/metrics.py)
    # — inf clears every gate below it trivially (min_profit_factor, beats-baseline,
    # drawdown), regardless of how few trades or how much luck produced it. min_trades
    # alone doesn't guarantee this can't happen: a fold with exactly min_trades winners and
    # zero losers would still pass every other check (2026-08-19 finding — confirmed by
    # code trace, not yet observed as an actual false promotion in this project, but the
    # gate must not rely on that being a coincidence). Zero losses is itself insufficient
    # evidence of a real edge — no risk-side variance was ever observed — so it's rejected
    # explicitly here, independent of trade count.
    if candidate_metrics.num_trades > 0 and candidate_metrics.gross_loss == 0:
        return FoldResult(
            fold_index, candidate_metrics, baseline_metrics, False,
            f"fold sem nenhuma perda ({candidate_metrics.num_trades} trades, todos "
            "vencedores) — profit factor infinito não é evidência confiável sem "
            "nenhuma perda observada",
        )

    if candidate_metrics.profit_factor < criteria.min_profit_factor:
        return FoldResult(
            fold_index, candidate_metrics, baseline_metrics, False,
            f"expectância líquida do candidato não é positiva (profit factor "
            f"{candidate_metrics.profit_factor:.2f} < {criteria.min_profit_factor:.2f}) — "
            "não basta ser 'menos ruim' que o baseline",
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
