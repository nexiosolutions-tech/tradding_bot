"""Shared walk-forward evaluation — spec 04/07. Extracted from what train_model.py and
sweep_thresholds.py each implemented separately (near-identical fold loops) so the Fase 5
agentic loop (spec 09) has a single, already-tested function to call as a tool, instead of
a third copy of the same wiring.
"""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy
from tradingbot.ingestion.schema import MarketEvent
from tradingbot.model.dataset import TargetConfig, build_dataset
from tradingbot.model.promotion import PromotionCriteria, evaluate_fold
from tradingbot.model.strategy import ModelStrategy, RegimeFilteredStrategy, choose_regime_threshold
from tradingbot.model.training import ModelConfig, choose_thresholds, split_fit_calibration, train_model, walk_forward_splits

WARMUP_PREFIX_BARS = 40
STOP_LOSS_PCT = 0.015  # same as the Fase 1 placeholder, for a fair cost/risk comparison


def _events_in_ts_range(events: list[MarketEvent], start_ts: int, end_ts: int) -> list[MarketEvent]:
    return [e for e in events if start_ts <= e.exchange_ts <= end_ts]


def _warmup_prefix(events: list[MarketEvent], before_ts: int, n: int = WARMUP_PREFIX_BARS) -> list[MarketEvent]:
    prior = [e for e in events if e.exchange_ts < before_ts]
    return prior[-n:]


@dataclass(frozen=True)
class FoldSummary:
    fold_index: int
    profit_factor: float
    num_trades: int
    max_drawdown_pct: float
    won: bool
    reason: str


@dataclass(frozen=True)
class ConfigEvaluation:
    horizon_minutes: int
    entry_percentile: float
    move_threshold_pct: float
    move_threshold_atr_multiple: float | None
    use_regime_filter: bool
    label_rate: float
    folds: tuple[FoldSummary, ...]

    @property
    def folds_won(self) -> int:
        return sum(1 for f in self.folds if f.won)

    @property
    def folds_total(self) -> int:
        return len(self.folds)

    @property
    def mean_profit_factor(self) -> float:
        return sum(f.profit_factor for f in self.folds) / len(self.folds) if self.folds else 0.0

    @property
    def min_profit_factor(self) -> float:
        return min((f.profit_factor for f in self.folds), default=0.0)


def evaluate_config(
    events: list[MarketEvent],
    horizon_minutes: int,
    entry_percentile: float,
    move_threshold_pct: float = 0.008,
    move_threshold_atr_multiple: float | None = None,
    n_splits: int = 5,
    min_trades: int = 8,
    use_regime_filter: bool = True,
    regime_calib_min_trades: int = 5,
) -> ConfigEvaluation:
    """Walk-forward-evaluates one (horizon, entry_percentile, ...) configuration end to end
    — dataset build, per-fold train/calibrate/evaluate, exactly like train_model.py's exit
    criterion, but returning structured per-fold results instead of printing/saving."""
    target_config = TargetConfig(
        horizon_minutes=horizon_minutes,
        move_threshold_pct=move_threshold_pct,
        move_threshold_atr_multiple=move_threshold_atr_multiple,
        stop_loss_pct=STOP_LOSS_PCT,
    )
    rows = build_dataset(events, target_config)
    label_rate = sum(r.label for r in rows) / len(rows) if rows else 0.0

    model_config = ModelConfig()
    criteria = PromotionCriteria(min_trades=min_trades)
    folds: list[FoldSummary] = []

    for fold_index, (train_rows, test_rows) in enumerate(walk_forward_splits(rows, n_splits=n_splits)):
        if not train_rows or not test_rows:
            continue
        fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction=0.2)
        model = train_model(fit_rows, model_config, calibration_fraction=0.2)
        entry_threshold, exit_threshold = choose_thresholds(
            model, calib_rows, entry_percentile=entry_percentile, exit_percentile=50.0
        )
        model_strategy = ModelStrategy(
            model=model, entry_threshold=entry_threshold, exit_threshold=exit_threshold, stop_loss_pct=STOP_LOSS_PCT
        )

        if use_regime_filter:
            calib_start_ts = calib_rows[0].knowledge_ts
            calib_end_ts = calib_rows[-1].knowledge_ts
            calib_events = _events_in_ts_range(events, calib_start_ts, calib_end_ts)
            calib_warmup = _warmup_prefix(events, calib_start_ts)
            min_trend_pct = choose_regime_threshold(
                model_strategy, calib_events, min_trades=regime_calib_min_trades, warmup_events=calib_warmup
            )
            candidate = RegimeFilteredStrategy(inner=model_strategy, min_trend_pct=min_trend_pct)
        else:
            candidate = model_strategy

        baseline = RsiBollingerPlaceholderStrategy(stop_loss_pct=STOP_LOSS_PCT)
        test_start_ts = test_rows[0].knowledge_ts
        test_end_ts = test_rows[-1].knowledge_ts
        fold_events = _events_in_ts_range(events, test_start_ts, test_end_ts)
        warmup_events = _warmup_prefix(events, test_start_ts)

        result = evaluate_fold(fold_index, candidate, baseline, fold_events, criteria, warmup_events=warmup_events)
        folds.append(
            FoldSummary(
                fold_index=fold_index,
                profit_factor=result.candidate_metrics.profit_factor,
                num_trades=result.candidate_metrics.num_trades,
                max_drawdown_pct=result.candidate_metrics.max_drawdown_pct,
                won=result.candidate_wins,
                reason=result.reason,
            )
        )

    return ConfigEvaluation(
        horizon_minutes=horizon_minutes,
        entry_percentile=entry_percentile,
        move_threshold_pct=move_threshold_pct,
        move_threshold_atr_multiple=move_threshold_atr_multiple,
        use_regime_filter=use_regime_filter,
        label_rate=label_rate,
        folds=tuple(folds),
    )
