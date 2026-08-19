"""Shared walk-forward evaluation — spec 04/07. Extracted from what train_model.py and
sweep_thresholds.py each implemented separately (near-identical fold loops) so the Fase 5
agentic loop (spec 09) has a single, already-tested function to call as a tool, instead of
a third copy of the same wiring.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace

from tradingbot.backtesting.strategy import RsiBollingerPlaceholderStrategy
from tradingbot.ingestion.schema import MarketEvent
from tradingbot.model.dataset import DatasetRow, TargetConfig, build_dataset
from tradingbot.model.promotion import PromotionCriteria, evaluate_fold
from tradingbot.model.strategy import ModelStrategy, RegimeFilteredStrategy, choose_regime_threshold
from tradingbot.model.training import ModelConfig, choose_thresholds, split_fit_calibration, train_model, walk_forward_splits
from tradingbot.risk.manager import RiskConfig

WARMUP_PREFIX_BARS = 40
STOP_LOSS_PCT = 0.015  # default — same as the Fase 1 placeholder, for a fair cost/risk
# comparison. Overridable via evaluate_config's stop_loss_pct param (spec 13) for risk
# profile comparisons; this module constant is only the default when not overridden.


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
    # Persisted, not discarded (2026-08-19) — DSR/PBO (specs/11 fila estatística) need the
    # per-fold return series, not just the aggregate scalars above; it was already computed
    # inside compute_metrics (BacktestMetrics.equity_curve) and thrown away before this field
    # existed.
    equity_curve: list[tuple[int, float]] = field(default_factory=list)


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


def _with_shuffled_labels(rows: list[DatasetRow], seed: int) -> list[DatasetRow]:
    """Permutes labels across rows — the multiset (and therefore label_rate) is unchanged,
    only which row each label lands on. Used by the nullity test (specs/11,
    statistical-rigor thread): if the harness has no leak, training on this should find no
    real edge in any fold, since the label carries no information about that row's
    features anymore."""
    labels = [row.label for row in rows]
    random.Random(seed).shuffle(labels)
    return [replace(row, label=label) for row, label in zip(rows, labels)]


def evaluate_config(
    events: list[MarketEvent],
    horizon_minutes: int,
    entry_percentile: float,
    move_threshold_pct: float = 0.008,
    move_threshold_atr_multiple: float | None = None,
    n_splits: int = 5,
    candle_minutes: int = 1,
    min_trades: int = 8,
    use_regime_filter: bool = True,
    regime_calib_min_trades: int = 5,
    stop_loss_pct: float = STOP_LOSS_PCT,
    risk_config: RiskConfig | None = None,
    feature_names: tuple[str, ...] | None = None,
    reference_symbol: str | None = None,
    shuffle_labels: bool = False,
    shuffle_seed: int = 0,
) -> ConfigEvaluation:
    """Walk-forward-evaluates one (horizon, entry_percentile, ...) configuration end to end
    — dataset build, per-fold train/calibrate/evaluate, exactly like train_model.py's exit
    criterion, but returning structured per-fold results instead of printing/saving.
    candle_minutes must match the actual interval of `events` (e.g. 5 for 5-minute klines)
    — it's what converts horizon_minutes (wall-clock) into horizon_bars (candle count);
    left at the wrong value, horizon_minutes silently means the wrong amount of real time.
    stop_loss_pct/risk_config default to the values validated in every prior round (specs/11)
    — pass different ones to compare risk profiles (spec 13); candidate and baseline always
    run under the identical risk_config, for an apples-to-apples comparison.
    feature_names/reference_symbol default to None, preserving build_dataset's/train_model's
    own single-symbol defaults — pass feature_names=CROSS_ASSET_FEATURE_NAMES and
    reference_symbol="ETHUSDT" (with events merged from both symbols) for the cross-asset
    comparison (spec 03, 14ª rodada). shuffle_labels=True (default False) runs this exact
    same pipeline — same events, same folds, same training/calibration/backtest — with real
    triple-barrier labels replaced by a permutation of themselves, for the nullity test
    (specs/11): expected result is folds_won == 0; any fold won is evidence the harness is
    leaking information, not evidence of a lucky model."""
    target_config = TargetConfig(
        horizon_minutes=horizon_minutes,
        candle_minutes=candle_minutes,
        move_threshold_pct=move_threshold_pct,
        move_threshold_atr_multiple=move_threshold_atr_multiple,
        stop_loss_pct=stop_loss_pct,
    )
    dataset_kwargs = {} if feature_names is None else {"required_features": feature_names}
    rows = build_dataset(events, target_config, reference_symbol=reference_symbol, **dataset_kwargs)
    if shuffle_labels:
        rows = _with_shuffled_labels(rows, shuffle_seed)
    label_rate = sum(r.label for r in rows) / len(rows) if rows else 0.0

    model_config = ModelConfig()
    criteria = PromotionCriteria(min_trades=min_trades)
    folds: list[FoldSummary] = []
    model_feature_names = (
        None if feature_names is None else tuple(n for n in feature_names if n != "trend_regime_pct")
    )
    train_kwargs = {} if model_feature_names is None else {"feature_names": model_feature_names}

    for fold_index, (train_rows, test_rows) in enumerate(walk_forward_splits(rows, n_splits=n_splits)):
        if not train_rows or not test_rows:
            continue
        fit_rows, calib_rows = split_fit_calibration(train_rows, calibration_fraction=0.2)
        model = train_model(fit_rows, model_config, calibration_fraction=0.2, **train_kwargs)
        entry_threshold, exit_threshold = choose_thresholds(
            model, calib_rows, entry_percentile=entry_percentile, exit_percentile=50.0
        )
        model_strategy = ModelStrategy(
            model=model, entry_threshold=entry_threshold, exit_threshold=exit_threshold, stop_loss_pct=stop_loss_pct
        )

        if use_regime_filter:
            calib_start_ts = calib_rows[0].knowledge_ts
            calib_end_ts = calib_rows[-1].knowledge_ts
            calib_events = _events_in_ts_range(events, calib_start_ts, calib_end_ts)
            calib_warmup = _warmup_prefix(events, calib_start_ts)
            min_trend_pct = choose_regime_threshold(
                model_strategy,
                calib_events,
                min_trades=regime_calib_min_trades,
                warmup_events=calib_warmup,
                risk_config=risk_config,
                reference_symbol=reference_symbol,
            )
            candidate = RegimeFilteredStrategy(inner=model_strategy, min_trend_pct=min_trend_pct)
        else:
            candidate = model_strategy

        baseline = RsiBollingerPlaceholderStrategy(stop_loss_pct=stop_loss_pct)
        test_start_ts = test_rows[0].knowledge_ts
        test_end_ts = test_rows[-1].knowledge_ts
        fold_events = _events_in_ts_range(events, test_start_ts, test_end_ts)
        warmup_events = _warmup_prefix(events, test_start_ts)

        result = evaluate_fold(
            fold_index,
            candidate,
            baseline,
            fold_events,
            criteria,
            warmup_events=warmup_events,
            risk_config=risk_config,
            reference_symbol=reference_symbol,
        )
        folds.append(
            FoldSummary(
                fold_index=fold_index,
                profit_factor=result.candidate_metrics.profit_factor,
                num_trades=result.candidate_metrics.num_trades,
                max_drawdown_pct=result.candidate_metrics.max_drawdown_pct,
                won=result.candidate_wins,
                reason=result.reason,
                equity_curve=result.candidate_metrics.equity_curve,
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


@dataclass(frozen=True)
class NullityTestResult:
    real_mean_profit_factor: float
    real_folds_won: int
    real_folds_total: int
    permuted_mean_profit_factors: tuple[float, ...]
    # Empirical permutation-test p-value: fraction of permuted runs whose mean_profit_factor
    # matched or beat the real one, with the standard +1/+1 correction (Davison & Hinkley,
    # 1997) so a small n_permutations never overclaims an exact p=0.0.
    p_value: float

    @property
    def n_permutations(self) -> int:
        return len(self.permuted_mean_profit_factors)


def run_nullity_test(
    events: list[MarketEvent],
    horizon_minutes: int,
    entry_percentile: float,
    n_permutations: int = 30,
    base_seed: int = 0,
    **evaluate_config_kwargs,
) -> NullityTestResult:
    """Nullity test (specs/07/11, statistical-rigor thread, 2026-08-19): a single
    shuffle_labels seed only tells you whether that one permutation happened to look
    like an edge — it says nothing about whether the real result is typical or a fluke of
    the whole family of permutations. Runs evaluate_config once for real and
    n_permutations times with shuffle_labels=True (different shuffle_seed each time,
    base_seed..base_seed+n_permutations-1) to build the null distribution of
    mean_profit_factor, then reports where the real result falls in it as an empirical
    p-value. A useful side effect: this null distribution is a cheap approximation of what
    a proper Deflated Sharpe Ratio will give later (same question — "how good is this
    number against what chance produces on this exact pipeline and data" — without DSR's
    own implementation cost).

    evaluate_config_kwargs forwards every other evaluate_config parameter (n_splits,
    min_trades, move_threshold_pct, ...) unchanged to both the real and every permuted run,
    so the only difference between them is the label permutation. Must not include
    shuffle_labels/shuffle_seed — this function owns both."""
    if "shuffle_labels" in evaluate_config_kwargs or "shuffle_seed" in evaluate_config_kwargs:
        raise ValueError("run_nullity_test manages shuffle_labels/shuffle_seed itself")

    real = evaluate_config(events, horizon_minutes, entry_percentile, **evaluate_config_kwargs)
    permuted_pfs = [
        evaluate_config(
            events,
            horizon_minutes,
            entry_percentile,
            shuffle_labels=True,
            shuffle_seed=base_seed + i,
            **evaluate_config_kwargs,
        ).mean_profit_factor
        for i in range(n_permutations)
    ]

    at_least_as_good = sum(1 for pf in permuted_pfs if pf >= real.mean_profit_factor)
    p_value = (at_least_as_good + 1) / (n_permutations + 1)

    return NullityTestResult(
        real_mean_profit_factor=real.mean_profit_factor,
        real_folds_won=real.folds_won,
        real_folds_total=real.folds_total,
        permuted_mean_profit_factors=tuple(permuted_pfs),
        p_value=p_value,
    )
